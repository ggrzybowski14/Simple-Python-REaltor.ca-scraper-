# Realtor.ca Scraper POC

This is a deliberately small proof of concept built to answer one question:

Can a visible Python Playwright browser with stealth and light human-like behavior accept simple search inputs, drive Realtor.ca's filters, and scrape matching listing data?

Current state:

- Phase 1 complete: input-driven browser search
- Phase 2 complete: broader summary collection plus conservative detail enrichment
- Phase 3 next: richer listing-page detail extraction

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

## Phase 2 Summary

Phase 2 is complete and validated.

What it proved:

- the scraper can collect broader result sets across multiple pages
- the scraper can stop at configurable summary and detail caps
- the scraper can enrich detail pages with `detail_concurrency=2`
- the browser-first headed Playwright plus `playwright-stealth` setup remained stable during larger runs

Example validated outcome:

- a Victoria search with `2+` beds, `house`, and `max price 1000000`
- produced `57` visible matching listings on Realtor.ca for that search state
- successfully collected `50` summaries
- successfully enriched `10` detail pages

## Logs and failure artifacts

The script logs each major step to the terminal.

If scraping fails, it writes artifacts into `artifacts/`:

- a full-page screenshot
- the current page HTML

This is meant to make selector issues and anti-bot issues easier to diagnose without adding unnecessary framework code.
