# ReelNest

A private web app for tracking movies, TV series and anime from India and around the world. It works on phone, tablet and desktop browsers and can be installed to the home screen. There are no social features, public profiles or feeds.

## Files

| File | What it is |
|---|---|
| `index.html` | The whole app |
| `config.js` | Public site settings (Supabase URL and anon key). Empty means local-only. |
| `sw.js`, `manifest.webmanifest`, `icon*.png`, `icon.svg` | Offline support and home-screen install |
| `supabase/schema.sql` | Cloud backup database: tables, per-account security rules, merge functions |
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

**What syncs:** titles (including manual ones), episode progress and watch history, ratings, notes and preferences. Your TMDB key never syncs.

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
2. Open **SQL Editor › New query**, paste in all of `supabase/schema.sql`, and click **Run**. It's safe to run again later.
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
| **On the device** | The whole library, plus the TMDB key and relay address |
| **In the cloud** (only if signed in) | Your email address and a copy of the library and preferences |
| **Other services** | TMDB (searches, opened titles, your key) or your relay; poster image hosts, including wsrv.nl as a fallback proxy; Google Fonts. YouTube, IMDb and TMDB pages open only when you tap their links. |

## Backup files

Profile › Export backup produces a versioned JSON file (`reelnest-export` v1). Import validates the file and previews the changes, then merges without overwriting. This works with or without an account.

## Tests

`webtest/e2e.py` runs the real app in headless Chrome. TMDB is simulated with fixtures, and the Supabase server is the real `schema.sql` on a local PostgreSQL. `webtest/sql/tests.sql` tests the database rules directly.

This product uses the TMDB API but is not endorsed or certified by TMDB. Availability data comes from JustWatch. ReelNest doesn't stream or download anything.
