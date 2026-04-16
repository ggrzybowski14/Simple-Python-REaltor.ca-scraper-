from __future__ import annotations

import json
import os
import subprocess
import sys
import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from threading import Lock, Thread
from typing import Any
from urllib import error, parse, request

from flask import Flask, abort, redirect, render_template, request as flask_request, url_for

from scraper import load_dotenv


APP_ROOT = Path(__file__).parent
LOCAL_JOB_LOG_DIR = APP_ROOT / "artifacts" / "web_jobs"
DEFAULT_MAX_PAGES = 3
DEFAULT_MAX_LISTINGS = 25
DEFAULT_DETAIL_LIMIT = DEFAULT_MAX_LISTINGS
DEFAULT_DETAIL_CONCURRENCY = 1
PROPERTY_TYPE_OPTIONS = ["house", "apartment", "condo"]
SCRAPE_JOBS: dict[str, dict[str, Any]] = {}
SCRAPE_JOBS_LOCK = Lock()


@dataclass
class SupabaseReadConfig:
    url: str
    key: str


def create_app() -> Flask:
    load_dotenv()
    app = Flask(__name__)
    app.config["SECRET_KEY"] = os.getenv("FLASK_SECRET_KEY", "local-real-estate-analyzer")

    @app.context_processor
    def inject_now() -> dict[str, Any]:
        return {"now": datetime.utcnow()}

    @app.route("/")
    def dashboard() -> str:
        config = get_supabase_read_config()
        saved_searches = fetch_saved_searches(config)
        recent_runs = fetch_recent_runs(config)
        job_snapshots = list_scrape_jobs()
        return render_template(
            "dashboard.html",
            saved_searches=saved_searches,
            recent_runs=recent_runs,
            jobs=job_snapshots,
            property_type_options=PROPERTY_TYPE_OPTIONS,
        )

    @app.route("/saved-searches/<int:saved_search_id>")
    def saved_search_detail(saved_search_id: int) -> str:
        config = get_supabase_read_config()
        saved_search = fetch_saved_search(config, saved_search_id)
        if saved_search is None:
            abort(404)
        active_listings = fetch_active_listings(config, saved_search_id)
        scrape_runs = fetch_recent_runs(config, saved_search_id=saved_search_id)
        latest_run = scrape_runs[0] if scrape_runs else None
        return render_template(
            "saved_search.html",
            saved_search=saved_search,
            active_listings=active_listings,
            scrape_runs=scrape_runs,
            latest_run=latest_run,
        )

    @app.route("/saved-searches/<int:saved_search_id>/listings/<int:listing_id>")
    def listing_detail(saved_search_id: int, listing_id: int) -> str:
        config = get_supabase_read_config()
        saved_search = fetch_saved_search(config, saved_search_id)
        if saved_search is None:
            abort(404)
        listing = fetch_active_listing_detail(config, saved_search_id, listing_id)
        if listing is None:
            abort(404)
        return render_template(
            "listing_detail.html",
            saved_search=saved_search,
            listing=listing,
        )

    @app.route("/scrapes", methods=["POST"])
    def create_scrape() -> Any:
        location = (flask_request.form.get("location") or "").strip()
        if not location:
            abort(400, "Location is required")

        args = build_scrape_args(flask_request.form)
        job = start_scrape_job(args)
        return redirect(url_for("dashboard", started=job["id"]))

    @app.route("/jobs/<job_id>")
    def job_detail(job_id: str) -> str:
        job = get_scrape_job(job_id)
        if job is None:
            abort(404)
        return render_template("job_detail.html", job=job)

    return app


def get_supabase_read_config() -> SupabaseReadConfig:
    url = os.getenv("SUPABASE_URL")
    key = os.getenv("SUPABASE_KEY")
    if not url or not key:
        raise RuntimeError("SUPABASE_URL and SUPABASE_KEY must be configured for the local website")
    return SupabaseReadConfig(url=url.rstrip("/"), key=key)


def supabase_get(config: SupabaseReadConfig, path: str, *, query: dict[str, Any] | None = None) -> Any:
    endpoint = f"{config.url}/rest/v1/{path}"
    if query:
        endpoint = f"{endpoint}?{parse.urlencode(query, doseq=True)}"

    req = request.Request(
        endpoint,
        headers={
            "apikey": config.key,
            "Authorization": f"Bearer {config.key}",
            "Accept": "application/json",
        },
    )
    try:
        with request.urlopen(req, timeout=30) as response:
            raw = response.read().decode("utf-8", errors="replace")
            return json.loads(raw) if raw else None
    except error.HTTPError as exc:
        details = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Supabase read failed with status {exc.code}: {details}") from exc
    except error.URLError as exc:
        raise RuntimeError(f"Supabase read failed: {exc.reason}") from exc


def fetch_saved_searches(config: SupabaseReadConfig) -> list[dict[str, Any]]:
    result = supabase_get(
        config,
        "saved_searches",
        query={
            "select": "id,search_key,name,location,min_price,max_price,beds_min,property_type,last_scraped_at",
            "order": "last_scraped_at.desc.nullslast,id.desc",
        },
    )
    return result if isinstance(result, list) else []


def fetch_saved_search(config: SupabaseReadConfig, saved_search_id: int) -> dict[str, Any] | None:
    result = supabase_get(
        config,
        "saved_searches",
        query={
            "id": f"eq.{saved_search_id}",
            "select": "id,search_key,name,location,min_price,max_price,beds_min,property_type,last_scraped_at",
            "limit": 1,
        },
    )
    if isinstance(result, list) and result:
        return result[0]
    return None


def fetch_recent_runs(config: SupabaseReadConfig, *, saved_search_id: int | None = None) -> list[dict[str, Any]]:
    query: dict[str, Any] = {
        "select": "id,saved_search_id,status,results_count,summary_count,detail_attempted,detail_succeeded,started_at,finished_at",
        "order": "id.desc",
        "limit": 20,
    }
    if saved_search_id is not None:
        query["saved_search_id"] = f"eq.{saved_search_id}"
    result = supabase_get(config, "scrape_runs", query=query)
    return result if isinstance(result, list) else []


def fetch_active_listings(config: SupabaseReadConfig, saved_search_id: int) -> list[dict[str, Any]]:
    result = supabase_get(
        config,
        "current_active_saved_search_listings",
        query={
            "saved_search_id": f"eq.{saved_search_id}",
            "select": (
                "saved_search_id,listing_id,address,price,bedrooms,bathrooms,property_type,"
                "building_type,square_feet,land_size,built_in,annual_taxes,hoa_fees,"
                "time_on_realtor,zoning_type,url,results_page,is_new_in_run,last_seen_at"
            ),
            "order": "is_new_in_run.desc,price.asc.nullslast,listing_id.asc",
        },
    )
    return result if isinstance(result, list) else []


def fetch_active_listing_detail(
    config: SupabaseReadConfig,
    saved_search_id: int,
    listing_id: int,
) -> dict[str, Any] | None:
    result = supabase_get(
        config,
        "current_active_saved_search_listings",
        query={
            "saved_search_id": f"eq.{saved_search_id}",
            "listing_id": f"eq.{listing_id}",
            "select": (
                "saved_search_id,listing_id,address,price,bedrooms,bathrooms,property_type,building_type,"
                "square_feet,land_size,built_in,annual_taxes,hoa_fees,time_on_realtor,zoning_type,url,"
                "results_page,is_new_in_run,last_seen_at,listing_description,source_listing_key,source"
            ),
            "limit": 1,
        },
    )
    if isinstance(result, list) and result:
        return result[0]
    return None


def build_scrape_args(form_data) -> list[str]:
    args = [str(resolve_scraper_python()), "scraper.py"]

    def append_value(flag: str, value: str | None) -> None:
        if value is None:
            return
        cleaned = value.strip()
        if cleaned:
            args.extend([flag, cleaned])

    append_value("--location", form_data.get("location"))
    append_value("--beds-min", form_data.get("beds_min"))
    append_value("--property-type", form_data.get("property_type"))
    append_value("--min-price", form_data.get("min_price"))
    append_value("--max-price", form_data.get("max_price"))
    append_value("--max-pages", form_data.get("max_pages") or str(DEFAULT_MAX_PAGES))
    append_value("--max-listings", form_data.get("max_listings") or str(DEFAULT_MAX_LISTINGS))
    append_value("--detail-limit", form_data.get("detail_limit") or str(DEFAULT_DETAIL_LIMIT))
    append_value("--detail-concurrency", form_data.get("detail_concurrency") or str(DEFAULT_DETAIL_CONCURRENCY))
    return args


def resolve_scraper_python() -> Path:
    venv_python = APP_ROOT / ".venv" / "bin" / "python"
    return venv_python if venv_python.exists() else Path(sys.executable)


def start_scrape_job(args: list[str]) -> dict[str, Any]:
    LOCAL_JOB_LOG_DIR.mkdir(parents=True, exist_ok=True)
    job_id = uuid.uuid4().hex[:12]
    started_at = datetime.utcnow().isoformat(timespec="seconds") + "Z"
    log_path = LOCAL_JOB_LOG_DIR / f"{job_id}.log"
    log_handle = log_path.open("w", encoding="utf-8")
    env = os.environ.copy()
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    process = subprocess.Popen(
        args,
        cwd=APP_ROOT,
        stdout=log_handle,
        stderr=subprocess.STDOUT,
        text=True,
        env=env,
    )
    log_handle.close()

    job = {
        "id": job_id,
        "args": args[1:],
        "pid": process.pid,
        "started_at": started_at,
        "log_path": str(log_path),
        "status_path": str(LOCAL_JOB_LOG_DIR / f"{job_id}.status.json"),
    }
    with SCRAPE_JOBS_LOCK:
        SCRAPE_JOBS[job_id] = job
    write_job_status(job, status="running", return_code=None)
    watcher = Thread(target=watch_scrape_job, args=(job, process), daemon=True)
    watcher.start()
    return job


def watch_scrape_job(job: dict[str, Any], process: subprocess.Popen[str]) -> None:
    return_code = process.wait()
    status = "succeeded" if return_code == 0 else "failed"
    write_job_status(job, status=status, return_code=return_code)


def list_scrape_jobs() -> list[dict[str, Any]]:
    with SCRAPE_JOBS_LOCK:
        jobs = [augment_job_snapshot(job) for job in SCRAPE_JOBS.values()]
    return sorted(jobs, key=lambda item: item["started_at"], reverse=True)


def get_scrape_job(job_id: str) -> dict[str, Any] | None:
    with SCRAPE_JOBS_LOCK:
        job = SCRAPE_JOBS.get(job_id)
    return augment_job_snapshot(job) if job else None


def augment_job_snapshot(job: dict[str, Any] | None) -> dict[str, Any]:
    if job is None:
        return {}

    pid = job["pid"]
    status_payload = read_job_status(job)
    return_code = status_payload.get("return_code")
    status_label = status_payload.get("status", "running")

    if status_label == "running":
        try:
            os.kill(pid, 0)
        except OSError:
            if return_code is None:
                status_label = "unknown"
        else:
            status_label = "running"

    log_path = Path(job["log_path"])
    log_tail = ""
    if log_path.exists():
        lines = log_path.read_text(encoding="utf-8", errors="replace").splitlines()
        log_tail = "\n".join(lines[-20:])

    snapshot = dict(job)
    snapshot["status"] = status_label
    snapshot["return_code"] = return_code
    snapshot["log_tail"] = log_tail
    return snapshot


def write_job_status(job: dict[str, Any], *, status: str, return_code: int | None) -> None:
    status_path = Path(job["status_path"])
    payload = {
        "status": status,
        "return_code": return_code,
        "updated_at": datetime.utcnow().isoformat(timespec="seconds") + "Z",
    }
    status_path.write_text(json.dumps(payload), encoding="utf-8")


def read_job_status(job: dict[str, Any]) -> dict[str, Any]:
    status_path = Path(job["status_path"])
    if not status_path.exists():
        return {"status": "running", "return_code": None}
    try:
        return json.loads(status_path.read_text(encoding="utf-8"))
    except Exception:
        return {"status": "unknown", "return_code": None}


app = create_app()


if __name__ == "__main__":
    app.run(debug=True, use_reloader=False, port=int(os.getenv("PORT", "5000")))
