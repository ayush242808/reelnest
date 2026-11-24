# ReelNest

A private web app for tracking movies, TV series and anime from India and around the world. It works on phone, tablet and desktop browsers and can be installed to the home screen. There are no social features, public profiles or feeds.

## Files

| File | What it is |
|---|---|
| `index.html` | The whole app |
| `config.js` | Public site settings (Supabase URL and anon key). Empty means local-only. |
| `sw.js`, `manifest.webmanifest`, `icon*.png`, `icon.svg` | Offline support and home-screen install |
| `supabase/schema.sql` | Cloud backup database: tables, per-account security rules, merge functions |
| `supabase/migrations-2026-11-watch-source.sql` | Upgrade for databases created before watch dates and sources were added (already applied to this site's project) |
| `supabase/migrations-2026-11-20-security.sql` (+ `.rollback.sql`) | Least-privilege grants, fixed `search_path`, commit-safe sync cursor, clock clamp, relay rate-limit table (applied 2026-11-20) |
| `supabase/migrations-2026-11-20-hotfix-push.sql` | Fix: a missing deletion time stays "not deleted" (applied 2026-11-20) |
| `supabase/migrations-2026-11-20b-sync-convergence.sql` | Rejected edits flow back to the device that lost; clamp to server time (applied 2026-11-20). Rollback = re-run the hotfix file |
| `supabase/functions/tmdb/index.ts` | Shared TMDB relay (Edge Function) |
| `supabase/migrations-2026-11-24-ratings.sql` (+ `.rollback.sql`) | Private IMDb ratings store, TMDB→IMDb id cache, daily sync job (applied 2026-11-24) |
| `supabase/functions/ratings/index.ts` | Ratings function: IMDb audience ratings for signed-in users, plus the daily sync |
| `tools/csp.py` | Regenerates the Content-Security-Policy tag after any change to the app's script |
| `relay-worker.js` | Optional Cloudflare relay for networks that block TMDB (deploy to Cloudflare, not GitHub Pages) |

## Hosting (GitHub Pages, free)

Put all files except `relay-worker.js` in the repository root. Then go to Settings › Pages › Deploy from a branch › `main` / root. The site appears at `https://<username>.github.io/<repo>/`.

## Catalog (TMDB)

Search, details, episodes, artwork and availability come from TMDB. Paste a free TMDB API key in Profile › Catalog. It's stored only in that browser.

Some Indian networks (notably Jio) block TMDB. The app automatically tries TMDB's second API address, `api.tmdb.org`. For posters it tries `image.tmdb.org`, then `media.themoviedb.org`, then the public image proxy `wsrv.nl`. If search is still blocked, use the relay:

1. Create a free Cloudflare account and go to Workers & Pages › Create Worker.
2. Paste in `relay-worker.js` and Deploy.
3. Optionally add a secret `TMDB_KEY`, and `ALLOWED_ORIGIN` set to your site's address.
4. Paste the worker address into Profile › Catalog › relay.

Coverage depends on TMDB. Some regional titles and episodes are missing; add them manually and link them later.

## Where to watch

Availability comes from TMDB's watch-provider data, which is supplied by JustWatch. Attributing JustWatch is required, and the app does so.

- **What's shown:** each title page lists providers for your **viewing country** (default India; change it in Profile), grouped into subscription, free, rent and buy, with the provider's logo. The only link is the TMDB "watch" page that TMDB returns; no links are invented.
- **How it's labelled:** availability is for the whole title, not individual seasons or episodes, and the page shows when it was last refreshed. The app re-checks after 24 hours, or when you tap Refresh.
- **When nothing comes back:** "No providers found" means JustWatch has no listing for that country. It does not mean the title is definitely unavailable. Network errors show a retry button.
- **Certifications:** age ratings use the same viewing country. A title's country of origin is shown separately.

## Cloud backup and sync (optional, Supabase)

Without an account, everything stays in the browser. Clearing site data, private browsing, or switching browsers loses it unless you export a backup file. With cloud backup, you sign in with your email and a one-time code (Google sign-in is optional).

**What syncs:** titles (including manual ones), episode progress and watch history, ratings, notes and preferences. Your own TMDB key syncs only if you turn on **Profile › Catalog › Sync my key to my account** (off by default). Turning it off removes the cloud copy; each device keeps its own key.

**How it stays safe:**
- Every edit is saved on the device first and queued for upload.
- "Backed up" appears only after the server confirms the upload.
- Offline changes wait in the queue and upload when you're back online. Failures show the error with a Retry button.

**How merging works:**
- Watch history is combined. A removed watch never comes back from a stale device.
- Status, interest, watchlist, rating and notes merge field by field; the newest change wins. When notes differ on both sides, the other version is kept under Profile › Needs review.
- A deleted title stays deleted unless another device changed it after the deletion. In that case it's kept and you're told.
- The first sign-in on a device that already has titles shows both counts and asks before merging. "Not now" changes nothing on either side.

### One-time setup (about 10 minutes)

1. Create a free project at supabase.com.
2. Open **SQL Editor › New query**, paste in all of `supabase/schema.sql`, and click **Run**. It's safe to run again later. A database set up before November 2026 only needs `supabase/migrations-2026-11-watch-source.sql`.
3. Under **Authentication › URL Configuration**, set **Site URL** to your GitHub Pages address, and add it under **Redirect URLs**.
4. Under **Authentication › Email Templates › Magic Link**, add `{{ .Token }}` to the message so the email contains the 6-digit code. The sign-in link in the email works too.
5. Under **Project Settings › API**, copy the **Project URL** and the **anon public** key into `config.js`. Commit it, or paste both into Profile › Backup & sync on one device to try it first.
6. Optional Google sign-in: enable Google under Authentication › Providers (it needs a Google Cloud OAuth client), then set `googleSignIn: true` in `config.js`.

The anon key is meant to be public. Data is protected on the server by Row Level Security: each signed-in user can read and write only their own rows. Never put the `service_role` key in `config.js`.

### Costs and limits (Supabase free plan, as checked November 2026)

- **Price and size:** $0. The 500 MB database holds millions of watch records, far more than one person needs.
- **Pausing:** free projects pause after 7 days with no requests. Data is kept, and you resume the project from the Supabase dashboard. Daily use keeps it awake. While paused, the app shows a sync error, and your device copy keeps working.
- **Email:** Supabase's built-in email only sends to members of your Supabase organization. That's fine when you're the only user (sign in with the address you used for Supabase). Other people would need custom SMTP.
- **Account deletion:** "Delete cloud copy" in Profile removes your library rows. Removing the sign-in account itself is done in Supabase › Authentication › Users.

## Privacy

| Where | What's there |
|---|---|
| **On the device** | The whole library, plus your own TMDB key and relay address if you added them, and your sign-in session |
| **In the cloud** (only if signed in) | Your email address and a copy of the library and preferences. Your own TMDB key and relay address only if you opted in to key syncing |
| **Backup files** | Library, history and preferences. Never the TMDB key, relay address or sign-in session |
| **Other services** | The shared relay (this project's Supabase function: searches, opened titles, and your IP address, kept only as a one-way hash for rate limiting) or TMDB directly (searches, opened titles, your own key) or your own relay; poster image hosts, including wsrv.nl as a fallback proxy; Google Fonts. YouTube, IMDb and TMDB pages open only when you tap their links. |

## Backup files

Profile › Export backup produces a versioned JSON file (`reelnest-export` v1). Import validates the file (20 MB and record-count limits, record shapes, field types and lengths) and previews the changes, then merges without overwriting. This works with or without an account.

## Tests

`webtest/e2e.py` runs the real app in headless Chrome. TMDB is simulated with fixtures, and the Supabase server is the real `schema.sql` on a local PostgreSQL. `webtest/sql/tests.sql` tests the database rules directly. Also:

- `webtest/migtest.py`: replays the production schema, then the migrations, and checks grants, isolation, the sync cursor race, clamping, NULL deletions and convergence (needs a schema-only dump at `/tmp/prod_schema.sql`).
- `webtest/scenarios.py`: TMDB-key opt-in and removal, episode loading/failure/retry/offline, and sync scenarios (equal timestamps, clock skew, concurrent edits, retries, delete vs. edit, fresh-device restore, backups).
- `webtest/csp_check.py`: the CSP blocks injected scripts and handlers, image fallback, backup limits, unsafe links.
- `webtest/relay/relay_test.mjs`: relay allowlists, limits, timeouts (`node --experimental-strip-types`).

## Security notes

- **Content-Security-Policy** is a `<meta>` tag, because GitHub Pages can't send custom headers. After editing the script in `index.html`, run `python3 tools/csp.py` (CI-style check: `--check`). GitHub Pages also can't send `frame-ancestors`, HSTS or `X-Content-Type-Options`, so clickjacking protection isn't possible on this host.
- **Database roles:** `anon` has no table access. `authenticated` has select/insert/update/delete only, limited to its own rows by RLS. No TRUNCATE, TRIGGER or REFERENCES for either role, and default privileges for new tables were narrowed too.
- **Sync** uses a transaction-id cursor, so changes committed out of order are never skipped. Client timestamps can't be later than the server clock. A device whose edit lost a conflict pulls the winning value back.

## Discover verdicts (public audience ratings)

Discover rates titles like Moctale's meter (**Perfection**, **Go for It**, **Time Pass**, **Skip**). The score is calculated from public audience votes, not paid or critic reviews:

- **IMDb:** official non-commercial dataset (`title.ratings.tsv.gz`), loaded nightly at 02:47 IST by `pg_cron` calling the `ratings` function. It's stored in `rn_private`, which no API role can read, and returned only to signed-in users, as IMDb's personal-use terms require.
- **TMDB:** vote average and vote count.

Each source is pulled towards an average film (6.4) until it has enough votes (IMDb 2,500, TMDB 250), so a handful of 10/10 votes can't top the list. IMDb is weighted 3:1 over TMDB. The bands are Perfection 8.0+, Go for It 7.0–7.9, Time Pass 6.0–6.9 and Skip below 6.0 (`VERDICTS` in `index.html`).

The rows show Perfection and Go for It, best first; **+ Time Pass** adds the next band. Anime keeps TMDB's popularity order. When you're signed out, verdicts use TMDB votes alone. Moctale has no public API, so title pages only link to it.

To check the sync, run `select * from rn_private.imdb_sync;` in the SQL editor, or open Logs and search for `ratings_sync`. To run it by hand, open `…/functions/v1/ratings?op=sync`; it runs at most once every 20 hours.

## Monitoring the shared relay

- Logs: Supabase › Edge Functions › `tmdb` › Logs. Look for `relay_limit` (a client or the daily budget hit its limit), `relay_upstream` (TMDB errors or timeouts) and `relay_limiter_unavailable` (the database counter couldn't be reached, so the per-instance fallback applied).
- Usage: run this in the SQL editor:
  `select case when bucket like '%:global' then bucket else 'per-client' end as bucket, window_start, sum(hits) as hits from rn_private.relay_hits where window_start > now() - interval '1 day' group by 1, 2 order by 2 desc;`
- Limits per client: 300 API calls and 900 images per 5 minutes. Site-wide: 25,000 API calls and 40,000 images per day. Change `LIMITS` in `index.ts` and redeploy.

This product uses the TMDB API but is not endorsed or certified by TMDB. Availability data comes from JustWatch. ReelNest doesn't stream or download anything.

## Shared catalog (no key needed for visitors)

`supabase/functions/tmdb/index.ts` is a Supabase Edge Function that forwards read-only TMDB requests and adds the site owner's TMDB key on the server, so family members can use the site without their own key. The key is stored only as the Supabase secret `TMDB_KEY` (Edge Functions › Secrets), never in this repository. Catalog requests are answered only for pages served from `https://ayush242808.github.io`, and JWT verification is off for this one function because visitors call it without signing in. `config.js` points `tmdbRelay` at it. Visitors who add their own key go to TMDB directly, and their key is never sent through the shared relay.
