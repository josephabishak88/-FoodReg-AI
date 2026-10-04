"""
FoodReg AI - Regulatory Document Intelligence

Extracts candidate regulatory changes from official PDF/HTML/TXT documents.
This module proposes changes; it never changes regulatory_records by itself.
"""
from __future__ import annotations

import io
import re
from datetime import datetime
from pathlib import Path
from typing import Iterable

try:
    from rapidfuzz import fuzz
except Exception:  # optional fallback
    fuzz = None


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


# CPU FINAL: Government-document OCR is intentionally configured for CPU stability.\ndef _extract_paddleocr_text(image_np) -> list[str]:
    """Run the same PaddleOCR result parsing used by the main FoodReg app.

    Supports the current PaddleOCR ``predict`` API and keeps parsing defensive
    because result objects differ slightly between PaddleOCR releases.
    """
    from paddleocr import PaddleOCR

    ocr = PaddleOCR(lang="en", enable_mkldnn=False, device="cpu")
    results = ocr.predict(image_np)
    detected = []

    for result in results or []:
        try:
            data = getattr(result, "json", None)
            data = data() if callable(data) else data
            if not isinstance(data, dict):
                continue
            ocr_data = data.get("res", data)
            if not isinstance(ocr_data, dict):
                continue
            texts = ocr_data.get("rec_texts", [])
            scores = ocr_data.get("rec_scores", [])
            if not isinstance(texts, list):
                continue
            for i, value in enumerate(texts):
                value = str(value or "").strip()
                if not value:
                    continue
                if isinstance(scores, list) and i < len(scores):
                    try:
                        if float(scores[i]) < 0.35:
                            continue
                    except (TypeError, ValueError):
                        pass
                detected.append(value)
        except Exception:
            continue
    return detected


def _ocr_pdf_pages(content: bytes, max_pages: int = 30) -> str:
    """Render scanned PDF pages and OCR them with PaddleOCR.

    Rendering prefers PyMuPDF when installed, but falls back to pypdfium2 so
    scanned government PDFs do not require the optional ``fitz`` package.
    """
    import io as _io
    import numpy as np
    import cv2

    pages = []
    rendered = False

    # Renderer 1: PyMuPDF / fitz (fast when installed).
    try:
        import fitz
        doc = fitz.open(stream=content, filetype="pdf")
        rendered = True
        for i, page in enumerate(doc):
            if i >= max_pages:
                break
            pix = page.get_pixmap(matrix=fitz.Matrix(2.0, 2.0), alpha=False)
            image_np = cv2.imdecode(np.frombuffer(pix.tobytes("png"), dtype=np.uint8), cv2.IMREAD_COLOR)
            if image_np is not None:
                page_text = _extract_paddleocr_text(image_np)
                if page_text:
                    pages.append(" ".join(page_text))
        if pages:
            return "\n".join(pages)
    except Exception:
        pass

    # Renderer 2: pypdfium2 (pip-installable, no Poppler required).
    try:
        import pypdfium2 as pdfium
        pdf = pdfium.PdfDocument(content)
        rendered = True
        for i in range(min(len(pdf), max_pages)):
            page = pdf[i]
            bitmap = page.render(scale=1.5)
            pil_image = bitmap.to_pil().convert("RGB")
            image_np = np.array(pil_image)
            page_text = _extract_paddleocr_text(image_np)
            if page_text:
                pages.append(" ".join(page_text))
            page.close()
        pdf.close()
    except Exception:
        pass

    return "\n".join(pages)


def extract_document_text(content: bytes, filename: str = "", content_type: str = "") -> str:
    name = (filename or "").lower()
    ctype = (content_type or "").lower()
    is_pdf = "pdf" in ctype or name.endswith(".pdf")
    if is_pdf:
        extracted = ""
        # 1) Fast path for text-based PDFs.
        try:
            import fitz
            doc = fitz.open(stream=content, filetype="pdf")
            extracted = "\n".join(page.get_text("text") or "" for page in doc)
        except Exception:
            extracted = ""

        # 2) Secondary text extractor.
        if not extracted.strip():
            try:
                from pypdf import PdfReader
                reader = PdfReader(io.BytesIO(content))
                extracted = "\n".join(page.extract_text() or "" for page in reader.pages)
            except Exception:
                extracted = ""

        # 3) OCR fallback for valid PDFs containing scanned/image-only pages.
        if not extracted.strip():
            try:
                extracted = _ocr_pdf_pages(content, max_pages=18)
            except Exception:
                # Preserve the existing API contract: callers receive an empty
                # string when no extraction backend is available.
                extracted = ""

        return extracted

    try:
        return content.decode("utf-8", errors="ignore")
    except Exception:
        return str(content)


def _strip_markup(text: str) -> str:
    text = re.sub(r"(?is)<script.*?</script>", " ", text or "")
    text = re.sub(r"(?is)<style.*?</style>", " ", text)
    text = re.sub(r"(?s)<[^>]+>", " ", text)
    text = text.replace("&nbsp;", " ")
    return _clean(text)


def _date_candidates(text: str) -> list[str]:
    patterns = [
        r"\b(?:effective|effective from|effective date|comes into force|in force)\s*[:\-]?\s*(\d{1,2}[/-]\d{1,2}[/-]\d{2,4})",
        r"\b(\d{1,2}\s+(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|Sep(?:t(?:ember)?)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)\s+\d{4})\b",
        r"\b((?:19|20)\d{2}-\d{2}-\d{2})\b",
    ]
    out: list[str] = []
    for p in patterns:
        out.extend(m.group(1) for m in re.finditer(p, text, flags=re.I))
    return list(dict.fromkeys(out))[:5]


def _status_from_window(window: str) -> tuple[str, float]:
    w = window.lower()
    if re.search(r"\b(?:banned|prohibited|forbidden|not authorised|not authorized|withdrawn|revoked)\b", w):
        return "BANNED", 0.90
    if re.search(r"\b(?:restricted|restriction|limited use|not permitted except|conditional use)\b", w):
        return "RESTRICTED", 0.82
    if re.search(r"\b(?:authori[sz]ed|permitted|allowed|approved)\b", w):
        if re.search(r"\b(?:conditions?|maximum|only in|subject to|gmp|good manufacturing practice)\b", w):
            return "CHECK_CONDITIONS", 0.78
        return "NO_RESTRICTION", 0.72
    return "CHECK_CONDITIONS", 0.45


def _level_from_window(window: str) -> tuple[str, str]:
    patterns = [
        r"\b(?:maximum|max(?:imum)? level|limit|not exceed|up to)\s*(?:of\s*)?(\d+(?:\.\d+)?)\s*(ppm|mg/kg|mg/l|g/kg|%|mg/100\s?kg)\b",
        r"\b(\d+(?:\.\d+)?)\s*(ppm|mg/kg|mg/l|g/kg|%)\b",
    ]
    for p in patterns:
        m = re.search(p, window, flags=re.I)
        if m:
            return m.group(1), m.group(2)
    return "", ""


def _food_category_from_window(window: str) -> str:
    labels = [
        "beverages", "bakery", "confectionery", "dairy", "meat", "fish", "sauces",
        "snacks", "cereals", "infant food", "processed foods", "food products"
    ]
    found = [x for x in labels if re.search(rf"\b{re.escape(x)}\b", window, flags=re.I)]
    return ", ".join(dict.fromkeys(found))[:200]


def _find_canonical_mentions(text: str, ingredients: Iterable[dict]) -> list[dict]:
    lower = text.lower()
    out = []
    for item in ingredients:
        name = str(item.get("canonical_name") or item.get("name") or "").strip()
        ins = str(item.get("ins_code") or item.get("ins") or "").strip()
        aliases = [str(x).strip() for x in (item.get("aliases") or []) if str(x).strip()]
        candidates = [x for x in [name, ins] + aliases if x]
        best = None
        for term in candidates:
            pos = lower.find(term.lower())
            if pos >= 0:
                best = (pos, term, 1.0)
                break
            if fuzz and len(term) >= 5:
                # Lightweight fuzzy search over nearby words; only used if exact match is absent.
                score = fuzz.partial_ratio(term.lower(), lower)
                if score >= 92:
                    best = (0, term, score / 100.0)
                    break
        if best:
            pos, term, score = best
            out.append({"canonical_name": name, "matched_term": term, "position": pos, "match_confidence": round(score, 3)})
    return out


def extract_regulatory_proposals(text: str, ingredients: Iterable[dict], jurisdiction: str, authority: str, source_url: str = "", source_document: str = "") -> list[dict]:
    clean = _strip_markup(text)
    matches = _find_canonical_mentions(clean, ingredients)
    proposals: list[dict] = []
    for match in matches:
        pos = int(match.get("position", 0))
        start = max(0, pos - 750)
        end = min(len(clean), pos + 1400)
        window = clean[start:end]
        status, status_conf = _status_from_window(window)
        maximum_level, unit = _level_from_window(window)
        food_category = _food_category_from_window(window)
        effective_dates = _date_candidates(window)
        conditions = ""
        m = re.search(r"\b(?:conditions?|subject to|only if|only in|good manufacturing practice|GMP)\b.{0,280}", window, flags=re.I)
        if m:
            conditions = _clean(m.group(0))[:500]
        restriction = ""
        m = re.search(r"\b(?:restricted|prohibited|not permitted|not authorised|not authorized|limited)\b.{0,220}", window, flags=re.I)
        if m:
            restriction = _clean(m.group(0))[:400]
        reason = "Official-document extraction proposal; requires human verification against the legal text and applicable food category/use conditions."
        confidence = min(0.99, round((match.get("match_confidence", 1.0) * 0.55) + (status_conf * 0.45), 3))
        proposals.append({
            "ingredient_name": match["canonical_name"],
            "jurisdiction": jurisdiction,
            "status": status,
            "label": status.replace("_", " ").title(),
            "restriction": restriction,
            "reason": reason,
            "food_category": food_category,
            "maximum_level": maximum_level,
            "unit": unit,
            "conditions": conditions,
            "authority": authority,
            "source_url": source_url,
            "source_document": source_document,
            "effective_date": effective_dates[0] if effective_dates else "",
            "confidence": confidence,
            "evidence_excerpt": window[:1800],
            "matched_term": match.get("matched_term", ""),
        })
    # one proposal per ingredient/jurisdiction/status; keep highest confidence
    unique: dict[tuple[str, str, str], dict] = {}
    for row in proposals:
        key = (row["ingredient_name"].lower(), row["jurisdiction"].lower(), row["status"])
        old = unique.get(key)
        if old is None or float(row.get("confidence", 0)) > float(old.get("confidence", 0)):
            unique[key] = row
    return list(unique.values())
