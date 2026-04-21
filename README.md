# Realtor.ca Scraper And Local Analyzer

This repository started as a small proof of concept built to answer one question:

Can a visible Python Playwright browser with stealth and light human-like behavior accept search inputs, drive Realtor.ca's filters, and scrape matching listing data?

That proof of concept now serves as the foundation for a local real-estate analyzer application.

Current state:

- Scraper foundation working: neutral startup plus input-driven browser search
- Broader collection working: summary collection across pages plus conservative detail enrichment
- Rich detail extraction integrated into the same script
- Phase 1 Supabase model working: saved searches, scrape runs, canonical listings, and run history
- Light lifecycle handling implemented: active listings per saved search plus `is_new_in_run`
- Remaining Phase 1 follow-up: prove the inactive-listing transition with a controlled rerun
- Local website working: dashboard, saved search detail view, listing detail, photo gallery, and background scrape launch
- Safe speed pass completed: shorter fixed waits, lower `slow_mo`, and conservative parallel detail scraping
- Repeat-run optimization added: recently enriched listings can reuse cached detail from Supabase instead of re-opening every detail page
- Phase 3 started: structured and AI-assisted buy box with `matched`, `maybe`, and `unmatched` buckets
- Buy-box persistence working: one saved buy box per saved search, shown on both saved-search and listing-detail pages
- Investment analyzer working: dedicated underwriting page for all active listings in a saved search
- Underwriting persistence working: saved-search defaults plus listing-level rent overrides
- CMHC market-reference layer working: imported market rent and vacancy reference rows can hydrate underwriting defaults
- CMHC source controls working: rent and vacancy can explicitly switch between manual and CMHC-backed values
- Listing-detail underwriting working: listing pages now show underwriting metrics, assumptions, and source context
- Reliability pass in progress: sparse-detail retry, stricter detached-house filtering, and improved pagination collection
- Next active step: move AI rent and vacancy controls into the assumptions cards and complete the AI source mode

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
- Tracks both site `results_count` and collected `summary_count` per run so pagination gaps are visible
- Prints listing data to the terminal
- Saves a screenshot and HTML snapshot on failure
- Saves JSON output that includes the search criteria used for the run
- Automatically upserts listings into Supabase after a successful scrape when local Supabase credentials are present
- Serves a local website for browsing active listings and running buy-box filters
- Supports an AI interpretation goal for fuzzy listing-description criteria such as secondary suite potential
- Supports targeted retry of only sparse listing details instead of forcing a full rerun
- Supports a dedicated saved-search underwriting page with grouped listing comparison and computed investment metrics
- Supports listing-specific rent overrides that feed the underwriting table and listing-detail page
- Supports CMHC market-reference matching for market rent and vacancy baselines

## What It Is Not Yet

This is not yet:

- a finished listing-analysis product
- a polished final investment analyzer
- a market fundamentals analyzer
- a multi-user application
- a deployed production website

The repository is currently a working local-first scraper, ingestion layer, and early listing-analysis tool.

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

# import BC CMHC market reference data from the workbook
python3 scripts/import_cmhc_market_data.py \
  "/Users/georgia/Documents/rmr-british-columbia-2025-en.xlsx" \
  --source-url "https://www.cmhc-schl.gc.ca/professionals/housing-markets-data-and-research/housing-data/data-tables/rental-market/rental-market-report-data-tables"
```

Then open `http://127.0.0.1:5000` unless you are using a different local port during development.

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
- The Supabase schema now stores saved searches, scrape runs, canonical listings, run-to-listing history, saved-search lifecycle state, underwriting defaults, listing overrides, CMHC market reference rows, and AI suggestion history separately.
- CMHC import currently parses the BC rental-market workbook and loads apartment-based market rent and vacancy rows into `market_reference_data`.

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
- the scraper now runs location-based collection without relying on `Search within boundary`
- the scraper now waits for a settled results state before collection and uses more robust page-2 navigation fallbacks
- the scraper now persists data into `saved_searches`, `scrape_runs`, `listings`, and `scrape_run_listings`
- the scraper now maintains a saved-search-specific active-listing view via `current_active_saved_search_listings`
- the scraper now has a targeted sparse-detail retry script for repairing missing detail fields

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

## Local Website

The repository now includes a working local website in [app.py](/Users/georgia/Projects/simple realtor.ca scraper python/app.py:1).

Current website scope:

- dashboard showing saved searches
- recent scrape runs
- saved-search detail page showing current active listings
- latest run metrics showing active listings, site results count, and collected count
- visual indicator for the saved search updated by the latest run
- local form to launch a new headed scrape in the background
- local action to retry only sparse listing details
- local job detail page with basic log output
- listing detail page with photo gallery and richer scraped fields
- buy-box workspace with:
  - all scraped listings
  - structured filters
  - AI interpretation goal
  - `matched`, `maybe`, and `unmatched` result buckets
- saved buy-box summary showing the currently persisted structured and AI criteria
- buy-box verdict and AI reasoning on the listing-detail page
- investment analyzer page with:
  - all active listings underwritten by default
  - grouping into `likely`, `maybe`, and `unlikely`
  - sorting within each bucket by strongest monthly cash flow first
  - saved-search underwriting defaults
  - local source controls for market rent and vacancy
  - listing-level rent overrides
- listing-detail underwriting section with:
  - monthly cash flow
  - cap rate
  - cash-on-cash
  - rent-to-price ratio
  - assumptions and source summary

Current website limitations:

- no authentication
- no persistent job queue beyond the current local app process
- no edit/delete workflow for saved searches yet
- no polished error handling yet
- no dedicated run comparison or retry UX yet
- no explicit “why this listing was reused vs re-scraped” UI yet
- site result counts can still fluctuate while Realtor.ca settles
- AI underwriting flow is scaffolded but not yet fully integrated into the `Market Rent Monthly` and `Vacancy %` cards
- CMHC rent data is currently apartment-oriented, so house searches can still require manual or AI adjustment

## Product Direction

The intended product direction is:

1. define a saved search for a market of interest
2. scrape all active listings matching that saved search
3. store both the current listing state and scrape history
4. show current active listings in a local application
5. evaluate those listings against a persisted buy box
6. underwrite promising listings with investment metrics
7. later add review workflow, market analysis, notes, shortlist behavior, and explicit run comparison

Important scope clarifications:

- `saved search` and `buy box` are related but separate concepts
- the current near-term goal is listing ingestion and listing analysis within a selected market
- broader market fundamentals analysis is a later product area, but the roadmap now explicitly leaves room for a future market analyzer

## Investment Analyzer Direction

The next major product area is a buy-and-hold investment analyzer layered on top of scraped listings.

Locked product decisions:

- v1 strategy scope is only `buy, rent, and hold`
- `CapEx` should be kept separate from `NOI` in v1
- assumptions should be auto-filled per listing and remain editable
- market-derived assumptions should be editable rather than hard-coded
- heuristic metrics can use green / yellow / red indicators

Recommended v1 metric groups:

- `Cash Flow`
  monthly rent, monthly expenses, mortgage, monthly cash flow
- `Returns`
  NOI, cap rate, annual cash flow, cash-on-cash return
- `Quick Rules`
  1% rule, 50% rule, rent-to-price ratio
- `Risk`
  base, conservative, and stress-case scenarios

Planning guidance:

- cash flow is the backbone of the analyzer
- the product should distinguish canonical metrics from heuristic rules
- long-term metrics like appreciation, IRR, and equity multiple should be phase 2+ work after the base underwriting engine is stable
- future market context should support items like rent growth, appreciation, population growth, job growth, household income, supply, and liquidity

AI-assisted estimation is planned for a later phase to help thin-data markets. The intended rule is:

- use structured or public data first when available
- use AI as a fallback or synthesis layer when local market data is sparse
- always show source and confidence
- always allow the user to edit the estimate

## Project Phases

The current working roadmap is:

1. stabilize scrape result counts and pagination reliability
2. continue improving listing-review workflow in the local app
3. add a listing-level investment assumptions model
4. add a buy-and-hold underwriting engine and listing-detail investment UI
5. add smarter market-derived defaults and AI-assisted estimates
6. add a future market analyzer with market tiles generated from scraped regions
7. later add long-term projections, IRR, equity multiple, and other strategy overlays

See [PROJECT_OVERVIEW.md](/Users/georgia/Projects/simple realtor.ca scraper python/PROJECT_OVERVIEW.md:1) for the detailed product spec and next-session handoff notes.
See [PRODUCT_INSPIRATION.md](/Users/georgia/Projects/simple realtor.ca scraper python/PRODUCT_INSPIRATION.md:1) for external product references, screenshot-derived UI patterns, and future design ideas that should persist across sessions.

## Current Next Steps

Highest-value next work from the current state:

1. make settled site counts more reliable by improving post-filter stabilization and logging first-page URLs more clearly
2. keep hardening pagination so `results_count` and `summary_count` stay aligned across repeated runs
3. decide the schema for listing-level investment assumptions
4. build the first buy-and-hold underwriting module and listing-detail investment UI
5. add workflow states such as shortlist / ignore / notes for reviewed listings
6. add clearer run-to-run comparison so `new in update` can be interpreted against collected-set churn

## Next Active Work

Phase 1 foundation work is largely complete and has been validated in live headed runs.

What is now done:

- removed the Victoria-specific startup assumption
- made the scrape flow work from a neutral Realtor.ca map page
- redesigned the Supabase model to preserve scrape history without duplicating canonical listing rows
- added a clean current active-listings view for future UI work
- validated the headed scraper plus Supabase persistence end to end
- added the first AI-assisted buy-box pass for ambiguous listing-description criteria

Remaining near-term follow-up:

- prove the inactive-listing transition with a controlled rerun for the same saved-search context
- keep improving scrape stability until the active listing set is dependable enough for underwriting
- add listing-level investment assumptions and a first `Investment Analysis` section
- add simple listing workflow actions such as shortlist / ignore / notes

Planned direction after that:

1. continue Phase 3 listing-analysis iteration
2. add Phase 4 workflow refinements
3. keep only high-value Phase 2 UX improvements
4. later: optional market-analysis features

See [PROJECT_OVERVIEW.md](/Users/georgia/Projects/simple realtor.ca scraper python/PROJECT_OVERVIEW.md:1) for the fuller roadmap and phase definitions.

## Logs and failure artifacts

The script logs each major step to the terminal.

If scraping fails, it writes artifacts into `artifacts/`:

- a full-page screenshot
- the current page HTML

This is meant to make selector issues and anti-bot issues easier to diagnose without adding unnecessary framework code.
