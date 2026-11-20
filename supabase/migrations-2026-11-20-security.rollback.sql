-- Rollback for migrations-2026-11-20-security.sql. Restores the previous privileges and functions.
-- It does NOT drop the txid columns/indexes or the relay counters (dropping them is unnecessary and
-- they are harmless); the app keeps working with the old rn_pull. Re-granting TRUNCATE etc. is deliberately
-- left out: those privileges were never needed. Uncomment that block only if something truly depends on it.
begin;
create or replace function public.rn_bump_rev() returns trigger language plpgsql as $$
begin
  new.rev := nextval('public.rn_rev');
  return new;
end $$;
-- Restore the push function from supabase/migrations-2026-11-watch-source.sql (previous version), e.g.
--   \i supabase/migrations-2026-11-watch-source.sql
drop function if exists public.rn_pull_since(text);
drop function if exists public.rn_relay_take(text, integer, integer);
-- Restores Supabase's original defaults for new tables (they included these privileges):
alter default privileges for role postgres in schema public grant truncate, references, trigger on tables to anon, authenticated, service_role;
-- do $$ declare t text; begin
--   foreach t in array array['rn_works','rn_episodes','rn_states','rn_events','rn_tombstones','rn_settings'] loop
--     execute format('grant truncate, references, trigger on public.%I to authenticated', t);
--   end loop; end $$;
commit;
