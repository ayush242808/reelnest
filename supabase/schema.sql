-- ReelNest cloud backup schema for Supabase (PostgreSQL).
-- Paste this whole file into Supabase › SQL Editor › New query › Run. Safe to run again.
--
-- Design
--  * Every row belongs to one signed-in user (user_id = auth.uid()). Row Level Security
--    enforces this on the server: nobody can read or write anyone else's rows.
--  * Watch history is append-only. A "removed" watch keeps its row with deleted_at set,
--    so a stale device can never bring it back.
--  * Library state merges field by field (status, interest, watchlist, rating, notes each
--    keep their own timestamp), so two devices editing different fields never overwrite
--    each other. The merge happens inside rn_push, in one transaction.
--  * Deleted titles leave tombstones. Clients decide with timestamps whether a later edit
--    on another device should win over a deletion.
--  * rev is a server-assigned, increasing number used for incremental pulls.

create sequence if not exists public.rn_rev;

create table if not exists public.rn_works (
  user_id uuid not null default auth.uid() references auth.users (id) on delete cascade,
  id text not null,
  body jsonb not null,
  updated_at bigint not null,
  rev bigint not null default nextval('public.rn_rev'),
  primary key (user_id, id)
);

create table if not exists public.rn_episodes (
  user_id uuid not null default auth.uid() references auth.users (id) on delete cascade,
  id text not null,
  work_id text not null,
  body jsonb not null,
  updated_at bigint not null,
  deleted boolean not null default false,
  rev bigint not null default nextval('public.rn_rev'),
  primary key (user_id, id)
);

create table if not exists public.rn_states (
  user_id uuid not null default auth.uid() references auth.users (id) on delete cascade,
  work_id text not null,
  interest text not null, interest_at bigint not null default 0,
  status text not null, status_at bigint not null default 0,
  watchlist boolean not null default false, watchlist_at bigint not null default 0,
  rating int, rating_at bigint not null default 0,
  notes text, notes_at bigint not null default 0,
  device_id text not null default '',
  added_at bigint not null default 0,
  rev bigint not null default nextval('public.rn_rev'),
  primary key (user_id, work_id),
  constraint rn_rating_range check (rating is null or rating between 1 and 10)
);

create table if not exists public.rn_events (
  user_id uuid not null default auth.uid() references auth.users (id) on delete cascade,
  id text not null,
  work_id text not null,
  episode_id text,
  watched_at bigint not null,
  is_rewatch boolean not null default false,
  created_at bigint not null,
  deleted_at bigint,
  device_id text not null default '',
  rev bigint not null default nextval('public.rn_rev'),
  primary key (user_id, id)
);

create table if not exists public.rn_tombstones (
  user_id uuid not null default auth.uid() references auth.users (id) on delete cascade,
  entity_type text not null,
  entity_id text not null,
  deleted_at bigint not null,
  device_id text not null default '',
  rev bigint not null default nextval('public.rn_rev'),
  primary key (user_id, entity_type, entity_id)
);

create table if not exists public.rn_settings (
  user_id uuid primary key default auth.uid() references auth.users (id) on delete cascade,
  body jsonb not null,
  updated_at bigint not null,
  rev bigint not null default nextval('public.rn_rev')
);

create index if not exists rn_works_rev on public.rn_works (user_id, rev);
create index if not exists rn_episodes_rev on public.rn_episodes (user_id, rev);
create index if not exists rn_states_rev on public.rn_states (user_id, rev);
create index if not exists rn_events_rev on public.rn_events (user_id, rev);
create index if not exists rn_tombstones_rev on public.rn_tombstones (user_id, rev);

-- Any update gets a fresh rev so other devices see it on their next pull.
create or replace function public.rn_bump_rev() returns trigger language plpgsql as $$
begin
  new.rev := nextval('public.rn_rev');
  return new;
end $$;

do $$
declare t text;
begin
  foreach t in array array['rn_works','rn_episodes','rn_states','rn_events','rn_tombstones','rn_settings'] loop
    execute format('drop trigger if exists %I_bump on public.%I', t, t);
    execute format('create trigger %I_bump before update on public.%I for each row execute function public.rn_bump_rev()', t, t);
    execute format('alter table public.%I enable row level security', t);
    execute format('drop policy if exists "own rows" on public.%I', t);
    execute format('create policy "own rows" on public.%I for all to authenticated using (user_id = auth.uid()) with check (user_id = auth.uid())', t);
    execute format('revoke all on public.%I from anon', t);
    execute format('grant select, insert, update, delete on public.%I to authenticated', t);
  end loop;
end $$;

grant usage on sequence public.rn_rev to authenticated;

-- Push a batch of local changes. Runs as the calling user, so RLS still applies.
create or replace function public.rn_push(payload jsonb) returns bigint
language plpgsql security invoker set search_path = public as $$
declare uid uuid := auth.uid();
begin
  if uid is null then raise exception 'not signed in'; end if;

  insert into rn_works (user_id, id, body, updated_at)
  select uid, x.id, x.body, x.updated_at
  from jsonb_to_recordset(coalesce(payload->'works', '[]')) as x(id text, body jsonb, updated_at bigint)
  on conflict (user_id, id) do update set body = excluded.body, updated_at = excluded.updated_at
  where excluded.updated_at > rn_works.updated_at;

  insert into rn_episodes (user_id, id, work_id, body, updated_at, deleted)
  select uid, x.id, x.work_id, x.body, x.updated_at, coalesce(x.deleted, false)
  from jsonb_to_recordset(coalesce(payload->'episodes', '[]')) as x(id text, work_id text, body jsonb, updated_at bigint, deleted boolean)
  on conflict (user_id, id) do update set body = excluded.body, updated_at = excluded.updated_at, deleted = excluded.deleted, work_id = excluded.work_id
  where excluded.updated_at > rn_episodes.updated_at;

  -- Field-by-field: each field keeps whichever value has the newer timestamp.
  insert into rn_states as s (user_id, work_id, interest, interest_at, status, status_at, watchlist, watchlist_at,
                              rating, rating_at, notes, notes_at, device_id, added_at)
  select uid, x.work_id, x.interest, x.interest_at, x.status, x.status_at, x.watchlist, x.watchlist_at,
         x.rating, x.rating_at, x.notes, x.notes_at, coalesce(x.device_id, ''), coalesce(x.added_at, 0)
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
  insert into rn_events as e (user_id, id, work_id, episode_id, watched_at, is_rewatch, created_at, deleted_at, device_id)
  select uid, x.id, x.work_id, x.episode_id, x.watched_at, coalesce(x.is_rewatch, false), x.created_at, x.deleted_at, coalesce(x.device_id, '')
  from jsonb_to_recordset(coalesce(payload->'events', '[]')) as x(id text, work_id text, episode_id text, watched_at bigint,
       is_rewatch boolean, created_at bigint, deleted_at bigint, device_id text)
  on conflict (user_id, id) do update set deleted_at = least(coalesce(e.deleted_at, excluded.deleted_at), excluded.deleted_at)
  where excluded.deleted_at is not null and (e.deleted_at is null or excluded.deleted_at < e.deleted_at);

  insert into rn_tombstones as t (user_id, entity_type, entity_id, deleted_at, device_id)
  select uid, x.entity_type, x.entity_id, x.deleted_at, coalesce(x.device_id, '')
  from jsonb_to_recordset(coalesce(payload->'tombstones', '[]')) as x(entity_type text, entity_id text, deleted_at bigint, device_id text)
  on conflict (user_id, entity_type, entity_id) do update set deleted_at = excluded.deleted_at, device_id = excluded.device_id
  where excluded.deleted_at > t.deleted_at;

  if payload ? 'settings' and jsonb_typeof(payload->'settings') = 'object' then
    insert into rn_settings as st (user_id, body, updated_at)
    values (uid, payload->'settings'->'body', (payload->'settings'->>'updated_at')::bigint)
    on conflict (user_id) do update set body = excluded.body, updated_at = excluded.updated_at
    where excluded.updated_at > st.updated_at;
  end if;

  return 1;
end $$;

-- Everything for the caller changed after `since` (a rev). Also returns the newest rev seen.
create or replace function public.rn_pull(since bigint) returns jsonb
language sql stable security invoker set search_path = public as $$
  select jsonb_build_object(
    'works',      coalesce((select jsonb_agg(jsonb_build_object('id', id, 'body', body, 'updated_at', updated_at)) from rn_works where user_id = auth.uid() and rev > since), '[]'),
    'episodes',   coalesce((select jsonb_agg(jsonb_build_object('id', id, 'work_id', work_id, 'body', body, 'updated_at', updated_at, 'deleted', deleted)) from rn_episodes where user_id = auth.uid() and rev > since), '[]'),
    'states',     coalesce((select jsonb_agg(to_jsonb(s) - 'user_id' - 'rev') from rn_states s where user_id = auth.uid() and rev > since), '[]'),
    'events',     coalesce((select jsonb_agg(to_jsonb(e) - 'user_id' - 'rev') from rn_events e where user_id = auth.uid() and rev > since), '[]'),
    'tombstones', coalesce((select jsonb_agg(to_jsonb(t) - 'user_id' - 'rev') from rn_tombstones t where user_id = auth.uid() and rev > since), '[]'),
    'settings',   (select jsonb_build_object('body', body, 'updated_at', updated_at) from rn_settings where user_id = auth.uid() and rev > since),
    'rev', greatest(since,
      coalesce((select max(rev) from rn_works where user_id = auth.uid()), 0),
      coalesce((select max(rev) from rn_episodes where user_id = auth.uid()), 0),
      coalesce((select max(rev) from rn_states where user_id = auth.uid()), 0),
      coalesce((select max(rev) from rn_events where user_id = auth.uid()), 0),
      coalesce((select max(rev) from rn_tombstones where user_id = auth.uid()), 0),
      coalesce((select max(rev) from rn_settings where user_id = auth.uid()), 0)))
$$;

-- Deletes the caller's cloud copy (not their sign-in account, and not any device's local copy).
create or replace function public.rn_delete_my_data() returns void
language plpgsql security invoker set search_path = public as $$
declare uid uuid := auth.uid();
begin
  if uid is null then raise exception 'not signed in'; end if;
  delete from rn_events where user_id = uid;
  delete from rn_states where user_id = uid;
  delete from rn_episodes where user_id = uid;
  delete from rn_tombstones where user_id = uid;
  delete from rn_works where user_id = uid;
  delete from rn_settings where user_id = uid;
end $$;

revoke all on function public.rn_push(jsonb), public.rn_pull(bigint), public.rn_delete_my_data() from public, anon;
grant execute on function public.rn_push(jsonb), public.rn_pull(bigint), public.rn_delete_my_data() to authenticated;
