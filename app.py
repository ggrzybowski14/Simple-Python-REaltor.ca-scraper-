from __future__ import annotations

import json
import os
import subprocess
import sys
import uuid
import hashlib
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
DEFAULT_DETAIL_CONCURRENCY = 2
PROPERTY_TYPE_OPTIONS = ["house", "apartment", "condo"]
SCRAPE_JOBS: dict[str, dict[str, Any]] = {}
SCRAPE_JOBS_LOCK = Lock()
AI_BUY_BOX_CACHE: dict[str, dict[str, str]] = {}


@dataclass
class SupabaseReadConfig:
    url: str
    key: str


def parse_optional_int(value: str | None) -> int | None:
    if value is None:
        return None
    cleaned = value.strip()
    if not cleaned:
        return None
    try:
        return int(cleaned.replace(",", ""))
    except ValueError:
        return None


def parse_iso_timestamp(value: str | None) -> datetime | None:
    if not value:
        return None
    normalized = value.replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(normalized)
    except ValueError:
        return None


def parse_price_amount(value: str | None) -> int | None:
    if not value:
        return None
    digits = "".join(ch for ch in value if ch.isdigit())
    return int(digits) if digits else None


def normalize_keyword_list(value: str | None) -> list[str]:
    if not value:
        return []
    raw_parts = [part.strip().lower() for part in value.replace("\n", ",").split(",")]
    return [part for part in raw_parts if part]


def build_buy_box_criteria(args, saved_search: dict[str, Any]) -> dict[str, Any]:
    return {
        "max_price": parse_optional_int(args.get("buy_box_max_price")) if args.get("apply_buy_box") else saved_search.get("max_price"),
        "beds_min": parse_optional_int(args.get("buy_box_beds_min")) if args.get("apply_buy_box") else saved_search.get("beds_min"),
        "property_type": (args.get("buy_box_property_type") or "").strip().lower() or (saved_search.get("property_type") or ""),
        "required_keywords_raw": (args.get("buy_box_keywords") or "").strip(),
        "required_keywords": normalize_keyword_list(args.get("buy_box_keywords") or ""),
        "ai_goal_raw": (args.get("buy_box_ai_goal") or "").strip(),
        "ai_enabled": bool((args.get("buy_box_ai_goal") or "").strip()),
        "applied": bool(args.get("apply_buy_box")),
    }


def analyze_listing_against_buy_box(listing: dict[str, Any], criteria: dict[str, Any]) -> dict[str, Any]:
    reasons: list[str] = []
    listing_price = parse_price_amount(listing.get("price"))
    listing_beds = listing.get("bedrooms")
    listing_type_parts = [
        (listing.get("property_type") or "").strip().lower(),
        (listing.get("building_type") or "").strip().lower(),
    ]
    listing_type = " ".join(part for part in listing_type_parts if part)
    description = (listing.get("listing_description") or "").lower()

    if criteria.get("max_price") is not None:
        if listing_price is None:
            reasons.append("Missing price")
        elif listing_price > criteria["max_price"]:
            reasons.append(f"Price exceeds ${criteria['max_price']:,}")

    if criteria.get("beds_min") is not None:
        if listing_beds is None:
            reasons.append("Missing bedroom count")
        elif listing_beds < criteria["beds_min"]:
            reasons.append(f"Fewer than {criteria['beds_min']} beds")

    if criteria.get("property_type"):
        expected_type = criteria["property_type"]
        property_type_aliases = {
            "house": ["house", "single family"],
            "apartment": ["apartment"],
            "condo": ["condo", "apartment"],
        }
        aliases = property_type_aliases.get(expected_type, [expected_type])
        if not any(alias in listing_type for alias in aliases):
            reasons.append(f"Type is not {expected_type}")

    missing_keywords = [
        keyword for keyword in criteria.get("required_keywords", [])
        if keyword not in description
    ]
    if missing_keywords:
        reasons.append(f"Missing keywords: {', '.join(missing_keywords)}")

    return {
        "matched": not reasons,
        "reasons": reasons or ["Matches all buy-box rules"],
    }


def build_ai_buy_box_cache_key(goal: str, listing: dict[str, Any]) -> str:
    payload = "\n".join(
        [
            goal.strip(),
            str(listing.get("listing_id") or ""),
            listing.get("address") or "",
            listing.get("listing_description") or "",
        ]
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def call_openai_buy_box_assessment(goal: str, listings: list[dict[str, Any]]) -> dict[int, dict[str, str]]:
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key or not listings:
        return {}

    model = os.getenv("OPENAI_BUY_BOX_MODEL", "gpt-5.4-mini")
    user_payload = {
        "goal": goal,
        "listings": [
            {
                "listing_id": listing["listing_id"],
                "address": listing.get("address"),
                "description": listing.get("listing_description") or "",
            }
            for listing in listings
        ],
    }
    body = {
        "model": model,
        "messages": [
            {
                "role": "system",
                "content": (
                    "You analyze scraped real-estate listing descriptions for investment screening. "
                    "Assess whether each listing satisfies the user's qualitative criterion. "
                    "Return only structured JSON."
                ),
            },
            {
                "role": "user",
                "content": json.dumps(user_payload),
            },
        ],
        "response_format": {
            "type": "json_schema",
            "json_schema": {
                "name": "buy_box_ai_assessment",
                "strict": True,
                "schema": {
                    "type": "object",
                    "properties": {
                        "assessments": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "listing_id": {"type": "integer"},
                                    "verdict": {"type": "string", "enum": ["likely", "maybe", "no"]},
                                    "reason": {"type": "string"},
                                },
                                "required": ["listing_id", "verdict", "reason"],
                                "additionalProperties": False,
                            },
                        }
                    },
                    "required": ["assessments"],
                    "additionalProperties": False,
                },
            },
        },
    }

    req = request.Request(
        "https://api.openai.com/v1/chat/completions",
        data=json.dumps(body).encode("utf-8"),
        method="POST",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
    )
    try:
        with request.urlopen(req, timeout=60) as response:
            raw = response.read().decode("utf-8", errors="replace")
    except error.HTTPError as exc:
        details = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"OpenAI request failed with status {exc.code}: {details}") from exc
    except error.URLError as exc:
        raise RuntimeError(f"OpenAI request failed: {exc.reason}") from exc

    payload = json.loads(raw)
    content = payload["choices"][0]["message"]["content"]
    parsed = json.loads(content)
    assessment_by_listing_id: dict[int, dict[str, str]] = {}
    for item in parsed.get("assessments", []):
        listing_id = item.get("listing_id")
        verdict = item.get("verdict")
        reason = item.get("reason")
        if isinstance(listing_id, int) and isinstance(verdict, str) and isinstance(reason, str):
            assessment_by_listing_id[listing_id] = {"verdict": verdict, "reason": reason}
    return assessment_by_listing_id


def apply_ai_buy_box(goal: str, listings: list[dict[str, Any]]) -> tuple[dict[int, dict[str, str]], str | None]:
    if not goal.strip():
        return {}, None
    if not os.getenv("OPENAI_API_KEY"):
        return {}, "OPENAI_API_KEY is not configured for AI buy-box analysis."

    cached_results: dict[int, dict[str, str]] = {}
    uncached_listings: list[dict[str, Any]] = []
    uncached_keys: dict[int, str] = {}

    for listing in listings:
        cache_key = build_ai_buy_box_cache_key(goal, listing)
        cached = AI_BUY_BOX_CACHE.get(cache_key)
        if cached:
            cached_results[listing["listing_id"]] = cached
        else:
            uncached_listings.append(listing)
            uncached_keys[listing["listing_id"]] = cache_key

    if uncached_listings:
        fresh_results = call_openai_buy_box_assessment(goal, uncached_listings)
        for listing_id, result in fresh_results.items():
            cache_key = uncached_keys.get(listing_id)
            if cache_key:
                AI_BUY_BOX_CACHE[cache_key] = result
        cached_results.update(fresh_results)

    return cached_results, None


def analyze_active_listings(active_listings: list[dict[str, Any]], criteria: dict[str, Any]) -> dict[str, Any]:
    structured_matches: list[dict[str, Any]] = []
    structured_unmatched: list[dict[str, Any]] = []

    for listing in active_listings:
        result = analyze_listing_against_buy_box(listing, criteria)
        enriched_listing = dict(listing)
        enriched_listing["buy_box_match"] = result["matched"]
        enriched_listing["buy_box_reasons"] = result["reasons"]
        if result["matched"]:
            structured_matches.append(enriched_listing)
        else:
            structured_unmatched.append(enriched_listing)

    ai_results: dict[int, dict[str, str]] = {}
    ai_error: str | None = None
    if criteria.get("applied") and criteria.get("ai_goal_raw"):
        try:
            ai_results, ai_error = apply_ai_buy_box(criteria["ai_goal_raw"], structured_matches)
        except Exception as exc:
            ai_error = str(exc)

    matched: list[dict[str, Any]] = []
    maybe: list[dict[str, Any]] = []
    unmatched: list[dict[str, Any]] = list(structured_unmatched)

    for listing in structured_matches:
        if criteria.get("applied") and criteria.get("ai_goal_raw"):
            ai_result = ai_results.get(listing["listing_id"])
            if ai_result:
                listing["ai_buy_box_verdict"] = ai_result["verdict"]
                listing["ai_buy_box_reason"] = ai_result["reason"]
                if ai_result["verdict"] == "likely":
                    listing["buy_box_reasons"] = listing["buy_box_reasons"] + [f"AI: likely - {ai_result['reason']}"]
                    matched.append(listing)
                elif ai_result["verdict"] == "maybe":
                    listing["buy_box_match"] = False
                    listing["buy_box_reasons"] = listing["buy_box_reasons"] + [f"AI: maybe - {ai_result['reason']}"]
                    maybe.append(listing)
                else:
                    listing["buy_box_match"] = False
                    listing["buy_box_reasons"] = listing["buy_box_reasons"] + [f"AI: {ai_result['verdict']} - {ai_result['reason']}"]
                    unmatched.append(listing)
            else:
                if ai_error:
                    listing["buy_box_reasons"] = listing["buy_box_reasons"] + [f"AI unavailable: {ai_error}"]
                    matched.append(listing)
                else:
                    listing["buy_box_match"] = False
                    listing["buy_box_reasons"] = listing["buy_box_reasons"] + ["AI analysis unavailable"]
                    unmatched.append(listing)
        else:
            matched.append(listing)

    return {
        "matched": matched,
        "maybe": maybe,
        "unmatched": unmatched,
        "ai_error": ai_error,
    }


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
        latest_run = recent_runs[0] if recent_runs else None
        runs_by_saved_search = {}
        for run in recent_runs:
            runs_by_saved_search.setdefault(run["saved_search_id"], run)
        for search in saved_searches:
            search["latest_run"] = runs_by_saved_search.get(search["id"])
            search["updated_in_latest_run"] = bool(
                latest_run and latest_run.get("saved_search_id") == search["id"]
            )
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
        buy_box = build_buy_box_criteria(flask_request.args, saved_search)
        analysis = analyze_active_listings(active_listings, buy_box)
        scrape_runs = fetch_recent_runs(config, saved_search_id=saved_search_id)
        latest_run = scrape_runs[0] if scrape_runs else None
        return render_template(
            "saved_search.html",
            saved_search=saved_search,
            active_listings=active_listings,
            buy_box=buy_box,
            matched_listings=analysis["matched"],
            maybe_listings=analysis["maybe"],
            unmatched_listings=analysis["unmatched"],
            buy_box_ai_error=analysis["ai_error"],
            scrape_runs=scrape_runs,
            latest_run=latest_run,
            property_type_options=PROPERTY_TYPE_OPTIONS,
            current_query=flask_request.query_string.decode("utf-8"),
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
            back_query=flask_request.query_string.decode("utf-8"),
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
    searches = result if isinstance(result, list) else []
    now = datetime.utcnow().astimezone()
    for search in searches:
        last_scraped_at = parse_iso_timestamp(search.get("last_scraped_at"))
        search["updated_recently"] = bool(
            last_scraped_at and (now - last_scraped_at.astimezone()).total_seconds() <= 15 * 60
        )
    return searches


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
                "listing_description,"
                "time_on_realtor,zoning_type,url,results_page,is_new_in_run,last_seen_at"
            ),
            "order": "is_new_in_run.desc,price.asc.nullslast,listing_id.asc",
        },
    )
    listings = result if isinstance(result, list) else []
    merge_listing_media(config, listings)
    return listings


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
        listing = result[0]
        merge_listing_media(config, [listing])
        return listing
    return None


def fetch_listing_media(config: SupabaseReadConfig, listing_ids: list[int]) -> dict[int, dict[str, Any]]:
    unique_ids = sorted({listing_id for listing_id in listing_ids if listing_id})
    if not unique_ids:
        return {}

    result = supabase_get(
        config,
        "listings",
        query={
            "id": f"in.({','.join(str(listing_id) for listing_id in unique_ids)})",
            "select": "id,raw_listing",
        },
    )
    rows = result if isinstance(result, list) else []
    media_by_id: dict[int, dict[str, Any]] = {}
    for row in rows:
        raw_listing = row.get("raw_listing") if isinstance(row, dict) else None
        photo_urls = raw_listing.get("photo_urls") if isinstance(raw_listing, dict) else None
        if not isinstance(photo_urls, list):
            photo_urls = []
        cleaned_urls = [url for url in photo_urls if isinstance(url, str) and url.strip()]
        primary_photo_url = raw_listing.get("primary_photo_url") if isinstance(raw_listing, dict) else None
        if not primary_photo_url and cleaned_urls:
            primary_photo_url = cleaned_urls[0]
        media_by_id[row["id"]] = {
            "photo_urls": cleaned_urls[:6],
            "primary_photo_url": primary_photo_url,
        }
    return media_by_id


def merge_listing_media(config: SupabaseReadConfig, listings: list[dict[str, Any]]) -> None:
    media_by_id = fetch_listing_media(
        config,
        [listing.get("listing_id") for listing in listings if isinstance(listing, dict)],
    )
    for listing in listings:
        media = media_by_id.get(listing.get("listing_id"), {})
        listing["photo_urls"] = media.get("photo_urls", [])
        listing["primary_photo_url"] = media.get("primary_photo_url")


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
