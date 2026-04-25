# GovScroll — Master Briefing Document

> **For Claude Code:** Read this entire document at the start of every session before taking any action. It contains the product vision, architecture decisions, current build state, and what to work on next. Update the Progress Tracker and Decision Log sections as work is completed.

---

## 1. What This Is

A multi-tenant, feed-driven federal contracting opportunity intelligence platform built on SAM.gov data. Companies create accounts, configure their profile, and receive a personalized, algorithm-ranked feed of contract opportunities they can swipe through (Tinder-style) to surface high-fit work and train a per-account recommendation engine.

**Product name:** GovScroll

**The core insight:** Most SAM.gov tools are search engines. This is a recommendation engine with a social-media-style interaction loop. The swipe mechanic generates training data. The training data improves the feed. A better feed drives more engagement. More engagement drives more data. This flywheel is the product's moat.

**The target user:** Business development professionals at small-to-midsize government contractors who need to identify and track federal opportunities without spending hours manually searching SAM.gov.

**No Kanban. No pipeline management.** Users already have their own tracking systems. GovScroll's value is in *finding* contracts, not managing them. The swipe interaction is both the product and the data collection mechanism — we do not ask users to do extra work to train the algorithm.

---

## 2. Current State (v2 — In Progress)

### What is built and working

- **Monorepo structure:** `backend/` (Flask) + `frontend/` (React + Vite)
- **Database:** Supabase PostgreSQL with full schema (companies, users, opportunities, swipes, pipeline, bookmarks, company_naics, company_keywords, company_agencies). **35,914 opportunities ingested.** `ai_analysis` column added (TEXT, nullable).
- **Auth:** Supabase Auth (email/password, email confirmation disabled for dev)
- **RLS:** Policies in place. `my_company_id()` is SECURITY DEFINER. Users SELECT policy uses `id = auth.uid()` (not circular).
- **Signup flow:** `POST /api/v2/auth/register` on Flask backend creates company + user rows using service key (bypasses RLS).
- **Onboarding:** 4-step profile setup (contract size, NAICS, keywords, exclusions). Working end-to-end.
- **Flask API v2** (`backend/src/api/v2.py`): Feed, AI summary, opportunity detail, company profile, health check, register endpoints.
- **Feed UI:** Tinder-style swipe deck. Cards fly off correctly on swipe. Pass/Save buttons. Right swipes auto-added to pipeline. Undo (up to 3 cards). Bookmark action. Refills when running low (< 6 cards).
- **Bottom nav:** 3 tabs — Feed / Liked / Bookmarks.
- **Liked tab (`SavedList.jsx`):** Lists all right-swiped opportunities from the `pipeline` table. Shows agency, title, NAICS, set-aside, deadline, SAM.gov link. Remove button.
- **Bookmarks tab (`BookmarksList.jsx`):** Lists all bookmarked opportunities from the `bookmarks` table. Same layout as Liked. `db.getBookmarks()` and `db.removeBookmark()` in `api.js`.
- **Card detail view:** Slide-up bottom sheet (`DetailModal.jsx`) — zero AI calls, instant load. Shows structured scope (DLA parsed fields), raw description text, metadata grid, attachments, SAM.gov link, Pass/Save actions.
- **AI summaries:** Pre-generated on backend in background thread for top 12 cards per feed load (~4 parallel Haiku calls). Cached in `ai_summary` DB column. Used in Scope row on card when no structured DLA scope available.
- **Title cleaning:** SAM.gov PSC prefixes stripped (e.g. `J--`, `47--`). All-caps converted to title case with acronym preservation (HVAC, DOD, NSA, USAF, etc.).
- **Feed query:** Two-pass candidate pool. Pass A: all NAICS-matched opportunities (no date cap). Pass B: 1500 most recent diverse records. Deduped and merged. Filters to actionable notice types only. Expired records score 0.
- **Description fetch:** When description field is a SAM.gov URL, `_fetch_description_text()` follows it to get real HTML, strips tags, feeds 1500 chars into AI prompt.
- **Card UI (OpportunityCard):** Labeled row layout — Fit / Scope / Buyer / Effort rows. Disqualifier flag pills (clearance=red, cert=orange, vehicle=cyan, sole=yellow). Urgency-colored deadline dot. Score bar. Swipe direction hint overlay (imperative ref-based, zero re-renders).
- **NAICS/PSC lookup tables:** ~300 NAICS codes (6-digit) + PSC letter-prefix categories.
- **Disqualifier flags:** `_extract_flags()` regex on description for security clearance, CMMC, ITAR, DIBBS, GSA Schedule, sole source. Shown as colored pills.
- **Deadline extraction:** `_extract_deadline_from_description()` regex finds embedded deadline dates in description text. Fallback when DB `response_deadline` is null. Cards show `*` asterisk when derived.
- **Complexity estimation:** `_estimate_complexity()` returns High/Medium/Low from NAICS prefix rules.
- **DLA scope parsing:** `_parse_scope()` extracts NSN, quantity+unit, delivery days ADO, approved source, and item name from DLA description text.
- **format_card() fields:** `industry_label`, `location`, `flags`, `complexity`, `days_left`, `days_left_derived`, `description_text` (raw, truncated 8000 chars, null if URL), `attachments` (full JSON string).
- **sessionStorage versioning:** `CARD_SCHEMA_VERSION = 6`, key = `govscroll_cards_v6`. Bumping version auto-discards stale caches.
- **CORS fix:** `require_auth` decorator returns `200` for OPTIONS preflight before checking JWT.
- **Swipe recording:** `recordDetailView` is a no-op — doesn't write `direction: 'expand'` (violates DB CHECK constraint). Detail views tracked via `expanded` flag on actual swipe record.
- **Swipe count:** Loaded from Supabase on Feed mount. Persisted to sessionStorage.
- **Bulk ingestion:** `backend/src/ingestion/bulk_ingest.py` — two 6-month windows, 250-row upsert batches, `--full` and `--delta` modes.
- **Expiration job:** `backend/src/ingestion/expiration.py` — marks past-deadline records as expired nightly.
- **Behavioral scoring engine (Stage 2):** `compute_swipe_signals()` + `_behavioral_score()` — see Section 11 for full algorithm documentation.
- **Git + GitHub:** Repo at github.com/BradleyBrewington/Doom-Scroll-Gov-Contracts. Windows Credential Manager stores PAT.

### What is NOT yet built

- Keyboard navigation on feed (arrow keys / J/K)
- Nightly scheduled jobs (delta + expiration via cron/APScheduler)
- Email alerts
- Deployment (Railway)
- Mobile layout polish
- Evaluation harness (`evaluate_scorer()` — Lift@30 metric)
- Stage 3: keyword lift from liked corpus (activates at 100+ likes)
- Stage 4: vector embeddings + pgvector

### Known issues / next things to verify

1. **Onboarding data persistence** — the 4-step flow needs end-to-end verification that all data lands in Supabase (`companies`, `company_naics`, `company_keywords`). Likely works but hasn't been confirmed with data inspection.
2. **AI summary Anthropic key** — summaries generate fine when the key is valid. If Scope row shows empty for non-DLA cards, the `.env` key may be wrong or expired.
3. **Bookmarks table `created_at`** — `BookmarksList.jsx` uses `db.getBookmarks()` which orders by `created_at`. Verify the `bookmarks` table has this column.
4. **DetailModal `sam_url`** — uses `card.sam_url` first, falls back to `https://sam.gov/opp/{notice_id}/view`. If `notice_id` is null for some records, the SAM.gov link will be broken.
5. **DLA Scope row often empty** — DLA records have URL descriptions; `_parse_scope()` runs on the raw URL string, returns nothing. `ai_summary` also null for low-scoring DLA records. Acceptable trade-off.
6. **ai_analysis column unused** — Column exists in Supabase but analysis endpoint is no longer called from the frontend. Can be dropped later.
7. **Two-pass candidate pool latency** — Two Supabase round trips now instead of one. Monitor feed load time. If NAICS query returns very large result sets (common NAICS like 541512), may need a LIMIT on Pass A.

---

## 3. Project Structure

```
SAM_Opportunity_Search/
├── CLAUDE.md                          — this file
├── .env                               — local secrets (never committed)
├── .env.example                       — placeholder template
├── .gitignore
├── supabase/
│   └── schema.sql                     — full DB schema, run once in Supabase SQL Editor
├── backend/
│   ├── requirements.txt               — Python deps (Flask, supabase==2.28.3, anthropic, etc.)
│   └── src/
│       ├── api/
│       │   ├── server.py              — v1 legacy API (single-tenant, leave alone)
│       │   └── v2.py                  — v2 platform API (active development)
│       ├── ingestion/
│       │   ├── bulk_ingest.py         — SAM.gov bulk downloader
│       │   └── expiration.py          — nightly expiration job
│       ├── scrapers/                  — v1 scrapers (leave alone)
│       ├── scoring/                   — v1 rule engine (leave alone)
│       ├── parsers/                   — PDF/DOCX attachment parsing
│       └── notifications/             — email via SendGrid
├── frontend/
│   ├── .env.local                     — VITE_SUPABASE_URL, VITE_SUPABASE_ANON_KEY, VITE_API_URL
│   ├── package.json
│   └── src/
│       ├── main.jsx                   — entry point
│       ├── App.jsx                    — auth state machine (loading→login→onboard→feed)
│       ├── index.css                  — dark theme design system (CSS variables)
│       ├── App.css                    — spinner keyframe only
│       ├── lib/
│       │   ├── supabase.js            — Supabase client singleton
│       │   └── api.js                 — Flask v2 API client + Supabase direct write helpers
│       ├── pages/
│       │   ├── Login.jsx              — email/password auth + company signup
│       │   ├── Onboarding.jsx         — 4-step profile setup
│       │   └── Feed.jsx               — swipe deck + bottom nav (feed/liked/bookmarks)
│       └── components/
│           ├── OpportunityCard.jsx    — card UI (summary, badges, deadline, expand button)
│           ├── DetailModal.jsx        — bottom sheet detail view
│           ├── SavedList.jsx          — Liked tab: right-swiped pipeline items
│           └── BookmarksList.jsx      — Bookmarks tab: bookmarked items
```

---

## 4. How to Run Locally

**Terminal 1 — Flask API:**
```powershell
cd C:\Users\bmbre\OneDrive\Desktop\Projects\SAM_Opportunity_Search
py -3 backend/src/api/v2.py
```
Runs on http://localhost:5001

**Terminal 2 — React frontend:**
```powershell
cd C:\Users\bmbre\OneDrive\Desktop\Projects\SAM_Opportunity_Search\frontend
npm run dev
```
Runs on http://localhost:5174 (or 5173 if available)

**To run ingestion (one-time or nightly):**
```powershell
cd C:\Users\bmbre\OneDrive\Desktop\Projects\SAM_Opportunity_Search
py -3 backend/src/ingestion/bulk_ingest.py --full    # first time
py -3 backend/src/ingestion/bulk_ingest.py --delta   # nightly after
py -3 backend/src/ingestion/expiration.py            # nightly after delta
```

---

## 5. Environment Variables

**`.env`** (backend, root of project):
```
SAM_API_KEY=SAM-94f24b82-cc12-4946-82a3-c0e0f10689f9
ANTHROPIC_API_KEY=<current key>
SUPABASE_URL=https://zfipmsupwtrcusbmccpg.supabase.co
SUPABASE_SERVICE_KEY=<sb_secret_...>
```

**`frontend/.env.local`** (frontend, gitignored):
```
VITE_SUPABASE_URL=https://zfipmsupwtrcusbmccpg.supabase.co
VITE_SUPABASE_ANON_KEY=<sb_publishable_...>
VITE_API_URL=http://localhost:5001
```

---

## 6. Supabase RLS Notes

Critical — the RLS setup had a circular dependency bug that took significant time to resolve. Current working state:

- `my_company_id()` — SECURITY DEFINER function, bypasses RLS when reading users table
- `users` SELECT policy — `id = auth.uid()` (simple, no circular reference)
- `companies` SELECT/UPDATE — uses `my_company_id()` (works because function is SECURITY DEFINER)
- All INSERT policies — company/user creation goes through Flask `/api/v2/auth/register` using service key, which bypasses RLS entirely. Do NOT try to insert companies or users from the browser.
- `opportunities` — all authenticated users can read (public government data)

---

## 7. Build Phases

### Phase 1 — The Feed
**Goal:** Working end-to-end: account → onboarding → scored feed → swipe → pipeline entry.

- [x] Initialize git + push to GitHub
- [x] Database schema (Supabase PostgreSQL)
- [x] Bulk SAM.gov ingestion pipeline (two 6-month windows) — **35,914 records ingested**
- [x] Expiration job
- [x] Flask API v2 (feed, summary, detail, profile, register endpoints)
- [x] Feed scoring engine (weighted, profile-based)
- [x] React app scaffold (Vite + Supabase JS + react-tinder-card)
- [x] Auth flow (login, signup, session management)
- [x] Onboarding (4-step, handles missing company row)
- [x] Swipe deck UI + card component
- [x] Right-swipe → pipeline insert
- [x] Swipe mechanic works (cards fly off, deck advances correctly)
- [x] AI summaries pre-generated per feed load (parallel Haiku, cached in DB)
- [x] Card detail bottom sheet (DetailModal) — instant load, zero AI, raw SAM data
- [x] Title cleaning (PSC prefix removal, smart title case)
- [x] NAICS/PSC lookup tables expanded (~300 codes + PSC prefix categories)
- [x] Disqualifier flags (clearance, CMMC, ITAR, DIBBS, GSA Schedule, sole source)
- [x] Labeled row card layout (Fit / Scope / Buyer / Effort / Deadline)
- [x] Deadline extraction from description text (regex fallback, `days_left_derived` flag)
- [x] Complexity estimation from NAICS prefix
- [x] DLA scope parsing (NSN, qty, delivery, approved source, item name)
- [x] sessionStorage schema versioning (v6 — auto-invalidates stale caches)
- [x] CORS OPTIONS preflight fix in require_auth decorator
- [x] Swipe direction constraint fix (recordDetailView is no-op)
- [x] Undo button (up to 3 swipes, removes from pipeline if right-swipe)
- [x] Bookmark action (saves to `bookmarks` table, separate from pipeline)
- [x] Liked tab (SavedList.jsx — right-swipes / pipeline view)
- [x] Bookmarks tab (BookmarksList.jsx)
- [x] Bottom nav: Feed / Liked / Bookmarks
- [x] Swipe hint overlay (imperative ref on OpportunityCard, zero re-renders)
- [ ] **Verify onboarding saves all 4 steps to Supabase correctly**
- [ ] Keyboard navigation (arrow keys / J/K to swipe)
- [ ] Deploy to Railway

### Phase 2 — The Algorithm
**Goal:** Feed that measurably improves as users swipe. No Kanban. The swipe IS the data collection.

- [x] Two-pass candidate pool (NAICS-first, no date cap on matched records)
- [x] `compute_swipe_signals()` — behavioral signal extraction from swipe history (dwell-weighted, time-decayed, company-level, 30-min cache)
- [x] `_behavioral_score()` — 4-component score: NAICS affinity (40%), agency affinity (25%), value alignment (20%), keyword lift placeholder (15%)
- [x] Bayesian smoothing (Beta-Binomial with empirical prior, hierarchical NAICS fallback 6→4→2 digit)
- [x] Thompson sampling on NAICS + agency affinity (natural exploration, no fixed epsilon)
- [x] Lift-normalized scoring (raw_lift / (raw_lift + 1) — unseen = 0.5 neutral, not penalized)
- [x] Blend ramp: 0% behavioral at < 20 swipes → 80% behavioral at 250+ swipes
- [x] Hard exclusions (excluded agencies, exclusion keywords, expired deadlines) always return 0 regardless of behavioral signal
- [ ] Evaluation harness (`evaluate_scorer()` — temporal holdout, Lift@30 metric)
- [ ] "Your feed is improving" UI nudge at swipe milestones (20, 50, 100)
- [ ] Nightly delta ingestion + expiration cron (APScheduler or separate process)
- [ ] Deploy to Railway

### Phase 3 — Content Intelligence
**Goal:** Feed that learns what you actually win, not just what you say you do.

- [ ] Stage 3: Keyword lift from liked corpus (activates at 100+ likes, replaces keyword_comp placeholder)
- [ ] Stage 4: TF-IDF cosine similarity against liked corpus (activates at 100+ likes, 15+ unique NAICS in corpus)
- [ ] Evaluation: Lift@30 must reach ≥ 1.3× before promoting new scorer stages
- [ ] Email digest for deadline alerts
- [ ] Amendment tracking for liked opportunities

### Phase 4 — Semantic Intelligence
**Goal:** Semantic similarity that captures what keyword matching misses.

- [ ] Vector embeddings (sentence-transformers/all-MiniLM-L6-v2, runs locally on Railway — no API cost)
- [ ] pgvector column on opportunities table + HNSW index
- [ ] Nightly embedding batch for new records
- [ ] Cosine similarity to liked-opportunity embedding centroid
- [ ] Activates at 500+ likes per company
- [ ] Per-user divergence detection (if within-company user correlation < 0.5, split to per-user models)

### Phase 5 — The Network
- [ ] Teaming partner matching
- [ ] Public company profiles
- [ ] Collaborative filtering ("companies like yours also liked")

---

## 8. Tech Stack (Decided)

| Layer | Choice | Notes |
|---|---|---|
| Backend | Python + Flask | Keep v2.py; FastAPI migration deferred |
| Database | Supabase PostgreSQL | Hosted, free tier sufficient for now |
| Auth | Supabase Auth | Email confirmation disabled in dev |
| Frontend | React + Vite | v8.0.8 |
| Swipe | react-tinder-card 1.6.4 | Requires @react-spring/web as peer dep |
| AI summaries | Claude Haiku (claude-haiku-4-5-20251001) | Pre-generated in feed load, cached in DB |
| Hosting | Railway (planned) | Not yet deployed |
| Git | GitHub — BradleyBrewington/Doom-Scroll-Gov-Contracts | PAT in Windows Credential Manager |

---

## 9. Decision Log

| Date | Decision | Reason |
|---|---|---|
| 2026-04-18 | Pivot to multi-tenant platform | Product should work for any company |
| 2026-04-18 | Bulk ingestion over per-query API | Rate limits; bulk + local index is instant |
| 2026-04-18 | Swipe/feed UI as primary interaction | Generates behavioral training data |
| 2026-04-18 | Keep expired opportunities | Historical data for re-compete tracking |
| 2026-04-18 | CLAUDE.md as session briefing | Auto-loaded by Claude Code |
| 2026-04-20 | Company/user creation via Flask service key | Browser→Supabase inserts blocked by RLS regardless of policies |
| 2026-04-20 | SAM.gov date range max ~180 days | API returns 400 for ranges crossing year boundary; use two 6-month windows |
| 2026-04-20 | my_company_id() as SECURITY DEFINER | Fixes circular RLS dependency between users and companies tables |
| 2026-04-20 | Users SELECT policy: id = auth.uid() | Replaced circular company_id = my_company_id() policy |
| 2026-04-20 | Remove deadline filter from feed query | SAM.gov records often have null deadlines; filtering cut pool from 35k to ~24 records |
| 2026-04-20 | Pre-generate summaries in feed endpoint | Lazy frontend generation caused "no description" on all cards |
| 2026-04-20 | Remove card from cards array on swipe | react-tinder-card bounces card back if state isn't updated |
| 2026-04-21 | DetailModal: zero AI, raw SAM data only | AI analysis was always null; raw description_text loads instantly |
| 2026-04-21 | Labeled row layout on quickview card | Prose AI description truncated badly; labeled rows (Fit/Scope/Buyer/Effort) are scannable |
| 2026-04-21 | Deadline regex fallback from description text | ~40% of records have null response_deadline; regex extracts embedded dates |
| 2026-04-21 | sessionStorage schema versioning | Old cached payloads missing new fields were being served instead of fresh data |
| 2026-04-21 | CORS fix: OPTIONS returns 200 before JWT check | /analysis endpoint returning 401 on preflight |
| 2026-04-21 | recordDetailView is a no-op | direction='expand' violated swipes CHECK constraint (only left/right allowed) |
| 2026-04-25 | No Kanban board | Users have their own tracking systems; GovScroll's value is finding contracts, not managing them. Kanban is friction with no user payoff. |
| 2026-04-25 | Phase 2 = algorithm improvement, not pipeline UI | The feed quality IS the product. Every engineering hour should compound the recommendation flywheel. |
| 2026-04-25 | Two-pass candidate pool | Old 500-record date-ordered pool made high-scoring older NAICS matches invisible. Pass A fetches all NAICS matches regardless of date; Pass B fills with 1500 recent records. |
| 2026-04-25 | Behavioral blend ramp 0→80% over 250 swipes | Cold-start protection: new accounts get pure rule-based scoring until enough signal accumulates. Prevents noise from small samples dominating the feed. |
| 2026-04-25 | Unseen NAICS → 0.5 neutral (not Thompson sample) | Sampling from Beta(0.8, 9.2) prior produces heavily skewed draws near 0, not the intended neutral signal. Unseen = no information = neutral. Thompson sampling only applies when observations exist. |
| 2026-04-25 | Lift normalization: raw_lift / (raw_lift + 1) | Normalizes against baseline like-rate so a 10% like rate on a NAICS means something only relative to the company's global rate (~8%). Avoids penalizing rare-but-liked categories. |
| 2026-04-25 | Company-level behavioral model (not per-user) | Small firms share one BD strategy. Per-user models revisited when within-company user correlation drops below 0.5. |
| 2026-04-25 | Renamed "Saved" tab to "Liked" | "Saved" was ambiguous — confused with Bookmarks. Liked = right-swipes/pipeline. Bookmarks = deliberate 🔖 saves for later. |

---

## 10. What To Do Next Session

**Before starting:** Restart Flask (`py -3 backend/src/api/v2.py`) to pick up all scoring changes. Frontend cache will auto-discard (CARD_SCHEMA_VERSION=6).

**Immediate priorities:**

1. **Verify onboarding end-to-end** — complete all 4 steps as a new user and confirm data in Supabase: `companies` (contract_min, contract_max, clearance, set_asides), `company_naics`, `company_keywords`. This is the last unverified piece of Phase 1.

2. **Evaluation harness** — implement `evaluate_scorer(sb, company_id, holdout_fraction=0.2)` in v2.py. Temporal holdout split (chronological), compute Lift@30. Log to a `scorer_evals` table. This is the only way to know if Phase 2 scoring improvements are actually working.

3. **Keyboard navigation** — arrow left/right (or J/K) to trigger swipe. Small effort, meaningful for desktop BD users.

4. **Nightly cron** — set up APScheduler in v2.py (or separate process) to run delta + expiration nightly. DB goes stale without this.

5. **Deploy to Railway** — get it live to share. Env vars: SAM_API_KEY, ANTHROPIC_API_KEY, SUPABASE_URL, SUPABASE_SERVICE_KEY. Frontend: set VITE_API_URL to Railway backend URL.

---

## 11. Feed Algorithm — Full Documentation

This section documents the scoring architecture so future sessions can extend it without re-deriving decisions.

### Overview

The feed scorer has two layers that blend together as swipe data accumulates:

1. **Rule-based score** (`_rule_based_score`) — static matching against company profile. Pure logic, no learning. Always active.
2. **Behavioral score** (`_behavioral_score`) — learned from swipe history. Activates at 20+ swipes, ramps to 80% weight at 250+ swipes.

```
final_score = rule_score × (1 - blend) + behavioral_score × blend

where blend = min(0.80, total_swipes / 250)
```

Hard exclusions (excluded agencies, exclusion keywords, expired deadlines) always return 0 regardless of behavioral signals.

### Rule-Based Score (0–100 points)

| Signal | Max Points | Logic |
|---|---|---|
| NAICS exact match | 35 | opp NAICS in company_naics table |
| NAICS 4-digit group | 15 | partial credit for related codes |
| Set-aside alignment | 20 | matches eligibility; 10pts if unrestricted |
| Contract value in range | 15 | penalizes -10 if way outside range |
| Agency affinity | 15 | from company_agencies (past_perf / target) |
| Keyword overlap | 0–15 | keywords in title + description |
| Deadline urgency | 0–5 | +5 if ≤ 7 days, +2 if ≤ 21 days |

### Behavioral Score (0–100, 4 components)

```
behavioral_score = 100 × (
    0.40 × naics_affinity  +
    0.25 × agency_affinity +
    0.20 × value_alignment +
    0.15 × keyword_lift        ← neutral placeholder (0.5) until Stage 3
)
```

Each component is in [0, 1]. 0.5 = neutral/unseen. >0.5 = positive signal.

**naics_affinity / agency_affinity — Thompson-sampled lift:**
1. Look up weighted observations (rights, lefts) for the NAICS code
2. If no observations at any hierarchy level → return 0.5 (neutral, not penalized)
3. Otherwise: sample from Beta(a0 + wr, b0 + wl) posterior
4. Compute lift = sample / global_rate
5. Normalize: lift / (lift + 1) → maps lift=1.0 to 0.5, lift=2.0 to 0.67, lift=5.0 to 0.83

NAICS uses hierarchical fallback: 6-digit → 4-digit group → 2-digit sector. Falls back when finer level has < 5 weighted observations.

**value_alignment — log-Gaussian proximity:**
```
alignment = exp(-0.5 × ((log(opp_value) - log(centroid)) / sigma)²)
```
`centroid` and `sigma` are computed from the liked-opportunity value distribution. Returns 0.5 if no centroid data yet.

### Swipe Signal Quality

Each swipe is weighted by dwell time and behavior before accumulating into signals:

| Behavior | Weight |
|---|---|
| Expanded detail view + right-swipe | 2.0 (strongest positive) |
| Long dwell (>5s) + right-swipe | 1.5 |
| Fast (<2s) right-swipe | 0.5 |
| Long dwell (>10s) + left-swipe | 1.5 (strong negative) |
| Normal dwell + left-swipe | 1.0 |
| Fast (<2s) left-swipe | 0.2 (reflexive pass, weak) |

Signals also decay exponentially: `weight × min(time_decay, swipe_decay)` where half-lives are 45 days and 150 swipes respectively. This prevents stale preferences from permanently shaping the feed.

### Candidate Pool

Two Supabase queries per feed load:
- **Pass A:** All unswiped active opportunities matching company NAICS codes (no date ordering). Guarantees NAICS matches are always in the pool regardless of posted date.
- **Pass B:** 1500 most recent unswiped active opportunities (ordered by `posted_date DESC`). Provides exploration and catches non-NAICS opportunities.

Deduplicated in Python. Combined pool scored entirely.

### Blend Schedule

| Swipe count | Rule weight | Behavioral weight |
|---|---|---|
| 0–19 | 100% | 0% (signals not yet computed) |
| 20 | 92% | 8% |
| 50 | 80% | 20% |
| 100 | 60% | 40% |
| 200 | 20% | 80% |
| 250+ | 20% | 80% (capped) |

### Signal Cache

`compute_swipe_signals(sb, company_id)` results are cached in-memory per company for 30 minutes (`_SIGNAL_CACHE_TTL = 1800`). Thread-safe via `threading.Lock()`. Cache is process-local — restarting Flask clears it. This is intentional: signal recomputation on restart is cheap and avoids stale data.

### Future Stages

- **Stage 3 (100+ likes):** Keyword lift from liked corpus. Compute term frequency in liked vs. passed descriptions; score new opps by high-lift term presence. Replaces the 0.15 keyword_comp placeholder.
- **Stage 4 (100+ likes, 15+ unique NAICS):** TF-IDF cosine similarity against liked corpus.
- **Stage 5 (500+ likes):** Vector embeddings (sentence-transformers/all-MiniLM-L6-v2, local inference). Store in pgvector column on opportunities table. Score by cosine similarity to centroid of liked embeddings.

### Evaluation

Target metric: **Lift@30** = (right-swipe rate in top 30 scored cards) / global_right-swipe_rate. Baseline = 1.0. Goal before promoting Stage 3: Lift@30 ≥ 1.3× across companies with ≥ 100 swipes. Computed via temporal holdout (`evaluate_scorer()` — not yet implemented).

---

*Last updated: 2026-04-25 | Session 5: Liked/Bookmarks tabs, Phase 2 pivot (no Kanban), behavioral scoring engine (Stage 2), two-pass candidate pool, Bayesian smoothing, Thompson sampling, lift normalization, blend ramp, dwell-weighted signal decay.*
