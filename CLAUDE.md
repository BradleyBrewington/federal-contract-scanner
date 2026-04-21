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
- **Database:** Supabase PostgreSQL with full schema (companies, users, opportunities, swipes, pipeline, company_naics, company_keywords, company_agencies)
- **Auth:** Supabase Auth (email/password, email confirmation disabled for dev)
- **RLS:** Policies in place. Key fix applied: `my_company_id()` is SECURITY DEFINER. Users SELECT policy uses `id = auth.uid()` (not circular).
- **Signup flow:** `POST /api/v2/auth/register` on Flask backend creates company + user rows using service key (bypasses RLS). Frontend calls this after Supabase Auth signup.
- **Onboarding:** 4-step profile setup (contract size, NAICS, keywords, exclusions). Handles case where company row is missing — prompts for company name and calls register on first Continue click.
- **Flask API v2** (`backend/src/api/v2.py`): Feed endpoint, AI summary endpoint, opportunity detail, company profile read, health check, register endpoint.
- **Feed UI:** Tinder-style swipe deck with `react-tinder-card`. Pass/Save buttons. Dwell time tracking. Right swipes auto-added to pipeline table. Feed refills when running low.
- **Opportunity cards:** Agency icon, title, AI summary (fetched on-demand for top card), value badge, NAICS/set-aside/location badges, urgency-colored deadline, SAM.gov link, score bar.
- **Bulk ingestion:** `backend/src/ingestion/bulk_ingest.py` — downloads SAM.gov in two 6-month windows (API rejects ranges > ~180 days crossing year boundary), upserts to Supabase in 250-row batches. Supports `--full` and `--delta` modes.
- **Expiration job:** `backend/src/ingestion/expiration.py` — marks past-deadline records as expired nightly.
- **Git + GitHub:** Repo at github.com/BradleyBrewington/Doom-Scroll-Gov-Contracts. Windows Credential Manager stores PAT for auto-push.

### What is NOT yet built
- Feed has no data yet (ingestion needs to complete successfully — see known issues)
- Pipeline Kanban board (Phase 2)
- Keyboard navigation on feed (J/K, arrow keys)
- Expand-to-detail view when tapping a card
- Mobile layout polish
- Nightly scheduled jobs (delta + expiration)
- Email alerts
- Deployment (Railway)

### Known issues to fix next session
1. **SAM.gov ingestion not yet successful** — needs to be run and confirmed. Check `data/last_ingest.txt` exists after run. Verify `opportunities` table row count in Supabase.
2. **Feed shows empty** until ingestion completes. The feed endpoint works — it just returns 0 cards with `exhausted: true`.
3. **`db.saveCompany` / `db.saveNaics` / `db.saveKeywords` in api.js** write directly from the browser using the anon key. These hit RLS. The UPDATE policy uses `my_company_id()` which should work now, but needs testing end-to-end through onboarding.
4. **Onboarding completion** — the full 4-step flow has not been successfully tested end-to-end. Need to verify data lands in Supabase after each step.
5. **`supabase.from('table')` vs `supabase.table('table')`** — Python SDK uses `.table()`, JS SDK uses `.from()`. Don't mix them.

---

## 3. Project Structure

```
Doom-Scroll-Gov-Contracts/
├── CLAUDE.md                          — this file
├── .env                               — local secrets (never committed)
├── .env.example                       — placeholder template
├── .gitignore
├── supabase/
│   └── schema.sql                     — full DB schema, run once in Supabase SQL Editor
├── backend/
│   ├── requirements.txt               — Python deps (Flask, supabase==2.28.3, anthropic, etc.)
│   ├── src/
│   │   ├── api/
│   │   │   ├── server.py              — v1 legacy API (single-tenant, leave alone)
│   │   │   └── v2.py                  — v2 platform API (active development)
│   │   ├── ingestion/
│   │   │   ├── bulk_ingest.py         — SAM.gov bulk downloader
│   │   │   └── expiration.py          — nightly expiration job
│   │   ├── scrapers/                  — v1 scrapers (SAM, SBIR, Grants, USASpending)
│   │   ├── scoring/                   — v1 rule engine + AI enrichment
│   │   ├── parsers/                   — PDF/DOCX attachment parsing
│   │   └── notifications/             — email via SendGrid
│   └── config/                        — v1 JSON config files
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
│           └── OpportunityCard.jsx    — card UI component
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

Critical: the RLS setup had a circular dependency bug that took significant time to resolve. Current working state:

- `my_company_id()` — SECURITY DEFINER function, bypasses RLS when reading users table
- `users` SELECT policy — `id = auth.uid()` (simple, no circular reference)
- `companies` SELECT/UPDATE — uses `my_company_id()` (works now that function is SECURITY DEFINER)
- All INSERT policies — company/user creation goes through Flask `/api/v2/auth/register` using service key, which bypasses RLS entirely. Do NOT try to insert companies or users from the browser.
- `opportunities` — all authenticated users can read (public government data)

---

## 7. Build Phases

### Phase 1 — The Feed
**Goal:** Working end-to-end: account → onboarding → scored feed → swipe → pipeline entry.

- [x] Initialize git + push to GitHub
- [x] Database schema (Supabase PostgreSQL)
- [x] Bulk SAM.gov ingestion pipeline (two 6-month windows)
- [x] Expiration job
- [x] Flask API v2 (feed, summary, detail, profile, register endpoints)
- [x] Feed scoring engine (weighted, profile-based, no ML)
- [x] React app scaffold (Vite + Supabase JS + react-tinder-card)
- [x] Auth flow (login, signup, session management)
- [x] Onboarding (4-step, handles missing company row)
- [x] Swipe deck UI + card component
- [x] Right-swipe → pipeline insert
- [ ] **Run ingestion successfully and confirm opportunities in DB**
- [ ] **Test full onboarding flow end-to-end (all 4 steps save correctly)**
- [ ] **Confirm feed shows cards after ingestion**
- [ ] Card tap → expand to detail view (modal or new page)
- [ ] Keyboard navigation (arrow keys / J/K to swipe)
- [ ] "Liked" opportunities list page (pipeline view, simplified)
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
| AI summaries | Claude Haiku (claude-haiku-4-5-20251001) | On-demand, cached in DB |
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

---

## 10. What To Do Next Session

**Immediate (finish Phase 1):**

1. **Run ingestion** — `py -3 backend/src/ingestion/bulk_ingest.py --full` and confirm `data/last_ingest.txt` exists and Supabase `opportunities` table has rows.

2. **Test onboarding end-to-end** — complete all 4 steps and verify data in Supabase tables: `companies` (fields populated), `company_naics`, `company_keywords`.

3. **Confirm feed loads** — after ingestion, swipe deck should show cards. If still empty, debug the feed endpoint by hitting `http://localhost:5001/api/v2/feed` directly with a Bearer token.

4. **Card detail view** — tapping a card should expand to show full description, all fields, attachments list, SAM.gov link. Build as a slide-up sheet or modal.

5. **Liked opportunities page** — simple list of right-swiped opportunities pulled from the `pipeline` table. Users need somewhere to see what they saved.

6. **Deploy to Railway** — get it live so it can be shared with investors.

---

*Last updated: 2026-04-20 | Session: Phase 1 build — auth, onboarding, feed UI complete. Ingestion + end-to-end testing remaining.*
