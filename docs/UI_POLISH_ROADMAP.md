# UI Polish Roadmap And Handoff

Last updated: 2026-04-30

This file captures the UI/workflow polish brainstorm and the work completed during the April 30 demo-readiness pass. Use it to continue the product-facing cleanup without redoing the discussion.

## Product Language Direction

- Prefer customer-facing language over implementation language.
- Avoid visible words like `scrape`, `scraper`, `local scaffold`, `phase`, and internal run/status details unless the user is on a technical progress page.
- Prefer:
  - `Find listings`
  - `Refresh listings`
  - `Listing search`
  - `Listings loaded`
  - `Last updated`
  - `Analyze listings`
  - `Open market`
- Keep AI/source details visible when useful, but put long reasoning in `details` dropdowns such as `Source notes`, `How this works`, or later listing-detail reasoning panels.

## Completed In This Pass

### Dashboard

- Header changed to `Canadian Real Estate Analyzer`.
- Removed `Local Website Scaffold`, `Phase 2 Scaffold`, and scraper-oriented copy.
- Hero changed to a product-facing welcome message.
- New listing search card uses:
  - `Listing search`
  - `What listings are you interested in finding?`
  - `Find listings`
- Saved search cards were simplified:
  - removed repeated location/filter/run metadata
  - kept the red update dot only
  - buttons now read `Open search`, `Open market`, and `Refresh listings`
- Technical recent-runs panel was removed.
- Listing activity panel was kept as a compact collapsible status panel.
- Market cards no longer show internal `market_key`.

### Saved Search Detail Page

- Page title uses title-cased display and product wording, for example `Victoria House Search`.
- Criteria moved to subtitle, for example `2+ beds under $1,000,000`.
- Removed visible scrape limits from the hero.
- Hero actions now use `Open market` and `Refresh listings`.
- Metrics use:
  - `Listings Available`
  - `Listings Loaded`
  - `Last Updated`
- Raw ISO timestamps are formatted with the `display_time` filter using `America/Vancouver`.
  - Note: dates in late April are PDT, not PST.
- Listing section now says `Listings` and `3 listings found`.
- Listing card link changed to `View listing details`.
- Listing cards were made more compact on desktop by moving images left and details right.
- Analysis card now owns the primary red `Analyze listings` CTA.
- Removed the saved-buy-box summary from this page.

### Listing Analyzer Hero And Setup

- Listing analyzer hero now follows the saved-search title style:
  - `Duncan House Analysis`
  - subtitle like `3+ beds under $1,000,000`
- Removed `active scraped listing` language.
- Removed the `Listings To Analyze` metric tile.
- `Market Context` changed to `Open market`.
- Buy-box setup language was changed to user-facing preference language:
  - `What are you looking for?`
  - `Use filters and interest prompts to guide the listing analysis.`
  - `Interest 1 description`
  - `Interest 2 description`
  - `Use this`
- Keyword filter was removed from the visible setup UI because it overlaps with interest prompts.
- Hidden empty `buy_box_keywords` remains so old keyword filters are cleared on rerun.
- Price/bedroom filters are collapsed by default.

### Listing Analyzer Assumptions

- Section renamed to `Analysis assumptions`.
- Removed small all-caps eyebrow labels from this section.
- Financing is at the top.
- Rent comes next.
- Operating costs come after rent.
- Rent label simplified to `Monthly Rent`.
- Rent source cards use compact combined titles:
  - `Manual: set value directly`
  - `CMHC: use market baseline`
  - `AI: generate listing values`
- Removed top-level `Source` links from assumption titles.
- Removed source/confidence pills from financing and operating-cost assumption cards.
- Operating-cost cards now use a more compact two-column grid:
  - `Vacancy` + `Property Management`
  - `Maintenance Reserve` + `CapEx Reserve`
  - `Insurance` + `Utilities`
  - `Other Costs` as a normal half-width tile
- Source choices within operating-cost cards use compact side-by-side tiles.
- Long CMHC/source notes and AI explanation text moved into collapsible details.
- Main `Vacancy` info tooltip now explains vacancy itself rather than the active CMHC/manual source.

## Remaining Near-Term UI Work

### Listing Analyzer Results Table

This is the next highest-value UI target.

- Make `Strong`, `Review`, and `Reject` groups visually obvious.
- Consider collapsible result groups.
- Make strong results feel clearly positive at a glance.
- Tighten the `Buy Box Outcome` column.
- Remove noisy subtext such as AI screen counts from the table.
- Move detailed AI/source reasoning to listing detail or row-level dropdowns.
- Add clear sorting controls:
  - cash flow
  - cap rate
  - cash-on-cash
  - rent-to-price ratio
- Make the default ranking obvious to the user.
- Consider whether `Final Score` should be the primary visible rating, with buy-box and underwriting as supporting context.

### Listing Detail Page

- Remove remaining `scraped` / internal wording.
- Polish listing facts and underwriting summary into customer-facing sections.
- Add or reserve space for the planned listing-detail AI chat.
- Keep detailed buy-box/AI reasoning and rent reasoning here rather than bloating analyzer tables.
- Make listing-specific underwriting overrides easier to scan and edit.
- Keep favorite action prominent but not visually noisy.

### Market Context Pages

- Add location photo and short market description.
- Replace internal/empty-state language with polished market-page copy.
- Keep partial-data/source limitations visible but not prototype-sounding.
- Add/reserve market AI chat.
- Improve market cards and top-line investor metrics.
- Continue clear labels for official data, proxies, closest matches, and AI estimates.

### Fetch/Job Progress UI

- Continue replacing visible `scrape`/`scraper` with `listing search` / `fetching listings`.
- Make running listing searches clearer:
  - `Fetching your listings`
  - `This can take a few minutes`
  - status/progress
- Add auto-refresh or polling when listing fetch jobs complete.

### Delete Demo Data

- Add ability to delete old/demo saved searches.
- Deleting a saved search should remove associated saved-search links, runs, analysis state, overrides, and job context.
- Be careful with canonical listings that may belong to other saved searches.

## Performance Follow-Up

After the demo UI pass, return to performance.

- Add route timing logs for Supabase calls, OpenAI calls, render time, and context-building.
- Investigate slow page-to-page navigation separately from AI latency.
- Cache repeated market reference reads and market metric reads.
- Avoid rebuilding analysis or invoking AI during normal navigation.
- Convert slow AI actions to background jobs where useful.

## Feature Backlog From Brainstorm

### AI Chat Surfaces

- Listing detail AI chat.
- Market context AI chat.
- Listing analyzer AI chat.
- Use page-specific app context.
- Use web search for current market, zoning, permit, tax, and regulatory questions.
- Show citations/source trail.

### Market Enrichment

- Market photo.
- Short market description.
- Potentially AI-generated or curated with attribution/source rules.

### Due Diligence Research

- Permit rules.
- Renovation rules.
- Rental and short-term rental rules.
- Secondary suite, carriage home, subdivision, and zoning questions.
- Local qualitative research, including official sources first and community sources where useful.

### Investor Strategy Questions

- Self-managed rental.
- Property-managed rental.
- Living in the property and renting a room.
- Tax implications by strategy and market, with accountant/legal verification language.

### Future / Farther-Out

- User goal/preferences scoring.
- Expected renovation cost estimator using listing photos, age, condition, and target renovation style.
- Break-even charts showing cumulative cash recovery over time.
- Long-term return projections:
  - appreciation
  - rent growth
  - debt paydown
  - equity growth
  - IRR-style outputs
- Strategy overlays:
  - house hacking
  - BRRR
  - flip
  - short-term rental
- Persistent AI research memory and cached source documents.
