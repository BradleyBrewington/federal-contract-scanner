# GovScroll — Master Briefing Document

> **For Claude Code:** Read this entire document at the start of every session before taking any action. It contains the product vision, architecture decisions, current build state, and what to work on next. Update the Progress Tracker and Decision Log sections as work is completed.

---

## 1. What This Is

A multi-tenant, feed-driven federal contracting opportunity intelligence platform built on SAM.gov data. Companies create accounts, configure their profile, and receive a personalized, algorithm-ranked feed of contract opportunities they can swipe through (Tinder-style) to surface high-fit work and train a per-account recommendation engine.

**Product name:** GovScroll

**The core insight:** Most SAM.gov tools are search engines. This is a recommendation engine with a social-media-style interaction loop. The swipe mechanic generates training data. The training data improves the feed. A better feed drives more engagement. More engagement drives more data. This flywheel is the product's moat.

**The target user:** Business development professionals at small-to-midsize government contractors who need to identify and track federal opportunities without spending hours manually searching SAM.gov.

**No Kanban. No pipeline management.** Users already have their own tracking systems. GovScroll's value is in *finding* contracts, not managing them. The swipe interaction is both the product and the data collection mechanism — we do not ask users to do extra work to train the algorithm.

**The discovery goal:** Surface opportunities the user didn't know to search for. NAICS codes are a cold-start seed, not the long-term query. As behavioral data accumulates, swipe history becomes the prior and the declared profile becomes irrelevant. The endgame is: "find contracts similar to what you've actually liked" — not "find contracts matching what you said you do."

---

## 2. Current State (v2 — In Progress)

### What is built and working

- **Monorepo structure:** `backend/` (Flask) + `frontend/` (React + Vite)
- **Database:** Supabase PostgreSQL with full schema (companies, users, opportunities, swipes, pipeline, bookmarks, company_naics, company_keywords, company_agencies). **35,914 opportunities ingested.** `ai_analysis` column added (TEXT, nullable).
- **Auth:** Supabase Auth (email/password, email confirmation disabled for dev)
- **RLS:** Policies in place. `my_company_id()` is SECURITY DEFINER. Users SELECT policy uses `id = auth.uid()` (not circular).
- **Signup flow:** `POST /api/v2/auth/register` on Flask backend creates company + user rows using service key (bypasses RLS). App.jsx uses `.maybeSingle()` so new users (no DB row yet) get auth user object passed to Onboarding instead of crashing.
- **Onboarding:** 4-step profile setup (contract size, NAICS, keywords, exclusions). LocalStorage draft survives tab eviction — all fields persist in real time, cleared on completion. Keywords saved once at Step 4 (not twice). Verified end-to-end.
- **Flask API v2** (`backend/src/api/v2.py`): Feed, AI summary, opportunity detail, company profile, health check, register endpoints.
- **Feed UI:** Tinder-style swipe deck. Cards fly off correctly on swipe. Pass/Save buttons. Right swipes auto-added to pipeline. Undo (up to 3 cards). Bookmark action. Refills when running low (< 6 cards).
- **Bottom nav:** 3 tabs — Feed / Liked / Bookmarks.
- **Liked tab (`SavedList.jsx`):** Lists all right-swiped opportunities from the `pipeline` table.
- **Bookmarks tab (`BookmarksList.jsx`):** Lists all bookmarked opportunities from the `bookmarks` table.
- **Card detail view:** Slide-up bottom sheet (`DetailModal.jsx`) — zero AI calls, instant load. `maxHeight: 82svh` so header/close button never hide behind iOS browser chrome. Close button 44×44px tap target.
- **Details + SAM.gov buttons:** Rendered outside TinderCard DOM (siblings in deck, not children) so touch events are not intercepted by react-tinder-card's native addEventListener. This was the root cause of mobile tap failures.
- **AI summaries:** Pre-generated on backend in background thread for top 12 cards per feed load (~4 parallel Haiku calls). Cached in `ai_summary` DB column.
- **Title cleaning:** SAM.gov PSC prefixes stripped. All-caps converted to title case with acronym preservation.
- **Feed query:** Three-slot output mix: 70% top scorers, 20% exploration (mid-range random), 10% urgency (closing ≤14 days). Two-pass candidate pool. Pass A: all NAICS-matched opportunities (no date cap). Pass B: 1500 most recent diverse records. Deduped and merged.
- **Description fetch:** When description field is a SAM.gov URL, follows it to get real HTML, strips tags.
- **Card UI (OpportunityCard):** Labeled row layout — Fit / Scope / Buyer / Effort rows. Disqualifier flag pills. Urgency-colored deadline dot. Score bar. Responsive card width: `min(360px, calc(100vw - 32px))`.
- **Keyboard navigation:** Arrow left/right and J/L to swipe, Z to undo. Hidden on touch devices via `@media (pointer: coarse)`.
- **Behavioral scoring engine (Stage 2):** `compute_swipe_signals()` + `_behavioral_score()` — see Section 11 for full algorithm documentation.
- **Deployment:** Railway (Flask backend) + Vercel (React frontend). Both auto-deploy on GitHub push.
- **Git + GitHub:** Repo at github.com/BradleyBrewington/Doom-Scroll-Gov-Contracts. Windows Credential Manager stores PAT.

### What is NOT yet built

- "Your feed is improving" UI nudge at swipe milestones
- Nightly scheduled jobs (delta + expiration — APScheduler code exists but verify it runs on Railway)
- Email alerts
- Description enrichment (attachment text extraction, quality scoring, multi-field embedding input)
- Vector embeddings + pgvector (Pass C candidate pool)
- Discovery metrics instrumentation
- Incumbency/winnability scoring (USASpending integration)

### Known issues / next things to verify

1. **Capabilities statement is inert** — saved to `companies.capabilities_statement` but `v2.py` never reads it. It's a placeholder for Stage 3 keyword extraction. Do not tell users it affects their feed until it does.
2. **AI summary Anthropic key** — summaries generate fine when the key is valid. If Scope row shows empty for non-DLA cards, the `.env` key may be wrong or expired.
3. **Nightly cron on Railway** — APScheduler BackgroundScheduler is initialized in v2.py. Verify it actually fires on Railway (check logs for "Running nightly jobs" at 02:00 UTC). If Railway sleeps the dyno, the scheduler won't fire.
4. **DLA Scope row often empty** — DLA records have URL descriptions; `_parse_scope()` runs on the raw URL string, returns nothing. Acceptable trade-off.
5. **ai_analysis column unused** — Column exists in Supabase but analysis endpoint is no longer called from the frontend. Can be dropped later.
6. **JSON-wrapped descriptions** — Some records have `{"description":"..."}` in the description field. `DetailModal.jsx` has `unwrapDescription()` to handle this at render time. The root fix is re-running format_card on those records at ingestion.

---

## 3. Project Structure

```
SAM_Opportunity_Search/
├── CLAUDE.md                          — this file
├── .env                               — local secrets (never committed)
├── .env.example                       — placeholder template
├── .gitignore
├── railway.json                       — Railway deploy config
├── vercel.json                        — Vercel build config
├── requirements.txt                   — root-level copy for Railpack detection
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
│       ├── parsers/                   — PDF/DOCX attachment parsing (wire into ingestion for Stage 3)
│       └── notifications/             — email via SendGrid
├── frontend/
│   ├── .env.local                     — VITE_SUPABASE_URL, VITE_SUPABASE_ANON_KEY, VITE_API_URL
│   ├── package.json
│   └── src/
│       ├── main.jsx                   — entry point
│       ├── App.jsx                    — auth state machine (loading→login→onboard→feed)
│       ├── index.css                  — dark theme design system (CSS variables)
│       ├── lib/
│       │   ├── supabase.js            — Supabase client singleton
│       │   └── api.js                 — Flask v2 API client + Supabase direct write helpers
│       ├── pages/
│       │   ├── Login.jsx              — email/password auth + company signup
│       │   ├── Onboarding.jsx         — 4-step profile setup (localStorage draft persistence)
│       │   └── Feed.jsx               — swipe deck + bottom nav (feed/liked/bookmarks)
│       └── components/
│           ├── OpportunityCard.jsx    — card UI (Details/SAM buttons excluded from TinderCard DOM)
│           ├── DetailModal.jsx        — bottom sheet detail view (82svh, unwrapDescription)
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

**Note:** The live site (Vercel + Railway) auto-deploys on every GitHub push. Local dev is only needed when actively writing code.

**To run ingestion:**
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
- [x] Auth flow (login, signup, session management) — `.maybeSingle()` handles new users with no DB row
- [x] Onboarding (4-step, localStorage draft, verified end-to-end)
- [x] Swipe deck UI + card component
- [x] Right-swipe → pipeline insert
- [x] AI summaries pre-generated per feed load (parallel Haiku, cached in DB)
- [x] Card detail bottom sheet (DetailModal) — instant load, zero AI, raw SAM data
- [x] Title cleaning, NAICS/PSC lookup tables, disqualifier flags
- [x] Labeled row card layout (Fit / Scope / Buyer / Effort / Deadline)
- [x] Deadline extraction from description text (regex fallback)
- [x] sessionStorage schema versioning (v6)
- [x] Undo button, Bookmark action, Liked tab, Bookmarks tab, Bottom nav
- [x] Keyboard navigation (arrow keys / J/L to swipe, Z to undo)
- [x] Mobile UI fixes (responsive card width, Details button outside TinderCard, DetailModal height)
- [x] Deploy to Railway (backend) + Vercel (frontend)

### Phase 2 — The Algorithm
**Goal:** Feed that measurably improves as users swipe.

- [x] Two-pass candidate pool (Pass A: all NAICS matches; Pass B: 1500 recent)
- [x] Three-slot output mix (70% top / 20% exploration / 10% urgency)
- [x] `compute_swipe_signals()` — behavioral signal extraction (dwell-weighted, time-decayed, 30-min cache)
- [x] `_behavioral_score()` — 4-component score: NAICS affinity (40%), agency affinity (25%), value alignment (20%), keyword placeholder (15%)
- [x] Bayesian smoothing (Beta-Binomial, hierarchical NAICS fallback 6→4→2 digit)
- [x] Thompson sampling on NAICS + agency affinity
- [x] Lift-normalized scoring, blend ramp (0% behavioral at <20 swipes → 80% at 250+)
- [x] Hard exclusions always return 0
- [x] Evaluation harness (`evaluate_scorer()` — Lift@30 + out-of-NAICS like rate + exploration breadth, logged to `scorer_evals` table, exposed via `GET /api/v2/eval`)
- [ ] "Your feed is improving" UI nudge at swipe milestones (20, 50, 100)
- [ ] Verify nightly APScheduler fires correctly on Railway

### Phase 3 — Description Enrichment
**Goal:** Make content-based scoring reliable. Everything downstream (embeddings, TF-IDF) degrades on bad descriptions. Fix the input before building the model.

**Do this before embeddings. Do not skip it.**

- [ ] Wire `parsers/` into bulk ingestion — extract text from PDF/DOCX attachments at write time, store in `description_full` column
- [ ] Description quality scoring — word count, unique term count, boilerplate ratio, numeric scope presence. Records below threshold fall back to `title + NAICS title + agency` as content signal
- [ ] Multi-field content string — concatenate `title + agency + NAICS title + description_full` as the canonical text field for all downstream ML. Not just `description`.
- [ ] Re-run format_card on records with JSON-wrapped descriptions (`{"description":"..."}`) to fix at source
- [ ] Skip TF-IDF entirely — not worth building something to immediately deprecate. Go straight to embeddings.

### Phase 4 — Vector Embeddings (Discovery Engine)
**Goal:** Replace NAICS as the primary discovery mechanism with semantic similarity to liked opportunities.

**Architecture decisions (locked):**
- Model: `sentence-transformers/all-MiniLM-L6-v2` (384-dim, ~14ms/record on CPU, no API cost, local on Railway)
- Pin model version in a config constant (`EMBEDDING_MODEL_VERSION`). Store version alongside each vector. Treat model upgrades as migrations, not incremental changes.
- Embed at ingestion time (inline, not nightly batch). 14ms × 250 records = 3-4s per delta run. Acceptable. A 24-hour embedding lag contradicts the "surface before competitors" value prop.
- pgvector column on opportunities table + HNSW index for approximate nearest-neighbor search
- Liked-centroid: mean of all liked-opportunity embedding vectors per company. Recompute when swipe_count changes, cache 30 min alongside signal cache.

**Candidate pool evolution (Pass C):**
- Pass A: all NAICS matches (unchanged, always)
- Pass B: `min(10000, 1500 + 20 × swipe_count)` recent records, grows with engagement
- Pass C: vector similarity pool, activates at 100 swipes. `min(5000, 50 × swipe_count)` records, deduplicated against A+B
- At 500+ swipes, Pass C dominates and Pass B becomes redundant

**Agency-conditioned similarity:** Agency affinity signal (≥3 right-swipes from an agency) restricts a portion of Pass C to that agency's portfolio before running similarity search. Prevents "all NIH things" noise — forces "NIH things that look like the NIH things you liked."

**Recency boost:** Opportunities posted <48h get 1.2× score multiplier, decaying linearly to 1.0× at 7 days. Tiebreaker only — a highly relevant 6-month-old record still beats an irrelevant fresh one.

**Implementation checklist:**
- [ ] Add `description_full` column + `embedding` vector(384) column + `embedding_model_version` column to opportunities table
- [ ] Add pgvector extension + HNSW index
- [ ] Inline embedding at ingestion (sentence-transformers loaded at startup)
- [ ] `compute_liked_centroid(sb, company_id)` — mean of liked-opp vectors, cached
- [ ] Pass C query using pgvector `<=>` cosine distance operator
- [ ] Agency-conditioned Pass C subset
- [ ] Recency boost multiplier
- [ ] Update blend schedule to account for Pass C activation at 100 swipes
- [ ] Evaluation: Lift@30 ≥ 1.3× required before promoting embedding scorer

### Phase 5 — Discovery Metrics
**Goal:** Instrument whether the system is actually achieving discovery, not just prediction accuracy.

Lift@30 measures prediction accuracy — how well the algorithm predicts what the user already likes. It does NOT measure discovery. A perfect Lift@30 system is a filter bubble. You need orthogonal metrics.

**Three required discovery metrics:**

1. **Out-of-NAICS like rate** — % of right-swipes whose opportunity falls outside the user's declared NAICS codes. Track over time. Flat or declining = tightening filter bubble. Growing = discovery working.

2. **Surprise-weighted lift** — weight each liked opportunity by inverse similarity to the user's stated profile at swipe time. A right-swipe on an opportunity with 0 keyword overlap and a different NAICS sector counts more toward this metric than one that exactly matches the profile. Rewards serendipitous finds.

3. **Exploration breadth** — count of distinct NAICS 4-digit groups in the user's liked corpus over time. Good discovery engine grows this number. Filter bubble keeps it flat.

**Implementation:**
- [ ] Log these three metrics per company to a `discovery_metrics` table on each feed load (or nightly batch)
- [x] `evaluate_scorer()` — temporal holdout (oldest 80% = training, newest 20% = holdout), Lift@30 + out-of-NAICS like rate + exploration breadth. Needs `scorer_evals` table created in Supabase (DDL in schema.sql). Endpoint: `GET /api/v2/eval`.
- [ ] Instrument before iterating on the embedding model — can't improve what you can't measure

### Phase 6 — Incumbency & Winnability
**Goal:** Layer "can we win this?" on top of "is this relevant?"

Opportunity characterization (what a contract is) and winnability (whether you can win it) are separate signals. Keep them as separate scoring components — do not mix them into the similarity score.

**USASpending integration:**
- Enrich each opportunity at ingestion with an `incumbency_risk` score: who won the last award for this agency/NAICS/PSC combination, how recently, how often they repeat
- Produces a `winnability_score` component that blends into final score alongside similarity and rule-based signals
- Agencies that consistently award to one vendor are lower-priority than open competitions

*This is Stage 5+ territory. Flag it as future work. Do not build it before embeddings and discovery metrics.*

### Phase 7 — The Network
- [ ] Teaming partner matching
- [ ] Public company profiles
- [ ] Collaborative filtering ("companies like yours also liked")

---

## 8. Tech Stack (Decided)

| Layer | Choice | Notes |
|---|---|---|
| Backend | Python + Flask | Keep v2.py; FastAPI migration deferred |
| Database | Supabase PostgreSQL | Hosted, free tier sufficient for now |
| Vector search | pgvector + HNSW index | To be added for Phase 4 |
| Embeddings | sentence-transformers/all-MiniLM-L6-v2 | Local on Railway, no API cost, 384-dim |
| Auth | Supabase Auth | Email confirmation disabled in dev |
| Frontend | React + Vite | v8.0.8 |
| Swipe | react-tinder-card 1.6.4 | Requires @react-spring/web ^9.x (not ^10) |
| AI summaries | Claude Haiku (claude-haiku-4-5-20251001) | Pre-generated in feed load, cached in DB |
| Hosting | Railway (backend) + Vercel (frontend) | Both live, auto-deploy on push |
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
| 2026-04-20 | Company/user creation via Flask service key | Browser→Supabase inserts blocked by RLS |
| 2026-04-20 | SAM.gov date range max ~180 days | API returns 400 for ranges crossing year boundary |
| 2026-04-20 | my_company_id() as SECURITY DEFINER | Fixes circular RLS dependency |
| 2026-04-20 | Users SELECT policy: id = auth.uid() | Replaced circular company_id = my_company_id() policy |
| 2026-04-20 | Remove deadline filter from feed query | SAM.gov records often have null deadlines; filtering cut pool from 35k to ~24 records |
| 2026-04-20 | Pre-generate summaries in feed endpoint | Lazy frontend generation caused "no description" on all cards |
| 2026-04-21 | DetailModal: zero AI, raw SAM data only | AI analysis was always null; raw description_text loads instantly |
| 2026-04-21 | Labeled row layout on quickview card | Prose AI description truncated badly; labeled rows are scannable |
| 2026-04-21 | sessionStorage schema versioning | Old cached payloads missing new fields were being served |
| 2026-04-21 | recordDetailView is a no-op | direction='expand' violated swipes CHECK constraint |
| 2026-04-25 | No Kanban board | Users have their own tracking systems. GovScroll's value is finding contracts, not managing them. |
| 2026-04-25 | Two-pass candidate pool | Old 500-record pool made high-scoring older NAICS matches invisible |
| 2026-04-25 | Behavioral blend ramp 0→80% over 250 swipes | Cold-start protection; prevents noise from small samples |
| 2026-04-25 | Unseen NAICS → 0.5 neutral (not Thompson sample) | Beta(0.8, 9.2) prior produces heavily skewed near-zero draws. Unseen = neutral. |
| 2026-04-25 | Lift normalization: raw_lift / (raw_lift + 1) | Normalizes against baseline like-rate. Avoids penalizing rare-but-liked categories. |
| 2026-04-25 | Company-level behavioral model (not per-user) | Small firms share one BD strategy. Revisit at within-company user correlation < 0.5. |
| 2026-04-25 | Renamed "Saved" tab to "Liked" | "Saved" was ambiguous with Bookmarks. |
| 2026-04-25 | Details/SAM buttons outside TinderCard DOM | react-tinder-card uses native addEventListener. React synthetic onTouchStart fires at root after native listeners — stopPropagation cannot prevent TinderCard from consuming the touch and calling preventDefault, suppressing the click. Fix: render buttons as siblings to TinderCard, not descendants. |
| 2026-04-25 | DetailModal maxHeight: 82svh | iOS Safari vh includes browser chrome. Sheet was pushing header behind address bar. svh = small viewport height, always excludes chrome. |
| 2026-04-27 | localStorage draft for onboarding | iOS Safari evicts backgrounded tabs. All form state lost on tab switch. Draft keyed to user ID, persists every keystroke, cleared on completion. |
| 2026-04-27 | Keywords saved once at Step 4 only | Step 3 previously saved regular keywords; Step 4 re-saved all. A page refresh between steps would delete regular keywords before exclusions ran. Consolidated to single save at completion. |
| 2026-04-27 | .maybeSingle() for user row lookup | New users have no DB row until Onboarding calls /register. .single() threw 406, leaving user=null, crashing Onboarding on user.id. maybeSingle() returns null cleanly; App.jsx falls back to session.user. |
| 2026-04-27 | Skip TF-IDF entirely | Gap between TF-IDF and embeddings in implementation effort is smaller than the gap in capability. Building TF-IDF first means building something to immediately deprecate. |
| 2026-04-27 | Description enrichment before embeddings | SAM.gov descriptions are inconsistent. Both TF-IDF and embeddings degrade silently on bad input. Fix the input first — attachment text, multi-field concatenation, quality scoring. |
| 2026-04-27 | Embed at ingestion, not nightly batch | 24-hour embedding lag contradicts "surface before competitors" value prop. 14ms/record with MiniLM is negligible per delta run. |
| 2026-04-27 | Pin embedding model version | Model upgrades require re-embedding entire corpus. Treat as migrations, not incremental changes. Store version alongside each vector. |
| 2026-04-27 | Agency affinity conditioned on content | Unconditional agency affinity ("all NIH things") is noise. Correct signal: "NIH things that look like the NIH things you liked." Restrict agency-led Pass C to similarity search within target agency portfolio. |
| 2026-04-27 | Discovery metrics separate from Lift@30 | Lift@30 measures prediction accuracy. A perfect Lift@30 is a filter bubble. Need orthogonal metrics: out-of-NAICS like rate, surprise-weighted lift, exploration breadth. Without these, you optimize a system that gets better at confirming what users already think. |
| 2026-04-27 | Pool composition ramp tied to swipe count | Pass B: min(10000, 1500 + 20×swipes). Pass C: activates at 100 swipes, min(5000, 50×swipes). Mirrors blend ramp schedule so pool and scoring weights evolve together. |

---

## 10. What To Do Next Session

**Current state:** Platform is live on Railway + Vercel. Onboarding is verified. Mobile UI is functional. Phase 2 behavioral scoring is built.

**Priority order:**

1. **Create `scorer_evals` table in Supabase** — run the DDL from `supabase/schema.sql` (the `scorer_evals` block) in the Supabase SQL Editor. The eval harness is implemented in v2.py and callable via `GET /api/v2/eval`, but will fail until this table exists. Call the endpoint after creating the table to confirm.

2. **Verify nightly APScheduler on Railway** — check Railway logs for "Running nightly jobs" at 02:00 UTC. If the dyno sleeps, the scheduler won't fire. May need a Railway cron job or external ping to keep it alive.

3. **Description enrichment (Phase 3 start)** — add `description_full` column to opportunities table. Wire `parsers/` PDF/DOCX extraction into `bulk_ingest.py` so attachment text is extracted at write time. Add description quality scoring to `format_card()`.

4. **NAICS hierarchy expansion** — cheap, ship anytime. When behavioral data shows ≥5 right-swipes in a 6-digit code, include sibling codes at the 4-digit level in Pass A. Uses the existing hierarchical NAICS fallback logic in the opposite direction. This is a small coverage improvement (~10-15%), not a discovery mechanism — do not confuse it with embeddings.

---

## 11. Feed Algorithm — Full Documentation

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

Each swipe is weighted by dwell time and behavior:

| Behavior | Weight |
|---|---|
| Expanded detail view + right-swipe | 2.0 (strongest positive) |
| Long dwell (>5s) + right-swipe | 1.5 |
| Fast (<2s) right-swipe | 0.5 |
| Long dwell (>10s) + left-swipe | 1.5 (strong negative) |
| Normal dwell + left-swipe | 1.0 |
| Fast (<2s) left-swipe | 0.2 (reflexive pass, weak) |

Signals decay exponentially: `weight × min(time_decay, swipe_decay)` where half-lives are 45 days and 150 swipes respectively.

### Candidate Pool (Current)

- **Pass A:** All unswiped active NAICS-matched opportunities (no date cap, no limit)
- **Pass B:** `min(10000, 1500 + 20 × swipe_count)` most recent unswiped active opportunities, deduplicated against Pass A
- **Pass C (Phase 4):** Vector similarity pool, activates at 100 swipes, `min(5000, 50 × swipe_count)` records

### Output Mix

- 70% top scorers (ranked by final score)
- 20% exploration (random sample from positions 71–120)
- 10% urgency (closing ≤14 days, from remaining pool)

### Blend Schedule

| Swipe count | Rule weight | Behavioral weight |
|---|---|---|
| 0–19 | 100% | 0% |
| 20 | 92% | 8% |
| 50 | 80% | 20% |
| 100 | 60% | 40% |
| 200 | 20% | 80% |
| 250+ | 20% | 80% (capped) |

### Signal Cache

`compute_swipe_signals()` cached in-memory per company for 30 minutes. Thread-safe via `threading.Lock()`. Process-local — restarting Flask clears it intentionally.

---

## 12. Discovery Architecture — Goals and Design

This section documents the architectural goal and design decisions for the discovery engine so future sessions build toward it coherently.

### The Core Problem

NAICS codes are a cold-start seed, not a long-term query. Users enter inaccurate codes, incomplete codes, or codes that don't capture what they actually win. The stated goal of GovScroll is to surface opportunities the user didn't know to search for. That requires inverting the prior/posterior relationship over time:

- **Cold start (0–50 swipes):** Profile is the prior. Behavior modifies it.
- **Mature (250+ swipes):** Behavior is the prior. Profile is irrelevant.

The gap between "search engine" and "recommendation engine" is exactly this inversion. Most personalization features fail because they treat behavior as a re-ranker on top of a fixed query. The correct architecture treats behavior as the query itself.

### What NAICS Expansion Can and Cannot Do

Hierarchical NAICS expansion (high affinity in 541715 → include all 5417 children in Pass A) is a cheap, early improvement. It solves the adjacent-NAICS problem — codes that are structurally close in the NAICS tree.

It cannot bridge structural gaps between branches. 541715 (R&D in Physical Sciences) and 334413 (Semiconductor Manufacturing) are in completely different sectors. No hierarchical walk connects them. NAICS expansion is a 10-15% coverage improvement, not a discovery mechanism. Do not over-invest in it.

### Why Embeddings Are the Actual Answer

Vector embeddings characterize what a contract *is* well enough to find structurally unrelated opportunities that are semantically similar. An EIS-related contract under 541715 and one under 334515 that both use "electrochemical impedance spectroscopy" in their scope will be close in embedding space even though they share almost no NAICS hierarchy.

The liked-corpus centroid (mean of all liked-opportunity vectors) becomes the user's "taste profile" in semantic space. New opportunities are scored by cosine similarity to that centroid. This is immune to wrong NAICS codes because it's built from revealed preference.

### Description Quality Is Non-Negotiable

Both TF-IDF and embeddings degrade silently on bad descriptions. A 12-word boilerplate gets a noisy embedding that produces confident-but-wrong similarity scores. SAM.gov descriptions are notoriously inconsistent — some are 2,000 words of detailed scope, some say "see attached SOW."

**The fix before building the model:**
1. Extract attachment text at ingestion (PDF/DOCX via existing `parsers/`). Store in `description_full`.
2. Score description quality (word count, term diversity, boilerplate phrases, numeric scope signals). Below-threshold records fall back to `title + NAICS title + agency` as the embedding input.
3. Embed the multi-field concatenation: `title + agency + NAICS title + description_full`. Not just description. Title often carries more signal than a short boilerplate.

### The Measurement Problem

Lift@30 measures prediction accuracy. A system that perfectly predicts what the user already likes has Lift@30 = ∞ and is a complete filter bubble. You cannot use Lift@30 alone to know if the discovery engine is working.

The three required discovery metrics:

| Metric | Definition | Good signal |
|---|---|---|
| Out-of-NAICS like rate | % of right-swipes outside declared NAICS codes | Growing over time |
| Surprise-weighted lift | Lift@30 weighted by inverse profile-similarity of liked opps | Higher = finding things keyword search would miss |
| Exploration breadth | Distinct NAICS 4-digit groups in liked corpus over time | Growing = discovery working, flat = filter bubble |

Instrument these before iterating on the embedding model. Without them, you cannot distinguish a better recommendation engine from a better filter bubble.

### Incumbency and Winnability (Future)

Opportunity characterization (what a contract is) and winnability (can you win it?) are separate dimensions. Do not mix them into the similarity score — keep them as separate scoring components so they can be tuned independently.

When built: enrich each opportunity at ingestion with `incumbency_risk` from USASpending award history (who won last time, how recently, how often they repeat). Produces a `winnability_score` that blends into final score alongside similarity and rule-based signals. The USASpending data is already available — this is a Phase 6 integration.

---

*Last updated: 2026-04-27 | Session 6: Mobile fixes (Details button outside TinderCard, DetailModal svh, responsive width), onboarding localStorage draft, signup .maybeSingle() fix, discovery architecture design (skip TF-IDF, embeddings + description enrichment, discovery metrics, pool composition ramp, agency-conditioned similarity, incumbency future work).*
