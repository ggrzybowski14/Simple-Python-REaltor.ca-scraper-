# Project Brief

## Premise

This repository began as a proof-of-concept for a `realtor.ca` scraper built in Python with Playwright. Its original purpose was narrow: validate that a visible browser, stealth measures, and light human-like interaction could reliably collect listing data from Realtor.ca search results and detail pages.

That proof of concept is now working well enough to treat the repository as the early foundation of a larger real-estate analysis application. The project is still not a finished product, but it has moved beyond pure scraping validation. The next step is to turn the scraper foundation into a reliable, structured ingestion system that can support a user-facing application.

## Current State

The current codebase has a single integrated scraper flow in place.

What works today:

- Opens a visible Chromium browser rather than running fully headless.
- Applies `playwright-stealth`.
- Accepts runtime inputs for location, price bounds, minimum beds, and property type.
- Applies those filters in the visible Realtor.ca UI.
- Collects listing summaries across multiple result pages.
- Enriches a configurable subset of listings with detail-page fields.
- Saves structured JSON output locally.
- Can upsert scraped listings into Supabase when local credentials are configured.
- Saves screenshots and HTML artifacts on failure for debugging.

This should still be understood as a browser-first ingestion foundation, not yet a proper end-user application.

## Current Technical Approach

The scraper intentionally uses Playwright plus stealth and human-like interaction patterns. The goal is not to perfectly mimic human behavior, but to avoid the most obvious characteristics of a naive automation script.

The current implementation includes:

- A visible Chromium browser launched with automation-related blink features disabled.
- A browser context configured with a realistic desktop viewport, `en-CA` locale, `America/Vancouver` timezone, and a Chrome-style user agent.
- `playwright-stealth` applied to the browser context.
- Light mouse movement before and after interactions.
- Randomized pauses between actions.
- Randomized scroll distances.
- Occasional longer pauses while iterating listings.
- Popup dismissal logic for common consent or close buttons.

These interaction values are part of the scraping strategy and should be treated as tunable implementation details, not product requirements.

## Product Direction

The broader product is meant to become a real-estate analyzer application for a single primary user at first. The near-term focus is not a public platform and not a multi-user SaaS product. The goal is to support one person's workflow for identifying and reviewing promising listings within selected Canadian markets.

The intended workflow is:

1. The user defines a saved search for a market of interest.
2. The scraper collects all active listings that match that saved search.
3. The system stores both the latest known listing state and scrape history.
4. The application shows the current active listings for that saved search.
5. A later analysis layer evaluates listings against buy-box criteria and highlights which ones deserve manual review.

## Scope Clarifications

### Saved Search Versus Buy Box

These concepts overlap, but they are not the same thing.

- A `saved search` defines what the scraper should collect from Realtor.ca.
- A `buy box` defines how the application should evaluate the listings that were collected.

Examples:

- A saved search might be: Duncan, house, 2+ beds, max price 1,000,000.
- A buy box might later be: under 750,000, house, suite potential, and specific keywords in the listing description.

The system should scrape candidate listings first, then evaluate them through buy-box logic later. Buy-box design is important, but it is not the current implementation focus.

### Market Context

For now, the app is not a full market analyzer. It is primarily a listing-ingestion and listing-analysis tool scoped to one market or saved search at a time.

A separate future product area may analyze broader market fundamentals such as:

- rental rates
- appreciation trends
- economic indicators
- population growth

That future market-analyzer concept should remain explicitly out of active implementation scope for now.

### Active Listings and History

The product should show active listings, not stale listings that disappeared weeks ago.

That means the system needs two things at once:

- a current view of active listings for each saved search
- historical scrape records so the system knows when a listing was first seen, last seen, or no longer active

The UI should normally show deduplicated current listings. It may later also show helpful indicators such as:

- new in the last scrape
- new in the last 24 hours
- no longer active

## Current Limitations To Fix Before UI Work

Two important issues should be addressed before building the first local website.

### 1. Search Initialization Is Still Too Anchored To A Victoria-Specific Starting State

The current scraper still begins from a Victoria-specific Realtor.ca map URL. Even though later filters can be changed by user input, the startup state is still tied too closely to one market.

The next version should:

- start from a neutral Realtor.ca entry point
- establish search state from structured user input rather than a market-specific hard-coded URL
- apply location first, then the rest of the search filters
- validate that the rendered search state matches the requested input

### 2. The Current Supabase Model Blends Latest Listing State With Scrape History

The current single-table approach is acceptable for the proof of concept, but it is not sufficient for the application phase because repeated listings overwrite prior run context.

The next version should separate:

- canonical listing identity
- scrape run history
- run-to-listing relationships
- saved-search definitions

That will allow the system to keep one canonical record per listing while also preserving which listings were seen in each scrape.

## Data Model Direction

The intended direction is to move toward a more explicit relational structure.

Expected core entities:

- `saved_searches`
  One row per reusable search definition. This is the primary unit the user will manage in the app.
- `scrape_runs`
  One row per scrape execution for a saved search.
- `listings`
  One canonical row per unique listing.
- `scrape_run_listings`
  One row per listing seen in a given scrape run.

This structure should support:

- no duplicate canonical listing rows
- a clean current active-listings view
- detection of newly seen listings
- detection of disappeared or inactive listings
- comparison between one scrape run and another

The product requirement is not to duplicate listings in the normal application view. The purpose of the additional tables is to preserve history without showing duplicates in the UI.

## Phase 1 Implementation Blueprint

This section defines the concrete design target for the next implementation phase.

### Proposed Phase 1 Tables

#### `saved_searches`

Purpose:

- store the reusable search definitions the user wants to run repeatedly

Suggested fields:

- `id`
- `name`
- `location`
- `min_price`
- `max_price`
- `beds_min`
- `property_type`
- `is_active`
- `created_at`
- `updated_at`
- optional later fields such as `baths_min`, `keywords_include`, or other Realtor.ca filters

Notes:

- for now, this is the main user-managed concept in the system
- this should represent the scraping scope, not the buy-box logic

#### `scrape_runs`

Purpose:

- store one row per scrape execution for a saved search

Suggested fields:

- `id`
- `saved_search_id`
- `status`
- `started_at`
- `finished_at`
- `summary_count`
- `detail_attempted`
- `detail_succeeded`
- `failed_detail_urls`
- `error_message`
- `search_snapshot`
- `run_settings`
- `created_at`

Status examples:

- `queued`
- `running`
- `succeeded`
- `failed`

Notes:

- `search_snapshot` should preserve the exact search parameters used for that run
- `run_settings` can preserve internal debug controls if they still exist

#### `listings`

Purpose:

- store one canonical row per unique listing

Suggested fields:

- `id`
- `source`
- `source_listing_key`
- `url`
- `address`
- `price`
- `bedrooms`
- `bathrooms`
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
- `raw_listing`
- `first_seen_at`
- `last_seen_at`
- `last_scraped_at`
- `is_active`
- `created_at`
- `updated_at`

Notes:

- `source_listing_key` should use a stable Realtor identifier if one can be extracted; otherwise use URL initially
- `is_active` should reflect whether the listing is still present in the latest relevant scrape context
- `first_seen_at` and `last_seen_at` support listing lifecycle tracking

#### `scrape_run_listings`

Purpose:

- link a scrape run to every listing seen in that run

Suggested fields:

- `id`
- `scrape_run_id`
- `listing_id`
- `saved_search_id`
- `results_page`
- `is_new_in_run`
- `raw_listing_snapshot`
- `created_at`

Notes:

- this table preserves run history without duplicating canonical listing records
- `is_new_in_run` can support UI labels such as "new in last scrape"

### Expected Behavior Of The New Model

When the same listing is seen repeatedly:

- `listings` keeps one canonical row
- `scrape_runs` records each execution
- `scrape_run_listings` records that the listing appeared in each run
- `listings.last_seen_at` is updated
- `listings.is_active` remains true if it is still being seen in current runs

When a listing disappears from the latest scrape for a saved search:

- the listing should stop appearing in the default current active-listings view for that saved search
- history should still remain queryable through prior runs
- the canonical listing record should not be deleted

That preserves history while keeping the UI focused on currently active inventory.

### Proposed Phase 1 Scraper Request Shape

The scraper should be driven by a structured request object rather than a fixed market-specific URL.

Proposed core request fields:

- `location`
- `min_price`
- `max_price`
- `beds_min`
- `property_type`

Internal or temporary development controls may still exist separately, such as:

- `detail_limit`
- `detail_concurrency`
- `max_pages`

These controls should be treated as debugging or safety settings, not long-term user-facing product inputs.

### Proposed Phase 1 Scraper Flow

1. Load a neutral Realtor.ca starting page rather than a Victoria-specific map state.
2. Apply location from the structured search request.
3. Apply price, beds, property type, and other supported filters from the same request.
4. Validate the rendered location and search state after filters are applied.
5. Collect all matching listings for a normal run.
6. Enrich listing details where appropriate.
7. Persist:
   - the scrape run
   - canonical listings
   - run-to-listing history
8. Update active/inactive state based on the latest run results for the saved search.

### Proposed Refactor Direction In Code

The current integrated script should be broken into clearer responsibilities before UI work.

Suggested logical modules:

- `search request parsing`
- `browser/session setup`
- `search-state application`
- `results collection`
- `detail enrichment`
- `persistence layer`
- `run orchestration`

The goal is not abstraction for its own sake. The goal is to make the scraper callable later from:

- CLI validation
- a local web app
- scheduled local runs

### Out Of Scope For Phase 1

The following should not expand the Phase 1 surface area:

- buy-box scoring logic
- AI-assisted buy-box definition
- public deployment
- multi-user auth
- broader market fundamentals analysis

## Phase 1 Progress

Phase 1 is now mostly implemented and partially validated in live headed runs.

What has been completed:

- neutral Realtor.ca startup using a broad default map state rather than a Victoria-specific hard-coded map URL
- visible browser search flow that successfully applies location, price, beds, and property type from structured inputs
- Supabase persistence into:
  - `saved_searches`
  - `scrape_runs`
  - `listings`
  - `scrape_run_listings`
- active-listing read model via `current_active_saved_search_listings`
- light lifecycle support via:
  - `saved_search_listings`
  - `is_new_in_run` on `scrape_run_listings`

What has been validated:

- a live headed Victoria run with `house`, `2+ beds`, and `max price 1000000`
- successful summary collection, detail enrichment, local JSON output, and Supabase writes
- correct creation of saved search, scrape run, canonical listing, and run-history rows
- correct population of the current active-listings view

What remains to be proven:

- the explicit inactive transition when a listing disappears from a later run for the same saved-search context

That inactive-path proof is considered a small follow-up, not a blocker to starting the first local website, because the active-listings view and saved-search persistence model are already working.

## Phase Plan

### Completed Foundation Work

The following foundation work is already in place:

- input-driven browser search controls
- broader summary collection across pages
- conservative detail enrichment
- richer listing detail extraction
- local JSON output
- initial Supabase integration

### Phase 1: Scraper And Data Foundation

This phase is largely complete.

Goals:

- remove market-specific startup assumptions
- make search truly input-driven from a structured request object
- redesign the Supabase schema around saved searches, scrape runs, listings, and run history
- keep the CLI available for validation and debugging
- preserve failure artifacts and logging

Phase 1 implementation direction:

- Replace the fixed Victoria-oriented start state with a neutral Realtor.ca starting page.
- Treat the search request as structured input driven by the user or a saved search.
- Collect all matching listings for real runs rather than relying on `max-listings` and `max-pages` as product behavior.
- Keep `max-pages` and `max-listings` only as internal debugging safeguards if they remain at all.
- Store both the latest known state of a listing and its scrape history.
- Ensure the system can determine whether a listing is still active in the latest run for a saved search.

Current status:

- completed for neutral startup, input-driven search, persistence redesign, and active-listings read model
- partially validated for lifecycle handling
- one remaining follow-up is to explicitly prove the inactive transition with a controlled rerun

### Phase 2: Local Website

Phase 2 has now started with an initial local website scaffold.

Goals:

- create and manage saved searches from a local web UI
- trigger scrape jobs from the UI
- show scrape run history and status
- display current active listings for a saved search
- flag listings that are newly seen since the last scrape

Expected shape of the first UI:

- saved searches
- scrape runs
- current listings
- listing detail view

The first website should be a thin orchestration and read layer on top of the scraper and Supabase foundation, not a rewrite of scraper logic.

Current scaffold status:

- local Python website entrypoint added
- dashboard added for saved searches and recent runs
- saved-search detail page added for current active listings
- local background scrape launch wired to the existing `scraper.py`

Immediate next website work:

- improve scrape job status and refresh behavior
- refine saved-search detail presentation
- decide whether the next increment should prioritize saved-search management or listing-detail views

### Phase 3: Listing Analysis Layer

After the local website is working, add the first analysis features.

Goals:

- define initial buy-box inputs
- score or filter listings against those inputs
- identify which listings deserve manual review first

Possible future approaches:

- simple structured buy-box inputs
- later AI-assisted help to define or refine buy-box criteria

The first implementation should stay simple and structured.

### Phase 4: Workflow Refinement

After analysis is in place, improve the review workflow.

Potential features:

- shortlist or reviewed status
- notes on listings
- candidate versus rejected classification
- better change tracking between runs
- better explanation of why a listing matches or misses the buy box

### Future State Beyond Current Scope

A separate future product area may later expand into broader market analysis.

Examples:

- rental market analysis
- appreciation and trend analysis
- macro and local economic indicators
- population-growth context

This future work should be acknowledged in project documentation, but should not become active implementation work yet.
