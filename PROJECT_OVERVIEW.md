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

This repository now has two validated stages in place:

- Phase 1 is complete: the scraper accepts user-provided runtime inputs for location, minimum beds, property type, and price bounds instead of relying on a single hard-coded search URL.
- Phase 2 is complete: the scraper can broaden collection across multiple results pages, collect larger sets of listing summaries, and enrich a controlled subset of those listings with detail-page data using conservative low-risk concurrency.

The current codebase should still be understood as a browser-first foundation project rather than a finished end-user product. The next major step is richer listing-detail extraction and downstream data modeling for later storage and analysis.

## Next Steps

### Phase 2: Broader Collection

Phase 2 is complete.

What was validated in this phase:

- The scraper can collect broader result sets across multiple results pages instead of stopping at a tiny proof-of-concept sample.
- The scraper can use runtime controls for `max-pages`, `max-listings`, `detail-limit`, and `detail-concurrency`.
- The scraper can separate summary collection from detail enrichment.
- The scraper can enrich detail pages with conservative concurrency, starting at `detail-concurrency=2`.
- The browser-first approach with visible Chromium and `playwright-stealth` remained stable during broader collection tests.

Known note from phase 2:
Location-based searches may still need better calibration of the resulting map state, including zoom level and geographic bounds. Different zoom and bounds combinations on Realtor.ca can produce different visible result totals even when the location name and filters are otherwise the same. This should be revisited later as a search-state tuning task, but it is not a blocker for moving into richer detail extraction.

### Phase 3: Rich Detail Extraction

Phase 3 is the next active scope.

The goals for this phase are to:

- Capture listing description text from the listing page.
- Capture richer structured property summary fields such as property type, building type, square footage, land size, built year, taxes, and time on REALTOR.ca.
- Capture deeper building and land details such as heating, cooling, parking, architectural style, zoning, access, features, and other visible structured sections.
- Preserve the current summary-plus-detail output flow while expanding the detail schema.
- Normalize those fields into a cleaner JSON structure suitable for later loading into Supabase.

Recommended implementation direction for phase 3:

- Keep the current browser-first search and pagination flow unchanged.
- Expand detail extraction only after a listing has already been selected for enrichment.
- Add detail fields incrementally and verify them section by section against the live listing page.
- Prefer explicit field names in the output schema over storing large unstructured text blobs only.
- Keep failure artifacts and logging strong, because detail-page extraction is where selector drift is most likely to happen.
