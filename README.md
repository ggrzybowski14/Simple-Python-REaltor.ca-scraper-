# Realtor.ca Scraper POC

This is a deliberately small proof of concept built to answer one question:

Can a visible Python Playwright browser with stealth and light human-like behavior accept simple search inputs, drive Realtor.ca's filters, and scrape matching listing data?

## What it does

- Opens a visible Chromium browser
- Applies `playwright-stealth`
- Opens the Realtor.ca map/results experience in a visible browser
- Accepts runtime search inputs for location, min/max price, minimum beds, and property type
- Uses the visible Realtor.ca search UI to apply those filters
- Waits, moves the mouse, and scrolls lightly
- Scrapes a small sample of matching listings from the results tiles
- Prints a few fields to the terminal
- Saves a screenshot and HTML snapshot on failure
- Saves JSON output that includes the search criteria used for the run

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
playwright install chromium
python scraper.py

# or pass filters directly
python scraper.py --location Victoria --beds-min 2 --property-type house --max-price 1000000
```

## Logs and failure artifacts

The script logs each major step to the terminal.

If scraping fails, it writes artifacts into `artifacts/`:

- a full-page screenshot
- the current page HTML

This is meant to make selector issues and anti-bot issues easier to diagnose without adding unnecessary framework code.
