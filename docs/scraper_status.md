# Scraper Status And Handoff

Last updated: 2026-04-27

This file captures the current scraper behavior, live benchmark results, and the active reliability issue so a new session can continue without reconstructing the conversation history.

## Current Scraper Behavior

- Main entry point: `scraper.py`.
- Browser: headed Playwright Chromium with `playwright-stealth`.
- Startup: opens neutral `https://www.realtor.ca/map`, then applies search criteria through the visible Realtor.ca UI.
- Collection no longer enforces a strict requested-city filter. It scrapes whatever listing cards Realtor shows for the filtered results.
- Pagination now waits for visible listing URLs to stabilize on each results page.
- If a next-page URL changes but cards/page indicator are stale, the scraper reloads the current results URL once and only continues if cards actually update.
- Detail enrichment runs after summary URL collection. `--detail-concurrency` controls how many detail pages are open in parallel.
- Repeat runs can reuse recently enriched Supabase rows when detail data is already fresh and complete.

## Proxy Behavior

Preferred setup uses Webshare API selection:

```bash
WEBSHARE_API_KEY=...
WEBSHARE_PROXY_MODE=direct
WEBSHARE_PROXY_COUNTRY_CODES=CA,US
```

When `WEBSHARE_API_KEY` is present, each scraper run:

1. Fetches the Webshare proxy list.
2. Filters to valid proxies.
3. Randomly selects one proxy for the browser launch.
4. Logs only the selected proxy host/port plus whether it is authenticated.

Manual `SCRAPER_PROXY_*` values remain as fallback if API lookup fails or returns no valid proxies.

## Performance Flags

Current performance-related CLI flags:

- `--detail-concurrency N`: number of parallel detail pages.
- `--detail-pause-min SECONDS`: lower bound for random delay before opening each detail page.
- `--detail-pause-max SECONDS`: upper bound for random delay before opening each detail page.
- `--block-detail-assets`: blocks detail-page images, media, fonts, and common analytics/tracking URLs.
- `--no-print-listings`: skips printing full listing JSON payloads after the run.

Asset blocking is not enabled by default. In tests it preserved at least a few photo URLs per listing, but lowered the average photo count because blocked images do not fully render.

## Live Benchmark Results

Search used for the benchmark runs:

```bash
--location Victoria
--beds-min 2
--property-type house
--max-price 1000000
--max-pages 6
--max-listings 60
--detail-limit 60
--detail-pause-min 0.2
--detail-pause-max 0.5
--no-supabase
--no-print-listings
```

Validated before security challenges appeared:

| Settings | Result | Detail time | Total time | Notes |
| --- | --- | ---: | ---: | --- |
| concurrency 12, no asset blocking | 60/60 details | 75.2s | 106.1s | photo avg 8.17/listing |
| concurrency 12, `--block-detail-assets` | 60/60 details | 59.8s | 90.9s | photo avg 6.95/listing, no photo-missing listings |

Aggressive concurrency tests:

| Settings | Result | Detail time | Total time | Notes |
| --- | --- | ---: | ---: | --- |
| concurrency 16, `--block-detail-assets` | 60/60 eventually | 285.7s | 314.6s | 28 first-pass failures, sequential retry recovered |
| concurrency 14, `--block-detail-assets` | 60/60 eventually | 311.4s | 339.3s | 31 first-pass failures, security challenge visible |

Conclusion from current tests:

- `12 + --block-detail-assets` was the best confirmed setting before challenges appeared.
- `14` and `16` are too aggressive for a single browser/proxy/session.
- After the aggressive tests, Realtor began serving security-check pages even during a later `12` run, so the current setup needs a cooldown/retest.

## Current Security-Challenge Issue

Realtor started serving a page with:

```text
www.realtor.ca Additional security check is required
Click to verify
```

This happened during detail-page enrichment after pushing concurrency above the stable range. It then reproduced during a later `12` concurrency run.

The scraper now detects this challenge text and treats it separately from ordinary timeouts:

- raises a `SecurityChallengeError`
- marks the current detail batch as challenged
- skips queued detail work after the challenge flag is set
- avoids automatic sequential retry for challenge-triggered failures

This avoids continuing to hammer challenged pages and keeps future runs easier to diagnose.

## Recommended Next Retest

Do not immediately keep speed-testing the same proxy/session after a challenge. Recommended next pass:

1. Let the proxy/session cool down.
2. Start with a smaller validation run, for example `--max-listings 12 --detail-limit 12 --detail-concurrency 4 --block-detail-assets`.
3. If no challenge appears, test `--detail-concurrency 6`.
4. Then test `--detail-concurrency 8`.
5. Only retest `12` after lower concurrency is clean.

Future scaling should probably use multiple browser contexts/proxies with modest per-proxy concurrency rather than pushing one browser/proxy above 12 detail tabs.

## Commands

Small proxy-backed validation:

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python scraper.py \
  --location Victoria \
  --beds-min 2 \
  --property-type house \
  --max-price 1000000 \
  --max-pages 1 \
  --max-listings 12 \
  --detail-limit 12 \
  --detail-concurrency 4 \
  --detail-pause-min 0.2 \
  --detail-pause-max 0.5 \
  --block-detail-assets \
  --no-supabase \
  --no-print-listings
```

Current best historical benchmark command, to retest only after lower concurrency is clean:

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python scraper.py \
  --location Victoria \
  --beds-min 2 \
  --property-type house \
  --max-price 1000000 \
  --max-pages 6 \
  --max-listings 60 \
  --detail-limit 60 \
  --detail-concurrency 12 \
  --detail-pause-min 0.2 \
  --detail-pause-max 0.5 \
  --block-detail-assets \
  --no-supabase \
  --no-print-listings
```
