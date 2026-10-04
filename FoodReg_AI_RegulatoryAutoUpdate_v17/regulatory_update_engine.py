"""
FoodReg AI - Regulatory Auto-Update Engine

Purpose
-------
Monitor authoritative regulatory source pages/documents, detect source changes,
identify which stored FoodReg ingredients appear in the changed material, and
create an auditable re-verification queue.

Important design rule
---------------------
A changed official source is NOT automatically converted into a new legal
status. FoodReg AI records the change and queues it for human verification.
This prevents source-layout changes, OCR/text extraction mistakes, or unrelated
notifications from silently changing legal conclusions.

No third-party HTTP dependency is required; urllib is used for downloads.
"""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "foodreg.db"

USER_AGENT = (
    "FoodReg-AI-Regulatory-Monitor/1.0 "
    "(+official-source-monitor; contact=local-project)"
)
MAX_DOWNLOAD_BYTES = 12 * 1024 * 1024
DEFAULT_TIMEOUT = 25


SOURCE_REGISTRY: list[dict] = [
    {
        "source_key": "india_fssai_notifications",
        "jurisdiction": "India",
        "authority": "Food Safety and Standards Authority of India (FSSAI)",
        "title": "FSSAI Food Laws and Notifications",
        "url": "https://www.fssai.gov.in/notifications.php",
        "source_type": "official_notifications",
        "parser": "html",
        "priority": "high",
        "notes": "Official notification/archive page; changes should be reviewed for additive and food-rule relevance.",
    },
    {
        "source_key": "us_fda_color_additives",
        "jurisdiction": "United States",
        "authority": "U.S. Food and Drug Administration (FDA)",
        "title": "Regulatory Status of Color Additives",
        "url": "https://www.hfpappexternal.fda.gov/scripts/fdcc/?set=ColorAdditives",
        "source_type": "official_database",
        "parser": "html",
        "priority": "high",
        "notes": "Official FDA color-additive status database; covers colors, not every food additive.",
    },
    {
        "source_key": "eu_food_additives_1333_2008",
        "jurisdiction": "European Union",
        "authority": "EUR-Lex / European Union",
        "title": "Regulation (EC) No 1333/2008 on food additives",
        "url": "https://eur-lex.europa.eu/legal-content/EN/ALL/?uri=celex:32008R1333",
        "source_type": "official_legislation",
        "parser": "html",
        "priority": "high",
        "notes": "Official EU legal text/consolidated legislation; monitor for consolidated-version changes.",
    },
    {
        "source_key": "canada_permitted_food_additives",
        "jurisdiction": "Canada",
        "authority": "Health Canada",
        "title": "Lists of Permitted Food Additives",
        "url": "https://www.canada.ca/en/health-canada/services/food-nutrition/food-safety/food-additives/lists-permitted.html",
        "source_type": "official_database",
        "parser": "html",
        "priority": "high",
        "notes": "Official repository for Canada's permitted food-additive lists.",
    },
    {
        "source_key": "australia_new_zealand_food_standards",
        "jurisdiction": "Australia/New Zealand",
        "authority": "Food Standards Australia New Zealand (FSANZ)",
        "title": "Food Standards Code legislation",
        "url": "https://www.foodstandards.gov.au/food-standards-code/legislation",
        "source_type": "official_legislation",
        "parser": "html",
        "priority": "high",
        "notes": "FSANZ legislation hub; authoritative versions are linked through the Federal Register of Legislation.",
    },
    {
        "source_key": "singapore_sfa_additives",
        "jurisdiction": "Singapore",
        "authority": "Singapore Food Agency (SFA)",
        "title": "Regulatory Limits for Food Additives",
        "url": "https://www.sfa.gov.sg/regulatory-standards-frameworks-guidelines/food-safety-regulatory-limits/regulatory-limits-for-food-additives/",
        "source_type": "official_guidance",
        "parser": "html",
        "priority": "high",
        "notes": "Official SFA additive limits page; SFA also provides an additive search tool.",
    },
    {
        "source_key": "japan_mhlw_food_additives",
        "jurisdiction": "Japan",
        "authority": "Ministry of Health, Labour and Welfare (MHLW)",
        "title": "Food Additives",
        "url": "https://www.mhlw.go.jp/stf/seisakunitsuite/bunya/kenkou_iryou/shokuhin/syokuten/index.html",
        "source_type": "official_regulatory_page",
        "parser": "html",
        "priority": "high",
        "notes": "Official MHLW page describing designated/existing food-additive lists and standards.",
    },
    {
        "source_key": "great_britain_fsa_regulated_products",
        "jurisdiction": "Great Britain",
        "authority": "Food Standards Agency (FSA)",
        "title": "Authorised Regulated Food and Feed Products for Great Britain",
        "url": "https://data.food.gov.uk/regulated-products/food_authorisations/",
        "source_type": "official_database",
        "parser": "html",
        "priority": "high",
        "notes": "Official GB register for regulated-product authorisations including food additives.",
    },
]


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _connect() -> sqlite3.Connection:
    if not DB_PATH.exists():
        raise FileNotFoundError(f"FoodReg database not found: {DB_PATH}")
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def ensure_update_schema() -> None:
    """Create only the updater's own tables; never alter regulatory_records."""
    conn = _connect()
    try:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS regulatory_source_registry (
                source_key TEXT PRIMARY KEY,
                jurisdiction TEXT NOT NULL,
                authority TEXT NOT NULL,
                title TEXT NOT NULL,
                url TEXT NOT NULL,
                source_type TEXT,
                parser TEXT,
                priority TEXT,
                notes TEXT,
                enabled INTEGER NOT NULL DEFAULT 1,
                created_at TEXT,
                updated_at TEXT
            );

            CREATE TABLE IF NOT EXISTS regulatory_source_snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source_key TEXT NOT NULL,
                checked_at TEXT NOT NULL,
                http_status INTEGER,
                content_type TEXT,
                content_length INTEGER,
                etag TEXT,
                last_modified TEXT,
                content_sha256 TEXT,
                title_hint TEXT,
                matched_ingredients TEXT,
                fetch_seconds REAL,
                error TEXT,
                FOREIGN KEY(source_key) REFERENCES regulatory_source_registry(source_key)
            );

            CREATE INDEX IF NOT EXISTS idx_source_snapshots_key_time
                ON regulatory_source_snapshots(source_key, checked_at DESC);

            CREATE TABLE IF NOT EXISTS regulatory_update_runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                started_at TEXT NOT NULL,
                finished_at TEXT,
                sources_checked INTEGER NOT NULL DEFAULT 0,
                sources_changed INTEGER NOT NULL DEFAULT 0,
                errors INTEGER NOT NULL DEFAULT 0,
                notes TEXT
            );

            CREATE TABLE IF NOT EXISTS regulatory_change_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source_key TEXT NOT NULL,
                detected_at TEXT NOT NULL,
                jurisdiction TEXT,
                event_type TEXT NOT NULL,
                previous_sha256 TEXT,
                current_sha256 TEXT,
                matched_ingredients TEXT,
                status TEXT NOT NULL DEFAULT 'PENDING_REVIEW',
                reviewer TEXT,
                reviewed_at TEXT,
                reviewer_note TEXT,
                FOREIGN KEY(source_key) REFERENCES regulatory_source_registry(source_key)
            );

            CREATE INDEX IF NOT EXISTS idx_change_events_status
                ON regulatory_change_events(status, detected_at DESC);
            """
        )

        now = _utc_now()
        for source in SOURCE_REGISTRY:
            conn.execute(
                """
                INSERT INTO regulatory_source_registry
                (source_key,jurisdiction,authority,title,url,source_type,parser,priority,notes,enabled,created_at,updated_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(source_key) DO UPDATE SET
                    jurisdiction=excluded.jurisdiction,
                    authority=excluded.authority,
                    title=excluded.title,
                    url=excluded.url,
                    source_type=excluded.source_type,
                    parser=excluded.parser,
                    priority=excluded.priority,
                    notes=excluded.notes,
                    updated_at=excluded.updated_at
                """,
                (
                    source["source_key"], source["jurisdiction"], source["authority"],
                    source["title"], source["url"], source["source_type"],
                    source["parser"], source["priority"], source["notes"], 1,
                    now, now,
                ),
            )
        conn.commit()
    finally:
        conn.close()


def _normalise_text(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip().lower()


def _extract_text(content: bytes, content_type: str, url: str) -> str:
    """Best-effort text extraction. Hashing still works if extraction is poor."""
    ctype = (content_type or "").lower()
    is_pdf = "pdf" in ctype or url.lower().split("?", 1)[0].endswith(".pdf")

    if is_pdf:
        try:
            from pypdf import PdfReader  # optional, lightweight if already installed
            import io
            reader = PdfReader(io.BytesIO(content))
            return "\n".join((page.extract_text() or "") for page in reader.pages)
        except Exception:
            # Do not fail a source check just because PDF text extraction is unavailable.
            return ""

    for encoding in ("utf-8", "utf-8-sig", "latin-1"):
        try:
            return content.decode(encoding, errors="ignore")
        except Exception:
            continue
    return ""


def _strip_html(text: str) -> str:
    text = re.sub(r"(?is)<script.*?</script>", " ", text)
    text = re.sub(r"(?is)<style.*?</style>", " ", text)
    text = re.sub(r"(?s)<[^>]+>", " ", text)
    text = re.sub(r"&nbsp;", " ", text, flags=re.I)
    text = re.sub(r"&amp;", "&", text, flags=re.I)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _source_title(text: str) -> str:
    m = re.search(r"<title[^>]*>(.*?)</title>", text or "", flags=re.I | re.S)
    if m:
        return _strip_html(m.group(1))[:300]
    return ""


def _load_db_ingredients(conn: sqlite3.Connection) -> list[tuple[str, str]]:
    try:
        rows = conn.execute(
            "SELECT canonical_name, COALESCE(ins_code,'') FROM ingredients"
        ).fetchall()
    except sqlite3.Error:
        return []
    return [(str(r[0] or "").strip(), str(r[1] or "").strip()) for r in rows if r[0]]


def _match_known_ingredients(text: str, conn: sqlite3.Connection) -> list[str]:
    """Find stored ingredients/INS codes mentioned in the changed source."""
    normal = _normalise_text(_strip_html(text))
    found: list[str] = []
    for canonical, ins in _load_db_ingredients(conn):
        c = canonical.lower()
        if len(c) >= 4 and c in normal:
            found.append(canonical)
            continue
        if ins and re.search(rf"\b(?:ins|e)?\s*{re.escape(ins.lower())}\b", normal):
            found.append(canonical)
    return sorted(set(found), key=str.lower)


def fetch_source(url: str, timeout: int = DEFAULT_TIMEOUT) -> dict:
    """Fetch an official source with conditional headers when possible."""
    started = time.perf_counter()
    request = Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,application/pdf;q=0.9,*/*;q=0.8",
        },
    )
    try:
        with urlopen(request, timeout=timeout) as response:
            chunks = []
            total = 0
            while True:
                chunk = response.read(1024 * 1024)
                if not chunk:
                    break
                total += len(chunk)
                if total > MAX_DOWNLOAD_BYTES:
                    raise ValueError(f"Source exceeded {MAX_DOWNLOAD_BYTES // (1024*1024)} MB limit")
                chunks.append(chunk)

            body = b"".join(chunks)
            headers = response.headers
            return {
                "ok": True,
                "status": int(getattr(response, "status", 200) or 200),
                "content": body,
                "content_type": headers.get("Content-Type", ""),
                "etag": headers.get("ETag", ""),
                "last_modified": headers.get("Last-Modified", ""),
                "seconds": round(time.perf_counter() - started, 3),
                "error": "",
            }
    except (HTTPError, URLError, TimeoutError, ValueError, OSError) as exc:
        return {
            "ok": False,
            "status": getattr(exc, "code", None),
            "content": b"",
            "content_type": "",
            "etag": "",
            "last_modified": "",
            "seconds": round(time.perf_counter() - started, 3),
            "error": str(exc),
        }


def _latest_snapshot(conn: sqlite3.Connection, source_key: str):
    return conn.execute(
        """
        SELECT * FROM regulatory_source_snapshots
        WHERE source_key=?
        ORDER BY id DESC LIMIT 1
        """,
        (source_key,),
    ).fetchone()


def run_source_monitor(source_keys: Iterable[str] | None = None) -> dict:
    """
    Check configured official sources and record source changes.

    Returns a summary dict suitable for Streamlit and automation logs.
    """
    ensure_update_schema()
    keys = set(source_keys or [s["source_key"] for s in SOURCE_REGISTRY])
    started = _utc_now()
    conn = _connect()
    checked = 0
    changed = 0
    errors = 0
    results: list[dict] = []
    try:
        for source in SOURCE_REGISTRY:
            if source["source_key"] not in keys:
                continue
            checked += 1
            url = source["url"]
            fetched = fetch_source(url)
            sha = hashlib.sha256(fetched["content"]).hexdigest() if fetched["ok"] else ""
            latest = _latest_snapshot(conn, source["source_key"])
            previous_sha = str(latest["content_sha256"] or "") if latest else ""
            source_text = _extract_text(fetched["content"], fetched["content_type"], url) if fetched["ok"] else ""
            title_hint = _source_title(source_text) if fetched["ok"] else source["title"]
            matched = _match_known_ingredients(source_text, conn) if source_text else []

            conn.execute(
                """
                INSERT INTO regulatory_source_snapshots
                (source_key,checked_at,http_status,content_type,content_length,etag,last_modified,content_sha256,title_hint,matched_ingredients,fetch_seconds,error)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    source["source_key"], _utc_now(), fetched["status"], fetched["content_type"],
                    len(fetched["content"]), fetched["etag"], fetched["last_modified"], sha,
                    title_hint, json.dumps(matched, ensure_ascii=False), fetched["seconds"], fetched["error"],
                ),
            )

            is_changed = bool(fetched["ok"] and previous_sha and sha and previous_sha != sha)
            is_first = bool(fetched["ok"] and not previous_sha and sha)

            if is_changed:
                changed += 1
                # Avoid creating duplicate pending events for the exact same transition.
                existing = conn.execute(
                    """
                    SELECT 1 FROM regulatory_change_events
                    WHERE source_key=? AND previous_sha256=? AND current_sha256=?
                    LIMIT 1
                    """,
                    (source["source_key"], previous_sha, sha),
                ).fetchone()
                if existing is None:
                    conn.execute(
                        """
                        INSERT INTO regulatory_change_events
                        (source_key,detected_at,jurisdiction,event_type,previous_sha256,current_sha256,matched_ingredients,status)
                        VALUES (?,?,?,?,?,?,?, 'PENDING_REVIEW')
                        """,
                        (
                            source["source_key"], _utc_now(), source["jurisdiction"], "SOURCE_CHANGED",
                            previous_sha, sha, json.dumps(matched, ensure_ascii=False),
                        ),
                    )

            if not fetched["ok"]:
                errors += 1

            results.append({
                "source_key": source["source_key"],
                "jurisdiction": source["jurisdiction"],
                "authority": source["authority"],
                "title": source["title"],
                "url": url,
                "status": "CHANGED" if is_changed else "INITIAL SNAPSHOT" if is_first else "UNCHANGED" if fetched["ok"] else "ERROR",
                "http_status": fetched["status"],
                "sha256": sha,
                "previous_sha256": previous_sha,
                "matched_ingredients": matched,
                "error": fetched["error"],
            })

        finished = _utc_now()
        conn.execute(
            """
            INSERT INTO regulatory_update_runs
            (started_at,finished_at,sources_checked,sources_changed,errors,notes)
            VALUES (?,?,?,?,?,?)
            """,
            (
                started, finished, checked, changed, errors,
                "Source monitor only. Status changes require human verification before regulatory_records are edited.",
            ),
        )
        conn.commit()
    finally:
        conn.close()

    return {
        "started_at": started,
        "finished_at": _utc_now(),
        "sources_checked": checked,
        "sources_changed": changed,
        "errors": errors,
        "results": results,
    }


def get_update_dashboard(limit_events: int = 100) -> dict:
    ensure_update_schema()
    conn = _connect()
    try:
        run = conn.execute(
            "SELECT * FROM regulatory_update_runs ORDER BY id DESC LIMIT 1"
        ).fetchone()
        pending = conn.execute(
            "SELECT COUNT(*) AS n FROM regulatory_change_events WHERE status='PENDING_REVIEW'"
        ).fetchone()["n"]
        events = conn.execute(
            """
            SELECT e.*, r.title, r.url, r.authority, r.jurisdiction
            FROM regulatory_change_events e
            JOIN regulatory_source_registry r ON r.source_key=e.source_key
            ORDER BY e.detected_at DESC
            LIMIT ?
            """,
            (limit_events,),
        ).fetchall()
        sources = conn.execute(
            """
            SELECT r.*, s.checked_at, s.http_status, s.content_sha256, s.error
            FROM regulatory_source_registry r
            LEFT JOIN regulatory_source_snapshots s
              ON s.id = (
                    SELECT s2.id FROM regulatory_source_snapshots s2
                    WHERE s2.source_key=r.source_key
                    ORDER BY s2.id DESC LIMIT 1
              )
            WHERE r.enabled=1
            ORDER BY CASE r.priority WHEN 'high' THEN 1 WHEN 'medium' THEN 2 ELSE 3 END, r.jurisdiction
            """
        ).fetchall()
        return {
            "last_run": dict(run) if run else None,
            "pending_changes": int(pending or 0),
            "events": [dict(x) for x in events],
            "sources": [dict(x) for x in sources],
        }
    finally:
        conn.close()


def review_change_event(event_id: int, status: str, reviewer: str = "local-review", note: str = "") -> None:
    """Mark a source-change event reviewed; does not edit regulatory_records."""
    status = status.upper().strip()
    allowed = {"PENDING_REVIEW", "REVIEWED", "DISMISSED"}
    if status not in allowed:
        raise ValueError(f"Invalid status: {status}")
    ensure_update_schema()
    conn = _connect()
    try:
        conn.execute(
            """
            UPDATE regulatory_change_events
            SET status=?, reviewer=?, reviewed_at=?, reviewer_note=?
            WHERE id=?
            """,
            (status, reviewer, _utc_now(), note.strip(), int(event_id)),
        )
        conn.commit()
    finally:
        conn.close()


def build_update_audit_csv(dashboard: dict) -> str:
    import csv
    import io
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow([
        "event_id", "detected_at", "jurisdiction", "authority", "source",
        "event_type", "status", "matched_ingredients", "source_url",
    ])
    for event in dashboard.get("events", []):
        try:
            matched = ", ".join(json.loads(event.get("matched_ingredients") or "[]"))
        except Exception:
            matched = str(event.get("matched_ingredients") or "")
        writer.writerow([
            event.get("id", ""), event.get("detected_at", ""), event.get("jurisdiction", ""),
            event.get("authority", ""), event.get("title", ""), event.get("event_type", ""),
            event.get("status", ""), matched, event.get("url", ""),
        ])
    return out.getvalue()


def get_source_registry() -> list[dict]:
    return [dict(x) for x in SOURCE_REGISTRY]


if __name__ == "__main__":
    result = run_source_monitor()
    print(json.dumps({k: result[k] for k in ("started_at", "finished_at", "sources_checked", "sources_changed", "errors")}, indent=2))
    dash = get_update_dashboard()
    print(f"Pending source changes: {dash['pending_changes']}")
    for row in result["results"]:
        print(f"{row['jurisdiction']}: {row['status']} — {row['url']}")
