# Performance Notes

## Current Slow Spots

The app has two different kinds of slowness:

- Normal page navigation can be slow because routes rebuild page context from multiple Supabase reads.
- AI actions are slow because they make live OpenAI calls, and the newer research features use web search.

## Market Context Page

Routes:

- `/saved-searches/<saved_search_id>/market-context`
- `/markets/<market_key>`

Main work on each load:

- fetch saved search or all saved searches
- fetch/bootstrap market profile
- fetch market metrics
- build rental housing summary
- build appreciation context
- fetch all market reference rows via `fetch_market_reference_rows`
- fetch latest persisted AI rental/appreciation estimates

Likely improvements:

- Cache `fetch_market_reference_rows` in-process with a short TTL.
- Add a market-key-filtered reference-row fetch instead of reading up to 2000 rows on every page.
- Cache market metrics/appreciation snapshots per market key.
- Avoid bootstrapping market context during ordinary page loads unless explicitly requested.

## Underwriting / Investment Analyzer Page

Route:

- `/saved-searches/<saved_search_id>/investment-analyzer`

Main work on each load:

- fetch active listings
- merge listing media
- fetch investment defaults
- fetch all market reference rows
- fetch listing overrides/favorites
- rebuild underwriting rows when analysis has run
- rebuild buy-box result lookup

Important issue:

- `build_buy_box_result_lookup` calls `analyze_active_listings`.
- If the saved buy box has enabled AI screens and `AI_BUY_BOX_CACHE` is cold, this can call OpenAI while simply loading the underwriting page.
- The cache is in-process only, so it is lost after a server restart.

Recommended fix:

- Persist buy-box AI screen results in the saved analysis state when the user runs analysis.
- On normal page navigation, render the persisted buy-box results instead of re-running `analyze_active_listings`.
- Only re-run buy-box AI when the user explicitly clicks `Run analysis` or changes the buy-box prompts.

## AI Actions

Current research-backed AI calls:

- `call_openai_rent_suggestions`
- `call_openai_market_rental_gap_estimate`
- `call_openai_market_appreciation_gap_estimate`

These use OpenAI Responses API with `web_search`, so latency is expected to be noticeably higher than local page rendering.

Recommended UX improvements:

- Run AI actions as background jobs, similar to scraper jobs.
- Return immediately to the page with a status panel.
- Poll for completion and show the result when ready.
- Cache researched source context by market/property/bedroom/topic so repeat estimates do not re-search every time.

## First Performance Fixes To Build

1. Add route timing logs for Supabase calls, OpenAI calls, and render time.
2. Persist buy-box AI analysis results and stop re-running AI on ordinary underwriting page loads.
3. Add a TTL cache for market reference rows and market metrics.
4. Convert market rental/appreciation AI actions to background jobs.
5. Lazy-load listing images/media where possible on analyzer/detail pages.
