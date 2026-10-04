from __future__ import annotations

import importlib
import py_compile
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parent

REQUIRED_FILES = [
    "app.py",
    "foodreg.db",
    "ingredient_normalizer.py",
    "regulatory_database.py",
    "regulatory_update_engine.py",
    "regulatory_document_intelligence.py",
]

OPTIONAL_MODULES = [
    "streamlit",
    "cv2",
    "numpy",
    "PIL",
    "paddleocr",
    "rapidfuzz",
    "fitz",
    "pypdf",
]

CORE_TABLES = [
    "ingredients",
    "ingredient_aliases",
    "jurisdictions",
    "regulatory_records",
]

UPDATE_TABLES = [
    "regulatory_source_registry",
    "regulatory_source_snapshots",
    "regulatory_update_runs",
    "regulatory_change_events",
    "regulatory_document_proposals",
    "regulatory_record_versions",
]


def fail(msg: str) -> None:
    print(f"FAIL: {msg}")


def main() -> int:
    ok = True

    print("FoodReg AI release health check")
    print(f"Project: {ROOT}")

    for name in REQUIRED_FILES:
        path = ROOT / name
        if path.exists():
            print(f"PASS: {name}")
        else:
            fail(f"missing {name}")
            ok = False

    for name in ["app.py", "regulatory_update_engine.py", "regulatory_document_intelligence.py"]:
        path = ROOT / name
        if path.exists():
            try:
                py_compile.compile(str(path), doraise=True)
                print(f"PASS: syntax {name}")
            except Exception as exc:
                fail(f"syntax {name}: {exc}")
                ok = False

    db_path = ROOT / "foodreg.db"
    if db_path.exists():
        try:
            with sqlite3.connect(db_path) as conn:
                names = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
                for table in CORE_TABLES:
                    if table in names:
                        print(f"PASS: DB table {table}")
                    else:
                        fail(f"missing DB table {table}")
                        ok = False
                # Update tables are created by the V18 updater and are safe to add.
                try:
                    import regulatory_update_engine as updater
                    updater.DB_PATH = db_path
                    updater.ensure_update_schema()
                    with sqlite3.connect(db_path) as check_conn:
                        names = {r[0] for r in check_conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
                    for table in UPDATE_TABLES:
                        if table in names:
                            print(f"PASS: updater table {table}")
                        else:
                            fail(f"updater table not available: {table}")
                            ok = False
                except Exception as exc:
                    fail(f"updater schema check: {exc}")
                    ok = False

                with sqlite3.connect(db_path) as stats:
                    ingredients = stats.execute("SELECT COUNT(*) FROM ingredients").fetchone()[0]
                    records = stats.execute("SELECT COUNT(*) FROM regulatory_records").fetchone()[0]
                    jurisdictions = stats.execute("SELECT COUNT(*) FROM jurisdictions").fetchone()[0]
                print(f"INFO: {ingredients} ingredients, {records} regulatory records, {jurisdictions} jurisdictions")
        except Exception as exc:
            fail(f"database check: {exc}")
            ok = False

    print("\nDependency check:")
    for module in OPTIONAL_MODULES:
        try:
            importlib.import_module(module)
            print(f"PASS: {module}")
        except Exception as exc:
            print(f"WARN: {module} -> {exc}")

    if ok:
        print("\nRELEASE CHECK: PASS")
        return 0
    print("\nRELEASE CHECK: FAIL")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
