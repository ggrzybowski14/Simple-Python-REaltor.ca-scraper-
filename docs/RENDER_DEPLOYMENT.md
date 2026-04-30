# Render Deployment

This app deploys as a Render Python web service backed by Supabase.

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
4. Use the `standard` plan first because Playwright/Chromium needs more memory than a tiny web app.
5. Confirm the build command:

```bash
PLAYWRIGHT_BROWSERS_PATH=0 pip install -r requirements.txt && PLAYWRIGHT_BROWSERS_PATH=0 playwright install chromium
```

6. Confirm the start command:

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
