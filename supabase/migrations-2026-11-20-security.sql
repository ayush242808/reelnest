-- ReelNest security + sync hardening migration (2026-11-20).
-- Additive and data-preserving: no table is dropped, truncated or rewritten, no user row is changed.
-- Rollback: supabase/migrations-2026-11-20-security.rollback.sql
begin;

-- 1. Least privilege on the ReelNest tables --------------------------------------------------------
-- The app (through RLS-protected RPCs that run as the caller) needs SELECT/INSERT/UPDATE/DELETE only.
-- TRUNCATE ignores RLS, so it must never be held by API roles. TRIGGER/REFERENCES/MAINTAIN aren't needed.
do $$
declare t text;
        extra text := case when current_setting('server_version_num')::int >= 170000 then ', maintain' else '' end;
begin
  foreach t in array array['rn_works','rn_episodes','rn_states','rn_events','rn_tombstones','rn_settings'] loop
    execute format('revoke all on public.%I from anon', t);
    execute format('revoke truncate, references, trigger%s on public.%I from authenticated, service_role', extra, t);
    execute format('grant select, insert, update, delete on public.%I to authenticated', t);
  end loop;
  -- New tables created by the dashboard/SQL role in public must not hand API roles TRUNCATE & co. again.
  execute format('alter default privileges for role postgres in schema public revoke truncate, references, trigger%s on tables from anon, authenticated, service_role', extra);
end $$;
revoke all on sequence public.rn_rev from anon;
grant usage on sequence public.rn_rev to authenticated; -- needed by column defaults and the rev trigger


-- 2. Commit-safe change cursor ------------------------------------------------------------------------
-- rev comes from a sequence, so a transaction can take a lower rev but commit after a pull that already
-- moved past it. Each row now also records the transaction that last wrote it; rn_pull_since returns
-- rows written by any transaction not yet finished at the previous pull, so no commit is ever skipped.
alter table public.rn_works      add column if not exists txid xid8 not null default pg_current_xact_id();
alter table public.rn_episodes   add column if not exists txid xid8 not null default pg_current_xact_id();
alter table public.rn_states     add column if not exists txid xid8 not null default pg_current_xact_id();
alter table public.rn_events     add column if not exists txid xid8 not null default pg_current_xact_id();
alter table public.rn_tombstones add column if not exists txid xid8 not null default pg_current_xact_id();
alter table public.rn_settings   add column if not exists txid xid8 not null default pg_current_xact_id();
create index if not exists rn_works_txid      on public.rn_works (user_id, txid);
create index if not exists rn_episodes_txid   on public.rn_episodes (user_id, txid);
create index if not exists rn_states_txid     on public.rn_states (user_id, txid);
create index if not exists rn_events_txid     on public.rn_events (user_id, txid);
create index if not exists rn_tombstones_txid on public.rn_tombstones (user_id, txid);

-- Trigger function: fixed empty search_path, schema-qualified objects, not callable by API roles.
create or replace function public.rn_bump_rev() returns trigger
language plpgsql set search_path = '' as $$
begin
  new.rev := nextval('public.rn_rev'::regclass);
  new.txid := pg_current_xact_id();
  return new;
end $$;
revoke all on function public.rn_bump_rev() from public, anon, authenticated;

-- 3. Push: device clocks can't win the future ------------------------------------------------------
-- Same per-field last-writer-wins as before, but any client timestamp more than 5 minutes ahead of
-- the server clock is clamped, so a device with a wrong clock can't make its edits unbeatable.
-- NOTE: LEAST() ignores NULLs, so a NULL deleted_at must stay NULL explicitly (NULL means "not deleted").
create or replace function public.rn_push(payload jsonb) returns bigint
language plpgsql security invoker set search_path = '' as $$
declare uid uuid := auth.uid();
        lim bigint := (extract(epoch from clock_timestamp()) * 1000)::bigint + 300000;
begin
  if uid is null then raise exception 'not signed in'; end if;

  insert into public.rn_works (user_id, id, body, updated_at)
  select uid, x.id, x.body, least(coalesce(x.updated_at, 0), lim)
  from jsonb_to_recordset(coalesce(payload->'works', '[]')) as x(id text, body jsonb, updated_at bigint)
  on conflict (user_id, id) do update set body = excluded.body, updated_at = excluded.updated_at
  where excluded.updated_at > public.rn_works.updated_at;

  insert into public.rn_episodes (user_id, id, work_id, body, updated_at, deleted)
  select uid, x.id, x.work_id, x.body, least(coalesce(x.updated_at, 0), lim), coalesce(x.deleted, false)
  from jsonb_to_recordset(coalesce(payload->'episodes', '[]')) as x(id text, work_id text, body jsonb, updated_at bigint, deleted boolean)
  on conflict (user_id, id) do update set body = excluded.body, updated_at = excluded.updated_at, deleted = excluded.deleted, work_id = excluded.work_id
  where excluded.updated_at > public.rn_episodes.updated_at;

  insert into public.rn_states as s (user_id, work_id, interest, interest_at, status, status_at, watchlist, watchlist_at,
                                     rating, rating_at, notes, notes_at, device_id, added_at)
  select uid, x.work_id, x.interest, least(coalesce(x.interest_at, 0), lim), x.status, least(coalesce(x.status_at, 0), lim), x.watchlist, least(coalesce(x.watchlist_at, 0), lim),
         x.rating, least(coalesce(x.rating_at, 0), lim), x.notes, least(coalesce(x.notes_at, 0), lim), coalesce(x.device_id, ''), coalesce(x.added_at, 0)
  from jsonb_to_recordset(coalesce(payload->'states', '[]')) as x(work_id text, interest text, interest_at bigint, status text, status_at bigint,
       watchlist boolean, watchlist_at bigint, rating int, rating_at bigint, notes text, notes_at bigint, device_id text, added_at bigint)
  on conflict (user_id, work_id) do update set
    interest     = case when excluded.interest_at  > s.interest_at  then excluded.interest  else s.interest  end,
    interest_at  = greatest(excluded.interest_at, s.interest_at),
    status       = case when excluded.status_at    > s.status_at    then excluded.status    else s.status    end,
    status_at    = greatest(excluded.status_at, s.status_at),
    watchlist    = case when excluded.watchlist_at > s.watchlist_at then excluded.watchlist else s.watchlist end,
    watchlist_at = greatest(excluded.watchlist_at, s.watchlist_at),
    rating       = case when excluded.rating_at    > s.rating_at    then excluded.rating    else s.rating    end,
    rating_at    = greatest(excluded.rating_at, s.rating_at),
    notes        = case when excluded.notes_at     > s.notes_at     then excluded.notes     else s.notes     end,
    notes_at     = greatest(excluded.notes_at, s.notes_at),
    device_id    = excluded.device_id,
    added_at     = least(nullif(excluded.added_at, 0), nullif(s.added_at, 0), greatest(excluded.added_at, s.added_at))
  where excluded.interest_at > s.interest_at or excluded.status_at > s.status_at or excluded.watchlist_at > s.watchlist_at
     or excluded.rating_at > s.rating_at or excluded.notes_at > s.notes_at;

  -- Append-only history: new ids are inserted; an existing row only ever gains a deletion.
  insert into public.rn_events as e (user_id, id, work_id, episode_id, watched_at, watched_date, is_rewatch, source, created_at, deleted_at, device_id)
  select uid, x.id, x.work_id, x.episode_id, x.watched_at, x.watched_date, coalesce(x.is_rewatch, false), x.source, least(x.created_at, lim), case when x.deleted_at is null then null else least(x.deleted_at, lim) end, coalesce(x.device_id, '')
  from jsonb_to_recordset(coalesce(payload->'events', '[]')) as x(id text, work_id text, episode_id text, watched_at bigint, watched_date text,
       is_rewatch boolean, source jsonb, created_at bigint, deleted_at bigint, device_id text)
  on conflict (user_id, id) do update set deleted_at = least(coalesce(e.deleted_at, excluded.deleted_at), excluded.deleted_at)
  where excluded.deleted_at is not null and (e.deleted_at is null or excluded.deleted_at < e.deleted_at);

  insert into public.rn_tombstones as t (user_id, entity_type, entity_id, deleted_at, device_id)
  select uid, x.entity_type, x.entity_id, least(coalesce(x.deleted_at, 0), lim), coalesce(x.device_id, '')
  from jsonb_to_recordset(coalesce(payload->'tombstones', '[]')) as x(entity_type text, entity_id text, deleted_at bigint, device_id text)
  on conflict (user_id, entity_type, entity_id) do update set deleted_at = excluded.deleted_at, device_id = excluded.device_id
  where excluded.deleted_at > t.deleted_at;

  if payload ? 'settings' and jsonb_typeof(payload->'settings') = 'object' then
    insert into public.rn_settings as st (user_id, body, updated_at)
    values (uid, payload->'settings'->'body', least((payload->'settings'->>'updated_at')::bigint, lim))
    on conflict (user_id) do update set body = excluded.body, updated_at = excluded.updated_at
    where excluded.updated_at > st.updated_at;
  end if;

  return 1;
end $$;

-- Cursor-based pull. cursor = null means "everything". Returns the next cursor to store.
create or replace function public.rn_pull_since(cursor text) returns jsonb
language plpgsql stable security invoker set search_path = '' as $$
declare uid uuid := auth.uid();
        c xid8 := coalesce(nullif(cursor, '')::xid8, '0'::xid8);
begin
  if uid is null then raise exception 'not signed in'; end if;
  return jsonb_build_object(
    'works',      coalesce((select jsonb_agg(jsonb_build_object('id', id, 'body', body, 'updated_at', updated_at)) from public.rn_works where user_id = uid and txid >= c), '[]'),
    'episodes',   coalesce((select jsonb_agg(jsonb_build_object('id', id, 'work_id', work_id, 'body', body, 'updated_at', updated_at, 'deleted', deleted)) from public.rn_episodes where user_id = uid and txid >= c), '[]'),
    'states',     coalesce((select jsonb_agg(to_jsonb(s) - 'user_id' - 'rev' - 'txid') from public.rn_states s where user_id = uid and txid >= c), '[]'),
    'events',     coalesce((select jsonb_agg(to_jsonb(e) - 'user_id' - 'rev' - 'txid') from public.rn_events e where user_id = uid and txid >= c), '[]'),
    'tombstones', coalesce((select jsonb_agg(to_jsonb(t) - 'user_id' - 'rev' - 'txid') from public.rn_tombstones t where user_id = uid and txid >= c), '[]'),
    'settings',   (select jsonb_build_object('body', body, 'updated_at', updated_at) from public.rn_settings where user_id = uid and txid >= c),
    -- Oldest transaction still running now: anything it (or a later one) writes is >= this, so it's fetched next time.
    'cursor', pg_snapshot_xmin(pg_current_snapshot())::text);
end $$;

-- The older rn_pull stays for app versions still cached on devices; give it the same fixed search_path.
alter function public.rn_pull(bigint) set search_path = '';
alter function public.rn_delete_my_data() set search_path = '';
create or replace function public.rn_pull(since bigint) returns jsonb
language sql stable security invoker set search_path = '' as $$
  select jsonb_build_object(
    'works',      coalesce((select jsonb_agg(jsonb_build_object('id', id, 'body', body, 'updated_at', updated_at)) from public.rn_works where user_id = auth.uid() and rev > since), '[]'),
    'episodes',   coalesce((select jsonb_agg(jsonb_build_object('id', id, 'work_id', work_id, 'body', body, 'updated_at', updated_at, 'deleted', deleted)) from public.rn_episodes where user_id = auth.uid() and rev > since), '[]'),
    'states',     coalesce((select jsonb_agg(to_jsonb(s) - 'user_id' - 'rev' - 'txid') from public.rn_states s where user_id = auth.uid() and rev > since), '[]'),
    'events',     coalesce((select jsonb_agg(to_jsonb(e) - 'user_id' - 'rev' - 'txid') from public.rn_events e where user_id = auth.uid() and rev > since), '[]'),
    'tombstones', coalesce((select jsonb_agg(to_jsonb(t) - 'user_id' - 'rev' - 'txid') from public.rn_tombstones t where user_id = auth.uid() and rev > since), '[]'),
    'settings',   (select jsonb_build_object('body', body, 'updated_at', updated_at) from public.rn_settings where user_id = auth.uid() and rev > since),
    'rev', greatest(since,
      coalesce((select max(rev) from public.rn_works where user_id = auth.uid()), 0),
      coalesce((select max(rev) from public.rn_episodes where user_id = auth.uid()), 0),
      coalesce((select max(rev) from public.rn_states where user_id = auth.uid()), 0),
      coalesce((select max(rev) from public.rn_events where user_id = auth.uid()), 0),
      coalesce((select max(rev) from public.rn_tombstones where user_id = auth.uid()), 0),
      coalesce((select max(rev) from public.rn_settings where user_id = auth.uid()), 0)))
$$;
create or replace function public.rn_delete_my_data() returns void
language plpgsql security invoker set search_path = '' as $$
declare uid uuid := auth.uid();
begin
  if uid is null then raise exception 'not signed in'; end if;
  delete from public.rn_events where user_id = uid;
  delete from public.rn_states where user_id = uid;
  delete from public.rn_episodes where user_id = uid;
  delete from public.rn_tombstones where user_id = uid;
  delete from public.rn_works where user_id = uid;
  delete from public.rn_settings where user_id = uid;
end $$;

revoke all on function public.rn_push(jsonb), public.rn_pull(bigint), public.rn_pull_since(text), public.rn_delete_my_data() from public, anon;
grant execute on function public.rn_push(jsonb), public.rn_pull(bigint), public.rn_pull_since(text), public.rn_delete_my_data() to authenticated;

-- 4. Shared TMDB relay: server-side rate limiting ---------------------------------------------------
-- Counters live in a schema the Data API doesn't expose. Only the service role (the relay's own server
-- credential) can call rn_relay_take; browsers and signed-in users can't.
create schema if not exists rn_private;
revoke all on schema rn_private from public, anon, authenticated;
create table if not exists rn_private.relay_hits (
  bucket text not null,
  window_start timestamptz not null,
  hits integer not null default 0,
  primary key (bucket, window_start)
);
revoke all on rn_private.relay_hits from public, anon, authenticated;

-- Returns true if the request is within limits (and counts it). p_bucket is an opaque hash, never an IP.
create or replace function public.rn_relay_take(p_bucket text, p_limit integer, p_window_seconds integer) returns boolean
language plpgsql security definer set search_path = '' as $$
declare w timestamptz := to_timestamp(floor(extract(epoch from clock_timestamp()) / p_window_seconds) * p_window_seconds);
        n integer;
begin
  if p_bucket is null or length(p_bucket) > 80 or p_limit < 1 or p_window_seconds < 1 then return false; end if;
  insert into rn_private.relay_hits as h (bucket, window_start, hits) values (p_bucket, w, 1)
  on conflict (bucket, window_start) do update set hits = h.hits + 1
  returning hits into n;
  if random() < 0.002 then delete from rn_private.relay_hits where window_start < clock_timestamp() - interval '3 days'; end if;
  return n <= p_limit;
end $$;
revoke all on function public.rn_relay_take(text, integer, integer) from public, anon, authenticated;
grant execute on function public.rn_relay_take(text, integer, integer) to service_role;

commit;
