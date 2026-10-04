import re
import csv
import io
import json
import hashlib
import zipfile
from datetime import datetime
from html import escape
from pathlib import Path

from urllib.parse import urlparse


import cv2

import numpy as np

import streamlit as st

from PIL import Image

from paddleocr import PaddleOCR


from ingredient_normalizer import INGREDIENT_DATABASE, normalize_ingredient
from regulatory_database import check_ingredient

try:
    from regulatory_update_engine import (
        ensure_update_schema,
        get_update_dashboard,
        get_source_registry,
        run_source_monitor,
        review_change_event,
        build_update_audit_csv,
    )
    REGULATORY_UPDATE_ENGINE_READY = True
except Exception:
    REGULATORY_UPDATE_ENGINE_READY = False



# =========================================================
# ORDINARY FOOD INGREDIENT CLASSIFICATION
# =========================================================


ORDINARY_INGREDIENT_PATTERNS = [
    (r"^wheat flour$", "Staple food ingredient"),
    (r"^edible vegetable oil$", "Food ingredient / edible oil"),
    (r"^salt$", "Staple food ingredient"),
    (r"^sugar$", "Food ingredient / sweetener"),
    (r"^edible starch$", "Food ingredient / starch"),
    (r"^wheat gluten$", "Food ingredient / protein"),
    (r"^hydrolysed groundnut protein$", "Food ingredient / protein"),
    (r"^mixed spices.*", "Compound food ingredient / spices"),
]


def classify_ingredient(name: str, ins=None) -> dict[str, str]:
    """Classify ordinary food ingredients without calling them safe."""
    text = str(name or "").strip().lower()

    if ins:
        return {
            "type": "ADDITIVE",
            "label": "Food additive",
            "summary_status": "",
            "explanation": "Regulatory additive records are checked by jurisdiction.",
        }

    for pattern, label in ORDINARY_INGREDIENT_PATTERNS:
        if re.fullmatch(pattern, text, flags=re.IGNORECASE):
            return {
                "type": "ORDINARY_INGREDIENT",
                "label": label,
                "summary_status": "ℹ️ Food ingredient",
                "explanation": (
                    "This is primarily a food/commodity ingredient rather than an additive. "
                    "Product standards, composition rules and labelling requirements may apply."
                ),
            }

    return {
        "type": "UNKNOWN",
        "label": "Unclassified ingredient",
        "summary_status": "",
        "explanation": "No special ingredient-type classification is stored yet.",
    }



# =========================================================
# ALLERGEN + INGREDIENT INSIGHTS
# =========================================================


ALLERGEN_RULES = [
    ("wheat", "Wheat", "Wheat ingredients are present on the label."),
    ("wheat flour", "Wheat", "Wheat flour is present on the label."),
    ("wheat gluten", "Wheat / Gluten", "Wheat gluten is present on the label."),
    ("gluten", "Wheat / Gluten", "Gluten is identified in the ingredient list."),
    ("groundnut", "Groundnut / Peanut", "Groundnut (peanut) protein is present on the label."),
    ("peanut", "Groundnut / Peanut", "Peanut is identified in the ingredient list."),
    ("milk", "Milk", "A milk-derived ingredient is identified on the label."),
    ("casein", "Milk", "Casein is a milk-derived protein."),
    ("whey", "Milk", "Whey is a milk-derived ingredient."),
    ("soy", "Soy", "A soy-derived ingredient is identified on the label."),
    ("soya", "Soy", "A soya-derived ingredient is identified on the label."),
    ("egg", "Egg", "Egg is identified in the ingredient list."),
    ("sesame", "Sesame", "Sesame is identified in the ingredient list."),
    ("mustard", "Mustard", "Mustard is identified in the ingredient list."),
    ("almond", "Tree nuts", "Almond is identified in the ingredient list."),
    ("cashew", "Tree nuts", "Cashew is identified in the ingredient list."),
    ("walnut", "Tree nuts", "Walnut is identified in the ingredient list."),
    ("hazelnut", "Tree nuts", "Hazelnut is identified in the ingredient list."),
]


INGREDIENT_INSIGHTS = {
    "wheat flour": {
        "role": "Main cereal ingredient used to provide structure and bulk.",
        "notes": "Contains wheat proteins and may contain gluten. Its presence is relevant for people avoiding wheat or gluten.",
    },
    "edible vegetable oil": {
        "role": "Provides fat, texture and helps with cooking or frying.",
        "notes": "The exact nutritional profile depends on the specific oil used; the label may not identify the oil type in detail.",
    },
    "salt": {
        "role": "Adds saltiness and can also support flavour and product stability.",
        "notes": "Salt contributes sodium to the diet. The amount in the finished serving depends on the product and portion size.",
    },
    "sugar": {
        "role": "Provides sweetness and can contribute to texture and browning.",
        "notes": "Sugar is a source of carbohydrate and adds to the product's total sugars and energy.",
    },
    "edible starch": {
        "role": "Used for texture, thickening, binding or structure.",
        "notes": "The nutritional effect depends on the starch source and the amount used in the finished food.",
    },
    "wheat gluten": {
        "role": "Wheat protein used to strengthen dough or improve texture.",
        "notes": "Relevant for people who need to avoid wheat or gluten.",
    },
    "hydrolysed groundnut protein": {
        "role": "Protein ingredient processed to break proteins into smaller components and add flavour or protein functionality.",
        "notes": "Groundnut/peanut is an important allergen and should be treated as such when identified on the label.",
    },
    "mixed spices": {
        "role": "Blend of spices used primarily for flavour and aroma.",
        "notes": "The exact composition depends on the listed spice blend. Individual spices may also have separate allergen or labelling requirements in some jurisdictions.",
    },
    "citric acid": {
        "role": "Acidity regulator used to control acidity and provide a sour taste.",
        "notes": "Regulatory use depends on the food category and jurisdiction.",
    },
    "guar gum": {
        "role": "Thickener and stabiliser used to improve texture and consistency.",
        "notes": "Regulatory use depends on the food category and applicable conditions.",
    },
    "potassium chloride": {
        "role": "Mineral salt used for seasoning or as a partial salt substitute in some foods.",
        "notes": "Regulatory use and maximum levels, where applicable, depend on the food category and jurisdiction.",
    },
    "caramel iv": {
        "role": "Food colouring used to give products a brown to dark-brown colour.",
        "notes": "Its permitted uses and conditions vary by jurisdiction and food category.",
    },
    "disodium 5'-ribonucleotides": {
        "role": "Flavour enhancer used to strengthen savoury taste.",
        "notes": "Food-category conditions apply in many regulatory systems; this is not a general health or safety conclusion.",
    },
    "sodium carbonate": {
        "role": "Acidity regulator or raising-agent ingredient used for functional effects in food processing.",
        "notes": "Permitted uses depend on the applicable food category and regulatory conditions.",
    },
}


def detect_allergens(normalized_results: list[dict]) -> list[dict]:
    """Detect likely allergens directly from identified ingredient names."""
    found = {}

    for item in normalized_results:
        canonical = str(item.get("canonical", "")).strip().lower()
        if not canonical:
            continue

        for pattern, allergen, explanation in ALLERGEN_RULES:
            if re.search(r"\b" + re.escape(pattern) + r"\b", canonical, flags=re.IGNORECASE):
                key = allergen.lower()
                found.setdefault(
                    key,
                    {
                        "allergen": allergen,
                        "ingredients": [],
                        "explanation": explanation,
                    },
                )
                display_name = str(item.get("canonical", "")).strip().title()
                if display_name and display_name not in found[key]["ingredients"]:
                    found[key]["ingredients"].append(display_name)

    return list(found.values())


def get_ingredient_insight(canonical: str) -> dict[str, str]:
    """Return neutral, label-focused ingredient information."""
    key = str(canonical or "").strip().lower()

    if key in INGREDIENT_INSIGHTS:
        return INGREDIENT_INSIGHTS[key]

    for known_key, data in INGREDIENT_INSIGHTS.items():
        if known_key == "mixed spices" and key.startswith("mixed spices"):
            return data

    return {
        "role": "Ingredient identified from the product label.",
        "notes": "The label identifies this ingredient, but the current FoodReg AI insight library does not yet contain a specific description for it.",
    }


# =========================================================
# PRESENTATION / AUDIT HELPERS — V8
# =========================================================

def build_country_attention_chart_rows(country_profile_rows: list[dict]) -> list[dict]:
    """Build compact jurisdiction-level attention counts for visualization."""
    rows = []
    for row in country_profile_rows or []:
        rows.append({
            "Country / jurisdiction": row.get("Country", row.get("Jurisdiction", "—")),
            "Prohibited": int(row.get("Prohibited", 0) or 0),
            "Restricted": int(row.get("Restricted", 0) or 0),
            "Conditions": int(row.get("Conditions", row.get("Conditions apply", 0)) or 0),
            "No restriction": int(row.get("No restriction", row.get("No restriction found", 0)) or 0),
            "Records": int(row.get("Total records", row.get("Records", 0)) or 0),
        })
    return rows


def build_ingredient_type_rows(summary_rows: list[dict]) -> list[dict]:
    """Aggregate ordinary ingredients/additives/unknowns from the current scan."""
    counts = {}
    for row in summary_rows or []:
        kind = str(row.get("Type", row.get("Ingredient type", "Unknown")) or "Unknown").strip()
        if not kind:
            kind = "Unknown"
        label = {
            "ADDITIVE": "Food additives",
            "ORDINARY_INGREDIENT": "Food ingredients",
            "UNKNOWN": "Unclassified ingredients",
        }.get(kind, kind.replace("_", " ").title())
        counts[label] = counts.get(label, 0) + 1
    return [{"Category": k, "Ingredients": v} for k, v in sorted(counts.items(), key=lambda x: (-x[1], x[0]))]


def build_regulatory_explanation(regulatory_results: list[dict], ingredient: str, country: str) -> dict:
    """Create a plain-English explanation from the stored record only."""
    rows = build_regulatory_evidence_rows(regulatory_results, ingredient, country)
    if not rows:
        return {
            "found": False,
            "headline": "No stored regulatory record",
            "summary": "The current database does not contain a record for this ingredient in the selected jurisdiction. Missing data is not treated as approval.",
            "source": "",
        }
    ev = rows[0]
    status = str(ev.get("Status", "—"))
    level = str(ev.get("Legal level", "—"))
    unit = str(ev.get("Unit", "—"))
    conditions = str(ev.get("Conditions", "—"))
    restriction = str(ev.get("Restriction", "—"))
    authority = str(ev.get("Authority", "—"))
    verified = str(ev.get("Last verified", "—"))
    source = str(ev.get("Source", "—"))
    headline = f"{ingredient} — {country}: {status}"
    pieces = [f"Stored status: {status}."]
    if level not in {"—", "", "None"}:
        pieces.append(f"Recorded level: {level} {unit if unit not in {'—',''} else ''}.".strip())
    if conditions not in {"—", "", "None"}:
        pieces.append(f"Conditions: {conditions}.")
    if restriction not in {"—", "", "None"}:
        pieces.append(f"Restriction: {restriction}.")
    if authority not in {"—", "", "None"}:
        pieces.append(f"Authority recorded: {authority}.")
    if verified not in {"—", "", "None"}:
        pieces.append(f"Last verified: {verified}.")
    return {
        "found": True,
        "headline": headline,
        "summary": " ".join(pieces),
        "source": source if source != "—" else "",
    }


def build_scan_manifest(scan_entry: dict, analysis_timestamp: str = "") -> dict:
    """Create a lightweight trace ID for the current analysis/export set."""
    scan_id = str(scan_entry.get("scan_id", "")).strip() if scan_entry else ""
    if not scan_id:
        seed = "|".join([
            str(scan_entry.get("file", "")) if scan_entry else "",
            str(scan_entry.get("content_hash", "")) if scan_entry else "",
            analysis_timestamp,
        ])
        scan_id = "FR-" + hashlib.sha1(seed.encode("utf-8", errors="ignore")).hexdigest()[:12].upper()
    return {
        "Scan ID": scan_id,
        "Generated": analysis_timestamp or datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "Source file": str(scan_entry.get("file", "")) if scan_entry else "",
        "Content fingerprint": str(scan_entry.get("content_hash", ""))[:16] if scan_entry else "",
    }


# =========================================================
# REPORT + COMPARISON HELPERS
# =========================================================

def get_risk_explanation(risk: str, ingredient_class: dict) -> str:
    if risk == "🔴 Prohibited":
        return "At least one checked jurisdiction has a prohibited or not-authorised finding."
    if risk == "🟠 Restricted":
        return "At least one checked jurisdiction allows the ingredient only with specific restrictions."
    if risk == "🟡 Conditions apply":
        return "Use depends on food category, permitted level, GMP, footnotes, or other conditions."
    if risk == "🟢 No restriction found":
        return "The available verified records are positive and no stronger restriction was found."
    if risk == "ℹ️ Food ingredient":
        return "This is primarily a food ingredient rather than a food additive; product standards and labelling rules may apply."
    return "The current database does not yet provide enough verified regulatory coverage."


def get_attention_level(summary_rows: list[dict], allergens: list[dict], country_alerts: list[dict]) -> dict[str, str]:
    """Create a transparent product-level regulatory attention summary.

    This is not a health/safety score. It summarizes label-derived regulatory
    findings and detected allergens only.
    """
    flags = [str(row.get("Regulatory flag", "")) for row in summary_rows]
    has_prohibited = any("Prohibited" in flag for flag in flags)
    has_restricted = any("Restricted" in flag for flag in flags)
    has_conditions = any("Conditions apply" in flag for flag in flags)

    if has_prohibited:
        return {
            "level": "🔴 High attention",
            "title": "Regulatory attention required",
            "text": "At least one checked jurisdiction has a prohibited or not-authorised finding.",
        }
    if has_restricted:
        return {
            "level": "🟠 Elevated attention",
            "title": "Restrictions need checking",
            "text": "At least one checked jurisdiction has a restricted-use finding.",
        }
    if allergens and (has_conditions or country_alerts):
        return {
            "level": "🟡 Review recommended",
            "title": "Allergen or regulatory conditions detected",
            "text": "The label contains detected allergens and/or regulatory conditions that vary by jurisdiction.",
        }
    if allergens:
        return {
            "level": "🟡 Review recommended",
            "title": "Allergen review recommended",
            "text": "Potential allergens were identified directly from the ingredient list.",
        }
    if has_conditions:
        return {
            "level": "🟡 Review recommended",
            "title": "Regulatory conditions apply",
            "text": "Several ingredients have jurisdiction-specific conditions of use.",
        }
    return {
        "level": "🟢 Standard screening",
        "title": "No major alert in the current database",
        "text": "No prohibited or restricted finding was detected in the currently stored records.",
    }





def build_ingredient_attention_rows(summary_rows: list[dict], regulatory_results: list[dict], review_queue: list[dict]) -> list[dict]:
    """Rank ingredients by transparent review signals, not health risk."""
    review_names = {str(r.get("Normalized ingredient", "")).strip().lower() for r in (review_queue or []) if str(r.get("Normalized ingredient", "")).strip()}
    rows=[]
    for summary in summary_rows or []:
        ingredient=str(summary.get("Ingredient", "")).strip()
        if not ingredient:
            continue
        matched=next((r for r in (regulatory_results or []) if str(r.get("ingredient", "")).strip().lower()==ingredient.lower()),{})
        record=matched.get("record", {}) or {}
        statuses=[str(d.get("status", "")).upper() for d in (record.get("jurisdictions", {}) or {}).values()]
        prohibited=sum(1 for x in statuses if "BANNED" in x or "NOT_AUTHORISED" in x)
        restricted=sum(1 for x in statuses if "RESTRICTED" in x)
        conditions=sum(1 for x in statuses if "CONDIT" in x)
        manual=ingredient.lower() in review_names
        signals=prohibited*4 + restricted*3 + conditions + (2 if manual else 0)
        if prohibited: level="🔴 Priority review"
        elif restricted or manual: level="🟠 Review soon"
        elif conditions: level="🟡 Check conditions"
        else: level="🟢 Routine"
        rows.append({"Ingredient":ingredient,"Review level":level,"Review signals":signals,
                     "Prohibited / not authorised":prohibited,"Restricted":restricted,"Conditions":conditions,
                     "Manual review":"Yes" if manual else "No","Countries covered":len(statuses)})
    return sorted(rows,key=lambda r:(-int(r.get("Review signals",0)),r["Ingredient"].lower()))


def build_country_profile_rows(comparison_rows: list[dict]) -> list[dict]:
    """Summarize current stored findings by jurisdiction."""
    grouped={}
    for row in comparison_rows or []:
        country=str(row.get("Country","")).strip(); status=str(row.get("Status","")).strip()
        if not country: continue
        item=grouped.setdefault(country,{"Country":country,"Records":0,"Prohibited":0,"Restricted":0,"Conditions":0,"No restriction":0,"Other / unknown":0})
        item["Records"]+=1
        low=status.lower()
        if "prohibited" in low or "not authorised" in low: item["Prohibited"]+=1
        elif "restricted" in low: item["Restricted"]+=1
        elif "conditions" in low: item["Conditions"]+=1
        elif "no restriction" in low: item["No restriction"]+=1
        else: item["Other / unknown"]+=1
    rows=list(grouped.values())
    for row in rows:
        row["Attention findings"]=row["Prohibited"]+row["Restricted"]+row["Conditions"]
        if row["Prohibited"]: row["Profile"]="🔴 Highest attention"
        elif row["Restricted"]: row["Profile"]="🟠 Elevated"
        elif row["Conditions"]: row["Profile"]="🟡 Conditions"
        else: row["Profile"]="🟢 No major stored alert"
    return sorted(rows,key=lambda r:(-int(r["Attention findings"]),r["Country"].lower()))


def build_decision_brief(screening_decision: dict, attention_rows: list[dict], country_profile_rows: list[dict], review_action_checklist: list[dict], review_notes: str = "") -> str:
    lines=["FOODREG AI — DECISION BRIEF","="*40,"",f"Screening level: {screening_decision.get('level','Not calculated')}",
           f"Title: {screening_decision.get('title','Screening result')}",f"Summary: {screening_decision.get('text','')}","","Reasons:"]
    reasons=screening_decision.get("reasons",[]) or []
    lines.extend([f"- {x}" for x in reasons] or ["- No additional reasons recorded."])
    lines.extend(["","TOP INGREDIENT REVIEW SIGNALS:"])
    for row in (attention_rows or [])[:8]:
        lines.append(f"- {row['Ingredient']}: {row['Review level']} | prohibited={row['Prohibited / not authorised']}, restricted={row['Restricted']}, conditions={row['Conditions']}, manual_review={row['Manual review']}")
    lines.extend(["","COUNTRY PROFILES:"])
    for row in (country_profile_rows or [])[:10]:
        lines.append(f"- {row['Country']}: {row['Profile']} | records={row['Records']}, attention findings={row['Attention findings']}")
    lines.extend(["","ACTION CHECKLIST:"])
    for row in (review_action_checklist or [])[:10]:
        lines.append(f"- [{row.get('Priority','')}] {row.get('Action','')} — {row.get('Why','')}")
    if review_notes.strip(): lines.extend(["","REVIEW NOTES:",review_notes.strip()])
    lines.extend(["","DISCLAIMER:",str(screening_decision.get("disclaimer","This is a screening summary, not legal or medical advice."))])
    return "\n".join(lines)


def build_scan_history_rows(history: list[dict]) -> list[dict]:
    return [{"Time":e.get("time",""),"File":e.get("file",""),"Ingredients":e.get("ingredients",0),"Additives":e.get("additives",0),"Allergens":e.get("allergens",0),"Regulatory records":e.get("regulatory_records",0),"Attention":e.get("attention","")} for e in (history or [])]


PERSISTENT_HISTORY_PATH = Path(__file__).resolve().parent / ".foodreg_scan_history.json"

def load_persistent_scan_history(limit: int = 25) -> list[dict]:
    try:
        if not PERSISTENT_HISTORY_PATH.exists():
            return []
        payload=json.loads(PERSISTENT_HISTORY_PATH.read_text(encoding="utf-8"))
        return [x for x in payload if isinstance(x, dict)][:limit] if isinstance(payload, list) else []
    except Exception:
        return []

def save_persistent_scan_history(history: list[dict], limit: int = 25) -> None:
    try:
        keep_keys=("scan_id","time","file","ingredients","ingredient_names","ingredient_fingerprint","content_hash","additives","allergens","regulatory_records","attention","bookmarked","product_name","net_weight","mrp","nutrition_snapshot","regulatory_snapshot","claims_count")
        payload=[]
        for item in (history or [])[:limit]:
            payload.append({k:item.get(k) for k in keep_keys if k in item})
        PERSISTENT_HISTORY_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass

def build_history_dashboard_rows(history: list[dict]) -> dict:
    history=history or []
    return {
        "scans": len(history),
        "unique_files": len({str(x.get("file","")).strip() for x in history if str(x.get("file","")).strip()}),
        "unique_ingredients": len({str(n).strip().lower() for x in history for n in (x.get("ingredient_names",[]) or []) if str(n).strip()}),
        "bookmarked": sum(1 for x in history if x.get("bookmarked")),
    }

def compare_scan_history_entries(left: dict, right: dict) -> list[dict]:
    left_names={str(x).strip() for x in (left.get("ingredient_names",[]) or []) if str(x).strip()}
    right_names={str(x).strip() for x in (right.get("ingredient_names",[]) or []) if str(x).strip()}
    added=sorted(right_names-left_names,key=str.lower)
    removed=sorted(left_names-right_names,key=str.lower)
    shared=left_names & right_names
    rows=[
        {"Metric":"Ingredients", "Left value":len(left_names), "Right value":len(right_names), "Difference":len(right_names)-len(left_names)},
        {"Metric":"Shared ingredients", "Left value":len(shared), "Right value":len(shared), "Difference":0},
        {"Metric":"Added in right scan", "Left value":0, "Right value":len(added), "Difference":len(added)},
        {"Metric":"Removed in right scan", "Left value":len(removed), "Right value":0, "Difference":-len(removed)},
        {"Metric":"Additives", "Left value":int(left.get("additives",0) or 0), "Right value":int(right.get("additives",0) or 0), "Difference":int(right.get("additives",0) or 0)-int(left.get("additives",0) or 0)},
        {"Metric":"Allergen signals", "Left value":int(left.get("allergens",0) or 0), "Right value":int(right.get("allergens",0) or 0), "Difference":int(right.get("allergens",0) or 0)-int(left.get("allergens",0) or 0)},
        {"Metric":"Regulatory records", "Left value":int(left.get("regulatory_records",0) or 0), "Right value":int(right.get("regulatory_records",0) or 0), "Difference":int(right.get("regulatory_records",0) or 0)-int(left.get("regulatory_records",0) or 0)},
        {"Metric":"Added ingredient names", "Left value":"—", "Right value":", ".join(added) if added else "None", "Difference":"—"},
        {"Metric":"Removed ingredient names", "Left value":", ".join(removed) if removed else "None", "Right value":"—", "Difference":"—"},
    ]
    return rows


def build_content_hash(uploaded_file) -> str:
    """Hash uploaded bytes without persisting the file."""
    try:
        raw = uploaded_file.getvalue() if uploaded_file is not None else b""
        return hashlib.sha256(raw).hexdigest() if raw else ""
    except Exception:
        return ""


def build_regulatory_snapshot(regulatory_results: list[dict]) -> dict:
    """Compact ingredient -> jurisdiction -> status snapshot for scan-to-scan comparison."""
    snapshot = {}
    for item in regulatory_results or []:
        ingredient = str(item.get("ingredient") or item.get("canonical_name") or item.get("name") or "").strip()
        record = item.get("record", {}) or {}
        if not ingredient:
            continue
        per_country = {}
        for country, data in (record.get("jurisdictions", {}) or {}).items():
            data = data or {}
            per_country[str(country)] = {
                "status": str(data.get("status", "UNKNOWN") or "UNKNOWN"),
                "maximum_level": str(data.get("maximum_level", "") or ""),
                "unit": str(data.get("unit", "") or ""),
                "conditions": str(data.get("conditions", "") or ""),
            }
        snapshot[ingredient] = per_country
    return snapshot


def _numeric_value(value):
    try:
        return float(value)
    except Exception:
        return None


def build_scan_delta(current_entry: dict, previous_entry: dict | None) -> list[dict]:
    """Compare two lightweight scan snapshots. Missing prior data is never treated as zero/safe."""
    if not previous_entry:
        return []
    rows = []
    current_names = set(current_entry.get("ingredient_names", []) or [])
    previous_names = set(previous_entry.get("ingredient_names", []) or [])
    added = sorted(current_names - previous_names, key=str.lower)
    removed = sorted(previous_names - current_names, key=str.lower)
    rows.append({"Area": "Ingredients", "Change": f"{len(added)} added / {len(removed)} removed", "Previous": len(previous_names), "Current": len(current_names), "Interpretation": "Ingredient-list change" if (added or removed) else "No ingredient-name change detected"})
    if added:
        rows.append({"Area": "Added ingredients", "Change": ", ".join(added), "Previous": "—", "Current": len(added), "Interpretation": "Present in current scan only"})
    if removed:
        rows.append({"Area": "Removed ingredients", "Change": ", ".join(removed), "Previous": len(removed), "Current": "—", "Interpretation": "Present in previous scan only"})

    prev_n = previous_entry.get("nutrition_snapshot") or {}
    curr_n = current_entry.get("nutrition_snapshot") or {}
    for key in ["energy_kcal", "protein_g", "carbohydrate_g", "total_sugars_g", "total_fat_g", "sodium_mg"]:
        pv = _numeric_value(prev_n.get(key))
        cv = _numeric_value(curr_n.get(key))
        if pv is None and cv is None:
            continue
        delta = (cv - pv) if pv is not None and cv is not None else None
        label = key.replace("_", " ").title()
        rows.append({"Area": f"Nutrition • {label}", "Change": f"{delta:+g}" if delta is not None else "Not comparable", "Previous": prev_n.get(key, "—"), "Current": curr_n.get(key, "—"), "Interpretation": "Numeric change" if delta is not None else "One scan lacks a comparable numeric value"})

    prev_reg = previous_entry.get("regulatory_snapshot") or {}
    curr_reg = current_entry.get("regulatory_snapshot") or {}
    reg_changes = []
    for ingredient in sorted(set(prev_reg) | set(curr_reg), key=str.lower):
        pc = prev_reg.get(ingredient, {}) or {}
        cc = curr_reg.get(ingredient, {}) or {}
        for country in sorted(set(pc) | set(cc), key=str.lower):
            ps = (pc.get(country, {}) or {}).get("status")
            cs = (cc.get(country, {}) or {}).get("status")
            if ps != cs and (ps is not None or cs is not None):
                reg_changes.append(f"{ingredient} / {country}: {ps or 'no record'} → {cs or 'no record'}")
    if reg_changes:
        rows.append({"Area": "Regulatory status changes", "Change": "; ".join(reg_changes[:25]), "Previous": "Stored snapshot", "Current": "Stored snapshot", "Interpretation": f"{len(reg_changes)} stored status change(s); verify source/effective dates"})
    else:
        rows.append({"Area": "Regulatory status changes", "Change": "None detected", "Previous": "Stored snapshot", "Current": "Stored snapshot", "Interpretation": "No stored status difference across comparable records"})
    return rows


def find_previous_similar_scan(current_entry: dict, history: list[dict]) -> dict | None:
    """Find the strongest previous comparison candidate without storing images."""
    if not history:
        return None
    current_id = current_entry.get("scan_id")
    candidates = [x for x in history if x.get("scan_id") != current_id]
    if not candidates:
        return None
    current_product = str(current_entry.get("product_name", "") or "").strip().lower()
    current_fp = str(current_entry.get("ingredient_fingerprint", "") or "")
    scored = []
    for row in candidates:
        score = 0
        product = str(row.get("product_name", "") or "").strip().lower()
        if current_product and product and current_product == product:
            score += 5
        if current_fp and row.get("ingredient_fingerprint") == current_fp:
            score += 4
        shared = len(set(current_entry.get("ingredient_names", []) or []) & set(row.get("ingredient_names", []) or []))
        score += min(shared, 5)
        scored.append((score, str(row.get("time", "")), row))
    scored.sort(key=lambda x: (x[0], x[1]), reverse=True)
    return scored[0][2] if scored and scored[0][0] > 0 else None


def build_product_library_rows(history: list[dict]) -> list[dict]:
    grouped = {}
    for row in history or []:
        name = str(row.get("product_name", "") or "").strip()
        if not name:
            name = Path(str(row.get("file", "Scan"))).stem or "Unnamed product"
        key = name.casefold()
        item = grouped.setdefault(key, {"Product": name, "Scans": 0, "Latest scan": "", "Latest ingredients": 0, "Bookmarks": 0, "Latest attention": ""})
        item["Scans"] += 1
        item["Latest scan"] = max(item["Latest scan"], str(row.get("time", "")))
        if str(row.get("time", "")) == item["Latest scan"]:
            item["Latest ingredients"] = int(row.get("ingredients", 0) or 0)
            item["Latest attention"] = str(row.get("attention", ""))
        item["Bookmarks"] += 1 if row.get("bookmarked") else 0
    return sorted(grouped.values(), key=lambda r: (r["Latest scan"], r["Product"].lower()), reverse=True)


def build_product_trend_rows(product_name: str, history: list[dict]) -> list[dict]:
    target = str(product_name or "").strip().casefold()
    rows=[]
    for row in reversed(history or []):
        name = str(row.get("product_name", "") or "").strip().casefold()
        if target and name == target:
            rows.append({
                "Date": row.get("time", ""),
                "Ingredients": int(row.get("ingredients", 0) or 0),
                "Additives": int(row.get("additives", 0) or 0),
                "Allergens": int(row.get("allergens", 0) or 0),
                "Regulatory records": int(row.get("regulatory_records", 0) or 0),
            })
    return rows

def build_coverage_stats(regulatory_results: list[dict]) -> dict:
    """Summarize evidence coverage without treating missing data as safe."""
    total_records=0; linked_sources=0; verified_dates=[]; framework_records=0; jurisdictions=set()
    for result_item in regulatory_results:
        record=result_item.get("record", {})
        for country, data in record.get("jurisdictions", {}).items():
            total_records += 1; jurisdictions.add(country)
            if str(data.get("source", "") or "").strip(): linked_sources += 1
            verified=str(data.get("verified", "") or "").strip()
            if verified: verified_dates.append(verified)
            source_type=str(data.get("source_type", "") or "").upper()
            notes=str(data.get("notes", "") or "").lower()
            label=str(data.get("label", "") or "").lower()
            if "reference" in source_type or "prototype" in notes or "product-standard/reference" in label:
                framework_records += 1
    return {"records": total_records, "jurisdictions": len(jurisdictions), "linked_sources": linked_sources,
            "latest_verified": max(verified_dates) if verified_dates else "Not available",
            "framework_records": framework_records}


def build_country_matrix(comparison_rows: list[dict], countries: list[str]) -> list[dict]:
    """Build an ingredient x country status matrix."""
    by_ingredient={}
    for row in comparison_rows:
        ingredient=row.get("Ingredient", ""); country=row.get("Country", "")
        if ingredient and country:
            by_ingredient.setdefault(ingredient, {})[country]=row.get("Status", "⚪ Unknown")
    matrix=[]
    for ingredient in sorted(by_ingredient, key=str.lower):
        row={"Ingredient": ingredient}
        for country in countries: row[country]=by_ingredient[ingredient].get(country, "—")
        matrix.append(row)
    return matrix

def build_regulatory_difference_rows(comparison_rows: list[dict]) -> list[dict]:
    """Highlight ingredients whose stored regulatory status differs by jurisdiction."""
    grouped = {}
    for row in comparison_rows:
        ingredient = str(row.get("Ingredient", "")).strip()
        country = str(row.get("Country", "")).strip()
        status = str(row.get("Status", "")).strip()
        if not ingredient or not country:
            continue
        grouped.setdefault(ingredient, []).append((country, status))

    rows = []
    for ingredient, entries in grouped.items():
        unique_statuses = {status for _, status in entries if status}
        if len(unique_statuses) <= 1:
            continue
        status_text = " | ".join(f"{country}: {status}" for country, status in sorted(entries, key=lambda x: x[0].lower()))
        rows.append({
            "Ingredient": ingredient,
            "Different by country": "Yes",
            "Status count": len(unique_statuses),
            "Jurisdictions covered": len(entries),
            "Country findings": status_text,
        })

    return sorted(rows, key=lambda row: (-int(row.get("Status count", 0)), row["Ingredient"].lower()))


def build_regulatory_consistency_rows(regulatory_results: list[dict]) -> list[dict]:
    """Flag metadata combinations that deserve audit review. Not a legal correctness test."""
    rows = []
    for result_item in regulatory_results:
        ingredient = str(result_item.get("ingredient", "")).strip()
        record = result_item.get("record", {}) or {}
        for jurisdiction, data in (record.get("jurisdictions", {}) or {}).items():
            data = data or {}
            status = str(data.get("status", "UNKNOWN") or "UNKNOWN").upper()
            restriction = str(data.get("restriction", "") or "").strip()
            conditions = str(data.get("conditions", "") or "").strip()
            maximum_level = str(data.get("maximum_level", "") or "").strip()
            source = str(data.get("source", "") or "").strip()
            verified = str(data.get("verified", "") or "").strip()
            issues = []
            priority = "Low"
            if status in {"AUTHORISED", "LISTED"} and restriction:
                issues.append("Authorised/listed status has a restriction field.")
                priority = "Medium"
            if status in {"CHECK_CONDITIONS", "CHECK", "REGULATED"} and not (conditions or restriction or maximum_level):
                issues.append("Condition/regulation status has no recorded rule detail.")
                priority = "High"
            if not source:
                issues.append("Source URL is missing.")
                priority = "High" if priority == "Low" else priority
            if not verified:
                issues.append("Verification date is missing.")
                if priority == "Low":
                    priority = "Medium"
            if status == "UNKNOWN":
                issues.append("Stored status is unknown.")
                priority = "High"
            if issues:
                rows.append({
                    "Ingredient": ingredient.title(),
                    "Jurisdiction": jurisdiction,
                    "Stored status": get_status_display(status),
                    "Audit priority": priority,
                    "Metadata issue": " ".join(issues),
                    "Source": source or "—",
                    "Verified": verified or "—",
                })
    order = {"High": 0, "Medium": 1, "Low": 2}
    return sorted(rows, key=lambda r: (order.get(r.get("Audit priority"), 9), str(r.get("Ingredient", "")).lower(), str(r.get("Jurisdiction", "")).lower()))


def build_regulatory_alert_feed(regulatory_results: list[dict]) -> list[dict]:
    """Create a compact, prioritized feed from stored jurisdiction records."""
    rows = []
    priority_map = {
        "BANNED": ("High", "Prohibited / not authorised"),
        "NOT_AUTHORISED": ("High", "Not authorised"),
        "RESTRICTED": ("High", "Restricted use"),
        "CHECK_CONDITIONS": ("Medium", "Conditions apply"),
        "CHECK": ("Medium", "Check conditions"),
        "REGULATED": ("Medium", "Regulated / rule-specific"),
    }
    for result_item in regulatory_results:
        ingredient = str(result_item.get("ingredient", "")).strip()
        record = result_item.get("record", {}) or {}
        for jurisdiction, data in (record.get("jurisdictions", {}) or {}).items():
            data = data or {}
            status = str(data.get("status", "UNKNOWN") or "UNKNOWN").upper()
            if status not in priority_map:
                continue
            priority, finding = priority_map[status]
            detail = str(data.get("restriction", "") or data.get("conditions", "") or data.get("reason", "") or "").strip()
            if not detail:
                detail = "See stored regulatory record for the jurisdiction-specific rule."
            rows.append({
                "Priority": priority,
                "Ingredient": ingredient.title(),
                "Jurisdiction": jurisdiction,
                "Finding": finding,
                "Recorded level": str(data.get("maximum_level", "") or "—"),
                "Detail": detail,
                "Verified": str(data.get("verified", "") or "—"),
                "Source": str(data.get("source", "") or "—"),
            })
    order = {"High": 0, "Medium": 1, "Low": 2}
    return sorted(rows, key=lambda r: (order.get(r.get("Priority"), 9), str(r.get("Ingredient", "")).lower(), str(r.get("Jurisdiction", "")).lower()))


def build_function_explorer_rows(additive_function_rows: list[dict], query: str = "") -> list[dict]:
    """Filter additive function/reference rows for a focused explorer."""
    q = str(query or "").strip().lower()
    if not q:
        return list(additive_function_rows or [])
    rows = []
    for row in additive_function_rows or []:
        blob = " | ".join(str(v or "") for v in row.values()).lower()
        if q in blob:
            rows.append(row)
    return rows


def build_executive_brief(screening_decision: dict, dashboard_stats: dict, label_quality: dict, source_quality: dict, alert_feed: list[dict], consistency_rows: list[dict]) -> str:
    """Create a concise decision-support brief without presenting it as legal advice."""
    high_alerts = sum(1 for r in alert_feed if r.get("Priority") == "High")
    medium_alerts = sum(1 for r in alert_feed if r.get("Priority") == "Medium")
    consistency_high = sum(1 for r in consistency_rows if r.get("Audit priority") == "High")
    quality_score = label_quality.get("score", "—") if isinstance(label_quality, dict) else "—"
    return (
        "FOODREG AI — 60-SECOND EXECUTIVE BRIEF\n\n"
        f"Screening result: {screening_decision.get('level', 'Not available')}\n"
        f"Ingredients identified: {dashboard_stats.get('ingredients', 0)}\n"
        f"Additives identified: {dashboard_stats.get('additives', 0)}\n"
        f"Potential allergen signals: {dashboard_stats.get('allergen_signals', 0)}\n"
        f"Regulatory records reviewed: {dashboard_stats.get('regulatory_records', 0)} across {dashboard_stats.get('jurisdictions', 0)} jurisdictions\n"
        f"High-priority regulatory alerts: {high_alerts}\n"
        f"Medium-priority regulatory alerts: {medium_alerts}\n"
        f"Regulatory metadata consistency issues: {len(consistency_rows)} ({consistency_high} high priority)\n"
        f"Label data capture score: {quality_score}/100\n"
        f"Records with source links: {source_quality.get('with_source_url', 0)} / {source_quality.get('total_records', 0)}\n\n"
        "Top reasons:\n" + "\n".join(f"- {r}" for r in screening_decision.get("reasons", [])[:5]) + "\n\n"
        "Important: This brief summarizes the current stored OCR, ingredient and regulatory evidence. It is not medical advice, a safety score, or a legal compliance certificate."
    )


def build_ingredient_relationship_rows(normalized_results: list[dict], allergens: list[dict], regulatory_results: list[dict]) -> list[dict]:
    """Map each ingredient to type, allergen signal and regulatory coverage."""
    allergen_map = {}
    for a in allergens or []:
        for ing in (a.get("ingredients") or []):
            allergen_map.setdefault(str(ing).strip().lower(), set()).add(str(a.get("allergen", "")).strip())
    rows=[]
    for item in normalized_results or []:
        name=str(item.get("canonical", "")).strip()
        if not name: continue
        ins=str(item.get("ins", "") or "").strip()
        cls=classify_ingredient(name, ins or None)
        match=next((r for r in (regulatory_results or []) if str(r.get("ingredient", "")).strip().lower()==name.lower()), {})
        rec=match.get("record") or {}
        statuses=[]
        for country,data in (rec.get("jurisdictions") or {}).items():
            statuses.append((country,str((data or {}).get("status","UNKNOWN") or "UNKNOWN").upper()))
        flagged=sum(1 for _,st in statuses if st in {"BANNED","NOT_AUTHORISED","RESTRICTED","CHECK_CONDITIONS","CONDITIONAL","CONDITIONS"})
        rows.append({"Ingredient":name,"Type":cls.get("label","Unclassified ingredient"),"INS":ins or "—","Allergen signal":", ".join(sorted(allergen_map.get(name.lower(), set()))) or "None detected","Countries with records":len(statuses),"Attention countries":flagged,"Regulatory link":"Stored record" if rec.get("found") else "No stored record"})
    return rows


def build_regulatory_watch_rows(current_results: list[dict], history: list[dict]) -> list[dict]:
    """Compare current regulatory snapshot with the most recent comparable scan."""
    current=build_regulatory_snapshot(current_results)
    current_names={str(k).strip().lower() for k in current}
    prior=None
    for entry in history or []:
        snap=entry.get("regulatory_snapshot") or {}
        if snap and current_names & {str(k).strip().lower() for k in snap}:
            prior=entry; break
    if not prior: return []
    prev=prior.get("regulatory_snapshot") or {}
    rows=[]
    prev_lookup={str(k).strip().lower():(k,v) for k,v in prev.items()}
    for ing,curr_by in current.items():
        prev_key,prev_by=prev_lookup.get(ing.lower(),("",{}))
        if not prev_key:
            rows.append({"Ingredient":ing,"Country":"—","Previous":"Not in prior scan","Current":"Present now","Change":"Added to current scan"})
            continue
        prev_by=prev_by or {}
        curr_by=curr_by or {}
        for country in sorted(set(prev_by)|set(curr_by), key=str.lower):
            p=prev_by.get(country) or {}; c=curr_by.get(country) or {}
            ps=str(p.get("status","MISSING")); cs=str(c.get("status","MISSING"))
            if ps!=cs:
                rows.append({"Ingredient":ing,"Country":country,"Previous":ps,"Current":cs,"Change":"Stored regulatory snapshot changed"})
    return rows


def build_final_summary_panel(screening_decision: dict, dashboard_stats: dict, label_quality: dict, review_center_rows: list[dict], regulatory_alert_feed: list[dict]) -> dict:
    """Compact product-level summary using current evidence only."""
    high=sum(1 for r in (regulatory_alert_feed or []) if str(r.get("Priority","")).lower()=="high")
    medium=sum(1 for r in (regulatory_alert_feed or []) if str(r.get("Priority","")).lower()=="medium")
    open_items=sum(1 for r in (review_center_rows or []))
    return {"Screening":screening_decision.get("level","Not calculated"),"Title":screening_decision.get("title","Screening result"),"Ingredients":int(dashboard_stats.get("ingredients",0)),"Additives":int(dashboard_stats.get("additives",0)),"Allergen signals":int(dashboard_stats.get("allergen_signals",0)),"Regulatory records":int(dashboard_stats.get("regulatory_records",0)),"High alerts":high,"Medium alerts":medium,"Open review items":open_items,"Label data quality":label_quality.get("label","Not calculated"),"Label data quality score":label_quality.get("score",0)}

def build_regulatory_evidence_rows(regulatory_results: list[dict], ingredient: str = "", country: str = "") -> list[dict]:
    """Return source/evidence metadata for a selected ingredient and optional jurisdiction."""
    wanted_ingredient = str(ingredient or "").strip().lower()
    wanted_country = str(country or "").strip().lower()
    rows = []

    for result_item in regulatory_results:
        canonical = str(result_item.get("ingredient", "")).strip()
        if wanted_ingredient and canonical.lower() != wanted_ingredient:
            continue
        record = result_item.get("record", {}) or {}
        for jurisdiction, data in record.get("jurisdictions", {}).items():
            if wanted_country and jurisdiction.lower() != wanted_country:
                continue
            data = data or {}
            rows.append({
                "Ingredient": canonical.title(),
                "Jurisdiction": jurisdiction,
                "Status": get_status_display(str(data.get("status", "UNKNOWN") or "UNKNOWN").upper()),
                "Legal level": str(data.get("maximum_level", "") or "").strip() or "—",
                "Unit": str(data.get("unit", "") or "").strip() or "—",
                "Food category": str(data.get("food_category", "") or "").strip() or "—",
                "Conditions": str(data.get("conditions", "") or "").strip() or "—",
                "Restriction": str(data.get("restriction", "") or "").strip() or "—",
                "Authority": str(data.get("authority", "") or "").strip() or "—",
                "Source": str(data.get("source", "") or "").strip() or "—",
                "Source type": str(data.get("source_type", "") or "").strip() or "—",
                "Last verified": str(data.get("verified", "") or "").strip() or "—",
                "Data status": str(data.get("data_status", "") or "").strip() or "—",
            })

    return sorted(rows, key=lambda row: (row["Jurisdiction"].lower(), row["Ingredient"].lower()))


def build_screening_decision(summary_rows: list[dict], allergens: list[dict], country_alerts: list[dict], scan_clarity: dict, review_queue: list[dict]) -> dict:
    """Create a transparent screening conclusion without turning it into a health score."""
    attention = get_attention_level(summary_rows, allergens, country_alerts)
    reasons = []
    prohibited = sum(1 for row in summary_rows if "Prohibited" in str(row.get("Regulatory flag", "")))
    restricted = sum(1 for row in summary_rows if "Restricted" in str(row.get("Regulatory flag", "")))
    conditions = sum(1 for row in summary_rows if "Conditions apply" in str(row.get("Regulatory flag", "")))

    if prohibited:
        reasons.append(f"{prohibited} prohibited/not-authorised ingredient finding(s) are stored for at least one jurisdiction.")
    elif restricted:
        reasons.append(f"{restricted} restricted-use ingredient finding(s) are stored for at least one jurisdiction.")
    elif conditions:
        reasons.append(f"{conditions} ingredient(s) have jurisdiction-specific conditions.")
    else:
        reasons.append("No prohibited or restricted finding was detected in the currently stored records.")

    if allergens:
        reasons.append(f"{len(allergens)} potential allergen group(s) were detected from the ingredient names.")
    if review_queue:
        reasons.append(f"{len(review_queue)} ingredient identification item(s) need manual review.")
    if scan_clarity and int(scan_clarity.get("score", 100) or 100) < 70:
        reasons.append("The scan/normalization quality is below the preferred review threshold.")

    return {
        "level": attention.get("level", "🟢 Standard screening"),
        "title": attention.get("title", "Screening result"),
        "text": attention.get("text", ""),
        "reasons": reasons[:5],
        "disclaimer": "This conclusion summarizes the stored ingredient/regulatory evidence. It is not medical advice, a health score, or a legal compliance certificate.",
    }


def build_concern_list(summary_rows: list[dict], allergens: list[dict], country_alerts: list[dict]) -> list[str]:
    concerns = []
    if allergens:
        concerns.append(f"{len(allergens)} potential allergen group(s) detected")
    prohibited = [r["Ingredient"] for r in summary_rows if "Prohibited" in str(r.get("Regulatory flag", ""))]
    restricted = [r["Ingredient"] for r in summary_rows if "Restricted" in str(r.get("Regulatory flag", ""))]
    conditions = [r["Ingredient"] for r in summary_rows if "Conditions apply" in str(r.get("Regulatory flag", ""))]
    if prohibited:
        concerns.append("Prohibited/not-authorised finding: " + ", ".join(prohibited[:4]))
    if restricted:
        concerns.append("Restricted-use finding: " + ", ".join(restricted[:4]))
    if conditions:
        concerns.append(f"{len(conditions)} ingredient(s) have jurisdiction-specific conditions")
    if country_alerts:
        concerns.append(f"{len(country_alerts)} country-specific alert(s) require review")
    return concerns[:5]


def build_summary_csv(summary_rows: list[dict]) -> str:
    fields = [
        "Ingredient",
        "INS",
        "Regulatory flag",
        "Ingredient type",
        "Why flagged",
        "Countries with records",
        "Covered countries",
    ]
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=fields, extrasaction="ignore")
    writer.writeheader()
    for row in summary_rows:
        writer.writerow(row)
    return buffer.getvalue()


def build_regulatory_difference_csv(rows: list[dict]) -> str:
    fields = ["Ingredient", "Different by country", "Status count", "Jurisdictions covered", "Country findings"]
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=fields, extrasaction="ignore")
    writer.writeheader()
    for row in rows:
        writer.writerow(row)
    return buffer.getvalue()

def build_country_csv(comparison_rows: list[dict]) -> str:
    fields = [
        "Ingredient",
        "Country",
        "Status",
        "Legal level",
        "Condition",
        "Food category",
    ]
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=fields, extrasaction="ignore")
    writer.writeheader()
    for row in comparison_rows:
        writer.writerow(row)
    return buffer.getvalue()



# =========================================================
# ADDITIVE FUNCTIONS + SOURCE QUALITY
# =========================================================

ADDITIVE_FUNCTION_HINTS = {
    "citric acid": ("Acidity regulator", "Controls acidity and can provide sourness."),
    "guar gum": ("Thickener / stabiliser", "Used to improve texture, viscosity or stability."),
    "calcium carbonate": ("Mineral / acidity regulator", "Used for functional or acidity-related purposes depending on the food."),
    "potassium chloride": ("Mineral salt / salt substitute", "Can provide mineral salt functionality or replace part of sodium chloride in some foods."),
    "sodium carbonate": ("Raising agent / acidity regulator", "Used for functional processing effects depending on the food category."),
    "caramel iv": ("Colour", "Used to provide brown to dark-brown colour."),
    "disodium 5'-ribonucleotides": ("Flavour enhancer", "Used to strengthen savoury flavour."),
}

def get_additive_function(canonical: str, original: str = "") -> tuple[str, str]:
    key = str(canonical or "").strip().lower()
    if key in ADDITIVE_FUNCTION_HINTS:
        return ADDITIVE_FUNCTION_HINTS[key]
    raw = str(original or "")
    rules = [
        (r"\bcolour\b|\bcolor\b", "Colour"),
        (r"\bflavou?r\s+enhancer\b", "Flavour enhancer"),
        (r"\bacidity\s+regulator\b", "Acidity regulator"),
        (r"\bthickener\b", "Thickener"),
        (r"\bstabiliser\b|\bstabilizer\b", "Stabiliser"),
        (r"\braising\s+agent\b|\bleavening\s+agent\b", "Raising / leavening agent"),
    ]
    for pattern, label in rules:
        if re.search(pattern, raw, flags=re.IGNORECASE):
            return label, "Function wording was detected on the label."
    return "Function not classified", "No function wording is currently stored for this ingredient."

def build_additive_function_rows(normalized_results: list[dict]) -> list[dict]:
    rows = []
    for item in normalized_results:
        if not item.get("ins"):
            continue
        canonical = str(item.get("canonical", "")).strip()
        if not canonical:
            continue
        function, note = get_additive_function(canonical, item.get("original", ""))
        rows.append({
            "Ingredient": canonical.title(),
            "INS": f"INS {item.get('ins')}",
            "Function": function,
            "Label evidence": str(item.get("original", "")).strip() or "—",
            "What it means": note,
        })
    return rows

def build_product_glance(normalized_results: list[dict], allergens: list[dict], nutrition: dict, regulatory_results: list[dict]) -> dict:
    """Compact label-analysis counts for the product overview."""
    total = len([x for x in normalized_results if str(x.get("canonical", "")).strip()])
    additives = sum(1 for x in normalized_results if x.get("ins"))
    nutrition_values = int(nutrition.get("value_count", 0) or 0)
    flagged_country_records = 0
    countries_with_records = set()
    for item in regulatory_results:
        for country, data in (item.get("record", {}) or {}).get("jurisdictions", {}).items():
            countries_with_records.add(country)
            status = str((data or {}).get("status", "") or "").upper()
            if status in {"BANNED", "NOT_AUTHORISED", "RESTRICTED", "CHECK_CONDITIONS", "CONDITIONAL", "CONDITIONS"}:
                flagged_country_records += 1
    return {
        "ingredients": total,
        "additives": additives,
        "allergen_types": len(allergens),
        "nutrition_values": nutrition_values,
        "countries": len(countries_with_records),
        "flagged_country_records": flagged_country_records,
    }


def build_ingredient_audit_rows(normalized_results: list[dict]) -> list[dict]:
    """Show the evidence path from OCR text to the normalized ingredient."""
    rows = []
    for rank, item in enumerate(normalized_results, start=1):
        canonical = str(item.get("canonical", "")).strip()
        if not canonical:
            continue
        validation = item.get("validation", {}) or {}
        correction = item.get("text_correction", {}) or {}
        confidence = item.get("confidence", 0)
        try:
            confidence_pct = round(float(confidence) * 100)
        except Exception:
            confidence_pct = 0
        if confidence_pct >= 90:
            confidence_label = f"🟢 {confidence_pct}%"
        elif confidence_pct >= 75:
            confidence_label = f"🟡 {confidence_pct}%"
        else:
            confidence_label = f"🟠 {confidence_pct}%"
        if validation.get("status") == "UNKNOWN_CODE":
            review = "Review unknown additive code"
        elif item.get("error"):
            review = "Normalization error"
        elif correction.get("changed"):
            review = "OCR cleanup applied"
        elif validation.get("status") == "OCR_CORRECTED":
            review = "OCR code correction applied"
        else:
            review = "Looks consistent"
        rows.append({
            "Rank": rank,
            "OCR text": str(item.get("original", "")).strip() or "—",
            "Corrected text": str(item.get("ocr_text", "")).strip() or "—",
            "Normalized ingredient": canonical.title(),
            "INS": f"INS {item.get('ins')}" if item.get("ins") else "—",
            "Confidence": confidence_label,
            "Method": str(item.get("method", "—")),
            "Review": review,
        })
    return rows


def build_review_queue(ingredient_audit_rows: list[dict]) -> list[dict]:
    return [
        row for row in ingredient_audit_rows
        if ("🟠" in str(row.get("Confidence", "")))
        or row.get("Review") not in {"Looks consistent"}
    ]


def build_review_action_checklist(summary_rows: list[dict], allergens: list[dict], label_checks: list[dict], review_queue: list[dict], nutrition: dict, regulatory_differences: list[dict], source_quality: dict) -> list[dict]:
    """Turn existing evidence into a practical review checklist without inventing facts."""
    rows = []
    flags = [str(r.get("Regulatory flag", "")) for r in summary_rows]
    if any("Prohibited" in f for f in flags):
        rows.append({"Priority":"High","Action":"Review prohibited/not-authorised findings","Why":"At least one checked jurisdiction has a prohibited or not-authorised finding.","Evidence":"Regulatory summary"})
    if any("Restricted" in f for f in flags):
        rows.append({"Priority":"High","Action":"Check restricted-use conditions","Why":"At least one checked jurisdiction has a restricted finding.","Evidence":"Regulatory summary"})
    if regulatory_differences:
        rows.append({"Priority":"Medium","Action":"Compare country-specific rules","Why":"At least one ingredient has different stored status findings across jurisdictions.","Evidence":"Regulatory differences"})
    if allergens:
        rows.append({"Priority":"High","Action":"Review detected allergen declarations","Why":"Potential allergens were identified from the ingredient names.","Evidence":"Allergen analysis"})
    for check in label_checks:
        if check.get("Scan result") != "✅ Detected" and check.get("Check") in {"Ingredient list", "Nutrition panel", "Allergen statement"}:
            rows.append({"Priority":"Medium","Action":f"Recheck {str(check.get('Check','label section')).lower()}","Why":str(check.get("Evidence","")),"Evidence":"Label completeness scan"})
    if review_queue:
        rows.append({"Priority":"Medium","Action":"Review uncertain ingredient matches","Why":f"{len(review_queue)} ingredient identification row(s) contain corrections, lower confidence, or an unknown code.","Evidence":"Ingredient verification audit"})
    if nutrition.get("section_detected") and nutrition.get("value_count",0)==0:
        rows.append({"Priority":"Medium","Action":"Retake nutrition-panel photo","Why":"Nutrition wording was detected but numeric values were not extracted reliably.","Evidence":"Nutrition OCR"})
    total=source_quality.get("total_records",0)
    links=source_quality.get("with_source_url",0)
    verified=source_quality.get("with_verified_date",0)
    if total and (links < total or verified < total):
        rows.append({"Priority":"Low","Action":"Check source metadata where available","Why":f"{total} regulatory records were checked; {links} have source links and {verified} have verification dates.","Evidence":"Regulatory source quality"})
    if not rows:
        rows.append({"Priority":"Low","Action":"No additional review flag from current checks","Why":"The current evidence did not generate a specific follow-up item.","Evidence":"Current scan"})
    order={"High":0,"Medium":1,"Low":2}
    return sorted(rows, key=lambda r:(order.get(r.get("Priority"),9), str(r.get("Action",""))))


def build_ingredient_compare_rows(regulatory_results: list[dict], ingredients: list[str], countries: list[str]) -> list[dict]:
    """Build a compact side-by-side country matrix for up to three selected ingredients."""
    selected={str(x).strip().lower():str(x).strip().title() for x in ingredients if str(x).strip()}
    if not selected:
        return []
    by_ing={}
    for result in regulatory_results:
        name=str(result.get("ingredient","")).strip()
        if name.lower() not in selected:
            continue
        row=by_ing.setdefault(selected[name.lower()], {})
        for country,data in (result.get("record",{}) or {}).get("jurisdictions",{}).items():
            if not countries or country in countries:
                status=str((data or {}).get("status","UNKNOWN") or "UNKNOWN").upper()
                level=str((data or {}).get("maximum_level","") or "").strip()
                unit=str((data or {}).get("unit","") or "").strip()
                level_text=f"{level} {unit}".strip() if level else ""
                row[country]=get_status_display(status)+(f" · {level_text}" if level_text else "")
    out=[]
    for ingredient in sorted(by_ing):
        item={"Ingredient":ingredient}
        for country in countries:
            item[country]=by_ing[ingredient].get(country,"—")
        out.append(item)
    return out


def build_metadata_completeness(source_quality: dict) -> dict:
    total=int(source_quality.get("total_records",0) or 0)
    if not total:
        return {"score":0,"label":"No records","note":"No stored regulatory records were available to score."}
    components=[source_quality.get("with_source_url",0)/total, source_quality.get("with_authority",0)/total, source_quality.get("with_verified_date",0)/total]
    score=round(sum(components)/len(components)*100)
    if score>=85: label="Strong metadata coverage"
    elif score>=65: label="Moderate metadata coverage"
    else: label="Limited metadata coverage"
    return {"score":score,"label":label,"note":"This score measures metadata completeness only; it does not measure whether the underlying legal record is correct or current."}


def build_ingredient_audit_csv(ingredient_audit_rows: list[dict]) -> str:
    fields = ["Rank", "OCR text", "Corrected text", "Normalized ingredient", "INS", "Confidence", "Method", "Review"]
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=fields, extrasaction="ignore")
    writer.writeheader()
    writer.writerows(ingredient_audit_rows)
    return buffer.getvalue()


def build_regulatory_source_quality(regulatory_results: list[dict]) -> dict:
    records = []
    for item in regulatory_results:
        records.extend((item.get("record", {}) or {}).get("jurisdictions", {}).values())
    total = len(records)
    return {
        "total_records": total,
        "with_source_url": sum(1 for d in records if str(d.get("source_url", "") or "").strip()),
        "with_authority": sum(1 for d in records if str(d.get("authority", "") or "").strip()),
        "with_verified_date": sum(1 for d in records if str(d.get("verified_date", "") or "").strip()),
    }

def build_jurisdiction_attention_rows(regulatory_results: list[dict]) -> list[dict]:
    by_country = {}
    for item in regulatory_results:
        for country, data in (item.get("record", {}) or {}).get("jurisdictions", {}).items():
            row = by_country.setdefault(country, {"Country": country, "Records": 0, "Prohibited": 0, "Restricted": 0, "Conditions": 0})
            row["Records"] += 1
            status = str((data or {}).get("status", "UNKNOWN") or "UNKNOWN").upper()
            if status in {"BANNED", "NOT_AUTHORISED"}:
                row["Prohibited"] += 1
            elif status == "RESTRICTED":
                row["Restricted"] += 1
            elif status in {"CHECK_CONDITIONS", "CONDITIONAL", "CONDITIONS"}:
                row["Conditions"] += 1
    return sorted(by_country.values(), key=lambda r: (-r["Prohibited"], -r["Restricted"], -r["Conditions"], r["Country"].lower()))

def build_json_export(summary_rows, comparison_rows, allergens, nutrition, label_checks, ingredient_order_rows, additive_function_rows, scan_clarity, ingredient_audit_rows=None, product_glance=None, regulatory_differences=None, screening_decision=None, review_action_checklist=None, metadata_completeness=None) -> str:
    return json.dumps({
        "product": "FoodReg AI analysis",
        "summary": summary_rows,
        "country_comparison": comparison_rows,
        "allergens": allergens,
        "nutrition": nutrition,
        "label_completeness": label_checks,
        "ingredient_order": ingredient_order_rows,
        "additive_functions": additive_function_rows,
        "scan_clarity": scan_clarity,
        "ingredient_audit": ingredient_audit_rows or [],
        "regulatory_differences": regulatory_differences or [],
        "screening_decision": screening_decision or {},
        "review_action_checklist": review_action_checklist or [],
        "metadata_completeness": metadata_completeness or {},
        "product_glance": product_glance or {},
    }, indent=2, ensure_ascii=False)

def build_html_report(
    summary_rows: list[dict],
    comparison_rows: list[dict],
    allergens: list[dict],
    nutrition: dict | None = None,
    label_checks: list[dict] | None = None,
    ingredient_order_rows: list[dict] | None = None,
    scan_clarity: dict | None = None,
    additive_function_rows: list[dict] | None = None,
    jurisdiction_attention_rows: list[dict] | None = None,
    ingredient_audit_rows: list[dict] | None = None,
    product_glance: dict | None = None,
    review_action_checklist: list[dict] | None = None,
    metadata_completeness: dict | None = None,
) -> str:
    if allergens:
        cards = []
        for item in allergens:
            cards.append(
                f"<li><b>{escape(item['allergen'])}</b> — "
                f"found in: {escape(', '.join(item['ingredients']))}</li>"
            )
        allergen_html = "<h2>Allergen alerts</h2><ul>" + "".join(cards) + "</ul>"
    else:
        allergen_html = (
            "<h2>Allergen alerts</h2>"
            "<p>No common allergens were detected from the identified ingredient names.</p>"
        )

    summary_rows_html = []
    for row in summary_rows:
        summary_rows_html.append(
            "<tr>"
            f"<td>{escape(str(row.get('Ingredient', '')))}</td>"
            f"<td>{escape(str(row.get('INS', '—')))}</td>"
            f"<td>{escape(str(row.get('Regulatory flag', '')))}</td>"
            f"<td>{escape(str(row.get('Ingredient type', '')))}</td>"
            f"<td>{escape(str(row.get('Why flagged', '')))}</td>"
            f"<td>{escape(str(row.get('Covered countries', '—')))}</td>"
            "</tr>"
        )

    nutrition = nutrition or {}
    label_checks = label_checks or []
    ingredient_order_rows = ingredient_order_rows or []
    additive_function_rows = additive_function_rows or []
    jurisdiction_attention_rows = jurisdiction_attention_rows or []
    ingredient_audit_rows = ingredient_audit_rows or []
    product_glance = product_glance or {}
    review_action_checklist = review_action_checklist or []
    metadata_completeness = metadata_completeness or {}
    nutrition_comparison = build_nutrition_comparison(nutrition)
    scan_clarity = scan_clarity or {}

    nutrition_items = []
    nutrition_labels = {
        "energy_kcal": "Energy (kcal)", "energy_kj": "Energy (kJ)",
        "total_fat_g": "Total fat (g)", "saturated_fat_g": "Saturated fat (g)",
        "trans_fat_g": "Trans fat (g)", "cholesterol_mg": "Cholesterol (mg)",
        "sodium_mg": "Sodium (mg)", "carbohydrate_g": "Carbohydrate (g)",
        "fiber_g": "Dietary fibre (g)", "total_sugars_g": "Total sugars (g)",
        "added_sugars_g": "Added sugars (g)", "protein_g": "Protein (g)",
    }
    for key, label in nutrition_labels.items():
        value = nutrition.get(key)
        if value is not None:
            nutrition_items.append(f"<li><b>{escape(label)}</b>: {escape(str(value))}</li>")
    nutrition_basis = []
    if nutrition.get("serving_size"):
        nutrition_basis.append(f"Serving size: {escape(str(nutrition['serving_size']))}")
    if nutrition.get("servings_per_container"):
        nutrition_basis.append(f"Servings/container: {escape(str(nutrition['servings_per_container']))}")
    if nutrition.get("declared_basis"):
        nutrition_basis.append(f"Declared basis: {escape(str(nutrition['declared_basis']))}")
    nutrition_html = "<h2>Nutrition snapshot</h2>"
    if nutrition_items:
        if nutrition_basis:
            nutrition_html += "<p>" + " | ".join(nutrition_basis) + "</p>"
        nutrition_html += "<ul>" + "".join(nutrition_items) + "</ul>"
    else:
        nutrition_html += "<p>No clear nutrition values were extracted from the OCR scan.</p>"

    order_rows_html = []
    for row in ingredient_order_rows:
        order_rows_html.append("<tr>" + f"<td>{escape(str(row.get('Rank','')))}</td>" + f"<td>{escape(str(row.get('Ingredient','')))}</td>" + f"<td>{escape(str(row.get('Type','')))}</td>" + f"<td>{escape(str(row.get('Label prominence','')))}</td>" + f"<td>{escape(str(row.get('Prominence score','—')))}</td></tr>")

    additive_rows_html = []
    for row in additive_function_rows:
        additive_rows_html.append(
            "<tr>"
            f"<td>{escape(str(row.get('Ingredient','')))}</td>"
            f"<td>{escape(str(row.get('INS','')))}</td>"
            f"<td>{escape(str(row.get('Function','')))}</td>"
            f"<td>{escape(str(row.get('Label evidence','')))}</td>"
            f"<td>{escape(str(row.get('What it means','')))}</td></tr>"
        )

    jurisdiction_rows_html = []
    for row in jurisdiction_attention_rows:
        jurisdiction_rows_html.append(
            "<tr>"
            f"<td>{escape(str(row.get('Country','')))}</td>"
            f"<td>{escape(str(row.get('Records',0)))}</td>"
            f"<td>{escape(str(row.get('Prohibited',0)))}</td>"
            f"<td>{escape(str(row.get('Restricted',0)))}</td>"
            f"<td>{escape(str(row.get('Conditions',0)))}</td></tr>"
        )

    check_rows_html = []
    for row in label_checks:
        check_rows_html.append("<tr>" + f"<td>{escape(str(row.get('Check','')))}</td>" + f"<td>{escape(str(row.get('Scan result','')))}</td>" + f"<td>{escape(str(row.get('Evidence','')))}</td></tr>")

    nutrition_compare_rows_html = []
    for row in nutrition_comparison.get("rows", []):
        nutrition_compare_rows_html.append(
            "<tr>"
            f"<td>{escape(str(row.get('Nutrient','')))}</td>"
            f"<td>{escape(str(row.get('Label value','')))}</td>"
            f"<td>{escape(str(row.get('Comparison','')))}</td>"
            f"<td>{escape(str(row.get('Basis','')))}</td>"
            "</tr>"
        )

    audit_rows_html = []
    for row in ingredient_audit_rows:
        audit_rows_html.append(
            "<tr>"
            f"<td>{escape(str(row.get('Rank','')))}</td>"
            f"<td>{escape(str(row.get('OCR text','')))}</td>"
            f"<td>{escape(str(row.get('Normalized ingredient','')))}</td>"
            f"<td>{escape(str(row.get('INS','—')))}</td>"
            f"<td>{escape(str(row.get('Confidence','')))}</td>"
            f"<td>{escape(str(row.get('Review','')))}</td></tr>"
        )

    review_rows_html=[]
    for row in review_action_checklist:
        review_rows_html.append("<tr>" + f"<td>{escape(str(row.get('Priority','')))}</td>" + f"<td>{escape(str(row.get('Action','')))}</td>" + f"<td>{escape(str(row.get('Why','')))}</td>" + f"<td>{escape(str(row.get('Evidence','')))}</td></tr>")

    country_rows_html = []
    for row in comparison_rows:
        country_rows_html.append(
            "<tr>"
            f"<td>{escape(str(row.get('Ingredient', '')))}</td>"
            f"<td>{escape(str(row.get('Country', '')))}</td>"
            f"<td>{escape(str(row.get('Status', '')))}</td>"
            f"<td>{escape(str(row.get('Legal level', '')))}</td>"
            f"<td>{escape(str(row.get('Condition', '')))}</td>"
            f"<td>{escape(str(row.get('Food category', '—')))}</td>"
            "</tr>"
        )

    return f"""<!doctype html>
<html>
<head>
<meta charset="utf-8">
<title>FoodReg AI Report</title>
<style>
body {{ font-family: Arial, sans-serif; background:#fff7de; color:#2e2020; margin:0; }}
header {{ background:#8f1f1f; color:#fff7de; padding:28px 34px; }}
main {{ padding:28px 34px; }}
h1,h2 {{ color:#7b1515; }}
table {{ width:100%; border-collapse:collapse; margin:14px 0 28px; background:#fffdf7; }}
th,td {{ border:1px solid #e4cf8a; padding:8px; text-align:left; vertical-align:top; }}
th {{ background:#f2c94c; color:#4b1f1f; }}
.note {{ padding:12px 14px; background:#fff0ad; border-left:4px solid #9a1b1b; }}
</style>
</head>
<body>
<header><h1>🥫 FoodReg AI</h1><div>Ingredient and international regulatory report</div></header>
<main>
{allergen_html}
{nutrition_html}
<h2>Comparable nutrition view</h2>
<p>{escape(str(nutrition_comparison.get('note', '')))}</p>
<table>
<thead><tr><th>Nutrient</th><th>Label value</th><th>Comparison</th><th>Basis</th></tr></thead>
<tbody>{''.join(nutrition_compare_rows_html) if nutrition_compare_rows_html else '<tr><td colspan="4">No valid basis for a comparable nutrition conversion.</td></tr>'}</tbody>
</table>
<h2>Ingredient verification audit</h2>
<table>
<thead><tr><th>Rank</th><th>OCR text</th><th>Normalized ingredient</th><th>INS</th><th>Confidence</th><th>Review</th></tr></thead>
<tbody>{''.join(audit_rows_html) if audit_rows_html else '<tr><td colspan="6">No ingredient audit rows available.</td></tr>'}</tbody>
</table>
<h2>Ingredient order & prominence</h2>
<table>
<thead><tr><th>Rank</th><th>Ingredient</th><th>Type</th><th>Label prominence</th><th>Prominence score</th></tr></thead>
<tbody>{''.join(order_rows_html)}</tbody>
</table>
<h2>Additive function guide</h2>
<table>
<thead><tr><th>Ingredient</th><th>INS</th><th>Function</th><th>Label evidence</th><th>What it means</th></tr></thead>
<tbody>{''.join(additive_rows_html) if additive_rows_html else '<tr><td colspan="5">No food additives with a stored function were identified.</td></tr>'}</tbody>
</table>
<h2>Jurisdiction attention summary</h2>
<table>
<thead><tr><th>Country</th><th>Records</th><th>Prohibited</th><th>Restricted</th><th>Conditions</th></tr></thead>
<tbody>{''.join(jurisdiction_rows_html) if jurisdiction_rows_html else '<tr><td colspan="5">No jurisdiction summary available.</td></tr>'}</tbody>
</table>
<h2>Scan clarity</h2>
<p><b>{escape(str(scan_clarity.get('level', 'Not calculated')))}</b> — score {escape(str(scan_clarity.get('score', '—')))}/100; OCR lines {escape(str(scan_clarity.get('line_count', '—')))}; uncertain ingredient matches {escape(str(scan_clarity.get('uncertain_items', '—')))}.</p>
<h2>Label completeness scan</h2>
<table>
<thead><tr><th>Check</th><th>Scan result</th><th>Evidence</th></tr></thead>
<tbody>{''.join(check_rows_html)}</tbody>
</table>
<h2>Review action checklist</h2>
<table><thead><tr><th>Priority</th><th>Action</th><th>Why</th><th>Evidence</th></tr></thead><tbody>{''.join(review_rows_html) if review_rows_html else '<tr><td colspan="4">No checklist available.</td></tr>'}</tbody></table>
<h2>Regulatory metadata completeness</h2>
<p><b>{escape(str(metadata_completeness.get("score", "—")))}/100</b> — {escape(str(metadata_completeness.get("label", "Not calculated")))}. {escape(str(metadata_completeness.get("note", "")))}</p>
<h2>Regulatory summary</h2>
<table>
<thead><tr><th>Ingredient</th><th>INS</th><th>Flag</th><th>Type</th><th>Why flagged</th><th>Countries</th></tr></thead>
<tbody>{''.join(summary_rows_html)}</tbody>
</table>
<h2>Country comparison</h2>
<table>
<thead><tr><th>Ingredient</th><th>Country</th><th>Status</th><th>Legal level</th><th>Condition</th><th>Food category</th></tr></thead>
<tbody>{''.join(country_rows_html)}</tbody>
</table>
<div class="note">Regulatory findings are based only on records currently stored in the FoodReg AI database. A missing record is not a declaration of safety or approval.</div>
</main>
</body>
</html>"""


# =========================================================

# PAGE CONFIGURATION

# =========================================================


st.set_page_config(

    page_title="FoodReg AI",

    page_icon="🥫",

    layout="wide",

)


# =========================================================

# CUSTOM CSS
# =========================================================


st.markdown(
    """
    <style>
    :root {
        --cream: #FFF7DE;
        --paper: #FFFDF7;
        --red: #9A1B1B;
        --red-dark: #651313;
        --yellow: #F2C94C;
        --yellow-soft: #FFF0AD;
        --ink: #2E2020;
        --muted: #6C5B5B;
        --line: #E4CF8A;
    }

    .stApp {
        background: linear-gradient(180deg, #FFF8E5 0%, #FFF1BF 52%, #F8E3A7 100%);
        color: var(--ink);
    }
    .main .block-container { padding-top: 1.1rem; padding-bottom: 3rem; max-width: 1420px; }
    .block-container { color: var(--ink); }

    .main-title { font-size: 46px; line-height: 1.05; font-weight: 850; letter-spacing: -0.9px; color: var(--red-dark); margin-bottom: 4px; }
    .subtitle { font-size: 17px; color: var(--muted); margin-bottom: 22px; }
    .section-title { font-size: 24px; font-weight: 800; color: var(--red-dark); margin-top: 24px; margin-bottom: 12px; }

    .hero-card {
        background: linear-gradient(135deg, #8D1B1B 0%, #A62828 68%, #B63A2C 100%);
        border: 2px solid var(--yellow); border-radius: 18px; padding: 24px 26px; margin: 10px 0 22px 0;
        box-shadow: 0 14px 30px rgba(143,29,29,0.20);
    }
    .hero-kicker { color: #FFE48A; font-size: 13px; font-weight: 850; text-transform: uppercase; letter-spacing: 1.1px; margin-bottom: 6px; }
    .hero-title { color: #FFFDF7; font-size: 30px; font-weight: 850; margin-bottom: 5px; }
    .hero-text { color: #FFF4D8; font-size: 15px; line-height: 1.5; max-width: 900px; }

    .ingredient-card, .insight-card, .info-box {
        padding: 15px 17px; border-radius: 14px; border: 1px solid var(--line); margin-bottom: 10px;
        background: rgba(255,253,247,0.95); color: var(--ink); box-shadow: 0 6px 16px rgba(126,88,10,0.08);
    }
    .ingredient-name { font-size: 17px; font-weight: 750; color: var(--red-dark); }
    .ingredient-code { color: #8A6500; font-size: 13px; font-weight: 800; margin-top: 3px; }

    .alert-card { background: #FFF0EE; border: 1px solid #E8ABA4; border-left: 5px solid #D62828; border-radius: 14px; padding: 14px 16px; margin-bottom: 10px; box-shadow: 0 6px 16px rgba(143,29,29,0.10); }
    .alert-title { font-size: 17px; font-weight: 850; color: #A71919; }
    .alert-meta { color: #6E3A35; font-size: 13px; margin-top: 4px; }

    .stButton > button {
        background: linear-gradient(135deg, #921D1D, #B62626); color: #FFFDF7; border: 1px solid var(--yellow);
        border-radius: 10px; font-weight: 800; box-shadow: 0 7px 15px rgba(143,29,29,0.16);
    }
    .stButton > button:hover { background: linear-gradient(135deg, #A92121, #C52D2D); border-color: #F7D66D; }
    .stButton > button:focus { box-shadow: 0 0 0 0.2rem rgba(242,201,76,0.35); }

    [data-testid="stMetric"] { background: rgba(255,253,247,0.95); border: 1px solid var(--line); border-radius: 14px; padding: 12px 14px; box-shadow: 0 6px 16px rgba(126,88,10,0.08); }
    [data-testid="stMetricLabel"] { color: #7B6868 !important; }
    [data-testid="stMetricValue"] { color: var(--red-dark) !important; }

    [data-testid="stFileUploader"] { background: rgba(255,253,247,0.95); border: 2px dashed #D7A813; border-radius: 14px; padding: 8px; }
    [data-testid="stFileUploaderDropzone"] { background: #FFF9EA; border-color: #DDBB55; color: var(--ink); }
    [data-testid="stFileUploaderDropzoneInstructions"] { color: #665252 !important; }

    .stSelectbox > div > div, .stMultiSelect > div > div, .stTextInput > div > div { background: #FFFDF7 !important; color: var(--ink) !important; border-color: #D7C27A !important; }
    .stSelectbox label, .stMultiSelect label, .stTextInput label { color: #644D4D !important; }

    [data-testid="stDataFrame"] { border: 1px solid var(--line); border-radius: 12px; overflow: hidden; box-shadow: 0 6px 16px rgba(126,88,10,0.08); }
    [data-testid="stExpander"] { background: rgba(255,253,247,0.95); border: 1px solid var(--line); border-radius: 12px; }
    hr { border-color: #E6D18B !important; }
    .source-note { font-size: 12px; color: #7D6868; }
    .section-caption { color: #6D5B5B !important; }
    </style>
    """,
    unsafe_allow_html=True,
)


# =========================================================

# HEADER

# =========================================================


st.markdown(

    '<div class="main-title">🥫 FoodReg AI</div>',

    unsafe_allow_html=True,

)


st.markdown(

    '<div class="subtitle">'

    "Upload an ingredient label to identify ingredients and "

    "compare available regulatory information across countries."

    "</div>",

    unsafe_allow_html=True,

)

st.markdown(
    """
    <div class="hero-card">
        <div class="hero-kicker">International food-label intelligence</div>
        <div class="hero-title">Know what is in your food. Know how it is regulated.</div>
        <div class="hero-text">OCR the label, identify ingredients and allergens, then compare regulatory conditions across jurisdictions using the records currently stored in FoodReg AI.</div>
    </div>
    """,
    unsafe_allow_html=True,
)


# =========================================================

# OCR MODEL

# =========================================================


@st.cache_resource

def load_ocr():

    return PaddleOCR(

        lang="en",

        enable_mkldnn=False,

        device="cpu",

    )


# =========================================================

# IMAGE PREPROCESSING

# =========================================================


def preprocess_image(image_np: np.ndarray) -> np.ndarray:

    image = image_np.copy()


    height, width = image.shape[:2]

    min_width = 1400


    if width < min_width:

        scale = min_width / width

        new_width = int(width * scale)

        new_height = int(height * scale)


        image = cv2.resize(

            image,

            (new_width, new_height),

            interpolation=cv2.INTER_CUBIC,

        )


    gray = cv2.cvtColor(

        image,

        cv2.COLOR_RGB2GRAY,

    )


    clahe = cv2.createCLAHE(

        clipLimit=2.0,

        tileGridSize=(8, 8),

    )


    enhanced = clahe.apply(gray)


    enhanced = cv2.GaussianBlur(

        enhanced,

        (3, 3),

        0,

    )


    return enhanced


# =========================================================

# TEXT HELPERS

# =========================================================


def clean_text(text: str) -> str:

    text = text.replace("\n", " ")

    text = text.replace("\r", " ")

    text = text.replace(";", ",")


    text = re.sub(

        r"\s+",

        " ",

        text,

    )


    return text.strip()

# =========================================================
# NUTRITION + LABEL QUALITY HELPERS
# =========================================================

def _first_regex_value(text: str, patterns: list[str]):
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            return match.group(1).strip()
    return None


def extract_nutrition_facts(detected_text: list[str]) -> dict:
    """Extract nutrition values only when the OCR text explicitly contains them."""
    joined = clean_text(" ".join(detected_text))
    lower = joined.lower()
    heading_detected = any(marker in lower for marker in [
        "nutrition facts", "nutrition information", "nutritional information",
    ])
    numeric_markers = [
        r"\benergy\s*[:\-]?\s*[0-9]+(?:\.[0-9]+)?\s*(?:kcal|kj)\b",
        r"\b(?:total\s+)?fat\s*[:\-]?\s*[0-9]+(?:\.[0-9]+)?\s*g\b",
        r"\b(?:total\s+)?carbohydrate[s]?\s*[:\-]?\s*[0-9]+(?:\.[0-9]+)?\s*g\b",
        r"\b(?:total\s+)?sugars?\s*[:\-]?\s*[0-9]+(?:\.[0-9]+)?\s*g\b",
        r"\bprotein\s*[:\-]?\s*[0-9]+(?:\.[0-9]+)?\s*g\b",
        r"\bsodium\s*[:\-]?\s*[0-9]+(?:\.[0-9]+)?\s*mg\b",
    ]
    numeric_field_count = sum(1 for pattern in numeric_markers if re.search(pattern, joined, flags=re.IGNORECASE))
    result = {
        "section_detected": heading_detected or numeric_field_count >= 2,
        "serving_size": _first_regex_value(joined, [
            r"\bserv(?:ing|e)\s+size\s*[:\-]?\s*([^,;|]+?)(?=\s+(?:servings?|energy|calories|calorie|protein|total\s+fat|carbohydrate|sodium)\b|$)",
            r"\bserving\s*[:\-]?\s*([0-9]+(?:\.[0-9]+)?\s*(?:g|kg|mg|ml|l|oz|fl\.?\s*oz))\b",
        ]),
        "servings_per_container": _first_regex_value(joined, [r"\bservings?\s+per\s+(?:container|pack|package)\s*[:\-]?\s*([0-9]+(?:\.[0-9]+)?)"]),
    }
    patterns = {
        "energy_kcal": [r"\b(?:energy|calories|calorie)\s*[:\-]?\s*([0-9]+(?:\.[0-9]+)?)\s*kcal\b"],
        "energy_kj": [r"\benergy\s*[:\-]?\s*([0-9]+(?:\.[0-9]+)?)\s*kj\b"],
        "total_fat_g": [r"\b(?:total\s+)?fat\s*[:\-]?\s*([0-9]+(?:\.[0-9]+)?)\s*g\b"],
        "saturated_fat_g": [r"\b(?:saturated|sat\.?)[ -]?fat\s*[:\-]?\s*([0-9]+(?:\.[0-9]+)?)\s*g\b"],
        "trans_fat_g": [r"\btrans\s+fat\s*[:\-]?\s*([0-9]+(?:\.[0-9]+)?)\s*g\b"],
        "cholesterol_mg": [r"\bcholesterol\s*[:\-]?\s*([0-9]+(?:\.[0-9]+)?)\s*mg\b"],
        "sodium_mg": [r"\bsodium\s*[:\-]?\s*([0-9]+(?:\.[0-9]+)?)\s*mg\b"],
        "carbohydrate_g": [r"\b(?:total\s+)?carbohydrate[s]?\s*[:\-]?\s*([0-9]+(?:\.[0-9]+)?)\s*g\b"],
        "fiber_g": [r"\b(?:dietary\s+)?f(?:i|1)ber\s*[:\-]?\s*([0-9]+(?:\.[0-9]+)?)\s*g\b"],
        "total_sugars_g": [r"\b(?:total\s+)?sugars?\s*[:\-]?\s*([0-9]+(?:\.[0-9]+)?)\s*g\b"],
        "added_sugars_g": [r"\badded\s+sugars?\s*[:\-]?\s*([0-9]+(?:\.[0-9]+)?)\s*g\b"],
        "protein_g": [r"\bprotein\s*[:\-]?\s*([0-9]+(?:\.[0-9]+)?)\s*g\b"],
    }
    for key, pats in patterns.items():
        result[key] = _first_regex_value(joined, pats)
    result["value_count"] = sum(1 for key in patterns if result.get(key) is not None)
    basis = re.search(r"\b(per\s+(?:100\s*g|100\s*ml|serving|serve|portion))\b", joined, flags=re.IGNORECASE)
    result["declared_basis"] = basis.group(1) if basis else None
    return result


def _parse_mass_grams(value: str | None) -> float | None:
    if not value:
        return None
    match = re.search(r"([0-9]+(?:\.[0-9]+)?)\s*(kg|g|mg)\b", str(value), flags=re.IGNORECASE)
    if not match:
        return None
    amount = float(match.group(1))
    unit = match.group(2).lower()
    if unit == "kg":
        return amount * 1000.0
    if unit == "mg":
        return amount / 1000.0
    return amount


def build_nutrition_comparison(nutrition: dict) -> dict:
    """Compare nutrition values only when the label basis supports a valid conversion."""
    fields = [
        ("Energy", "energy_kcal", "kcal"),
        ("Protein", "protein_g", "g"),
        ("Carbohydrate", "carbohydrate_g", "g"),
        ("Total sugars", "total_sugars_g", "g"),
        ("Total fat", "total_fat_g", "g"),
        ("Sodium", "sodium_mg", "mg"),
        ("Dietary fibre", "fiber_g", "g"),
        ("Saturated fat", "saturated_fat_g", "g"),
        ("Added sugars", "added_sugars_g", "g"),
    ]
    rows = []
    basis = str(nutrition.get("declared_basis") or "").lower()
    serving_g = _parse_mass_grams(nutrition.get("serving_size"))

    if "100 g" in basis or "100g" in basis:
        target_label = "Estimated per serving" if serving_g else "Per 100 g"
        factor = serving_g / 100.0 if serving_g else None
        for label, key, unit in fields:
            value = nutrition.get(key)
            if value is None:
                continue
            numeric = float(value)
            converted = numeric * factor if factor is not None else None
            rows.append({
                "Nutrient": label,
                "Label value": f"{numeric:g} {unit}",
                "Comparison": f"{converted:g} {unit}" if converted is not None else "—",
                "Basis": target_label,
            })
        note = (
            f"Converted from the label's per 100 g basis using the detected serving size ({nutrition.get('serving_size')})."
            if serving_g else
            "The label uses a per 100 g basis, but no usable serving mass was detected, so no per-serving conversion was made."
        )
        return {"rows": rows, "note": note, "source_basis": "per 100 g", "target_basis": target_label}

    if "serving" in basis or "serve" in basis or "portion" in basis:
        target_label = "Estimated per 100 g" if serving_g else "Per serving"
        factor = 100.0 / serving_g if serving_g else None
        for label, key, unit in fields:
            value = nutrition.get(key)
            if value is None:
                continue
            numeric = float(value)
            converted = numeric * factor if factor is not None else None
            rows.append({
                "Nutrient": label,
                "Label value": f"{numeric:g} {unit}",
                "Comparison": f"{converted:g} {unit}" if converted is not None else "—",
                "Basis": target_label,
            })
        note = (
            f"Converted from the label's per-serving basis using the detected serving size ({nutrition.get('serving_size')})."
            if serving_g else
            "The label uses a per-serving basis, but no usable serving mass was detected, so no per-100 g conversion was made."
        )
        return {"rows": rows, "note": note, "source_basis": "per serving", "target_basis": target_label}

    return {
        "rows": [],
        "note": "A comparable per-serving/per-100 g basis could not be established from the detected label text.",
        "source_basis": nutrition.get("declared_basis") or "Not detected",
        "target_basis": "Not calculated",
    }


def build_scan_clarity_summary(
    detected_text: list[str],
    ingredient_section: str,
    normalized_results: list[dict],
    correction_count: int,
) -> dict:
    """Estimate scan clarity from observable OCR/extraction signals; this is not raw OCR confidence."""
    line_count = len([line for line in detected_text if str(line).strip()])
    uncertain = sum(1 for item in normalized_results if float(item.get("confidence", 1.0) or 0.0) < 0.75)
    normalization_errors = sum(1 for item in normalized_results if item.get("error"))
    score = 100
    reasons = []
    if line_count < 5:
        score -= 30
        reasons.append("Low OCR text volume")
    elif line_count < 10:
        score -= 10
        reasons.append("Limited OCR text volume")
    if not ingredient_section.strip():
        score -= 40
        reasons.append("Ingredient section not isolated")
    elif len(ingredient_section.strip()) < 25:
        score -= 15
        reasons.append("Very short ingredient section")
    if correction_count:
        score -= min(20, correction_count * 3)
        reasons.append(f"{correction_count} OCR/text correction(s)")
    if uncertain:
        score -= min(20, uncertain * 4)
        reasons.append(f"{uncertain} ingredient match(es) need review")
    if normalization_errors:
        score -= min(25, normalization_errors * 10)
        reasons.append(f"{normalization_errors} normalization error(s)")
    score = max(0, min(100, score))
    level = "🟢 Clear scan" if score >= 85 else "🟡 Review recommended" if score >= 65 else "🟠 Low clarity"
    return {
        "score": score,
        "level": level,
        "line_count": line_count,
        "uncertain_items": uncertain,
        "normalization_errors": normalization_errors,
        "reasons": reasons,
    }


def build_ingredient_order_rows(normalized_results: list[dict]) -> list[dict]:
    total = len(normalized_results)
    rows = []
    for rank, item in enumerate(normalized_results, start=1):
        name = str(item.get("canonical", "")).strip()
        if not name:
            continue
        if total <= 3:
            prominence = "Early listed" if rank <= 2 else "Later listed"
        else:
            fraction = rank / total
            prominence = "Top of ingredient list" if fraction <= 0.33 else "Middle of ingredient list" if fraction <= 0.66 else "Lower part of ingredient list"
        if total <= 1:
            prominence_score = 5
        else:
            prominence_score = max(1, 5 - round((rank - 1) * 4 / max(1, total - 1)))
        rows.append({"Rank": rank, "Ingredient": name.title(), "Type": "Additive" if item.get("ins") else "Food ingredient / compound", "Label prominence": prominence, "Prominence score": f"{prominence_score}/5"})
    return rows


def build_label_completeness_checks(detected_text: list[str], ingredient_section: str, nutrition: dict) -> list[dict]:
    text = clean_text(" ".join(detected_text)).lower()
    checks = [
        ("Ingredient list", bool(ingredient_section.strip()), "Ingredient heading and section detected."),
        ("Nutrition information", bool(nutrition.get("section_detected")), "Nutrition-related text detected by OCR."),
        ("Allergen statement", bool(re.search(r"\b(?:contains|may\s+contain|allergen|allergy|allergens)\b", text)), "Contains/may-contain or allergen wording detected."),
        ("Net quantity", bool(re.search(r"\bnet\s*(?:weight|wt|quantity)\b|\bnet\s+[0-9]+(?:\.[0-9]+)?\s*(?:g|kg|ml|l)\b", text)), "Net quantity wording or value detected."),
        ("Date marking", bool(re.search(r"\b(?:best\s+before|use\s+by|expiry|expires|manufactured\s+on|mfg\.?\s*date)\b", text)), "A date-marking phrase was detected."),
        ("Storage instructions", bool(re.search(r"\b(?:store|storage|keep\s+refrigerated|refrigerate|keep\s+in)\b", text)), "Storage-related wording was detected."),
        ("Manufacturer / packer", bool(re.search(r"\b(?:manufactured\s+by|marketed\s+by|packed\s+by|manufactured\s+for)\b", text)), "Manufacturer/packer wording was detected."),
        ("Batch / lot identifier", bool(re.search(r"\b(?:batch|lot)\s*(?:no\.?|number)?\b", text)), "Batch/lot wording was detected."),
    ]
    return [{"Check": label, "Scan result": "✅ Detected" if present else "⚠️ Not detected", "Evidence": evidence} for label, present, evidence in checks]


# =========================================================

# INGREDIENT SECTION EXTRACTION

# =========================================================


def extract_ingredient_section(

    detected_text: list[str],

) -> str:

    """

    Find the ingredient heading and return only the

    ingredient section.


    We never fall back to the complete OCR text because

    nutrition facts, licence information and storage text

    must not become ingredients.

    """


    joined = clean_text(

        " ".join(detected_text)

    )


    heading_pattern = re.compile(

        r"\b(?:other\s+)?"

        r"(?:ingredients?|ngredients?|ngredent|composition)"

        r"\s*:?\s*",

        flags=re.IGNORECASE,

    )


    heading = heading_pattern.search(

        joined

    )


    if not heading:

        return ""


    section = joined[

        heading.end():

    ]


    # -----------------------------------------------------

    # STOP AT NON-INGREDIENT CONTENT

    # -----------------------------------------------------


    stop_pattern = re.compile(

        r"\b(?:"

        r"contains"

        r"|may\s+contain"

        r"|best\s+before"

        r"|use\s+before"

        r"|licen[cs]e"

        r"|lic\s*\.?\s*no"

        r"|store\s+in"

        r"|storage"

        r"|nutritional?"

        r"|nutrition\s+information"

        r"|manufactured\s+by"

        r"|marketed\s+by"

        r"|customer\s+care"

        r"|mrp"

        r"|net\s*(?:weight|wt)"

        r"|batch\s*(?:no|number)?"

        r"|packed\s+by"

        r")\b",

        flags=re.IGNORECASE,

    )


    stop = stop_pattern.search(

        section

    )


    if stop:

        section = section[

            :stop.start()

        ]


    # -----------------------------------------------------

    # REMOVE SUBSECTION HEADINGS

    # -----------------------------------------------------


    section = re.sub(

        r"\b(?:"

        r"noodle"

        r"|noodles"

        r"|masala\s+tastemaker"

        r"|tastemaker"

        r"|seasoning"

        r")\s*:\s*",

        "",

        section,

        flags=re.IGNORECASE,

    )


    return clean_text(

        section

    )


# =========================================================

# INGREDIENT OCR CLEANUP

# =========================================================


ORDINARY_OCR_REPLACEMENTS = {

    r"\bwheat\s+fur\b": "Wheat Flour",

    r"\bwheat\s+flur\b": "Wheat Flour",

    r"\bwheat\s+flor\b": "Wheat Flour",


    r"\bedible\s+vegetable\s+ol\b":

        "Edible Vegetable Oil",


    r"\bedible\s+vegetable\s+0il\b":

        "Edible Vegetable Oil",


    r"\bedible\s+vegetable\s*$":

        "Edible Vegetable Oil",


    r"\bsal\b":

        "Salt",


    r"\bcalum\b":

        "calcium",


    r"\bcalcuim\b":

        "calcium",


    r"\bcalicium\b":

        "calcium",


    r"\bcabnate\b":

        "carbonate",


    r"\bcarbnate\b":

        "carbonate",


    r"\bgluen\b":

        "gluten",


    r"\bprotien\b":

        "protein",


    r"\bpotasium\b":

        "potassium",


    r"\bchlorde\b":

        "chloride",


    r"\bcloride\b":

        "chloride",


    r"\bspces\b":

        "spices",


    r"\bwhch\b":

        "which",


    r"\bblad\s+pepper\b":

        "black pepper",


    r"\bblak\s+pepper\b":

        "black pepper",


    r"\bhydrolysd\b":

        "hydrolysed",

    r"\bsuga\b":

        "Sugar",

    r"\btumeric\b":

        "turmeric",

}


def clean_ordinary_ingredient_text(

    text: str,

) -> str:


    cleaned = clean_text(text)


    for pattern, replacement in (

        ORDINARY_OCR_REPLACEMENTS.items()

    ):

        cleaned = re.sub(

            pattern,

            replacement,

            cleaned,

            flags=re.IGNORECASE,

        )


    return cleaned


# =========================================================

# SPLIT KNOWN COMBINED INGREDIENT PHRASES

# =========================================================


def split_known_compound_ingredients(

    ingredients: list[str],

) -> list[str]:


    result = []


    for ingredient in ingredients:


        text = clean_ordinary_ingredient_text(

            ingredient

        )


        # -------------------------------------------------

        # OCR / label variants for known INS-coded additives

        # -------------------------------------------------

        if re.fullmatch(

            r"(?:ad\s*ae|acidity\s*regulator|acidifier)\s*\(\s*330\s*\)?",

            text,

            flags=re.IGNORECASE,

        ):

            result.append("Citric Acid")

            continue


        if re.fullmatch(

            r"mineral\s*\(\s*potassium\s+chloride\s*\)?",

            text,

            flags=re.IGNORECASE,

        ):

            result.append("Potassium Chloride")

            continue


        if re.fullmatch(

            r"colou?r\s*\(\s*150d\s*\)?",

            text,

            flags=re.IGNORECASE,

        ):

            result.append("Caramel IV")

            continue


        if re.fullmatch(

            r"flavou?r\s+enhancer\s*\(\s*635\s*\)\s+and\s+raising\s+agent\s*\(\s*500\s*\)*",

            text,

            flags=re.IGNORECASE,

        ):

            result.extend(

                [

                    "Disodium 5'-Ribonucleotides",

                    "Sodium Carbonate",

                ]

            )

            continue


        if re.fullmatch(

            r"suga?r\s+edible\s+starch",

            text,

            flags=re.IGNORECASE,

        ):

            result.extend(

                [

                    "Sugar",

                    "Edible Starch",

                ]

            )

            continue


        # -------------------------------------------------

        # Mineral Calcium Carbonate + Guar Gum

        # -------------------------------------------------


        if re.fullmatch(

            r"mineral\s+calcium\s+carbonate\s+and\s+guar\s+gum",

            text,

            flags=re.IGNORECASE,

        ):


            result.extend(

                [

                    "Mineral Calcium Carbonate",

                    "Guar Gum",

                ]

            )


            continue


        # -------------------------------------------------

        # Period between ingredients

        # -------------------------------------------------


        text = re.sub(

            r"\.\s+",

            ", ",

            text,

        )


        # -------------------------------------------------

        # Sugar + Edible Starch

        # -------------------------------------------------


        if re.fullmatch(

            r"sugar\s+edible\s+starch",

            text,

            flags=re.IGNORECASE,

        ):


            result.extend(

                [

                    "Sugar",

                    "Edible Starch",

                ]

            )


            continue


        # -------------------------------------------------

        # Compound phrase with trailing ingredient

        # -------------------------------------------------


        # -------------------------------------------------
        # Enhancer 635 + 500
        # -------------------------------------------------

        if re.fullmatch(
            r"enhancer\s+635\s+and\s+500",
            text,
            flags=re.IGNORECASE,
        ):
            result.extend(
                [
                    "Disodium 5'-Ribonucleotides",
                    "Sodium Carbonate",
                ]
            )
            continue

        match = re.fullmatch(

            r"mineral\s+calcium\s+carbonate\s+and\s+guar\s+gum\s*,?\s*(.+)",

            text,

            flags=re.IGNORECASE,

        )


        if match:


            result.extend(

                [

                    "Mineral Calcium Carbonate",

                    "Guar Gum",

                    match.group(1).strip(),

                ]

            )


            continue


        result.append(

            text

        )


    return result


# =========================================================

# SMART INGREDIENT EXTRACTION

# =========================================================


def extract_ingredients(

    text: str,

) -> list[str]:


    text = clean_text(

        text

    )


    # Remove remaining heading.

    text = re.sub(

        r"\b(?:"

        r"ingredients?"

        r"|ngredients?"

        r"|ngredent"

        r"|composition"

        r")\s*:?\s*",

        "",

        text,

        flags=re.IGNORECASE,

    )


    # Remove subsection labels.

    text = re.sub(

        r"\b(?:"

        r"noodle"

        r"|noodles"

        r"|masala\s+tastemaker"

        r"|tastemaker"

        r"|seasoning"

        r")\s*:\s*",

        "",

        text,

        flags=re.IGNORECASE,

    )


    # Fix:

    # Guar Gum. Hydrolysed Groundnut Protein

    #

    # without breaking:

    # 23.6%

    text = re.sub(

        r"(?<=[A-Za-z])\.\s+(?=[A-Za-z])",

        ", ",

        text,

    )


    text = text.replace(

        ";",

        ",",

    )


    ingredients = []

    current = []


    round_depth = 0

    square_depth = 0

    curly_depth = 0


    for char in text:


        if char == "(":

            round_depth += 1


        elif char == "[":

            square_depth += 1


        elif char == "{":

            curly_depth += 1


        elif char == ")":

            round_depth = max(

                0,

                round_depth - 1,

            )


        elif char == "]":

            square_depth = max(

                0,

                square_depth - 1,

            )


        elif char == "}":

            curly_depth = max(

                0,

                curly_depth - 1,

            )


        is_top_level_comma = (

            char == ","

            and round_depth == 0

            and square_depth == 0

            and curly_depth == 0

        )


        if is_top_level_comma:


            ingredient = "".join(

                current

            ).strip(

                " .:-"

            )


            if len(ingredient) >= 2:


                ingredients.append(

                    ingredient

                )


            current = []


        else:


            current.append(

                char

            )


    ingredient = "".join(

        current

    ).strip(

        " .:-"

    )


    if len(ingredient) >= 2:


        ingredients.append(

            ingredient

        )


    # Split known combined phrases.

    ingredients = (

        split_known_compound_ingredients(

            ingredients

        )

    )


    # -----------------------------------------------------

    # CLEAN + DEDUPLICATE

    # -----------------------------------------------------


    cleaned = []

    seen = set()


    for ingredient in ingredients:


        ingredient = (

            clean_ordinary_ingredient_text(

                ingredient

            )

        )


        ingredient = re.sub(

            r"\s+",

            " ",

            ingredient,

        ).strip(

            " .:-"

        )


        if len(ingredient) < 2:

            continue


        key = ingredient.lower()


        if key in seen:

            continue


        seen.add(

            key

        )


        cleaned.append(

            ingredient

        )


    return cleaned


# =========================================================

# OCR CODE VALIDATION

# =========================================================


OCR_CODE_FIXES = {

    "O": "0",

    "o": "0",

    "I": "1",

    "i": "1",

    "L": "1",

    "l": "1",

    "S": "5",

    "s": "5",

    "B": "8",

    "b": "8",

}


def get_valid_ins_codes() -> set[str]:


    codes = set()


    for data in INGREDIENT_DATABASE.values():


        ins = data.get(

            "ins"

        )


        if ins:


            codes.add(

                str(ins)

            )


    return codes


def validate_ingredient_code(

    text: str,

) -> dict:


    pattern = (

        r"\b(?:INS\s*|E\s*)"

        r"([A-Z0-9]{3}[A-Z]?)\b"

    )


    match = re.search(

        pattern,

        text,

        flags=re.IGNORECASE,

    )


    if not match:


        return {

            "original": text,

            "corrected_text": text,

            "has_code": False,

            "raw_code": None,

            "corrected_code": None,

            "confidence": 0.0,

            "status": "NO_CODE",

        }


    raw_code = match.group(

        1

    )


    normalized_raw = raw_code.upper()


    valid_codes = get_valid_ins_codes()


    if normalized_raw.isdigit():


        if normalized_raw in valid_codes:


            return {

                "original": text,

                "corrected_text": text,

                "has_code": True,

                "raw_code": raw_code,

                "corrected_code": normalized_raw,

                "confidence": 1.0,

                "status": "VALID",

            }


        return {

            "original": text,

            "corrected_text": text,

            "has_code": True,

            "raw_code": raw_code,

            "corrected_code": normalized_raw,

            "confidence": 0.5,

            "status": "UNKNOWN_CODE",

        }


    corrected = "".join(

        OCR_CODE_FIXES.get(

            char,

            char,

        )

        for char in raw_code

    )


    if (

        len(corrected) == 3

        and corrected.isdigit()

        and corrected in valid_codes

    ):


        start, end = match.span(

            1

        )


        corrected_text = (

            text[:start]

            + corrected

            + text[end:]

        )


        return {

            "original": text,

            "corrected_text": corrected_text,

            "has_code": True,

            "raw_code": raw_code,

            "corrected_code": corrected,

            "confidence": 0.95,

            "status": "OCR_CORRECTED",

        }


    return {

        "original": text,

        "corrected_text": text,

        "has_code": True,

        "raw_code": raw_code,

        "corrected_code": corrected,

        "confidence": 0.5,

        "status": "UNKNOWN_CODE",

    }


# =========================================================

# OCR SINGLE PASS

# =========================================================


def run_single_ocr(

    ocr,

    image,

) -> list[str]:


    detected_text = []


    try:


        results = ocr.predict(

            image

        )


    except Exception:


        return []


    for result in results:


        try:


            data = result.json


            if callable(data):

                data = data()


            if not isinstance(

                data,

                dict,

            ):

                continue


            ocr_data = data.get(

                "res",

                data,

            )


            texts = ocr_data.get(

                "rec_texts",

                [],

            )


            scores = ocr_data.get(

                "rec_scores",

                [],

            )


            if not isinstance(

                texts,

                list,

            ):

                continue


            for index, text in enumerate(

                texts

            ):


                if text is None:

                    continue


                text = str(

                    text

                ).strip()


                if not text:

                    continue


                if (

                    isinstance(

                        scores,

                        list,

                    )

                    and index < len(scores)

                ):


                    try:


                        score = float(

                            scores[index]

                        )


                        if score < 0.45:

                            continue


                    except (

                        ValueError,

                        TypeError,

                    ):

                        pass


                detected_text.append(

                    text

                )


        except Exception:


            continue


    return detected_text


# =========================================================

# OCR

# =========================================================


def run_ocr(

    image_np: np.ndarray,

) -> list[str]:


    ocr = load_ocr()


    enhanced_image = preprocess_image(

        image_np

    )


    original_results = run_single_ocr(

        ocr,

        image_np,

    )


    enhanced_results = run_single_ocr(

        ocr,

        enhanced_image,

    )


    all_results = (

        original_results

        + enhanced_results

    )


    unique_text = []


    seen = set()


    for text in all_results:


        key = re.sub(

            r"\s+",

            " ",

            text.lower(),

        ).strip()


        if key in seen:

            continue


        seen.add(

            key

        )


        unique_text.append(

            text

        )


    return unique_text


# =========================================================

# DISPLAY HELPERS

# =========================================================


def get_status_display(

    status: str,

) -> str:


    status_map = {

        "NOT_AUTHORISED":

            "🔴 Not authorised",

        "BANNED":

            "🔴 Prohibited",

        "RESTRICTED":

            "🟠 Restricted",

        "CHECK_CONDITIONS":

            "🟡 Conditions apply",

        "CHECK":

            "🟡 Requires verification",

        "AUTHORISED":

            "🟢 Authorised",

        "LISTED":

            "🟢 Listed",

        "REGULATED":

            "🟢 Regulated",

        "IDENTIFIED":

            "ℹ️ Identified",

    }


    return status_map.get(

        status,

        "⚪ Unknown",

    )


def is_flagged_status(

    status: str,

) -> bool:


    return status in {

        "BANNED",

        "NOT_AUTHORISED",

        "RESTRICTED",

    }


def is_valid_url(

    url: str,

) -> bool:


    try:


        parsed = urlparse(

            url

        )


        return (

            parsed.scheme in {

                "http",

                "https",

            }

            and bool(

                parsed.netloc

            )

        )


    except Exception:


        return False


# =========================================================


# =========================================================
# PLAIN-ENGLISH REGULATORY CONDITION HELPERS
# =========================================================

def get_condition_label(restriction: str, status: str) -> str:
    """Convert stored regulatory wording into a short user-friendly label."""
    text = str(restriction or "").lower()

    if "quantum satis" in text:
        return "No fixed amount"

    if "maximum" in text or "max level" in text or "limit" in text:
        return "Maximum amount"

    if "gmp" in text and (
        "food-category" in text
        or "food category" in text
    ):
        return "Certain foods + GMP"

    if (
        "food-category" in text
        or "food category" in text
        or "category-specific" in text
    ):
        return "Certain foods only"

    if "restricted" in text or status in {
        "RESTRICTED",
        "NOT_AUTHORISED",
        "BANNED",
    }:
        return "Restricted"

    if "specific regulation" in text:
        return "Specific rule applies"

    if "verification" in text or status == "CHECK":
        return "Needs checking"

    if "authori" in text or status == "AUTHORISED":
        return "Authorised with conditions"

    if "listed" in text or status == "LISTED":
        return "Listed"

    return "Conditions apply"


def get_condition_explanation(
    condition: str,
    restriction: str,
    status: str,
) -> str:
    """Return one short sentence for normal users."""
    text = str(restriction or "").lower()

    if status == "BANNED":
        return "Not permitted under this country's rule."

    if status == "NOT_AUTHORISED":
        return "Not authorised for this use."

    if status == "RESTRICTED":
        return "Allowed only under specific restrictions."

    if "quantum satis" in text:
        return "No fixed amount shown here, but the food rules still apply."

    if "maximum" in text or "max level" in text or "limit" in text:
        return "There is a legal maximum amount for the relevant food."

    if "gmp" in text and (
        "food-category" in text
        or "food category" in text
    ):
        return "Allowed under good manufacturing practice and only in applicable foods."

    if "gmp" in text:
        return "Good manufacturing practice applies; food-specific rules still apply."

    if (
        "food-category" in text
        or "food category" in text
        or "category-specific" in text
    ):
        return "It may be allowed only for certain foods or amounts."

    if status == "AUTHORISED":
        return "Authorised, subject to the stated conditions."

    if status == "LISTED":
        return "Listed by the regulator; check the stated use conditions."

    if status == "CHECK":
        return "The exact legal use needs to be checked."

    return "The regulator's conditions need to be checked."


def build_comparison_rows(record: dict) -> list[dict]:
    rows = []

    for country, data in record.get("jurisdictions", {}).items():
        status = data.get("status", "UNKNOWN")
        restriction = data.get("restriction", "")
        condition = get_condition_label(restriction, status)

        rows.append(
            {
                "Country": country,
                "Status": get_status_display(status),
                "Condition": condition,
                "What it means": get_condition_explanation(
                    condition,
                    restriction,
                    status,
                ),
            }
        )

    return rows


# NORMALIZATION

# =========================================================


def normalize_results(

    ingredients: list[str],

) -> list[dict]:


    results = []

    seen = set()


    for ingredient in ingredients:


        validation = (

            validate_ingredient_code(

                ingredient

            )

        )


        corrected_text = validation[

            "corrected_text"

        ]


        normalized_text = (

            clean_ordinary_ingredient_text(

                corrected_text

            )

        )


        try:

            # Prefer an explicit INS/E code when present.
            code_match = re.search(
                r"\b(?:INS\s*|E\s*)?([0-9]{3}[A-Za-z]?)\b",
                normalized_text,
                flags=re.IGNORECASE,
            )

            code_result = None

            if code_match:
                detected_code = code_match.group(1).lower()
                for canonical_name, data in INGREDIENT_DATABASE.items():
                    db_code = str(data.get("ins", "")).strip().lower()
                    if db_code and db_code == detected_code:
                        code_result = {
                            "canonical": canonical_name,
                            "ins": data.get("ins"),
                            "method": "INS/E code",
                            "confidence": 1.0,
                        }
                        break

            if code_result is not None:
                result = code_result
            else:
                result = normalize_ingredient(
                    normalized_text
                )


        except Exception as exc:


            result = {

                "original": ingredient,

                "canonical": normalized_text,

                "ins": None,

                "method": "normalization error",

                "confidence": 0.0,

                "error": str(exc),

            }


        result["original"] = ingredient


        result["ocr_text"] = (

            corrected_text

        )


        result["text_correction"] = {

            "original": corrected_text,

            "corrected_text": normalized_text,

            "changed": (

                corrected_text.lower()

                != normalized_text.lower()

            ),

        }


        result["validation"] = (

            validation

        )


        canonical = str(

            result.get(

                "canonical",

                normalized_text,

            )

        ).strip()


        if not canonical:

            continue


        key = canonical.lower()


        if key in seen:

            continue


        seen.add(

            key

        )

        results.append(

            result

        )


    return results


# =========================================================


def _parse_verified_date(value: str):
    raw = str(value or "").strip()
    if not raw:
        return None
    candidates = [
        "%Y-%m-%d", "%Y/%m/%d", "%d-%m-%Y", "%d/%m/%Y",
        "%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M",
    ]
    for fmt in candidates:
        try:
            return datetime.strptime(raw, fmt)
        except ValueError:
            continue
    return None


def build_regulatory_freshness_rows(regulatory_results: list[dict]) -> list[dict]:
    rows = []
    now = datetime.now()
    for result_item in regulatory_results:
        ingredient = str(result_item.get("ingredient", "")).strip()
        record = result_item.get("record", {})
        for country, data in record.get("jurisdictions", {}).items():
            verified = str(data.get("verified", "") or "").strip()
            parsed = _parse_verified_date(verified)
            if parsed is None:
                age = None
                freshness = "⚪ Unknown"
            else:
                age = max(0, (now - parsed).days)
                if age <= 365:
                    freshness = "🟢 Recent"
                elif age <= 730:
                    freshness = "🟡 Aging"
                else:
                    freshness = "🟠 Stale"
            rows.append({
                "Ingredient": ingredient.title(),
                "Country": country,
                "Last verified": verified or "—",
                "Age (days)": age if age is not None else "—",
                "Freshness": freshness,
            })
    return rows


def build_coverage_gap_rows(normalized_results: list[dict], comparison_rows: list[dict]) -> list[dict]:
    countries = sorted({str(r.get("Country", "")).strip() for r in comparison_rows if str(r.get("Country", "")).strip()}, key=str.lower)
    if not countries:
        return []
    by_ingredient = {}
    for row in comparison_rows:
        ingredient = str(row.get("Ingredient", "")).strip()
        country = str(row.get("Country", "")).strip()
        if ingredient and country:
            by_ingredient.setdefault(ingredient.lower(), set()).add(country)
    rows=[]
    for item in normalized_results:
        ingredient=str(item.get("canonical", "")).strip()
        if not ingredient:
            continue
        covered=by_ingredient.get(ingredient.lower(), set())
        missing=[c for c in countries if c not in covered]
        rows.append({
            "Ingredient": ingredient.title(),
            "Jurisdictions represented": len(covered),
            "Jurisdictions missing": len(missing),
            "Missing current comparison jurisdictions": ", ".join(missing) if missing else "None",
            "Coverage note": "Missing stored record is not approval; it means the current database has no record for this ingredient/jurisdiction pair.",
        })
    return rows


def search_label_lines(detected_text: list[str], query: str) -> list[dict]:
    q = str(query or "").strip().lower()
    if not q:
        return []
    rows=[]
    for idx, line in enumerate(detected_text, start=1):
        line_text=str(line or "").strip()
        if q in line_text.lower():
            rows.append({"OCR line": idx, "Matched text": line_text})
    return rows


def build_scan_fingerprint(normalized_results: list[dict]) -> str:
    names=[str(item.get("canonical", "")).strip().lower() for item in normalized_results if str(item.get("canonical", "")).strip()]
    payload="|".join(names)
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()[:12]


def build_session_comparison(current_ingredients: list[str], previous_ingredients: list[str] | None) -> dict:
    current={str(x).strip() for x in (current_ingredients or []) if str(x).strip()}
    previous={str(x).strip() for x in (previous_ingredients or []) if str(x).strip()}
    return {
        "added": sorted(current - previous, key=str.lower),
        "removed": sorted(previous - current, key=str.lower),
        "unchanged": sorted(current & previous, key=str.lower),
    }


# =========================================================
# BATCH 20–24 HELPERS
# =========================================================


def build_nutrition_review_rows(nutrition: dict) -> list[dict]:
    """Show nutrition fields detected/not detected without treating absence as a legal or health conclusion."""
    fields = [
        ("Energy", "energy_kcal", "kcal"),
        ("Protein", "protein_g", "g"),
        ("Carbohydrate", "carbohydrate_g", "g"),
        ("Total sugars", "total_sugars_g", "g"),
        ("Total fat", "total_fat_g", "g"),
        ("Sodium", "sodium_mg", "mg"),
        ("Dietary fibre", "fiber_g", "g"),
        ("Saturated fat", "saturated_fat_g", "g"),
        ("Added sugars", "added_sugars_g", "g"),
    ]
    rows = []
    for label, key, unit in fields:
        value = nutrition.get(key)
        rows.append({
            "Nutrient": label,
            "Detected": "✅ Yes" if value is not None else "⚪ Not detected",
            "Value": f"{value:g} {unit}" if value is not None else "—",
            "Interpretation": "Read from OCR text" if value is not None else "Not captured from the current label image",
        })
    return rows


def build_country_focus_rows(comparison_rows: list[dict], country: str) -> list[dict]:
    rows = []
    for row in comparison_rows:
        if str(row.get("Country", "")) != str(country):
            continue
        rows.append({
            "Ingredient": row.get("Ingredient", ""),
            "Status": row.get("Status", "—"),
            "Legal level": row.get("Legal level", "—"),
            "Condition": row.get("Condition", "—"),
            "Food category": row.get("Food category", "—"),
        })
    return rows


def build_copyable_scan_summary(
    screening_decision: dict,
    summary_rows: list[dict],
    allergens: list[dict],
    nutrition_info: dict,
    scan_clarity: dict,
    review_actions: list[dict],
) -> str:
    attention = screening_decision.get("level", "Recorded scan")
    title = screening_decision.get("title", "Label screening")
    ingredient_names = [str(r.get("Ingredient", "")).strip() for r in summary_rows if str(r.get("Ingredient", "")).strip()]
    allergen_names = [str(a.get("Allergen", a.get("Type", ""))).strip() for a in allergens if str(a.get("Allergen", a.get("Type", ""))).strip()]
    actions = [str(r.get("Action", "")).strip() for r in review_actions if str(r.get("Action", "")).strip()]
    parts = [
        f"FoodReg AI screening: {title} ({attention})",
        f"Ingredients identified: {', '.join(ingredient_names) if ingredient_names else 'None'}",
        f"Allergen signals: {', '.join(allergen_names) if allergen_names else 'None detected from current OCR text'}",
        f"Nutrition fields detected: {nutrition_info.get('value_count', 0)}",
        f"Scan clarity: {scan_clarity.get('level', 'Not calculated')} ({scan_clarity.get('score', '—')}/100)",
    ]
    if actions:
        parts.append("Review actions: " + "; ".join(actions[:5]))
    parts.append("Note: This is a label/OCR and regulatory-database screening summary, not a medical or dietary risk score.")
    return "\n".join(parts)


def build_manual_lookup_rows(record: dict) -> list[dict]:
    rows = []
    for country, data in record.get("jurisdictions", {}).items():
        status = str(data.get("status", "UNKNOWN") or "UNKNOWN").upper()
        rows.append({
            "Country": country,
            "Status": get_status_display(status),
            "Legal level": format_level(data),
            "Condition": format_condition(data, status),
            "Authority": str(data.get("authority", "") or "—"),
            "Last verified": str(data.get("verified", "") or "—"),
            "Source type": str(data.get("source_type", "") or "—"),
            "Source": str(data.get("source_url", "") or "—"),
        })
    return rows


# =========================================================
# FINAL INTELLIGENCE UPGRADE HELPERS
# =========================================================

CLAIM_CONTRADICTION_PATTERNS = {
    "No added sugar": [
        r"\bsugar\b", r"\bsucrose\b", r"\bglucose\b", r"\bfructose\b",
        r"\bmolasses\b", r"\bhoney\b", r"\bcane sugar\b", r"\bcorn syrup\b",
        r"\bglucose syrup\b", r"\binvert syrup\b",
    ],
    "Sugar free": [
        r"\bsugar\b", r"\bsucrose\b", r"\bglucose\b", r"\bfructose\b",
        r"\bhoney\b", r"\bsyrup\b",
    ],
    "Gluten free": [r"\bwheat\b", r"\bgluten\b", r"\bbarley\b", r"\brye\b"],
    "Vegan": [
        r"\bmilk\b", r"\bcasein\b", r"\bwhey\b", r"\begg\b", r"\bgelatin\b",
        r"\bgelatine\b", r"\blard\b", r"\bbeef\b", r"\bchicken\b", r"\bfish\b",
    ],
    "Vegetarian": [
        r"\bgelatin\b", r"\bgelatine\b", r"\blard\b", r"\bbeef\b",
        r"\bchicken\b", r"\bmutton\b", r"\bpork\b", r"\bfish\b",
    ],
    "No preservatives": [
        r"\bsodium benzoate\b", r"\bpotassium sorbate\b", r"\bsorbic acid\b",
        r"\bbenzoic acid\b", r"\bpropionate\b", r"\bmetabisulphite\b",
        r"\bsulphite\b", r"\bsulfite\b",
    ],
}

CLAIM_NUTRITION_REVIEW = {
    "High protein": "Protein threshold depends on the jurisdiction and claim standard; this tool does not apply one global legal threshold.",
    "Low sugar": "Low-sugar thresholds depend on the jurisdiction, product category and serving/100 g basis.",
    "Low sodium / low salt": "Low-sodium/low-salt thresholds depend on the jurisdiction, product category and label basis.",
    "Low fat": "Low-fat thresholds depend on the jurisdiction, product category and serving/100 g basis.",
    "Fat free": "Fat-free thresholds depend on the jurisdiction and applicable nutrient-claim standard.",
}


def build_claim_verification_rows(claims_rows: list[dict], normalized_results: list[dict], nutrition: dict) -> list[dict]:
    """Screen detected claims against label evidence without declaring legal compliance."""
    names = [str(x.get("canonical", "")).strip() for x in normalized_results if str(x.get("canonical", "")).strip()]
    text = " | ".join(names)
    rows = []
    for claim in claims_rows:
        label = str(claim.get("Claim detected", "")).strip()
        status = "Needs verification"
        evidence = "No direct contradiction found in the identified ingredients."
        action = "Verify against the product's target-jurisdiction claim rule and the complete label."

        patterns = CLAIM_CONTRADICTION_PATTERNS.get(label, [])
        matched = []
        for pattern in patterns:
            for name in names:
                if re.search(pattern, name, flags=re.IGNORECASE):
                    matched.append(name.title())
        if matched:
            status = "⚠️ Potential inconsistency"
            evidence = "Detected ingredient(s): " + ", ".join(sorted(set(matched), key=str.lower))
            action = "Review the claim wording, formulation and target-jurisdiction rule before relying on it."
        elif label in CLAIM_NUTRITION_REVIEW:
            value_map = {
                "High protein": ("protein_g", "Protein value"),
                "Low sugar": ("total_sugars_g", "Total sugars value"),
                "Low sodium / low salt": ("sodium_mg", "Sodium value"),
                "Low fat": ("total_fat_g", "Total fat value"),
                "Fat free": ("total_fat_g", "Total fat value"),
            }
            key, value_label = value_map.get(label, (None, "Nutrition value"))
            value = nutrition.get(key) if key else None
            if value is None:
                status = "🟡 Unresolved — nutrition value not captured"
                evidence = "The label scan did not provide a usable value for the relevant nutrient."
            else:
                status = "🟡 Needs threshold check"
                evidence = f"{value_label}: {value}. No universal legal threshold is applied by FoodReg AI."
            action = CLAIM_NUTRITION_REVIEW.get(label, action)
        elif label in {"Organic", "Natural", "No artificial colours"}:
            status = "🟡 Evidence/standard check required"
            if label == "Organic":
                evidence = "Organic status generally depends on certification/production standards, not ingredient-name matching alone."
            elif label == "Natural":
                evidence = "Natural claims require the applicable product definition/standard; ingredient matching alone is insufficient."
            else:
                colour_names = [n.title() for n in names if re.search(r"colour|color|caramel|\b150[a-z]?\b", n, re.I)]
                evidence = "Colour-related ingredient signal detected: " + ", ".join(colour_names) if colour_names else "No clear colour ingredient was identified."
            action = "Check the specific claim standard, formulation records and certification/technical documentation."
        rows.append({
            "Claim": label,
            "Screening": status,
            "Evidence": evidence,
            "Recommended action": action,
            "OCR evidence": str(claim.get("Evidence in OCR", "")),
        })
    return rows


def _source_tier(data: dict) -> str:
    """Classify evidence source strength from stored metadata; not a legal-validity score."""
    source_type = str(data.get("source_type", "") or "").strip().lower()
    authority = str(data.get("authority", "") or "").strip()
    url = str(data.get("source_url", "") or data.get("source", "") or "").strip().lower()
    host = ""
    try:
        host = urlparse(url).netloc.lower()
    except Exception:
        host = ""
    official_domain = (
        host.endswith(".gov") or ".gov." in host or host.endswith(".gov.uk") or
        host.endswith(".gov.au") or host.endswith(".gov.sg") or host.endswith(".go.jp") or
        ".go." in host or ".gob." in host or "eur-lex.europa.eu" in host or
        host.endswith(".gc.ca") or host.endswith(".canada.ca") or
        host.endswith(".gov.sa") or host.endswith(".gov.kr") or host.endswith(".gov.my")
    )
    if official_domain or "official" in source_type:
        return "Tier 1 — Official authority/source"
    if "codex" in source_type or "framework" in source_type or "international" in source_type or "fao.org" in host or "who.int" in host:
        return "Tier 2 — International/framework reference"
    if authority and url:
        return "Tier 3 — Referenced regulatory source"
    if authority or url:
        return "Tier 3 — Partial source metadata"
    return "Tier 4 — Source not identified"


def build_regulatory_matrix_rows(normalized_results: list[dict], regulatory_results: list[dict]) -> list[dict]:
    """Compact ingredient x regulatory-status matrix for audit use."""
    rows = []
    for item in regulatory_results:
        ingredient = str(item.get("ingredient", "")).strip().title()
        jurisdictions = (item.get("record", {}) or {}).get("jurisdictions", {}) or {}
        counts = {"Prohibited": 0, "Restricted": 0, "Conditions": 0, "No restriction": 0, "Food ingredient": 0, "Not verified": 0}
        for data in jurisdictions.values():
            status = str((data or {}).get("status", "UNKNOWN") or "UNKNOWN").upper()
            if status in {"BANNED", "NOT_AUTHORISED"}: counts["Prohibited"] += 1
            elif status == "RESTRICTED": counts["Restricted"] += 1
            elif status in {"CHECK_CONDITIONS", "CONDITIONAL", "CONDITIONS"}: counts["Conditions"] += 1
            elif status in {"NO_RESTRICTION", "NO_RESTRICTION_FOUND", "NOT_RESTRICTED", "AUTHORISED", "APPROVED", "LISTED"}: counts["No restriction"] += 1
            elif status in {"FOOD_INGREDIENT", "FOOD INGREDIENT"}: counts["Food ingredient"] += 1
            else: counts["Not verified"] += 1
        rows.append({"Ingredient": ingredient, "Stored jurisdictions": len(jurisdictions), **counts, "Attention findings": counts["Prohibited"] + counts["Restricted"] + counts["Conditions"], "Coverage": "Stored records found" if jurisdictions else "No stored record"})
    return sorted(rows, key=lambda r: (-int(r.get("Attention findings", 0)), str(r.get("Ingredient", ""))))

def build_regulatory_batch_summary(regulatory_results: list[dict], source_rows: list[dict]) -> dict:
    total_records = 0; countries = set(); prohibited = restricted = conditions = no_restriction = not_verified = 0; ingredients_with_records = 0
    for item in regulatory_results:
        jurisdictions = (item.get("record", {}) or {}).get("jurisdictions", {}) or {}
        if jurisdictions: ingredients_with_records += 1
        for country, data in jurisdictions.items():
            countries.add(country); total_records += 1
            status = str((data or {}).get("status", "UNKNOWN") or "UNKNOWN").upper()
            if status in {"BANNED", "NOT_AUTHORISED"}: prohibited += 1
            elif status == "RESTRICTED": restricted += 1
            elif status in {"CHECK_CONDITIONS", "CONDITIONAL", "CONDITIONS"}: conditions += 1
            elif status in {"NO_RESTRICTION", "NO_RESTRICTION_FOUND", "NOT_RESTRICTED", "AUTHORISED", "APPROVED", "LISTED", "FOOD_INGREDIENT"}: no_restriction += 1
            else: not_verified += 1
    tier_counts = {}
    for row in source_rows:
        tier = str(row.get("Source tier", "Tier 4 — Source not identified")); tier_counts[tier] = tier_counts.get(tier, 0) + 1
    return {"ingredients_scanned": len([x for x in regulatory_results if str(x.get("ingredient", "")).strip()]), "ingredients_with_stored_records": ingredients_with_records, "countries_with_records": len(countries), "stored_regulatory_records": total_records, "prohibited_not_authorised": prohibited, "restricted": restricted, "conditions": conditions, "no_restriction_or_listed": no_restriction, "other_or_not_verified": not_verified, "source_tiers": tier_counts}

def build_claim_evidence_rows(claim_verification_rows: list[dict], nutrition_info: dict, normalized_results: list[dict]) -> list[dict]:
    """Make claim screening easier to audit by explicitly listing the evidence basis."""
    nutrition_keys = {"energy_kcal": "Energy", "protein_g": "Protein", "carbohydrate_g": "Carbohydrate", "total_sugars_g": "Total sugars", "total_fat_g": "Total fat", "saturated_fat_g": "Saturated fat", "sodium_mg": "Sodium", "fibre_g": "Fibre"}
    available_nutrition = [label for key, label in nutrition_keys.items() if nutrition_info.get(key) is not None]
    has_ingredients = any(str(x.get("canonical", "")).strip() for x in normalized_results)
    rows = []
    for row in claim_verification_rows or []:
        evidence = str(row.get("Evidence", "")).strip(); basis = []
        if evidence: basis.append("Claim-screening result")
        if has_ingredients: basis.append("Normalized ingredients")
        if available_nutrition: basis.append("Nutrition panel: " + ", ".join(available_nutrition))
        rows.append({"Claim": row.get("Claim", ""), "Screening": row.get("Screening", "Needs verification"), "Evidence": evidence or "No direct evidence recorded.", "Evidence basis": "; ".join(basis) if basis else "No label evidence available", "Recommended action": row.get("Recommended action", "Verify against the target-jurisdiction claim rule.")})
    return rows

def build_export_manifest(file_names: list[str]) -> list[dict]:
    return [{"File": name, "Purpose": "Current FoodReg AI scan export"} for name in file_names]

def build_source_intelligence_rows(regulatory_results: list[dict]) -> list[dict]:
    rows = []
    for item in regulatory_results:
        ingredient = str(item.get("ingredient", "")).strip().title()
        for country, data in (item.get("record", {}) or {}).get("jurisdictions", {}).items():
            data = data or {}
            status = str(data.get("status", "UNKNOWN") or "UNKNOWN").upper()
            source = str(data.get("source_url", "") or data.get("source", "") or "").strip()
            authority = str(data.get("authority", "") or "").strip()
            verified = str(data.get("verified_date", "") or data.get("verified", "") or "").strip()
            completeness = sum(bool(x) for x in (source, authority, verified))
            rows.append({
                "Ingredient": ingredient,
                "Country / jurisdiction": country,
                "Status": get_status_display(status),
                "Source tier": _source_tier(data),
                "Authority": authority or "—",
                "Verified": verified or "—",
                "Metadata completeness": f"{completeness}/3",
                "Source": source or "—",
            })
    return rows


def build_source_intelligence_summary(rows: list[dict]) -> dict:
    total = len(rows)
    counts = {}
    for row in rows:
        tier = row.get("Source tier", "Tier 4 — Source not identified")
        counts[tier] = counts.get(tier, 0) + 1
    verified = sum(1 for row in rows if row.get("Verified", "—") not in ("", "—"))
    return {
        "total_records": total,
        "verified_records": verified,
        "verified_pct": round(100 * verified / total, 1) if total else 0,
        "tier_counts": counts,
        "note": "Source tiers are metadata-derived categories for review prioritisation. They do not guarantee the legal correctness or current validity of a record.",
    }


def build_regulatory_divergence_rows(regulatory_results: list[dict]) -> list[dict]:
    rows = []
    for item in regulatory_results:
        ingredient = str(item.get("ingredient", "")).strip().title()
        records = []
        statuses = {}
        for country, data in (item.get("record", {}) or {}).get("jurisdictions", {}).items():
            data = data or {}
            status = str(data.get("status", "UNKNOWN") or "UNKNOWN").upper()
            shown = get_status_display(status)
            statuses.setdefault(status, []).append(country)
            records.append((country, shown, format_level(data), format_condition(data, status)))
        if len(statuses) <= 1:
            continue
        attention = any(st in {"BANNED", "NOT_AUTHORISED", "RESTRICTED", "CHECK_CONDITIONS", "CONDITIONAL", "CONDITIONS"} for st in statuses)
        rows.append({
            "Ingredient": ingredient,
            "Distinct stored statuses": len(statuses),
            "Status divergence": "⚠️ Yes — jurisdiction-specific treatment differs",
            "Countries by status": " | ".join(f"{get_status_display(st)}: {', '.join(countries)}" for st, countries in statuses.items()),
            "Review priority": "High" if attention else "Medium",
        })
    return rows


def build_ingredient_evidence_rows(normalized_results: list[dict], regulatory_results: list[dict], claims_rows: list[dict]) -> list[dict]:
    claim_text = " ".join(str(x.get("Claim detected", "")) for x in claims_rows)
    by_name = {str(x.get("ingredient", "")).strip().lower(): x for x in regulatory_results}
    rows = []
    for item in normalized_results:
        canonical = str(item.get("canonical", "")).strip()
        if not canonical:
            continue
        rec = by_name.get(canonical.lower(), {})
        record = rec.get("record", {}) or {}
        jurisdictions = record.get("jurisdictions", {}) or {}
        statuses = []
        sources = 0
        official = 0
        for data in jurisdictions.values():
            data = data or {}
            st_code = str(data.get("status", "UNKNOWN") or "UNKNOWN").upper()
            statuses.append(st_code)
            tier = _source_tier(data)
            if str(data.get("source_url", "") or data.get("source", "") or "").strip():
                sources += 1
            if tier.startswith("Tier 1"):
                official += 1
        attention = any(st in {"BANNED", "NOT_AUTHORISED", "RESTRICTED", "CHECK_CONDITIONS", "CONDITIONAL", "CONDITIONS"} for st in statuses)
        rows.append({
            "Ingredient": canonical.title(),
            "OCR text": str(item.get("original", "")),
            "Corrected text": str(item.get("text_correction", {}).get("corrected", item.get("original", ""))),
            "INS": str(item.get("ins", "") or "—"),
            "Match confidence": f"{float(item.get('confidence', 0.0) or 0.0):.2f}",
            "Normalization method": str(item.get("method", "") or "—"),
            "Regulatory records": len(jurisdictions),
            "Records with sources": sources,
            "Tier 1 source records": official,
            "Attention finding present": "Yes" if attention else "No",
            "Claim-related review": "Review claim context" if canonical.lower() in claim_text.lower() and claim_text.strip() else "None detected",
        })
    return rows


def build_regulatory_review_packet(screening_decision: dict, claim_rows: list[dict], divergence_rows: list[dict], source_summary: dict, actions: list[dict]) -> str:
    lines = [
        "FOODREG AI — REGULATORY REVIEW PACKET",
        "=" * 42,
        f"Screening: {screening_decision.get('level','Not available')} — {screening_decision.get('title','')}",
        "",
        "CLAIM REVIEW",
    ]
    if claim_rows:
        lines.extend(f"- {r.get('Claim')}: {r.get('Screening')} — {r.get('Evidence')}" for r in claim_rows)
    else:
        lines.append("- No predefined claims detected.")
    lines += ["", "REGULATORY DIVERGENCE"]
    if divergence_rows:
        lines.extend(f"- {r.get('Ingredient')}: {r.get('Countries by status')}" for r in divergence_rows)
    else:
        lines.append("- No cross-jurisdiction status divergence was found in the stored records.")
    lines += ["", "SOURCE INTELLIGENCE", f"- Records: {source_summary.get('total_records',0)}", f"- With verification dates: {source_summary.get('verified_records',0)} ({source_summary.get('verified_pct',0)}%)"]
    for tier, count in source_summary.get("tier_counts", {}).items():
        lines.append(f"- {tier}: {count}")
    lines += ["", "RECOMMENDED ACTIONS"]
    if actions:
        lines.extend(f"- [{r.get('Priority','')}] {r.get('Action','')} — {r.get('Why','')}" for r in actions[:10])
    else:
        lines.append("- No additional review actions were generated.")
    lines += ["", "DISCLAIMER", "This packet is a review aid based on OCR-derived label data and the regulatory records stored in FoodReg AI. It is not a legal compliance certificate, legal advice, or a medical safety assessment."]
    return "\n".join(lines)

# =========================================================
# FINAL PRODUCT REVIEW HELPERS
# =========================================================
LABEL_CLAIM_RULES=[
    ("No added sugar",r"\bno\s+added\s+sugars?\b"),("Sugar free",r"\b(?:sugar[-\s]?free|free\s+from\s+sugar)\b"),
    ("Low sugar",r"\blow\s+sugar\b"),("No added salt",r"\bno\s+added\s+salt\b"),("Low sodium / low salt",r"\b(?:low\s+sodium|low\s+salt)\b"),
    ("Gluten free",r"\bgluten[-\s]?free\b"),("High protein",r"\bhigh\s+protein\b"),("Low fat",r"\blow\s+fat\b"),("Fat free",r"\b(?:fat[-\s]?free|free\s+from\s+fat)\b"),
    ("Natural",r"\bnatural\b"),("Organic",r"\borganic\b"),("No preservatives",r"\b(?:no\s+preservatives?|preservative[-\s]?free)\b"),
    ("No artificial colours",r"\b(?:no\s+artificial\s+colou?rs?|artificial\s+colour[-\s]?free)\b"),("Vegan",r"\bvegan\b"),("Vegetarian",r"\bvegetarian\b"),
]
def detect_label_claims(detected_text:list[str])->list[dict]:
    full=clean_text(" ".join(str(x) for x in detected_text if str(x).strip())); rows=[]
    for label,pattern in LABEL_CLAIM_RULES:
        m=re.search(pattern,full,flags=re.IGNORECASE)
        if not m: continue
        a=max(0,m.start()-60); b=min(len(full),m.end()+100); snippet=full[a:b].strip()
        if a>0: snippet='…'+snippet
        if b<len(full): snippet+='…'
        rows.append({"Claim detected":label,"Evidence in OCR":snippet,"Verification":"Needs product/official-rule verification"})
    return rows

def build_composition_breakdown(normalized_results:list[dict],allergens:list[dict])->list[dict]:
    allergen_names={str(x).strip().lower() for a in allergens for x in (a.get('ingredients',[]) or []) if str(x).strip()}
    buckets={"Food additives":{"count":0,"ingredients":[]},"Ordinary food ingredients":{"count":0,"ingredients":[]},"Unclassified ingredients":{"count":0,"ingredients":[]},"Ingredients linked to an allergen signal":{"count":0,"ingredients":[]}}
    for item in normalized_results:
        name=str(item.get('canonical','')).strip()
        if not name: continue
        typ=classify_ingredient(name,item.get('ins')).get('type'); bucket={'ADDITIVE':'Food additives','ORDINARY_INGREDIENT':'Ordinary food ingredients'}.get(typ,'Unclassified ingredients')
        buckets[bucket]['count']+=1; buckets[bucket]['ingredients'].append(name.title())
        if name.lower() in allergen_names: buckets['Ingredients linked to an allergen signal']['count']+=1; buckets['Ingredients linked to an allergen signal']['ingredients'].append(name.title())
    return [{"Category":k,"Count":v['count'],"Ingredients":', '.join(v['ingredients']) if v['ingredients'] else '—'} for k,v in buckets.items()]

def build_regulatory_status_distribution(regulatory_results:list[dict])->list[dict]:
    counts={}; inds={}
    for item in regulatory_results:
        ing=str(item.get('ingredient','')).strip().title()
        for data in (item.get('record',{}) or {}).get('jurisdictions',{}).values():
            status=str((data or {}).get('status','UNKNOWN') or 'UNKNOWN').upper(); counts[status]=counts.get(status,0)+1; inds.setdefault(status,set()).add(ing)
    preferred=['BANNED','NOT_AUTHORISED','RESTRICTED','CHECK_CONDITIONS','AUTHORISED','LISTED','UNKNOWN']; order=preferred+[x for x in counts if x not in preferred]
    return [{"Status":get_status_display(st),"Country records":counts[st],"Unique ingredients":len(inds.get(st,set()))} for st in order if st in counts]

def build_coverage_action_rows(normalized_results:list[dict],comparison_rows:list[dict])->list[dict]:
    countries=sorted({str(r.get('Country','')).strip() for r in comparison_rows if str(r.get('Country','')).strip()},key=str.lower)
    if not countries: return []
    out=[]
    for item in normalized_results:
        ingredient=str(item.get('canonical','')).strip().title()
        if not ingredient: continue
        recorded={str(r.get('Country','')).strip() for r in comparison_rows if str(r.get('Ingredient','')).strip().lower()==ingredient.lower()}; missing=[c for c in countries if c not in recorded]
        out.append({"Ingredient":ingredient,"Jurisdictions checked":len(countries),"Stored records":len(recorded),"Missing stored records":len(missing),"Review":"Check coverage before interpreting as approved" if missing else "No coverage gap in current comparison set"})
    return out

def build_product_fact_sheet(screening_decision:dict,normalized_results:list[dict],allergens:list[dict],nutrition_info:dict,composition_rows:list[dict],claims_rows:list[dict],coverage_rows:list[dict])->str:
    lines=['FOODREG AI — PRODUCT FACT SHEET','='*36,f"Screening: {screening_decision.get('level','Not available')} — {screening_decision.get('title','')}",f"Ingredients identified: {len(normalized_results)}",f"Allergen signals: {len(allergens)}",f"Nutrition values detected: {nutrition_info.get('value_count',0)}",'', 'INGREDIENTS',', '.join(str(x.get('canonical','')).strip().title() for x in normalized_results if str(x.get('canonical','')).strip()) or 'None detected','', 'ALLERGEN SIGNALS',', '.join(str(x.get('allergen','')).strip() for x in allergens) or 'None detected','', 'LABEL CLAIMS DETECTED',', '.join(str(x.get('Claim detected','')).strip() for x in claims_rows) or 'None detected','', 'NUTRITION']
    for label,key,unit in [('Energy','energy_kcal','kcal'),('Protein','protein_g','g'),('Carbohydrate','carbohydrate_g','g'),('Total sugars','total_sugars_g','g'),('Total fat','total_fat_g','g'),('Sodium','sodium_mg','mg')]:
        v=nutrition_info.get(key)
        if v not in (None,''): lines.append(f'{label}: {v} {unit}')
    if nutrition_info.get('serving_size'): lines.append(f"Serving size: {nutrition_info['serving_size']}")
    lines += ['', 'COMPOSITION BREAKDOWN']+[f"{r['Category']}: {r['Count']}" for r in composition_rows]
    lines += ['',f"Coverage gaps in current comparison set: {sum(int(r.get('Missing stored records',0) or 0) for r in coverage_rows)}",'','DISCLAIMER',"This fact sheet summarizes OCR-derived label content and stored regulatory records. Claim detection does not verify marketing or legal claims. Missing regulatory records are not treated as approval. This is not medical or legal advice."]
    return '\n'.join(lines)

def rows_to_csv(rows:list[dict])->str:
    if not rows:return ''
    buf=io.StringIO(); writer=csv.DictWriter(buf,fieldnames=list(rows[0].keys()),extrasaction='ignore'); writer.writeheader(); writer.writerows(rows); return buf.getvalue()


# =========================================================
# FINAL PRODUCT / REGULATORY HELPERS
# =========================================================

def extract_product_metadata(detected_text: list[str]) -> dict:
    """Extract simple package metadata only when the OCR text explicitly contains it."""
    lines = [clean_text(str(x)) for x in detected_text if str(x).strip()]
    full = clean_text(" ".join(lines))

    def first_match(patterns):
        for pattern in patterns:
            m = re.search(pattern, full, flags=re.IGNORECASE)
            if m:
                value = re.sub(r"\s+", " ", m.group(1)).strip(" .:-")
                if value:
                    return value
        return ""

    net_weight = first_match([
        r"\bnet\s*(?:weight|wt)\s*[:\-]?\s*([0-9]+(?:[.,][0-9]+)?\s*(?:kg|g|mg|ml|l))\b",
        r"\bnet\s*[:\-]?\s*([0-9]+(?:[.,][0-9]+)?\s*(?:kg|g|mg|ml|l))\b",
    ])
    mrp = first_match([
        r"\b(?:mrp|maximum\s+retail\s+price)\s*[:\-]?\s*(?:rs\.?|₹)?\s*([0-9]+(?:[.,][0-9]{1,2})?)",
    ])
    batch_no = first_match([
        r"\b(?:batch\s*(?:no\.?|number)?|lot\s*(?:no\.?|number)?)\s*[:\-]?\s*([A-Z0-9\-/]{2,})",
    ])
    license_no = first_match([
        r"\b(?:fssai|licen[cs]e|lic\s*\.?\s*no)\s*[:\-]?\s*([A-Z0-9\-/]{4,})",
    ])

    product_name = ""
    for line in lines[:10]:
        low = line.lower()
        if len(line) < 3 or len(line) > 90:
            continue
        if re.search(r"\b(?:ingredients?|composition|nutrition|contains|may contain|net weight|mrp|batch|fssai|licen[cs]e|store|best before|use before)\b", low):
            continue
        if sum(ch.isalpha() for ch in line) < 3:
            continue
        product_name = line.strip()
        break

    return {
        "product_name": product_name,
        "brand": "",
        "net_weight": net_weight,
        "mrp": mrp,
        "batch_no": batch_no,
        "license_no": license_no,
        "detected_fields": sum(bool(v) for v in [product_name, net_weight, mrp, batch_no, license_no]),
    }


def build_regulatory_attention_finder_rows(regulatory_results: list[dict], ingredient: str) -> list[dict]:
    """Return jurisdictions where a selected ingredient has an attention-level finding."""
    target = str(ingredient or "").strip().lower()
    rows = []
    for item in regulatory_results:
        if str(item.get("ingredient", "")).strip().lower() != target:
            continue
        for country, data in (item.get("record", {}) or {}).get("jurisdictions", {}).items():
            status = str((data or {}).get("status", "UNKNOWN") or "UNKNOWN").upper()
            if status not in {"BANNED", "NOT_AUTHORISED", "RESTRICTED", "CHECK_CONDITIONS", "CHECK", "REGULATED"}:
                continue
            rows.append({
                "Country / jurisdiction": country,
                "Status": get_status_display(status),
                "Legal level": format_level(data),
                "Food category": str(data.get("food_category", "") or "—"),
                "Conditions": format_condition(data, status),
                "Restriction": str(data.get("restriction", "") or "—"),
                "Authority": str(data.get("authority", "") or "—"),
                "Last verified": str(data.get("verified", "") or "—"),
                "Source": str(data.get("source_url", "") or "—"),
            })
    rows.sort(key=lambda r: (r["Country / jurisdiction"].lower(), r["Status"]))
    return rows


def build_regulatory_timeline_rows(regulatory_results: list[dict]) -> list[dict]:
    """Flatten stored regulatory verification dates into an auditable timeline view."""
    rows = []
    for item in regulatory_results:
        ingredient = str(item.get("ingredient", "")).strip().title()
        for country, data in (item.get("record", {}) or {}).get("jurisdictions", {}).items():
            verified = str((data or {}).get("verified", "") or "").strip()
            if not verified:
                continue
            parsed = _parse_verified_date(verified)
            rows.append({
                "Ingredient": ingredient,
                "Country / jurisdiction": country,
                "Status": get_status_display(str(data.get("status", "UNKNOWN") or "UNKNOWN")),
                "Last verified": verified,
                "Authority": str(data.get("authority", "") or "—"),
                "Source type": str(data.get("source_type", "") or "—"),
                "Date sort": parsed.isoformat() if parsed else "",
            })
    rows.sort(key=lambda r: (r["Date sort"] or "0000-00-00", r["Ingredient"], r["Country / jurisdiction"]), reverse=True)
    for row in rows:
        row.pop("Date sort", None)
    return rows


def build_regulatory_only_rows(regulatory_results: list[dict]) -> list[dict]:
    """Create a flat regulatory CSV-friendly dataset."""
    rows = []
    for item in regulatory_results:
        ingredient = str(item.get("ingredient", "")).strip()
        record = item.get("record", {}) or {}
        ins = str(record.get("ins_code", "") or "")
        for country, data in record.get("jurisdictions", {}).items():
            status = str((data or {}).get("status", "UNKNOWN") or "UNKNOWN").upper()
            rows.append({
                "Ingredient": ingredient,
                "INS": ins,
                "Jurisdiction": country,
                "Status": get_status_display(status),
                "Raw status": status,
                "Label": str(data.get("label", "") or "—"),
                "Restriction": str(data.get("restriction", "") or "—"),
                "Food category": str(data.get("food_category", "") or "—"),
                "Maximum level": format_level(data),
                "Conditions": format_condition(data, status),
                "Authority": str(data.get("authority", "") or "—"),
                "Source type": str(data.get("source_type", "") or "—"),
                "Source": str(data.get("source_url", "") or "—"),
                "Last verified": str(data.get("verified", "") or "—"),
                "Data status": str(data.get("data_status", "") or "—"),
            })
    return rows



def build_custom_nutrition_review(nutrition: dict, thresholds: dict) -> list[dict]:
    """Compare declared label nutrition values against user-defined review thresholds.
    These are user-configured screening thresholds, not medical recommendations.
    """
    specs = [
        ("energy_kcal", "Calories", "kcal"),
        ("total_sugars_g", "Total sugars", "g"),
        ("total_fat_g", "Total fat", "g"),
        ("saturated_fat_g", "Saturated fat", "g"),
        ("sodium_mg", "Sodium", "mg"),
    ]
    rows = []
    for key, label, unit in specs:
        value = nutrition.get(key)
        threshold = thresholds.get(key)
        if value is None or threshold is None:
            continue
        try:
            value_f = float(value)
            threshold_f = float(threshold)
        except (TypeError, ValueError):
            continue
        rows.append({
            "Nutrient": label,
            "Detected value": f"{value_f:g} {unit}",
            "Your threshold": f"{threshold_f:g} {unit}",
            "Review flag": "🟠 Above threshold" if value_f > threshold_f else "🟢 Within threshold",
            "Basis": str(nutrition.get("declared_basis") or nutrition.get("serving_size") or "Label basis"),
        })
    return rows


def build_watchlist_rows(normalized_results: list[dict], regulatory_results: list[dict], watchlist: list[str]) -> list[dict]:
    selected = {str(x).strip().casefold() for x in watchlist if str(x).strip()}
    rows = []
    for item in regulatory_results:
        ingredient = str(item.get("ingredient", "")).strip()
        if not ingredient or ingredient.casefold() not in selected:
            continue
        record = item.get("record", {}) or {}
        jurisdictions = record.get("jurisdictions", {}) or {}
        statuses = {}
        for country, data in jurisdictions.items():
            status = str((data or {}).get("status", "UNKNOWN") or "UNKNOWN").upper()
            statuses[country] = get_status_display(status)
        distinct = sorted(set(statuses.values()))
        rows.append({
            "Ingredient": ingredient,
            "INS": str(record.get("ins_code", "") or "—"),
            "Jurisdictions with records": len(jurisdictions),
            "Distinct stored statuses": ", ".join(distinct) if distinct else "No stored record",
            "Attention jurisdictions": sum(1 for data in jurisdictions.values() if is_flagged_status(str((data or {}).get("status", "")))),
        })
    return rows


def build_reviewer_status_rows(normalized_results: list[dict], review_status: dict[str, dict]) -> list[dict]:
    rows = []
    for idx, item in enumerate(normalized_results, start=1):
        ingredient = str(item.get("canonical", "")).strip()
        if not ingredient:
            continue
        state = review_status.get(ingredient, {}) if isinstance(review_status, dict) else {}
        rows.append({
            "Rank": idx,
            "Ingredient": ingredient,
            "Reviewer status": state.get("status", "Not reviewed"),
            "Reviewer note": state.get("note", ""),
        })
    return rows


def build_dashboard_stats(normalized_results: list[dict], regulatory_results: list[dict], allergens: list[dict], nutrition_info: dict) -> dict:
    ingredients = [str(x.get("canonical", "")).strip() for x in normalized_results if str(x.get("canonical", "")).strip()]
    additives = [x for x in normalized_results if x.get("ins")]
    ordinary = [x for x in normalized_results if classify_ingredient(x.get("canonical", ""), x.get("ins")).get("type") == "ORDINARY_INGREDIENT"]
    unknown = [x for x in normalized_results if classify_ingredient(x.get("canonical", ""), x.get("ins")).get("type") == "UNKNOWN"]
    reg_records = 0
    flagged_records = 0
    countries = set()
    for item in regulatory_results:
        record = item.get("record", {}) or {}
        for country, data in (record.get("jurisdictions", {}) or {}).items():
            countries.add(country)
            reg_records += 1
            if is_flagged_status(str((data or {}).get("status", ""))):
                flagged_records += 1
    return {
        "ingredients": len(ingredients),
        "additives": len(additives),
        "ordinary_ingredients": len(ordinary),
        "unclassified": len(unknown),
        "allergen_signals": len(allergens),
        "regulatory_records": reg_records,
        "flagged_records": flagged_records,
        "jurisdictions": len(countries),
        "nutrition_fields": sum(1 for v in (nutrition_info or {}).values() if v not in (None, "", [])),
    }


def build_regulatory_heatmap_rows(regulatory_results: list[dict], countries: list[str]) -> list[dict]:
    country_set = [str(c).strip() for c in countries if str(c).strip()]
    rows = []
    for item in regulatory_results:
        ingredient = str(item.get("ingredient", "")).strip()
        record = item.get("record", {}) or {}
        if not ingredient:
            continue
        jurisdictions = record.get("jurisdictions", {}) or {}
        row = {"Ingredient": ingredient}
        for country in country_set:
            data = jurisdictions.get(country)
            if not data:
                row[country] = "—"
                continue
            status = str((data or {}).get("status", "UNKNOWN") or "UNKNOWN").upper()
            row[country] = get_status_display(status)
        rows.append(row)
    return rows


def build_ingredient_evidence_scores(regulatory_results: list[dict]) -> list[dict]:
    rows = []
    for item in regulatory_results:
        ingredient = str(item.get("ingredient", "")).strip()
        record = item.get("record", {}) or {}
        jurisdictions = record.get("jurisdictions", {}) or {}
        if not ingredient:
            continue
        total = len(jurisdictions)
        scored = 0
        tier1 = 0
        for data in jurisdictions.values():
            data = data or {}
            has_source = bool(str(data.get("source_url", "") or "").strip())
            has_authority = bool(str(data.get("authority", "") or "").strip())
            has_verified = bool(str(data.get("verified_date", "") or "").strip())
            if has_source and has_authority and has_verified:
                scored += 1
            source_type = str(data.get("source_type", "") or "").lower()
            if "official" in source_type or "government" in source_type or "regulator" in source_type:
                tier1 += 1
        pct = round((scored / total) * 100) if total else 0
        label = "🟢 Strong metadata" if pct >= 80 else "🟡 Partial metadata" if pct >= 50 else "🔴 Limited metadata" if total else "⚪ No stored record"
        rows.append({
            "Ingredient": ingredient,
            "Stored records": total,
            "Complete metadata records": scored,
            "Metadata coverage": f"{pct}%",
            "Official/regulator records": tier1,
            "Evidence status": label,
        })
    return sorted(rows, key=lambda r: (-r["Stored records"], r["Ingredient"].lower()))


def build_label_quality_score(scan_clarity: dict, label_checks: list[dict], nutrition: dict, normalized_results: list[dict], product_metadata: dict, source_quality: dict) -> dict:
    """Score label-data completeness/clarity only; never treat this as food safety or health score."""
    checks = []
    clarity = int(scan_clarity.get("score", 0) or 0)
    checks.append(("OCR / scan clarity", clarity, "Observable OCR and extraction signals"))
    detected_checks = sum(1 for row in label_checks if "✅" in str(row.get("Scan result", "")))
    total_checks = len(label_checks) or 1
    checks.append(("Label section completeness", round((detected_checks / total_checks) * 100), f"{detected_checks}/{total_checks} common sections detected"))
    ingredient_count = len([x for x in normalized_results if str(x.get("canonical", "")).strip()])
    checks.append(("Ingredient extraction", 100 if ingredient_count else 0, f"{ingredient_count} normalized ingredient(s)"))
    nutrition_fields = [k for k, v in (nutrition or {}).items() if k not in {"section_detected", "raw_text"} and v not in (None, "", "—")]
    nutrition_score = min(100, len(nutrition_fields) * 20) if nutrition.get("section_detected") else 0
    checks.append(("Nutrition extraction", nutrition_score, f"{len(nutrition_fields)} nutrition field(s) captured" if nutrition.get("section_detected") else "Nutrition panel not detected"))
    package_fields = [v for k, v in (product_metadata or {}).items() if k != "detected_fields" and str(v).strip()]
    checks.append(("Package metadata", min(100, len(package_fields) * 25), f"{len(package_fields)} package field(s) detected"))
    records = int(source_quality.get("total_records", 0) or 0) if isinstance(source_quality, dict) else 0
    verified = int(source_quality.get("with_verified_date", 0) or 0) if isinstance(source_quality, dict) else 0
    source_score = round(((verified / records) * 70) + (30 if records else 0)) if records else 0
    checks.append(("Regulatory evidence metadata", min(100, source_score), f"{records} stored record(s); {verified} with verification date"))
    weights = {"OCR / scan clarity": 0.25, "Label section completeness": 0.20, "Ingredient extraction": 0.20, "Nutrition extraction": 0.15, "Package metadata": 0.05, "Regulatory evidence metadata": 0.15}
    overall = round(sum(score * weights.get(name, 0) for name, score, _ in checks))
    level = "🟢 Strong data capture" if overall >= 85 else "🟡 Usable with review" if overall >= 65 else "🟠 Limited data capture"
    return {"score": overall, "level": level, "checks": [{"Area": n, "Score": sc, "Evidence": ev} for n, sc, ev in checks], "disclaimer": "This is a label/data-capture quality indicator, not a health, safety, legality, or product-quality score."}


def build_review_center_rows(review_queue: list[dict], allergens: list[dict], claims_rows: list[dict], coverage_action_rows: list[dict], freshness_rows: list[dict]) -> list[dict]:
    """Create one concise review queue from findings already present in the scan."""
    rows = []
    for item in review_queue or []:
        rows.append({"Priority": "High", "Area": "Ingredient identification", "Item": item.get("Ingredient", ""), "Why": item.get("Reason", item.get("Review reason", "Review normalization / OCR match")), "Action": "Verify ingredient wording and canonical match"})
    for allergen in allergens or []:
        rows.append({"Priority": "High", "Area": "Allergen signal", "Item": allergen.get("Allergen", ""), "Why": allergen.get("Reason", allergen.get("Evidence", "Allergen-related wording detected")), "Action": "Review against the product's allergen declaration and applicable labelling rules"})
    for claim in claims_rows or []:
        verdict = str(claim.get("Consistency", claim.get("Result", "")))
        if verdict and any(token in verdict.lower() for token in ["review", "inconsistent", "conflict", "uncertain"]):
            rows.append({"Priority": "Medium", "Area": "Label claim", "Item": claim.get("Claim", ""), "Why": verdict, "Action": "Check supporting label evidence and applicable claim rules"})
    for gap in coverage_action_rows or []:
        rows.append({"Priority": "Medium", "Area": "Regulatory coverage", "Item": gap.get("Ingredient", ""), "Why": gap.get("Action", gap.get("Reason", "No stored record for one or more comparison jurisdictions")), "Action": "Check the relevant jurisdiction source directly"})
    for fresh in freshness_rows or []:
        freshness = str(fresh.get("Freshness", fresh.get("Age", "")))
        if any(token in freshness.lower() for token in ["stale", "aging", "missing", "unknown"]):
            rows.append({"Priority": "Low", "Area": "Regulatory freshness", "Item": f"{fresh.get('Ingredient', '')} — {fresh.get('Country / jurisdiction', fresh.get('Country', ''))}", "Why": freshness, "Action": "Re-check the underlying official source"})
    return rows


def build_nutrition_consistency_rows(nutrition: dict) -> list[dict]:
    """Check internal nutrition-label consistency only; no health interpretation."""
    n = nutrition or {}
    rows = []
    serving = _parse_mass_grams(str(n.get("serving_size", "") or ""))
    per100 = {k: n.get(k) for k in ["energy_kcal", "total_fat_g", "saturated_fat_g", "carbohydrate_g", "total_sugars_g", "protein_g", "sodium_mg", "fibre_g"]}
    numeric_fields = {k: _numeric_value(v) for k, v in per100.items() if v not in (None, "", "—")}
    rows.append({"Check": "Nutrition section", "Result": "✅ Detected" if n.get("section_detected") else "⚠️ Not detected", "Detail": "Nutrition text was detected by OCR." if n.get("section_detected") else "No nutrition panel was isolated."})
    rows.append({"Check": "Serving-size basis", "Result": "✅ Detected" if serving else "ℹ️ Not available", "Detail": f"Parsed serving mass: {serving:g} g" if serving else "A numeric serving mass was not available."})
    negative = [k for k, v in numeric_fields.items() if v is not None and v < 0]
    rows.append({"Check": "Negative numeric values", "Result": "⚠️ Review" if negative else "✅ None detected", "Detail": ", ".join(negative) if negative else "No negative nutrition values were captured."})
    energy = numeric_fields.get("energy_kcal")
    rows.append({"Check": "Energy magnitude", "Result": "⚠️ Review" if energy is not None and energy > 10000 else "✅ Plausible", "Detail": "Captured energy value is unusually large; verify OCR/units." if energy is not None and energy > 10000 else "No obvious energy magnitude anomaly detected."})
    sugar = numeric_fields.get("total_sugars_g")
    carbs = numeric_fields.get("carbohydrate_g")
    if sugar is not None and carbs is not None:
        ok = sugar <= carbs + 0.01
        rows.append({"Check": "Sugars vs carbohydrate", "Result": "✅ Consistent" if ok else "⚠️ Review", "Detail": "Sugars do not exceed captured carbohydrate." if ok else "Captured sugars exceed captured carbohydrate; verify OCR/units."})
    return rows


def build_audit_snapshot(summary_display_rows: list[dict], dashboard_stats: dict, screening_decision: dict | None = None, review_action_checklist: list[dict] | None = None) -> str:
    decision = screening_decision or {}
    checklist = review_action_checklist or []
    lines = [
        "FOODREG AI — AUDIT SNAPSHOT",
        "Generated: " + datetime.now().strftime("%Y-%m-%d %H:%M"),
        "",
        "SCAN OVERVIEW",
        f"Ingredients: {dashboard_stats.get('ingredients', 0)}",
        f"Additives: {dashboard_stats.get('additives', 0)}",
        f"Potential allergen signals: {dashboard_stats.get('allergen_signals', 0)}",
        f"Jurisdictions with records: {dashboard_stats.get('jurisdictions', 0)}",
        f"Regulatory records: {dashboard_stats.get('regulatory_records', 0)}",
        f"Flagged regulatory records: {dashboard_stats.get('flagged_records', 0)}",
        "",
        "SCREENING DECISION",
        str(decision.get("level", decision.get("decision", "Not available"))),
        str(decision.get("summary", "")),
        "",
        "KEY INGREDIENT STATUS",
    ]
    for row in summary_display_rows[:25]:
        lines.append(f"- {row.get('Ingredient','')}: {row.get('Status','')} | {row.get('Country coverage', row.get('Jurisdictions with records',''))}")
    lines += ["", "REVIEW ACTIONS"]
    for row in checklist[:15]:
        lines.append(f"- [{row.get('Priority','')}] {row.get('Action','')}")
    lines += ["", "DISCLAIMER", "This snapshot summarizes label-derived OCR/NLP analysis and stored regulatory records. It is not legal advice, product certification, or a health risk score."]
    return "\n".join(lines)


def build_ingredient_glossary_rows(query: str = "") -> list[dict]:
    q = str(query or "").strip().casefold()
    rows = []
    for canonical, data in INGREDIENT_DATABASE.items():
        data = data if isinstance(data, dict) else {}
        aliases = data.get("aliases", []) or []
        if isinstance(aliases, str):
            aliases = [aliases]
        alias_text = ", ".join(str(a) for a in aliases if str(a).strip())
        haystack = " ".join([
            str(canonical), alias_text,
            str(data.get("ins", "")),
            str(data.get("cas", data.get("cas_number", ""))),
            str(data.get("description", "")),
        ]).casefold()
        if q and q not in haystack:
            continue
        rows.append({
            "Ingredient": str(canonical),
            "INS": str(data.get("ins", "") or "—"),
            "CAS": str(data.get("cas", data.get("cas_number", "")) or "—"),
            "Aliases": alias_text or "—",
            "Description": str(data.get("description", "") or "—"),
        })
    rows.sort(key=lambda r: r["Ingredient"].casefold())
    return rows[:100]




def build_review_progress(normalized_results: list[dict], reviewer_status: dict) -> dict:
    total = len([x for x in normalized_results or [] if str(x.get("canonical", "")).strip()])
    counts = {"Not reviewed": 0, "Reviewed": 0, "Needs follow-up": 0, "Resolved": 0}
    for item in normalized_results or []:
        name = str(item.get("canonical", "")).strip()
        if not name:
            continue
        status = str((reviewer_status or {}).get(name, {}).get("status", "Not reviewed") or "Not reviewed")
        counts[status] = counts.get(status, 0) + 1
    completed = counts.get("Reviewed", 0) + counts.get("Resolved", 0)
    percent = round((completed / total) * 100) if total else 0
    return {"total": total, "completed": completed, "percent": percent, "counts": counts}


def build_evidence_gap_rows(normalized_results: list[dict], regulatory_results: list[dict]) -> list[dict]:
    reg_by_name = {str(x.get("ingredient", "")).strip().lower(): x.get("record", {}) or {} for x in (regulatory_results or [])}
    rows = []
    for item in normalized_results or []:
        ingredient = str(item.get("canonical", "")).strip()
        if not ingredient:
            continue
        record = reg_by_name.get(ingredient.lower(), {})
        jurisdictions = record.get("jurisdictions", {}) or {}
        missing_record = not bool(jurisdictions)
        missing_source = sum(1 for data in jurisdictions.values() if not str((data or {}).get("source_url", "") or (data or {}).get("source", "")).strip())
        missing_authority = sum(1 for data in jurisdictions.values() if not str((data or {}).get("authority", "")).strip())
        missing_verified = sum(1 for data in jurisdictions.values() if not str((data or {}).get("verified", "")).strip())
        confidence = float(item.get("confidence", 0.0) or 0.0)
        gaps=[]
        if confidence < 0.80:
            gaps.append("Verify ingredient match")
        if missing_record:
            gaps.append("No stored regulatory record")
        if missing_source:
            gaps.append(f"{missing_source} record(s) missing source")
        if missing_authority:
            gaps.append(f"{missing_authority} record(s) missing authority")
        if missing_verified:
            gaps.append(f"{missing_verified} record(s) missing verification date")
        rows.append({
            "Ingredient": ingredient.title(),
            "Match confidence": f"{confidence:.2f}",
            "Regulatory records": len(jurisdictions),
            "Missing source": missing_source,
            "Missing authority": missing_authority,
            "Missing verification": missing_verified,
            "Evidence gaps": "; ".join(gaps) if gaps else "None detected",
            "Priority": "High" if missing_record or confidence < 0.70 else ("Medium" if gaps else "Low"),
        })
    rows.sort(key=lambda r: {"High": 0, "Medium": 1, "Low": 2}.get(r["Priority"], 3))
    return rows


def build_source_link_rows(regulatory_results: list[dict], ingredient: str = "", country: str = "") -> list[dict]:
    rows=[]
    ing_filter = str(ingredient or "").strip().casefold()
    country_filter = str(country or "").strip().casefold()
    for item in regulatory_results or []:
        ing = str(item.get("ingredient", "")).strip()
        if ing_filter and ing.casefold() != ing_filter:
            continue
        record = item.get("record", {}) or {}
        for jurisdiction, data in (record.get("jurisdictions", {}) or {}).items():
            if country_filter and str(jurisdiction).strip().casefold() != country_filter:
                continue
            source = str((data or {}).get("source_url", "") or (data or {}).get("source", "")).strip()
            if not source:
                continue
            rows.append({
                "Ingredient": ing.title(),
                "Jurisdiction": jurisdiction,
                "Status": str((data or {}).get("status", "—") or "—"),
                "Authority": str((data or {}).get("authority", "—") or "—"),
                "Last verified": str((data or {}).get("verified", "—") or "—"),
                "Source type": str((data or {}).get("source_type", "—") or "—"),
                "Source": source,
            })
    rows.sort(key=lambda r: (r["Ingredient"].casefold(), r["Jurisdiction"].casefold()))
    return rows


def build_current_scan_search_rows(query: str, normalized_results: list[dict], detected_text: list[str]) -> list[dict]:
    q=str(query or "").strip().casefold()
    if not q:
        return []
    rows=[]
    for rank, item in enumerate(normalized_results or [], start=1):
        canonical=str(item.get("canonical", "")).strip()
        original=str(item.get("original", "") or item.get("ocr_text", "")).strip()
        ins=str(item.get("ins", "") or "").strip()
        hay=" ".join([canonical, original, ins]).casefold()
        if q in hay:
            rows.append({"Match type": "Ingredient", "Ingredient": canonical.title(), "INS": ins or "—", "OCR text": original or "—", "Rank": rank})
    for idx, line in enumerate(detected_text or [], start=1):
        text=str(line or "").strip()
        if q in text.casefold():
            rows.append({"Match type": "OCR line", "Ingredient": "—", "INS": "—", "OCR text": text, "Rank": idx})
    return rows[:150]


def build_compliance_review_rows(summary_rows, normalized_results, regulatory_results, allergens, reviewer_status_rows):
    """Build one compact review row per identified ingredient."""
    allergen_names = set()
    for a in (allergens or []):
        if isinstance(a, dict):
            val = str(a.get("allergen", "")).strip().lower()
            if val:
                allergen_names.add(val)
    reg_by_name = {str(x.get("ingredient", "")).strip().lower(): x.get("record", {}) or {} for x in (regulatory_results or [])}
    review_by_name = {str(x.get("Ingredient", "")).strip().lower(): x for x in (reviewer_status_rows or [])}
    rows = []
    for item in normalized_results or []:
        canonical = str(item.get("canonical", "")).strip()
        if not canonical:
            continue
        rec = reg_by_name.get(canonical.lower(), {})
        jurisdictions = rec.get("jurisdictions", {}) or {}
        statuses = [str((d or {}).get("status", "UNKNOWN") or "UNKNOWN").upper() for d in jurisdictions.values()]
        prohibited = sum(st in {"BANNED", "NOT_AUTHORISED"} for st in statuses)
        restricted = sum(st == "RESTRICTED" for st in statuses)
        conditions = sum(st in {"CHECK_CONDITIONS", "CONDITIONAL", "CONDITIONS", "CHECK", "REGULATED"} for st in statuses)
        source_count = sum(bool(str((d or {}).get("source_url", "") or (d or {}).get("source", "")).strip()) for d in jurisdictions.values())
        verified_dates = [str((d or {}).get("verified", "")).strip() for d in jurisdictions.values() if str((d or {}).get("verified", "")).strip()]
        latest_verified = max(verified_dates) if verified_dates else "—"
        matched_allergen = any(name in canonical.lower() or canonical.lower() in name for name in allergen_names)
        reviewer = review_by_name.get(canonical.lower(), {})
        rows.append({
            "Ingredient": canonical.title(),
            "INS": str(item.get("ins", "") or "—"),
            "Match confidence": f"{float(item.get('confidence', 0.0) or 0.0):.2f}",
            "Category": classify_ingredient(canonical, item.get("ins")).get("category", "Other"),
            "Regulatory records": len(jurisdictions),
            "Prohibited": prohibited,
            "Restricted": restricted,
            "Conditions": conditions,
            "Sources": source_count,
            "Latest verified": latest_verified,
            "Allergen signal": "Yes" if matched_allergen else "No",
            "Reviewer status": str(reviewer.get("Status", "Not reviewed") or "Not reviewed"),
        })
    return rows


def build_label_evidence_rows(detected_text, ingredient_section, nutrition_info, product_metadata, scan_clarity):
    """Create an evidence map for what was actually captured from the label."""
    full_text = "\n".join(str(x) for x in (detected_text or []))
    rows = [
        {"Label field": "OCR lines", "Captured": len(detected_text or []), "Evidence": "Number of OCR lines returned by PaddleOCR."},
        {"Label field": "Ingredient section", "Captured": "Yes" if str(ingredient_section or "").strip() else "No", "Evidence": str(ingredient_section or "—")},
        {"Label field": "Nutrition panel", "Captured": "Yes" if any(v is not None for k, v in (nutrition_info or {}).items() if k not in {"serving_size", "servings_per_container", "declared_basis"}) else "No", "Evidence": "Structured nutrition fields extracted from OCR."},
        {"Label field": "Package metadata", "Captured": "Yes" if any(str(v).strip() for k, v in (product_metadata or {}).items() if k != "detected_fields" and v is not None) else "No", "Evidence": json.dumps(product_metadata or {}, ensure_ascii=False)},
        {"Label field": "OCR clarity", "Captured": scan_clarity.get("level", "Unknown") if isinstance(scan_clarity, dict) else "Unknown", "Evidence": f"Clarity score: {scan_clarity.get('score', '—') if isinstance(scan_clarity, dict) else '—'}"},
        {"Label field": "Raw OCR text", "Captured": "Yes" if full_text.strip() else "No", "Evidence": full_text[:5000] if full_text.strip() else "—"},
    ]
    return rows





def build_duplicate_ingredient_rows(normalized_results: list[dict]) -> list[dict]:
    """Find duplicate canonical ingredients created by parsing/normalization."""
    groups = {}
    for idx, item in enumerate(normalized_results or [], start=1):
        canonical = str(item.get("canonical", "") or "").strip()
        if not canonical:
            continue
        key = canonical.casefold()
        groups.setdefault(key, []).append({
            "Position": idx,
            "OCR text": str(item.get("original", "") or ""),
            "Canonical ingredient": canonical,
            "INS": str(item.get("ins", "") or "—"),
        })
    rows = []
    for entries in groups.values():
        if len(entries) < 2:
            continue
        canonical = entries[0]["Canonical ingredient"]
        rows.append({
            "Ingredient": canonical,
            "Occurrences": len(entries),
            "Positions": ", ".join(str(x["Position"]) for x in entries),
            "OCR variants": " | ".join(sorted({str(x["OCR text"]) for x in entries if str(x["OCR text"]).strip()})) or "—",
            "INS": entries[0]["INS"],
            "Review note": "Check whether repeated entries are true duplicates, compound-ingredient components, or OCR segmentation artifacts.",
        })
    return sorted(rows, key=lambda r: str(r["Ingredient"]).casefold())


def build_country_pair_diff_rows(regulatory_results: list[dict], country_a: str, country_b: str) -> list[dict]:
    """Compare two stored jurisdictions ingredient-by-ingredient."""
    if not country_a or not country_b or country_a == country_b:
        return []
    rows = []
    for item in regulatory_results or []:
        ingredient = str(item.get("ingredient", "") or "").strip().title()
        jurisdictions = (item.get("record", {}) or {}).get("jurisdictions", {}) or {}
        da = jurisdictions.get(country_a)
        db = jurisdictions.get(country_b)
        if not da and not db:
            continue
        da = da or {}
        db = db or {}
        sa = str(da.get("status", "NO_STORED_RECORD") or "NO_STORED_RECORD").upper()
        sb = str(db.get("status", "NO_STORED_RECORD") or "NO_STORED_RECORD").upper()
        level_a = " ".join(x for x in [str(da.get("maximum_level", "") or "").strip(), str(da.get("unit", "") or "").strip()] if x).strip() or "—"
        level_b = " ".join(x for x in [str(db.get("maximum_level", "") or "").strip(), str(db.get("unit", "") or "").strip()] if x).strip() or "—"
        cond_a = format_condition(da, sa) if da else "No stored record"
        cond_b = format_condition(db, sb) if db else "No stored record"
        differs = (sa != sb) or (level_a != level_b) or (cond_a != cond_b)
        if differs:
            rows.append({
                "Ingredient": ingredient,
                country_a: get_status_display(sa),
                f"{country_a} level": level_a,
                f"{country_a} conditions": cond_a,
                country_b: get_status_display(sb),
                f"{country_b} level": level_b,
                f"{country_b} conditions": cond_b,
                "Difference type": "Status / level / conditions differ",
            })
    return rows


def build_ingredient_evidence_grade_rows(normalized_results: list[dict], regulatory_results: list[dict], evidence_gap_rows: list[dict]) -> list[dict]:
    """Assign a transparent evidence grade from captured metadata; not a safety or legal score."""
    reg_map = {str(x.get("ingredient", "") or "").strip().casefold(): (x.get("record", {}) or {}) for x in regulatory_results or []}
    gap_map = {str(x.get("Ingredient", "") or "").strip().casefold(): x for x in evidence_gap_rows or []}
    rows = []
    for item in normalized_results or []:
        ingredient = str(item.get("canonical", "") or "").strip()
        if not ingredient:
            continue
        rec = reg_map.get(ingredient.casefold(), {})
        jurisdictions = rec.get("jurisdictions", {}) or {}
        source_count = sum(bool(str((d or {}).get("source_url", "") or (d or {}).get("source", "") or "").strip()) for d in jurisdictions.values())
        verified_count = sum(bool(str((d or {}).get("verified_date", "") or (d or {}).get("verified", "") or "").strip()) for d in jurisdictions.values())
        gaps = gap_map.get(ingredient.casefold(), {})
        score = 0
        confidence = float(item.get("confidence", 0.0) or 0.0)
        if confidence >= 0.90:
            score += 2
        elif confidence >= 0.75:
            score += 1
        if jurisdictions:
            score += 1
        if source_count:
            score += 1
        if verified_count:
            score += 1
        if str(gaps.get("Priority", "")).casefold() == "high":
            score -= 1
        grade = "A — Strong evidence metadata" if score >= 5 else "B — Good evidence metadata" if score >= 4 else "C — Partial evidence metadata" if score >= 2 else "D — Weak evidence metadata"
        rows.append({
            "Ingredient": ingredient.title(),
            "OCR match confidence": f"{confidence:.2f}",
            "Stored jurisdictions": len(jurisdictions),
            "Source records": source_count,
            "Verified records": verified_count,
            "Evidence gaps": str(gaps.get("Priority", "None") or "None"),
            "Evidence grade": grade,
            "Interpretation": "Metadata/evidence coverage only; not a safety, health, legal-compliance, or risk score.",
        })
    return rows


def build_reviewer_signoff_text(checks: dict, scan_id: str, now_text: str) -> str:
    labels = {
        "ingredients": "Ingredient identification reviewed",
        "allergens": "Allergen signals reviewed",
        "regulatory": "Regulatory findings and source links reviewed",
        "nutrition": "Nutrition/package fields reviewed",
    }
    lines = [
        "FoodReg AI reviewer sign-off",
        "",
        f"Scan ID: {scan_id or '—'}",
        f"Generated: {now_text}",
        "",
    ]
    done = 0
    for key, label in labels.items():
        state = bool(checks.get(key, False))
        if state:
            done += 1
        lines.append(f"[{'x' if state else ' '}] {label}")
    lines += [
        "",
        f"Checklist completion: {done}/{len(labels)}",
        "",
        "This sign-off records workflow completion only. It is not a legal certification, health assessment, or claim of regulatory compliance.",
    ]
    return "\n".join(lines)


def build_claim_conflict_rows(claim_rows: list[dict], normalized_results: list[dict], nutrition_info: dict) -> list[dict]:
    """Flag potential claim/evidence inconsistencies without certifying legal compliance."""
    names = [str(x.get("canonical", "")).strip().lower() for x in (normalized_results or []) if str(x.get("canonical", "")).strip()]
    joined = " | ".join(names)
    total_sugars = nutrition_info.get("total_sugars_g") if isinstance(nutrition_info, dict) else None
    protein = nutrition_info.get("protein_g") if isinstance(nutrition_info, dict) else None
    rules = [
        ("Gluten free", lambda: any(re.search(r"\bwheat\b|\bgluten\b", n) for n in names), "Wheat/gluten ingredient detected on the label."),
        ("No added sugar", lambda: any(re.search(r"\bsugar\b", n) for n in names), "Sugar is listed as an ingredient."),
        ("Sugar free", lambda: any(re.search(r"\bsugar\b", n) for n in names) or (isinstance(total_sugars, (int, float)) and total_sugars > 0), "Sugar ingredient or captured total sugars were detected."),
        ("No added salt", lambda: any(re.search(r"\bsalt\b", n) for n in names), "Salt is listed as an ingredient."),
        ("Low sodium / low salt", lambda: isinstance(nutrition_info.get("sodium_mg"), (int, float)) and nutrition_info.get("sodium_mg") > 0, "Sodium was captured on the nutrition panel; this does not establish whether the legal claim threshold is met."),
        ("Fat free", lambda: any(re.search(r"(?:vegetable|edible) oil|fat|butter|ghee", n) for n in names) or (isinstance(nutrition_info.get("total_fat_g"), (int, float)) and nutrition_info.get("total_fat_g") > 0), "A fat-containing ingredient or positive total fat value was captured."),
        ("Vegan", lambda: any(re.search(r"\bmilk\b|\bwhey\b|\bcasein\b|\begg\b|\bgelatin\b", n) for n in names), "A commonly animal-derived ingredient was detected."),
        ("Vegetarian", lambda: any(re.search(r"\bmeat\b|\bchicken\b|\bbeef\b|\bpork\b|\bfish\b|\bgelatin\b", n) for n in names), "A commonly animal-derived ingredient was detected."),
        ("No preservatives", lambda: any(re.search(r"preserv|benzoate|sorbate|propionate|nitrite|nitrate", n) for n in names), "A preservation-related ingredient name was detected."),
        ("No artificial colours", lambda: any(re.search(r"colour|color|caramel iv", n) for n in names), "A colour-related ingredient was detected; whether it is legally 'artificial' is jurisdiction-specific."),
        ("High protein", lambda: protein is None, "No structured protein value was captured, so the claim cannot be quantitatively checked from this label."),
    ]
    out_rows = []
    for claim in claim_rows or []:
        label = str(claim.get("Claim detected", "")).strip()
        fn = next((x[1] for x in rules if x[0].casefold() == label.casefold()), None)
        explanation = next((x[2] for x in rules if x[0].casefold() == label.casefold()), "")
        if fn is None:
            status = "Needs official/product-rule review"
            reason = "No deterministic conflict rule is configured for this claim."
        else:
            try:
                triggered = bool(fn())
            except Exception:
                triggered = False
            if triggered:
                status = "Potential inconsistency — review"
                reason = explanation
            else:
                status = "No direct conflict detected from captured evidence"
                reason = "The current OCR/structured fields did not trigger the configured screening rule."
        out_rows.append({
            "Claim": label or "—",
            "Screening result": status,
            "Evidence": str(claim.get("Evidence in OCR", "—") or "—"),
            "Why": reason,
            "Legal verification": "Required before treating the claim as compliant",
        })
    return out_rows


def build_regulatory_level_explorer_rows(regulatory_results: list[dict]) -> list[dict]:
    """Flatten stored regulatory records into a filterable level/conditions view."""
    rows = []
    for item in regulatory_results or []:
        ingredient = str(item.get("ingredient", "")).strip().title()
        for jurisdiction, data in ((item.get("record", {}) or {}).get("jurisdictions", {}) or {}).items():
            d = data or {}
            status = str(d.get("status", "UNKNOWN") or "UNKNOWN").upper()
            rows.append({
                "Ingredient": ingredient,
                "Jurisdiction": str(jurisdiction or "—"),
                "Status": get_status_display(status),
                "Food category": str(d.get("food_category", "") or "—"),
                "Maximum level": str(d.get("maximum_level", "") or "—"),
                "Unit": str(d.get("unit", "") or "—"),
                "Conditions": format_condition(d, status),
                "Restriction": str(d.get("restriction", "") or "—"),
                "Authority": str(d.get("authority", "") or "—"),
                "Last verified": str(d.get("verified", "") or "—"),
                "Source type": str(d.get("source_type", "") or "—"),
                "Source": str(d.get("source_url", "") or d.get("source", "") or "—"),
            })
    rows.sort(key=lambda r: (r["Ingredient"].casefold(), r["Jurisdiction"].casefold()))
    return rows


def build_ingredient_screening_matrix(normalized_results: list[dict], regulatory_results: list[dict], allergens: list[dict], evidence_gap_rows: list[dict], reviewer_status_rows: list[dict]) -> list[dict]:
    """Combine identification, allergen, regulatory and workflow signals in one audit table."""
    allergen_ingredients = set()
    for a in allergens or []:
        for name in a.get("ingredients", []) or []:
            allergen_ingredients.add(str(name).strip().casefold())
    reg_map = {str(x.get("ingredient", "")).strip().casefold(): (x.get("record", {}) or {}) for x in regulatory_results or []}
    gaps = {str(x.get("Ingredient", "")).strip().casefold(): x for x in evidence_gap_rows or []}
    reviews = {str(x.get("Ingredient", "")).strip().casefold(): x for x in reviewer_status_rows or []}
    rows=[]
    for item in normalized_results or []:
        name = str(item.get("canonical", "")).strip()
        if not name:
            continue
        key = name.casefold()
        rec = reg_map.get(key, {})
        jurisdictions = rec.get("jurisdictions", {}) or {}
        statuses = [str((d or {}).get("status", "UNKNOWN") or "UNKNOWN").upper() for d in jurisdictions.values()]
        prohibited = sum(s in {"BANNED", "NOT_AUTHORISED"} for s in statuses)
        restricted = sum(s == "RESTRICTED" for s in statuses)
        conditions = sum(s in {"CHECK_CONDITIONS", "CONDITIONAL", "CONDITIONS", "CHECK", "REGULATED"} for s in statuses)
        gap = gaps.get(key, {})
        review = reviews.get(key, {})
        if prohibited:
            signal = "High — stored prohibited/not-authorised finding"
        elif restricted:
            signal = "High — stored restricted finding"
        elif conditions:
            signal = "Medium — stored condition-based finding"
        elif name.casefold() in allergen_ingredients:
            signal = "Medium — allergen signal"
        elif str(gap.get("Priority", "")).casefold() == "high":
            signal = "High — evidence gap"
        elif str(gap.get("Priority", "")).casefold() == "medium":
            signal = "Medium — evidence gap"
        else:
            signal = "Standard screening"
        rows.append({
            "Ingredient": name.title(),
            "Type": classify_ingredient(name, item.get("ins")).get("label", "Unclassified ingredient"),
            "Match confidence": f"{float(item.get('confidence', 0.0) or 0.0):.2f}",
            "INS": str(item.get("ins", "") or "—"),
            "Allergen signal": "Yes" if key in allergen_ingredients else "No",
            "Regulatory jurisdictions": len(jurisdictions),
            "Prohibited": prohibited,
            "Restricted": restricted,
            "Conditions": conditions,
            "Evidence gaps": str(gap.get("Evidence gaps", "None detected")),
            "Reviewer status": str(review.get("Status", "Not reviewed") or "Not reviewed"),
            "Screening signal": signal,
        })
    return rows


def build_reviewer_handoff_text(screening_matrix: list[dict], claim_conflicts: list[dict], nutrition_consistency: list[dict], review_center_rows: list[dict]) -> str:
    """Create a compact handoff checklist for a human reviewer."""
    lines = ["FOODREG AI — REVIEWER HANDOFF", "=" * 34, ""]
    high = [r for r in screening_matrix if str(r.get("Screening signal", "")).startswith("High")]
    medium = [r for r in screening_matrix if str(r.get("Screening signal", "")).startswith("Medium")]
    lines.append(f"High-priority ingredient signals: {len(high)}")
    lines.append(f"Medium-priority ingredient signals: {len(medium)}")
    if high:
        lines += ["", "HIGH-PRIORITY INGREDIENTS"]
        lines.extend([f"[ ] {r['Ingredient']} — {r['Screening signal']}" for r in high])
    claim_issues = [r for r in claim_conflicts if "Potential inconsistency" in str(r.get("Screening result", ""))]
    if claim_issues:
        lines += ["", "CLAIMS REQUIRING REVIEW"]
        lines.extend([f"[ ] {r['Claim']} — {r['Why']}" for r in claim_issues])
    nutrition_issues = [r for r in nutrition_consistency if str(r.get("Status", "")).lower() not in {"ok", "no issue", "not available"}]
    if nutrition_issues:
        lines += ["", "NUTRITION DATA CHECKS"]
        lines.extend([f"[ ] {r.get('Field','—')} — {r.get('Status','—')} — {r.get('Explanation','—')}" for r in nutrition_issues])
    actionable = [r for r in review_center_rows if r.get("Priority") in {"High", "Medium"}]
    if actionable:
        lines += ["", "OTHER REVIEW CENTER ITEMS"]
        for r in actionable[:40]:
            lines.append(f"[ ] {r.get('Area','Review')} — {r.get('Priority','—')} — {r.get('Issue','—')}")
    if len(lines) == 5:
        lines += ["", "No high/medium reviewer actions were generated from the current stored evidence."]
    lines += ["", "DISCLAIMER", "This checklist is generated from OCR-derived label data and the regulatory records stored in FoodReg AI. It is a human-review aid, not legal advice or a legal compliance certificate."]
    return "\n".join(lines)

def build_clean_label_text(detected_text, ingredient_section, normalized_results, nutrition_info, product_metadata):
    """Create a plain-text evidence export without hidden conclusions."""
    lines = ["FOODREG AI — LABEL EVIDENCE EXPORT", "=" * 36, ""]
    if ingredient_section:
        lines += ["INGREDIENT SECTION", ingredient_section.strip(), ""]
    lines.append("IDENTIFIED INGREDIENTS")
    for item in normalized_results or []:
        canonical = str(item.get("canonical", "")).strip()
        if not canonical:
            continue
        original = str(item.get("original", "")).strip()
        ins = str(item.get("ins", "")).strip()
        extra = f" | INS {ins}" if ins else ""
        lines.append(f"- {canonical}{extra}" + (f" | OCR: {original}" if original else ""))
    lines.append("")
    lines.append("NUTRITION FIELDS CAPTURED")
    for key, value in (nutrition_info or {}).items():
        if value is not None and value != "":
            lines.append(f"- {key}: {value}")
    lines.append("")
    lines.append("PACKAGE METADATA CAPTURED")
    for key, value in (product_metadata or {}).items():
        if key == "detected_fields" or value in (None, ""):
            continue
        lines.append(f"- {key}: {value}")
    lines.append("")
    lines.append("RAW OCR TEXT")
    lines.extend(str(x) for x in (detected_text or []))
    return "\n".join(lines).strip() + "\n"

# =========================================================
# REGULATORY AUTO-UPDATE CENTER
# =========================================================

if REGULATORY_UPDATE_ENGINE_READY:
    try:
        ensure_update_schema()
        update_dashboard = get_update_dashboard()
    except Exception as _update_init_exc:
        update_dashboard = {"last_run": None, "pending_changes": 0, "events": [], "sources": []}
        st.session_state["reg_update_init_error"] = str(_update_init_exc)

    with st.sidebar.expander("🔄 Regulatory Update Center", expanded=False):
        st.caption(
            "Monitors configured official regulatory sources for source changes. "
            "A detected change creates a review event; it does not silently rewrite legal status."
        )

        if st.session_state.get("reg_update_init_error"):
            st.warning("Update engine could not initialize against the current database.")

        last_run = update_dashboard.get("last_run") if isinstance(update_dashboard, dict) else None
        pending_changes = int(update_dashboard.get("pending_changes", 0) or 0) if isinstance(update_dashboard, dict) else 0
        source_rows = update_dashboard.get("sources", []) if isinstance(update_dashboard, dict) else []
        event_rows = update_dashboard.get("events", []) if isinstance(update_dashboard, dict) else []

        m1, m2 = st.columns(2)
        with m1:
            st.metric("Official sources", len(source_rows))
        with m2:
            st.metric("Pending reviews", pending_changes)

        if last_run:
            st.caption(
                f"Last check: {last_run.get('finished_at','—')} • "
                f"Changed: {last_run.get('sources_changed',0)} • "
                f"Errors: {last_run.get('errors',0)}"
            )
        else:
            st.caption("No regulatory source check has been run yet.")

        source_options = [
            (str(x.get("source_key","")), str(x.get("jurisdiction","")))
            for x in source_rows
            if str(x.get("source_key",""))
        ]
        selected_pairs = st.multiselect(
            "Sources to check",
            options=source_options,
            default=source_options,
            format_func=lambda x: f"{x[1]} — {x[0]}",
            key="reg_update_sources",
        )
        selected_keys = [x[0] for x in selected_pairs]

        if st.button("🔄 Check official sources now", use_container_width=True, key="run_regulatory_source_monitor"):
            with st.spinner("Checking configured official regulatory sources…"):
                try:
                    update_run = run_source_monitor(selected_keys)
                    st.session_state["last_reg_update_run"] = update_run
                    update_dashboard = get_update_dashboard()
                    st.success(
                        f"Checked {update_run['sources_checked']} sources • "
                        f"{update_run['sources_changed']} changed • {update_run['errors']} errors"
                    )
                    if update_run["sources_changed"]:
                        st.warning("Source changes were detected. Review the pending events before treating stored regulatory records as current.")
                except Exception as _update_run_exc:
                    st.error(f"Regulatory source check failed: {_update_run_exc}")

        event_rows = update_dashboard.get("events", []) if isinstance(update_dashboard, dict) else []
        pending_event_rows = [e for e in event_rows if str(e.get("status","")).upper() == "PENDING_REVIEW"]
        if pending_event_rows:
            st.markdown("**Pending source-change events**")
            for e in pending_event_rows[:8]:
                try:
                    matched = json.loads(e.get("matched_ingredients") or "[]")
                except Exception:
                    matched = []
                matched_text = ", ".join(matched[:5]) if matched else "No stored ingredient match"
                st.warning(
                    f"#{e.get('id')} • {e.get('jurisdiction')} • {e.get('title')}\n\n"
                    f"Detected: {e.get('detected_at','—')} • {matched_text}"
                )

            event_ids = [str(e.get("id")) for e in pending_event_rows if e.get("id") is not None]
            if event_ids:
                selected_event = st.selectbox("Review event", event_ids, key="reg_update_review_event")
                rc1, rc2 = st.columns(2)
                with rc1:
                    review_status = st.selectbox("Decision", ["REVIEWED", "DISMISSED"], key="reg_update_review_status")
                with rc2:
                    reviewer_name = st.text_input("Reviewer", value="local-review", key="reg_update_reviewer")
                reviewer_note = st.text_area("Review note", key="reg_update_review_note", placeholder="Record what was verified and where.")
                if st.button("Save review decision", use_container_width=True, key="save_reg_update_review"):
                    try:
                        review_change_event(int(selected_event), review_status, reviewer_name or "local-review", reviewer_note)
                        st.success(f"Event #{selected_event} marked {review_status}.")
                        st.rerun()
                    except Exception as _review_exc:
                        st.error(f"Could not save review decision: {_review_exc}")
        else:
            st.success("No pending source-change events.")

        st.markdown("**Configured sources**")
        source_display = [
            {
                "Jurisdiction": x.get("jurisdiction",""),
                "Authority": x.get("authority",""),
                "Status": "Error" if x.get("error") else ("Checked" if x.get("checked_at") else "Not checked"),
                "Last checked": x.get("checked_at","") or "—",
            }
            for x in source_rows
        ]
        if source_display:
            st.dataframe(source_display, use_container_width=True, hide_index=True)

        try:
            update_audit_csv = build_update_audit_csv(update_dashboard)
            st.download_button(
                "⬇️ Download update audit CSV",
                data=update_audit_csv,
                file_name="foodreg_ai_regulatory_update_audit.csv",
                mime="text/csv",
                use_container_width=True,
                key="download_reg_update_audit_sidebar",
            )
        except Exception:
            pass
else:
    st.sidebar.warning("Regulatory update engine is not available. Add regulatory_update_engine.py beside app.py.")


# UPLOAD SECTION

# =========================================================


if "upload_version" not in st.session_state:
    st.session_state.upload_version = 0

if "has_upload" not in st.session_state:
    st.session_state.has_upload = False
if "analysis_complete" not in st.session_state:
    st.session_state.analysis_complete = False
if "analysis_data" not in st.session_state:
    st.session_state.analysis_data = None
if "file_signature" not in st.session_state:
    st.session_state.file_signature = None
if "review_notes" not in st.session_state:
    st.session_state.review_notes = ""
if "scan_history" not in st.session_state:
    st.session_state.scan_history = load_persistent_scan_history()
if "nutrition_review_thresholds" not in st.session_state:
    st.session_state.nutrition_review_thresholds = {
        "energy_kcal": 500.0,
        "total_sugars_g": 15.0,
        "total_fat_g": 20.0,
        "saturated_fat_g": 5.0,
        "sodium_mg": 600.0,
    }
if "ingredient_watchlist" not in st.session_state:
    st.session_state.ingredient_watchlist = []
if "ingredient_review_status" not in st.session_state:
    st.session_state.ingredient_review_status = {}
if "v14_reviewer_checks" not in st.session_state:
    st.session_state.v14_reviewer_checks = {"ingredients": False, "allergens": False, "regulatory": False, "nutrition": False}

st.markdown(

    '<div class="section-title">'

    "📸 Upload Product Label"

    "</div>",

    unsafe_allow_html=True,

)


if st.session_state.has_upload:
    top_col1, top_col2 = st.columns([1, 1])
    with top_col1:
        st.caption("Analyzing the currently uploaded label.")
    with top_col2:
        if st.button("↩ Upload another label", use_container_width=True, key="new_label_btn"):
            st.session_state.upload_version += 1
            st.session_state.has_upload = False
            st.session_state.analysis_complete = False
            st.session_state.analysis_data = None
            st.session_state.file_signature = None
            st.session_state.review_notes = ""
            st.session_state.ingredient_watchlist = []
            st.session_state.ingredient_review_status = {}
            st.session_state.v14_reviewer_checks = {"ingredients": False, "allergens": False, "regulatory": False, "nutrition": False}
            for _key in ("reg_ingredient_filter", "reg_country_filter", "reg_status_filter", "ingredient_watchlist_widget"):
                st.session_state.pop(_key, None)
            st.rerun()


st.write(

    "Upload a clear photo of the ingredient list printed "

    "on your food package."

)


uploaded_file = st.file_uploader(

    "Choose an image",

    type=[

        "jpg",

        "jpeg",

        "png",

    ],

    label_visibility="collapsed",

    key=f"upload_label_{st.session_state.upload_version}",

)

if uploaded_file is not None:
    st.session_state.has_upload = True
    current_file_signature = (uploaded_file.name, uploaded_file.size)
    if st.session_state.file_signature != current_file_signature:
        st.session_state.file_signature = current_file_signature
        st.session_state.analysis_complete = False
        st.session_state.analysis_data = None
        st.session_state.review_notes = ""
        st.session_state.v14_reviewer_checks = {"ingredients": False, "allergens": False, "regulatory": False, "nutrition": False}
        for _key in ("reg_ingredient_filter", "reg_country_filter", "reg_status_filter"):
            st.session_state.pop(_key, None)


# =========================================================

# NO IMAGE

# =========================================================


if uploaded_file is None:


    st.info(

        "Start by uploading a clear ingredient-label photo. "

        "Avoid glare, extreme blur, or very small text."

    )


    st.stop()


# =========================================================

# LOAD IMAGE

# =========================================================


try:


    image = Image.open(

        uploaded_file

    ).convert(

        "RGB"

    )


except Exception as exc:


    st.error(

        f"Could not open the image: {exc}"

    )


    st.stop()


image_np = np.array(

    image

)


# =========================================================

# PREVIEW

# =========================================================


st.divider()


col1, col2 = st.columns(

    [1, 1]

)


with col1:


    st.subheader(

        "📷 Product Image"

    )


    st.image(

        image,

        use_container_width=True,

    )


with col2:


    st.subheader(

        "🔍 Ready to Analyze"

    )


    st.markdown(

        """

        <div class="info-box">

        FoodReg AI will read the label, isolate the ingredient

        section, correct common OCR mistakes, standardize

        ingredient names, and check the regulatory records

        currently available in the project database.

        </div>

        """,

        unsafe_allow_html=True,

    )


    st.write("")


    analyze = st.button(

        "🔎 Analyze Ingredients",

        use_container_width=True,

        type="primary",

    )


# =========================================================

# ANALYSIS

# =========================================================
# =========================================================


if analyze or st.session_state.get("analysis_complete", False):

    if analyze:



        # -----------------------------------------------------

        # OCR

        # -----------------------------------------------------


        with st.spinner(

            "Reading and analyzing the ingredient label..."

        ):


            try:


                detected_text = run_ocr(

                    image_np

                )


            except Exception as exc:


                st.error(

                    f"Unable to read the image: {exc}"

                )


                st.stop()


        if not detected_text:


            st.warning(

                "No readable text was found. "

                "Try a clearer, closer photo with good lighting."

            )


            st.stop()


        # -----------------------------------------------------

        # CLEAN OCR

        # -----------------------------------------------------


        full_text = " ".join(

            detected_text

        )


        cleaned_text = clean_text(

            full_text

        )


        

        product_metadata = extract_product_metadata(detected_text)
# -----------------------------------------------------

        # EXTRACT INGREDIENT SECTION

        # -----------------------------------------------------


        ingredient_section = (

            extract_ingredient_section(

                detected_text

            )

        )


        if not ingredient_section:


            st.warning(

                "The ingredient section could not be detected. "

                "The app will not use the full OCR text as ingredients."

            )


            st.stop()


        # -----------------------------------------------------

        # EXTRACT INGREDIENTS

        # -----------------------------------------------------


        ingredients = extract_ingredients(

            ingredient_section

        )


        if not ingredients:


            st.warning(

                "The ingredient section was found, but no "

                "ingredient entries could be separated."

            )


            st.stop()


        # -----------------------------------------------------

        # NORMALIZATION

        # -----------------------------------------------------


        normalized_results = normalize_results(

            ingredients

        )

        correction_count = sum(
            1
            for item in normalized_results
            if (
                item.get("validation", {}).get("status") == "OCR_CORRECTED"
                or item.get("text_correction", {}).get("changed")
            )
        )

        nutrition_info = extract_nutrition_facts(detected_text)
        nutrition_comparison = build_nutrition_comparison(nutrition_info)
        ingredient_order_rows = build_ingredient_order_rows(normalized_results)
        label_completeness_rows = build_label_completeness_checks(detected_text, ingredient_section, nutrition_info)
        scan_clarity = build_scan_clarity_summary(detected_text, ingredient_section, normalized_results, correction_count)
        ingredient_audit_rows = build_ingredient_audit_rows(normalized_results)


        # =====================================================

        # SUMMARY

        # =====================================================


        st.divider()


        st.markdown(

            '<div class="section-title">'

            "🧾 Ingredient Analysis"

            "</div>",

            unsafe_allow_html=True,

        )


        total_count = len(

            normalized_results

        )


        additive_count = sum(

            1

            for item in normalized_results

            if item.get("ins")

        )


        regulatory_count = 0

        flagged_count = 0

        jurisdiction_record_count = 0


        regulatory_results = []


        # =====================================================

        # REGULATORY LOOKUP

        # =====================================================


        for item in normalized_results:


            canonical = str(

                item.get(

                    "canonical",

                    "",

                )

            ).strip()


            if not canonical:

                continue


            record = check_ingredient(

                canonical

            )


            regulatory_results.append(

                {

                    "ingredient": canonical,

                    "record": record,

                }

            )


            if record.get("found"):


                regulatory_count += 1


                jurisdiction_record_count += record.get(

                    "jurisdiction_count",

                    len(record.get("jurisdictions", {})),

                )


                for country_data in record.get(

                    "jurisdictions",

                    {},

                ).values():


                    if is_flagged_status(

                        country_data.get(

                            "status",

                            "",

                        )

                    ):


                        flagged_count += 1



    if analyze:
        ingredient_audit_rows = build_ingredient_audit_rows(normalized_results)
        product_glance = build_product_glance(normalized_results, [], nutrition_info, regulatory_results)
        st.session_state.analysis_data = {
            "detected_text": detected_text,
            "cleaned_text": cleaned_text,
            "ingredient_section": ingredient_section,
            "ingredients": ingredients,
            "normalized_results": normalized_results,
            "regulatory_results": regulatory_results,
            "total_count": total_count,
            "additive_count": additive_count,
            "correction_count": correction_count,
            "regulatory_count": regulatory_count,
            "flagged_count": flagged_count,
            "jurisdiction_record_count": jurisdiction_record_count,
            "nutrition_info": nutrition_info,
            "ingredient_order_rows": ingredient_order_rows,
            "label_completeness_rows": label_completeness_rows,
            "nutrition_comparison": nutrition_comparison,
            "scan_clarity": scan_clarity,
            "ingredient_audit_rows": ingredient_audit_rows,
            "product_metadata": product_metadata,
            "product_glance": product_glance,
        }
        st.session_state.analysis_complete = True
        history_time=datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        history_entry={
            "scan_id": hashlib.sha1(f"{uploaded_file.name if uploaded_file is not None else 'Uploaded label'}|{history_time}|{build_scan_fingerprint(normalized_results)}".encode("utf-8")).hexdigest()[:12],
            "time": history_time,
            "file": uploaded_file.name if uploaded_file is not None else "Uploaded label",
            "ingredients": total_count,
            "ingredient_names": [str(item.get("canonical", "")).strip() for item in normalized_results if str(item.get("canonical", "")).strip()],
            "ingredient_fingerprint": build_scan_fingerprint(normalized_results),
            "additives": additive_count,
            "allergens": 0,
            "regulatory_records": jurisdiction_record_count,
            "attention": "Recorded scan",
            "bookmarked": False,
            "product_name": str((product_metadata or {}).get("Product name", "") or "").strip(),
            "net_weight": str((product_metadata or {}).get("Net weight", "") or "").strip(),
            "mrp": str((product_metadata or {}).get("MRP", "") or "").strip(),
            "content_hash": build_content_hash(uploaded_file),
            "nutrition_snapshot": {k: nutrition_info.get(k) for k in ["energy_kcal", "protein_g", "carbohydrate_g", "total_sugars_g", "total_fat_g", "sodium_mg"] if nutrition_info.get(k) is not None},
            "regulatory_snapshot": build_regulatory_snapshot(regulatory_results),
            "claims_count": len(globals().get("claims_rows", []) or []),
        }
        st.session_state.scan_history=[history_entry]+[x for x in st.session_state.scan_history if x.get("scan_id") != history_entry["scan_id"]]
        st.session_state.scan_history=st.session_state.scan_history[:25]
        save_persistent_scan_history(st.session_state.scan_history)
    else:
        cached = st.session_state.get("analysis_data") or {}
        detected_text = cached.get("detected_text", [])
        cleaned_text = cached.get("cleaned_text", "")
        ingredient_section = cached.get("ingredient_section", "")
        ingredients = cached.get("ingredients", [])
        normalized_results = cached.get("normalized_results", [])
        regulatory_results = cached.get("regulatory_results", [])
        total_count = cached.get("total_count", len(normalized_results))
        additive_count = cached.get("additive_count", sum(1 for item in normalized_results if item.get("ins")))
        correction_count = cached.get("correction_count", 0)
        regulatory_count = cached.get("regulatory_count", 0)
        flagged_count = cached.get("flagged_count", 0)
        jurisdiction_record_count = cached.get("jurisdiction_record_count", 0)
        nutrition_info = cached.get("nutrition_info", extract_nutrition_facts(detected_text))
        ingredient_order_rows = cached.get("ingredient_order_rows", build_ingredient_order_rows(normalized_results))
        label_completeness_rows = cached.get("label_completeness_rows", build_label_completeness_checks(detected_text, ingredient_section, nutrition_info))
        nutrition_comparison = cached.get("nutrition_comparison", build_nutrition_comparison(nutrition_info))
        scan_clarity = cached.get("scan_clarity", build_scan_clarity_summary(detected_text, ingredient_section, normalized_results, correction_count))
        ingredient_audit_rows = cached.get("ingredient_audit_rows", build_ingredient_audit_rows(normalized_results))
        product_metadata = cached.get("product_metadata", extract_product_metadata(detected_text))
        product_glance = cached.get("product_glance", build_product_glance(normalized_results, [], nutrition_info, regulatory_results))

    nutrition_review_rows = []
    watchlist_rows = []
    reviewer_status_rows = []
    glossary_rows = []

    # =====================================================
    # NUTRITION SNAPSHOT + SERVING SIZE
    # =====================================================

    # =====================================================
    # PRODUCT AT A GLANCE
    # =====================================================

    st.markdown('<div class="section-title">🏷️ Product & Package Details</div>', unsafe_allow_html=True)
    st.caption("Only packaging details explicitly visible in the OCR text are shown. A blank field means it was not reliably detected.")
    pm = product_metadata or {}
    pm_cols = st.columns(5)
    for col, label, key in zip(
        pm_cols,
        ["Product name", "Net weight", "MRP", "Batch / lot", "Licence"],
        ["product_name", "net_weight", "mrp", "batch_no", "license_no"],
    ):
        with col:
            st.metric(label, pm.get(key) or "—")

    st.markdown('<div class="section-title">📋 Product at a Glance</div>', unsafe_allow_html=True)
    pg1, pg2, pg3, pg4, pg5 = st.columns(5)
    with pg1:
        st.metric("Ingredients", product_glance.get("ingredients", 0))
    with pg2:
        st.metric("Additives", product_glance.get("additives", 0))
    with pg3:
        st.metric("Allergen types", product_glance.get("allergen_types", 0))
    with pg4:
        st.metric("Nutrition values", product_glance.get("nutrition_values", 0))
    with pg5:
        st.metric("Jurisdictions", product_glance.get("countries", 0))
    st.caption("This is a label-analysis overview, not a health score or legal compliance verdict.")

    st.markdown('<div class="section-title">🥗 Nutrition Snapshot</div>', unsafe_allow_html=True)
    st.caption("Only values explicitly detected in the scanned label are shown. Missing values may simply mean the photo/OCR did not capture them.")

    nutrition_basis_text = []
    if nutrition_info.get("serving_size"):
        nutrition_basis_text.append(f"Serving size: **{nutrition_info['serving_size']}**")
    if nutrition_info.get("servings_per_container"):
        nutrition_basis_text.append(f"Servings/container: **{nutrition_info['servings_per_container']}**")
    if nutrition_info.get("declared_basis"):
        nutrition_basis_text.append(f"Label basis: **{nutrition_info['declared_basis']}**")
    if nutrition_basis_text:
        st.info(" • ".join(nutrition_basis_text))

    nutrition_display = [
        ("Energy", nutrition_info.get("energy_kcal"), "kcal"),
        ("Protein", nutrition_info.get("protein_g"), "g"),
        ("Carbohydrate", nutrition_info.get("carbohydrate_g"), "g"),
        ("Total sugars", nutrition_info.get("total_sugars_g"), "g"),
        ("Total fat", nutrition_info.get("total_fat_g"), "g"),
        ("Sodium", nutrition_info.get("sodium_mg"), "mg"),
    ]
    nutrition_display = [(a,b,c) for a,b,c in nutrition_display if b is not None]
    if nutrition_display:
        cols = st.columns(min(6, len(nutrition_display)))
        for idx, (label, value, unit) in enumerate(nutrition_display):
            with cols[idx % len(cols)]:
                st.metric(label, f"{value} {unit}")
        with st.expander("More detected nutrition fields"):
            more = [
                ("Energy (kJ)", nutrition_info.get("energy_kj"), "kJ"),
                ("Saturated fat", nutrition_info.get("saturated_fat_g"), "g"),
                ("Trans fat", nutrition_info.get("trans_fat_g"), "g"),
                ("Cholesterol", nutrition_info.get("cholesterol_mg"), "mg"),
                ("Dietary fibre", nutrition_info.get("fiber_g"), "g"),
                ("Added sugars", nutrition_info.get("added_sugars_g"), "g"),
            ]
            more = [(a,b,c) for a,b,c in more if b is not None]
            if more:
                st.dataframe([{"Nutrient":a, "Detected value":f"{b} {c}"} for a,b,c in more], use_container_width=True, hide_index=True)
            else:
                st.caption("No additional nutrition fields were confidently extracted.")
    elif nutrition_info.get("section_detected"):
        st.warning("Nutrition-related wording was detected, but no numeric nutrition values could be extracted reliably.")
    else:
        st.info("No clear nutrition panel was detected in the scan. This does not prove that the product has no nutrition label.")

    st.markdown('<div class="section-title">⚖️ Comparable Nutrition View</div>', unsafe_allow_html=True)
    st.caption("When the label provides a valid serving mass and a per-serving or per-100 g basis, FoodReg AI converts the detected values for easier comparison. Converted values are estimates from the label basis, not laboratory measurements.")
    if nutrition_comparison.get("rows"):
        st.info(nutrition_comparison.get("note", ""))
        st.dataframe(nutrition_comparison["rows"], use_container_width=True, hide_index=True)
    else:
        st.info(nutrition_comparison.get("note", "A comparable nutrition basis could not be established from the scan."))

    st.markdown('<div class="section-title">🎚️ My Nutrition Review Thresholds</div>', unsafe_allow_html=True)
    st.caption("Set your own screening thresholds for the declared label basis. These are configurable review rules, not medical recommendations or regulatory limits.")
    nt1, nt2, nt3, nt4, nt5 = st.columns(5)
    with nt1:
        st.session_state.nutrition_review_thresholds["energy_kcal"] = st.number_input("Calories", min_value=0.0, value=float(st.session_state.nutrition_review_thresholds["energy_kcal"]), step=25.0, key="threshold_energy")
    with nt2:
        st.session_state.nutrition_review_thresholds["total_sugars_g"] = st.number_input("Total sugars (g)", min_value=0.0, value=float(st.session_state.nutrition_review_thresholds["total_sugars_g"]), step=1.0, key="threshold_sugar")
    with nt3:
        st.session_state.nutrition_review_thresholds["total_fat_g"] = st.number_input("Total fat (g)", min_value=0.0, value=float(st.session_state.nutrition_review_thresholds["total_fat_g"]), step=1.0, key="threshold_fat")
    with nt4:
        st.session_state.nutrition_review_thresholds["saturated_fat_g"] = st.number_input("Saturated fat (g)", min_value=0.0, value=float(st.session_state.nutrition_review_thresholds["saturated_fat_g"]), step=0.5, key="threshold_satfat")
    with nt5:
        st.session_state.nutrition_review_thresholds["sodium_mg"] = st.number_input("Sodium (mg)", min_value=0.0, value=float(st.session_state.nutrition_review_thresholds["sodium_mg"]), step=25.0, key="threshold_sodium")
    nutrition_review_rows = build_custom_nutrition_review(nutrition_info, st.session_state.nutrition_review_thresholds)
    if nutrition_review_rows:
        st.dataframe(nutrition_review_rows, use_container_width=True, hide_index=True)
    else:
        st.info("No numeric nutrition values are available for the selected thresholds.")

    # =====================================================
    # INGREDIENT ORDER + PROMINENCE
    # =====================================================

    st.markdown('<div class="section-title">📌 Ingredient Order & Prominence</div>', unsafe_allow_html=True)
    st.caption("This reflects the order detected on the label. It does not estimate ingredient percentages unless the label itself provides them.")
    if ingredient_order_rows:
        st.dataframe(ingredient_order_rows, use_container_width=True, hide_index=True)
    else:
        st.info("No ingredient order could be built from the detected label text.")

    # =====================================================
    # LABEL COMPLETENESS CHECK
    # =====================================================

    st.markdown('<div class="section-title">🧾 Label Completeness Check</div>', unsafe_allow_html=True)
    st.caption("A scan-quality checklist only. It is not a legal compliance score because required label elements vary by product and jurisdiction.")
    detected_checks = sum(1 for row in label_completeness_rows if row.get("Scan result") == "✅ Detected")
    total_checks = len(label_completeness_rows)
    if total_checks:
        st.progress(detected_checks / total_checks, text=f"Detected {detected_checks} of {total_checks} common label sections")
    st.dataframe(label_completeness_rows, use_container_width=True, hide_index=True)

    # =====================================================
    # INGREDIENT IDENTIFICATION + REGULATORY SUMMARY
    # =====================================================

    st.markdown(
        '<div class="section-title">'
        "🧪 Identified Ingredients"
        "</div>",
        unsafe_allow_html=True,
    )

    for item in normalized_results:
        canonical = str(item.get("canonical", "")).strip()
        ins = item.get("ins")

        if not canonical:
            continue

        display_name = canonical.title()
        icon = "🧪" if ins else "🥣"
        code_html = (
            f'<div class="ingredient-code">INS {ins}</div>'
            if ins
            else ""
        )

        st.markdown(
            f"""
            <div class="ingredient-card">
                <div class="ingredient-name">{icon} {display_name}</div>
                {code_html}
            </div>
            """,
            unsafe_allow_html=True,
        )

    # =====================================================
    # INGREDIENT VERIFICATION AUDIT
    # =====================================================

    st.markdown('<div class="section-title">🔎 Ingredient Verification Audit</div>', unsafe_allow_html=True)
    st.caption("Follow the extraction path from the OCR text to the normalized ingredient and INS code. Confidence is the normalizer's matching signal, not OCR engine confidence.")
    review_queue = build_review_queue(ingredient_audit_rows)
    if review_queue:
        st.warning(f"{len(review_queue)} ingredient entr{'y needs' if len(review_queue)==1 else 'ies need'} review before relying on the downstream regulatory result.")
    st.dataframe(ingredient_audit_rows, use_container_width=True, hide_index=True)
    with st.expander("Show how FoodReg AI classified each entry"):
        for row in ingredient_audit_rows:
            st.markdown(f"**#{row['Rank']} {row['Normalized ingredient']}**  ")
            st.caption(f"OCR: {row['OCR text']} → Corrected: {row['Corrected text']} → {row['Confidence']} → {row['Review']}")

    st.markdown('<div class="section-title">📝 Reviewer Status Tracker</div>', unsafe_allow_html=True)
    st.caption("Mark individual ingredients as reviewed or needing follow-up. These statuses are local review annotations and do not change the regulatory database.")
    review_options = [str(item.get("canonical", "")).strip() for item in normalized_results if str(item.get("canonical", "")).strip()]
    if review_options:
        rs1, rs2, rs3 = st.columns([2, 1, 3])
        with rs1:
            selected_review_ingredient = st.selectbox("Ingredient", review_options, key="review_status_ingredient")
        with rs2:
            selected_review_status = st.selectbox("Status", ["Not reviewed", "Reviewed", "Needs follow-up", "Resolved"], key="review_status_value")
        with rs3:
            selected_review_note = st.text_input("Reviewer note", key="review_status_note", placeholder="Optional note…")
        if st.button("Save ingredient review status", key="save_review_status_btn"):
            st.session_state.ingredient_review_status[selected_review_ingredient] = {
                "status": selected_review_status,
                "note": selected_review_note.strip(),
            }
            st.success(f"Saved review status for {selected_review_ingredient}.")
        reviewer_status_rows = build_reviewer_status_rows(normalized_results, st.session_state.ingredient_review_status)
        st.dataframe(reviewer_status_rows, use_container_width=True, hide_index=True)

    st.markdown('<div class="section-title">✅ Review Progress</div>', unsafe_allow_html=True)
    review_progress = build_review_progress(normalized_results, st.session_state.ingredient_review_status)
    rp1, rp2, rp3, rp4 = st.columns(4)
    rp1.metric("Ingredients", review_progress["total"])
    rp2.metric("Completed", review_progress["completed"])
    rp3.metric("Progress", f"{review_progress["percent"]}%")
    rp4.metric("Follow-up", review_progress["counts"].get("Needs follow-up", 0))
    st.progress(review_progress["percent"] / 100 if review_progress["percent"] else 0.0)
    st.caption("Completed means an ingredient is marked Reviewed or Resolved. This is a workflow progress indicator, not a compliance score.")

    st.markdown('<div class="section-title">🔎 Current Label Search</div>', unsafe_allow_html=True)
    st.caption("Search the current scan's normalized ingredients and raw OCR lines. Useful for quickly locating wording such as INS codes, allergens, or nutrition terms.")
    scan_search_query = st.text_input("Search this label", key="current_scan_search_query", placeholder="Example: 330, peanut, sugar, sodium…")
    current_scan_search_rows = build_current_scan_search_rows(scan_search_query, normalized_results, detected_text)
    if scan_search_query.strip():
        if current_scan_search_rows:
            st.dataframe(current_scan_search_rows, use_container_width=True, hide_index=True)
        else:
            st.info("No matching ingredient or OCR line was found in the current scan.")

    st.markdown('<div class="section-title">📚 Ingredient Glossary Search</div>', unsafe_allow_html=True)
    st.caption("Search the built-in ingredient/additive reference used by FoodReg AI for canonical names, INS/CAS identifiers, aliases and descriptions.")
    glossary_query = st.text_input("Search ingredient glossary", key="ingredient_glossary_query", placeholder="Example: caramel, 330, peanut, guar…")
    glossary_rows = build_ingredient_glossary_rows(glossary_query)
    if glossary_rows:
        st.dataframe(glossary_rows, use_container_width=True, hide_index=True)
    else:
        st.info("No glossary entries matched that search.")

    # =====================================================
    # ALLERGEN ALERTS
    # =====================================================

    allergens = detect_allergens(normalized_results)
    product_glance = build_product_glance(normalized_results, allergens, nutrition_info, regulatory_results)

    st.markdown(
        '<div class="section-title">'
        "⚠️ Allergen Alerts"
        "</div>",
        unsafe_allow_html=True,
    )

    if allergens:
        st.warning(
            "Potential allergens identified directly from the ingredient list. "
            "This is a label-based identification feature, not a medical diagnosis."
        )

        for item in allergens:
            st.markdown(
                f"""
                <div class="alert-card">
                    <div class="alert-title">⚠️ {item["allergen"]}</div>
                    <div class="alert-meta"><b>Found in:</b> {', '.join(item["ingredients"])}</div>
                    <div class="alert-meta">{item["explanation"]}</div>
                </div>
                """,
                unsafe_allow_html=True,
            )
    else:
        st.success("No common allergens were detected from the identified ingredient names.")

    st.markdown(
        '<div class="section-title">'
        "💡 Ingredient Insights"
        "</div>",
        unsafe_allow_html=True,
    )

    st.caption(
        "These are plain-language ingredient explanations based on the label. "
        "They are not medical advice and do not determine whether a product is healthy or unhealthy for a specific person."
    )

    for item in normalized_results:
        canonical = str(item.get("canonical", "")).strip()
        if not canonical:
            continue

        insight = get_ingredient_insight(canonical)
        with st.expander(f"{canonical.title()}"):
            st.markdown(f"**What it does:** {insight['role']}")
            st.markdown(f"**Things to know:** {insight['notes']}")

    # =====================================================
    # ADDITIVE FUNCTION + SOURCE QUALITY
    # =====================================================

    additive_function_rows = build_additive_function_rows(normalized_results)
    st.markdown('<div class="section-title">🧪 Additive Function & INS Guide</div>', unsafe_allow_html=True)
    st.caption("Plain-language function classifications from the ingredient name, label wording, and the current reference library. This is not a health rating.")
    if additive_function_rows:
        st.dataframe(additive_function_rows, use_container_width=True, hide_index=True)
    else:
        st.info("No food additives were identified in this label analysis.")

    st.markdown('<div class="section-title">🔎 Additive Function Explorer</div>', unsafe_allow_html=True)
    st.caption("Search the detected additive function/reference rows. This is a reference aid, not a toxicology or health assessment.")
    function_query = st.text_input("Search additive/function", key="additive_function_query", placeholder="Example: colour, acidity, 330, thickener…")
    function_rows_filtered = build_function_explorer_rows(additive_function_rows, function_query)
    if function_rows_filtered:
        st.dataframe(function_rows_filtered, use_container_width=True, hide_index=True)
    elif additive_function_rows:
        st.info("No additive function row matched that search.")
    else:
        st.info("No additive function data is available for this scan.")

    source_quality = build_regulatory_source_quality(regulatory_results)
    jurisdiction_attention_rows = build_jurisdiction_attention_rows(regulatory_results)
    st.markdown('<div class="section-title">🔗 Regulatory Source Quality</div>', unsafe_allow_html=True)
    st.caption("Metadata completeness for the regulatory records currently stored in FoodReg AI.")
    sq1, sq2, sq3, sq4 = st.columns(4)
    with sq1: st.metric("Records checked", source_quality["total_records"])
    with sq2: st.metric("Source links", source_quality["with_source_url"])
    with sq3: st.metric("Authorities listed", source_quality["with_authority"])
    with sq4: st.metric("Verified dates", source_quality["with_verified_date"])

    st.markdown('<div class="section-title">🌍 Jurisdiction Attention Summary</div>', unsafe_allow_html=True)
    st.caption("Counts of stored jurisdiction findings by severity category; not a legal verdict on the product.")
    if jurisdiction_attention_rows:
        st.dataframe(jurisdiction_attention_rows, use_container_width=True, hide_index=True)
    else:
        st.info("No jurisdiction-level records are available yet.")

    regulatory_consistency_rows = build_regulatory_consistency_rows(regulatory_results)
    st.markdown('<div class="section-title">🧹 Regulatory Data Consistency Audit</div>', unsafe_allow_html=True)
    st.caption("Checks the internal completeness/consistency of stored metadata such as status, conditions, source and verification date. It does not determine whether the underlying regulation is legally correct.")
    if regulatory_consistency_rows:
        st.dataframe(regulatory_consistency_rows, use_container_width=True, hide_index=True)
    else:
        st.success("No metadata consistency issues were detected in the stored regulatory records for this scan.")

    st.markdown(
        '<div class="section-title">'
        "🚦 How to read the regulatory levels"
        "</div>",
        unsafe_allow_html=True,
    )

    st.markdown(
        """
        <div style="border:1px solid #E4CF8A; border-radius:12px; padding:14px 16px; margin-bottom:18px; background:#FFF6D5; color:#2E2020;">
            <div style="margin-bottom:8px; font-weight:650;">Each ingredient is classified using the strongest verified finding in the database:</div>
            <table style="width:100%; border-collapse:collapse; font-size:14px;">
                <tr><td style="padding:7px 8px; border-bottom:1px solid #eee; width:190px;"><b>🔴 Prohibited</b></td><td style="padding:7px 8px; border-bottom:1px solid #eee;">The checked jurisdiction does not permit the ingredient/use.</td></tr>
                <tr><td style="padding:7px 8px; border-bottom:1px solid #eee;"><b>🟠 Restricted</b></td><td style="padding:7px 8px; border-bottom:1px solid #eee;">Allowed only under specific restrictions.</td></tr>
                <tr><td style="padding:7px 8px; border-bottom:1px solid #eee;"><b>🟡 Conditions apply</b></td><td style="padding:7px 8px; border-bottom:1px solid #eee;">Use depends on food category, maximum level, GMP, footnotes, or other conditions.</td></tr>
                <tr><td style="padding:7px 8px; border-bottom:1px solid #eee;"><b>🟢 No restriction found</b></td><td style="padding:7px 8px; border-bottom:1px solid #eee;">A verified positive record is present and no stronger restriction was found in the checked records.</td></tr>
                <tr><td style="padding:7px 8px; border-bottom:1px solid #eee;"><b>ℹ️ Food ingredient</b></td><td style="padding:7px 8px; border-bottom:1px solid #eee;">Primarily a food/commodity ingredient rather than an additive. Product standards and labelling rules may apply.</td></tr>
                <tr><td style="padding:7px 8px;"><b>⚪ Not verified</b></td><td style="padding:7px 8px;">The database does not yet contain enough verified regulatory coverage for this ingredient.</td></tr>
            </table>
            <div style="margin-top:10px; font-size:13px; color:#555;">
                <b>UK note:</b> Food-additive rules are shown separately for <b>Great Britain</b> (England, Scotland and Wales) and <b>Northern Ireland</b> because their applicable frameworks differ.
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    st.markdown(
        '<div class="section-title">'
        "🚨 Regulatory Summary"
        "</div>",
        unsafe_allow_html=True,
    )

    st.caption(
        "This is a quick screening summary. A missing record means the ingredient "
        "is not yet covered by the current database; it does not mean the ingredient "
        "is automatically safe, approved, or unrestricted."
    )

    # Build one clear risk result per detected ingredient.
    summary_rows = []
    prohibited_count = 0
    restricted_count = 0
    conditions_count = 0
    no_restriction_count = 0
    not_verified_count = 0

    for item in normalized_results:
        canonical = str(item.get("canonical", "")).strip()
        ins = item.get("ins")
        if not canonical:
            continue

        record = next(
            (
                result_item.get("record", {})
                for result_item in regulatory_results
                if result_item.get("ingredient", "").strip().lower() == canonical.lower()
            ),
            {},
        )

        jurisdictions = record.get("jurisdictions", {}) if record.get("found") else {}

        statuses = [
            str(data.get("status", "")).upper()
            for data in jurisdictions.values()
        ]

        ingredient_class = classify_ingredient(canonical, ins)

        if not record.get("found") or not jurisdictions:
            if ingredient_class.get("type") == "ORDINARY_INGREDIENT":
                risk = "ℹ️ Food ingredient"
                risk_order = 4
            else:
                risk = "⚪ Not verified"
                risk_order = 5
                not_verified_count += 1
        elif any(status in {"BANNED", "NOT_AUTHORISED"} for status in statuses):
            risk = "🔴 Prohibited"
            risk_order = 1
            prohibited_count += 1
        elif any(status == "RESTRICTED" for status in statuses):
            risk = "🟠 Restricted"
            risk_order = 2
            restricted_count += 1
        elif any(status in {"CHECK_CONDITIONS", "CHECK", "REGULATED"} for status in statuses):
            risk = "🟡 Conditions apply"
            risk_order = 3
            conditions_count += 1
        elif all(status in {"AUTHORISED", "LISTED"} for status in statuses):
            risk = "🟢 No restriction found"
            risk_order = 5
            no_restriction_count += 1
        else:
            risk = "⚪ Not verified"
            risk_order = 4
            not_verified_count += 1

        country_count = len(jurisdictions)
        countries = ", ".join(jurisdictions.keys()) if jurisdictions else "—"

        summary_rows.append(
            {
                "Ingredient": canonical.title(),
                "INS": str(ins).upper() if ins else "—",
                "Regulatory flag": risk,
                "Ingredient type": ingredient_class.get("label", ""),
                "Why flagged": get_risk_explanation(risk, ingredient_class),
                "Countries with records": country_count,
                "Covered countries": countries,
                "_risk_order": risk_order,
            }
        )

    # Put the strongest warning at the top of the table.
    summary_rows.sort(key=lambda row: (row["_risk_order"], row["Ingredient"]))

    food_ingredient_count = sum(
        1
        for row in summary_rows
        if row.get("Regulatory flag") == "ℹ️ Food ingredient"
    )

    sc1, sc2, sc3, sc4, sc5, sc6 = st.columns(6)
    with sc1:
        st.metric("🔴 Prohibited", prohibited_count)
    with sc2:
        st.metric("🟠 Restricted", restricted_count)
    with sc3:
        st.metric("🟡 Conditions", conditions_count)
    with sc4:
        st.metric("🟢 No restriction", no_restriction_count)
    with sc5:
        st.metric("ℹ️ Food ingredients", food_ingredient_count)
    with sc6:
        st.metric("⚪ Not verified", not_verified_count)

    summary_display_rows = [
        {key: value for key, value in row.items() if key != "_risk_order"}
        for row in summary_rows
    ]

    if summary_display_rows:
        st.dataframe(
            summary_display_rows,
            use_container_width=True,
            hide_index=True,
        )
    else:
        st.info("No ingredients were identified for regulatory screening.")

    # =====================================================
    # PRODUCT SCREENING OVERVIEW
    # =====================================================

    country_alerts = []
    for result_item in regulatory_results:
        ingredient = str(result_item.get("ingredient", "")).strip()
        record = result_item.get("record", {})
        for country, data in record.get("jurisdictions", {}).items():
            status = str(data.get("status", "UNKNOWN") or "UNKNOWN").upper()
            if status in {"BANNED", "NOT_AUTHORISED", "RESTRICTED"}:
                country_alerts.append(
                    {
                        "Ingredient": ingredient.title(),
                        "Country": country,
                        "Status": get_status_display(status),
                        "Condition": get_condition_explanation("", data.get("restriction", ""), status),
                    }
                )

    attention = get_attention_level(summary_rows, allergens, country_alerts)
    concerns = build_concern_list(summary_rows, allergens, country_alerts)

    st.markdown(
        '<div class="section-title">📌 Product Screening Overview</div>',
        unsafe_allow_html=True,
    )
    st.markdown(
        f"""
        <div class="hero-card">
            <div class="hero-kicker">Label-based screening result</div>
            <div class="hero-title">{escape(attention['title'])}</div>
            <div class="hero-text"><b>{escape(attention['level'])}</b><br>{escape(attention['text'])}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    ov1, ov2 = st.columns(2)
    with ov1:
        st.markdown('<div class="section-title" style="margin-top:4px;">⚠️ Main things to review</div>', unsafe_allow_html=True)
        attention_items = list(concerns)
        if scan_clarity.get("score", 100) < 85:
            attention_items.append(f"Scan clarity: {scan_clarity.get('level')} ({scan_clarity.get('score')}/100)")
        missing_sections = [row.get("Check") for row in label_completeness_rows if row.get("Scan result") == "⚠️ Not detected"]
        if missing_sections:
            attention_items.append("Label sections not detected: " + ", ".join(missing_sections[:3]))
        if nutrition_info.get("section_detected") and nutrition_info.get("value_count", 0) < 2:
            attention_items.append("Nutrition wording detected, but few numeric nutrition values were captured")
        if review_queue:
            attention_items.append(f"{len(review_queue)} ingredient identification{' needs' if len(review_queue)==1 else 's need'} review")
        if attention_items:
            for concern in attention_items[:6]:
                st.markdown(f"- {escape(concern)}")
        else:
            st.success("No major label-derived concern was identified by the current rules.")
    with ov2:
        st.markdown('<div class="section-title" style="margin-top:4px;">🩺 Health context</div>', unsafe_allow_html=True)
        st.markdown(
            f"""<div class="info-box">
            <b>Scan clarity:</b> {escape(str(scan_clarity.get('level', 'Not calculated')))} — {escape(str(scan_clarity.get('score', '—')))} / 100.<br>
            Nutrition values shown by FoodReg AI come only from the detected label text. Any converted value is derived from the label basis and should be treated as an estimate.<br>
            This is not a medical, dietary, or blood-glucose risk score.
            </div>""",
            unsafe_allow_html=True,
        )

    # =====================================================
    # QUICK INGREDIENT FOCUS
    # =====================================================

    st.markdown(
        '<div class="section-title">🎯 Quick Ingredient Focus</div>',
        unsafe_allow_html=True,
    )
    st.caption(
        "Choose one ingredient to see its overall classification and strongest "
        "regulatory finding without scrolling through the full report."
    )

    focus_options = [row["Ingredient"] for row in summary_display_rows]
    if focus_options:
        focus_name = st.selectbox(
            "Choose an ingredient",
            ["Select an ingredient"] + focus_options,
            key="focus_ingredient_select",
        )

        if focus_name != "Select an ingredient":
            focus_row = next(
                (
                    row
                    for row in summary_display_rows
                    if row["Ingredient"] == focus_name
                ),
                None,
            )
            if focus_row:
                fc1, fc2, fc3 = st.columns(3)
                with fc1:
                    st.metric("Status", focus_row["Regulatory flag"])
                with fc2:
                    st.metric("Type", focus_row["Ingredient type"])
                with fc3:
                    st.metric("Countries", focus_row["Countries with records"])

                st.markdown(
                    f"""
                    <div class="info-box">
                        <div class="ingredient-name">{escape(focus_row["Ingredient"])}</div>
                        <div style="margin-top:8px;"><b>Why:</b> {escape(focus_row["Why flagged"])}</div>
                        <div style="margin-top:6px;"><b>Countries:</b> {escape(focus_row["Covered countries"])}</div>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )

    # =====================================================
    # OCR CLARITY SUMMARY
    # =====================================================

    st.markdown('<div class="section-title">🔬 OCR Clarity Summary</div>', unsafe_allow_html=True)
    sc1, sc2, sc3 = st.columns(3)
    with sc1:
        st.metric("Clarity score", f"{scan_clarity.get('score', 0)}/100")
    with sc2:
        st.metric("Uncertain ingredient matches", scan_clarity.get("uncertain_items", 0))
    with sc3:
        st.metric("Normalization errors", scan_clarity.get("normalization_errors", 0))
    if scan_clarity.get("reasons"):
        st.warning("Review flags: " + " • ".join(scan_clarity["reasons"]))
    else:
        st.success("The current OCR and ingredient-normalization signals look consistent.")

    # =====================================================
    # SCAN QUALITY + DATA COVERAGE
    # =====================================================

    st.markdown(
        '<div class="section-title">🔎 Scan & Data Quality</div>',
        unsafe_allow_html=True,
    )

    section_found=bool(ingredient_section.strip())
    ocr_line_count=len([line for line in detected_text if str(line).strip()])
    coverage_stats=build_coverage_stats(regulatory_results)

    q1,q2,q3,q4,q5=st.columns(5)
    with q1: st.metric("OCR lines", ocr_line_count)
    with q2: st.metric("Ingredient section", "Detected" if section_found else "Not detected")
    with q3: st.metric("OCR corrections", correction_count)
    with q4: st.metric("Sources linked", coverage_stats["linked_sources"])
    with q5: st.metric("Latest verification", coverage_stats["latest_verified"])

    if not section_found:
        st.warning("The ingredient heading could not be isolated reliably. Review the extracted ingredients before relying on the regulatory comparison.")
    elif ocr_line_count < 5:
        st.info("The scan produced a small amount of OCR text. A clearer or closer photo may improve ingredient recognition.")
    elif correction_count:
        st.info("Some OCR corrections were applied. Review corrected ingredient/code entries before using the regulatory results.")
    elif scan_clarity.get("score", 100) >= 85:
        st.success("OCR text volume, ingredient extraction, and normalization signals are reasonably clear.")

    if coverage_stats["framework_records"]:
        st.caption(f"{coverage_stats['framework_records']} regulatory entries are framework/reference records. Exact compliance can still depend on food category, function, amount, labelling, or other conditions.")

    st.markdown('<div class="section-title">🧾 OCR Trace</div>', unsafe_allow_html=True)
    st.caption("This lets you audit how the scanned text led to the detected ingredient section. OCR output may contain mistakes; the normalized ingredient list should be reviewed when corrections are shown.")
    with st.expander("Show OCR text and extracted ingredient section"):
        ot1, ot2 = st.columns(2)
        with ot1:
            st.text_area("Raw OCR text", "\n".join(str(x) for x in detected_text), height=240, key="ocr_trace_raw", disabled=True)
        with ot2:
            st.text_area("Extracted ingredient section", ingredient_section or "(not detected)", height=240, key="ocr_trace_ingredients", disabled=True)
        st.write(f"**Cleaned text:** {cleaned_text[:1200] + ('…' if len(cleaned_text) > 1200 else '')}")

    # Existing detailed country-by-country records remain below.
    # =====================================================
    # METRICS
    # =====================================================

    covered_jurisdictions_set = set()

    for result_item in regulatory_results:
        result_record = result_item.get("record", {})

        for jurisdiction_name in result_record.get("jurisdictions", {}).keys():
            covered_jurisdictions_set.add(jurisdiction_name)

    covered_jurisdictions = len(covered_jurisdictions_set)

    c1, c2, c3, c4, c5, c6 = st.columns(6)

    with c1:
        st.metric("Ingredients", total_count)

    with c2:
        st.metric("Additives", additive_count)

    with c3:
        st.metric("OCR corrections", correction_count)

    with c4:
        st.metric("Ingredients with records", regulatory_count)

    with c5:
        st.metric("Country records", jurisdiction_record_count)

    with c6:
        st.metric("Jurisdictions covered", covered_jurisdictions)

    if jurisdiction_record_count == 0:
        st.warning(
            "No jurisdiction records were returned. Make sure the regulatory scripts "
            "were run and regulatory_database.py points to the same foodreg.db."
        )

    # OCR CORRECTION WARNINGS



    # =====================================================


    for item in normalized_results:


        validation = item.get(

            "validation",

            {},

        )


        text_correction = item.get(

            "text_correction",

            {},

        )


        if validation.get(

            "status"

        ) == "OCR_CORRECTED":


            st.warning(

                f"⚠️ Additive OCR correction: "

                f"{validation.get('raw_code')} → "

                f"{validation.get('corrected_code')}"

            )


        elif text_correction.get(

            "changed"

        ):


            st.info(

                f"ℹ️ Ingredient OCR cleanup: "

                f"'{text_correction.get('original')}' → "

                f"'{text_correction.get('corrected_text')}'"

            )


    # =====================================================

    # UNKNOWN ADDITIVE CODES

    # =====================================================


    for item in normalized_results:


        validation = item.get(

            "validation",

            {},

        )


        if validation.get(

            "status"

        ) == "UNKNOWN_CODE":


            st.info(

                f"ℹ️ Additive code "

                f"'{validation.get('raw_code')}' was detected, "

                f"but it is not currently mapped in our database."

            )


    # =====================================================
    # COUNTRY CONDITION SUMMARY
    # =====================================================

    st.divider()

    st.markdown(
        '<div class="section-title">'
        "🌍 Country Condition Summary"
        "</div>",
        unsafe_allow_html=True,
    )

    st.caption(
        "A compact legal-use view. The level is shown exactly from the stored regulatory record; "
        "when no numerical limit is recorded, the table shows the applicable condition instead."
    )

    def format_level(data: dict) -> str:
        maximum_level = str(data.get("maximum_level", "") or "").strip()
        unit = str(data.get("unit", "") or "").strip()
        conditions = str(data.get("conditions", "") or "").strip()
        restriction = str(data.get("restriction", "") or "").strip()
        food_category = str(data.get("food_category", "") or "").strip()

        if maximum_level and unit:
            return f"{maximum_level} {unit}"
        if maximum_level:
            return maximum_level
        if "quantum satis" in restriction.lower() or "quantum satis" in conditions.lower():
            return "Quantum satis"
        if conditions:
            return "See stated conditions"
        if food_category:
            return "Category-specific"
        if restriction:
            return "Restricted / conditional"
        return "Not specified"

    def format_condition(data: dict, status: str) -> str:
        restriction = str(data.get("restriction", "") or "").strip()
        conditions = str(data.get("conditions", "") or "").strip()
        food_category = str(data.get("food_category", "") or "").strip()

        if status in {"BANNED", "NOT_AUTHORISED"}:
            return "Not permitted"
        if status == "RESTRICTED":
            return "Specific restrictions apply"
        if restriction:
            return restriction
        if conditions:
            return conditions
        if food_category:
            return f"Food category: {food_category}"
        if status in {"AUTHORISED", "LISTED"}:
            return "No additional restriction recorded"
        return "See official source"

    def country_sort_key(row: dict):
        name = str(row.get("Country", ""))
        preferred = {
            "India": 10,
            "United States": 20,
            "European Union": 30,
            "Great Britain": 40,
            "Northern Ireland": 41,
            "Canada": 50,
            "Australia/New Zealand": 60,
            "Singapore": 70,
            "Codex GSFA": 80,
        }
        return (preferred.get(name, 500), name.lower(), row.get("Ingredient", "").lower())

    comparison_rows = []

    for result_item in regulatory_results:
        ingredient = str(result_item.get("ingredient", "")).strip()
        record = result_item.get("record", {})

        if not record.get("found"):
            continue

        for country, data in record.get("jurisdictions", {}).items():
            status = str(data.get("status", "UNKNOWN") or "UNKNOWN").upper()
            comparison_rows.append(
                {
                    "Ingredient": ingredient.title(),
                    "Country": country,
                    "Status": get_status_display(status),
                    "Legal level": format_level(data),
                    "Condition": format_condition(data, status),
                    "Food category": str(data.get("food_category", "") or "").strip() or "—",
                }
            )

    comparison_rows.sort(key=country_sort_key)

    regulatory_difference_rows = build_regulatory_difference_rows(comparison_rows)
    review_queue = build_review_queue(ingredient_audit_rows)
    source_quality = build_regulatory_source_quality(regulatory_results)
    metadata_completeness = build_metadata_completeness(source_quality)
    review_action_checklist = build_review_action_checklist(
        summary_display_rows, allergens, label_completeness_rows, review_queue,
        nutrition_info, regulatory_difference_rows, source_quality
    )

    # =====================================================
    # SCREENING DECISION + REGULATORY DIFFERENCES
    # =====================================================

    review_queue = build_review_queue(ingredient_audit_rows)
    screening_decision = build_screening_decision(
        summary_display_rows,
        allergens,
        country_alerts if "country_alerts" in locals() else [],
        scan_clarity,
        review_queue,
    )

    st.markdown('<div class="section-title">🧭 Screening Decision</div>', unsafe_allow_html=True)
    st.caption("A transparent evidence summary for the current scan. It deliberately avoids converting the label into a health or safety score.")
    decision_text = ""
    if screening_decision["reasons"]:
        decision_text = " • ".join(screening_decision["reasons"])
    st.info(f"{screening_decision['level']} — **{screening_decision['title']}**\n\n{screening_decision['text']}\n\n{decision_text}")
    st.caption(screening_decision["disclaimer"])

    st.markdown('<div class="section-title">✅ Review Action Checklist</div>', unsafe_allow_html=True)
    st.caption("A practical follow-up list generated only from findings already visible in this analysis.")
    st.dataframe(review_action_checklist, use_container_width=True, hide_index=True)

# =====================================================
# BUNDLED FEATURES — 4–5 UPDATES TOGETHER
# =====================================================
if st.session_state.get("analysis_complete", False):
    attention_rows = build_ingredient_attention_rows(summary_display_rows, regulatory_results, review_queue)
    current_history_entry = st.session_state.get("scan_history", [{}])[0] if st.session_state.get("scan_history") else {}
    previous_similar_scan = find_previous_similar_scan(current_history_entry, st.session_state.get("scan_history", []))
    scan_delta_rows = build_scan_delta(current_history_entry, previous_similar_scan)
    product_library_rows = build_product_library_rows(st.session_state.get("scan_history", []))
    duplicate_file_matches = [x for x in st.session_state.get("scan_history", [])[1:] if current_history_entry.get("content_hash") and x.get("content_hash") == current_history_entry.get("content_hash")]
    ingredient_match_scans = [x for x in st.session_state.get("scan_history", [])[1:] if current_history_entry.get("ingredient_fingerprint") and x.get("ingredient_fingerprint") == current_history_entry.get("ingredient_fingerprint")]
    current_product_name = str(current_history_entry.get("product_name", "") or "").strip()
    product_trend_rows = build_product_trend_rows(current_product_name, st.session_state.get("scan_history", [])) if current_product_name else []
    country_profile_rows = build_country_profile_rows(comparison_rows)

    if st.session_state.get("scan_history") and analyze:
        st.session_state.scan_history[0]["allergens"] = len(allergens)
        st.session_state.scan_history[0]["attention"] = screening_decision.get("level", "Recorded scan")
        save_persistent_scan_history(st.session_state.scan_history)

    st.markdown('<div class="section-title">🎯 Ingredient Attention Ranking</div>', unsafe_allow_html=True)
    st.caption("Ranks ingredients using stored regulatory findings and manual-review signals. This is not a health or safety score.")
    if attention_rows:
        st.dataframe(attention_rows, use_container_width=True, hide_index=True)
    else:
        st.info("No ingredient attention ranking is available for this scan.")

    st.markdown('<div class="section-title">🌐 Country Regulatory Profile</div>', unsafe_allow_html=True)
    st.caption("Summarizes the current product's stored country-level findings. Missing data is not treated as approval.")
    if country_profile_rows:
        st.dataframe(country_profile_rows, use_container_width=True, hide_index=True)
    else:
        st.info("No country-level regulatory records are available for profiling.")

    st.markdown('<div class="section-title">📝 Reviewer Notes</div>', unsafe_allow_html=True)
    st.caption("Session-only notes. They are included in this scan's exports but never written to the regulatory database.")
    st.text_area("Add notes for this review", key="review_notes", height=120, placeholder="Example: Re-check the OCR match for Caramel IV before using the country comparison.")

    st.markdown('<div class="section-title">🕘 Scan History Dashboard</div>', unsafe_allow_html=True)
    st.caption("Recent scan metadata is stored locally in a tiny JSON file. Product images and raw OCR text are never stored by this history feature.")
    history_rows=build_scan_history_rows(st.session_state.get("scan_history", []))
    if history_rows:
        st.dataframe(history_rows[:10], use_container_width=True, hide_index=True)
        dash=build_history_dashboard_rows(st.session_state.get("scan_history", []))
        hm1,hm2,hm3,hm4=st.columns(4)
        hm1.metric("Stored scans", dash["scans"])
        hm2.metric("Unique files", dash["unique_files"])
        hm3.metric("Unique ingredients", dash["unique_ingredients"])
        hm4.metric("Bookmarked", dash["bookmarked"])
        latest=st.session_state.scan_history[0]
        bookmark_key=f"bookmark_scan_{latest.get('scan_id','current')}"
        bookmarked=st.checkbox("⭐ Bookmark this scan", value=bool(latest.get("bookmarked")), key=bookmark_key)
        if bookmarked != bool(latest.get("bookmarked")):
            latest["bookmarked"]=bookmarked
            save_persistent_scan_history(st.session_state.scan_history)
        st.markdown('<div class="section-title">🔄 Product-to-Product Comparison</div>', unsafe_allow_html=True)
        compare_options=[f"{i+1}. {row.get('file','Scan')} • {row.get('time','')}" for i,row in enumerate(st.session_state.scan_history)]
        if len(compare_options) >= 2:
            c1,c2=st.columns(2)
            with c1:
                left_label=st.selectbox("Baseline scan", compare_options, index=1, key="history_compare_left")
            with c2:
                right_label=st.selectbox("Comparison scan", compare_options, index=0, key="history_compare_right")
            left_entry=st.session_state.scan_history[compare_options.index(left_label)]
            right_entry=st.session_state.scan_history[compare_options.index(right_label)]
            if left_entry.get("scan_id") == right_entry.get("scan_id"):
                history_compare_rows=[]
                st.info("Choose two different scans to compare them.")
            else:
                history_compare_rows=compare_scan_history_entries(left_entry,right_entry)
                st.dataframe(history_compare_rows, use_container_width=True, hide_index=True)
        else:
            history_compare_rows=[]
            st.info("Complete at least two scans to compare products across time.")
    else:
        history_compare_rows=[]
        st.info("No completed scans are stored yet.")

    st.markdown('<div class="section-title">📚 Product Library</div>', unsafe_allow_html=True)
    st.caption("Groups persistent scan metadata by detected product name. This library stores metadata only; it does not store product images.")
    if product_library_rows:
        lib_query = st.text_input("Search saved products", key="product_library_query", placeholder="Type a product name…")
        filtered_library = [r for r in product_library_rows if not lib_query.strip() or lib_query.strip().casefold() in str(r.get("Product", "")).casefold()]
        st.dataframe(filtered_library, use_container_width=True, hide_index=True)
    else:
        st.info("Your product library will appear after the first completed scan.")

    st.markdown('<div class="section-title">🧬 Scan Integrity & Rescan Detection</div>', unsafe_allow_html=True)
    si1, si2, si3 = st.columns(3)
    si1.metric("Exact file matches", len(duplicate_file_matches))
    si2.metric("Same ingredient-list matches", len(ingredient_match_scans))
    si3.metric("Previous similar scan", "Found" if previous_similar_scan else "None")
    if duplicate_file_matches:
        st.warning("This exact uploaded file has been scanned before. The result is still a fresh OCR/regulatory analysis, but you may be reviewing a duplicate scan.")
    elif ingredient_match_scans:
        st.info("A previous scan has the same normalized ingredient fingerprint. Use the change analysis below to check whether the surrounding label information changed.")
    else:
        st.success("No matching previous scan was found from the stored metadata.")

    st.markdown('<div class="section-title">📈 Change Impact vs Previous Similar Scan</div>', unsafe_allow_html=True)
    if previous_similar_scan:
        st.caption(f"Compared with: **{previous_similar_scan.get('file','previous scan')}** from {previous_similar_scan.get('time','')}. Changes are screening differences, not automatic evidence of formulation or legal changes.")
        st.dataframe(scan_delta_rows, use_container_width=True, hide_index=True)
    else:
        st.info("No sufficiently similar previous scan is available for an automatic delta comparison.")

    st.markdown('<div class="section-title">📊 Product History Trend</div>', unsafe_allow_html=True)
    if product_trend_rows and len(product_trend_rows) >= 2:
        trend_df = product_trend_rows
        st.line_chart(trend_df, x="Date", y=["Ingredients", "Additives", "Allergens", "Regulatory records"])
        st.caption("Trend lines reflect stored scan metadata for the same detected product name; they are not quality or safety scores.")
    else:
        st.info("Complete at least two scans with the same detected product name to build a history trend.")

    st.markdown('<div class="section-title">🧹 History Management</div>', unsafe_allow_html=True)
    st.caption("This removes the local metadata history file. It does not delete your foodreg.db or uploaded label files.")
    hm_a, hm_b = st.columns([1, 2])
    with hm_a:
        confirm_clear_history = st.checkbox("I understand", key="confirm_clear_scan_history")
    with hm_b:
        if st.button("Clear persistent scan history", disabled=not confirm_clear_history, key="clear_persistent_history_btn"):
            st.session_state.scan_history = []
            try:
                if PERSISTENT_HISTORY_PATH.exists():
                    PERSISTENT_HISTORY_PATH.unlink()
            except Exception:
                pass
            st.success("Persistent scan history cleared. The current analysis remains on screen.")

    st.markdown('<div class="section-title">📊 Evidence Metadata Coverage</div>', unsafe_allow_html=True)
    mc1, mc2 = st.columns([1, 3])
    with mc1:
        st.metric("Metadata completeness", f"{metadata_completeness['score']}/100")
    with mc2:
        st.write(f"**{metadata_completeness['label']}** — {metadata_completeness['note']}")

    st.markdown('<div class="section-title">🕳️ Evidence Gap Action Plan</div>', unsafe_allow_html=True)
    evidence_gap_rows = build_evidence_gap_rows(normalized_results, regulatory_results)
    gap_high = sum(1 for r in evidence_gap_rows if r.get("Priority") == "High")
    gap_medium = sum(1 for r in evidence_gap_rows if r.get("Priority") == "Medium")
    g1, g2 = st.columns(2)
    g1.metric("High-priority gaps", gap_high)
    g2.metric("Medium-priority gaps", gap_medium)
    if evidence_gap_rows:
        st.dataframe(evidence_gap_rows, use_container_width=True, hide_index=True)
        st.caption("Gaps identify missing or weak evidence in the current dataset. They are not findings that a product violates a rule.")
    else:
        st.success("No evidence gaps were detected for the current ingredient records.")

    st.markdown('<div class="section-title">⚖️ Regulatory Differences by Country</div>', unsafe_allow_html=True)
    st.caption("Only ingredients with different stored status findings across jurisdictions are shown. Different status does not by itself mean one country permits unlimited use.")
    if regulatory_difference_rows:
        st.dataframe(regulatory_difference_rows, use_container_width=True, hide_index=True)
    else:
        st.success("No stored status differences were detected across the currently covered jurisdictions.")

    st.markdown('<div class="section-title">🔍 Ingredient Explorer & Evidence</div>', unsafe_allow_html=True)
    explorer_options = [str(row.get("Ingredient", "")).strip() for row in summary_display_rows if str(row.get("Ingredient", "")).strip()]
    explorer_options = sorted(dict.fromkeys(explorer_options), key=str.lower)
    if explorer_options:
        ex1, ex2 = st.columns([2, 1])
        with ex1:
            selected_explorer_ingredient = st.selectbox("Ingredient", explorer_options, key="evidence_ingredient")
        evidence_preview = build_regulatory_evidence_rows(regulatory_results, selected_explorer_ingredient)
        evidence_countries = [row["Jurisdiction"] for row in evidence_preview]
        with ex2:
            selected_evidence_country = st.selectbox("Jurisdiction", ["All jurisdictions"] + evidence_countries, key="evidence_country")
        country_filter = "" if selected_evidence_country == "All jurisdictions" else selected_evidence_country
        evidence_rows = build_regulatory_evidence_rows(regulatory_results, selected_explorer_ingredient, country_filter)
        if evidence_rows:
            for ev in evidence_rows:
                title = f"{ev['Jurisdiction']} — {ev['Status']}"
                with st.expander(title, expanded=(len(evidence_rows) == 1)):
                    e1, e2, e3 = st.columns(3)
                    with e1:
                        st.write(f"**Legal level:** {ev['Legal level']} {ev['Unit'] if ev['Unit'] != '—' else ''}".strip())
                        st.write(f"**Food category:** {ev['Food category']}")
                    with e2:
                        st.write(f"**Authority:** {ev['Authority']}")
                        st.write(f"**Last verified:** {ev['Last verified']}")
                    with e3:
                        st.write(f"**Source type:** {ev['Source type']}")
                        st.write(f"**Data status:** {ev['Data status']}")
                    st.write(f"**Conditions:** {ev['Conditions']}")
                    st.write(f"**Restriction:** {ev['Restriction']}")
                    if ev['Source'] != '—':
                        st.markdown(f"**Source:** {ev['Source']}")
        else:
            st.warning("No stored regulatory evidence is available for this ingredient/jurisdiction selection.")
    else:
        st.info("No identified ingredients are available for the evidence explorer.")

    st.markdown('<div class="section-title">🔗 Source Link Hub</div>', unsafe_allow_html=True)
    st.caption("Open the stored regulatory source links for the current scan. These are the source references already stored in your database; FoodReg AI does not independently certify them.")
    source_hub_options = ["All ingredients"] + sorted({str(r.get("Ingredient", "")).strip() for r in summary_display_rows if str(r.get("Ingredient", "")).strip()}, key=str.lower)
    source_hub_ingredient = st.selectbox("Ingredient", source_hub_options, key="source_hub_ingredient")
    source_filter_value = "" if source_hub_ingredient == "All ingredients" else source_hub_ingredient
    source_hub_rows = build_source_link_rows(regulatory_results, source_filter_value)
    if source_hub_rows:
        st.dataframe(source_hub_rows, use_container_width=True, hide_index=True, column_config={"Source": st.column_config.LinkColumn("Source", display_text="Open source")})
    else:
        st.info("No stored source links match this selection.")

    st.markdown('<div class="section-title">🔬 Side-by-Side Ingredient Comparison</div>', unsafe_allow_html=True)
    all_compare_ingredients = sorted({str(r.get("Ingredient", "")).strip() for r in comparison_rows if str(r.get("Ingredient", "")).strip()}, key=str.lower)
    all_compare_countries = [c for c in ["India", "United States", "European Union", "Great Britain", "Northern Ireland", "Canada", "Australia/New Zealand", "Singapore"] if c in {str(r.get("Country", "")) for r in comparison_rows}]
    if all_compare_ingredients and all_compare_countries:
        cc1, cc2 = st.columns([2, 3])
        with cc1:
            selected_compare_ingredients = st.multiselect("Choose up to 3 ingredients", all_compare_ingredients, default=all_compare_ingredients[:min(2, len(all_compare_ingredients))], max_selections=3, key="side_by_side_ingredients")
        with cc2:
            selected_compare_countries = st.multiselect("Choose countries", all_compare_countries, default=all_compare_countries[:min(4, len(all_compare_countries))], key="side_by_side_countries")
        compare_rows = build_ingredient_compare_rows(regulatory_results, selected_compare_ingredients, selected_compare_countries)
        if compare_rows:
            st.dataframe(compare_rows, use_container_width=True, hide_index=True)
            st.caption("Values show stored regulatory status and, where recorded, the maximum level. A dash means no current stored record for that country.")
        else:
            st.info("Select at least one ingredient and one country with stored regulatory records.")
    else:
        st.info("The side-by-side comparison becomes available when multiple regulatory records are present.")

    st.markdown('<div class="section-title">🚨 Where Is This Ingredient Restricted?</div>', unsafe_allow_html=True)
    st.caption("Pick one ingredient to see jurisdictions with prohibited, restricted, regulated, or condition-based findings. A country not shown here is not necessarily an approval.")
    attention_finder_options = sorted({str(r.get("Ingredient", "")).strip() for r in summary_display_rows if str(r.get("Ingredient", "")).strip()}, key=str.lower)
    if attention_finder_options:
        selected_attention_ingredient = st.selectbox("Ingredient to trace across jurisdictions", attention_finder_options, key="attention_finder_ingredient")
        attention_finder_rows = build_regulatory_attention_finder_rows(regulatory_results, selected_attention_ingredient)
        if attention_finder_rows:
            st.dataframe(attention_finder_rows, use_container_width=True, hide_index=True)
        else:
            st.success("No stored attention-level regulatory finding was found for this ingredient in the current database records.")

        st.markdown('<div class="section-title">⭐ Ingredient Watchlist</div>', unsafe_allow_html=True)
        st.caption("Choose ingredients to keep visible during this scan. The watchlist is session-only and does not change the regulatory database.")
        watch_options = sorted({str(r.get("Ingredient", "")).strip() for r in summary_display_rows if str(r.get("Ingredient", "")).strip()}, key=str.lower)
        selected_watchlist = st.multiselect("Watch these ingredients", watch_options, default=[x for x in st.session_state.ingredient_watchlist if x in watch_options], key="ingredient_watchlist_widget")
        st.session_state.ingredient_watchlist = selected_watchlist
        watchlist_rows = build_watchlist_rows(normalized_results, regulatory_results, st.session_state.ingredient_watchlist)
        if watchlist_rows:
            st.dataframe(watchlist_rows, use_container_width=True, hide_index=True)
        else:
            st.info("Select one or more ingredients to build a watchlist.")

    st.markdown('<div class="section-title">🕒 Regulatory Evidence Timeline</div>', unsafe_allow_html=True)
    st.caption("Chronological view of stored verification dates. This is a record-history view, not a guarantee that the underlying rule remains current today.")
    regulatory_timeline_rows = build_regulatory_timeline_rows(regulatory_results)
    if regulatory_timeline_rows:
        timeline_max = min(50, max(5, len(regulatory_timeline_rows)))
        timeline_default = min(15, len(regulatory_timeline_rows))
        timeline_limit = st.slider("Timeline rows", min_value=5, max_value=timeline_max, value=timeline_default, key="reg_timeline_rows")
        st.dataframe(regulatory_timeline_rows[:timeline_limit], use_container_width=True, hide_index=True)
    else:
        st.info("No verification dates are available for the current regulatory records.")

    # Existing country-level filters
    if comparison_rows:
        filter_col1, filter_col2, filter_col3 = st.columns(3)

        ingredient_options = sorted(
            {row["Ingredient"] for row in comparison_rows},
            key=str.lower,
        )
        country_options = sorted(
            {row["Country"] for row in comparison_rows},
            key=str.lower,
        )
        status_options = sorted(
            {row["Status"] for row in comparison_rows},
            key=str.lower,
        )

        with filter_col1:
            selected_ingredient = st.selectbox(
                "Filter ingredient",
                ["All ingredients"] + ingredient_options,
                key="reg_ingredient_filter",
            )

        with filter_col2:
            selected_country = st.selectbox(
                "Filter country",
                ["All countries"] + country_options,
                key="reg_country_filter",
            )

        with filter_col3:
            selected_status = st.selectbox(
                "Filter status",
                ["All statuses"] + status_options,
                key="reg_status_filter",
            )

        clear_col1, clear_col2 = st.columns([1, 5])
        with clear_col1:
            if st.button("↺ Clear filters", key="clear_reg_filters", use_container_width=True):
                for _key in ("reg_ingredient_filter", "reg_country_filter", "reg_status_filter"):
                    st.session_state.pop(_key, None)
                st.rerun()

        filtered_rows = comparison_rows

        if selected_ingredient != "All ingredients":
            filtered_rows = [
                row for row in filtered_rows
                if row["Ingredient"] == selected_ingredient
            ]

        if selected_country != "All countries":
            filtered_rows = [
                row for row in filtered_rows
                if row["Country"] == selected_country
            ]

        if selected_status != "All statuses":
            filtered_rows = [
                row for row in filtered_rows
                if row["Status"] == selected_status
            ]

        st.caption(
            f"Showing {len(filtered_rows)} of {len(comparison_rows)} country-level records."
        )

        if filtered_rows:
            st.dataframe(
                filtered_rows,
                use_container_width=True,
                hide_index=True,
                column_config={
                    "Ingredient": st.column_config.TextColumn("Ingredient", width="medium"),
                    "Country": st.column_config.TextColumn("Country", width="medium"),
                    "Status": st.column_config.TextColumn("Status", width="small"),
                    "Legal level": st.column_config.TextColumn("Legal level", width="medium"),
                    "Condition": st.column_config.TextColumn("Condition", width="large"),
                    "Food category": st.column_config.TextColumn("Food category", width="medium"),
                },
            )
        else:
            st.info("No country-level records match the selected filters.")
    else:
        st.info("No verified country-level regulatory records are available for this label.")

    # =====================================================
    # COUNTRY COMPARISON MATRIX
    # =====================================================

    if comparison_rows:
        st.markdown('<div class="section-title">🗺️ Country Comparison Matrix</div>', unsafe_allow_html=True)
        st.caption("Compare the same ingredient across selected jurisdictions. A dash means no record is currently stored for that ingredient/country pair.")
        available_countries=sorted({row["Country"] for row in comparison_rows}, key=str.lower)
        preferred=[c for c in ["India","United States","European Union","Great Britain","Northern Ireland","Singapore"] if c in available_countries]
        defaults=preferred[:4] or available_countries[:3]
        matrix_countries=st.multiselect("Countries to compare", available_countries, default=defaults, key="matrix_countries")
        if matrix_countries:
            st.dataframe(build_country_matrix(comparison_rows, matrix_countries), use_container_width=True, hide_index=True)
        else:
            st.info("Choose at least one country to build the comparison matrix.")


    # =====================================================
    # V15 FEATURES
    # =====================================================

    relationship_rows = build_ingredient_relationship_rows(normalized_results, allergens, regulatory_results)
    regulatory_watch_rows = build_regulatory_watch_rows(regulatory_results, st.session_state.get("scan_history", []))

    st.markdown('<div id="ingredient-relationship"></div>', unsafe_allow_html=True)
    st.markdown('<div class="section-title">🧩 Ingredient Relationship Map</div>', unsafe_allow_html=True)
    st.caption("Links each identified ingredient to its type, allergen signal and stored regulatory coverage. This is an evidence map, not a safety score.")
    if relationship_rows:
        st.dataframe(relationship_rows,use_container_width=True,hide_index=True)
    else:
        st.info("No ingredient relationships could be assembled from this scan.")

    st.markdown('<div id="regulatory-watch"></div>', unsafe_allow_html=True)
    st.markdown('<div class="section-title">👀 Regulatory Change Watch</div>', unsafe_allow_html=True)
    st.caption("Compares this scan with the most recent comparable local scan. A difference means the stored database snapshot changed; it does not prove that legislation changed.")
    if regulatory_watch_rows:
        st.dataframe(regulatory_watch_rows,use_container_width=True,hide_index=True)
    elif st.session_state.get("scan_history"):
        st.info("No stored regulatory snapshot change was found against the available comparable scans.")
    else:
        st.info("Run another comparable scan to activate this watch view.")

    st.markdown('<div class="section-title">🧭 Quick Navigation</div><div style="display:flex;gap:10px;flex-wrap:wrap;"><a href="#ingredient-relationship">Ingredients</a><a href="#regulatory-watch">Regulatory watch</a><a href="#final-summary">Final summary</a><a href="#downloads">Downloads</a></div>',unsafe_allow_html=True)

    # =====================================================
    # PRODUCT INTELLIGENCE DASHBOARD
    # =====================================================

    dashboard_stats = build_dashboard_stats(normalized_results, regulatory_results, allergens, nutrition_info)
    evidence_score_rows = build_ingredient_evidence_scores(regulatory_results)

    st.markdown('<div class="section-title">📊 Product Intelligence Dashboard</div>', unsafe_allow_html=True)
    st.caption("A visual summary of what FoodReg AI extracted and what is currently supported by stored regulatory records. These metrics are screening indicators, not safety scores.")
    d1, d2, d3, d4, d5, d6 = st.columns(6)
    with d1: st.metric("Ingredients", dashboard_stats["ingredients"])
    with d2: st.metric("Additives", dashboard_stats["additives"])
    with d3: st.metric("Allergen signals", dashboard_stats["allergen_signals"])
    with d4: st.metric("Regulatory records", dashboard_stats["regulatory_records"])
    with d5: st.metric("Flagged records", dashboard_stats["flagged_records"])
    with d6: st.metric("Jurisdictions", dashboard_stats["jurisdictions"])

    dash_col1, dash_col2 = st.columns(2)
    with dash_col1:
        st.markdown("**Ingredient composition**")
        st.dataframe([
            {"Category": "Food/additive ingredients", "Count": dashboard_stats["ordinary_ingredients"]},
            {"Category": "Additives with INS", "Count": dashboard_stats["additives"]},
            {"Category": "Unclassified", "Count": dashboard_stats["unclassified"]},
        ], use_container_width=True, hide_index=True)
    with dash_col2:
        st.markdown("**Regulatory attention distribution**")
        attention_distribution = [
            {"Measure": "Flagged records", "Count": dashboard_stats["flagged_records"]},
            {"Measure": "Other stored records", "Count": max(0, dashboard_stats["regulatory_records"] - dashboard_stats["flagged_records"])},
        ]
        st.dataframe(attention_distribution, use_container_width=True, hide_index=True)

    st.markdown('<div class="section-title">🗺️ Regulatory Status Heatmap</div>', unsafe_allow_html=True)
    st.caption("A compact ingredient × jurisdiction view. The symbols reflect the stored database status; a dash means the database has no current record for that pair.")
    heatmap_countries = []
    for country in ["India", "United States", "European Union", "Great Britain", "Northern Ireland", "Canada", "Australia/New Zealand", "Singapore"]:
        if country in {str(r.get("Country", "")) for r in comparison_rows} and country not in heatmap_countries:
            heatmap_countries.append(country)
    if not heatmap_countries:
        heatmap_countries = sorted({str(r.get("Country", "")).strip() for r in comparison_rows if str(r.get("Country", "")).strip()})[:6]
    if heatmap_countries:
        heatmap_rows = build_regulatory_heatmap_rows(regulatory_results, heatmap_countries)
        st.dataframe(heatmap_rows, use_container_width=True, hide_index=True)
    else:
        st.info("No country-level regulatory records are available for a heatmap.")

    st.markdown('<div class="section-title">🔬 Evidence Coverage by Ingredient</div>', unsafe_allow_html=True)
    st.caption("Metadata coverage checks whether stored records have a source, authority and verification date. It does not validate the underlying law.")
    if evidence_score_rows:
        st.dataframe(evidence_score_rows, use_container_width=True, hide_index=True)
    else:
        st.info("No ingredient-level regulatory evidence rows are available.")

    audit_snapshot = build_audit_snapshot(summary_display_rows, dashboard_stats, screening_decision, review_action_checklist)
    with st.expander("🖨️ Print / Copy Audit Snapshot", expanded=False):
        st.text_area("Audit snapshot", value=audit_snapshot, height=360, key="audit_snapshot_text")
        st.download_button("⬇️ Download Audit Snapshot", data=audit_snapshot, file_name="foodreg_ai_audit_snapshot.txt", mime="text/plain", use_container_width=True, key="download_audit_snapshot")


    # =====================================================
    # BATCH 15–19 FEATURES
    # =====================================================

    st.markdown('<div class="section-title">🕒 Regulatory Record Freshness</div>', unsafe_allow_html=True)
    st.caption("Aging is a data-maintenance indicator based on the stored verification date. It is not a legal expiry date and does not mean the underlying rule is invalid.")
    freshness_rows = build_regulatory_freshness_rows(regulatory_results)
    if freshness_rows:
        recent_count=sum(1 for r in freshness_rows if r.get("Freshness") == "🟢 Recent")
        aging_count=sum(1 for r in freshness_rows if r.get("Freshness") == "🟡 Aging")
        stale_count=sum(1 for r in freshness_rows if r.get("Freshness") == "🟠 Stale")
        unknown_count=sum(1 for r in freshness_rows if r.get("Freshness") == "⚪ Unknown")
        fr1,fr2,fr3,fr4=st.columns(4)
        with fr1: st.metric("Recent", recent_count)
        with fr2: st.metric("Aging", aging_count)
        with fr3: st.metric("Stale", stale_count)
        with fr4: st.metric("Unknown date", unknown_count)
        st.dataframe(freshness_rows, use_container_width=True, hide_index=True)
    else:
        st.info("No jurisdiction records with freshness metadata are available.")

    st.markdown('<div class="section-title">🕳️ Regulatory Coverage Gaps</div>', unsafe_allow_html=True)
    st.caption("Shows missing records only among jurisdictions currently represented elsewhere in this scan. Missing data is not interpreted as approval or prohibition.")
    coverage_gap_rows = build_coverage_gap_rows(normalized_results, comparison_rows)
    if coverage_gap_rows:
        gap_count=sum(1 for r in coverage_gap_rows if r.get("Jurisdictions missing", 0) > 0)
        st.metric("Ingredients with at least one coverage gap", gap_count)
        st.dataframe(coverage_gap_rows, use_container_width=True, hide_index=True)
    else:
        st.info("No comparison-jurisdiction coverage gaps can be calculated for this scan.")

    st.markdown('<div class="section-title">🔎 Search the OCR Label Text</div>', unsafe_allow_html=True)
    st.caption("Searches the OCR lines captured from this image. It does not change the ingredient parser or regulatory results.")
    label_query=st.text_input("Search OCR text", key="ocr_text_search", placeholder="Try: sugar, INS 330, calories, contains, peanut...")
    if label_query.strip():
        label_matches=search_label_lines(detected_text, label_query)
        if label_matches:
            st.dataframe(label_matches, use_container_width=True, hide_index=True)
        else:
            st.info(f'No OCR line matched “{label_query.strip()}”.')

    st.markdown('<div class="section-title">🔄 Compare With a Previous Session Scan</div>', unsafe_allow_html=True)
    st.caption("This comparison uses only ingredient names stored in the current browser session. It does not retain product images.")
    previous_history=[row for row in st.session_state.get("scan_history", [])[1:] if row.get("ingredient_names")]
    if previous_history:
        previous_labels=[f"{row.get('time','—')} — {row.get('file','Previous scan')}" for row in previous_history]
        previous_choice=st.selectbox("Previous scan", ["No comparison"] + previous_labels, key="previous_scan_compare")
        if previous_choice != "No comparison":
            selected_prev=previous_history[previous_labels.index(previous_choice)]
            current_names=[str(item.get("canonical", "")).strip() for item in normalized_results if str(item.get("canonical", "")).strip()]
            diff=build_session_comparison(current_names, selected_prev.get("ingredient_names", []))
            if not diff["added"] and not diff["removed"]:
                st.success("No ingredient-name changes were detected between these two session scans.")
            else:
                dc1,dc2=st.columns(2)
                with dc1:
                    st.markdown("**➕ Present in current scan, absent in previous:**")
                    st.write(", ".join(diff["added"]) if diff["added"] else "None")
                with dc2:
                    st.markdown("**➖ Present in previous scan, absent in current:**")
                    st.write(", ".join(diff["removed"]) if diff["removed"] else "None")
    else:
        st.info("Run another label in this same session to enable an ingredient-list comparison.")


    # =====================================================
    # BATCH 20–24 FEATURES
    # =====================================================

    st.markdown('<div class="section-title">🥗 Nutrition Label Completeness</div>', unsafe_allow_html=True)
    st.caption("Shows which common nutrition fields were actually captured from the current label image. Not detected means OCR did not capture a usable value; it does not prove the physical label lacks the field.")
    nutrition_review_rows = build_nutrition_review_rows(nutrition_info)
    nr1, nr2, nr3 = st.columns(3)
    with nr1:
        st.metric("Nutrition fields detected", int(nutrition_info.get("value_count", 0) or 0))
    with nr2:
        st.metric("Serving size", str(nutrition_info.get("serving_size") or "Not detected"))
    with nr3:
        st.metric("Label basis", str(nutrition_info.get("declared_basis") or "Not detected"))
    st.dataframe(nutrition_review_rows, use_container_width=True, hide_index=True)

    st.markdown('<div class="section-title">📈 Ingredient Order Visual</div>', unsafe_allow_html=True)
    st.caption("This visual uses ingredient order only. It does not estimate ingredient percentages or quantities unless those are explicitly stated on the label.")
    order_chart = {}
    for row in ingredient_order_rows:
        try:
            score = int(str(row.get("Prominence score", "0")).split("/")[0])
        except Exception:
            score = 0
        order_chart[str(row.get("Ingredient", ""))] = score
    if order_chart:
        st.bar_chart({"Prominence score": order_chart}, horizontal=True)
        st.dataframe(ingredient_order_rows, use_container_width=True, hide_index=True)
    else:
        st.info("No ingredient-order data is available for this scan.")

    st.markdown('<div class="section-title">🔍 Manual Regulatory Ingredient Lookup</div>', unsafe_allow_html=True)
    st.caption("Check an ingredient or INS/E code without changing the current scan. This is a separate lookup against the same local regulatory database.")
    ml1, ml2 = st.columns([4, 1])
    with ml1:
        manual_lookup_query = st.text_input("Ingredient or INS/E code", key="manual_reg_lookup", placeholder="Example: INS 330, citric acid, caramel IV")
    with ml2:
        manual_lookup_run = st.button("Check", key="manual_reg_lookup_btn", use_container_width=True)
    if manual_lookup_run and manual_lookup_query.strip():
        manual_normalized = normalize_results([manual_lookup_query.strip()])
        if manual_normalized:
            manual_item = manual_normalized[0]
            manual_canonical = str(manual_item.get("canonical", "")).strip()
            manual_record = check_ingredient(manual_canonical) if manual_canonical else {"found": False, "jurisdictions": {}}
            st.markdown(
                f"**Matched:** `{escape(manual_canonical or 'No canonical match')}`  "
                f"**INS:** `{escape(str(manual_item.get('ins') or '—'))}`  "
                f"**Method:** `{escape(str(manual_item.get('method') or '—'))}`  "
                f"**Match confidence:** `{float(manual_item.get('confidence', 0.0) or 0.0):.2f}`"
            )
            if manual_record.get("found"):
                st.dataframe(build_manual_lookup_rows(manual_record), use_container_width=True, hide_index=True)
            else:
                st.warning("No stored regulatory record was found for this normalized ingredient. Missing data is not approval or prohibition.")
        else:
            st.warning("The lookup text could not be normalized to an ingredient.")

    st.markdown('<div class="section-title">🌍 Country Focus View</div>', unsafe_allow_html=True)
    st.caption("Pick one jurisdiction to see every ingredient in the current scan with its stored status, level and conditions.")
    focus_countries = sorted({str(r.get("Country", "")).strip() for r in comparison_rows if str(r.get("Country", "")).strip()}, key=str.lower)
    if focus_countries:
        selected_focus_country = st.selectbox("Country focus", focus_countries, key="country_focus_view")
        focus_rows = build_country_focus_rows(comparison_rows, selected_focus_country)
        if focus_rows:
            st.dataframe(focus_rows, use_container_width=True, hide_index=True)
        else:
            st.info("No stored records are available for this country in the current scan.")
    else:
        st.info("No country-level records are available for a country focus view.")

    st.markdown('<div class="section-title">📋 Copyable Scan Summary</div>', unsafe_allow_html=True)
    st.caption("Use this plain-text summary in a report, email or review note. It is generated from the current analysis and contains no hidden conclusions beyond the visible results.")
    copyable_summary = build_copyable_scan_summary(
        screening_decision,
        summary_display_rows,
        allergens,
        nutrition_info,
        scan_clarity,
        review_action_checklist,
    )
    st.text_area("Scan summary", value=copyable_summary, height=190, key="copyable_scan_summary")

    # =====================================================
    # FINAL PRODUCT REVIEW — NEW FEATURES
    # =====================================================
    claims_rows=detect_label_claims(detected_text)
    claim_verification_rows=build_claim_verification_rows(claims_rows, normalized_results, nutrition_info)
    composition_rows=build_composition_breakdown(normalized_results,allergens)
    status_distribution_rows=build_regulatory_status_distribution(regulatory_results)
    coverage_action_rows=build_coverage_action_rows(normalized_results,comparison_rows)
    source_intelligence_rows=build_source_intelligence_rows(regulatory_results)
    source_intelligence_summary=build_source_intelligence_summary(source_intelligence_rows)
    regulatory_matrix_rows=build_regulatory_matrix_rows(normalized_results, regulatory_results)
    regulatory_batch_summary=build_regulatory_batch_summary(regulatory_results, source_intelligence_rows)
    claim_evidence_rows=build_claim_evidence_rows(claim_verification_rows, nutrition_info, normalized_results)
    regulatory_divergence_rows=build_regulatory_divergence_rows(regulatory_results)
    ingredient_evidence_rows=build_ingredient_evidence_rows(normalized_results, regulatory_results, claims_rows)
    regulatory_review_packet=build_regulatory_review_packet(screening_decision, claim_verification_rows, regulatory_divergence_rows, source_intelligence_summary, review_action_checklist)
    product_fact_sheet=build_product_fact_sheet(screening_decision,normalized_results,allergens,nutrition_info,composition_rows,claims_rows,coverage_action_rows)
    package_lines = [f"{str(k).replace('_',' ').title()}: {str(v)}" for k,v in (product_metadata or {}).items() if k != "detected_fields" and v]
    if package_lines:
        product_fact_sheet += "\n\nPACKAGE DETAILS\n" + "\n".join(package_lines)

    label_quality = build_label_quality_score(scan_clarity, label_completeness_rows, nutrition_info, normalized_results, product_metadata, source_quality)
    freshness_rows = build_regulatory_freshness_rows(regulatory_results)
    review_center_rows = build_review_center_rows(review_queue, allergens, claims_rows, coverage_action_rows, freshness_rows)
    nutrition_consistency_rows = build_nutrition_consistency_rows(nutrition_info)

    st.markdown('<div class="section-title">🏷️ Label Claim Audit</div>',unsafe_allow_html=True)
    st.caption('Claims are detected from OCR wording only. FoodReg AI does not verify that a marketing, nutrition, or certification claim is legally valid or factually true.')
    if claims_rows: st.dataframe(claims_rows,use_container_width=True,hide_index=True)
    else: st.success('No predefined label claims were detected in the OCR text.')

    st.markdown('<div class="section-title">🧩 Product Composition Breakdown</div>',unsafe_allow_html=True)
    st.caption('Structural breakdown of identified ingredients. Allergen-linked ingredients are an additional review signal, not a separate ingredient category.')
    st.dataframe(composition_rows,use_container_width=True,hide_index=True)

    st.markdown('<div class="section-title">📊 Regulatory Status Distribution</div>',unsafe_allow_html=True)
    st.caption('Counts across stored jurisdiction records for this scan. These are not risk, prevalence, or approval percentages.')
    if status_distribution_rows: st.dataframe(status_distribution_rows,use_container_width=True,hide_index=True)
    else: st.info('No stored jurisdiction records were available for a status distribution.')

    st.markdown('<div class="section-title">🕳️ Coverage Action Panel</div>',unsafe_allow_html=True)
    st.caption('Shows where the current comparison set has no stored jurisdiction record. Missing data means more verification is needed; it does not mean the ingredient is banned or approved.')
    if coverage_action_rows: st.dataframe(coverage_action_rows,use_container_width=True,hide_index=True)
    else: st.info('Coverage gaps cannot be calculated because no comparison-jurisdiction records are available.')

    st.markdown('<div class="section-title">🗂️ Product Fact Sheet</div>',unsafe_allow_html=True)
    st.caption('Compact human-readable summary generated from the current scan and included in the export bundle.')
    st.text_area('Fact sheet',value=product_fact_sheet,height=260,key='product_fact_sheet',disabled=True)

    # =====================================================
    # REGULATORY INTELLIGENCE UPGRADE
    # =====================================================

    st.markdown('<div class="section-title">🧠 Claim Verification Intelligence</div>', unsafe_allow_html=True)
    st.caption("Screens detected marketing/nutrition claims against the ingredients and captured nutrition data. This is a consistency check, not a legal claim approval.")
    if claim_verification_rows:
        st.dataframe(claim_verification_rows, use_container_width=True, hide_index=True)
    else:
        st.info("No predefined label claims were detected for evidence screening.")

    st.markdown('<div class="section-title">🔬 Ingredient Evidence Cards</div>', unsafe_allow_html=True)
    st.caption("Each card connects the OCR match, normalization evidence and stored regulatory coverage for one ingredient.")
    evidence_names=[str(r.get("Ingredient","")).strip() for r in ingredient_evidence_rows if str(r.get("Ingredient","")).strip()]
    if evidence_names:
        selected_evidence_ingredient=st.selectbox("Ingredient evidence", evidence_names, key="ingredient_evidence_card")
        evidence_row=next((r for r in ingredient_evidence_rows if r.get("Ingredient")==selected_evidence_ingredient), None)
        if evidence_row:
            ec1,ec2,ec3,ec4=st.columns(4)
            with ec1: st.metric("Match confidence", evidence_row.get("Match confidence","—"))
            with ec2: st.metric("Regulatory records", evidence_row.get("Regulatory records",0))
            with ec3: st.metric("Source-linked records", evidence_row.get("Records with sources",0))
            with ec4: st.metric("Tier 1 records", evidence_row.get("Tier 1 source records",0))
            st.dataframe([evidence_row], use_container_width=True, hide_index=True)
            insight=get_ingredient_insight(selected_evidence_ingredient)
            st.markdown(f"**What it does:** {escape(str(insight.get('role','')))}")
            st.markdown(f"**Things to know:** {escape(str(insight.get('notes','')))}")
    else:
        st.info("No ingredient evidence cards are available.")

    st.markdown('<div class="section-title">🏛️ Regulatory Source Intelligence</div>', unsafe_allow_html=True)
    st.caption("Source tiers are metadata-based review categories. They do not guarantee that a regulatory record is legally correct or current.")
    si1,si2,si3=st.columns(3)
    with si1: st.metric("Records reviewed", source_intelligence_summary.get("total_records",0))
    with si2: st.metric("With verification date", f"{source_intelligence_summary.get('verified_pct',0)}%")
    with si3: st.metric("Tier 1 source records", sum(v for k,v in source_intelligence_summary.get("tier_counts",{}).items() if str(k).startswith("Tier 1")))
    if source_intelligence_rows:
        st.dataframe(source_intelligence_rows, use_container_width=True, hide_index=True)
    else:
        st.info("No regulatory source metadata is available for this scan.")

    st.markdown('<div class="section-title">⚖️ Cross-Jurisdiction Divergence</div>', unsafe_allow_html=True)
    st.caption("Highlights ingredients whose stored regulatory status differs across countries. Divergence is expected in some regulatory systems and should trigger jurisdiction-specific review.")
    if regulatory_divergence_rows:
        st.dataframe(regulatory_divergence_rows, use_container_width=True, hide_index=True)
    else:
        st.success("No stored status divergence was found across the jurisdictions currently represented for this scan.")

    st.markdown('<div class="section-title">📑 Regulatory Review Packet</div>', unsafe_allow_html=True)
    st.caption("A compact evidence-oriented review packet generated from the current scan. It is a review aid, not a legal certificate.")
    st.text_area("Review packet", value=regulatory_review_packet, height=320, key="regulatory_review_packet", disabled=True)

    st.markdown('<div class="section-title">🧾 Label Data Quality</div>', unsafe_allow_html=True)
    st.caption("Measures completeness and internal usability of captured label data. It is not a health, safety, legal, or product-quality score.")
    q1, q2 = st.columns([1, 2])
    with q1:
        st.metric("Data capture score", f"{label_quality['score']}/100")
        st.info(label_quality["level"])
    with q2:
        st.dataframe(label_quality["checks"], use_container_width=True, hide_index=True)

    regulatory_alert_feed = build_regulatory_alert_feed(regulatory_results)
    st.markdown('<div class="section-title">🚨 Priority Regulatory Alert Feed</div>', unsafe_allow_html=True)
    st.caption("A prioritized feed of stored jurisdiction findings that deserve attention. It is generated from the current database records and does not add new legal conclusions.")
    alert_priority = st.multiselect("Alert priority", ["High", "Medium"], default=["High", "Medium"], key="alert_feed_priority")
    filtered_alert_feed = [r for r in regulatory_alert_feed if r.get("Priority") in alert_priority]
    if filtered_alert_feed:
        st.dataframe(filtered_alert_feed, use_container_width=True, hide_index=True)
    else:
        st.success("No stored regulatory alerts match the selected priorities.")

    executive_brief = build_executive_brief(screening_decision, dashboard_stats, label_quality, source_quality, regulatory_alert_feed, regulatory_consistency_rows)
    st.markdown('<div class="section-title">⚡ 60-Second Executive Brief</div>', unsafe_allow_html=True)
    st.caption("A report-ready summary of the current evidence. It is a decision-support aid, not a legal or medical conclusion.")
    st.text_area("Executive brief", value=executive_brief, height=300, key="executive_brief_text")
    st.download_button("⬇️ Download Executive Brief", data=executive_brief, file_name="foodreg_ai_executive_brief.txt", mime="text/plain", use_container_width=True, key="download_executive_brief")

    st.markdown('<div class="section-title">🛠️ Smart Review Center</div>', unsafe_allow_html=True)
    st.caption("One queue combining identification, allergen, claim, coverage, and freshness items already requiring follow-up.")
    area_options = sorted({str(r.get("Area", "")) for r in review_center_rows if str(r.get("Area", "")).strip()})
    c1, c2 = st.columns(2)
    with c1:
        review_priority = st.multiselect("Priority", ["High", "Medium", "Low"], default=["High", "Medium", "Low"], key="review_center_priority")
    with c2:
        review_area = st.multiselect("Review area", area_options, default=area_options, key="review_center_area")
    filtered_review_center = [r for r in review_center_rows if r.get("Priority") in review_priority and r.get("Area") in review_area]
    if filtered_review_center:
        st.dataframe(filtered_review_center, use_container_width=True, hide_index=True)
    else:
        st.success("No review items match the selected filters.")

    st.markdown('<div class="section-title">🥗 Nutrition Consistency Check</div>', unsafe_allow_html=True)
    st.caption("Checks captured nutrition fields for obvious internal OCR/unit inconsistencies. It does not judge whether a nutrient level is healthy or unhealthy.")
    st.dataframe(nutrition_consistency_rows, use_container_width=True, hide_index=True)

    st.markdown('<div class="section-title">🏛️ Regulatory Source Explorer</div>', unsafe_allow_html=True)
    source_tiers = sorted({str(r.get("Source tier", "")) for r in source_intelligence_rows if str(r.get("Source tier", "")).strip()})
    source_countries = sorted({str(r.get("Country / jurisdiction", "")) for r in source_intelligence_rows if str(r.get("Country / jurisdiction", "")).strip()}, key=str.lower)
    s1, s2 = st.columns(2)
    with s1:
        selected_source_tiers = st.multiselect("Source tier", source_tiers, default=source_tiers, key="source_explorer_tiers")
    with s2:
        default_source_countries = source_countries[:8] if len(source_countries) > 8 else source_countries
        selected_source_countries = st.multiselect("Jurisdiction", source_countries, default=default_source_countries, key="source_explorer_countries")
    filtered_sources = [r for r in source_intelligence_rows if r.get("Source tier") in selected_source_tiers and r.get("Country / jurisdiction") in selected_source_countries]
    if filtered_sources:
        st.dataframe(filtered_sources, use_container_width=True, hide_index=True)
    else:
        st.info("No source records match the selected filters.")


    # =====================================================
    # V13 REVIEW INTELLIGENCE
    # =====================================================

    claim_conflict_rows = build_claim_conflict_rows(claim_evidence_rows, normalized_results, nutrition_info)
    regulatory_level_rows = build_regulatory_level_explorer_rows(regulatory_results)
    ingredient_screening_matrix = build_ingredient_screening_matrix(
        normalized_results,
        regulatory_results,
        allergens,
        evidence_gap_rows,
        reviewer_status_rows,
    )
    reviewer_handoff_text = build_reviewer_handoff_text(
        ingredient_screening_matrix,
        claim_conflict_rows,
        nutrition_consistency_rows,
        review_center_rows,
    )

    st.markdown('<div class="section-title">🏷️ Claim Conflict Detector</div>', unsafe_allow_html=True)
    st.caption("Flags potential inconsistencies between detected marketing claims and captured label evidence. This is screening only and does not certify legal claim compliance.")
    if claim_conflict_rows:
        claim_issue_count = sum(1 for r in claim_conflict_rows if "Potential inconsistency" in str(r.get("Screening result", "")))
        if claim_issue_count:
            st.warning(f"{claim_issue_count} detected claim(s) need human review based on the current label evidence.")
        else:
            st.success("No direct claim/evidence conflict was triggered by the configured screening rules.")
        st.dataframe(claim_conflict_rows, use_container_width=True, hide_index=True)
    else:
        st.info("No recognizable label claims were detected in the OCR text.")

    st.markdown('<div class="section-title">📐 Regulatory Level Explorer</div>', unsafe_allow_html=True)
    st.caption("Filter the regulatory records already stored in the database to focus on maximum levels, food categories and conditions. Missing records are not approval.")
    if regulatory_level_rows:
        level_c1, level_c2, level_c3 = st.columns(3)
        with level_c1:
            level_ingredients = ["All ingredients"] + sorted({r["Ingredient"] for r in regulatory_level_rows}, key=str.casefold)
            level_ingredient = st.selectbox("Ingredient", level_ingredients, key="v13_level_ingredient")
        with level_c2:
            level_countries = ["All jurisdictions"] + sorted({r["Jurisdiction"] for r in regulatory_level_rows}, key=str.casefold)
            level_country = st.selectbox("Jurisdiction", level_countries, key="v13_level_country")
        with level_c3:
            level_statuses = ["All statuses"] + sorted({r["Status"] for r in regulatory_level_rows}, key=str.casefold)
            level_status = st.selectbox("Status", level_statuses, key="v13_level_status")
        level_filtered = regulatory_level_rows
        if level_ingredient != "All ingredients":
            level_filtered = [r for r in level_filtered if r["Ingredient"] == level_ingredient]
        if level_country != "All jurisdictions":
            level_filtered = [r for r in level_filtered if r["Jurisdiction"] == level_country]
        if level_status != "All statuses":
            level_filtered = [r for r in level_filtered if r["Status"] == level_status]
        st.dataframe(level_filtered, use_container_width=True, hide_index=True)
    else:
        st.info("No stored regulatory records are available for the level explorer.")

    st.markdown('<div class="section-title">🧪 Ingredient Screening Matrix</div>', unsafe_allow_html=True)
    st.caption("A combined audit table for ingredient match quality, allergen signals, stored regulatory findings, evidence gaps and reviewer workflow state.")
    if ingredient_screening_matrix:
        matrix_filter = st.multiselect(
            "Screening signal",
            ["All", "High", "Medium", "Standard screening"],
            default=["All"],
            key="v13_matrix_filter",
        )
        filtered_matrix = ingredient_screening_matrix
        if "All" not in matrix_filter:
            filtered_matrix = []
            for row in ingredient_screening_matrix:
                signal = str(row.get("Screening signal", ""))
                if "High" in matrix_filter and signal.startswith("High"):
                    filtered_matrix.append(row)
                elif "Medium" in matrix_filter and signal.startswith("Medium"):
                    filtered_matrix.append(row)
                elif "Standard screening" in matrix_filter and signal == "Standard screening":
                    filtered_matrix.append(row)
        st.dataframe(filtered_matrix, use_container_width=True, hide_index=True)
    else:
        st.info("No ingredient screening rows are available.")

    st.markdown('<div class="section-title">📝 Reviewer Handoff Pack</div>', unsafe_allow_html=True)
    st.caption("A compact handoff checklist for a human reviewer. It is generated from the current scan and does not create new regulatory conclusions.")
    st.text_area("Reviewer handoff", value=reviewer_handoff_text, height=330, key="v13_reviewer_handoff")
    st.download_button("⬇️ Download Reviewer Handoff", data=reviewer_handoff_text, file_name="foodreg_ai_reviewer_handoff.txt", mime="text/plain", use_container_width=True, key="download_v13_reviewer_handoff")

    # =====================================================
    # V9 REVIEW & EVIDENCE TOOLS
    # =====================================================

    compliance_review_rows = build_compliance_review_rows(summary_rows, normalized_results, regulatory_results, allergens, reviewer_status_rows)
    label_evidence_rows = build_label_evidence_rows(detected_text, ingredient_section, nutrition_info, product_metadata, scan_clarity)
    clean_label_text = build_clean_label_text(detected_text, ingredient_section, normalized_results, nutrition_info, product_metadata)

    st.markdown('<div class="section-title">🔬 Ingredient Deep Dive</div>', unsafe_allow_html=True)
    st.caption("Inspect one ingredient from OCR through normalization and stored regulatory coverage. No quantity is inferred unless it appears in the label data.")
    deep_dive_options = [str(r.get("Ingredient", "")).strip() for r in compliance_review_rows if str(r.get("Ingredient", "")).strip()]
    if deep_dive_options:
        selected_deep_dive = st.selectbox("Ingredient", deep_dive_options, key="v9_deep_dive_ingredient")
        item = next((x for x in normalized_results if str(x.get("canonical", "")).strip().title() == selected_deep_dive), None)
        rec_item = next((x for x in regulatory_results if str(x.get("ingredient", "")).strip().title() == selected_deep_dive), None)
        if item:
            dd1, dd2, dd3, dd4 = st.columns(4)
            with dd1: st.metric("Match confidence", f"{float(item.get('confidence', 0.0) or 0.0):.2f}")
            with dd2: st.metric("INS", str(item.get("ins", "") or "—"))
            with dd3: st.metric("Normalization", str(item.get("method", "") or "—"))
            with dd4: st.metric("OCR corrected", "Yes" if item.get("text_correction", {}).get("changed") else "No")
            st.dataframe([{
                "OCR text": str(item.get("original", "") or "—"),
                "Corrected text": str(item.get("text_correction", {}).get("corrected", item.get("original", "")) or "—"),
                "Canonical": str(item.get("canonical", "") or "—"),
                "Category": classify_ingredient(str(item.get("canonical", "")), item.get("ins")).get("category", "Other"),
                "INS": str(item.get("ins", "") or "—"),
                "CAS": str(item.get("cas_number", "") or item.get("cas", "") or "—"),
            }], use_container_width=True, hide_index=True)
            if rec_item:
                j_count = len((rec_item.get("record", {}) or {}).get("jurisdictions", {}) or {})
                st.info(f"Stored regulatory jurisdictions for this ingredient: {j_count}. Review the country-specific evidence below before drawing a legal conclusion.")
        else:
            st.info("Ingredient details could not be mapped from the current normalized result.")
    else:
        st.info("No identified ingredients are available for deep-dive review.")

    st.markdown('<div class="section-title">🧾 Compliance Review Table</div>', unsafe_allow_html=True)
    st.caption("One-row-per-ingredient screening summary. Missing records are shown as missing evidence, not as approvals.")
    if compliance_review_rows:
        compliance_filter = st.multiselect("Show review signals", ["All", "Regulatory attention", "Allergen signal", "Needs review"], default=["All"], key="v9_compliance_filter")
        filtered_compliance = compliance_review_rows
        if "All" not in compliance_filter:
            filtered_compliance = []
            for row in compliance_review_rows:
                if "Regulatory attention" in compliance_filter and (row["Prohibited"] or row["Restricted"] or row["Conditions"]):
                    filtered_compliance.append(row); continue
                if "Allergen signal" in compliance_filter and row["Allergen signal"] == "Yes":
                    filtered_compliance.append(row); continue
                if "Needs review" in compliance_filter and (row["Reviewer status"] != "Resolved" or not row["Sources"]):
                    filtered_compliance.append(row); continue
        st.dataframe(filtered_compliance, use_container_width=True, hide_index=True)
    else:
        st.info("No ingredient review rows are available.")

    st.markdown('<div class="section-title">🧠 Label Evidence Inspector</div>', unsafe_allow_html=True)
    st.caption("A compact view of what the OCR actually captured. This is evidence inspection, not an assumption that missing fields are absent from the physical package.")
    if label_evidence_rows:
        st.dataframe(label_evidence_rows, use_container_width=True, hide_index=True)
    else:
        st.info("No label evidence rows are available.")

    st.markdown('<div class="section-title">📄 Clean Label Evidence Export</div>', unsafe_allow_html=True)
    st.caption("Download the extracted ingredient/nutrition/package evidence plus the raw OCR text for audit or report writing.")
    st.download_button("⬇️ Download Label Evidence TXT", data=clean_label_text, file_name="foodreg_ai_label_evidence.txt", mime="text/plain", use_container_width=True, key="download_v9_label_evidence")

    # =====================================================
    # V8 PRESENTATION + AUDIT FEATURES
    # =====================================================

    country_attention_chart_rows = build_country_attention_chart_rows(country_profile_rows)
    ingredient_type_rows = build_ingredient_type_rows(summary_display_rows)
    current_manifest_entry = st.session_state.get("scan_history", [{}])[0] if st.session_state.get("scan_history") else {}
    scan_manifest = build_scan_manifest(current_manifest_entry, datetime.now().strftime("%Y-%m-%d %H:%M:%S"))

    st.markdown('<div class="section-title">🌍 Country Attention Overview</div>', unsafe_allow_html=True)
    st.caption("Counts reflect stored regulatory records for the current scan. They are not country risk scores or approval percentages.")
    if country_attention_chart_rows:
        chart_df = __import__("pandas").DataFrame(country_attention_chart_rows).set_index("Country / jurisdiction")
        keep_cols = [c for c in ["Prohibited", "Restricted", "Conditions", "No restriction"] if c in chart_df.columns]
        if keep_cols:
            st.bar_chart(chart_df[keep_cols], use_container_width=True)
    else:
        st.info("No country-level records are available for this overview.")

    st.markdown('<div class="section-title">🧩 Ingredient Composition Breakdown</div>', unsafe_allow_html=True)
    st.caption("Groups only the ingredient types already assigned by the current normalizer; unclassified entries remain visible.")
    if ingredient_type_rows:
        type_df = __import__("pandas").DataFrame(ingredient_type_rows).set_index("Category")
        st.bar_chart(type_df["Ingredients"], use_container_width=True)
        st.dataframe(ingredient_type_rows, use_container_width=True, hide_index=True)
    else:
        st.info("No ingredient classification data is available.")

    st.markdown('<div class="section-title">🧠 Explain This Regulatory Result</div>', unsafe_allow_html=True)
    st.caption("Select one ingredient and jurisdiction to turn the stored regulatory fields into a plain-English review note. This does not add new legal interpretation.")
    explanation_ingredients = sorted({str(r.get("Ingredient", "")).strip() for r in summary_display_rows if str(r.get("Ingredient", "")).strip()}, key=str.lower)
    explanation_countries = sorted({str(r.get("Country", r.get("Jurisdiction", "")).strip()) for r in comparison_rows if str(r.get("Country", r.get("Jurisdiction", "")).strip())}, key=str.lower)
    if explanation_ingredients and explanation_countries:
        ee1, ee2 = st.columns(2)
        with ee1:
            explanation_ingredient = st.selectbox("Ingredient", explanation_ingredients, key="v8_explanation_ingredient")
        with ee2:
            explanation_country = st.selectbox("Jurisdiction", explanation_countries, key="v8_explanation_country")
        explanation = build_regulatory_explanation(regulatory_results, explanation_ingredient, explanation_country)
        if explanation["found"]:
            st.info(explanation["headline"])
            st.write(explanation["summary"])
            if explanation["source"]:
                st.markdown(f"**Stored source:** {explanation['source']}")
        else:
            st.warning(explanation["summary"])
    else:
        st.info("A regulatory explanation becomes available after country records are present.")

    st.markdown('<div class="section-title">🆔 Scan Audit Manifest</div>', unsafe_allow_html=True)
    st.caption("A lightweight trace identifier helps connect the on-screen analysis with exported files without storing the product image.")
    manifest_a, manifest_b, manifest_c = st.columns(3)
    manifest_a.metric("Scan ID", scan_manifest["Scan ID"])
    manifest_b.metric("Generated", scan_manifest["Generated"])
    manifest_c.metric("Source file", scan_manifest["Source file"] or "—")
    st.download_button("⬇️ Download Audit Manifest", data=json.dumps(scan_manifest, indent=2), file_name="foodreg_ai_scan_manifest.json", mime="application/json", use_container_width=True, key="download_scan_manifest")

    # =====================================================
    # V11 FEATURES
    # =====================================================

    st.markdown('<div class="section-title">🧪 Ingredient Regulatory Evidence Matrix</div>', unsafe_allow_html=True)
    st.caption("One-row-per-ingredient view of stored jurisdiction findings. Missing records are not treated as approval.")
    if regulatory_matrix_rows:
        rm1, rm2, rm3, rm4 = st.columns(4)
        rm1.metric("Ingredients", len(regulatory_matrix_rows))
        rm2.metric("With records", sum(1 for r in regulatory_matrix_rows if r.get("Stored jurisdictions", 0)))
        rm3.metric("Attention findings", sum(int(r.get("Attention findings", 0)) for r in regulatory_matrix_rows))
        rm4.metric("Stored records", sum(int(r.get("Stored jurisdictions", 0)) for r in regulatory_matrix_rows))
        st.dataframe(regulatory_matrix_rows, use_container_width=True, hide_index=True)
    else:
        st.info("No regulatory matrix rows are available for this scan.")

    st.markdown('<div class="section-title">📦 Regulatory Batch Summary</div>', unsafe_allow_html=True)
    st.caption("A compact summary of the current scan's stored regulatory dataset. Counts describe stored records, not legal approval or risk probabilities.")
    rb1, rb2, rb3, rb4, rb5 = st.columns(5)
    rb1.metric("Stored records", regulatory_batch_summary["stored_regulatory_records"])
    rb2.metric("Countries", regulatory_batch_summary["countries_with_records"])
    rb3.metric("Prohibited", regulatory_batch_summary["prohibited_not_authorised"])
    rb4.metric("Restricted", regulatory_batch_summary["restricted"])
    rb5.metric("Conditions", regulatory_batch_summary["conditions"])
    tier_rows = [{"Source tier": k, "Records": v} for k, v in sorted(regulatory_batch_summary.get("source_tiers", {}).items())]
    if tier_rows:
        st.dataframe(tier_rows, use_container_width=True, hide_index=True)

    st.markdown('<div class="section-title">🏷️ Claim Evidence View</div>', unsafe_allow_html=True)
    st.caption("Claim screening is label-evidence analysis only. It does not certify a claim as legally compliant.")
    if claim_evidence_rows:
        claim_filter = st.selectbox("Claim", ["All claims"] + [str(r.get("Claim", "")) for r in claim_evidence_rows], key="v11_claim_filter")
        filtered_claim_evidence = claim_evidence_rows if claim_filter == "All claims" else [r for r in claim_evidence_rows if r.get("Claim") == claim_filter]
        st.dataframe(filtered_claim_evidence, use_container_width=True, hide_index=True)
    else:
        st.info("No detected label claims are available for evidence review.")

    st.markdown('<div class="section-title">📦 Export Package Contents</div>', unsafe_allow_html=True)
    st.caption("The Full Export ZIP is the recommended single-file handoff for reviewing or archiving this scan.")
    st.info("The export package contains label-derived outputs, regulatory records, evidence tables and audit files. It does not contain the uploaded product image unless you explicitly add it yourself.")

    # =====================================================
    # V14 AUDIT + COMPARISON FEATURES
    # =====================================================

    duplicate_ingredient_rows = build_duplicate_ingredient_rows(normalized_results)
    st.markdown('<div class="section-title">🔁 Duplicate / Repeated Ingredient Check</div>', unsafe_allow_html=True)
    st.caption("Flags repeated normalized ingredients so OCR segmentation or repeated compound-ingredient entries can be reviewed. Repetition is not automatically an error.")
    if duplicate_ingredient_rows:
        st.dataframe(duplicate_ingredient_rows, use_container_width=True, hide_index=True)
    else:
        st.success("No repeated canonical ingredients were detected in the current scan.")

    st.markdown('<div class="section-title">⚖️ Two-Country Regulatory Difference Viewer</div>', unsafe_allow_html=True)
    st.caption("Compares stored records between two jurisdictions. Missing data is shown as missing evidence, not approval.")
    pair_countries = sorted({str(r.get("Country", r.get("Jurisdiction", "")) or "").strip() for r in comparison_rows if str(r.get("Country", r.get("Jurisdiction", "")) or "").strip()}, key=str.lower)
    if len(pair_countries) >= 2:
        pc1, pc2 = st.columns(2)
        with pc1:
            pair_a = st.selectbox("Country A", pair_countries, index=0, key="v14_country_a")
        with pc2:
            pair_b = st.selectbox("Country B", pair_countries, index=1, key="v14_country_b")
        country_pair_diff_rows = build_country_pair_diff_rows(regulatory_results, pair_a, pair_b)
        if country_pair_diff_rows:
            st.dataframe(country_pair_diff_rows, use_container_width=True, hide_index=True)
        else:
            st.success("No stored status/level/condition differences were found for the selected country pair.")
    else:
        pair_a, pair_b, country_pair_diff_rows = "", "", []
        st.info("At least two jurisdictions with stored records are needed for a country-pair comparison.")

    ingredient_evidence_grade_rows = build_ingredient_evidence_grade_rows(normalized_results, regulatory_results, evidence_gap_rows)
    st.markdown('<div class="section-title">🔬 Ingredient Evidence Grade</div>', unsafe_allow_html=True)
    st.caption("Grades summarize captured evidence metadata and OCR matching only. They are not safety, health, legal, or risk scores.")
    if ingredient_evidence_grade_rows:
        st.dataframe(ingredient_evidence_grade_rows, use_container_width=True, hide_index=True)
    else:
        st.info("No ingredient evidence-grade rows are available.")

    st.markdown('<div class="section-title">✅ Final Human Review Sign-off</div>', unsafe_allow_html=True)
    st.caption("Use this checklist before treating the scan as reviewed. Ticking a box records workflow completion only.")
    sc1, sc2, sc3, sc4 = st.columns(4)
    with sc1:
        st.session_state.v14_reviewer_checks["ingredients"] = st.checkbox("Ingredients reviewed", value=st.session_state.v14_reviewer_checks.get("ingredients", False), key="v14_check_ingredients")
    with sc2:
        st.session_state.v14_reviewer_checks["allergens"] = st.checkbox("Allergens reviewed", value=st.session_state.v14_reviewer_checks.get("allergens", False), key="v14_check_allergens")
    with sc3:
        st.session_state.v14_reviewer_checks["regulatory"] = st.checkbox("Regulatory reviewed", value=st.session_state.v14_reviewer_checks.get("regulatory", False), key="v14_check_regulatory")
    with sc4:
        st.session_state.v14_reviewer_checks["nutrition"] = st.checkbox("Nutrition reviewed", value=st.session_state.v14_reviewer_checks.get("nutrition", False), key="v14_check_nutrition")
    v14_now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    v14_scan_id = str(scan_manifest.get("Scan ID", "") if isinstance(scan_manifest, dict) else "")
    reviewer_signoff_text = build_reviewer_signoff_text(st.session_state.v14_reviewer_checks, v14_scan_id, v14_now)
    completed_checks = sum(bool(v) for v in st.session_state.v14_reviewer_checks.values())
    st.progress(completed_checks / 4 if 4 else 0)
    st.caption(f"Review checklist: {completed_checks}/4 completed.")
    st.download_button("⬇️ Download Review Sign-off", data=reviewer_signoff_text, file_name="foodreg_ai_reviewer_signoff.txt", mime="text/plain", use_container_width=True, key="download_v14_reviewer_signoff")

    # =====================================================
    # V15 FINAL SUMMARY
    # =====================================================

    final_summary_panel=build_final_summary_panel(screening_decision,dashboard_stats,label_quality,review_center_rows,regulatory_alert_feed)
    st.markdown('<div id="final-summary"></div>',unsafe_allow_html=True)
    st.markdown('<div class="section-title">🎯 Final Product Summary</div>',unsafe_allow_html=True)
    st.caption("One-screen summary of the current scan and stored evidence. It is not medical advice, a safety score, or a legal compliance certificate.")
    f1,f2,f3,f4,f5=st.columns(5)
    with f1: st.metric("Screening",final_summary_panel["Screening"])
    with f2: st.metric("Ingredients",final_summary_panel["Ingredients"])
    with f3: st.metric("Regulatory alerts",final_summary_panel["High alerts"]+final_summary_panel["Medium alerts"])
    with f4: st.metric("Open review items",final_summary_panel["Open review items"])
    with f5: st.metric("Label quality",f"{final_summary_panel['Label data quality score']} / 100")
    st.info(f"{final_summary_panel['Title']}: {screening_decision.get('text','Current screening result is based on stored evidence.')}")

    # Regulatory-source freshness warning for the current scan.
    if REGULATORY_UPDATE_ENGINE_READY:
        try:
            scan_update_dashboard = get_update_dashboard()
            pending_for_scan = []
            scan_names = {str(x.get("canonical","")).strip().lower() for x in normalized_results if str(x.get("canonical","")).strip()}
            for ev in scan_update_dashboard.get("events", []):
                if str(ev.get("status","")).upper() != "PENDING_REVIEW":
                    continue
                try:
                    ev_ingredients = {str(x).strip().lower() for x in json.loads(ev.get("matched_ingredients") or "[]")}
                except Exception:
                    ev_ingredients = set()
                if scan_names.intersection(ev_ingredients):
                    pending_for_scan.append(ev)
            if pending_for_scan:
                st.warning(
                    f"⚠️ {len(pending_for_scan)} pending official-source change event(s) match ingredients in this scan. "
                    "Re-verify those records before relying on the stored regulatory result."
                )
        except Exception:
            pass

    # =====================================================
    # DOWNLOADABLE REPORTS
    # =====================================================
    st.markdown('<div id="downloads"></div>', unsafe_allow_html=True)

    st.markdown(
        '<div class="section-title">📥 Download Results</div>',
        unsafe_allow_html=True,
    )

    summary_csv = build_summary_csv(summary_display_rows)
    country_csv = build_country_csv(comparison_rows)
    html_report = build_html_report(
        summary_display_rows,
        comparison_rows,
        allergens,
        nutrition=nutrition_info,
        label_checks=label_completeness_rows,
        ingredient_order_rows=ingredient_order_rows,
        scan_clarity=scan_clarity,
        additive_function_rows=additive_function_rows,
        jurisdiction_attention_rows=jurisdiction_attention_rows,
        ingredient_audit_rows=ingredient_audit_rows,
        product_glance=product_glance,
        review_action_checklist=review_action_checklist,
        metadata_completeness=metadata_completeness,
    )
    report_footer = f"<footer style=\"margin-top:32px;padding-top:14px;border-top:1px solid #e4cf8a;font-size:12px;color:#6f5b4d;\">FoodReg AI • Report version 16.0 • Generated {escape(datetime.now().strftime('%Y-%m-%d %H:%M:%S'))}</footer>"
    if "</main>" in html_report:
        html_report=html_report.replace("</main>", report_footer+"</main>", 1)
    ingredient_audit_csv = build_ingredient_audit_csv(ingredient_audit_rows)
    regulatory_difference_csv = build_regulatory_difference_csv(regulatory_difference_rows)
    review_action_csv = build_summary_csv(review_action_checklist) if review_action_checklist else ""
    regulatory_only_rows = build_regulatory_only_rows(regulatory_results)
    regulatory_only_csv = rows_to_csv(regulatory_only_rows)
    regulatory_timeline_rows = build_regulatory_timeline_rows(regulatory_results)
    decision_brief = build_decision_brief(
        screening_decision,
        attention_rows,
        country_profile_rows,
        review_action_checklist,
        st.session_state.get("review_notes", ""),
    )

    attention_html="".join(
        f"<tr><td>{escape(str(r.get('Ingredient','')))}</td><td>{escape(str(r.get('Review level','')))}</td><td>{escape(str(r.get('Prohibited / not authorised',0)))}</td><td>{escape(str(r.get('Restricted',0)))}</td><td>{escape(str(r.get('Conditions',0)))}</td><td>{escape(str(r.get('Manual review','No')))}</td></tr>"
        for r in attention_rows
    )
    country_profile_html="".join(
        f"<tr><td>{escape(str(r.get('Country','')))}</td><td>{escape(str(r.get('Profile','')))}</td><td>{escape(str(r.get('Records',0)))}</td><td>{escape(str(r.get('Attention findings',0)))}</td></tr>"
        for r in country_profile_rows
    )
    notes_html=escape(st.session_state.get("review_notes", "").strip()) or "No reviewer notes were added."
    history_html="".join(
        f"<tr><td>{escape(str(r.get('Time','')))}</td><td>{escape(str(r.get('File','')))}</td><td>{escape(str(r.get('Ingredients',0)))}</td><td>{escape(str(r.get('Regulatory records',0)))}</td><td>{escape(str(r.get('Attention','')))}</td></tr>"
        for r in history_rows
    )
    nutrition_review_html="".join(
        f"<tr><td>{escape(str(r.get('Nutrient','')))}</td><td>{escape(str(r.get('Detected value','')))}</td><td>{escape(str(r.get('Your threshold','')))}</td><td>{escape(str(r.get('Review flag','')))}</td><td>{escape(str(r.get('Basis','')))}</td></tr>"
        for r in nutrition_review_rows
    )
    order_visual_html="".join(
        f"<tr><td>{escape(str(r.get('Rank','')))}</td><td>{escape(str(r.get('Ingredient','')))}</td><td>{escape(str(r.get('Label prominence','')))}</td><td>{escape(str(r.get('Prominence score','')))}</td></tr>"
        for r in ingredient_order_rows
    )
    source_hub_html = "".join(
        f"<tr><td>{escape(str(r.get('Ingredient','')))}</td><td>{escape(str(r.get('Jurisdiction','')))}</td><td>{escape(str(r.get('Status','')))}</td><td>{escape(str(r.get('Authority','')))}</td><td>{escape(str(r.get('Last verified','')))}</td><td>{escape(str(r.get('Source','')))}</td></tr>"
        for r in source_hub_rows[:100]
    )

    html_appendix=f"""
    <h2>Scan history dashboard</h2>
    <p>Stored scans: {escape(str(build_history_dashboard_rows(st.session_state.get('scan_history', []))['scans']))} • Bookmarked: {escape(str(build_history_dashboard_rows(st.session_state.get('scan_history', []))['bookmarked']))}. History stores metadata only.</p>
    <h2>Product-to-product comparison</h2>
    <table><thead><tr><th>Metric</th><th>Left value</th><th>Right value</th><th>Difference</th></tr></thead><tbody>{''.join(f"<tr><td>{escape(str(r.get('Metric','')))}</td><td>{escape(str(r.get('Left value','')))}</td><td>{escape(str(r.get('Right value','')))}</td><td>{escape(str(r.get('Difference','')))}</td></tr>" for r in (history_compare_rows if 'history_compare_rows' in locals() else [])) or '<tr><td colspan="4">No two-scan comparison selected.</td></tr>'}</tbody></table>
    <h2>Custom nutrition review thresholds</h2>
    <table><thead><tr><th>Nutrient</th><th>Detected value</th><th>Your threshold</th><th>Review flag</th><th>Basis</th></tr></thead><tbody>{nutrition_review_html or '<tr><td colspan="5">No nutrition review data.</td></tr>'}</tbody></table>
    <h2>Ingredient order</h2>
    <table><thead><tr><th>Rank</th><th>Ingredient</th><th>Label prominence</th><th>Prominence score</th></tr></thead><tbody>{order_visual_html or '<tr><td colspan="4">No ingredient-order data.</td></tr>'}</tbody></table>
    <h2>Ingredient attention ranking</h2>
    <table><thead><tr><th>Ingredient</th><th>Review level</th><th>Prohibited</th><th>Restricted</th><th>Conditions</th><th>Manual review</th></tr></thead><tbody>{attention_html or '<tr><td colspan="6">No ranking available.</td></tr>'}</tbody></table>
    <h2>Country regulatory profile</h2>
    <table><thead><tr><th>Country</th><th>Profile</th><th>Records</th><th>Attention findings</th></tr></thead><tbody>{country_profile_html or '<tr><td colspan="4">No country profile available.</td></tr>'}</tbody></table>
    <h2>Reviewer notes</h2><div class="note">{notes_html}</div>
    <h2>Scan session history</h2>
    <table><thead><tr><th>Time</th><th>File</th><th>Ingredients</th><th>Regulatory records</th><th>Attention</th></tr></thead><tbody>{history_html or '<tr><td colspan="5">No session history available.</td></tr>'}</tbody></table>
    <h2>Regulatory record freshness</h2>
    <table><thead><tr><th>Ingredient</th><th>Country</th><th>Last verified</th><th>Age (days)</th><th>Freshness</th></tr></thead><tbody>{''.join(f"<tr><td>{escape(str(r.get('Ingredient','')))}</td><td>{escape(str(r.get('Country','')))}</td><td>{escape(str(r.get('Last verified','')))}</td><td>{escape(str(r.get('Age (days)','')))}</td><td>{escape(str(r.get('Freshness','')))}</td></tr>" for r in freshness_rows) or '<tr><td colspan="5">No freshness records.</td></tr>'}</tbody></table>
    <h2>Review progress</h2><p>{escape(str(review_progress.get('completed',0)))} of {escape(str(review_progress.get('total',0)))} ingredients completed ({escape(str(review_progress.get('percent',0)))}%).</p>
    <h2>Evidence gap action plan</h2><table><thead><tr><th>Ingredient</th><th>Priority</th><th>Match confidence</th><th>Regulatory records</th><th>Evidence gaps</th></tr></thead><tbody>{''.join(f"<tr><td>{escape(str(r.get('Ingredient','')))}</td><td>{escape(str(r.get('Priority','')))}</td><td>{escape(str(r.get('Match confidence','')))}</td><td>{escape(str(r.get('Regulatory records','')))}</td><td>{escape(str(r.get('Evidence gaps','')))}</td></tr>" for r in evidence_gap_rows) or '<tr><td colspan="5">No evidence gaps.</td></tr>'}</tbody></table>
    <h2>Stored regulatory source links</h2><table><thead><tr><th>Ingredient</th><th>Jurisdiction</th><th>Status</th><th>Authority</th><th>Verified</th><th>Source</th></tr></thead><tbody>{source_hub_html or '<tr><td colspan="6">No source links available.</td></tr>'}</tbody></table>
    """
    claims_html="".join(f"<tr><td>{escape(str(r.get('Claim detected','')))}</td><td>{escape(str(r.get('Evidence in OCR','')))}</td><td>{escape(str(r.get('Verification','')))}</td></tr>" for r in claims_rows)
    composition_html="".join(f"<tr><td>{escape(str(r.get('Category','')))}</td><td>{escape(str(r.get('Count','')))}</td><td>{escape(str(r.get('Ingredients','')))}</td></tr>" for r in composition_rows)
    status_html="".join(f"<tr><td>{escape(str(r.get('Status','')))}</td><td>{escape(str(r.get('Country records','')))}</td><td>{escape(str(r.get('Unique ingredients','')))}</td></tr>" for r in status_distribution_rows)
    coverage_html="".join(f"<tr><td>{escape(str(r.get('Ingredient','')))}</td><td>{escape(str(r.get('Jurisdictions checked','')))}</td><td>{escape(str(r.get('Stored records','')))}</td><td>{escape(str(r.get('Missing stored records','')))}</td><td>{escape(str(r.get('Review','')))}</td></tr>" for r in coverage_action_rows)
    metadata_rows_html = "".join(
        f"<tr><td>{escape(str(k).replace('_',' ').title())}</td><td>{escape(str(v or '—'))}</td></tr>"
        for k, v in (product_metadata or {}).items()
        if k != 'detected_fields'
    )
    timeline_html = "".join(
        f"<tr><td>{escape(str(r.get('Ingredient','')))}</td><td>{escape(str(r.get('Country / jurisdiction','')))}</td><td>{escape(str(r.get('Status','')))}</td><td>{escape(str(r.get('Last verified','')))}</td><td>{escape(str(r.get('Authority','')))}</td></tr>"
        for r in regulatory_timeline_rows
    )
    glossary_html="".join(f"<tr><td>{escape(str(r.get('Ingredient','')))}</td><td>{escape(str(r.get('INS','')))}</td><td>{escape(str(r.get('CAS','')))}</td><td>{escape(str(r.get('Aliases','')))}</td><td>{escape(str(r.get('Description','')))}</td></tr>" for r in glossary_rows)
    watchlist_html="".join(f"<tr><td>{escape(str(r.get('Ingredient','')))}</td><td>{escape(str(r.get('INS','')))}</td><td>{escape(str(r.get('Jurisdictions with records','')))}</td><td>{escape(str(r.get('Distinct stored statuses','')))}</td><td>{escape(str(r.get('Attention jurisdictions','')))}</td></tr>" for r in watchlist_rows)
    reviewer_html="".join(f"<tr><td>{escape(str(r.get('Ingredient','')))}</td><td>{escape(str(r.get('Reviewer status','')))}</td><td>{escape(str(r.get('Reviewer note','')))}</td></tr>" for r in reviewer_status_rows)
    html_appendix += f"""
    <h2>Ingredient watchlist</h2><table><thead><tr><th>Ingredient</th><th>INS</th><th>Jurisdictions with records</th><th>Distinct statuses</th><th>Attention jurisdictions</th></tr></thead><tbody>{watchlist_html or '<tr><td colspan="5">No ingredients were added to the watchlist.</td></tr>'}</tbody></table>
    <h2>Reviewer status tracker</h2><table><thead><tr><th>Ingredient</th><th>Status</th><th>Reviewer note</th></tr></thead><tbody>{reviewer_html or '<tr><td colspan="3">No reviewer statuses recorded.</td></tr>'}</tbody></table>
    <h2>Ingredient glossary results</h2><table><thead><tr><th>Ingredient</th><th>INS</th><th>CAS</th><th>Aliases</th><th>Description</th></tr></thead><tbody>{glossary_html or '<tr><td colspan="5">No glossary search results.</td></tr>'}</tbody></table>
    <h2>Product library</h2><table><thead><tr><th>Product</th><th>Scans</th><th>Latest scan</th><th>Bookmarks</th><th>Latest attention</th></tr></thead><tbody>{''.join(f"<tr><td>{escape(str(r.get('Product','')))}</td><td>{escape(str(r.get('Scans','')))}</td><td>{escape(str(r.get('Latest scan','')))}</td><td>{escape(str(r.get('Bookmarks','')))}</td><td>{escape(str(r.get('Latest attention','')))}</td></tr>" for r in product_library_rows) or '<tr><td colspan="5">No product library data.</td></tr>'}</tbody></table>
    <h2>Scan integrity</h2><p>Exact previous file matches: {len(duplicate_file_matches)} • Same ingredient-list matches: {len(ingredient_match_scans)} • Previous similar scan: {escape(str(previous_similar_scan.get('file','None') if previous_similar_scan else 'None'))}</p>
    <h2>Change impact vs previous similar scan</h2><table><thead><tr><th>Area</th><th>Change</th><th>Previous</th><th>Current</th><th>Interpretation</th></tr></thead><tbody>{''.join(f"<tr><td>{escape(str(r.get('Area','')))}</td><td>{escape(str(r.get('Change','')))}</td><td>{escape(str(r.get('Previous','')))}</td><td>{escape(str(r.get('Current','')))}</td><td>{escape(str(r.get('Interpretation','')))}</td></tr>" for r in scan_delta_rows) or '<tr><td colspan="5">No previous-scan delta available.</td></tr>'}</tbody></table>
    <h2>Product history trend</h2><table><thead><tr><th>Date</th><th>Ingredients</th><th>Additives</th><th>Allergens</th><th>Regulatory records</th></tr></thead><tbody>{''.join(f"<tr><td>{escape(str(r.get('Date','')))}</td><td>{escape(str(r.get('Ingredients','')))}</td><td>{escape(str(r.get('Additives','')))}</td><td>{escape(str(r.get('Allergens','')))}</td><td>{escape(str(r.get('Regulatory records','')))}</td></tr>" for r in product_trend_rows) or '<tr><td colspan="5">No history trend available.</td></tr>'}</tbody></table>
    <h2>Product & package details</h2><table><thead><tr><th>Field</th><th>Detected value</th></tr></thead><tbody>{metadata_rows_html or '<tr><td colspan="2">No package metadata detected.</td></tr>'}</tbody></table>
    <h2>Regulatory evidence timeline</h2><table><thead><tr><th>Ingredient</th><th>Country / jurisdiction</th><th>Status</th><th>Last verified</th><th>Authority</th></tr></thead><tbody>{timeline_html or '<tr><td colspan="5">No verification timeline available.</td></tr>'}</tbody></table>
    <h2>Label claim audit</h2><table><thead><tr><th>Claim detected</th><th>Evidence in OCR</th><th>Verification</th></tr></thead><tbody>{claims_html or '<tr><td colspan="3">No claims detected.</td></tr>'}</tbody></table>
    <h2>Product composition breakdown</h2><table><thead><tr><th>Category</th><th>Count</th><th>Ingredients</th></tr></thead><tbody>{composition_html}</tbody></table>
    <h2>Regulatory status distribution</h2><table><thead><tr><th>Status</th><th>Country records</th><th>Unique ingredients</th></tr></thead><tbody>{status_html or '<tr><td colspan="3">No status records.</td></tr>'}</tbody></table>
    <h2>Coverage action panel</h2><table><thead><tr><th>Ingredient</th><th>Checked</th><th>Stored</th><th>Missing</th><th>Review</th></tr></thead><tbody>{coverage_html or '<tr><td colspan="5">No coverage data.</td></tr>'}</tbody></table>
    <h2>Claim verification intelligence</h2><table><thead><tr><th>Claim</th><th>Screening</th><th>Evidence</th><th>Recommended action</th></tr></thead><tbody>{''.join(f"<tr><td>{escape(str(r.get('Claim','')))}</td><td>{escape(str(r.get('Screening','')))}</td><td>{escape(str(r.get('Evidence','')))}</td><td>{escape(str(r.get('Recommended action','')))}</td></tr>" for r in claim_verification_rows) or '<tr><td colspan="4">No claim verification data.</td></tr>'}</tbody></table>
    <h2>Ingredient evidence</h2><table><thead><tr><th>Ingredient</th><th>INS</th><th>Confidence</th><th>Regulatory records</th><th>Tier 1 records</th><th>Attention</th></tr></thead><tbody>{''.join(f"<tr><td>{escape(str(r.get('Ingredient','')))}</td><td>{escape(str(r.get('INS','')))}</td><td>{escape(str(r.get('Match confidence','')))}</td><td>{escape(str(r.get('Regulatory records',0)))}</td><td>{escape(str(r.get('Tier 1 source records',0)))}</td><td>{escape(str(r.get('Attention finding present','')))}</td></tr>" for r in ingredient_evidence_rows) or '<tr><td colspan="6">No ingredient evidence rows.</td></tr>'}</tbody></table>
    <h2>Regulatory source intelligence</h2><table><thead><tr><th>Ingredient</th><th>Country</th><th>Source tier</th><th>Authority</th><th>Verified</th><th>Metadata</th></tr></thead><tbody>{''.join(f"<tr><td>{escape(str(r.get('Ingredient','')))}</td><td>{escape(str(r.get('Country / jurisdiction','')))}</td><td>{escape(str(r.get('Source tier','')))}</td><td>{escape(str(r.get('Authority','')))}</td><td>{escape(str(r.get('Verified','')))}</td><td>{escape(str(r.get('Metadata completeness','')))}</td></tr>" for r in source_intelligence_rows) or '<tr><td colspan="6">No source intelligence rows.</td></tr>'}</tbody></table>
    <h2>Cross-jurisdiction divergence</h2><table><thead><tr><th>Ingredient</th><th>Statuses</th><th>Countries by status</th><th>Review priority</th></tr></thead><tbody>{''.join(f"<tr><td>{escape(str(r.get('Ingredient','')))}</td><td>{escape(str(r.get('Distinct stored statuses','')))}</td><td>{escape(str(r.get('Countries by status','')))}</td><td>{escape(str(r.get('Review priority','')))}</td></tr>" for r in regulatory_divergence_rows) or '<tr><td colspan="4">No divergence rows.</td></tr>'}</tbody></table>
    <h2>Regulatory review packet</h2><pre>{escape(regulatory_review_packet)}</pre>
    <h2>Product fact sheet</h2><pre>{escape(product_fact_sheet)}</pre>
    <h2>Ingredient relationship map</h2><table><thead><tr><th>Ingredient</th><th>Type</th><th>INS</th><th>Allergen signal</th><th>Countries with records</th><th>Attention countries</th></tr></thead><tbody>{''.join(f"<tr><td>{escape(str(r.get('Ingredient','')))}</td><td>{escape(str(r.get('Type','')))}</td><td>{escape(str(r.get('INS','')))}</td><td>{escape(str(r.get('Allergen signal','')))}</td><td>{escape(str(r.get('Countries with records','')))}</td><td>{escape(str(r.get('Attention countries','')))}</td></tr>" for r in relationship_rows) or '<tr><td colspan="6">No relationship rows.</td></tr>'}</tbody></table>
    <h2>Regulatory change watch</h2><table><thead><tr><th>Ingredient</th><th>Country</th><th>Previous</th><th>Current</th><th>Change</th></tr></thead><tbody>{''.join(f"<tr><td>{escape(str(r.get('Ingredient','')))}</td><td>{escape(str(r.get('Country','')))}</td><td>{escape(str(r.get('Previous','')))}</td><td>{escape(str(r.get('Current','')))}</td><td>{escape(str(r.get('Change','')))}</td></tr>" for r in regulatory_watch_rows) or '<tr><td colspan="5">No watch changes.</td></tr>'}</tbody></table>
    <h2>Final product summary</h2><pre>{escape(json.dumps(final_summary_panel, indent=2, ensure_ascii=False))}</pre>
    """
    if "</main>" in html_report:
        html_report=html_report.replace("</main>", html_appendix+"</main>", 1)

    json_report = build_json_export(
        summary_display_rows,
        comparison_rows,
        allergens,
        nutrition_info,
        label_completeness_rows,
        ingredient_order_rows,
        additive_function_rows,
        scan_clarity,
        ingredient_audit_rows=ingredient_audit_rows,
        product_glance=product_glance,
        regulatory_differences=regulatory_difference_rows,
        screening_decision=screening_decision,
        review_action_checklist=review_action_checklist,
        metadata_completeness=metadata_completeness,
    )
    try:
        _json_payload=json.loads(json_report)
    except Exception:
        _json_payload={}
    _json_payload["ingredient_attention_ranking"]=attention_rows
    _json_payload["country_regulatory_profile"]=country_profile_rows
    _json_payload["review_notes"]=st.session_state.get("review_notes", "")
    _json_payload["scan_session_history"]=st.session_state.get("scan_history", [])
    _json_payload["decision_brief"]=decision_brief
    _json_payload["regulatory_record_freshness"]=freshness_rows
    _json_payload["regulatory_coverage_gaps"]=coverage_gap_rows
    _json_payload["label_claim_audit"]=claims_rows
    _json_payload["product_composition_breakdown"]=composition_rows
    _json_payload["regulatory_status_distribution"]=status_distribution_rows
    _json_payload["coverage_action_panel"]=coverage_action_rows
    _json_payload["product_fact_sheet"]=product_fact_sheet
    _json_payload["product_metadata"]=product_metadata
    _json_payload["claim_verification_intelligence"]=claim_verification_rows
    _json_payload["ingredient_evidence_cards"]=ingredient_evidence_rows
    _json_payload["regulatory_source_intelligence"]=source_intelligence_rows
    if REGULATORY_UPDATE_ENGINE_READY:
        try:
            _json_payload["regulatory_update_monitor"] = get_update_dashboard()
        except Exception:
            _json_payload["regulatory_update_monitor"] = {"error": "Update dashboard unavailable"}
    else:
        _json_payload["regulatory_update_monitor"] = {"error": "Update engine unavailable"}
    _json_payload["regulatory_source_intelligence_summary"]=source_intelligence_summary
    _json_payload["cross_jurisdiction_divergence"]=regulatory_divergence_rows
    _json_payload["regulatory_review_packet"]=regulatory_review_packet
    _json_payload["persistent_scan_history"]=st.session_state.get("scan_history", [])
    _json_payload["history_dashboard"]=build_history_dashboard_rows(st.session_state.get("scan_history", []))
    _json_payload["product_library"]=product_library_rows
    _json_payload["scan_integrity"]={"exact_file_matches":len(duplicate_file_matches),"same_ingredient_matches":len(ingredient_match_scans),"previous_similar_scan":previous_similar_scan or {}}
    _json_payload["change_impact_vs_previous_similar_scan"]=scan_delta_rows
    _json_payload["product_history_trend"]=product_trend_rows
    _json_payload["nutrition_review_thresholds"] = st.session_state.nutrition_review_thresholds
    _json_payload["nutrition_review_rows"] = nutrition_review_rows
    _json_payload["ingredient_watchlist"] = st.session_state.ingredient_watchlist
    _json_payload["ingredient_watchlist_rows"] = watchlist_rows
    _json_payload["ingredient_reviewer_status"] = reviewer_status_rows
    _json_payload["ingredient_glossary_results"] = glossary_rows
    _json_payload["product_dashboard_stats"] = dashboard_stats
    _json_payload["regulatory_status_heatmap"] = heatmap_rows if "heatmap_rows" in locals() else []
    _json_payload["ingredient_evidence_coverage"] = evidence_score_rows
    _json_payload["audit_snapshot"] = audit_snapshot
    _json_payload["label_data_quality"] = label_quality
    _json_payload["smart_review_center"] = review_center_rows
    _json_payload["nutrition_consistency"] = nutrition_consistency_rows
    _json_payload["regulatory_source_explorer"] = filtered_sources if "filtered_sources" in locals() else []
    _json_payload["country_attention_overview"] = country_attention_chart_rows if "country_attention_chart_rows" in locals() else []
    _json_payload["ingredient_composition_breakdown"] = ingredient_type_rows if "ingredient_type_rows" in locals() else []
    _json_payload["regulatory_explanation"] = explanation if "explanation" in locals() else {}
    _json_payload["additive_function_explorer"] = function_rows_filtered if "function_rows_filtered" in locals() else []
    _json_payload["regulatory_data_consistency_audit"] = regulatory_consistency_rows if "regulatory_consistency_rows" in locals() else []
    _json_payload["priority_regulatory_alert_feed"] = regulatory_alert_feed if "regulatory_alert_feed" in locals() else []
    _json_payload["executive_brief"] = executive_brief if "executive_brief" in locals() else ""
    _json_payload["scan_manifest"] = scan_manifest if "scan_manifest" in locals() else {}
    _json_payload["compliance_review_table"] = compliance_review_rows if "compliance_review_rows" in locals() else []
    _json_payload["label_evidence_inspector"] = label_evidence_rows if "label_evidence_rows" in locals() else []
    _json_payload["review_progress"] = review_progress
    _json_payload["evidence_gap_action_plan"] = evidence_gap_rows
    _json_payload["source_link_hub"] = source_hub_rows
    _json_payload["current_scan_search"] = current_scan_search_rows
    _json_payload["clean_label_evidence_available"] = bool(clean_label_text) if "clean_label_text" in locals() else False
    _json_payload["product_to_product_comparison"]=history_compare_rows if "history_compare_rows" in locals() else []
    default_finder_ingredient = next((str(r.get("Ingredient", "")).strip() for r in summary_display_rows if str(r.get("Ingredient", "")).strip()), "")
    _json_payload["regulatory_attention_finder"] = build_regulatory_attention_finder_rows(regulatory_results, default_finder_ingredient)
    _json_payload["regulatory_evidence_timeline"] = regulatory_timeline_rows
    _json_payload["regulatory_evidence_matrix"] = regulatory_matrix_rows
    _json_payload["regulatory_batch_summary"] = regulatory_batch_summary
    _json_payload["claim_evidence_view"] = claim_evidence_rows
    _json_payload["duplicate_ingredient_check"] = duplicate_ingredient_rows
    _json_payload["country_pair_difference_view"] = country_pair_diff_rows if "country_pair_diff_rows" in locals() else []
    _json_payload["ingredient_evidence_grade"] = ingredient_evidence_grade_rows
    _json_payload["reviewer_signoff"] = reviewer_signoff_text if "reviewer_signoff_text" in locals() else ""
    _json_payload["ingredient_relationship_map"] = relationship_rows
    _json_payload["regulatory_change_watch"] = regulatory_watch_rows
    _json_payload["final_product_summary"] = final_summary_panel
    json_report=json.dumps(_json_payload, indent=2, ensure_ascii=False)

    export_manifest_rows = build_export_manifest([
        "foodreg_ai_summary.csv", "foodreg_ai_country_comparison.csv", "foodreg_ai_report.html", "foodreg_ai_analysis.json",
        "foodreg_ai_ingredient_audit.csv", "foodreg_ai_regulatory_differences.csv", "foodreg_ai_label_claim_audit.csv",
        "foodreg_ai_product_composition.csv", "foodreg_ai_regulatory_status_distribution.csv", "foodreg_ai_coverage_action_panel.csv",
        "foodreg_ai_product_fact_sheet.txt", "foodreg_ai_regulatory_records.csv", "foodreg_ai_regulatory_evidence_timeline.csv",
        "foodreg_ai_review_action_checklist.csv", "foodreg_ai_decision_brief.txt", "foodreg_ai_regulatory_matrix.csv",
        "foodreg_ai_claim_evidence.csv", "foodreg_ai_regulatory_batch_summary.json", "foodreg_ai_duplicate_ingredient_check.csv",
        "foodreg_ai_country_pair_difference.csv", "foodreg_ai_ingredient_evidence_grade.csv", "foodreg_ai_reviewer_signoff.txt", "foodreg_ai_ingredient_relationship.csv", "foodreg_ai_regulatory_change_watch.csv", "foodreg_ai_final_summary.json", "foodreg_ai_export_manifest.csv"
    ])

    export_readme = "FoodReg AI export bundle\n\n" \
        "This package contains label-derived analysis and database-backed regulatory records from the current scan.\n" \
        "Missing regulatory records are not treated as approval, and status differences are not automatically legal advice.\n" \
        "Scan history stores metadata only; product images and raw OCR text are not persisted by the history feature.\n"
    zip_buffer=io.BytesIO()
    with zipfile.ZipFile(zip_buffer, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("foodreg_ai_summary.csv", summary_csv)
        zf.writestr("foodreg_ai_country_comparison.csv", country_csv)
        zf.writestr("foodreg_ai_report.html", html_report)
        zf.writestr("foodreg_ai_analysis.json", json_report)
        zf.writestr("foodreg_ai_ingredient_audit.csv", ingredient_audit_csv)
        zf.writestr("foodreg_ai_regulatory_differences.csv", regulatory_difference_csv)
        zf.writestr("foodreg_ai_label_claim_audit.csv",rows_to_csv(claims_rows))
        zf.writestr("foodreg_ai_product_composition.csv",rows_to_csv(composition_rows))
        zf.writestr("foodreg_ai_regulatory_status_distribution.csv",rows_to_csv(status_distribution_rows))
        zf.writestr("foodreg_ai_coverage_action_panel.csv",rows_to_csv(coverage_action_rows))
        zf.writestr("foodreg_ai_product_fact_sheet.txt",product_fact_sheet)
        zf.writestr("foodreg_ai_regulatory_matrix.csv", rows_to_csv(regulatory_matrix_rows))
        zf.writestr("foodreg_ai_claim_evidence.csv", rows_to_csv(claim_evidence_rows))
        zf.writestr("foodreg_ai_duplicate_ingredient_check.csv", rows_to_csv(duplicate_ingredient_rows))
        zf.writestr("foodreg_ai_country_pair_difference.csv", rows_to_csv(country_pair_diff_rows if "country_pair_diff_rows" in locals() else []))
        zf.writestr("foodreg_ai_ingredient_evidence_grade.csv", rows_to_csv(ingredient_evidence_grade_rows))
        zf.writestr("foodreg_ai_reviewer_signoff.txt", reviewer_signoff_text if "reviewer_signoff_text" in locals() else "")
        zf.writestr("foodreg_ai_regulatory_batch_summary.json", json.dumps(regulatory_batch_summary, indent=2, ensure_ascii=False))
        zf.writestr("foodreg_ai_export_manifest.csv", rows_to_csv(export_manifest_rows))
        zf.writestr("foodreg_ai_regulatory_records.csv", regulatory_only_csv)
        zf.writestr("foodreg_ai_regulatory_evidence_timeline.csv", rows_to_csv(regulatory_timeline_rows))
        zf.writestr("foodreg_ai_review_action_checklist.csv", review_action_csv)
        zf.writestr("foodreg_ai_decision_brief.txt", decision_brief)
        zf.writestr("foodreg_ai_export_notes.txt", export_readme)
        zf.writestr("foodreg_ai_claim_verification.csv", rows_to_csv(claim_verification_rows))
        zf.writestr("foodreg_ai_ingredient_evidence.csv", rows_to_csv(ingredient_evidence_rows))
        zf.writestr("foodreg_ai_regulatory_source_intelligence.csv", rows_to_csv(source_intelligence_rows))
        zf.writestr("foodreg_ai_cross_jurisdiction_divergence.csv", rows_to_csv(regulatory_divergence_rows))
        zf.writestr("foodreg_ai_scan_history.csv", rows_to_csv(build_scan_history_rows(st.session_state.get("scan_history", []))))
        zf.writestr("foodreg_ai_product_to_product_comparison.csv", rows_to_csv(history_compare_rows if "history_compare_rows" in locals() else []))
        zf.writestr("foodreg_ai_product_library.csv", rows_to_csv(product_library_rows))
        zf.writestr("foodreg_ai_scan_delta.csv", rows_to_csv(scan_delta_rows))
        zf.writestr("foodreg_ai_product_history_trend.csv", rows_to_csv(product_trend_rows))
        zf.writestr("foodreg_ai_nutrition_review.csv", rows_to_csv(nutrition_review_rows))
        zf.writestr("foodreg_ai_ingredient_watchlist.csv", rows_to_csv(watchlist_rows))
        zf.writestr("foodreg_ai_reviewer_status.csv", rows_to_csv(reviewer_status_rows))
        zf.writestr("foodreg_ai_ingredient_glossary.csv", rows_to_csv(glossary_rows))
        zf.writestr("foodreg_ai_evidence_coverage.csv", rows_to_csv(evidence_score_rows))
        zf.writestr("foodreg_ai_regulatory_heatmap.csv", rows_to_csv(heatmap_rows if "heatmap_rows" in locals() else []))
        zf.writestr("foodreg_ai_audit_snapshot.txt", audit_snapshot)
        zf.writestr("foodreg_ai_label_data_quality.csv", rows_to_csv(label_quality["checks"]))
        zf.writestr("foodreg_ai_smart_review_center.csv", rows_to_csv(review_center_rows))
        zf.writestr("foodreg_ai_nutrition_consistency.csv", rows_to_csv(nutrition_consistency_rows))
        zf.writestr("foodreg_ai_regulatory_source_explorer.csv", rows_to_csv(filtered_sources if "filtered_sources" in locals() else []))
        zf.writestr("foodreg_ai_country_attention_overview.csv", rows_to_csv(country_attention_chart_rows if "country_attention_chart_rows" in locals() else []))
        zf.writestr("foodreg_ai_ingredient_composition.csv", rows_to_csv(ingredient_type_rows if "ingredient_type_rows" in locals() else []))
        zf.writestr("foodreg_ai_regulatory_explanation.txt", (explanation.get("headline", "") + "\n\n" + explanation.get("summary", "")) if "explanation" in locals() else "")
        zf.writestr("foodreg_ai_scan_manifest.json", json.dumps(scan_manifest if "scan_manifest" in locals() else {}, indent=2))
        zf.writestr("foodreg_ai_compliance_review.csv", rows_to_csv(compliance_review_rows if "compliance_review_rows" in locals() else []))
        zf.writestr("foodreg_ai_label_evidence.csv", rows_to_csv(label_evidence_rows if "label_evidence_rows" in locals() else []))
        zf.writestr("foodreg_ai_evidence_gap_action_plan.csv", rows_to_csv(evidence_gap_rows))
        zf.writestr("foodreg_ai_source_link_hub.csv", rows_to_csv(source_hub_rows))
        zf.writestr("foodreg_ai_current_scan_search.csv", rows_to_csv(current_scan_search_rows))
        zf.writestr("foodreg_ai_review_progress.json", json.dumps(review_progress, indent=2))
        zf.writestr("foodreg_ai_label_evidence.txt", clean_label_text if "clean_label_text" in locals() else "")
        zf.writestr("foodreg_ai_regulatory_review_packet.txt", regulatory_review_packet)
        zf.writestr("foodreg_ai_regulatory_consistency_audit.csv", rows_to_csv(regulatory_consistency_rows if "regulatory_consistency_rows" in locals() else []))
        zf.writestr("foodreg_ai_priority_regulatory_alert_feed.csv", rows_to_csv(regulatory_alert_feed if "regulatory_alert_feed" in locals() else []))
        zf.writestr("foodreg_ai_additive_function_explorer.csv", rows_to_csv(function_rows_filtered if "function_rows_filtered" in locals() else []))
        zf.writestr("foodreg_ai_executive_brief.txt", executive_brief if "executive_brief" in locals() else "")
        zf.writestr("foodreg_ai_claim_conflict_detector.csv", rows_to_csv(claim_conflict_rows if "claim_conflict_rows" in locals() else []))
        zf.writestr("foodreg_ai_regulatory_level_explorer.csv", rows_to_csv(level_filtered if "level_filtered" in locals() else regulatory_level_rows if "regulatory_level_rows" in locals() else []))
        zf.writestr("foodreg_ai_ingredient_screening_matrix.csv", rows_to_csv(ingredient_screening_matrix if "ingredient_screening_matrix" in locals() else []))
        zf.writestr("foodreg_ai_reviewer_handoff.txt", reviewer_handoff_text if "reviewer_handoff_text" in locals() else "")
        zf.writestr("foodreg_ai_ingredient_relationship.csv", rows_to_csv(relationship_rows))
        zf.writestr("foodreg_ai_regulatory_change_watch.csv", rows_to_csv(regulatory_watch_rows))
        zf.writestr("foodreg_ai_final_summary.json", json.dumps(final_summary_panel, indent=2, ensure_ascii=False))
        try:
            update_dashboard_for_export = get_update_dashboard() if REGULATORY_UPDATE_ENGINE_READY else {}
            zf.writestr("foodreg_ai_regulatory_update_dashboard.json", json.dumps(update_dashboard_for_export, indent=2, ensure_ascii=False, default=str))
            zf.writestr("foodreg_ai_regulatory_update_audit.csv", build_update_audit_csv(update_dashboard_for_export) if REGULATORY_UPDATE_ENGINE_READY else "")
        except Exception:
            zf.writestr("foodreg_ai_regulatory_update_dashboard.json", json.dumps({"error":"update dashboard unavailable"}))
            zf.writestr("foodreg_ai_regulatory_update_audit.csv", "")
    export_bundle=zip_buffer.getvalue()

    dl1, dl2, dl3, dl4, dl5, dl6 = st.columns(6)
    with dl1:
        st.download_button("⬇️ Full Export ZIP", data=export_bundle, file_name="foodreg_ai_export_bundle.zip", mime="application/zip", use_container_width=True, key="download_export_bundle")
    with dl2:
        st.download_button("⬇️ Summary CSV", data=summary_csv, file_name="foodreg_ai_summary.csv", mime="text/csv", use_container_width=True, key="download_summary_csv")
    with dl3:
        st.download_button("⬇️ Full HTML Report", data=html_report, file_name="foodreg_ai_report.html", mime="text/html", use_container_width=True, key="download_html_report")
    with dl4:
        st.download_button("⬇️ JSON Data", data=json_report, file_name="foodreg_ai_analysis.json", mime="application/json", use_container_width=True, key="download_json_report")
    with dl5:
        st.download_button("⬇️ Country CSV", data=country_csv, file_name="foodreg_ai_country_comparison.csv", mime="text/csv", use_container_width=True, key="download_country_csv")
    with dl6:
        st.download_button("⬇️ Regulatory CSV", data=regulatory_only_csv, file_name="foodreg_ai_regulatory_records.csv", mime="text/csv", use_container_width=True, key="download_regulatory_csv")
    exv9a, exv9b = st.columns(2)
    with exv9a:
        st.download_button("⬇️ Compliance Review CSV", data=rows_to_csv(compliance_review_rows if "compliance_review_rows" in locals() else []), file_name="foodreg_ai_compliance_review.csv", mime="text/csv", use_container_width=True, key="download_v9_compliance_csv")
    with exv9b:
        st.download_button("⬇️ Label Evidence CSV", data=rows_to_csv(label_evidence_rows if "label_evidence_rows" in locals() else []), file_name="foodreg_ai_label_evidence.csv", mime="text/csv", use_container_width=True, key="download_v9_label_evidence_csv")
    history_csv_export=rows_to_csv(build_scan_history_rows(st.session_state.get("scan_history", [])))
    comparison_history_csv=rows_to_csv(history_compare_rows if "history_compare_rows" in locals() else [])
    hdl1,hdl2=st.columns(2)
    with hdl1:
        st.download_button("⬇️ Scan History CSV", data=history_csv_export, file_name="foodreg_ai_scan_history.csv", mime="text/csv", use_container_width=True, key="download_scan_history_csv")
    with hdl2:
        st.download_button("⬇️ Product Comparison CSV", data=comparison_history_csv, file_name="foodreg_ai_product_comparison.csv", mime="text/csv", use_container_width=True, key="download_product_comparison_csv")
    hdl3, hdl4 = st.columns(2)
    with hdl3:
        st.download_button("⬇️ Product Library CSV", data=rows_to_csv(product_library_rows), file_name="foodreg_ai_product_library.csv", mime="text/csv", use_container_width=True, key="download_product_library_csv")
    with hdl4:
        st.download_button("⬇️ Scan Delta CSV", data=rows_to_csv(scan_delta_rows), file_name="foodreg_ai_scan_delta.csv", mime="text/csv", use_container_width=True, key="download_scan_delta_csv")
    hdl5, hdl6 = st.columns(2)
    with hdl5:
        st.download_button("⬇️ Nutrition Review CSV", data=rows_to_csv(nutrition_review_rows), file_name="foodreg_ai_nutrition_review.csv", mime="text/csv", use_container_width=True, key="download_nutrition_review_csv")
    with hdl6:
        st.download_button("⬇️ Reviewer Status CSV", data=rows_to_csv(reviewer_status_rows), file_name="foodreg_ai_reviewer_status.csv", mime="text/csv", use_container_width=True, key="download_reviewer_status_csv")
    hdl7, hdl8 = st.columns(2)
    with hdl7:
        st.download_button("⬇️ Smart Review CSV", data=rows_to_csv(review_center_rows), file_name="foodreg_ai_smart_review_center.csv", mime="text/csv", use_container_width=True, key="download_smart_review_center_csv")
    with hdl8:
        st.download_button("⬇️ Data Quality CSV", data=rows_to_csv(label_quality["checks"]), file_name="foodreg_ai_label_data_quality.csv", mime="text/csv", use_container_width=True, key="download_label_data_quality_csv")
    ep1, ep2 = st.columns(2)
    with ep1:
        st.download_button("⬇️ Evidence Gap CSV", data=rows_to_csv(evidence_gap_rows), file_name="foodreg_ai_evidence_gap_action_plan.csv", mime="text/csv", use_container_width=True, key="download_evidence_gap_csv")
    with ep2:
        st.download_button("⬇️ Source Link CSV", data=rows_to_csv(source_hub_rows), file_name="foodreg_ai_source_link_hub.csv", mime="text/csv", use_container_width=True, key="download_source_link_hub_csv")
    st.download_button("⬇️ Scan Manifest JSON", data=json.dumps(scan_manifest, indent=2), file_name="foodreg_ai_scan_manifest.json", mime="application/json", use_container_width=True, key="download_scan_manifest_export")
    st.download_button("⬇️ Reviewer Handoff TXT", data=reviewer_handoff_text, file_name="foodreg_ai_reviewer_handoff.txt", mime="text/plain", use_container_width=True, key="download_v13_reviewer_handoff_export")
    v14e1, v14e2, v14e3, v14e4 = st.columns(4)
    with v14e1:
        st.download_button("⬇️ Duplicate Check CSV", data=rows_to_csv(duplicate_ingredient_rows), file_name="foodreg_ai_duplicate_ingredient_check.csv", mime="text/csv", use_container_width=True, key="download_v14_duplicate_csv")
    with v14e2:
        st.download_button("⬇️ Country Pair CSV", data=rows_to_csv(country_pair_diff_rows if "country_pair_diff_rows" in locals() else []), file_name="foodreg_ai_country_pair_difference.csv", mime="text/csv", use_container_width=True, key="download_v14_country_pair_csv")
    with v14e3:
        st.download_button("⬇️ Evidence Grade CSV", data=rows_to_csv(ingredient_evidence_grade_rows), file_name="foodreg_ai_ingredient_evidence_grade.csv", mime="text/csv", use_container_width=True, key="download_v14_evidence_grade_csv")
    with v14e4:
        st.download_button("⬇️ Review Sign-off TXT", data=reviewer_signoff_text, file_name="foodreg_ai_reviewer_signoff.txt", mime="text/plain", use_container_width=True, key="download_v14_reviewer_signoff_export")
    vd1,vd2,vd3=st.columns(3)
    with vd1:
        st.download_button("⬇️ Ingredient Relationship CSV",data=rows_to_csv(relationship_rows),file_name="foodreg_ai_ingredient_relationship.csv",mime="text/csv",use_container_width=True,key="download_v15_relationship_csv")
    with vd2:
        st.download_button("⬇️ Regulatory Watch CSV",data=rows_to_csv(regulatory_watch_rows),file_name="foodreg_ai_regulatory_change_watch.csv",mime="text/csv",use_container_width=True,key="download_v15_watch_csv")
    with vd3:
        st.download_button("⬇️ Final Summary JSON",data=json.dumps(final_summary_panel,indent=2,ensure_ascii=False),file_name="foodreg_ai_final_summary.json",mime="application/json",use_container_width=True,key="download_v15_final_summary_json")
    st.caption("Use Full Export ZIP when you want one download instead of downloading each report separately.")

    adv1, adv2 = st.columns(2)
    with adv1:
        st.download_button("⬇️ Regulatory Consistency CSV", data=rows_to_csv(regulatory_consistency_rows), file_name="foodreg_ai_regulatory_consistency_audit.csv", mime="text/csv", use_container_width=True, key="download_regulatory_consistency_csv")
    with adv2:
        st.download_button("⬇️ Alert Feed CSV", data=rows_to_csv(regulatory_alert_feed), file_name="foodreg_ai_priority_regulatory_alert_feed.csv", mime="text/csv", use_container_width=True, key="download_regulatory_alert_feed_csv")
    v13d1, v13d2, v13d3 = st.columns(3)
    with v13d1:
        st.download_button("⬇️ Claim Conflict CSV", data=rows_to_csv(claim_conflict_rows), file_name="foodreg_ai_claim_conflict_detector.csv", mime="text/csv", use_container_width=True, key="download_v13_claim_conflict_csv")
    with v13d2:
        st.download_button("⬇️ Regulatory Level CSV", data=rows_to_csv(level_filtered if "level_filtered" in locals() else regulatory_level_rows), file_name="foodreg_ai_regulatory_level_explorer.csv", mime="text/csv", use_container_width=True, key="download_v13_regulatory_level_csv")
    with v13d3:
        st.download_button("⬇️ Screening Matrix CSV", data=rows_to_csv(ingredient_screening_matrix), file_name="foodreg_ai_ingredient_screening_matrix.csv", mime="text/csv", use_container_width=True, key="download_v13_screening_matrix_csv")

    # =====================================================
    # COUNTRY-SPECIFIC ALERTS
    # =====================================================

    if country_alerts:
        st.markdown(
            '<div class="section-title">🚨 Country-Specific Alerts</div>',
            unsafe_allow_html=True,
        )
        st.caption(
            "These are jurisdiction-specific findings. A restriction in one country "
            "does not automatically mean the ingredient is prohibited everywhere."
        )
        st.dataframe(
            country_alerts,
            use_container_width=True,
            hide_index=True,
        )

    # =====================================================
    # REGULATORY RESULTS
    # =====================================================

    st.divider()


    st.markdown(

        '<div class="section-title">'

        "🌍 International Regulatory Check"

        "</div>",

        unsafe_allow_html=True,

    )


    st.caption(

        "A missing record means the ingredient is not yet "

        "covered by the project's current regulatory database. "

        "It does not mean the ingredient is automatically "

        "safe, approved, or unrestricted."

    )


    for item in regulatory_results:


        ingredient = item[

            "ingredient"

        ]


        record = item[

            "record"

        ]


        if not record.get(

            "found"

        ):

            ingredient_class = classify_ingredient(
                ingredient,
                record.get("ins") if isinstance(record, dict) else None,
            )

            if ingredient_class.get("type") == "ORDINARY_INGREDIENT":
                st.info(
                    f"ℹ️ **{ingredient.title()}** is classified as a food ingredient "
                    f"rather than a food additive. {ingredient_class.get('explanation', '')}"
                )
            else:
                st.info(
                    f"No regulatory record is currently available "
                    f"for **{ingredient.title()}**."
                )

            continue


        heading = (

            f"🧪 {ingredient.title()}"

        )


        if record.get("ins"):


            heading += (

                f" — INS {record['ins']}"

            )


        st.subheader(

            heading

        )


        jurisdictions = record.get(

            "jurisdictions",

            {},

        )


        for country, data in jurisdictions.items():


            status = data.get(

                "status",

                "UNKNOWN",

            )


            label = data.get(

                "label",

                "Status unavailable",

            )


            restriction = data.get(

                "restriction",

                "",

            )


            reason = data.get(

                "reason",

                "",

            )


            authority = data.get(

                "authority",

                "",

            )


            source = data.get(

                "source",

                "",

            )


            verified = data.get(

                "verified",

                "",

            )


            display_status = (

                get_status_display(

                    status

                )

            )


            with st.container(

                border=True

            ):


                st.markdown(

                    f"**🌍 {country}**"

                )


                st.write(

                    f"**Status:** "

                    f"{display_status}"

                )


                st.write(

                    f"**Regulatory information:** "

                    f"{label}"

                )


                if restriction:


                    st.write(

                        f"**Restriction / condition:** "

                        f"{restriction}"

                    )


                if reason:


                    st.write(

                        f"**Reason / regulatory basis:** "

                        f"{reason}"

                    )


                if authority:


                    st.write(

                        f"**Authority:** "

                        f"{authority}"

                    )


                if verified:


                    st.caption(

                        f"Last verified: {verified}"

                    )

                data_status=str(data.get("data_status", "") or "").strip()
                source_type=str(data.get("source_type", "") or "").strip()
                if data_status or source_type:
                    meta_parts=[]
                    if data_status: meta_parts.append(f"Data status: {data_status}")
                    if source_type: meta_parts.append(f"Source type: {source_type}")
                    st.caption(" · ".join(meta_parts))


                if is_valid_url(

                    source

                ):


                    st.markdown(

                        f"[🔗 View official source]({source})"

                    )


        st.divider()


    # =====================================================

    # TECHNICAL DETAILS

    # =====================================================


    with st.expander(

        "⚙️ View technical details"

    ):


        st.write(

            "Raw OCR text:"

        )


        st.text_area(

            "OCR output",

            full_text,

            height=180,

            key="raw_ocr_output",

        )


        st.write(

            "Detected ingredient section:"

        )


        st.text_area(

            "Ingredient section",

            ingredient_section,

            height=180,

            key="ingredient_section_output",

        )


        st.write(

            "Parsed ingredient entries:"

        )


        st.text_area(

            "Parsed ingredients",

            "\n".join(ingredients),

            height=180,

            key="parsed_ingredients_output",

        )


        st.write(

            "Normalization details:"

        )


        for item in normalized_results:


            validation = item.get(

                "validation",

                {},

            )


            text_correction = item.get(

                "text_correction",

                {},

            )


            st.write(

                f"**{item.get('original', '')}** → "

                f"{item.get('canonical', '')} "

                f"| Additive: "

                f"{validation.get('status', 'NO_CODE')} "

                f"| Text changed: "

                f"{text_correction.get('changed', False)}"

            )


    st.success(

        "Analysis complete. Regulatory findings are based "

        "only on records currently present in the FoodReg AI database."

    )