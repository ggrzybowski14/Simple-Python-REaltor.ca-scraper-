# Project Overview

## Premise

This repository started as a proof of concept for a visible Realtor.ca scraper built with Python and Playwright. It has now progressed into the early foundation of a local real-estate analyzer application for a single primary user.

The project is no longer just "can we scrape Realtor.ca?" The current question is: can this scraper, data model, and local website support a repeatable workflow for collecting active listings, reviewing them, and filtering them against a buy box?

## Current State

The codebase now has three working layers:

- a headed Realtor.ca scraper with conservative anti-bot behavior
- a Supabase-backed ingestion and lifecycle model
- a local Flask website for browsing saved searches, listings, and buy-box results

This is still an early application, not a polished product, but it is now beyond pure scraping validation.

## What Works Today

### Scraper

- Starts from a neutral Realtor.ca map page rather than a Victoria-specific hard-coded URL
- Accepts structured inputs for location, min price, max price, minimum beds, and property type
- Applies those filters through the visible Realtor.ca UI
- Collects listing summaries across result pages
- Enriches listing detail pages with full description, property facts, and photos
- Saves local JSON output and failure artifacts
- Writes successful runs into Supabase

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
- latest-run indicator on the saved search updated most recently
- background launch of headed scrape jobs
- saved-search detail page with all active scraped listings
- saved-search hero metrics for active listings, site results count, and collected count
- listing detail page with richer fields and photo gallery
- collapsible recent-run history
- persisted buy-box settings per saved search
- targeted retry of sparse listing details

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

## Current Product Direction

The intended workflow is now:

1. create or reuse a saved search for a market
2. scrape all active listings for that search
3. store current state plus scrape history
4. review listings in the local website
5. run the buy box against the active listings
6. inspect matched, maybe, and unmatched candidates

The product is still single-user and local-first for now.

## Scope Clarifications

### Saved Search Versus Buy Box

These remain separate concepts.

- A `saved search` defines what Realtor.ca inventory to collect.
- A `buy box` defines how to evaluate the collected listings.

That distinction is now implemented in the product direction, even though buy-box persistence is still light.

### Market Analyzer

Broader market analysis remains future scope only.

Examples of explicitly future-only work:

- rental market analysis
- appreciation analysis
- economy and demographic indicators
- broader market fundamentals scoring

This should stay out of active implementation for now.

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

Validated:

- headed live Realtor.ca runs
- Supabase persistence
- detail enrichment with `detail_concurrency=2`
- photo extraction
- repeat-run reuse of recently enriched listing details

Remaining small follow-up:

- explicitly prove the inactive-listing transition with a controlled rerun in the same saved-search context

This is no longer a blocker for application work.

### Phase 2: Local Website

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

Still rough:

- local dev-server refresh/restart flow can be confusing when an older Flask process is still running
- run-management UX is basic
- there is no persistent background worker or polished queue
- active-set churn is still hard to interpret when Realtor result counts fluctuate between runs

Phase 2 should now focus only on improvements that materially help the listing-review workflow.

### Phase 3: Listing Analysis

Status: started

Completed:

- structured buy-box inputs
- pass/fail evaluation
- AI interpretation goal for ambiguous listing-description criteria
- `matched`, `maybe`, and `unmatched` buckets
- persisted buy-box settings per saved search
- listing-detail buy-box verdict and reasoning
- stricter detached-house filtering in app logic so duplex/townhouse rows are excluded from `house`

Immediate next opportunities:

- keep improving result-set stability before more workflow features are layered on top
- add excluded keywords
- add simple review workflow states such as shortlist / ignore / notes
- add clearer run comparison for listings that are new to the current collected set versus genuinely new on market

### Phase 4: Workflow Layer

Status: not started

Likely scope:

- shortlist
- ignore
- notes
- reviewed status
- better triage workflow after buy-box analysis

## Technical Direction From Here

The next work should favor real screening utility over more scaffolding.

Highest-value likely next steps:

1. improve settled count stability and log the first-page result set more explicitly
2. continue hardening pagination and page-state detection so collected results consistently match site results
3. add shortlist / ignore / notes
4. optionally refine the AI prompt and caching behavior based on real listing review

Lower-priority work for now:

- deeper run UX
- polished dashboard metrics
- broader market-analysis features

## Current Risks And Constraints

- Headed Playwright runs can still be flaky on the local machine, especially when Chrome for Testing crashes or an old Flask server keeps serving stale code
- AI-assisted buy-box results are only as good as the prompt and listing description quality
- Realtor.ca can still show transient or stale result counts before the page fully settles
- Pagination controls on Realtor.ca are inconsistent enough that continued defensive handling is warranted

These are known issues, but the current system is already usable enough to keep building on.
