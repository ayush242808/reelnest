"""Migration test on a disposable local copy of the production schema (PostgreSQL 16)."""
import subprocess, time, json
ok = []
def check(n, c, i=""): ok.append(bool(c)); print(("PASS " if c else "FAIL ") + n + ("" if c else "  :: " + str(i)[:300]))
PS = ["psql", "-h", "/tmp", "-p", "5544", "-U", "postgres", "-At", "-q", "-v", "ON_ERROR_STOP=1"]
def sql(q, db="mt"):
    r = subprocess.run(PS + ["-d", db, "-c", q], capture_output=True, text=True)
    return (r.returncode, r.stdout.strip(), r.stderr.strip())
def run_file(f, db="mt"):
    r = subprocess.run(PS + ["-d", db, "-f", f], capture_output=True, text=True); return r.returncode, r.stderr.strip()
U1, U2 = "11111111-1111-1111-1111-111111111111", "22222222-2222-2222-2222-222222222222"
def as_user(uid, q): return f"set role authenticated; select set_config('request.jwt.claim.sub', '{uid}', false); {q}"
subprocess.run(PS + ["-d", "postgres", "-c", "drop database if exists mt", "-c", "create database mt"], capture_output=True)
assert run_file("/home/claude/webtest/sql/shim.sql")[0] == 0
# Reproduce Supabase's default grants for new public tables (the source of TRUNCATE etc.)
sql("alter default privileges for role postgres in schema public grant truncate, references, trigger on tables to anon, authenticated, service_role")
rc, err = run_file("/tmp/prod_schema.sql"); check("production schema (pre-migration) applies", rc == 0, err)
check("pre-migration reproduces the finding: authenticated has TRUNCATE", sql("select has_table_privilege('authenticated','public.rn_works','TRUNCATE')")[1] == "t")
# Seed through the real RPC as user 1, and a second user
seed = {"works": [{"id": "tmdb:movie:1", "body": {"title": "A"}, "updated_at": 1000}],
        "states": [{"work_id": "tmdb:movie:1", "interest": "INTERESTED", "interest_at": 1000, "status": "WATCHING", "status_at": 1000, "watchlist": True, "watchlist_at": 1000, "rating": 8, "rating_at": 1000, "notes": "hi", "notes_at": 1000, "device_id": "d1", "added_at": 1000}],
        "events": [{"id": "e1", "work_id": "tmdb:movie:1", "episode_id": None, "watched_at": 1000, "watched_date": "2024-03-05", "is_rewatch": False, "source": {"kind": "ott", "name": "Netflix"}, "created_at": 1000, "deleted_at": None, "device_id": "d1"}],
        "settings": {"body": {"theme": "dark"}, "updated_at": 1000}}
for u in (U1, U2):
    rc, out, err = sql(as_user(u, "select rn_push($j$" + json.dumps(seed) + "$j$::jsonb)")); assert rc == 0, err
snap = "select md5(string_agg(x, ',' order by x)) from (select (to_jsonb(t) - 'rev' - 'txid')::text x from public.%s t) z"
tables = ["rn_works", "rn_episodes", "rn_states", "rn_events", "rn_tombstones", "rn_settings"]
before = {t: sql(snap % t)[1] for t in tables}
rc, err = run_file("/home/claude/reelnest-repo/supabase/migrations-2026-11-20-security.sql"); check("migration applies", rc == 0, err)
rc, err = run_file("/home/claude/reelnest-repo/supabase/migrations-2026-11-20-security.sql"); check("migration is safe to re-run", rc == 0, err)
for f_ in ("migrations-2026-11-20-hotfix-push.sql", "migrations-2026-11-20b-sync-convergence.sql", "migrations-2026-11-20b-sync-convergence.sql"):
    rc, err = run_file("/home/claude/reelnest-repo/supabase/" + f_); check(f"{f_} applies (re-runnable)", rc == 0, err)
check("all existing rows unchanged by the migration", all(sql(snap % t)[1] == before[t] for t in tables), [(t, before[t], sql(snap % t)[1]) for t in tables])
# Privileges
bad = sql("""select string_agg(r||':'||t||':'||p, ' ') from unnest(array['anon','authenticated']) r, unnest(array['rn_works','rn_episodes','rn_states','rn_events','rn_tombstones','rn_settings']) t,
  unnest(array['TRUNCATE','REFERENCES','TRIGGER']) p where has_table_privilege(r, 'public.'||t, p)""")[1]
check("no TRUNCATE/REFERENCES/TRIGGER for anon or authenticated (effective)", bad == "", bad)
anon_any = sql("""select string_agg(t||':'||p, ' ') from unnest(array['rn_works','rn_episodes','rn_states','rn_events','rn_tombstones','rn_settings']) t, unnest(array['SELECT','INSERT','UPDATE','DELETE']) p where has_table_privilege('anon','public.'||t,p)""")[1]
check("anon has no table access at all", anon_any == "", anon_any)
need = sql("""select bool_and(has_table_privilege('authenticated','public.'||t,p)) from unnest(array['rn_works','rn_episodes','rn_states','rn_events','rn_tombstones','rn_settings']) t, unnest(array['SELECT','INSERT','UPDATE','DELETE']) p""")[1]
check("authenticated keeps exactly what the app needs (select/insert/update/delete)", need == "t")
rc, out, err = sql(as_user(U1, "truncate public.rn_works")); check("TRUNCATE as a signed-in user is refused (disposable local DB)", rc != 0 and "permission denied" in err, err)
sql("create table public.zz_new (id int)")
check("new tables no longer inherit TRUNCATE for API roles", sql("select has_table_privilege('authenticated','public.zz_new','TRUNCATE') or has_table_privilege('anon','public.zz_new','TRUNCATE')")[1] == "f")
sql("drop table public.zz_new")
check("rn_bump_rev: fixed search_path, not executable by API roles",
      sql("select array_to_string(proconfig, ';') from pg_proc where proname='rn_bump_rev'")[1] == 'search_path=""' and sql("select has_function_privilege('authenticated','public.rn_bump_rev()','execute') or has_function_privilege('anon','public.rn_bump_rev()','execute')")[1] == "f",
      sql("select proconfig from pg_proc where proname='rn_bump_rev'")[1])
check("all rn_* functions have a fixed search_path", sql("select count(*) from pg_proc where pronamespace='public'::regnamespace and proname like 'rn\\_%' and (proconfig is null or not exists (select 1 from unnest(proconfig) c where c like 'search_path=%'))")[1] == "0")
check("anon can't call any sync function", sql("select bool_or(has_function_privilege('anon', p, 'execute')) from unnest(array['public.rn_push(jsonb)','public.rn_pull(bigint)','public.rn_pull_since(text)','public.rn_delete_my_data()']) p")[1] == "f")
check("relay limiter callable only by service_role", sql("select has_function_privilege('service_role','public.rn_relay_take(text,integer,integer)','execute') and not has_function_privilege('authenticated','public.rn_relay_take(text,integer,integer)','execute') and not has_function_privilege('anon','public.rn_relay_take(text,integer,integer)','execute')")[1] == "t")
check("relay counter table not reachable by API roles", sql("select has_table_privilege('authenticated','rn_private.relay_hits','SELECT') or has_table_privilege('anon','rn_private.relay_hits','SELECT') or has_schema_privilege('anon','rn_private','USAGE')")[1] == "f")
# Normal use after migration (trigger fires though API roles can't execute it directly)
upd = dict(seed); upd["states"] = [dict(seed["states"][0], status="COMPLETED", status_at=2000)]
rc, out, err = sql(as_user(U1, "select rn_push($j$" + json.dumps(upd) + "$j$::jsonb)")); check("push works after migration (update fires rev/txid trigger)", rc == 0, err)
rc, out, err = sql(as_user(U1, "select rn_pull_since(null)::text"))
pulled = json.loads(out.splitlines()[-1]) if rc == 0 else {}
check("pull_since(null) returns the full library + a cursor", rc == 0 and pulled["states"][0]["status"] == "COMPLETED" and pulled["events"][0]["source"]["name"] == "Netflix" and pulled.get("cursor"), err or out[:200])
check("pull never exposes user_id, rev or txid", all(k not in json.dumps(pulled) for k in ['"user_id"', '"txid"']))
rc, out, err = sql(as_user(U1, "select rn_pull(0)::text")); check("old rn_pull still works for cached app versions", rc == 0 and "COMPLETED" in out, err)
# Regression: LEAST() ignores NULLs -> a NULL deleted_at must stay NULL (an un-deleted watch must not become deleted)
evx = {"events": [{"id": "keep-me", "work_id": "tmdb:movie:1", "watched_at": 5, "created_at": 5, "deleted_at": None, "device_id": "d1"}]}
sql(as_user(U1, "select rn_push($j$" + json.dumps(evx) + "$j$::jsonb)")); sql(as_user(U1, "select rn_push($j$" + json.dumps(evx) + "$j$::jsonb)"))
check("new and re-pushed watch records stay un-deleted (NULL deleted_at preserved)", sql(f"select deleted_at is null from public.rn_events where user_id='{U1}' and id='keep-me'")[1] == "t")
check("existing watch record re-pushed without deletion stays active", sql(as_user(U1, "select rn_push($j$" + json.dumps({"events": [seed["events"][0]]}) + "$j$::jsonb)"))[0] == 0 and sql(f"select deleted_at is null from public.rn_events where user_id='{U1}' and id='e1'")[1] == "t")
evd = {"events": [{"id": "keep-me", "work_id": "tmdb:movie:1", "watched_at": 5, "created_at": 5, "deleted_at": 7000, "device_id": "d1"}]}
sql(as_user(U1, "select rn_push($j$" + json.dumps(evd) + "$j$::jsonb)"))
check("a real deletion still applies", sql(f"select deleted_at from public.rn_events where user_id='{U1}' and id='keep-me'")[1] == "7000")
st0 = {"states": [{"work_id": "tmdb:movie:9", "interest": "INTERESTED", "interest_at": None, "status": "WATCHING", "status_at": 10, "watchlist": False, "watchlist_at": 10, "rating": None, "rating_at": 10, "notes": None, "notes_at": 10}]}
sql(as_user(U1, "select rn_push($j$" + json.dumps(st0) + "$j$::jsonb)"))
check("a missing field timestamp is stored as 0, not as 'now + 5 min'", sql(f"select interest_at from public.rn_states where user_id='{U1}' and work_id='tmdb:movie:9'")[1] == "0")
# Clock clamp
fut = dict(seed); fut["states"] = [dict(seed["states"][0], notes="from the future", notes_at=int(time.time() * 1000) + 10 * 365 * 86400000)]; fut["works"] = []; fut["events"] = []; del fut["settings"]
sql(as_user(U1, "select rn_push($j$" + json.dumps(fut) + "$j$::jsonb)"))
na = int(sql(f"select notes_at from public.rn_states where user_id='{U1}' and work_id='{seed['states'][0]['work_id']}'")[1])
check("a far-future device clock is clamped to the server clock", na <= int(time.time() * 1000) + 5000, na)
time.sleep(0.05); later = dict(fut); later["states"] = [dict(seed["states"][0], notes="real later edit", notes_at=int(time.time() * 1000))]
sql(as_user(U1, "select rn_push($j$" + json.dumps(later) + "$j$::jsonb)"))
check("...so a later honest edit can still win", sql(f"select notes from public.rn_states where user_id='{U1}' and work_id='{seed['states'][0]['work_id']}'")[1] == "real later edit")
# Convergence: a stale push leaves the server's values but moves the row so the loser pulls the winner
c0 = json.loads(sql(as_user(U1, "select rn_pull_since(null)::text"))[1].splitlines()[-1])["cursor"]
stale = {"states": [dict(seed["states"][0], notes="stale", notes_at=1)]}; stale["states"][0].pop("work_id", None); stale["states"][0]["work_id"] = seed["states"][0]["work_id"]
sql(as_user(U1, "select rn_push($j$" + json.dumps(stale) + "$j$::jsonb)"))
p1 = json.loads(sql(as_user(U1, f"select rn_pull_since('{c0}')::text"))[1].splitlines()[-1])
check("a rejected stale push keeps the server value", sql(f"select notes from public.rn_states where user_id='{U1}' and work_id='{seed['states'][0]['work_id']}'")[1] == "real later edit")
check("...and the row comes back in the next pull so the device converges", any(s_["notes"] == "real later edit" for s_ in p1["states"]), p1["states"])
# Isolation through the RPCs
rc, out, err = sql(as_user(U2, "select rn_pull_since(null)::text")); p2 = json.loads(out.splitlines()[-1])
check("user 2 sees only their own data", p2["states"][0]["notes"] == "hi" and len(p2["works"]) == 1)
evil = {"states": [{"user_id": U1, "work_id": "tmdb:movie:1", "interest": "X", "interest_at": 9e12, "status": "DROPPED", "status_at": 9e12, "watchlist": False, "watchlist_at": 9e12, "rating": 1, "rating_at": 9e12, "notes": "hacked", "notes_at": 9e12}]}
sql(as_user(U2, "select rn_push($j$" + json.dumps(evil) + "$j$::jsonb)"))
check("a user_id in the payload is ignored (can't write another user's rows)", sql(f"select notes from public.rn_states where user_id='{U1}' and work_id='{seed['states'][0]['work_id']}'")[1] == "real later edit")
rc, out, err = sql(as_user(U2, f"insert into public.rn_works (user_id, id, body, updated_at) values ('{U1}', 'x', '{{}}', 1)"))
check("direct insert with another user's id is refused by RLS", rc != 0 and "row-level security" in err, err)
rc, out, err = sql(as_user(U2, f"update public.rn_states set notes='hacked' where user_id='{U1}' returning 1"))
check("direct update of another user's row affects nothing", rc == 0 and sql(f"select notes from public.rn_states where user_id='{U1}' and work_id='{seed['states'][0]['work_id']}'")[1] == "real later edit", (out, err))
n_before = sql(f"select count(*) from public.rn_events where user_id='{U1}'")[1]
rc, out, err = sql(as_user(U2, f"delete from public.rn_events where user_id='{U1}'"))
check("direct delete of another user's rows affects nothing", n_before not in ("", "0") and sql(f"select count(*) from public.rn_events where user_id='{U1}'")[1] == n_before)
rc, out, err = sql(as_user(U2, f"select count(*) from public.rn_works where user_id='{U1}'"))
check("direct read of another user's rows returns nothing", out.splitlines()[-1] == "0", out)
rc, out, err = sql("set role anon; select count(*) from public.rn_works")
check("signed-out (anon) can't read", rc != 0 and "permission denied" in err, err)
rc, out, err = sql("set role anon; select rn_push('{}'::jsonb)")
check("signed-out (anon) can't push", rc != 0 and "permission denied" in err, err)
rc, out, err = sql("set role authenticated; select set_config('request.jwt.claim.sub', '', false); select rn_push('{}'::jsonb)")
check("authenticated role without a user id can't push", rc != 0 and "not signed in" in err, err)
# Commit-order race: tx A takes a lower rev, tx B commits a higher rev first, then a pull happens, then A commits.
cur0 = json.loads(sql(as_user(U1, "select rn_pull_since(null)::text"))[1].splitlines()[-1])["cursor"]
rev0 = int(json.loads(sql(as_user(U1, "select rn_pull(0)::text"))[1].splitlines()[-1])["rev"])
A = subprocess.Popen(PS + ["-d", "mt"], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
evA = {"events": [{"id": "race-A", "work_id": "tmdb:movie:1", "watched_at": 1, "created_at": 1, "device_id": "A"}]}
A.stdin.write("begin;\n" + as_user(U1, "select rn_push($j$" + json.dumps(evA) + "$j$::jsonb);") + "\n"); A.stdin.flush(); time.sleep(1.0)
evB = {"events": [{"id": "race-B", "work_id": "tmdb:movie:1", "watched_at": 2, "created_at": 2, "device_id": "B"}]}
sql(as_user(U1, "select rn_push($j$" + json.dumps(evB) + "$j$::jsonb)"))
mid_new = json.loads(sql(as_user(U1, f"select rn_pull_since('{cur0}')::text"))[1].splitlines()[-1])
mid_old = json.loads(sql(as_user(U1, f"select rn_pull({rev0})::text"))[1].splitlines()[-1])
A.stdin.write("commit;\n"); A.stdin.close(); A.wait(10)
after_new = json.loads(sql(as_user(U1, f"select rn_pull_since('{mid_new['cursor']}')::text"))[1].splitlines()[-1])
after_old = json.loads(sql(as_user(U1, f"select rn_pull({mid_old['rev']})::text"))[1].splitlines()[-1])
ids = lambda r: {e["id"] for e in r["events"]}
check("race reproduced: old rev cursor skips the late-committing write", "race-B" in ids(mid_old) and "race-A" not in ids(mid_old) and "race-A" not in ids(after_old), (ids(mid_old), ids(after_old)))
check("new transaction cursor still delivers it on the next pull", "race-B" in ids(mid_new) and "race-A" in ids(after_new), (ids(mid_new), ids(after_new)))
# Rollback script
rc, err = run_file("/home/claude/reelnest-repo/supabase/migrations-2026-11-20-security.rollback.sql"); check("rollback script runs", rc == 0, err)
rc, err = run_file("/home/claude/reelnest-repo/supabase/migrations-2026-11-20-security.sql"); check("migration re-applies after rollback", rc == 0, err)
rc, err = run_file("/home/claude/reelnest-repo/supabase/migrations-2026-11-20b-sync-convergence.sql"); check("convergence migration re-applies after rollback", rc == 0, err)
print(f"\n{sum(ok)}/{len(ok)} passed")
