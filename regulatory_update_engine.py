"""FoodReg AI regulatory updater, version 18.

Design:
1) Monitor official source pages/documents with conditional HTTP requests and
   semantic content hashing.
2) Create auditable change events and regulatory proposals instead of silently
   editing legal records.
3) Allow a human reviewer to approve/reject proposals. Approval creates a
   version record and then updates/creates the corresponding regulatory record.
4) Accept official PDF/HTML/TXT material through the document-intelligence
   helper and put extracted proposals into the same review queue.
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
USER_AGENT = "FoodReg-AI-Regulatory-Monitor/2.0 (local-audit-engine)"
MAX_DOWNLOAD_BYTES = 12 * 1024 * 1024
DEFAULT_REQUEST_TIMEOUT = 25

SOURCE_REGISTRY: list[dict] = [
    {"source_key":"india_fssai_notifications","jurisdiction":"India","authority":"Food Safety and Standards Authority of India (FSSAI)","title":"FSSAI Food Laws and Notifications","url":"https://www.fssai.gov.in/notifications.php","source_type":"official_notifications","parser":"html","priority":"high","notes":"Official notification/archive page; additive and food-rule relevance requires review."},
    {"source_key":"us_fda_color_additives","jurisdiction":"United States","authority":"U.S. Food and Drug Administration (FDA)","title":"Regulatory Status of Color Additives","url":"https://www.hfpappexternal.fda.gov/scripts/fdcc/?set=ColorAdditives","source_type":"official_database","parser":"html","priority":"high","notes":"Official FDA color-additive status database; not a complete list of all food additives."},
    {"source_key":"eu_food_additives_1333_2008","jurisdiction":"European Union","authority":"EUR-Lex / European Union","title":"Regulation (EC) No 1333/2008 on food additives","url":"https://eur-lex.europa.eu/legal-content/EN/ALL/?uri=celex:32008R1333","source_type":"official_legislation","parser":"html","priority":"high","notes":"Official EU legal text/consolidated legislation."},
    {"source_key":"canada_permitted_food_additives","jurisdiction":"Canada","authority":"Health Canada","title":"Lists of Permitted Food Additives","url":"https://www.canada.ca/en/health-canada/services/food-nutrition/food-safety/food-additives/lists-permitted.html","source_type":"official_database","parser":"html","priority":"high","notes":"Official repository for Canada's permitted food-additive lists."},
    {"source_key":"australia_new_zealand_food_standards","jurisdiction":"Australia/New Zealand","authority":"Food Standards Australia New Zealand (FSANZ)","title":"Food Standards Code legislation","url":"https://www.foodstandards.gov.au/food-standards-code/legislation","source_type":"official_legislation","parser":"html","priority":"high","notes":"FSANZ legislation hub."},
    {"source_key":"singapore_sfa_additives","jurisdiction":"Singapore","authority":"Singapore Food Agency (SFA)","title":"Regulatory Limits for Food Additives","url":"https://www.sfa.gov.sg/regulatory-standards-frameworks-guidelines/food-safety-regulatory-limits/regulatory-limits-for-food-additives/","source_type":"official_guidance","parser":"html","priority":"high","notes":"Official SFA additive limits page."},
    {"source_key":"japan_mhlw_food_additives","jurisdiction":"Japan","authority":"Ministry of Health, Labour and Welfare (MHLW)","title":"Food Additives","url":"https://www.mhlw.go.jp/stf/seisakunitsuite/bunya/kenkou_iryou/shokuhin/syokuten/index.html","source_type":"official_regulatory_page","parser":"html","priority":"high","notes":"Official MHLW food-additive information page."},
    {"source_key":"great_britain_fsa_regulated_products","jurisdiction":"Great Britain","authority":"Food Standards Agency (FSA)","title":"Authorised Regulated Food and Feed Products for Great Britain","url":"https://data.food.gov.uk/regulated-products/food_authorisations/","source_type":"official_database","parser":"html","priority":"high","notes":"Official GB regulated-product register."},
]


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    return conn


def _ensure_column(conn: sqlite3.Connection, table: str, column: str, ddl: str) -> None:
    cols = {r[1] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()}
    if column not in cols:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}")


def ensure_update_schema() -> None:
    conn = _connect()
    try:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS regulatory_source_registry (
                source_key TEXT PRIMARY KEY, jurisdiction TEXT NOT NULL, authority TEXT NOT NULL,
                title TEXT NOT NULL, url TEXT NOT NULL, source_type TEXT, parser TEXT,
                priority TEXT, notes TEXT, enabled INTEGER NOT NULL DEFAULT 1, created_at TEXT, updated_at TEXT
            );
            CREATE TABLE IF NOT EXISTS regulatory_source_snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT, source_key TEXT NOT NULL, checked_at TEXT NOT NULL,
                http_status INTEGER, content_type TEXT, content_length INTEGER, etag TEXT, last_modified TEXT,
                content_sha256 TEXT, semantic_sha256 TEXT, title_hint TEXT, matched_ingredients TEXT,
                fetch_seconds REAL, error TEXT, content_excerpt TEXT,
                FOREIGN KEY(source_key) REFERENCES regulatory_source_registry(source_key)
            );
            CREATE INDEX IF NOT EXISTS idx_source_snapshots_key_time ON regulatory_source_snapshots(source_key, checked_at DESC);
            CREATE TABLE IF NOT EXISTS regulatory_update_runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT, started_at TEXT NOT NULL, finished_at TEXT,
                sources_checked INTEGER NOT NULL DEFAULT 0, sources_changed INTEGER NOT NULL DEFAULT 0,
                errors INTEGER NOT NULL DEFAULT 0, notes TEXT
            );
            CREATE TABLE IF NOT EXISTS regulatory_change_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT, source_key TEXT NOT NULL, detected_at TEXT NOT NULL,
                jurisdiction TEXT, event_type TEXT NOT NULL, previous_sha256 TEXT, current_sha256 TEXT,
                matched_ingredients TEXT, status TEXT NOT NULL DEFAULT 'PENDING_REVIEW', reviewer TEXT,
                reviewed_at TEXT, reviewer_note TEXT, FOREIGN KEY(source_key) REFERENCES regulatory_source_registry(source_key)
            );
            CREATE INDEX IF NOT EXISTS idx_change_events_status ON regulatory_change_events(status, detected_at DESC);
            CREATE TABLE IF NOT EXISTS regulatory_document_proposals (
                id INTEGER PRIMARY KEY AUTOINCREMENT, source_event_id INTEGER, jurisdiction TEXT NOT NULL,
                authority TEXT, ingredient_id INTEGER, ingredient_name TEXT NOT NULL, status TEXT NOT NULL,
                label TEXT, restriction TEXT, reason TEXT, food_category TEXT, maximum_level TEXT, unit TEXT,
                conditions TEXT, source_url TEXT, source_document TEXT, effective_date TEXT, confidence REAL,
                evidence_excerpt TEXT, proposal_state TEXT NOT NULL DEFAULT 'PENDING', created_at TEXT NOT NULL,
                reviewed_at TEXT, reviewer TEXT, reviewer_note TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_reg_doc_proposals_state ON regulatory_document_proposals(proposal_state, created_at DESC);
            CREATE TABLE IF NOT EXISTS regulatory_record_versions (
                id INTEGER PRIMARY KEY AUTOINCREMENT, regulatory_record_id INTEGER, ingredient_id INTEGER NOT NULL,
                jurisdiction_id INTEGER NOT NULL, previous_snapshot_json TEXT, new_snapshot_json TEXT NOT NULL,
                changed_at TEXT NOT NULL, reviewer TEXT, change_reason TEXT, proposal_id INTEGER, source_event_id INTEGER
            );
            CREATE INDEX IF NOT EXISTS idx_reg_record_versions_lookup ON regulatory_record_versions(ingredient_id, jurisdiction_id, changed_at DESC);
            """
        )
        # Migrate old V16/V17 source snapshot tables without replacing them.
        _ensure_column(conn, "regulatory_source_snapshots", "semantic_sha256", "TEXT")
        _ensure_column(conn, "regulatory_source_snapshots", "content_excerpt", "TEXT")
        now = _utc_now()
        for s in SOURCE_REGISTRY:
            conn.execute(
                """INSERT INTO regulatory_source_registry
                (source_key,jurisdiction,authority,title,url,source_type,parser,priority,notes,enabled,created_at,updated_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(source_key) DO UPDATE SET
                jurisdiction=excluded.jurisdiction,authority=excluded.authority,title=excluded.title,
                url=excluded.url,source_type=excluded.source_type,parser=excluded.parser,priority=excluded.priority,
                notes=excluded.notes,updated_at=excluded.updated_at""",
                (s["source_key"],s["jurisdiction"],s["authority"],s["title"],s["url"],s["source_type"],s["parser"],s["priority"],s["notes"],1,now,now),
            )
        conn.commit()
    finally:
        conn.close()


def _strip_html(text: str) -> str:
    text = re.sub(r"(?is)<script.*?</script>", " ", text or "")
    text = re.sub(r"(?is)<style.*?</style>", " ", text)
    text = re.sub(r"(?s)<[^>]+>", " ", text)
    text = text.replace("&nbsp;", " ").replace("&amp;", "&")
    return re.sub(r"\s+", " ", text).strip()


def _extract_text(content: bytes, content_type: str, url: str) -> str:
    if "pdf" in (content_type or "").lower() or url.lower().split("?",1)[0].endswith(".pdf"):
        try:
            import fitz
            doc = fitz.open(stream=content, filetype="pdf")
            return "\n".join(page.get_text("text") or "" for page in doc)
        except Exception:
            try:
                from pypdf import PdfReader
                import io
                return "\n".join(p.extract_text() or "" for p in PdfReader(io.BytesIO(content)).pages)
            except Exception:
                return ""
    return content.decode("utf-8", errors="ignore")


def _source_title(text: str) -> str:
    m = re.search(r"<title[^>]*>(.*?)</title>", text or "", flags=re.I|re.S)
    return _strip_html(m.group(1))[:300] if m else ""


def _semantic_text(text: str) -> str:
    clean = _strip_html(text)
    clean = re.sub(r"\b(?:last updated|page last modified|accessed on|updated on)\b[^.]{0,120}", " ", clean, flags=re.I)
    clean = re.sub(r"\b\d{1,2}:\d{2}:\d{2}\b", " ", clean)
    return re.sub(r"\s+", " ", clean).strip().lower()


def _semantic_sha256(text: str) -> str:
    return hashlib.sha256(_semantic_text(text).encode("utf-8", errors="ignore")).hexdigest()


def _load_db_ingredients(conn: sqlite3.Connection) -> list[dict]:
    rows = conn.execute("SELECT id, canonical_name, COALESCE(ins_code,'') AS ins_code FROM ingredients ORDER BY canonical_name").fetchall()
    out=[]
    for r in rows:
        aliases=[str(a[0] or "") for a in conn.execute("SELECT alias FROM ingredient_aliases WHERE ingredient_id=?", (int(r[0]),)).fetchall()]
        out.append({"id":int(r[0]),"canonical_name":str(r[1] or ""),"ins_code":str(r[2] or ""),"aliases":aliases})
    return out


def _match_known_ingredients(text: str, conn: sqlite3.Connection) -> list[str]:
    lower = _strip_html(text).lower(); found=[]
    for row in _load_db_ingredients(conn):
        terms=[row["canonical_name"], row["ins_code"]] + row["aliases"]
        if any(t and len(t)>=3 and t.lower() in lower for t in terms):
            found.append(row["canonical_name"])
    return sorted(set(found), key=str.lower)


def fetch_source(url: str, timeout: int = DEFAULT_REQUEST_TIMEOUT, etag: str = "", last_modified: str = "") -> dict:
    started=time.perf_counter()
    headers={"User-Agent":USER_AGENT,"Accept":"text/html,application/xhtml+xml,application/pdf;q=0.9,*/*;q=0.8"}
    if etag: headers["If-None-Match"]=etag
    if last_modified: headers["If-Modified-Since"]=last_modified
    try:
        with urlopen(Request(url, headers=headers), timeout=timeout) as response:
            chunks=[]; total=0
            while True:
                chunk=response.read(1024*1024)
                if not chunk: break
                total += len(chunk)
                if total > MAX_DOWNLOAD_BYTES: raise ValueError(f"Source exceeded {MAX_DOWNLOAD_BYTES//(1024*1024)} MB limit")
                chunks.append(chunk)
            body=b"".join(chunks); hdr=response.headers
            return {"ok":True,"not_modified":False,"status":int(getattr(response,"status",200) or 200),"content":body,"content_type":hdr.get("Content-Type",""),"etag":hdr.get("ETag","") or etag,"last_modified":hdr.get("Last-Modified","") or last_modified,"seconds":round(time.perf_counter()-started,3),"error":""}
    except HTTPError as exc:
        if getattr(exc,"code",None)==304:
            return {"ok":True,"not_modified":True,"status":304,"content":b"","content_type":"","etag":etag,"last_modified":last_modified,"seconds":round(time.perf_counter()-started,3),"error":""}
        return {"ok":False,"not_modified":False,"status":getattr(exc,"code",None),"content":b"","content_type":"","etag":"","last_modified":"","seconds":round(time.perf_counter()-started,3),"error":str(exc)}
    except (URLError,TimeoutError,ValueError,OSError) as exc:
        return {"ok":False,"not_modified":False,"status":None,"content":b"","content_type":"","etag":"","last_modified":"","seconds":round(time.perf_counter()-started,3),"error":str(exc)}


def _latest_snapshot(conn, source_key: str):
    return conn.execute("SELECT * FROM regulatory_source_snapshots WHERE source_key=? ORDER BY id DESC LIMIT 1", (source_key,)).fetchone()


def propose_document_changes(text: str, jurisdiction: str, authority: str, source_url: str = "", source_document: str = "", source_event_id: int | None = None) -> list[dict]:
    from regulatory_document_intelligence import extract_regulatory_proposals
    ensure_update_schema(); conn=_connect()
    try:
        proposals=extract_regulatory_proposals(text, _load_db_ingredients(conn), jurisdiction, authority, source_url, source_document)
        created=[]
        for p in proposals:
            ing=conn.execute("SELECT id FROM ingredients WHERE lower(canonical_name)=lower(?) LIMIT 1", (p["ingredient_name"],)).fetchone()
            if not ing: continue
            cur=conn.execute("""INSERT INTO regulatory_document_proposals
                (source_event_id,jurisdiction,authority,ingredient_id,ingredient_name,status,label,restriction,reason,food_category,maximum_level,unit,conditions,source_url,source_document,effective_date,confidence,evidence_excerpt,proposal_state,created_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,'PENDING',?)""", (
                source_event_id,p["jurisdiction"],p["authority"],int(ing[0]),p["ingredient_name"],p["status"],p.get("label",""),p.get("restriction",""),p.get("reason",""),p.get("food_category",""),p.get("maximum_level",""),p.get("unit",""),p.get("conditions",""),p.get("source_url",""),p.get("source_document",""),p.get("effective_date",""),float(p.get("confidence",0)),p.get("evidence_excerpt",""),_utc_now()))
            d=dict(p); d.update({"id":int(cur.lastrowid),"proposal_state":"PENDING","ingredient_id":int(ing[0]),"source_event_id":source_event_id}); created.append(d)
        conn.commit(); return created
    finally: conn.close()


def run_source_monitor(source_keys: Iterable[str] | None = None) -> dict:
    ensure_update_schema(); keys=set(source_keys or [s["source_key"] for s in SOURCE_REGISTRY])
    started=_utc_now(); checked=changed=errors=not_modified=0; results=[]; conn=_connect()
    try:
        for source in SOURCE_REGISTRY:
            if source["source_key"] not in keys: continue
            checked += 1; latest=_latest_snapshot(conn, source["source_key"])
            etag=str(latest["etag"] or "") if latest else ""; lm=str(latest["last_modified"] or "") if latest else ""
            fetched=fetch_source(source["url"], etag=etag, last_modified=lm)
            if fetched["not_modified"] and latest:
                not_modified += 1
                results.append({"source_key":source["source_key"],"jurisdiction":source["jurisdiction"],"authority":source["authority"],"title":source["title"],"url":source["url"],"status":"NOT MODIFIED","http_status":304,"sha256":latest["content_sha256"],"previous_sha256":latest["content_sha256"],"semantic_sha256":latest["semantic_sha256"] or latest["content_sha256"],"matched_ingredients":json.loads(latest["matched_ingredients"] or "[]"),"proposal_count":0,"error":""})
                continue
            if fetched["ok"]:
                raw_sha=hashlib.sha256(fetched["content"]).hexdigest(); text=_extract_text(fetched["content"],fetched["content_type"],source["url"]); sem_sha=_semantic_sha256(text); title=_source_title(text) or source["title"]; matched=_match_known_ingredients(text,conn)
            else:
                raw_sha=sem_sha=text=title=""; matched=[]
            prev_raw=str(latest["content_sha256"] or "") if latest else ""; prev_sem=str(latest["semantic_sha256"] or prev_raw) if latest else ""
            is_first=bool(fetched["ok"] and not prev_raw and raw_sha); is_changed=bool(fetched["ok"] and prev_sem and sem_sha and prev_sem!=sem_sha)
            conn.execute("""INSERT INTO regulatory_source_snapshots
                (source_key,checked_at,http_status,content_type,content_length,etag,last_modified,content_sha256,semantic_sha256,title_hint,matched_ingredients,fetch_seconds,error,content_excerpt)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", (source["source_key"],_utc_now(),fetched["status"],fetched["content_type"],len(fetched["content"]),fetched["etag"],fetched["last_modified"],raw_sha,sem_sha,title,json.dumps(matched,ensure_ascii=False),fetched["seconds"],fetched["error"],_strip_html(text)[:1400] if text else ""))
            proposal_count=0; event_id=None
            if is_changed:
                changed += 1
                existing=conn.execute("SELECT id FROM regulatory_change_events WHERE source_key=? AND previous_sha256=? AND current_sha256=? LIMIT 1",(source["source_key"],prev_raw,raw_sha)).fetchone()
                if not existing:
                    event_id=conn.execute("INSERT INTO regulatory_change_events (source_key,detected_at,jurisdiction,event_type,previous_sha256,current_sha256,matched_ingredients,status) VALUES (?,?,?,?,?,?,?,'PENDING_REVIEW')",(source["source_key"],_utc_now(),source["jurisdiction"],"SOURCE_CHANGED",prev_raw,raw_sha,json.dumps(matched,ensure_ascii=False))).lastrowid
                    try: proposal_count=len(propose_document_changes(text,source["jurisdiction"],source["authority"],source["url"],source["title"],event_id))
                    except Exception: proposal_count=0
            if not fetched["ok"]: errors += 1
            results.append({"source_key":source["source_key"],"jurisdiction":source["jurisdiction"],"authority":source["authority"],"title":source["title"],"url":source["url"],"status":"CHANGED" if is_changed else "INITIAL SNAPSHOT" if is_first else "UNCHANGED" if fetched["ok"] else "ERROR","http_status":fetched["status"],"sha256":raw_sha,"previous_sha256":prev_raw,"semantic_sha256":sem_sha,"matched_ingredients":matched,"proposal_count":proposal_count,"error":fetched["error"]})
        finished=_utc_now(); conn.execute("INSERT INTO regulatory_update_runs (started_at,finished_at,sources_checked,sources_changed,errors,notes) VALUES (?,?,?,?,?,?)",(started,finished,checked,changed,errors,"Conditional official-source monitoring; changes create proposals and require human approval.")); conn.commit()
    finally: conn.close()
    return {"started_at":started,"finished_at":_utc_now(),"sources_checked":checked,"sources_changed":changed,"errors":errors,"not_modified":not_modified,"results":results}


def get_update_dashboard(limit_events: int = 100) -> dict:
    ensure_update_schema(); conn=_connect()
    try:
        run=conn.execute("SELECT * FROM regulatory_update_runs ORDER BY id DESC LIMIT 1").fetchone()
        pending=conn.execute("SELECT COUNT(*) AS n FROM regulatory_change_events WHERE status='PENDING_REVIEW'").fetchone()["n"]
        proposals=conn.execute("SELECT COUNT(*) AS n FROM regulatory_document_proposals WHERE proposal_state='PENDING'").fetchone()["n"]
        events=conn.execute("""SELECT e.*,r.title,r.url,r.authority,r.jurisdiction FROM regulatory_change_events e JOIN regulatory_source_registry r ON r.source_key=e.source_key ORDER BY e.detected_at DESC LIMIT ?""",(int(limit_events),)).fetchall()
        sources=conn.execute("""SELECT r.*,s.checked_at,s.http_status,s.content_sha256,s.semantic_sha256,s.error FROM regulatory_source_registry r LEFT JOIN regulatory_source_snapshots s ON s.id=(SELECT s2.id FROM regulatory_source_snapshots s2 WHERE s2.source_key=r.source_key ORDER BY s2.id DESC LIMIT 1) WHERE r.enabled=1 ORDER BY r.jurisdiction""").fetchall()
        rows=conn.execute("SELECT * FROM regulatory_document_proposals ORDER BY created_at DESC LIMIT ?",(int(limit_events),)).fetchall()
        return {"last_run":dict(run) if run else None,"pending_changes":int(pending or 0),"pending_proposals":int(proposals or 0),"events":[dict(x) for x in events],"sources":[dict(x) for x in sources],"proposals":[dict(x) for x in rows]}
    finally: conn.close()


def _snapshot_record(row):
    return dict(row) if row else None


def _find_jurisdiction_id(conn, name: str) -> int:
    row=conn.execute("SELECT id FROM jurisdictions WHERE lower(name)=lower(?) LIMIT 1",(name,)).fetchone()
    if not row: raise ValueError(f"Jurisdiction not found in database: {name}")
    return int(row[0])


def approve_proposal(proposal_id: int, reviewer: str = "local-review", note: str = "") -> dict:
    ensure_update_schema(); conn=_connect()
    try:
        p=conn.execute("SELECT * FROM regulatory_document_proposals WHERE id=?",(int(proposal_id),)).fetchone()
        if not p: raise ValueError("Proposal not found")
        p=dict(p)
        if p["proposal_state"] != "PENDING": raise ValueError("Proposal is no longer pending")
        ingredient_id=int(p["ingredient_id"]); jurisdiction_id=_find_jurisdiction_id(conn,p["jurisdiction"])
        previous=_snapshot_record(conn.execute("SELECT * FROM regulatory_records WHERE ingredient_id=? AND jurisdiction_id=? LIMIT 1",(ingredient_id,jurisdiction_id)).fetchone())
        payload=(p["status"],p.get("label") or "",p.get("restriction") or "",p.get("reason") or "",p.get("food_category") or "",p.get("maximum_level") or "",p.get("unit") or "",p.get("conditions") or "",p.get("authority") or "",p.get("source_url") or "",p.get("source_document") or "",p.get("effective_date") or "",_utc_now(),"official_document_review")
        if previous:
            conn.execute("""UPDATE regulatory_records SET status=?,label=?,restriction=?,reason=?,food_category=?,maximum_level=?,unit=?,conditions=?,authority=?,source_url=?,source_document=?,effective_date=?,verified_date=?,source_type=? WHERE id=?""",payload+(int(previous["id"]),))
            record_id=int(previous["id"])
        else:
            record_id=conn.execute("""INSERT INTO regulatory_records (ingredient_id,jurisdiction_id,status,label,restriction,reason,food_category,maximum_level,unit,conditions,authority,source_url,source_document,effective_date,verified_date,source_type) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",(ingredient_id,jurisdiction_id)+payload).lastrowid
        current=_snapshot_record(conn.execute("SELECT * FROM regulatory_records WHERE id=?",(record_id,)).fetchone())
        conn.execute("INSERT INTO regulatory_record_versions (regulatory_record_id,ingredient_id,jurisdiction_id,previous_snapshot_json,new_snapshot_json,changed_at,reviewer,change_reason,proposal_id,source_event_id) VALUES (?,?,?,?,?,?,?,?,?,?)",(record_id,ingredient_id,jurisdiction_id,json.dumps(previous,ensure_ascii=False) if previous else "",json.dumps(current,ensure_ascii=False),_utc_now(),reviewer,note or "Approved regulatory proposal",int(proposal_id),p.get("source_event_id")))
        conn.execute("UPDATE regulatory_document_proposals SET proposal_state='APPROVED',reviewed_at=?,reviewer=?,reviewer_note=? WHERE id=?",(_utc_now(),reviewer,note,int(proposal_id)))
        if p.get("source_event_id"):
            remaining=conn.execute("SELECT COUNT(*) AS n FROM regulatory_document_proposals WHERE source_event_id=? AND proposal_state='PENDING'",(int(p["source_event_id"]),)).fetchone()["n"]
            if int(remaining or 0)==0:
                conn.execute("UPDATE regulatory_change_events SET status='REVIEWED',reviewer=?,reviewed_at=?,reviewer_note=? WHERE id=?",(reviewer,_utc_now(),note or "All linked proposals reviewed",int(p["source_event_id"])))
        conn.commit(); return {"ok":True,"record_id":record_id,"proposal_id":int(proposal_id)}
    finally: conn.close()


def reject_proposal(proposal_id: int, reviewer: str = "local-review", note: str = "") -> None:
    ensure_update_schema(); conn=_connect()
    try:
        conn.execute("UPDATE regulatory_document_proposals SET proposal_state='REJECTED',reviewed_at=?,reviewer=?,reviewer_note=? WHERE id=? AND proposal_state='PENDING'",(_utc_now(),reviewer,note,int(proposal_id))); conn.commit()
    finally: conn.close()


def review_change_event(event_id: int, status: str, reviewer: str = "local-review", note: str = "") -> None:
    status=status.upper().strip()
    if status not in {"PENDING_REVIEW","REVIEWED","DISMISSED"}: raise ValueError(f"Invalid status: {status}")
    ensure_update_schema(); conn=_connect()
    try:
        conn.execute("UPDATE regulatory_change_events SET status=?,reviewer=?,reviewed_at=?,reviewer_note=? WHERE id=?",(status,reviewer,_utc_now(),note,int(event_id))); conn.commit()
    finally: conn.close()


def build_update_audit_csv(dashboard: dict) -> str:
    import csv,io
    out=io.StringIO(); w=csv.writer(out)
    w.writerow(["event_id","detected_at","jurisdiction","authority","source","event_type","status","matched_ingredients","source_url","proposal_count"])
    counts={}
    for p in dashboard.get("proposals",[]): counts[p.get("source_event_id")]=counts.get(p.get("source_event_id"),0)+1
    for e in dashboard.get("events",[]):
        try: matched=", ".join(json.loads(e.get("matched_ingredients") or "[]"))
        except Exception: matched=str(e.get("matched_ingredients") or "")
        w.writerow([e.get("id",""),e.get("detected_at",""),e.get("jurisdiction",""),e.get("authority",""),e.get("title",""),e.get("event_type",""),e.get("status",""),matched,e.get("url",""),counts.get(e.get("id"),0)])
    return out.getvalue()


def build_proposals_csv(proposals: list[dict]) -> str:
    import csv,io
    out=io.StringIO(); w=csv.writer(out)
    headers=["id","jurisdiction","ingredient_name","status","maximum_level","unit","food_category","conditions","effective_date","confidence","proposal_state","source_document","source_url"]
    w.writerow(headers)
    for p in proposals: w.writerow([p.get(h,"") for h in headers])
    return out.getvalue()


def get_proposal_history(limit: int = 300) -> list[dict]:
    ensure_update_schema(); conn=_connect()
    try: return [dict(r) for r in conn.execute("SELECT * FROM regulatory_document_proposals ORDER BY created_at DESC LIMIT ?",(int(limit),)).fetchall()]
    finally: conn.close()


def get_record_versions(ingredient_id: int | None = None, jurisdiction_id: int | None = None, limit: int = 200) -> list[dict]:
    ensure_update_schema(); conn=_connect()
    try:
        q="SELECT * FROM regulatory_record_versions WHERE 1=1"; args=[]
        if ingredient_id is not None: q += " AND ingredient_id=?"; args.append(int(ingredient_id))
        if jurisdiction_id is not None: q += " AND jurisdiction_id=?"; args.append(int(jurisdiction_id))
        q += " ORDER BY changed_at DESC LIMIT ?"; args.append(int(limit))
        return [dict(r) for r in conn.execute(q,args).fetchall()]
    finally: conn.close()


def get_source_registry() -> list[dict]:
    return [dict(x) for x in SOURCE_REGISTRY]
