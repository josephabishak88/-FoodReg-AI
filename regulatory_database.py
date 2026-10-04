import sqlite3
from pathlib import Path


DB_PATH = Path(__file__).with_name("foodreg.db")


def _table_columns(conn, table_name):
    rows = conn.execute(
        f"PRAGMA table_info({table_name})"
    ).fetchall()

    return {row[1] for row in rows}


def _ensure_legacy_ids(conn):
    """
    Older FoodReg databases may have an id column that contains NULL
    even though SQLite has a valid rowid. Backfill those IDs so joins
    continue to work.
    """
    for table in ("ingredients", "jurisdictions", "regulatory_records"):
        columns = _table_columns(conn, table)

        if "id" not in columns:
            continue

        try:
            conn.execute(
                f"UPDATE {table} SET id = rowid WHERE id IS NULL"
            )
        except sqlite3.OperationalError:
            pass

    conn.commit()


def _connect():
    if not DB_PATH.exists():
        raise FileNotFoundError(
            f"FoodReg database not found: {DB_PATH}"
        )

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    _ensure_legacy_ids(conn)

    return conn


def _find_ingredient(conn, canonical_name):
    """
    Find an ingredient by canonical name, case-insensitively.
    """
    row = conn.execute(
        """
        SELECT id, rowid, canonical_name, ins_code
        FROM ingredients
        WHERE LOWER(TRIM(canonical_name)) = LOWER(TRIM(?))
        LIMIT 1
        """,
        (canonical_name,),
    ).fetchone()

    return row


def _load_all_regulatory_rows(conn, ingredient_id):
    """
    Return every regulatory record stored for this ingredient.

    This intentionally does NOT restrict the result to a hard-coded
    country list. Any future country added to foodreg.db automatically
    becomes visible in the app.
    """
    return conn.execute(
        """
        SELECT
            rr.id AS record_id,
            rr.rowid AS record_rowid,
            rr.ingredient_id,
            rr.jurisdiction_id,
            rr.status,
            rr.label,
            rr.restriction,
            rr.reason,
            rr.food_category,
            rr.maximum_level,
            rr.unit,
            rr.conditions,
            rr.authority AS record_authority,
            rr.source_url,
            rr.source_document,
            rr.effective_date,
            rr.verified_date,
            rr.source_type,
            rr.notes AS record_notes,

            j.id AS jurisdiction_id_value,
            j.rowid AS jurisdiction_rowid,
            j.name AS jurisdiction_name,
            j.code AS jurisdiction_code,
            j.type AS jurisdiction_type,
            j.authority AS jurisdiction_authority,
            j.official_source,
            j.additive_source,
            j.data_status,
            j.priority,
            j.notes AS jurisdiction_notes

        FROM regulatory_records rr

        JOIN jurisdictions j
          ON (
              j.id = rr.jurisdiction_id
              OR j.rowid = rr.jurisdiction_id
          )

        WHERE (
            rr.ingredient_id = ?
            OR rr.ingredient_id IN (
                SELECT rowid
                FROM ingredients
                WHERE id = ?
            )
        )

        ORDER BY
            CASE
                WHEN j.priority IS NULL THEN 999999
                ELSE j.priority
            END,
            LOWER(j.name)
        """,
        (ingredient_id, ingredient_id),
    ).fetchall()


def _clean_value(value):
    if value is None:
        return ""
    return str(value).strip()


def check_ingredient(canonical_name):
    """
    Return all regulatory information currently stored for an ingredient.

    Return structure is compatible with the existing app.py:
        {
            "found": bool,
            "ingredient": str,
            "ins": str | None,
            "jurisdiction_count": int,
            "jurisdictions": {
                "India": {
                    "status": ...,
                    "label": ...,
                    "restriction": ...,
                    "reason": ...,
                    "food_category": ...,
                    "maximum_level": ...,
                    "unit": ...,
                    "conditions": ...,
                    "authority": ...,
                    "source": ...,
                    "source_document": ...,
                    "effective_date": ...,
                    "verified": ...,
                    "source_type": ...,
                    "notes": ...
                },
                ...
            }
        }
    """
    canonical_name = _clean_value(canonical_name)

    if not canonical_name:
        return {
            "found": False,
            "ingredient": "",
            "ins": None,
            "jurisdiction_count": 0,
            "jurisdictions": {},
        }

    conn = _connect()

    try:
        ingredient = _find_ingredient(
            conn,
            canonical_name,
        )

        if ingredient is None:
            return {
                "found": False,
                "ingredient": canonical_name,
                "ins": None,
                "jurisdiction_count": 0,
                "jurisdictions": {},
            }

        ingredient_id = ingredient["id"]

        if ingredient_id is None:
            ingredient_id = ingredient["rowid"]

        rows = _load_all_regulatory_rows(
            conn,
            ingredient_id,
        )

        jurisdictions = {}

        for row in rows:
            country = _clean_value(
                row["jurisdiction_name"]
            )

            if not country:
                continue

            # Keep the first record for a country. The database design
            # intends one ingredient + one jurisdiction record.
            if country in jurisdictions:
                continue

            # Prefer record-level authority, then jurisdiction authority.
            authority = _clean_value(
                row["record_authority"]
            ) or _clean_value(
                row["jurisdiction_authority"]
            )

            jurisdictions[country] = {
                "status": _clean_value(
                    row["status"]
                ) or "UNKNOWN",

                "label": _clean_value(
                    row["label"]
                ),

                "restriction": _clean_value(
                    row["restriction"]
                ),

                "reason": _clean_value(
                    row["reason"]
                ),

                "food_category": _clean_value(
                    row["food_category"]
                ),

                "maximum_level": _clean_value(
                    row["maximum_level"]
                ),

                "unit": _clean_value(
                    row["unit"]
                ),

                "conditions": _clean_value(
                    row["conditions"]
                ),

                "authority": authority,

                "source": (
                    _clean_value(row["source_url"])
                    or _clean_value(row["official_source"])
                ),

                "source_document": (
                    _clean_value(row["source_document"])
                ),

                "effective_date": (
                    _clean_value(row["effective_date"])
                ),

                "verified": (
                    _clean_value(row["verified_date"])
                ),

                "source_type": (
                    _clean_value(row["source_type"])
                ),

                "notes": (
                    _clean_value(row["record_notes"])
                    or _clean_value(row["jurisdiction_notes"])
                ),

                "jurisdiction_code": (
                    _clean_value(row["jurisdiction_code"])
                ),

                "jurisdiction_type": (
                    _clean_value(row["jurisdiction_type"])
                ),

                "data_status": (
                    _clean_value(row["data_status"])
                ),

                "priority": row["priority"],
            }

        return {
            "found": bool(jurisdictions),
            "ingredient": _clean_value(
                ingredient["canonical_name"]
            ) or canonical_name,
            "ins": _clean_value(
                ingredient["ins_code"]
            ) or None,
            "jurisdiction_count": len(jurisdictions),
            "jurisdictions": jurisdictions,
        }

    finally:
        conn.close()


def get_all_jurisdictions():
    """
    Useful for diagnostics and future UI filters.
    Returns every jurisdiction currently stored in foodreg.db.
    """
    conn = _connect()

    try:
        rows = conn.execute(
            """
            SELECT
                name,
                code,
                type,
                authority,
                official_source,
                data_status,
                priority
            FROM jurisdictions
            ORDER BY
                CASE
                    WHEN priority IS NULL THEN 999999
                    ELSE priority
                END,
                LOWER(name)
            """
        ).fetchall()

        return [
            {
                "name": _clean_value(row["name"]),
                "code": _clean_value(row["code"]),
                "type": _clean_value(row["type"]),
                "authority": _clean_value(row["authority"]),
                "official_source": _clean_value(
                    row["official_source"]
                ),
                "data_status": _clean_value(
                    row["data_status"]
                ),
                "priority": row["priority"],
            }
            for row in rows
        ]

    finally:
        conn.close()


def count_regulatory_records():
    """
    Diagnostic helper for checking that the country scripts populated
    the database.
    """
    conn = _connect()

    try:
        total = conn.execute(
            """
            SELECT COUNT(*)
            FROM regulatory_records
            """
        ).fetchone()[0]

        jurisdictions = conn.execute(
            """
            SELECT COUNT(*)
            FROM jurisdictions
            """
        ).fetchone()[0]

        ingredients = conn.execute(
            """
            SELECT COUNT(*)
            FROM ingredients
            """
        ).fetchone()[0]

        return {
            "ingredients": int(ingredients),
            "jurisdictions": int(jurisdictions),
            "regulatory_records": int(total),
        }

    finally:
        conn.close()


if __name__ == "__main__":
    try:
        stats = count_regulatory_records()
        print("FoodReg AI database")
        print(f"Ingredients: {stats['ingredients']}")
        print(f"Jurisdictions: {stats['jurisdictions']}")
        print(f"Regulatory records: {stats['regulatory_records']}")

        example = check_ingredient("citric acid")

        print(
            f"\nCitric acid regulatory records found: "
            f"{example['jurisdiction_count']}"
        )

        for country, data in example["jurisdictions"].items():
            print(
                f" - {country}: {data['status']}"
            )

    except Exception as exc:
        print(f"❌ Regulatory database check failed: {exc}")
