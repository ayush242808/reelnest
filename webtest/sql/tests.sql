\set ON_ERROR_STOP on
\set A '\'11111111-1111-1111-1111-111111111111\''
\set B '\'22222222-2222-2222-2222-222222222222\''
create or replace function pg_temp.check(name text, ok boolean) returns void language plpgsql as $$
begin if ok then raise notice 'PASS %', name; else raise exception 'FAIL %', name; end if; end $$;

-- ---------- device 1 of user A pushes a library ----------
set role authenticated; select set_config('request.jwt.claim.sub', :A, false);
select rn_push('{"works":[{"id":"tmdb:series:1","body":{"title":"Panchayat"},"updated_at":100}],
  "episodes":[{"id":"manual-ep:x","work_id":"manual:1","body":{"season":1,"number":1},"updated_at":5}],
  "states":[{"work_id":"tmdb:series:1","interest":"INTERESTED","interest_at":10,"status":"WATCHING","status_at":10,"watchlist":false,"watchlist_at":0,"rating":7,"rating_at":10,"notes":"first","notes_at":10,"device_id":"A1","added_at":10}],
  "events":[{"id":"e1","work_id":"tmdb:series:1","episode_id":"tmdb:ep:1","watched_at":50,"is_rewatch":false,"created_at":50,"deleted_at":null,"device_id":"A1"}],
  "tombstones":[], "settings":{"body":{"region":"IN"},"updated_at":10}}'::jsonb);
select pg_temp.check('A sees own rows', (select count(*) from rn_works) = 1 and (select count(*) from rn_events) = 1);

-- ---------- per-field merge: device 2 changes only the watchlist, with an older status ----------
select rn_push('{"states":[{"work_id":"tmdb:series:1","interest":"UNCLASSIFIED","interest_at":5,"status":"DROPPED","status_at":5,"watchlist":true,"watchlist_at":20,"rating":null,"rating_at":5,"notes":"older","notes_at":5,"device_id":"A2","added_at":12}]}'::jsonb);
select pg_temp.check('newer watchlist applied, older fields ignored',
  (select watchlist and status = 'WATCHING' and interest = 'INTERESTED' and rating = 7 and notes = 'first' and added_at = 10 from rn_states));

-- ---------- append-only events: deletion sticks, stale copy cannot resurrect ----------
select rn_push('{"events":[{"id":"e1","work_id":"tmdb:series:1","episode_id":"tmdb:ep:1","watched_at":50,"created_at":50,"deleted_at":70,"device_id":"A2"}]}'::jsonb);
select rn_push('{"events":[{"id":"e1","work_id":"tmdb:series:1","episode_id":"tmdb:ep:1","watched_at":50,"created_at":50,"deleted_at":null,"device_id":"A1"}]}'::jsonb);
select pg_temp.check('deleted event stays deleted', (select deleted_at = 70 from rn_events where id = 'e1'));

-- ---------- older work body does not overwrite newer ----------
select rn_push('{"works":[{"id":"tmdb:series:1","body":{"title":"Old"},"updated_at":50}]}'::jsonb);
select pg_temp.check('older work body ignored', (select body->>'title' = 'Panchayat' from rn_works));

-- ---------- idempotent: pushing identical data does not bump rev ----------
select max(rev) as r1 from rn_events \gset
select rn_push('{"events":[{"id":"e1","work_id":"tmdb:series:1","episode_id":"tmdb:ep:1","watched_at":50,"created_at":50,"deleted_at":70,"device_id":"A2"}]}'::jsonb);
select pg_temp.check('re-push is a no-op', (select max(rev) from rn_events) = :r1);

-- ---------- pull: incremental ----------
select (rn_pull(0)->>'rev')::bigint as rev0 \gset
select pg_temp.check('full pull has everything', jsonb_array_length(rn_pull(0)->'works') = 1 and jsonb_array_length(rn_pull(0)->'events') = 1 and rn_pull(0)->'settings'->'body'->>'region' = 'IN');
select pg_temp.check('pull since latest rev is empty', jsonb_array_length(rn_pull(:rev0)->'works') = 0 and jsonb_array_length(rn_pull(:rev0)->'states') = 0);
select rn_push('{"tombstones":[{"entity_type":"work","entity_id":"manual:1","deleted_at":90,"device_id":"A1"}]}'::jsonb);
select pg_temp.check('pull since returns only the new tombstone', jsonb_array_length(rn_pull(:rev0)->'tombstones') = 1 and jsonb_array_length(rn_pull(:rev0)->'works') = 0);

-- ---------- isolation: user B sees and changes nothing of A ----------
select set_config('request.jwt.claim.sub', :B, false);
select pg_temp.check('B sees no rows of A', (select count(*) from rn_works) = 0 and jsonb_array_length(rn_pull(0)->'works') = 0);
select rn_push('{"works":[{"id":"tmdb:series:1","body":{"title":"B copy"},"updated_at":999}]}'::jsonb);
update rn_states set notes = 'hacked';
delete from rn_events;
select set_config('request.jwt.claim.sub', :A, false);
select pg_temp.check('A unaffected by B', (select body->>'title' = 'Panchayat' from rn_works) and (select notes = 'first' from rn_states) and (select count(*) from rn_events) = 1);

-- B cannot insert a row claiming to be A (RLS with check)
select set_config('request.jwt.claim.sub', :B, false);
do $$ begin
  insert into rn_works (user_id, id, body, updated_at) values ('11111111-1111-1111-1111-111111111111', 'evil', '{}', 1);
  raise exception 'FAIL insert as other user allowed';
exception when insufficient_privilege then raise notice 'PASS cannot write as another user';
end $$;

-- ---------- anonymous callers get nothing ----------
reset role; set role anon; select set_config('request.jwt.claim.sub', '', false);
do $$ begin
  perform rn_pull(0);
  raise exception 'FAIL anon could call rn_pull';
exception when insufficient_privilege then raise notice 'PASS anon cannot call functions';
end $$;
do $$ begin
  perform count(*) from rn_works;
  raise exception 'FAIL anon could read table';
exception when insufficient_privilege then raise notice 'PASS anon cannot read tables';
end $$;

-- ---------- delete my data only removes the caller's rows ----------
reset role; set role authenticated; select set_config('request.jwt.claim.sub', :B, false);
select rn_delete_my_data();
select pg_temp.check('B wiped own data', (select count(*) from rn_works) = 0);
select set_config('request.jwt.claim.sub', :A, false);
select pg_temp.check('A data intact after B wipe', (select count(*) from rn_works) = 1);
do $$ begin
  perform rn_push('{"states":[{"work_id":"w2","interest":"UNCLASSIFIED","interest_at":1,"status":"NOT_STARTED","status_at":1,"watchlist":false,"watchlist_at":0,"rating":42,"rating_at":1,"notes":null,"notes_at":0}]}'::jsonb);
  raise exception 'FAIL bad rating stored';
exception when check_violation then raise notice 'PASS invalid rating refused by the server';
end $$;
