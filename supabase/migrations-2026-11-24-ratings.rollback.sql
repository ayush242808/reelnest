-- Rollback for migrations-2026-11-24-ratings.sql. Removes only what that migration added.
select cron.unschedule(jobid) from cron.job where jobname = 'reelnest-imdb-sync';
drop function if exists public.rn_imdb_ingest(text, integer);
drop function if exists public.rn_imdb_sync_begin();
drop function if exists public.rn_imdb_sync_end(integer, boolean);
drop function if exists public.rn_ratings_lookup(text[]);
drop function if exists public.rn_ratings_map(jsonb);
drop table if exists rn_private.imdb_ratings;
drop table if exists rn_private.tmdb_imdb;
drop table if exists rn_private.imdb_sync;
-- pg_cron / pg_net are left installed (other jobs may use them).
