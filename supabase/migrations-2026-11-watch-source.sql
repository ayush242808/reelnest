-- ReelNest migration: watch date + source on watch records (additive, safe to re-run)
alter table public.rn_events add column if not exists watched_date text;
alter table public.rn_events add column if not exists source jsonb;

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
  insert into rn_events as e (user_id, id, work_id, episode_id, watched_at, watched_date, is_rewatch, source, created_at, deleted_at, device_id)
  select uid, x.id, x.work_id, x.episode_id, x.watched_at, x.watched_date, coalesce(x.is_rewatch, false), x.source, x.created_at, x.deleted_at, coalesce(x.device_id, '')
  from jsonb_to_recordset(coalesce(payload->'events', '[]')) as x(id text, work_id text, episode_id text, watched_at bigint, watched_date text,
       is_rewatch boolean, source jsonb, created_at bigint, deleted_at bigint, device_id text)
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

revoke all on function public.rn_push(jsonb) from public, anon;
grant execute on function public.rn_push(jsonb) to authenticated;
