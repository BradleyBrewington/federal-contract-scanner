# SAM Opportunity Platform — Master Briefing Document

> **For Claude Code:** Read this entire document at the start of every session before taking any action. It contains the product vision, architecture decisions, current build state, and what to work on next. Update the Progress Tracker and Decision Log sections as work is completed.

---

## 1. What This Is

A multi-tenant, feed-driven federal contracting opportunity intelligence platform built on SAM.gov data. Companies create accounts, configure their profile, and receive a personalized, algorithm-ranked feed of contract opportunities they can swipe through (Tinder-style) to surface high-fit work and train a per-account recommendation engine.

**The core insight:** Most SAM.gov tools are search engines. This is a recommendation engine with a social-media-style interaction loop. The swipe mechanic generates training data. The training data improves the feed. A better feed drives more engagement. More engagement drives more data. This flywheel is the product's moat.

**The target user:** Business development professionals at small-to-midsize government contractors who need to identify and track federal opportunities without spending hours manually searching SAM.gov.

---

## 2. What Exists Today (v1 — Single-Tenant)

The current codebase is a working single-tenant scanner hardcoded for one company. It is the foundation we are building from, not replacing.

**Current stack:**
- Python backend (Flask REST API at `src/api/server.py`)
- Static HTML/CSS/JS frontend (`dashboard/`)
- JSON file-based storage (`data/`)
- SAM.gov API polling (per-query, not bulk)
- Scoring via configurable rule engine (`config/scoring_rules.json`)
- AI enrichment via Claude (Anthropic API)
- Email alerts via SendGrid
- PDF/DOCX attachment parsing (`src/parsers/`)

**What v1 does well:**
- Scans SAM.gov, SBIR.gov, Grants.gov
- Scores opportunities against configurable rules and keywords
- Runs on a schedule, sends email digests
- Dashboard with filter/sort/detail/archive/CSV export
- Teaming partner lookup via USASpending

**What v1 does not do:**
- Multi-tenant (no accounts, no company profiles)
- Bulk data ingestion (queries API per search — rate-limited)
- Swipe/feed UI
- Behavioral learning / recommendation algorithm
- Pipeline tracking (beyond basic status field)
- Mobile-responsive design
- Any form of ML or feedback loop

---

## 3. Product Vision (v2 — Platform)

### 3.1 The User Experience

**Onboarding:**
1. Create account (company + users)
2. Upload capabilities statement or paste company description → AI extracts NAICS codes, keywords, agency history automatically
3. Quick calibration: rate 10–15 seed opportunities (Yes / No / Maybe) to prime the algorithm before first real use
4. Three required fields: contract size range, prime vs. sub posture, set-aside status
5. If onboarding is incomplete, show persistent non-blocking nudge on every login: "Your feed is 60% tuned — finish setup →"

**The Feed (primary surface):**
- Infinite scroll of opportunity cards
- Each card: agency logo, title, value range, deadline (color-coded by urgency), NAICS/set-aside badge, one-line AI-generated summary
- Swipe right = interested → goes to pipeline
- Swipe left = pass → trains algorithm
- Tap/click = expand to full detail view
- Keyboard navigable: J/K or arrow keys to scroll, Enter to expand, R/L to swipe

**The Pipeline (secondary surface):**
- Kanban board: Watching → Evaluating → Pursuing → Submitted → Won / Lost
- Drag cards between columns
- Column headers show count + total value
- Per-card detail: full opportunity text, attachments (on-demand download), internal notes, deadline countdown, match score breakdown, amendment history

**Dual-mode design:**
- Feed card = clean mode (20% of information, fast triage)
- Pipeline detail = advanced mode (100% of information, deep dive)
- Never force a wall of text during the feed experience

### 3.2 The Algorithm

**Signal collection (every interaction is data):**
- Swipe right / left (primary signal)
- Dwell time before swiping (long dwell + left = different from instant left)
- Tap to expand (high intent)
- Move to pipeline column (strongest positive signal)
- Open attachments
- Mark as Won / Lost (highest-value signal — rarely captured by other tools)

**Feed composition:**
- ~70% algorithm picks (high-confidence profile + behavioral matches)
- ~20% exploration (adjacent NAICS, new agencies, slightly outside stated range)
- ~10% urgency-surfaced (deadlines within 14 days, promoted regardless of score)

**Scoring factors (profile-based, before behavioral data accumulates):**
- NAICS / PSC code match (exact vs. adjacent)
- Set-aside eligibility alignment
- Contract value within stated range
- Agency affinity (have they worked there before?)
- Keyword overlap with capabilities statement
- Place of performance match
- Time to deadline (filter out < X days unless configured otherwise)

**Behavioral weight adjustment:**
- Phase 1: Weighted scoring system that updates from swipe history (no ML required)
- Phase 2: Per-account ML model (collaborative filtering + embedding similarity)
- Phase 3: Cross-account anonymized signal to improve cold-start for new companies

### 3.3 Engagement Mechanics

- "New since your last visit" badge (creates reason to open app without revealing count)
- Weekly digest notification: "23 new matches. 3 closing in 14 days."
- "Your feed improved" notification after N swipes
- Streak mechanic: "Reviewed opportunities 5 days in a row"
- Win celebration: confetti + running total of contract value won through platform
- Pre-solicitation alerts: Sources Sought and RFIs surfaced as early signals (3–18 months lead time)

---

## 4. Data Architecture

### 4.1 Bulk Ingestion (replacing per-query API calls)

- Download full SAM.gov opportunity dataset in 10,000-record pages
- Store in a proper database (replacing JSON files)
- Track `modifiedDate` and `responseDeadline` on every record
- Nightly delta update: pull only records modified since last run
- Nightly expiration job: mark past-deadline records as expired (do NOT delete — keep for historical analysis)
- Track awarded contracts separately for re-compete intelligence

**Why bulk over per-query:** API rate limits make per-query infeasible at scale across many accounts. Bulk download + local index makes all searches instant and unconstrained.

### 4.2 Index Design

- Full-text index on title + description
- Structured filters: NAICS, PSC, agency, set-aside type, value range, place of performance, status
- Semantic / vector index on description text (conceptual matching — "cybersecurity" matches "information assurance")
- The combination of keyword + semantic + structured filtering is the quality differentiator

### 4.3 Attachments

- Do NOT download proactively (storage cost)
- Download on-demand when user requests from detail view
- Cache for ~7 days, then purge
- Extract text from PDFs/Word docs for full-text search (Phase 2)

### 4.4 Multi-Tenancy

- Company account owns the profile and pipeline data
- User accounts belong to a company (multiple users per company, with roles)
- Feedback and pipeline data are private per company
- Aggregate anonymized signal (NAICS activity, agency trends) shared as market intelligence

---

## 5. Company Profile Schema

**Hard facts (structured):**
- NAICS codes (primary + secondary)
- PSC codes
- Set-aside eligibility (SDVOSB, 8(a), HUBZone, WOSB, small business, etc.)
- Contract size range (min / max they can realistically pursue)
- Geographic focus (CONUS, states, OCONUS)
- Clearance level held
- Company size / revenue tier

**Strategic posture:**
- Prime only / sub only / both
- Existing agency relationships
- Incumbent contracts (to track re-competes)
- Known teaming partners
- Keywords from capabilities statement

**Exclusions (critical for noise reduction):**
- Agencies or vehicles they cannot work with
- Geographies they won't support
- Contract types to exclude
- Value thresholds (hard min/max)

---

## 6. Build Phases

### Phase 1 — The Feed *(not started)*
**Goal:** Replace the current single-tenant dashboard with a multi-tenant, card-based feed experience.

- [ ] Initialize git repository and push to GitHub
- [ ] Design database schema (PostgreSQL) — accounts, companies, opportunities, swipes, pipeline
- [ ] Build bulk SAM.gov ingestion pipeline (replace per-query scraper)
- [ ] Build nightly delta update + expiration jobs
- [ ] Build opportunity card renderer (AI-generated one-line summary per card)
- [ ] Build swipe/feed UI (mobile-first, keyboard-navigable on desktop)
- [ ] Build profile-based relevance scoring (weighted, no ML yet)
- [ ] Build account creation + onboarding flow (with incomplete-state nudge)
- [ ] Build liked opportunities list (pre-pipeline)
- [ ] Deploy

**Phase 1 deliverable:** A usable product. Users create accounts, get a scored feed, swipe, and collect liked opportunities.

### Phase 2 — The Learning *(not started)*
**Goal:** The product starts feeling personalized. Add the pipeline and behavioral feedback loop.

- [ ] Behavioral signal collection (dwell time, expand events, document opens)
- [ ] Algorithm weight adjustment from swipe history
- [ ] Full pipeline Kanban board
- [ ] Deadline alerts (email + in-app)
- [ ] "Your feed improved" notifications
- [ ] Streak mechanic
- [ ] Pre-solicitation / Sources Sought surfacing
- [ ] Amendment tracking for opportunities in pipeline

### Phase 3 — The Intelligence *(not started)*
**Goal:** ML per account. The product becomes genuinely predictive.

- [ ] Vector embeddings for semantic opportunity matching
- [ ] Per-account ML recommendation model
- [ ] Win/loss pattern analysis ("You win at DHS more than civilian agencies")
- [ ] PDF/DOCX text extraction for attachment search
- [ ] Market intelligence dashboard (agency trends, NAICS activity)
- [ ] Collaborative filtering across accounts (anonymized)

### Phase 4 — The Network *(future vision)*
- [ ] Teaming partner matching ("Company A is pursuing this and needs a sub with your NAICS")
- [ ] Industry benchmark dashboards
- [ ] Public company profiles for teaming discovery

---

## 7. Tech Stack Decisions

These are decisions made during planning. Do not change without updating this document and noting the reason.

| Layer | Decision | Reason |
|---|---|---|
| Backend language | Python | Existing codebase is Python; no reason to switch |
| Backend framework | Flask → FastAPI | FastAPI is async, better for concurrent feed requests |
| Database | PostgreSQL | Replacing JSON files; need relational structure + full-text search |
| Vector search | pgvector (Postgres extension) or Pinecone | Keep it simple in Phase 1; evaluate in Phase 3 |
| Frontend framework | React | Component model fits card/swipe UI; large ecosystem for gesture libs |
| Swipe library | react-tinder-card or custom | Evaluate; needs to feel physically satisfying, not janky |
| Auth | Supabase Auth or Auth0 | Don't build auth from scratch |
| Hosting | TBD | Needs to support background jobs (ingestion, nightly updates) |
| AI summarization | Claude API (claude-haiku-4-5) | Fast + cheap for card summaries at scale |
| Email | SendGrid | Already integrated in v1 |

---

## 8. Key Design Principles

1. **Card quality is foundational.** If the one-line summary is garbage, the swipe mechanic fails. AI summarization and data cleaning are not cosmetic — they are load-bearing.

2. **Progressive disclosure.** Card = 20% of info. Expanded = 60%. Detail view = 100%. Never force depth during triage.

3. **Mobile-first, desktop-class.** Swipe lives on mobile. Pipeline board lives on desktop. Both are first-class, not ports of each other.

4. **Exclusions matter as much as inclusions.** Capturing what a company will NOT pursue is as important as what they will.

5. **Every interaction is training data.** Design UI flows with signal collection in mind. Dwell time, tap depth, and column moves are all behavioral signals.

6. **Don't delete expired data.** Historical opportunities, awards, and outcomes are intelligence assets for pattern recognition and re-compete tracking.

---

## 9. Decision Log

*Record significant architectural or product decisions here as they are made.*

| Date | Decision | Reason |
|---|---|---|
| 2026-04-18 | Pivot from single-tenant scanner to multi-tenant platform | Product should be shareable / uploadable for any company to use |
| 2026-04-18 | Bulk ingestion over per-query API | Rate limits make per-query infeasible at scale; bulk + local index is faster for users |
| 2026-04-18 | Swipe/feed UI as primary interaction | Generates behavioral training data while users triage; addictive loop increases engagement |
| 2026-04-18 | Keep expired opportunities in database | Historical data enables re-compete tracking, win/loss pattern analysis, and market intelligence |
| 2026-04-18 | CLAUDE.md as session briefing document | New Claude Code sessions load this automatically; no need to re-explain context each session |

---

## 10. Current Session / What To Do Next

**Current status:** Planning complete. No v2 code written yet. v1 single-tenant codebase exists and is functional.

**Immediate next steps (Phase 1 start):**
1. Initialize git repository, make initial commit of v1 code, push to GitHub
2. Design the PostgreSQL database schema before writing any application code
3. Decide on frontend framework and project structure (React app separate from Python backend, or monorepo?)

**Open questions to resolve before building:**
- Hosting platform (Railway, Render, AWS, GCP, Fly.io?)
- Auth provider (Supabase vs Auth0 vs rolling own with JWT)
- Will the React frontend live in the same repo as the Python backend, or a separate repo?
- SAM.gov bulk data terms-of-service review (confirm redistribution / multi-tenant use is permitted)

---

*Last updated: 2026-04-18 | Updated by: Planning session with Claude*
