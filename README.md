# Lead Scraper

AI-powered local-business lead generation tool. Find businesses on Google Places, qualify them with Claude, scrape contact emails from their websites, and work your outreach pipeline — all from a browser-based dashboard.

## What it does

- **Search** — query Google Places for local businesses (e.g., *"dental offices in Milwaukee, Wisconsin"*).
- **Qualify** — Claude scores each lead 1–10 with written reasoning and flags (`no_website`, `established`, `possible_chain`, etc.).
- **Enrich** — contact emails are scraped from each business's public website and classified as generic (`info@`, `contact@`) or personal.
- **Track** — leads are saved to a database with editable status (backlog → contacted → negotiating → won / lost / stale) and free-form notes. Duplicate businesses are merged automatically across searches.
- **Export** — download any result set as a formatted Excel file.

## Tech stack

- **Python 3.10+**
- **Streamlit** — dashboard UI
- **SQLite** — local persistence (per-instance for demo deployments)
- **Google Places API** — business data
- **Anthropic Claude API** (Haiku 4.5) — lead qualification with structured outputs via Pydantic
- **openpyxl** — Excel export
- **requests** — Google API + email scraping

## Local setup

1. Clone the repository and `cd` into it.

2. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

3. Create a `.env` file in the project root:
   ```
   GOOGLE_PLACES_API_KEY=your_google_places_key
   ANTHROPIC_API_KEY=your_anthropic_key
   ```

4. Run the dashboard:
   ```bash
   streamlit run app.py
   ```
   Opens at `http://localhost:8501`.

   A terminal-only version is also available:
   ```bash
   python scraper.py
   ```

## Architecture

Three modules sharing one pipeline:

- `scraper.py` — Google Places search, Place Details enrichment, Claude qualification, website email scraping. Exposes `run_pipeline()` for reuse.
- `database.py` — SQLite schema, upsert dedup via Google `place_id`, and editable status/notes via a whitelist.
- `app.py` — Streamlit dashboard. Two tabs: **Search** (run + save) and **My Leads** (edit pipeline status).

The CLI and the dashboard call the same `run_pipeline()` function — single source of truth for the work.

## Roadmap

- ✅ Phase 1: Browser dashboard
- ✅ Phase 2: Database persistence with dedup
- ✅ Phase 3: Editable pipeline status, notes, filtering
- ✅ Phase 4a: Hosted demo deployment (Streamlit Community Cloud)
- ⏳ Phase 4b: Migrate to hosted Postgres for production-grade persistence
- ⏳ Phase 5: Multi-tenant auth, per-user lead lists
