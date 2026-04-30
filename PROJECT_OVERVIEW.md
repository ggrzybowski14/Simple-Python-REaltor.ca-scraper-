# Project Overview

## Premise

This repository started as a proof of concept for a visible Realtor.ca scraper built with Python and Playwright. It has now progressed into the foundation of a local-first real-estate analyzer for a single primary user.

The project is no longer just "can we scrape Realtor.ca?" The next question is:

Can this scraper, data model, and local website support a repeatable workflow for:

1. collecting active listings by market
2. filtering them against a buy box
3. underwriting them with investment metrics in the same listing-analysis workflow
4. later adding market context and deeper review workflow

## Current State

The codebase now has three working layers:

- a headed Realtor.ca scraper with conservative anti-bot behavior
- a Supabase-backed ingestion and lifecycle model
- a local Flask website for browsing saved searches, listings, and combined listing-analysis results

The codebase now also has the first real underwriting layer:

- a saved-search listing-analysis page for all active listings
- explicit setup-and-run listing-analysis workflow: confirm buy-box criteria and underwriting defaults, then run or rerun analysis
- combined buy-box plus underwriting final verdicts
- persisted underwriting defaults at the saved-search level
- listing-level rent and underwriting assumption overrides
- persisted latest listing-analysis run snapshot per saved search
- persisted buy-box AI result snapshots per saved-search analysis run, so normal navigation and listing detail views reuse saved AI results instead of rerunning them
- CMHC-backed market reference data for rent and vacancy baselines
- explicit source-mode preservation so `Run analysis` does not silently convert active CMHC, AI, rule-based, or off assumptions back to manual
- buy-box draft preservation while users work through source-mode buttons before committing with `Run analysis`
- two configurable buy-box AI screens plus optional base filters
- favorites support for marking listings and reviewing them by saved-search location
- BC-wide rule-based utilities and insurance defaults
- listing-level smart maintenance and CapEx override support

The codebase now also has the first real market-context layer:

- direct market routes such as `/markets/victoria_bc`
- dashboard navigation for unique analyzed markets
- listing-analysis navigation into related market context pages
- first-pass `market_profiles`, `market_metrics`, and `market_metric_series`
- seeded Duncan and Victoria market stats
- seeded Victoria appreciation history from Statistics Canada RPPI
- explicit empty-state behavior for markets without a matched appreciation series yet
- automatic market-profile bootstrap for newly discovered scraped markets
- a bulk StatCan import path for the core structured market metrics used by the current market page
- CMHC rental cards for apartment, townhouse, condo-apartment, and AI-estimated detached-house gaps where official detached-house values are missing
- market-page bedroom filters that persist through rental AI, appreciation proxy, and appreciation AI actions
- web-search-backed AI rental and appreciation estimates that expose source URLs, direct-comparison counts, fallback-comparison counts, and fallback strategy notes

This is still an early application, not a polished product, but it is already beyond pure scraping validation.

This file should help a new agent answer three questions quickly:

- what functionality is already real in the codebase
- what product direction is actively being pursued next
- which product decisions are already settled and should not be re-litigated by default

For the current customer-facing UI polish handoff and remaining demo-readiness backlog, see [docs/UI_POLISH_ROADMAP.md](/Users/georgia/Projects/simple realtor.ca scraper python/docs/UI_POLISH_ROADMAP.md:1).

## What Works Today

### Scraper

- starts from a neutral Realtor.ca map page rather than a Victoria-specific hard-coded URL
- accepts structured inputs for location, min price, max price, minimum beds, and property type
- applies those filters through the visible Realtor.ca UI
- collects listing summaries across result pages
- enriches listing detail pages with full description, property facts, and photos
- saves local JSON output and failure artifacts
- writes successful runs into Supabase

### Supabase Model

The database design now separates:

- `saved_searches`
- `scrape_runs`
- `listings`
- `scrape_run_listings`
- `saved_search_listings`

This gives the project:

- one canonical row per listing
- scrape-run history
- saved-search-specific lifecycle tracking
- a current active-listings view through `current_active_saved_search_listings`

### Local Website

The local website currently provides:

- dashboard of tracked searches
- dashboard language polished into customer-facing listing-search terminology
- latest-run indicator on the saved search updated most recently
- background launch of headed scrape jobs
- saved-search detail page with all active scraped listings
- saved-search detail page polished into `Listing search` language with readable last-updated timestamps, compact listing cards, and product-facing actions
- saved-search detail page now acts as inventory review plus entry point into `Analyze Listings`
- listing detail page with richer fields and photo gallery
- collapsible recent-run history
- persisted buy-box settings per saved search
- listing-analysis page where buy-box screening and underwriting assumptions run together
- listing-analysis hero and setup copy now use customer-facing `Analysis`, `Listing preferences`, and `Interest` language
- listing-analysis assumptions section has been partially compacted and reordered, with financing first, monthly rent second, and operating costs third
- listing-analysis page now starts in a setup state and only fills the results table after the user presses `Run analysis`
- unsaved buy-box text fields survive source-mode button redirects until `Run analysis` is pressed
- latest listing-analysis run persists in the saved-search snapshot and can be restored after a reload or local server restart
- listing-analysis results table now uses compact score columns: `Final Score`, `Buy Box Outcome`, and `Underwriting Score`
- repeated row-level score explanation text has been moved into header info chips; scraped taxes, HOA, and warnings are not shown as table columns
- cash flow, cap rate, cash-on-cash, and rent-to-price ratio use green / orange / red metric color bands
- listing-detail pages read persisted buy-box results from `latest_listing_analysis` and show researched buy-box sources behind a collapsible `Research trail`
- targeted retry of sparse listing details
- investment analyzer route retained as the listing-analysis URL for underwriting all active listings in a saved search
- listing-detail underwriting summary and assumptions/source display
- source-mode controls for rent, vacancy, utilities, and insurance
- source-mode controls preserve active non-manual modes during `Run analysis`
- smart per-listing maintenance and CapEx estimate actions
- accepted AI rent suggestions are persisted and visible on listing detail; when the AI identifies a genuine additional rentable unit, saved results can show main-unit plus suite/cottage rent components behind `Rent reasoning`
- direct market-context pages for analyzed markets
- a dashboard-level `Markets analyzed` panel for fast market navigation
- market-level structured metrics and appreciation scaffolding
- market-context pages preserve selected bedroom filters across page actions

### Buy Box

Phase 3 has started with an initial buy-box workflow.

Current buy-box inputs:

- max price
- minimum beds
- property type
- required keywords in description
- AI interpretation goal

Current buy-box output buckets:

- `matched`
- `maybe`
- `unmatched`

The AI-assisted part now supports a qualitative rule such as:

- "separate suite for rental income"

The app uses structured rules first, then sends the remaining candidate listing descriptions to OpenAI for a `likely` / `maybe` / `no` judgment with a short reason.

This is specifically meant to handle cases where plain keyword matching is too weak, such as:

- distinguishing a true secondary suite from `ensuite`
- separating actual suite evidence from generic rental-history language

## Product Vision

The intended product direction is now:

1. define or reuse a saved search for a market
2. scrape all active listings matching that market search
3. store current listing state plus scrape history
4. review listings in the local website
5. confirm buy-box screening criteria and underwriting defaults in the listing-analysis workspace
6. run or rerun analysis to generate the active results table
7. review combined `Strong`, `Review`, and `Reject` results
8. later add listing workflow states, market context, and projection tools

The product remains single-user and local-first for now.

## Core Product Concepts

### Saved Search Versus Buy Box

These remain separate concepts.

- a `saved search` defines what Realtor.ca inventory to collect
- a `buy box` defines how to evaluate the collected listings

### Listing Analyzer Versus Market Analyzer

These are also separate layers.

- the `listing analyzer` evaluates a specific property
- the `market analyzer` evaluates a market like `Duncan` or `Victoria`

The listing analyzer is the more mature product area. The market analyzer is no longer just future thinking; the first scaffold is now built, but it is still intentionally narrow.

## Next Major Product Area: Listing Analysis

The next phase of the project is no longer just listing review. It is a buy-and-hold listing-analysis workspace layered on top of scraped listings.
This workspace now runs buy-box screening and underwriting together instead of asking the user to run a buy box first and then open a separate underwriting flow.

The first V1 slice is now built.

The immediate goal is:

- take a scraped listing
- auto-fill investment assumptions as much as possible
- let the user edit those assumptions
- calculate practical investment metrics
- show quick visual judgment on whether the listing is `Strong`, needs `Review`, or should be rejected

What is already implemented:

- `/saved-searches/<id>/investment-analyzer`
- setup-first listing-analysis workflow where source-mode changes save independently and table results update only after `Run analysis` / `Rerun analysis`
- buy-box controls on the listing-analysis page
- combined buy-box plus underwriting verdicts for all active listings
- sorting within each combined result group by strongest performance first
- saved-search underwriting defaults
- listing-level rent and underwriting assumption overrides
- listing-detail underwriting section
- clickable Realtor.ca listing URLs on listing-detail pages
- listing favorites shown throughout the site and collected on a dedicated Favorites page
- source-aware market rent and vacancy controls
- same-value source switching for rent and vacancy, so manual and CMHC modes can be selected even when their numeric values match
- `Run analysis` preserves active CMHC, AI, rule-based, and off source modes unless the user explicitly applies a manual value
- source-aware utilities and insurance controls
- BC-wide rule-based utilities and insurance heuristics
- listing-level smart maintenance and CapEx heuristic overrides
- CMHC market-reference import and match scaffolding
- AI rent preview inside the `Market Rent Monthly` card
- `Apply AI values` flow that applies listing-level AI rent suggestions across the underwriting table and refreshes the saved analysis snapshot
- listing-detail panel showing accepted AI rent reasoning and optional main-unit plus suite/cottage component breakdowns
- listing-detail panel showing saved buy-box results and collapsible research/source details when the run used web-search-backed buy-box AI
- web-search-backed AI rent/appreciation helpers using the OpenAI Responses API
- local automated tests for underwriting math, market matching, helper logic, and key routes

## Market Context Layer

The first market-context page is now in the product.

Current page structure:

- market header and linked saved searches
- housing fundamentals
- appreciation history
- demographics and labour

Recent behavior:

- selected bedroom filters persist across market-page actions
- appreciation proxy and AI actions preserve the current rental-baseline bedroom selection
- AI appreciation estimates now request best-effort numeric values when official HPI coverage is missing
- CMHC closest property-type rows are labeled as closest matches rather than generic exact matches

Current live market-context coverage:

- `Duncan`
  - CMHC housing fundamentals
  - seeded Statistics Canada market stats
  - Vancouver Island appreciation proxy available
- `Sidney`
  - auto-created discovered market profile
  - Statistics Canada structured market stats imported
  - no exact CMHC housing fundamentals yet
  - Vancouver Island appreciation proxy available
- `Nanaimo`
  - CMHC apartment and townhouse rental fundamentals
  - AI-estimated detached-house rental gaps where official detached-house rent is missing
  - Vancouver Island appreciation proxy available
- `Tofino`
  - discovered market profile from scraped saved searches
  - no official CMHC baseline imported yet
  - Vancouver Island appreciation proxy available for AI appreciation anchoring
- `Vancouver`
  - CMHC housing fundamentals
  - Statistics Canada structured market stats imported
  - no appreciation series yet
- `Victoria`
  - CMHC housing fundamentals
  - seeded Statistics Canada market stats
  - seeded Statistics Canada RPPI appreciation history

This is intentionally not yet a full market analyzer. It is a first market brief that supports the future projection layer.

### Current Data Model Direction

The market-context layer now points toward these concepts:

- `market_profiles`
- `market_metrics`
- `market_metric_series`

This is important because it separates:

- `saved_search`
  the inventory collection rule
- `market`
  the contextual object shared across one or more saved searches

That separation should remain intact as this area grows.

### Settled Product Decisions

The following should be treated as current working assumptions unless the user explicitly changes them:

- `Vacancy %` stays stats-backed plus manually editable; it is not an AI mode right now
- market pages should support partial coverage cleanly rather than forcing fake completeness
- appreciation charts should only render when we have a real source series
- smaller markets should show clean empty states unless a curated explicit proxy or user-triggered AI estimate is available
- source labels should distinguish official CMHC rows, closest property-type baselines, proxies, and AI estimates
- listing workflow clarity is still a higher priority than broad new product surface
- the result-label model is unsettled: `Final` may become the primary visible rating, with buy-box fit and underwriting strength demoted to supporting context

### Strategy Scope For V1

V1 supports only:

- `buy, rent, and hold`

Explicitly not in v1:

- BRRR
- flipping
- short-term rental underwriting
- advanced tax modeling

Those can be added later as separate strategy overlays.

## Investment Analyzer Framework

### 1. Backbone: Cash Flow

Everything starts with cash flow. If the monthly cash picture is weak or fragile, higher-level metrics become less meaningful.

Primary cash flow formula:

- `net cash flow = rent - (mortgage + taxes + insurance + maintenance + vacancy + management + HOA/strata + utilities if landlord-paid + other recurring expenses)`

Practical underwriting guidance for defaults and stress testing:

- build in `5% to 8%` vacancy
- assume `maintenance + CapEx reserve` around `8% to 15%` of rent when exact data is unknown
- evaluate not just whether cash flow is positive, but whether it remains positive under mild stress

### 2. Yield Metrics

These are the first-pass screening tools.

- `NOI`
  Formula: `gross operating income - operating expenses`
  Product decision: `CapEx` stays separate from `NOI` in v1.
- `cap rate`
  Formula: `NOI / purchase price`
- `cash-on-cash return`
  Formula: `annual pre-tax cash flow / total cash invested`
- `rent-to-price ratio`
  Formula: `monthly rent / purchase price`

### 3. Heuristic Rules

These are useful as quick filters, but should be clearly labeled as heuristics rather than canonical underwriting outputs.

- `1% rule`
  Use as a rent-to-price quick screen.
- `50% rule`
  Use as a fallback estimate when expense detail is missing.

Recommended UI treatment:

- show the numeric value
- show a green / yellow / red indicator
- show a short interpretation

### 4. Risk And Sensitivity

A deal is not strong just because the base-case model looks good. It should still work when assumptions move slightly against us.

Minimum stress tests to support:

- rent down `10%`
- vacancy up to `10%`
- unexpected repair shock
- future rate increase or refinance sensitivity later

Recommended scenarios:

- `base`
- `conservative`
- `stress`

### 5. Long-Term Return Layer

This is important, but should follow after the core underwriting engine is stable.

Longer-term metrics to support later:

- appreciation
- loan paydown
- total projected return
- IRR
- equity multiple
- annualized return over hold periods

Important product rule:

- `cash flow` can be modeled directly
- `appreciation`, `rent growth`, and similar forward assumptions must be visibly labeled as assumptions or estimates

## Market Context Layer

Market context is now started, but it should not displace the current listing-analysis prototype priorities.

Current or next market context inputs:

- market rent baseline
- rent growth trends
- appreciation trends
- population growth
- job growth
- median household income
- supply constraints
- liquidity / resale ease

## CMHC Market Data And Source Modes

The app now has a separate market-reference layer in Supabase:

- `market_reference_data`
- `saved_search_market_matches`
- `ai_underwriting_suggestions`

Current behavior:

- CMHC rows can hydrate `market_rent_monthly` and `vacancy_percent`
- user can explicitly switch `Market Rent Monthly` and `Vacancy %` between manual and CMHC
- switching rent to CMHC is a whole-table source change and clears listing-level rent overrides
- imported CMHC BC workbook rows are apartment-oriented, so detached-house searches are labeled as apartment baselines that may run low

Current importer:

- `scripts/import_cmhc_market_data.py`
- validated against the BC workbook `rmr-british-columbia-2025-en.xlsx`

This gives the project:

- an official baseline source for rent and vacancy
- explicit proxy and property-type-mismatch labeling
- a clean foundation for later AI adjustments

## Immediate Next Step

The next session should focus on two narrow follow-ups:

- auditing CMHC secondary-rental tables for usable detached-house and semi-detached BC coverage
- continuing the market-page expansion where official data is already publishable, especially broader BC CMHC rental coverage and CREA-backed appreciation

Concrete next step:

- tighten the current assumption-card UI so active source modes and smart listing-level overrides are obvious at a glance
- keep `Vacancy %` tied to market stats plus manual editing rather than adding an AI path
- improve how the underwriting table surfaces that a row is using smart maintenance or smart CapEx
- keep full reasoning and detailed override context on listing detail rather than bloating the analyzer table
- continue expanding the BC StatCan market-metrics coverage
- keep the CMHC rental importer focused on categories with clean published values now: `apartment`, `townhouse`, and `condo_apartment`
- treat `single_family` detached rent as an explicit data gap until the CMHC secondary-rental audit proves usable published values

Important product rule:

- AI suggestions stay user-triggered
- prompt text is visible and editable
- response is visible before acceptance
- accepted AI values rewrite the relevant source mode rather than hiding behind a background automation step

### Future Market Analyzer Vision

The future `market analyzer` should work like this:

- when the user has scraped a market like `Duncan`, the app automatically creates a market tile
- clicking that tile opens a market page for that region, not a property page
- the page eventually shows local demographic and economic context plus our own scraped inventory summary

This is future work, but the current product direction should leave room for it.

## Data And Assumptions Strategy

### Listing-Level Assumptions

The default direction is:

- assumptions should be auto-filled per listing
- the user should be able to edit every assumption

This is preferred over a purely global model because rent and some expense assumptions depend on the actual listing profile:

- beds
- baths
- property type
- neighborhood
- local rental market

### Source And Confidence Labels

Every important assumption should eventually be tagged with a source type such as:

- `scraped`
- `user entered`
- `rule-based estimate`
- `market-data estimate`
- `AI estimate`

That prevents false precision and makes the analyzer easier to trust.

### AI-Assisted Estimates

Phase 2 should support AI-assisted estimates for thin-data markets.

Recommended rule set:

- use structured or public data first when available
- use AI as a fallback or synthesis layer when local data is sparse or fragmented
- always show source and confidence
- always let the user edit the result

Likely AI-estimated fields later:

- estimated market rent
- appreciation assumption
- rent growth assumption
- insurance or maintenance guidance only if no stronger source exists

Important carve-out:

- `Vacancy %` should stay tied to market stats plus manual editing rather than becoming an AI-estimated field

The product should treat AI as an assistant, not an invisible authority.

## External Inspirations And Product Patterns

Research reviewed during this planning pass suggests a few strong patterns worth adopting.

Durable inspiration notes and screenshot-derived references are tracked in [PRODUCT_INSPIRATION.md](/Users/georgia/Projects/simple realtor.ca scraper python/PRODUCT_INSPIRATION.md:1) so future sessions do not need the same external context re-explained.

### BiggerPockets Patterns Worth Reusing

- clear separation between purchase, financing, revenue, expenses, and returns
- visible `rent estimate` with `confidence`
- comparable rental listings and map context
- quick headline metrics such as `NOI`, `cap rate`, and `cash-on-cash return`
- longer-term projection layer after the base underwriting inputs

### BiggerPockets Workbook Structure Confirmed

The reviewed BiggerPockets calculator workbook includes structured sections for:

- purchase assumptions
- revenue assumptions
- expenses
- mortgage calculations
- investor metrics
- advanced financials
- appreciation and five-year projections
- equity and debt tracking
- IRR with and without sale

We do not need to clone the spreadsheet, but it confirms that the product should separate current underwriting from longer-term projections.

## Current UI Structure For Listing Analysis

The current listing-analysis route is `/saved-searches/<id>/investment-analyzer`.
The URL name is still historical, but the product surface now behaves as a combined Listing Analysis workspace.

The current page structure is:

- `Buy Box`
  structured screening criteria plus AI interpretation goal
- `Assumptions`
  editable underwriting assumptions with source labels and source-mode controls
- `Analysis Results`
  a combined table that appears after the user runs analysis and shows buy-box result, underwriting metrics, underwriting verdict, and final result

Workflow behavior:

- opening `Analyze Listings` shows setup controls first
- changing source modes such as manual, CMHC, AI, rule-based utilities/insurance, or smart reserves saves that setting but does not automatically rewrite the visible analysis table
- pressing `Run analysis` or `Rerun analysis` saves the current buy-box criteria and saved-search defaults together, snapshots the current listing-level overrides, and refreshes the table
- the latest run snapshot is persisted in `saved_searches.search_snapshot.latest_listing_analysis`, including buy-box results by listing ID; the local in-memory state remains only a fallback for the current process

- `Cash Flow`
  monthly rent, monthly expenses, mortgage, monthly cash flow
- `Returns`
  NOI, cap rate, annual cash flow, cash-on-cash return
- `Quick Rules`
  1% rule, 50% rule, rent-to-price ratio
- `Risk`
  base, conservative, and stress-case outputs
- `Assumptions`
  editable assumptions with source labels
- `Confidence`
  explicit source and confidence per important estimate

Current final result buckets:

- `Strong`
  buy box is likely or inactive, and underwriting is promising
- `Review`
  buy box is maybe, underwriting is borderline, the signal is mixed, or a listing is outside the buy box but has promising underwriting
- `Reject`
  buy box is unlikely without promising underwriting, or underwriting is weak

Current UI direction:

- keep the three score columns visible for now, but make them compact
- use header info chips to explain score logic instead of repeating reason text in every row
- reserve detailed reasons, warnings, and source explanations for listing detail or a future expandable row

## Future IRR Projection Metric

IRR is not implemented yet. It should be added as a projection metric after the current underwriting table stabilizes.

IRR should include:

- yearly cash flow
- appreciation
- loan paydown
- projected sale price
- selling costs
- remaining loan balance at exit

Recommended V1 projection assumptions:

- hold period, default 5 years
- appreciation rate percentage
- appreciation source and confidence
- rent growth percentage
- expense growth percentage
- selling cost percentage

Appreciation source priority:

1. exact official market/property-type data such as CREA HPI
2. explicit approved proxy market, labeled low confidence
3. manual user input
4. AI estimate as an explicit fallback or synthesis path only

Suggested IRR display bands:

- below 10%: weak
- 10% to 15%: solid
- 15% to 20%: strong
- 20% or higher: excellent

Product guardrail: IRR should not override survivability. A property with weak current cash flow but attractive projected IRR should usually be `Review`, not `Strong`, and should be framed as an appreciation, hybrid, or value-add thesis.

## Product Decisions Locked In

The following product decisions were made during planning:

- `CapEx` should be separate from `NOI` in v1
- assumptions should be auto-filled per listing and remain editable
- all market-derived assumptions should be editable
- v1 includes only `buy, rent, and hold`
- heuristic metrics can use green / yellow / red indicators
- market analyzer work is future scope, but should be reflected in the roadmap now

## Phase Status

### Phase 1: Scraper And Data Foundation

Status: largely complete

Completed:

- neutral input-driven search flow
- canonical listing + run-history Supabase model
- current active-listings read model
- light lifecycle tracking per saved search
- repeat-run detail reuse
- safe speed pass
- Webshare API proxy selection
- improved pagination stabilization
- optional detail asset blocking
- Realtor.ca security-challenge detection during detail enrichment

Validated:

- headed live Realtor.ca runs
- Supabase persistence
- detail enrichment with `detail_concurrency=2`
- photo extraction
- repeat-run reuse of recently enriched listing details
- `60/60` detail enrichment with `detail_concurrency=12` and asset blocking before security challenges appeared

Remaining follow-up:

- explicitly prove the inactive-listing transition with a controlled rerun in the same saved-search context
- retest scraper stability after cooldown, starting with lower detail concurrency because recent `14`/`16` concurrency tests triggered Realtor.ca security-check pages

### Phase 2: Local Website And Listing Review

Status: active and usable

Completed:

- dashboard
- saved-search detail page
- listing detail page
- local scrape launch
- local sparse-detail retry action
- latest-run indicator
- latest-run result metrics
- listing photo gallery
- preserved buy-box query state when navigating into and back out of a listing
- saved buy-box persistence and listing-detail verdict display
- explicit setup-to-analysis handoff from saved-search review into listing analysis

Still rough:

- local dev-server refresh and restart flow can be confusing when an older Flask process is still running
- run-management UX is basic
- there is no persistent background worker or polished queue
- active-set churn is still hard to interpret when Realtor result counts fluctuate between runs
- listing-analysis run snapshots are persisted inside the saved-search `search_snapshot`; this is durable enough for the current prototype, though a normalized run-history table may still be useful later

### Phase 3: Buy Box And Listing Analysis

Status: active and integrated

Completed:

- structured buy-box inputs
- pass/fail evaluation
- AI interpretation goal for ambiguous listing-description criteria
- `matched`, `maybe`, and `unmatched` buckets
- persisted buy-box settings per saved search
- listing-detail buy-box verdict and reasoning
- persisted buy-box AI results by listing ID in the latest analysis snapshot
- collapsible researched buy-box source trail on listing detail pages
- stricter detached-house filtering in app logic so duplex and townhouse rows are excluded from `house`
- buy-box controls moved into the listing-analysis workspace
- combined `Strong`, `Review`, and `Reject` verdicts based on buy-box plus underwriting
- results table now updates only through an explicit `Run analysis` / `Rerun analysis` action

Next expansion area:

- simplify the combined results table language, especially whether to keep separate visible `Final`, `Buy Box`, and `Underwriting` columns
- add explicit listing workflow states such as shortlist, ignore, and notes

### Phase 4: Investment Analyzer V1

Status: active and partially merged into Listing Analysis

Scope:

- listing-level editable assumptions
- auto-filled rent and expense assumptions where possible
- core buy-and-hold metrics
- green / yellow / red rule indicators
- base / conservative / stress scenarios

Completed or in progress within this phase:

- saved-search underwriting defaults
- source-mode controls that preserve manual versus CMHC choices even when values match
- setup-first analysis flow that prevents source-mode changes from automatically rerunning the table
- listing-level rent overrides
- CMHC-backed vacancy and rent defaults
- AI-assisted listing-level rent application
- BC-wide rule-based utilities and insurance defaults
- listing-level smart maintenance and CapEx heuristics
- underwriting table is now grouped by combined listing-analysis result rather than only buy-box bucket

Still missing in this phase:

- cleaner visual explanation of which rows are using shared defaults versus listing-level smart overrides
- scenario views beyond the current base case
- stronger rule-indicator UX

### Phase 5: Smarter Assumptions And Market Defaults

Status: future

Scope:

- market-data rent estimation
- AI-assisted assumptions where structured data is weak
- source and confidence labels throughout the analyzer

### Phase 6: Market Analyzer

Status: future

Scope:

- auto-created market pages from scraped regions
- rent growth, appreciation, population, job growth, household income, supply, and liquidity context
- market-level inventory summary from our own scraped data

### Phase 7: Long-Term Projections

Status: future

Scope:

- property value versus equity versus loan balance
- cash flow over time
- 5, 10, 20, and 30 year projections
- annualized return, IRR, and equity multiple
- source-aware appreciation assumptions from official data, approved proxy, manual input, or explicit AI estimate

### Phase 8: Workflow Layer

Status: future

Likely scope:

- shortlist
- ignore
- notes
- reviewed status
- better triage after buy-box and underwriting analysis

## Recommended Build Order

The highest-value build order from here is:

1. keep tightening the investment-analyzer UI so score columns, source modes, and smart per-listing overrides are easy to understand
2. keep vacancy sourced from market stats plus manual editing, and make that behavior clearer in the UI
3. improve scrape result stability and first-page logging
4. harden pagination until `results_count` and collected summaries align more reliably
5. add listing workflow states such as shortlist / ignore / notes if needed for review
6. add rule indicators and base / conservative / stress scenarios
7. add IRR as a projection metric once appreciation source controls are clear
8. keep refining smarter defaults only where the source quality is defensible

## Immediate Next Goal

The next concrete goal for the project is:

- keep refining the compact analysis-results UX now that the table shows `Final Score`, `Buy Box Outcome`, and `Underwriting Score`
- decide whether detailed score reasons should live in expandable rows, listing detail, or only header info chips
- keep making the underwriting UX clearer now that multiple assumption source modes and listing-level overrides exist
- keep stabilizing listing ingestion enough that underwriting can trust the active result set

The next coding session should therefore start by answering:

1. should the table add expandable row details for score reasons, warnings, and source confidence
2. how should the analyzer page communicate smart listing overrides without forcing constant navigation into listing detail
3. how should the UI communicate that vacancy is stats-backed when available and otherwise manually entered
4. what exact source controls are needed before adding IRR projection assumptions
5. do we need one more scraper reliability pass before relying more heavily on the active set
6. what is the new stable detail concurrency after the Realtor.ca security-check event: retest `4`, `6`, `8`, then only retest `12` if lower settings are clean

## Current Risks And Constraints

- headed Playwright runs can still be flaky on the local machine, especially when Chrome for Testing crashes or an old Flask server keeps serving stale code
- AI-assisted buy-box results are only as good as the prompt and listing description quality
- Realtor.ca can still show transient or stale result counts before the page fully settles
- Realtor.ca can serve an additional security-check page during detail enrichment; this was observed after aggressive detail-concurrency tests. The scraper now detects the challenge and stops queued detail work, but the next session should treat this as an active reliability issue.
- Webshare API proxy selection works and randomly picks one valid proxy per run, but proxy rotation alone did not prevent challenges after aggressive concurrency tests.

See [docs/scraper_status.md](/Users/georgia/Projects/simple realtor.ca scraper python/docs/scraper_status.md:1) for the current scraper/proxy benchmark handoff.
- pagination controls on Realtor.ca are inconsistent enough that continued defensive handling is warranted
- market data for smaller Canadian regions may be sparse, which is why selective AI assistance still makes sense for some assumptions such as rent, but not every field should become AI-driven
- BC-wide utilities and insurance rule-based defaults are intentionally coarse and are not market-specific
- smart maintenance and CapEx heuristics are useful triage aids, but they are not substitutes for a real condition review or reserve study

## Settled Product Decisions

These are the current decisions a new agent should treat as active unless explicitly changed:

- the project remains local-first and single-user
- the listing analyzer is the active product area; the market analyzer is future work
- buy-box AI is allowed for fuzzy qualitative interpretation of listing descriptions
- AI rent suggestions are allowed as a user-triggered aid, and they should prioritize current direct comparable rent evidence before using CMHC or other official rows as fallback context
- AI appreciation fallback should prioritize target-market research before leaning on HPI proxy rows
- `Vacancy %` should come from market stats when available and remain manually editable rather than becoming an AI-driven field
- `CapEx` stays separate from `NOI` in v1

Next-session AI and performance handoffs:

- [docs/AI_CHATBOT_ROADMAP.md](/Users/georgia/Projects/simple realtor.ca scraper python/docs/AI_CHATBOT_ROADMAP.md:1) documents the staged listing-detail, market-context, and analyzer chatbot plan.
- [docs/PERFORMANCE_NOTES.md](/Users/georgia/Projects/simple realtor.ca scraper python/docs/PERFORMANCE_NOTES.md:1) documents the current page-load and AI latency bottlenecks.

These are known issues, but the project is already usable enough to keep building on.
