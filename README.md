# Realtor.ca Scraper POC

This is a deliberately small proof of concept built to answer one question:

Can a visible Python Playwright browser with stealth and light human-like behavior accept simple search inputs, drive Realtor.ca's filters, and scrape matching listing data?

Current state:

- Phase 1 complete: input-driven browser search
- Phase 2 complete: broader summary collection plus conservative detail enrichment
- Phase 3 integrated into the same script: richer listing-page detail extraction
- Next step: Supabase-ready storage integration

## What it does

- Opens a visible Chromium browser
- Applies `playwright-stealth`
- Opens the Realtor.ca map/results experience in a visible browser
- Accepts runtime search inputs for location, min/max price, minimum beds, and property type
- Uses the visible Realtor.ca search UI to apply those filters
- Supports broader collection controls for max pages, max listings, detail limit, and detail concurrency
- Waits, moves the mouse, and scrolls lightly
- Collects matching listing summaries across result pages
- Enriches detail pages with conservative low-risk concurrency
- Extracts richer listing detail fields including full description, property type, building type, square footage, land size, built year, taxes, time on Realtor.ca, and zoning type
- Logs visible result-count and page-state diagnostics during broader runs
- Prints a few fields to the terminal
- Saves a screenshot and HTML snapshot on failure
- Saves JSON output that includes the search criteria used for the run

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
```

## Current Integrated Flow

The current `scraper.py` is the integrated script for the project.

What is already working in the integrated flow:

- the scraper can collect broader result sets across multiple pages
- the scraper can stop at configurable summary and detail caps
- the scraper can enrich detail pages with `detail_concurrency=2`
- the scraper can extract richer detail fields directly into the same JSON output
- the browser-first headed Playwright plus `playwright-stealth` setup remained stable during larger runs

Example validated outcome:

- a Victoria search with `2+` beds, `house`, and `max price 1000000`
- produced `58` visible matching listings on Realtor.ca for that search state in the latest validated run
- successfully collected `12` summaries in a broader validation pass
- successfully enriched `4` detail pages with the cleaned Phase 3 schema

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

## Next Step

The next build step is Supabase integration.

That should focus on:

- defining the target table/schema for the current JSON output
- mapping the integrated scraper output into a stable insert payload
- preserving the current file output and failure artifacts while database writes are introduced

## Logs and failure artifacts

The script logs each major step to the terminal.

If scraping fails, it writes artifacts into `artifacts/`:

- a full-page screenshot
- the current page HTML

This is meant to make selector issues and anti-bot issues easier to diagnose without adding unnecessary framework code.
