# Render Deployment

This app can deploy as either a Render Python web service or a Docker web service backed by Supabase.

The Docker service is preferred for hosted scraping because it runs the scraper's visible Chromium browser inside `Xvfb`, which more closely matches the local headed-browser workflow than headless Chromium.

Current hosted development and testing happens from the `render-deployment` branch. Recent app fixes are pushed there first so Render can redeploy from GitHub.

## What Goes Where

- Local development secrets stay in `.env.local`.
- Production secrets go in Render environment variables.
- Supabase does not store your OpenAI, Webshare, or Flask secrets.
- Supabase only provides its own project URL and API keys, which the Flask app reads from Render at runtime.

Do not commit `.env.local`. It is ignored by git.

## Supabase Values

In Supabase, open your project dashboard:

1. Go to `Project Settings`.
2. Open `API`.
3. Copy the project URL into Render as `SUPABASE_URL`.
4. Copy the key you currently use locally into Render as `SUPABASE_KEY`.

For this prototype, the app writes directly to Supabase from the server. Keep `SUPABASE_KEY` server-side only in Render environment variables. Do not put it in frontend JavaScript, templates, or committed files.

## Render Setup

1. Push this repo to GitHub.
2. In Render, choose `New` -> `Blueprint` if using `render.yaml`, or `New` -> `Web Service` if configuring manually.
3. Connect the GitHub repo.
4. Select the `render-deployment` branch for the active hosted prototype.
5. Use the `standard` plan first because Playwright/Chromium needs more memory than a tiny web app.

### Docker Service

The Blueprint defines `realtor-analyzer-docker` with:

```yaml
runtime: docker
dockerfilePath: ./Dockerfile
```

The Docker entrypoint starts `Xvfb` and then runs Gunicorn. It sets:

```bash
SCRAPER_HEADLESS=false
DISPLAY=:99
```

This lets Playwright launch a headed Chromium browser without a physical display.

### Native Python Service

The earlier native Python service can still run the web app, but headless Chromium does not reliably activate Realtor.ca's location autocomplete. If using the native Python service, confirm the build command:

```bash
PLAYWRIGHT_BROWSERS_PATH=0 pip install -r requirements.txt && PLAYWRIGHT_BROWSERS_PATH=0 playwright install chromium
```

And confirm the start command:

```bash
PLAYWRIGHT_BROWSERS_PATH=0 gunicorn app:app --bind 0.0.0.0:$PORT --workers 1 --threads 4 --timeout 180
```

7. Add the required environment variables:

```bash
SUPABASE_URL=...
SUPABASE_KEY=...
OPENAI_API_KEY=...
SCRAPER_HEADLESS=true
```

Optional proxy variables:

```bash
WEBSHARE_API_KEY=...
WEBSHARE_PROXY_MODE=direct
WEBSHARE_PROXY_COUNTRY_CODES=CA,US
```

## Current Prototype Caveats

- Scrape jobs still launch from the web app process.
- Job logs are written under `artifacts/web_jobs`, which is ephemeral on Render unless a persistent disk is attached.
- A Render restart or redeploy can interrupt an active scrape job.
- This is acceptable for the first deployment, but background jobs should later move to a worker/queue.
- If Render auto-deploy is enabled, pushing to `render-deployment` starts a deploy automatically; otherwise use Manual Deploy in the Render dashboard.
- Current scraper default in the Flask app is `--detail-concurrency 6` with pacing and detail asset blocking.
