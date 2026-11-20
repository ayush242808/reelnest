-- Hotfix 2026-11-20: keep NULL deleted_at as NULL (LEAST ignores NULLs).
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
