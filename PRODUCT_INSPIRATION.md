# Product Inspiration

This file is the durable reference for external product patterns, screenshots, and research notes that should carry forward across sessions.

Use this file when:

- evaluating UI and UX patterns worth borrowing
- preserving product ideas from screenshots and links
- handing off design direction to a future agent
- avoiding repeated explanation of the same references

## How To Use This File

When a new external product reference comes up, capture:

- the product or page name
- the URL if available
- the specific pattern worth reusing
- any important caveats
- whether it is `active inspiration` or `future inspiration`

This file is not a feature spec or status report. The product roadmap and implementation plan live in [PROJECT_OVERVIEW.md](/Users/georgia/Projects/simple realtor.ca scraper python/PROJECT_OVERVIEW.md:1), and current implementation/setup notes live in [README.md](/Users/georgia/Projects/simple realtor.ca scraper python/README.md:1).

## Active Inspiration

### BiggerPockets Rental Analyzer

Reference:

- `BiggerPockets rental/property insights flow`
- example property-insights URL pattern:
  `https://www.biggerpockets.com/insights/properties/...`

Observed patterns worth reusing:

- estimated rent shown near the top of the property analysis flow
- visible confidence label for rent estimate
- comparable rentals shown on a map
- comparable rental cards with rent, date, address, bed, bath, square footage, and year built
- analyzer flow that turns listing facts into investment assumptions rather than expecting the user to start from a blank spreadsheet
- clean separation between current property snapshot and deeper underwriting outputs

Implications for our product:

- listing-level rent estimation should be auto-filled where possible
- every estimated value should have `source` and `confidence`
- comparable rentals should eventually be viewable alongside the estimate
- the listing analyzer should feel like a guided underwriting surface, not just a table of formulas
- source controls should live close to the affected assumption card rather than in a detached workflow section

Status:

- `active inspiration`

### BiggerPockets Investment Calculator Structure

Reference:

- reviewed workbook: `BiggerPockets_STR_Calculator_V3.xlsx`
- reviewed PDF summary exported from a BiggerPockets analysis

Observed structural patterns:

- purchase inputs are separated from revenue, expenses, financing, and returns
- investor metrics are surfaced prominently
- longer-term projections are separated from the current underwriting snapshot
- projections include appreciation, debt paydown, equity growth, and IRR-style outputs

Implications for our product:

- keep `cash flow` as the backbone
- keep `NOI`, `cap rate`, and `cash-on-cash` as first-class metrics
- keep `CapEx` separate from `NOI` in v1
- treat long-term projection metrics as a later layer after the base underwriting engine is stable

Status:

- `active inspiration`

### BiggerPockets Market Finder

Reference:

- `https://www.biggerpockets.com/markets`

Observed patterns worth reusing:

- a dedicated market-level experience separate from property analysis
- geographic market browsing rather than only property browsing
- map-based market exploration
- market cards with concise top-line metrics
- recommended markets section
- investor-facing market metrics such as:
  - appreciation
  - rent-to-price ratio
  - affordability
  - population
  - unemployment
  - median home value
  - median rental income
  - YoY home value growth
  - YoY rent growth

Implications for our product:

- we should build a future `market analyzer` section for Canada
- market pages should be distinct from listing pages
- scraped markets like `Duncan` should eventually auto-create market tiles in the app
- market cards should show fast investor-relevant metrics rather than generic census summaries
- market browsing should support both:
  - markets created from user scrapes
  - markets searched directly later

Important caveat:

- BiggerPockets is US-focused; our implementation needs Canadian data sources and Canadian geography concepts

Status:

- `active inspiration`

Current translation note:

- the first market-context scaffold now exists in the codebase, so this inspiration has moved from abstract planning into an active implementation path

## Current Product Translation

These references translate into the following concrete product direction for this repo:

- `listing analyzer`
  buy-and-hold underwriting for individual listings
- `market analyzer`
  future market-level pages for Canadian regions
- `assumptions model`
  auto-filled when possible, editable by the user
- `confidence model`
  every important estimate should indicate source and confidence
- `investment UX`
  metrics should be presented as decisions and signals, not just raw formulas
- `source UX`
  manual, CMHC, and AI should behave as explicit source modes in the same assumption card

## Future Market Analyzer Notes

Current direction for the future Canada-focused market analyzer:

- market tile should be created when a user has already scraped a region
- clicking the tile opens a market page for that region
- the page should eventually show:
  - rent growth
  - appreciation trends
  - population growth
  - job growth
  - median household income
  - supply constraints
  - liquidity / resale ease
  - rent-to-price style metrics
- summary of our own scraped listing inventory for that market

Current implementation status:

- direct market routes now exist for seeded markets like `Duncan` and `Victoria`
- the dashboard now includes a `Markets analyzed` panel
- the current market page already shows:
  - CMHC housing fundamentals
  - structured Statistics Canada metrics
  - an appreciation section with a real series when available and an explicit empty state when it is not

Near-term implication:

- future inspiration work should now focus less on whether market pages should exist and more on what the next highest-value fields and visual patterns should be inside that page

Potential top-line card metrics:

- median home price
- estimated median market rent
- rent-to-price ratio
- recent home price growth
- recent rent growth
- vacancy proxy or estimate
- affordability context

## Documentation Workflow Going Forward

To avoid repeated screenshots and repeated explanation:

1. add new product references to this file
2. put durable product decisions in [PROJECT_OVERVIEW.md](/Users/georgia/Projects/simple realtor.ca scraper python/PROJECT_OVERVIEW.md:1)
3. keep implementation details and current setup notes in [README.md](/Users/georgia/Projects/simple realtor.ca scraper python/README.md:1)

That split should let future agents recover:

- what inspired the product
- what decisions have already been made
- what the next implementation steps are
- where to look for current functionality versus future direction
