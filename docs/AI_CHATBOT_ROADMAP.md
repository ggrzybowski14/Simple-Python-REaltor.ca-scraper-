# AI Chatbot and Research Roadmap

## Current AI Integration Status

The app has several AI features. The market/rent estimate features now use OpenAI's Responses API with the built-in `web_search` tool enabled. The app does not use `file_search` yet.

Current AI implementation details:

- Buy-box AI screens in `app.py`
  - Function: `call_openai_buy_box_assessment`
  - Input: listing ID, address, and listing description.
  - Output: `likely` / `maybe` / `no` plus a short reason.
  - Description-only prompts still use `https://api.openai.com/v1/chat/completions`.
  - Prompts that need market/regulatory/neighborhood context now use one batch `web_search`-enabled Responses API call for the saved-search/listing batch, then apply that shared researched context across listings.
  - Buy-box AI intentionally does not do parcel-specific deep research per listing; exact zoning, school catchment, floodplain, safety nuance, and other address-specific due diligence belong in listing-detail chat.
  - Results from `Run analysis` are persisted in `saved_searches.search_snapshot.latest_listing_analysis.buy_box_results_by_listing_id`.
  - Listing detail pages now read those saved buy-box results and show researched summaries/source URLs behind a collapsible `Research trail`.

- Listing rent suggestions in `ai_underwriting.py`
  - Function: `call_openai_rent_suggestions`
  - Input: saved-search context, official/market baseline when available, listing details.
  - Output: market research summary, direct comp count, fallback comp count, fallback strategy, source names/URLs, suggested rent, confidence, reasoning, baseline used, and optional `rent_components`.
  - Uses one `web_search`-enabled Responses API call for the whole saved search/listing batch, not one web search per listing.
  - Important: the prompt now prioritizes current whole-property comparable rents for the saved-search segment. Official baselines such as CMHC are optional context/fallback, not the primary answer when direct comparable rents are available.
  - If listing facts clearly indicate multiple rentable units, such as a main house plus detached cottage, basement suite, carriage suite, garden suite, or other rentable unit, the accepted suggestion can include component rents that approximately add to the total.
  - The prompt explicitly should not treat ensuite bathrooms, guest rooms, dens, or generic bedroom/bathroom counts as rentable suite components unless the listing describes a separate rentable unit or occupancy setup.
  - `Run AI` only creates an in-process preview. `Apply AI values` persists accepted values/reasoning to Supabase and refreshes the saved listing-analysis snapshot.

- Market rental gap estimates in `ai_underwriting.py`
  - Function: `call_openai_market_rental_gap_estimate`
  - Input: market profile plus internal CMHC/reference rows.
  - Output: estimated rent/vacancy, confidence, market research summary, direct comp count, fallback comp count, fallback strategy, reasoning, source names/URLs.
  - Uses `web_search`-enabled Responses API.
  - Important: the prompt now searches direct comparable rents first and should only use CMHC apartment/townhouse data as floor/context for detached-house estimates if stronger evidence is not found.

- Market appreciation gap estimates in `ai_underwriting.py`
  - Function: `call_openai_market_appreciation_gap_estimate`
  - Input: market profile, HPI snapshots/proxy data, structured market metrics.
  - Output: estimated benchmark price and trend metrics, confidence, reasoning, source names/URLs.
  - Uses `web_search`-enabled Responses API.
  - Important: the prompt now prioritizes current target-market research first. HPI/proxy/structured metrics are optional context and fallback evidence, not the answer when better target-market evidence is available.

Shared web-search helper:

- Function: `call_openai_researched_json` in `ai_underwriting.py`
- Endpoint: `https://api.openai.com/v1/responses`
- Model env var: `OPENAI_RESEARCH_MODEL`; falls back to `OPENAI_UNDERWRITING_MODEL`.
- Tool: `{"type": "web_search"}`
- Response mode: strict JSON schema.

## Target Architecture

Build one shared AI research/chat service with different context builders for each page:

- Listing detail chat
- Market context chat
- Listing analyzer chat

The chat service should use:

- Internal app context: listing details, underwriting, saved-search setup, market metrics, rent/vacancy/HPI data, buy-box results, favorites.
- External retrieval: OpenAI Responses API with `web_search` enabled for current market/regulatory questions.
- Later optional internal document retrieval: OpenAI `file_search` or local vector search for stored bylaws, zoning PDFs, market reports, and cached source documents.

OpenAI docs:

- Web search: `https://platform.openai.com/docs/guides/tools-web-search`
- File search: `https://platform.openai.com/docs/guides/tools-file-search`

## Important Prompt Principle

The bot should not be told to avoid research. It should be told:

> Use provided listing, underwriting, and app data as the source of truth for facts already known inside the app. For market, zoning, subdivision, carriage-home, rent trend, regulatory, and local-quality questions, perform web research and cite sources. If source material conflicts or legal/planning interpretation is uncertain, say what needs municipal, zoning-map, survey, planner, lawyer, or realtor verification.

Reason:

- Listing facts should come from our scraped/internal data so the model does not invent bedrooms, lot size, price, zoning, or underwriting numbers.
- Regulatory and market facts change and should be researched from current/public sources.
- Internal official datasets such as CMHC and CREA are useful context, but for AI research features they should not be over-weighted when they do not directly match the requested segment. For example, do not let CMHC apartment/townhouse data drive a 5+ bedroom detached-house rent estimate unless there are no better whole-house comps, and label that fallback clearly.

For rental/appreciation research responses, prefer a visible research trail:

- direct comparable evidence found
- fallback evidence used
- why the fallback is acceptable or weak
- source URLs/citations
- confidence and verification steps

For listing rent responses, keep `suggested_rent_monthly` as the total full-listing rent. Use `rent_components` only when there is credible listing evidence for multiple rentable units; otherwise return an empty component list.

## V1: Listing Detail AI Chat

First build this on `templates/listing_detail.html`.

### User Experience

- Add a compact chat panel on the listing detail page.
- Include suggested question chips:
  - Is this listing likely subdividable?
  - Could this property support a carriage home?
  - What zoning or land-size issues should I verify?
  - What rent would this need to cash flow?
  - What risks do you see in the listing description?
- Chips should send/fill normal user messages. They are examples, not hard-coded answers.
- Chat response should display clickable citations when the model uses web search.
- Response should clearly label:
  - app-provided facts
  - researched facts
  - assumptions/uncertainties
  - recommended verification steps

### Backend Shape

Add a route similar to:

`POST /saved-searches/<saved_search_id>/listings/<listing_id>/ai-chat`

Suggested implementation pieces:

- `build_listing_detail_chat_context(config, saved_search, listing, underwriting, market_context) -> dict`
- `call_openai_research_chat(messages/context, tools=[web_search]) -> dict`
- `extract_response_text_and_citations(response) -> dict`
- Reuse the existing Responses API patterns in `ai_underwriting.py`, especially `call_openai_researched_json`, `extract_response_text`, and `extract_web_sources`. For chat, the response can be normal text plus citation metadata rather than strict JSON, but tests should still cover citation extraction.

Use the Responses API rather than current Chat Completions for this feature because Responses supports built-in `web_search` tool calls with citation annotations.

### Listing Detail Context

Feed structured context:

- Saved search:
  - location
  - property type
  - beds
  - price bounds
  - market profile key/province

- Listing:
  - address
  - Realtor URL
  - price
  - beds/baths
  - property type/building type
  - square feet
  - land size
  - built year
  - taxes
  - HOA/strata
  - zoning
  - listing description
  - source key

- Underwriting:
  - market rent
  - monthly mortgage
  - monthly cash flow
  - annual NOI
  - cap rate
  - cash-on-cash return
  - rent/price ratio
  - assumptions and sources

- Market context:
  - CMHC rent/vacancy when available
  - HPI/appreciation snapshot if available
  - population/jobs/income metrics if available

### Research Behavior

For questions about subdivision, zoning, carriage homes, suites, STRs, municipal rules, rent trends, or local market quality, instruct the model to use web search.

For regulatory questions, prefer official/reputable sources:

- City/municipality websites
- Zoning bylaws
- subdivision/development bylaws
- official planning PDFs
- BC government housing pages
- CMHC
- CREA
- StatCan

If the market is Nanaimo, the prompt can include preferred search targets such as the City of Nanaimo and Province of BC, but should not hard-code only Nanaimo.

## V2: Market Context AI Chat

Add chat to `templates/market_context.html`.

### Good Questions

- How have home prices changed over the last five years in Nanaimo?
- Is Nanaimo considered a good place to live?
- What do people normally do in Nanaimo?
- What are the top jobs or industries?
- What are the subdivision rules?
- What are the multifamily housing rules?
- What are rental demand and vacancy trends?

### Context

Feed:

- market profile
- saved searches in this market
- HPI snapshots and historical series if loaded
- CMHC rent/vacancy references
- StatCan demographics/jobs/income metrics
- market seed/bootstrap data
- any AI estimates already persisted

### Retrieval

Use web search for:

- current municipal rules
- qualitative local market/livability questions
- employment/economic context
- current rent reports or market commentary

Use internal data first for:

- stored HPI/rent/vacancy metrics
- imported StatCan/CMHC data
- saved-search inventory context

## V3: Listing Analyzer AI Chat

Add chat to `templates/investment_analyzer.html`.

### Good Questions

- Which listings should I inspect first?
- Which favorites are strongest?
- Which listings have suite or subdivision potential?
- Why did these listings fail the buy box?
- What rent assumptions are most sensitive?
- What is considered a good cash-on-cash return?
- Which listings are risky despite good cash flow?

### Context

Feed a compact summary, not every full detail unless needed:

- saved-search setup
- active buy box and AI screen prompts/results
- underwriting defaults
- top listings by cash flow/cap rate/cash-on-cash
- rejected/uncertain listings summary
- favorite listings
- market context summary

For follow-up questions about a specific listing, include that listing's full context or link the user to listing detail chat.

## V4: Source and Document Memory

After V1-V3, add source memory:

- Store researched URLs, titles, fetched snippets, fetch time, market key, and topic.
- Add a cache table or local artifact store so repeated questions do not re-search every time.
- Add manually uploaded PDFs/bylaws/market reports with file search.
- Show "last researched" timestamps.

Potential storage concepts:

- `ai_research_sources`
  - market_key
  - saved_search_id
  - listing_id
  - topic
  - url
  - title
  - fetched_at
  - snippet/hash

- `ai_chat_sessions`
  - scope: `listing_detail`, `market_context`, `listing_analyzer`
  - saved_search_id
  - listing_id nullable
  - market_key nullable
  - created_at

- `ai_chat_messages`
  - session_id
  - role
  - content
  - citations JSON
  - model
  - created_at

## V5: Upgrade Remaining Existing AI Estimates

Market rental, market appreciation, listing rent suggestions, and research-needed buy-box prompts now use Responses API with web search.

Remaining candidate:

- Listing-detail chat for property-specific due diligence follow-up after buy-box triage.

Important caveat: rent suggestions for many listings could become expensive/slower with web search. A better path may be:

- Research market rent once per market/property/bedroom profile.
- Cache cited source context.
- Use that researched market context as an input to cheaper listing-level rent adjustment.

The current listing rent implementation follows this pattern at a basic level by making one web-search-enabled call for the whole listing batch.

## Implementation Notes for Next Agent

- Current AI helper module is `ai_underwriting.py`.
- Current app routes are in `app.py`.
- Current AI calls use `urllib.request` directly, not the OpenAI Python SDK.
- Web-search-backed AI estimate calls use `call_openai_researched_json` in `ai_underwriting.py`.
- Existing web-search helper uses the Responses API endpoint `https://api.openai.com/v1/responses` with `tools: [{"type": "web_search"}]`, `tool_choice: "auto"`, and `include: ["web_search_call.action.sources"]`.
- Use `OPENAI_RESEARCH_MODEL` for research/chat features, falling back to `OPENAI_UNDERWRITING_MODEL`.
- Existing AI outputs are stored in `ai_underwriting_suggestions`.
- Listing-level overrides/favorites currently use `listing_investment_overrides.overrides_snapshot`.
- Use `rg "call_openai"` to find all current AI calls.
- Use `rg "ai_underwriting_suggestions"` to find persisted AI output handling.
- Add tests around context-building and citation parsing without calling OpenAI.
- First implementation recommendation: build V1 listing-detail chat as a non-persistent request/response panel, then add chat session persistence after the UX is proven. This keeps the first slice small while still validating web search, citations, and listing-context quality.
