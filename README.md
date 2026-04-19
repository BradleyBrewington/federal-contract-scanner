# Federal Contract Opportunity Scanner

Automated scanner for federal contract opportunities from SAM.gov, SBIR.gov, and Grants.gov. Scores opportunities using configurable rules, enriches high-scoring ones with Claude AI analysis, and sends email alerts via SendGrid.

## Setup

1. **Install dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

2. **Configure environment:**
   ```bash
   cp .env.example .env
   # Edit .env with your API keys
   ```

   Required keys:
   - `SAM_API_KEY` — from [SAM.gov](https://sam.gov) (required for scanning)
   - `ANTHROPIC_API_KEY` — for AI enrichment (optional)
   - `SENDGRID_API_KEY` + `SENDGRID_FROM_EMAIL` + `NOTIFICATION_EMAIL` — for email alerts (optional)
   - `DASHBOARD_PASSWORD` — dashboard login password (default: `changeme`)

3. **Customize config files** in `config/`:
   - `settings.json` — sources, NAICS codes, set-asides, scan schedule
   - `keywords.json` — positive/negative/bonus keywords for scoring
   - `scoring_rules.json` — scoring rubric and point values

## Usage

### Run a single scan
```bash
python src/main.py --scan
```

### Run on a schedule (every N hours)
```bash
python src/main.py --scheduled --interval 6
```

### Start the dashboard
```bash
python src/api/server.py
```
Open `http://localhost:8080` and log in with your configured password.

## Dashboard Features

- **Opportunity list** — filter by source, status, search text; sort by score, date, deadline
- **Detail view** — full info, AI analysis, score breakdown, notes, status tracking
- **Teaming leads** — search USASpending by NAICS for potential teaming partners
- **Archive** — archive reviewed opportunities
- **Statistics** — totals, averages, breakdowns by source and status
- **CSV export** — download all opportunities as CSV
- **Manual scan** — trigger a scan from the dashboard

## Project Structure

```
├── config/              # Configuration JSON files
├── dashboard/           # Frontend HTML/CSS/JS
├── data/                # Stored opportunities (generated)
├── src/
│   ├── api/server.py    # Flask REST API
│   ├── main.py          # CLI orchestrator
│   ├── scrapers/        # SAM, SBIR, Grants.gov, USASpending
│   ├── parsers/         # PDF/DOCX attachment extraction
│   ├── scoring/         # Rule engine + AI enrichment
│   └── notifications/   # SendGrid email alerts
├── .env.example
├── requirements.txt
└── README.md
```
