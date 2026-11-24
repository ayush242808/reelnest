-- ReelNest migration 2026-11-24: public audience ratings (IMDb) for Discover verdicts.
--
-- Source: IMDb's official non-commercial dataset title.ratings.tsv.gz (datasets.imdbws.com, refreshed daily):
-- real user votes, not paid or bought reviews. IMDb permits personal, non-commercial use and local copies,
-- not republishing; so the data lives in a private schema that no API role can read, and the Edge Function
-- "ratings" returns it only to signed-in ReelNest users, a few titles at a time.
--
-- Adds only new objects. No existing table, policy, grant or row is changed.
-- Rollback: supabase/migrations-2026-11-24-ratings.rollback.sql

create schema if not exists rn_private;
revoke all on schema rn_private from public, anon, authenticated;

-- Titles with at least 100 votes (~10% of IMDb's titles; the rest are too thin to rank on).
create table if not exists rn_private.imdb_ratings (
  tconst text primary key,
  rating numeric(3,1) not null,
  votes integer not null
);
-- TMDB title -> IMDb id, looked up once per title (TMDB external_ids). imdb_id null = TMDB has none (re-checked after 14 days).
create table if not exists rn_private.tmdb_imdb (
  tmdb_key text primary key,
  imdb_id text,
  checked_at timestamptz not null default now()
);
create table if not exists rn_private.imdb_sync (
  id int primary key default 1 check (id = 1),
  started_at timestamptz,
  finished_at timestamptz,
  rows_seen integer,
  status text
);
insert into rn_private.imdb_sync (id) values (1) on conflict do nothing;
alter table rn_private.imdb_ratings enable row level security;
alter table rn_private.tmdb_imdb enable row level security;
alter table rn_private.imdb_sync enable row level security;
revoke all on rn_private.imdb_ratings, rn_private.tmdb_imdb, rn_private.imdb_sync from public, anon, authenticated;

-- Parse one block of TSV lines ("tt0111161<TAB>9.3<TAB>3012345") and upsert. Only changed rows are written.
create or replace function public.rn_imdb_ingest(chunk text, min_votes integer default 100)
returns integer language sql security definer set search_path = '' set statement_timeout = '60s' as $$
  with l as (
    select string_to_array(x, E'\t') a from pg_catalog.string_to_table(chunk, E'\n') x
    where x ~ '^tt[0-9]{1,12}\t[0-9]{1,2}(\.[0-9])?\t[0-9]{1,9}$'
  ), ins as (
    insert into rn_private.imdb_ratings (tconst, rating, votes)
    select a[1], a[2]::numeric, a[3]::integer from l where a[3]::integer >= min_votes
    on conflict (tconst) do update set rating = excluded.rating, votes = excluded.votes
    where rn_private.imdb_ratings.rating <> excluded.rating or rn_private.imdb_ratings.votes <> excluded.votes
    returning 1)
  select count(*)::integer from ins;
$$;

-- At most one sync per 20 hours; a run that died is retried after 1 hour. Returns true if the caller may sync now.
create or replace function public.rn_imdb_sync_begin() returns boolean
language plpgsql security definer set search_path = '' as $$
begin
  update rn_private.imdb_sync set started_at = now(), status = 'running'
  where id = 1 and (started_at is null
    or (status = 'running' and started_at < now() - interval '1 hour')
    or (status <> 'running' and coalesce(finished_at, started_at) < now() - interval '20 hours'));
  return found;
end $$;
create or replace function public.rn_imdb_sync_end(rows_seen integer, ok boolean) returns void
language sql security definer set search_path = '' as $$
  update rn_private.imdb_sync set finished_at = now(), rows_seen = rn_imdb_sync_end.rows_seen, status = case when ok then 'ok' else 'failed' end where id = 1;
$$;

-- Ratings for up to 100 TMDB keys, plus which keys still need an IMDb id lookup.
create or replace function public.rn_ratings_lookup(keys text[])
returns table (tmdb_key text, imdb_id text, rating numeric, votes integer, needs_map boolean)
language sql security definer set search_path = '' stable as $$
  select k, m.imdb_id, r.rating, r.votes,
         (m.tmdb_key is null or (m.imdb_id is null and m.checked_at < now() - interval '14 days'))
  from unnest(keys[1:100]) k
  left join rn_private.tmdb_imdb m on m.tmdb_key = k
  left join rn_private.imdb_ratings r on r.tconst = m.imdb_id;
$$;
create or replace function public.rn_ratings_map(pairs jsonb) returns void
language sql security definer set search_path = '' as $$
  insert into rn_private.tmdb_imdb (tmdb_key, imdb_id, checked_at)
  select x.k, nullif(x.imdb, ''), now() from jsonb_to_recordset(pairs) as x(k text, imdb text)
  where x.k ~ '^tmdb:(movie|series):[0-9]{1,9}$' and (x.imdb is null or x.imdb = '' or x.imdb ~ '^tt[0-9]{1,12}$')
  on conflict (tmdb_key) do update set imdb_id = excluded.imdb_id, checked_at = excluded.checked_at;
$$;

revoke execute on function public.rn_imdb_ingest(text, integer), public.rn_imdb_sync_begin(), public.rn_imdb_sync_end(integer, boolean),
  public.rn_ratings_lookup(text[]), public.rn_ratings_map(jsonb) from public, anon, authenticated;
grant execute on function public.rn_imdb_ingest(text, integer), public.rn_imdb_sync_begin(), public.rn_imdb_sync_end(integer, boolean),
  public.rn_ratings_lookup(text[]), public.rn_ratings_map(jsonb) to service_role;

-- Daily sync at 02:47 IST (21:17 UTC). Needs the pg_cron and pg_net extensions (available on all Supabase plans).
create extension if not exists pg_cron with schema pg_catalog;
create extension if not exists pg_net with schema extensions;
select cron.unschedule(jobid) from cron.job where jobname = 'reelnest-imdb-sync';
select cron.schedule('reelnest-imdb-sync', '17 21 * * *',
  $$select net.http_get(url := 'https://gedkntwwjrpfklgvbjtp.supabase.co/functions/v1/ratings?op=sync', timeout_milliseconds := 140000)$$);
