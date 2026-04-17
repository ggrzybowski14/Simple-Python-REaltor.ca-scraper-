# Realtor.ca Scraper Foundation

This repository started as a small proof of concept built to answer one question:

Can a visible Python Playwright browser with stealth and light human-like behavior accept search inputs, drive Realtor.ca's filters, and scrape matching listing data?

That proof of concept is now working well enough to serve as the foundation for a larger real-estate analyzer application.

Current state:

- Scraper foundation working: neutral startup plus input-driven browser search
- Broader collection working: summary collection across pages plus conservative detail enrichment
- Rich detail extraction integrated into the same script
- Phase 1 Supabase model working: saved searches, scrape runs, canonical listings, and run history
- Light lifecycle handling implemented: active listings per saved search plus `is_new_in_run`
- Remaining Phase 1 follow-up: prove the inactive-listing transition with a controlled rerun
- Local website scaffold added: dashboard, saved search detail view, and background scrape launch
- Safe speed pass completed: shorter fixed waits, lower `slow_mo`, and conservative parallel detail scraping
- Repeat-run optimization added: recently enriched listings can reuse cached detail from Supabase instead of re-opening every detail page
- Next active step: iterate on the local website on top of the validated scraper and data foundation

## What It Does Today

- Opens a visible Chromium browser
- Applies `playwright-stealth`
- Opens the Realtor.ca map/results experience in a visible browser
- Accepts runtime search inputs for location, min/max price, minimum beds, and property type
- Uses the visible Realtor.ca search UI to apply those filters
- Supports broader collection controls for max pages, max listings, detail limit, and detail concurrency
- Waits, moves the mouse, and scrolls lightly
- Collects matching listing summaries across result pages
- Enriches detail pages with conservative low-risk concurrency
- Reuses recent fully enriched listing detail on repeat runs when Supabase already has fresh data
- Extracts richer listing detail fields including full description, property type, building type, square footage, land size, built year, taxes, time on Realtor.ca, and zoning type
- Extracts listing photos and stores a primary photo plus additional gallery images
- Logs visible result-count and page-state diagnostics during broader runs
- Prints listing data to the terminal
- Saves a screenshot and HTML snapshot on failure
- Saves JSON output that includes the search criteria used for the run
- Automatically upserts listings into Supabase after a successful scrape when local Supabase credentials are present

## What It Is Not Yet

This is not yet:

- a local website
- a finished listing-analysis product
- a buy-box evaluation engine
- a market fundamentals analyzer
- a multi-user application
- a polished full website workflow

The repository is currently the scraper and ingestion foundation for those later layers.

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
playwright install chromium
python scraper.py

# or pass filters directly
python scraper.py --location Victoria --beds-min 2 --property-type house --max-price 1000000

# broader collection with conservative detail concurrency
python scraper.py \
  --location Duncan \
  --beds-min 2 \
  --property-type house \
  --max-price 1000000 \
  --max-pages 3 \
  --max-listings 12 \
  --detail-limit 4 \
  --detail-concurrency 2

# denser-market breadth test
python scraper.py \
  --location Victoria \
  --beds-min 2 \
  --property-type house \
  --max-price 1000000 \
  --max-pages 10 \
  --max-listings 50 \
  --detail-limit 10 \
  --detail-concurrency 2

# run the first local website scaffold
python app.py
```

Then open `http://127.0.0.1:5000`.

## Supabase

Supabase writes are currently integrated into the same `scraper.py` script.

Setup:

1. Create the table in Supabase with [supabase/schema.sql](/Users/georgia/Projects/simple realtor.ca scraper python/supabase/schema.sql:1).
2. Copy `.env.example` to `.env.local` and fill in:
   - `SUPABASE_URL`
   - `SUPABASE_KEY`
3. Run the scraper normally. If credentials are present, Supabase upload happens automatically.

Example:

```bash
python scraper.py \
  --location Victoria \
  --beds-min 2 \
  --property-type house \
  --max-price 1000000 \
  --max-pages 1 \
  --max-listings 2 \
  --detail-limit 2 \
  --detail-concurrency 1
```

Notes:

- The script still saves local JSON output even when Supabase writes are enabled.
- If you want to disable database writes for a specific run, use `--no-supabase`.
- The Supabase schema now stores saved searches, scrape runs, canonical listings, run-to-listing history, and saved-search lifecycle state separately.

## Current Integrated Flow

The current `scraper.py` is the integrated script for the project.

What is already working in the integrated flow:

- the scraper can collect broader result sets across multiple pages
- the scraper can stop at configurable summary and detail caps
- the scraper can enrich detail pages with `detail_concurrency=2`
- repeat runs can reuse recently scraped, fully enriched listing detail instead of visiting every detail page again
- the scraper can extract richer detail fields directly into the same JSON output
- the scraper can extract listing photos and persist them inside the stored raw listing payload
- the browser-first headed Playwright plus `playwright-stealth` setup remained stable during larger runs
- the scraper now starts from a neutral Realtor.ca map page rather than a Victoria-specific hard-coded map state
- the scraper now persists data into `saved_searches`, `scrape_runs`, `listings`, and `scrape_run_listings`
- the scraper now maintains a saved-search-specific active-listing view via `current_active_saved_search_listings`

Example validated outcome:

- a Victoria search with `2+` beds, `house`, and `max price 1000000`
- produced `58` visible matching listings on Realtor.ca for that search state in the latest validated run
- successfully collected `12` summaries in a broader validation pass
- successfully enriched `4` detail pages with the cleaned Phase 3 schema
- successfully upserted validated listing data into Supabase in live testing

Current enriched fields include:

- `listing_description`
- `property_type`
- `building_type`
- `square_feet`
- `land_size`
- `built_in`
- `annual_taxes`
- `hoa_fees`
- `time_on_realtor`
- `zoning_type`
- `photo_urls`
- `primary_photo_url`

Lifecycle status:

- active listings per saved search are now tracked and queryable
- `is_new_in_run` is now tracked per scrape run
- the explicit inactive transition still needs a controlled verification run against the same saved-search context

## Local Website Scaffold

The repository now includes a first local website scaffold in [app.py](/Users/georgia/Projects/simple realtor.ca scraper python/app.py:1).

Current website scope:

- dashboard showing saved searches
- recent scrape runs
- saved-search detail page showing current active listings
- visual indicator for the saved search updated by the latest run
- local form to launch a new headed scrape in the background
- local job detail page with basic log output
- listing detail page with photo gallery and richer scraped fields

Current website limitations:

- no authentication
- no persistent job queue beyond the current local app process
- no inline listing analysis yet
- no edit/delete workflow for saved searches yet
- no polished error handling yet
- no dedicated run comparison or retry UX yet
- no explicit “why this listing was reused vs re-scraped” UI yet

## Product Direction

The intended product direction is:

1. define a saved search for a market of interest
2. scrape all active listings matching that saved search
3. store both the current listing state and scrape history
4. show current active listings in a local application
5. later evaluate those listings against buy-box criteria

Important scope clarifications:

- `saved search` and `buy box` are related but separate concepts
- the current near-term goal is listing ingestion and listing analysis within a selected market
- broader market fundamentals analysis is a later product area, not active implementation scope

## Next Active Work

Phase 1 foundation work is largely complete and has been validated in live headed runs.

What is now done:

- removed the Victoria-specific startup assumption
- made the scrape flow work from a neutral Realtor.ca map page
- redesigned the Supabase model to preserve scrape history without duplicating canonical listing rows
- added a clean current active-listings view for future UI work
- validated the headed scraper plus Supabase persistence end to end

Remaining near-term follow-up:

- prove the inactive-listing transition with a controlled rerun for the same saved-search context
- continue Phase 2 UX iteration around run visibility, run status, and listing workflow

Planned direction after that:

1. continue Phase 2 website iteration on top of the current scaffold
2. improve Phase 2 run UX:
   - clearer run status
   - clearer saved-search update indicators
   - better recent-run visibility from the dashboard
3. small follow-up on lifecycle verification if still needed during website work
4. Phase 3: listing analysis and buy-box filtering
5. later: workflow refinements and optional market-analysis features

See [PROJECT_OVERVIEW.md](/Users/georgia/Projects/simple realtor.ca scraper python/PROJECT_OVERVIEW.md:1) for the fuller roadmap and phase definitions.

## Logs and failure artifacts

The script logs each major step to the terminal.

If scraping fails, it writes artifacts into `artifacts/`:

- a full-page screenshot
- the current page HTML

This is meant to make selector issues and anti-bot issues easier to diagnose without adding unnecessary framework code.
