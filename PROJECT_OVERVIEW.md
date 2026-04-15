# Project Brief

## Premise

This repository is an early proof-of-concept for a `realtor.ca` scraper built in Python with Playwright. Its current purpose is to answer a narrow technical question: can listing data be collected reliably from Realtor.ca search results and detail pages using a browser-driven approach that looks closer to normal user behavior than a bare scripted session.

At this stage, the codebase is intentionally limited. It is not yet a full scraper platform, a reusable search engine, or an investment decision system. It is a working validation layer for data acquisition.

## Current Scope

The current scraper is designed to:

- Open a visible Chromium browser session rather than running fully headless.
- Apply `playwright-stealth` to reduce obvious browser automation signals.
- Visit a fixed Realtor.ca search URL.
- Move through a limited number of search result pages.
- Extract a small set of listing summary fields from result cards.
- Open listing detail pages and extract additional attributes.
- Save structured JSON output for successful runs.
- Save screenshots and HTML snapshots when failures occur, so selector and anti-bot issues can be debugged quickly.

This makes the current repository a proof of concept for collection reliability, not yet a generalized end-user product.

## Technical Approach

The scraper was intentionally built with Playwright plus stealth and human-like interaction patterns. The goal is not to perfectly mimic a human user, but to avoid the most obvious characteristics of a naive automation script.

The current implementation includes:

- A visible Chromium browser launched with automation-related blink features disabled.
- A browser context configured with a realistic desktop viewport, `en-CA` locale, `America/Vancouver` timezone, and a standard Chrome-style user agent.
- `playwright-stealth` applied to the browser context.
- Light mouse movement across several points in the viewport before or after page interaction.
- Small randomized pauses between actions.
- Randomized scroll distances.
- Occasional longer pauses while iterating listings, to reduce perfectly uniform timing.
- Popup dismissal logic for common consent or close buttons.

The current timing behavior includes:

- General pauses of roughly `0.6` to `1.6` seconds for baseline interaction pacing.
- Mouse movement pauses of roughly `0.15` to `0.45` seconds between movement points.
- Post-navigation or post-scroll pauses commonly around `1.0` to `3.2` seconds depending on context.
- Listing-to-listing pauses usually around `0.9` to `2.0` seconds, with occasional longer waits of roughly `2.5` to `4.5` seconds.
- Playwright `slow_mo=140` to add a consistent delay to browser actions.

These values are part of the proof-of-concept strategy and should be treated as tunable scraping behavior, not fixed product requirements.

## Intended Direction

The broader project is meant to grow from a scraper proof of concept into the data-ingestion layer for a real-estate investment workflow.

The planned direction is to support user-defined search inputs similar to the filters available on Realtor.ca, including examples such as:

- Minimum price
- Maximum price
- Property type, such as apartment versus house
- Location or map bounds
- Other relevant listing filters exposed by the source site

Over time, the scraper should evolve to:

- Accept structured search and filtering inputs instead of relying on a single hard-coded URL.
- Collect a richer and more consistent set of fields needed for downstream analysis.
- Normalize listing data into a format suitable for evaluation.
- Feed scraped listings into an analyzer that compares them against investment goals and buy-box criteria.
- Surface listings that are potentially worth closer review.

## Product Vision

The long-term goal is not just to scrape listings, but to help evaluate them against a personalized investment thesis.

In practical terms, that means the workflow is expected to become:

1. A user defines search constraints and buy-box parameters.
2. The scraper collects candidate listings from Realtor.ca.
3. An analysis layer evaluates those listings against the user's goals.
4. The system identifies which listings appear promising enough for manual review.

## Status

Right now, this repository should be understood as a foundation project. The current code proves out scraping mechanics and basic field extraction. User-configurable search filters, broader data coverage, and investment analysis are planned next-stage capabilities rather than completed features.

## Next Steps

### Phase 2: Broader Collection

After the input-driven search flow is validated, the next step is to expand from a small proof-of-concept sample to broader collection of matching listings.

The goals for this phase are to:

- Collect all or nearly all listings that match the provided search inputs.
- Improve pagination handling so the scraper can move through result pages more efficiently.
- Separate result-card collection from slower detail-page enrichment, so the scraper can gather candidate listings first and enrich them second.
- Improve deduplication and run controls so larger scrapes remain stable.
- Preserve a browser-first approach with conservative behavior to avoid unnecessary blocking risk.

### Phase 3: Rich Detail Extraction

Once broader collection is stable, the next step is to deepen the data extracted from each individual listing page.

The goals for this phase are to:

- Capture listing description text.
- Capture structured property summary fields such as property type, building type, square footage, land size, built year, taxes, and time on REALTOR.ca.
- Capture deeper building and land details such as heating, cooling, parking, architectural style, zoning, access, features, and other structured sections visible on the listing page.
- Normalize those detail fields into a consistent JSON shape suitable for later storage and analysis.
- Prepare the data structure so it can later be moved from JSON files into Supabase tables for persistence and downstream application use.
