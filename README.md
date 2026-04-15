# Realtor.ca Scraper POC

This is a deliberately small proof of concept built to answer one question:

Can a visible Python Playwright browser with stealth and light human-like behavior scrape one or two Realtor.ca listings from a known Victoria URL?

## What it does

- Opens a visible Chromium browser
- Applies `playwright-stealth`
- Loads the provided Victoria Realtor.ca map/results URL
- Waits, moves the mouse, and scrolls lightly
- Scrapes up to two listings from the results tiles
- Prints a few fields to the terminal
- Saves a screenshot and HTML snapshot on failure

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
playwright install chromium
python scraper.py
```

## Logs and failure artifacts

The script logs each major step to the terminal.

If scraping fails, it writes artifacts into `artifacts/`:

- a full-page screenshot
- the current page HTML

This is meant to make selector issues and anti-bot issues easier to diagnose without adding unnecessary framework code.
