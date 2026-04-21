# GovScroll — Master Briefing Document

> **For Claude Code:** Read this entire document at the start of every session before taking any action. It contains the product vision, architecture decisions, current build state, and what to work on next. Update the Progress Tracker and Decision Log sections as work is completed.

---

## 1. What This Is

A multi-tenant, feed-driven federal contracting opportunity intelligence platform built on SAM.gov data. Companies create accounts, configure their profile, and receive a personalized, algorithm-ranked feed of contract opportunities they can swipe through (Tinder-style) to surface high-fit work and train a per-account recommendation engine.

**Product name:** GovScroll

**The core insight:** Most SAM.gov tools are search engines. This is a recommendation engine with a social-media-style interaction loop. The swipe mechanic generates training data. The training data improves the feed. A better feed drives more engagement. More engagement drives more data. This flywheel is the product's moat.

**The target user:** Business development professionals at small-to-midsize government contractors who need to identify and track federal opportunities without spending hours manually searching SAM.gov.

---

## 2. Current State (v2 — In Progress)

### What is built and working
- **Monorepo structure:** `backend/` (Flask) + `frontend/` (React + Vite)
- **Database:** Supabase PostgreSQL with full schema (companies, users, opportunities, swipes, pipeline, company_naics, company_keywords, company_agencies). **35,914 opportunities ingested.**
- **Auth:** Supabase Auth (email/password, email confirmation disabled for dev)
- **RLS:** Policies in place. `my_company_id()` is SECURITY DEFINER. Users SELECT policy uses `id = auth.uid()` (not circular).
- **Signup flow:** `POST /api/v2/auth/register` on Flask backend creates company + user rows using service key (bypasses RLS).
- **Onboarding:** 4-step profile setup (contract size, NAICS, keywords, exclusions). Working end-to-end.
- **Flask API v2** (`backend/src/api/v2.py`): Feed, AI summary, opportunity detail, company profile, health check, register endpoints.
- **Feed UI:** Tinder-style swipe deck. Cards fly off correctly on swipe (fixed). Pass/Save buttons. Right swipes auto-added to pipeline. Refills when running low.
- **Card detail view:** Slide-up bottom sheet (`DetailModal.jsx`) with full opportunity details, AI summary, metadata grid, attachments, SAM.gov link, Pass/Save actions.
- **AI summaries:** Pre-generated on the backend for the first 6 cards per feed load (4 parallel Haiku calls, ~1s). Cached in DB. On-demand fallback for subsequent cards. Loading spinner shown while generating.
- **Title cleaning:** SAM.gov PSC prefixes stripped (e.g. `J--`, `47--`). All-caps converted to title case with acronym preservation (HVAC, DOD, NSA, USAF, etc.).
- **Feed query:** Shows all active opportunities (no deadline filter — null deadlines allowed). Scoring returns 0 for expired records. 500-candidate pool, 70/20/10 mix.
- **Bulk ingestion:** `backend/src/ingestion/bulk_ingest.py` — two 6-month windows, 250-row upsert batches, `--full` and `--delta` modes.
- **Expiration job:** `backend/src/ingestion/expiration.py` — marks past-deadline records as expired nightly.
- **Git + GitHub:** Repo at github.com/BradleyBrewington/Doom-Scroll-Gov-Contracts. Windows Credential Manager stores PAT.

### What is NOT yet built
- Keyboard navigation on feed (arrow keys / J/K)
- "Saved" / pipeline list page (right-swiped opportunities)
- Pipeline Kanban board (Phase 2)
- Nightly scheduled jobs (delta + expiration via cron/APScheduler)
- Email alerts
- Deployment (Railway)
- Mobile layout polish

### Known issues / next things to verify
1. **Onboarding data persistence** — the 4-step flow needs end-to-end verification that all data lands in Supabase (`companies`, `company_naics`, `company_keywords`). Likely works but hasn't been confirmed with data inspection.
2. **AI summary Anthropic key** — summaries generate fine when the key is valid. If cards show spinners indefinitely, the `.env` key may be wrong or expired.
3. **Feed score tuning** — with no NAICS/keywords set during onboarding, all opportunities score similarly. The feed works but feels random. Score improves once onboarding is complete.
4. **DetailModal `sam_url`** — uses `notice_id` from the card payload. If `notice_id` is null for some records, the SAM.gov link will be broken.

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
│       │   └── Feed.jsx               — swipe deck (primary surface)
│       └── components/
│           ├── OpportunityCard.jsx    — card UI (summary, badges, deadline, expand button)
│           └── DetailModal.jsx        — bottom sheet detail view
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
- [x] Feed scoring engine (weighted, profile-based, no ML)
- [x] React app scaffold (Vite + Supabase JS + react-tinder-card)
- [x] Auth flow (login, signup, session management)
- [x] Onboarding (4-step, handles missing company row)
- [x] Swipe deck UI + card component
- [x] Right-swipe → pipeline insert
- [x] Swipe mechanic works (cards fly off, deck advances correctly)
- [x] AI summaries pre-generated per feed load (parallel Haiku, cached in DB)
- [x] Card detail bottom sheet (DetailModal)
- [x] Title cleaning (PSC prefix removal, smart title case)
- [x] Feed query fixed — all active records shown, not just those with future deadlines
- [ ] **Verify onboarding saves all 4 steps to Supabase correctly**
- [ ] Keyboard navigation (arrow keys / J/K to swipe)
- [ ] "Saved" opportunities list page (pipeline view)
- [ ] Deploy to Railway

### Phase 2 — The Learning
- [ ] Full pipeline Kanban board (drag between stages)
- [ ] Deadline alerts (email digest)
- [ ] Pre-solicitation / Sources Sought surfacing in feed
- [ ] "Your feed improved" notification after N swipes
- [ ] Streak mechanic
- [ ] Amendment tracking for pipeline opportunities

### Phase 3 — The Intelligence
- [ ] Vector embeddings + semantic search
- [ ] Per-account ML recommendation model
- [ ] Win/loss analytics
- [ ] Market intelligence dashboard

### Phase 4 — The Network
- [ ] Teaming partner matching
- [ ] Public company profiles

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
| 2026-04-20 | Remove deadline filter from feed query | SAM.gov records often have null deadlines (awards, pre-sols); filtering by deadline > now cut pool from 35k to ~24 records |
| 2026-04-20 | Pre-generate summaries in feed endpoint | Lazy frontend generation caused "no description" on all cards; parallel Haiku calls add ~1s to feed load but arrive ready |
| 2026-04-20 | Remove card from cards array on swipe | react-tinder-card bounces card back if state isn't updated; must filter swiped card out immediately in onSwipe |

---

## 10. What To Do Next Session

**Immediate (finish Phase 1):**

1. **Verify onboarding end-to-end** — complete all 4 steps as a new user and confirm data in Supabase: `companies` (contract_min, contract_max, clearance, set_asides), `company_naics`, `company_keywords`. This is the last unverified piece of Phase 1.

2. **"Saved" opportunities page** — users who right-swipe have no way to see what they saved. Build a simple list view that queries the `pipeline` table joined to `opportunities`. Add a nav tab to switch between Feed and Saved.

3. **Keyboard navigation** — arrow left/right (or J/K) to trigger swipe. Small UX win, important for desktop users.

4. **Deploy to Railway** — get it live to share with investors. Environment variables: SAM_API_KEY, ANTHROPIC_API_KEY, SUPABASE_URL, SUPABASE_SERVICE_KEY. Frontend env: set VITE_API_URL to the Railway backend URL.

5. **Delta ingestion + nightly cron** — set up APScheduler in v2.py (or a separate process) to run delta + expiration nightly. Otherwise the database goes stale.

---

*Last updated: 2026-04-20 | Session 3: Swipe mechanic fixed, AI summaries pre-generated, card detail modal built, title cleaning, feed query fixed (35k+ opportunities now accessible).*
