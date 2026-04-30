# Realtor.ca Scraper And Local Analyzer

This repository started as a small proof of concept built to answer one question:

Can a visible Python Playwright browser with stealth and light human-like behavior accept search inputs, drive Realtor.ca's filters, and scrape matching listing data?

That proof of concept now serves as the foundation for a local-first real-estate analyzer prototype.

Current prototype state:

- Scraper foundation working: neutral startup plus input-driven browser search
- Broader collection working: summary collection across pages plus conservative detail enrichment
- Rich detail extraction integrated into the same script
- Phase 1 Supabase model working: saved searches, scrape runs, canonical listings, and run history
- Light lifecycle handling implemented: active listings per saved search plus `is_new_in_run`
- Remaining Phase 1 follow-up: prove the inactive-listing transition with a controlled rerun
- Local website prototype in place: dashboard, saved search detail view, listing detail, photo gallery, and background scrape launch
- Safe speed pass completed: shorter fixed waits, lower `slow_mo`, and conservative parallel detail scraping
- Webshare API proxy selection working: each scraper run can randomly select one valid proxy from the Webshare API list, with manual proxy config as fallback
- Scraper performance pass completed: detail timing metrics, detail pause controls, optional detail asset blocking, and pagination stabilization are in place
- Current scraper reliability baseline: use `--detail-concurrency 6` with pacing and asset blocking; `12` remains historical benchmark context only after Realtor.ca security checks appeared during aggressive `14`/`16` tests
- Repeat-run optimization added: recently enriched listings can reuse cached detail from Supabase instead of re-opening every detail page
- Phase 3 started: structured and AI-assisted buy box with `matched`, `maybe`, and `unmatched` buckets
- Buy-box persistence working: one saved buy box per saved search, now run from the combined listing-analysis workspace and shown on listing-detail pages
- Listing Analysis workspace in place: buy-box screening and investment underwriting now run together for all active listings in a saved search
- Listing Analysis workflow now uses an explicit setup-and-run step: users confirm buy-box criteria and saved-search defaults, then press `Run analysis` or `Rerun analysis` to refresh the table
- Listing Analysis draft preservation working: unsaved buy-box edits survive source-mode button clicks until `Run analysis` commits the workflow
- Combined analysis verdicts working: each active listing can be grouped as `Strong`, `Review`, or `Reject` based on buy-box result plus underwriting result
- Underwriting persistence working: saved-search defaults, listing-level rent overrides, and the latest listing-analysis run snapshot per saved search
- CMHC market-reference layer working: imported market rent and vacancy reference rows can hydrate underwriting defaults
- CMHC source controls working: rent and vacancy can explicitly switch between manual and CMHC-backed values, including same-value source switches, and `Run analysis` now preserves active non-manual source modes
- CMHC fallback labeling improved: closest property-type matches such as Nanaimo townhouse baselines are labeled as closest matches instead of generic exact market matches
- Market context prototype in place: dedicated market pages now exist for scraped markets and can be opened directly from the dashboard
- Market navigation from Listing Analysis working: analysis pages link directly into the related market context page
- Market page state preservation working: bedroom filters persist through rental AI, appreciation AI, and appreciation proxy actions
- First structured market layer working: `population`, `population growth`, `unemployment`, and `median household income` can now be stored per market and rendered on the website
- Broader BC structured market coverage working: a bulk StatCan import path can now load those four structured metrics for matched BC markets instead of keeping the market layer limited to hand-seeded examples
- CREA HPI appreciation layer working: official CREA MLS HPI data is now ingested into Supabase and rendered on market pages with benchmark-price history plus 1M, 12M, 5Y, and 10Y metrics
- Vancouver Island appreciation proxy working: Duncan, Sidney, Nanaimo, and Tofino can now use an explicit opt-in Vancouver Island proxy path with clear low-confidence labeling
- AI appreciation fallback tightened: when official HPI data is missing, the AI estimate path now requests best-effort numeric estimates instead of accepting all-null metric cards
- Broader BC CMHC rental coverage working: CMHC market rental workbooks now feed apartment, townhouse, and condo-apartment rental cards for CMHC-covered BC markets like Victoria, Vancouver, Kelowna, Nanaimo, Kamloops, and Chilliwack
- Detached-house rental gap documented: CMHC detached and semi-detached BC coverage is still too incomplete or suppressed to present as a reliable single-family baseline yet
- AI rent source mode working: the `Market Rent Monthly` card can preview AI suggestions and apply them across the active underwriting table
- AI rent research upgraded: listing rent suggestions, market rental gap estimates, and market appreciation estimates now use OpenAI Responses API with web search and visible source/research-trail fields
- AI rent accepted-result display upgraded: listing detail pages show saved AI rent reasoning behind a collapsible panel, including main-unit plus suite/cottage rent components when returned
- Non-rent source modes working: utilities and insurance now support manual plus BC-wide rule-based modes, and utilities can explicitly set landlord-paid utilities to zero
- Listing-level reserve heuristics working: maintenance and CapEx can apply smart per-listing estimates using age, property type, HOA/strata cues, and update/condition signals from listing descriptions
- Listing-level underwriting overrides working: listing detail pages can edit the major underwriting assumptions that feed that listing's analysis
- Favorites working: listings can be hearted from detail/analyzer views and reviewed from a dedicated Favorites page grouped by saved-search location
- Listing-detail underwriting working: listing pages now show underwriting metrics, assumptions, and source context
- Listing-detail AI rent reasoning working: accepted AI rent suggestions and component breakdowns now show on the listing page after `Apply AI values`
- Buy-box AI screens expanded: the listing-analysis workspace supports two separate AI prompt screens plus optional base filters
- Buy-box AI persistence working: `Run analysis` persists AI buy-box results in the saved-search analysis snapshot; normal analyzer and listing-detail navigation read saved results instead of rerunning AI
- Buy-box research trail visible: web-search-backed buy-box screens save research summaries/source URLs and listing detail exposes them in a collapsible `Research trail`
- Listing-analysis results UX simplified: the table now emphasizes `Final Score`, `Buy Box Outcome`, and `Underwriting Score`, uses header info chips for scoring logic, hides low-value scraped taxes/HOA/warnings columns, and color-codes core investment metrics
- Automated tests in place: pytest coverage now protects underwriting math, market matching, buy-box helpers, and key Flask routes
- Reliability pass in progress: sparse-detail retry, stricter detached-house filtering, improved pagination collection, and corrected `BC` versus `British Columbia` location matching for Nanaimo-style searches
- Current active step: build the planned AI chat surfaces for listing detail, market context, and listing analyzer pages
- Current performance priority: cache repeated market reference reads and move longer AI actions toward background jobs so ordinary navigation stays responsive

## What It Does Today

- Opens a visible Chromium browser
- Applies `playwright-stealth`
- Opens the Realtor.ca map/results experience in a visible browser
- Accepts runtime search inputs for location, min/max price, minimum beds, and property type
- Uses the visible Realtor.ca search UI to apply those filters
- Supports broader collection controls for max pages, max listings, detail limit, and detail concurrency
- Supports detail pacing controls with `--detail-pause-min` and `--detail-pause-max`
- Supports optional detail-page asset blocking with `--block-detail-assets`
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
- Serves a local website for browsing active listings and running combined listing analysis
- Supports an AI interpretation goal for fuzzy listing-description criteria such as secondary suite potential
- Supports targeted retry of only sparse listing details instead of forcing a full rerun
- Supports a dedicated saved-search listing-analysis page with buy-box controls, grouped listing comparison, and computed investment metrics
- Supports an explicit listing-analysis setup state before results are generated, so changing assumptions does not automatically rewrite the table until the user reruns analysis
- Preserves unsaved buy-box draft edits while users work through source-mode controls before running analysis
- Supports listing-specific rent overrides that feed the underwriting table and listing-detail page
- Supports listing-detail edits for major underwriting assumptions such as rent, down payment, interest rate, amortization, operating expenses, and source metadata
- Supports favoriting listings and reviewing favorites grouped by saved-search location
- Supports CMHC market-reference matching for market rent and vacancy baselines
- Labels CMHC closest property-type baselines, such as townhouse rows used for house searches, separately from exact market matches
- Supports web-search-backed AI rent/appreciation estimates with source URLs, direct-comparison counts, fallback-comparison counts, and fallback strategy notes
- Supports persisted researched buy-box results with collapsible source/research trails on listing detail pages
- Supports accepted listing-level AI rent suggestions with optional main-unit plus suite/cottage component breakdowns
- Supports BC-wide rule-based utilities and insurance estimates when manual values are not known
- Supports separate smart maintenance and smart CapEx per-listing override passes for active listings
- Includes a local pytest suite for the deterministic underwriting and app logic
- Supports dedicated market context pages backed by:
  - CMHC rent and vacancy where available
  - seeded structured market metrics
  - seeded appreciation history where an official series exists
- Preserves selected market bedroom filters across market-page actions such as rental AI estimates and appreciation proxy/AI workflows
- Supports a bulk StatCan market-metrics import workflow so matched BC markets can auto-fill `population`, `population growth`, `unemployment`, and `median household income`

For the current scraper/proxy/performance handoff, see [docs/scraper_status.md](/Users/georgia/Projects/simple realtor.ca scraper python/docs/scraper_status.md:1).
For the staged AI chatbot plan, see [docs/AI_CHATBOT_ROADMAP.md](/Users/georgia/Projects/simple realtor.ca scraper python/docs/AI_CHATBOT_ROADMAP.md:1).
For current page-load and AI latency notes, see [docs/PERFORMANCE_NOTES.md](/Users/georgia/Projects/simple realtor.ca scraper python/docs/PERFORMANCE_NOTES.md:1).
For the current UI polish handoff and remaining product-facing cleanup list, see [docs/UI_POLISH_ROADMAP.md](/Users/georgia/Projects/simple realtor.ca scraper python/docs/UI_POLISH_ROADMAP.md:1).

## What It Is Not Yet

This is not yet:

- a finished listing-analysis product
- a polished final investment analyzer
- a finished market fundamentals analyzer
- a multi-user application
- a deployed production website

The repository is currently a usable local-first scraper, ingestion layer, and early listing-analysis prototype.

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
playwright install chromium
python scraper.py

# run the automated tests
.venv/bin/python -m pytest -q

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

# performance benchmark pass with explicit detail pacing
python scraper.py \
  --location Victoria \
  --beds-min 2 \
  --property-type house \
  --max-price 1000000 \
  --max-pages 1 \
  --max-listings 12 \
  --detail-limit 6 \
  --detail-concurrency 3 \
  --detail-pause-min 0.25 \
  --detail-pause-max 0.6 \
  --no-supabase

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

# current proxy-backed baseline after security-challenge testing
python scraper.py \
  --location Victoria \
  --beds-min 2 \
  --property-type house \
  --max-price 1000000 \
  --max-pages 1 \
  --max-listings 12 \
  --detail-limit 12 \
  --detail-concurrency 6 \
  --detail-pause-min 0.2 \
  --detail-pause-max 0.5 \
  --block-detail-assets \
  --no-supabase \
  --no-print-listings

# run the first local website scaffold
python app.py

# import BC CMHC market reference data from the workbook
python3 scripts/import_cmhc_market_data.py \
  "/Users/georgia/Documents/rmr-british-columbia-2025-en.xlsx" \
  --source-url "https://www.cmhc-schl.gc.ca/professionals/housing-markets-data-and-research/housing-data/data-tables/rental-market/rental-market-report-data-tables"

# bulk import Statistics Canada market metrics from a CSV file
python3 scripts/import_statcan_market_metrics.py
```

Then open `http://127.0.0.1:5000` unless you are using a different local port during development.

Important local note:

- On this machine, `5000` has occasionally conflicted with other local services in Chrome, so recent development runs have used `http://127.0.0.1:8002`.

## Environment

Copy `.env.example` to `.env.local` and fill in the values needed for your local workflow.

Current config surface:

- `SUPABASE_URL`
- `SUPABASE_KEY`
- `OPENAI_API_KEY` for AI buy-box analysis and AI rent suggestions
- `OPENAI_BUY_BOX_MODEL` optional override for buy-box AI analysis
- `OPENAI_UNDERWRITING_MODEL` optional override for rent suggestion analysis
- `OPENAI_RESEARCH_MODEL` optional override for web-search-backed rent, appreciation, and future chat research
- `WEBSHARE_API_KEY` optional Webshare API key for automatic proxy-list selection
- `WEBSHARE_PROXY_MODE` optional Webshare proxy mode, either `direct` or `backbone`; defaults to `direct`
- `WEBSHARE_PROXY_COUNTRY_CODES` optional comma-separated Webshare country filter, for example `CA,US`
- `SCRAPER_PROXY_ENABLED` optional proxy toggle for Playwright scraper runs
- `SCRAPER_PROXY_SERVER` optional proxy server, for example `http://p.webshare.io:80`
- `SCRAPER_PROXY_USERNAME` optional proxy username
- `SCRAPER_PROXY_PASSWORD` optional proxy password

Important notes:

- Supabase is required for the persistent saved-search, scrape-history, and listing-analysis workflow.
- OpenAI configuration is optional. Without it, the core scraper, Supabase flow, and non-AI underwriting still work, but AI buy-box, AI rent, AI appreciation, and future AI chat features are unavailable.
- Scraper proxy configuration is optional. When `WEBSHARE_API_KEY` is set, the scraper fetches the current Webshare proxy list and randomly selects a valid proxy. If the API lookup fails or returns no valid proxies, it falls back to the manual `SCRAPER_PROXY_*` fields. Playwright logs only the proxy host/port.
- The latest speed tests triggered Realtor.ca security-check pages after aggressive detail concurrency. Treat `--detail-concurrency 6` as the current stable baseline. Treat `12` as historical benchmark context, not the default.

### Webshare Residential Proxy Setup

For Webshare Proxy Server plans, prefer API-based selection so you do not need to manually update `.env.local` when Webshare replaces or rotates IPs.

Example `.env.local` values:

```bash
WEBSHARE_API_KEY=your_webshare_api_key
WEBSHARE_PROXY_MODE=direct
WEBSHARE_PROXY_COUNTRY_CODES=CA,US
```

The scraper supports two modes:

- `direct` selects one proxy-list IP and port from Webshare's API response.
- `backbone` uses `p.webshare.io` with credentials from the selected proxy row.

Manual proxy values are still supported as a fallback. If Webshare gives you a full proxy URL like `http://username:password@host:port`, split it into:

```bash
SCRAPER_PROXY_ENABLED=true
SCRAPER_PROXY_SERVER=http://host-or-endpoint:port
SCRAPER_PROXY_USERNAME=your_webshare_username
SCRAPER_PROXY_PASSWORD=your_webshare_password
```

Run a small validation scrape before increasing limits:

```bash
python scraper.py \
  --location Victoria \
  --beds-min 2 \
  --property-type house \
  --max-price 1000000 \
  --max-pages 1 \
  --max-listings 3 \
  --detail-limit 1 \
  --detail-concurrency 1 \
  --no-supabase
```

## Supabase

Supabase writes are currently integrated into the same `scraper.py` script.

Setup:

1. Create the table in Supabase with [supabase/schema.sql](/Users/georgia/Projects/simple realtor.ca scraper python/supabase/schema.sql:1).
2. Copy `.env.example` to `.env.local` and fill in:
   - `SUPABASE_URL`
   - `SUPABASE_KEY`
   - optionally `OPENAI_API_KEY` if you want AI buy-box analysis and AI rent suggestions
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
- The Supabase schema now stores saved searches, scrape runs, canonical listings, run-to-listing history, saved-search lifecycle state, underwriting defaults, listing overrides, CMHC market reference rows, AI suggestion history, and first-pass market context tables separately.
- CMHC import currently parses the BC rental-market workbook for apartment baselines, and the repo now also includes a market-workbook parser for `townhouse` and `condo_apartment` rows where CMHC publishes them cleanly.
- First-pass market context seeding now uses:
  - [supabase/market_context_seed.sql](/Users/georgia/Projects/simple realtor.ca scraper python/supabase/market_context_seed.sql:1)
  - [scripts/seed_market_context.py](/Users/georgia/Projects/simple realtor.ca scraper python/scripts/seed_market_context.py:1)
- Bulk StatCan market-metrics import now uses:
  - [data/statcan_bc_market_metrics.csv](/Users/georgia/Projects/simple realtor.ca scraper python/data/statcan_bc_market_metrics.csv:1)
  - [scripts/generate_statcan_bc_market_metrics_csv.py](/Users/georgia/Projects/simple realtor.ca scraper python/scripts/generate_statcan_bc_market_metrics_csv.py:1)
  - [scripts/import_statcan_market_metrics.py](/Users/georgia/Projects/simple realtor.ca scraper python/scripts/import_statcan_market_metrics.py:1)

## Current Integrated Flow

The current `scraper.py` is the integrated script for the project.

What is already working in the integrated flow:

- the scraper can collect broader result sets across multiple pages
- the scraper can stop at configurable summary and detail caps
- the scraper can enrich detail pages with configurable detail concurrency and randomized detail pacing
- repeat runs can reuse recently scraped, fully enriched listing detail instead of visiting every detail page again
- the scraper can extract richer detail fields directly into the same JSON output
- the scraper can extract listing photos and persist them inside the stored raw listing payload
- the browser-first headed Playwright plus `playwright-stealth` setup remained stable during larger runs
- the scraper can use Webshare API-selected proxies and logs the selected host/port without credentials
- the scraper can optionally block nonessential detail-page assets to reduce bandwidth and load time
- the scraper detects Realtor.ca security-check pages and stops queued detail work instead of blindly retrying challenged tabs
- the scraper now starts from a neutral Realtor.ca map page rather than a Victoria-specific hard-coded map state
- the scraper now runs location-based collection without relying on `Search within boundary`
- the scraper now waits for a settled results state before collection and uses more robust page-2 navigation fallbacks
- the scraper now persists data into `saved_searches`, `scrape_runs`, `listings`, and `scrape_run_listings`
- the scraper now maintains a saved-search-specific active-listing view via `current_active_saved_search_listings`
- the scraper now has a targeted sparse-detail retry script for repairing missing detail fields

Example historical validated outcome:

- a Victoria search with `2+` beds, `house`, and `max price 1000000`
- produced `58` visible matching listings on Realtor.ca for that search state in one validated run
- successfully collected `12` summaries in a broader validation pass
- successfully enriched `4` detail pages with the cleaned Phase 3 schema
- successfully upserted validated listing data into Supabase in live testing

This block is included as an example of a successful validation pass, not as a claim about current live market counts.

Recent performance validation:

- `60` Victoria summaries across `5` results pages collected successfully after pagination stabilization.
- `60/60` detail enrichment succeeded at `detail_concurrency=12` before security challenges appeared.
- `--block-detail-assets` reduced the best 60-listing run from `106.1s` total to `90.9s` total, with photos still present for every listing.
- `detail_concurrency=14` and `16` caused many first-pass detail failures and visible Realtor.ca security-check pages.
- A later `detail_concurrency=12` rerun also showed security-check pages, so the next scraper pass should retest lower concurrency first. See [docs/scraper_status.md](/Users/georgia/Projects/simple realtor.ca scraper python/docs/scraper_status.md:1).

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
- listing detail page with photo gallery and richer scraped fields
- direct market context links from the dashboard
- dashboard `Markets analyzed` panel listing unique markets rather than only saved searches
- saved-search detail page focused on scraped inventory plus an `Analyze Listings` entry point
- listing-analysis workspace with:
  - buy-box screening controls
  - AI interpretation goal
  - saved-search underwriting assumptions
  - source controls for market rent, vacancy, utilities, and insurance
  - explicit `Run analysis` / `Rerun analysis` action that saves buy-box criteria and underwriting defaults together before refreshing results
  - a setup state that hides the results table until analysis has been run
  - latest analysis persistence through the saved-search snapshot so reloads and local server restarts can show the most recent run
  - combined `Strong`, `Review`, and `Reject` final verdicts
- saved buy-box summary showing the currently persisted structured and AI criteria where relevant
- buy-box verdict and AI reasoning on the listing-detail page
- listing-analysis page with:
  - all active listings underwritten by default
  - grouping by combined buy-box plus underwriting verdict
  - sorting within each group by strongest monthly cash flow first
  - compact score columns for `Final Score`, `Buy Box Outcome`, and `Underwriting Score`
  - explanatory info chips in the table headers instead of repeated row-level reason text
  - metric color bands for cash flow, cap rate, cash-on-cash, and rent-to-price ratio
  - saved-search underwriting defaults
  - local source controls for market rent, vacancy, utilities, and insurance
  - source-mode changes that persist independently without automatically rerunning the visible results table
  - AI rent preview and `Apply AI values` flow inside the `Market Rent Monthly` card
  - accepted AI rent suggestions that persist to Supabase after apply and can include main-unit plus suite/cottage rent components
  - BC-wide rule-based utilities and insurance defaults
  - separate `Apply smart maintenance` and `Apply smart CapEx` actions that write listing-level reserve overrides
  - listing-level rent overrides
- market context page with:
  - CMHC-backed housing fundamentals
  - structured market metrics for Duncan and Victoria
  - a direct market route like `/markets/victoria_bc`
  - an appreciation section that shows a real chart when a series exists and an explicit `Series pending` state when it does not
- listing-detail underwriting section with:
  - monthly cash flow
  - cap rate
  - cash-on-cash
  - rent-to-price ratio
  - assumptions and source summary
  - accepted AI rent reasoning and component breakdowns when present, collapsed behind `Rent reasoning`
  - persisted buy-box research/source details when present, collapsed behind `Research trail`
  - visibility into smart listing-level reserve overrides through `Assumptions Used`

Current website limitations:

- no authentication
- no persistent job queue beyond the current local app process
- no edit/delete workflow for saved searches yet
- no polished error handling yet
- no dedicated run comparison or retry UX yet
- no explicit “why this listing was reused vs re-scraped” UI yet
- site result counts can still fluctuate while Realtor.ca settles
- `Vacancy %` is intentionally not AI-driven right now; it should come from market stats such as CMHC when available and remain user-editable
- underwriting source-mode UI still needs another polish pass so smart overrides and active modes are more obvious
- CMHC rent data is still incomplete for detached-house coverage in BC, so house searches can still require manual or AI adjustment even after the new townhouse / condo groundwork
- utilities and insurance rule-based estimates are BC-wide heuristics, not market-specific estimates
- smart maintenance and smart CapEx are heuristic listing-level overrides, not full asset-condition models
- the results table is cleaner than before, but deal-type explanation, expandable row details, and projection metrics are still not built

## Product Direction

The intended product direction is:

1. define a saved search for a market of interest
2. scrape all active listings matching that saved search
3. store both the current listing state and scrape history
4. show current active listings in a local application
5. evaluate those listings in one combined buy-box plus underwriting workspace
6. explicitly run or rerun analysis after confirming buy-box criteria and saved-search defaults
7. review final `Strong`, `Review`, and `Reject` analysis buckets
8. later add review workflow, market analysis, notes, shortlist behavior, and explicit run comparison

Important scope clarifications:

- `saved search` and `buy box` are related but separate concepts
- the current near-term goal is to finish a clearer first full prototype of the listing-analysis workflow within a selected market
- broader market fundamentals analysis is a later product area, but the roadmap now explicitly leaves room for a future market analyzer

## Listing Analysis Direction

The next major product area is a buy-and-hold listing-analysis workspace layered on top of scraped listings.
This workspace now combines buy-box screening with underwriting instead of requiring the user to run one workflow and then another.

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
- buy-box and underwriting results should be merged into a practical final verdict, currently `Strong`, `Review`, or `Reject`
- table labels now use `Final Score`, `Buy Box Outcome`, and `Underwriting Score`; the current direction is to keep the three-column score view compact and move detailed explanations into info chips or expandable detail
- long-term metrics like appreciation, IRR, and equity multiple should be phase 2+ work after the base underwriting engine is stable; IRR should be added as a projection metric, not as a replacement for cash-flow survivability
- future market context should support items like rent growth, appreciation, population growth, job growth, household income, supply, and liquidity

### IRR Projection Notes

IRR is intentionally not implemented yet. When added, it should live in a projection layer rather than the core underwriting score.

Planned V1 inputs:

- hold period, defaulting to 5 years
- appreciation rate with explicit source modes: official market data, approved proxy, manual, and optionally AI estimate
- rent growth rate
- expense growth rate
- selling cost percentage

Planned calculation:

- initial cash outflow is down payment plus closing costs
- annual cash flows start from current underwriting and grow rent/expenses separately
- exit proceeds equal projected sale price minus selling costs and remaining loan balance
- IRR solves the annualized return from the initial cash outflow, yearly cash flows, and sale proceeds

Appreciation source priority should be:

1. exact CREA HPI or other official market/property-type series where available
2. explicit approved proxy, clearly labeled lower confidence
3. manual user input
4. AI estimate only as an explicit fallback/synthesis path, never silently selected

IRR benchmarks under consideration:

- below 10%: weak
- 10% to 15%: solid
- 15% to 20%: strong
- 20% or higher: excellent

Product guardrail: a strong IRR should not automatically make a weak cash-flow property `Strong`. If cash flow is weak but projected IRR is attractive, the listing should usually remain `Review` and be framed as a possible appreciation or value-add bet.

AI-assisted estimation is already part of the product for selective cases, but not every assumption should become AI-driven. The intended rule is:

- use structured or public data first when available
- use AI as a fallback or synthesis layer where it adds real value, such as fuzzy buy-box interpretation or rent estimation
- keep `Vacancy %` sourced from market stats plus manual user input for now rather than adding an AI vacancy mode
- always show source and confidence
- always allow the user to edit the estimate

## Project Phases

The current working roadmap is:

1. stabilize scrape result counts and pagination reliability
2. continue improving listing-review workflow in the local app
3. improve the clarity of the existing investment-assumptions and underwriting UI
4. keep refining market-derived defaults and selective AI-assisted estimates
5. add a future market analyzer with market tiles generated from scraped regions
6. later add long-term projections, IRR, equity multiple, and other strategy overlays

See [PROJECT_OVERVIEW.md](/Users/georgia/Projects/simple realtor.ca scraper python/PROJECT_OVERVIEW.md:1) for the detailed product spec and next-session handoff notes.
See [PRODUCT_INSPIRATION.md](/Users/georgia/Projects/simple realtor.ca scraper python/PRODUCT_INSPIRATION.md:1) for external product references, screenshot-derived UI patterns, and future design ideas that should persist across sessions.

## Current Next Steps

Highest-value next work from the current state:

1. tighten the results table language; consider whether to emphasize only a single final rating and reduce visible `Buy Box` / `Underwriting` label noise
2. keep improving source-mode clarity so active modes and listing-level smart overrides are obvious without opening every listing
3. keep `Vacancy %` as `manual` plus market-stats-backed input, and keep that source choice clear in the UI
4. improve the saved-search and listing-detail UI so incomplete data, missing details, and next actions are easier to interpret
5. add workflow states such as shortlist / ignore / notes for reviewed listings
6. add clearer run-to-run comparison so `new in update` can be interpreted against collected-set churn
7. continue scraper hardening only where it directly supports the prototype workflow

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
- polish the listing-analysis results UX, especially whether `Final`, buy-box fit, and underwriting strength should remain separate visible columns
- polish the listing-analysis assumption UX, especially the visibility of per-listing smart overrides versus shared defaults
- improve the saved-search and listing-detail UI so missing detail fields and incomplete underwriting inputs are clearer
- keep vacancy source modes tied to market stats plus manual editing rather than adding an AI vacancy path
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
## Market Context Status

The first market-context layer is now real in the codebase.

What is working now:

- market pages can be opened from the dashboard
- market pages can also be opened directly by market key:
  - `/markets/victoria_bc`
  - `/markets/duncan_bc`
- the current page shape includes:
  - market header and linked saved searches
  - housing fundamentals
  - appreciation
  - demographics and labour
- Duncan and Victoria now have seeded structured market metrics:
  - `population`
  - `population growth`
  - `unemployment rate`
  - `median household income`
- Victoria now has a seeded Statistics Canada RPPI appreciation series in `market_metric_series`
- Duncan intentionally does not yet have a matched appreciation series, so the page shows a clean empty state instead of proxying bad data
- newly discovered markets now persist into `market_profiles` automatically with normalized keys such as `sidney_bc`
- matched BC markets can now pick up bulk-imported StatCan metrics through `market_metrics`
- CMHC-backed rental fundamentals still depend on matching rows in `market_reference_data`, so markets like Sidney can now show structured metrics while still correctly showing no exact CMHC rent baseline

What is intentionally not finished yet:

- no rent-growth series yet
- no appreciation series beyond the current Victoria seed
- no AI-enriched market narrative yet
- no broader national market ingestion workflow yet
- no direct long-term return modeling wired from market context into listing pages yet

Current source choices:

- CMHC for rent and vacancy
- Statistics Canada 2021 Census for population, growth, unemployment, and household income
- Statistics Canada RPPI for Victoria appreciation history
- explicit empty-state handling for markets with no matched official appreciation series

## Fresh Agent Handoff

If a new agent picks this up later, the most important current truths are:

- this is a local-first Flask plus Supabase prototype, not a deployed website
- the listing-analysis loop is real and usable now
- the underwriting UI has been improved substantially, but should still be tightened further before large new feature areas are added
- the market-context layer has started and is now a real part of the website
- Victoria is the first market with a live appreciation chart
- Duncan has market stats but no appreciation series yet
- future smaller-market appreciation support will likely need a different source path than Victoria

## Next Steps

The next practical product and engineering steps are:

1. improve the presentation of the appreciation block:
   - friendlier quarter labels
   - stronger chart polish
   - slightly clearer source/context copy
2. decide the next appreciation-source path for non-StatCan markets such as Duncan
3. add the next market-context fields selectively rather than all at once:
   - likely `rent growth`
   - then selective market narrative / economic-driver fields
4. expand the bulk StatCan BC market CSV and generator coverage further, especially for markets that appear in `market_reference_data` but do not yet match cleanly
5. keep improving underwriting workflow clarity in parallel:
   - source-mode readability
   - shortlist / ignore / notes style review workflow
6. only after that, revisit wiring market context into longer-term return projections

## Push State

At the end of this session, the expected repo state for handoff is:

- docs updated to reflect current website and market-context functionality
- dashboard updated to link directly into market pages
- Duncan and Victoria seeded as first analyzed markets
- Victoria appreciation series seeded from Statistics Canada
