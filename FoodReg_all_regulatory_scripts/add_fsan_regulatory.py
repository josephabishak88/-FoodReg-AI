import sqlite3

DB_PATH = "foodreg.db"
TODAY = "2026-10-04"

FSANZ_SOURCE = (
    "https://www.foodstandards.gov.au/food-standards-code"
)

FSANZ_DOCUMENT = (
    "Australia New Zealand Food Standards Code — "
    "Schedule 15 / Schedule 8"
)

RECORDS = [
    {
        "ingredient": "caramel iv",
        "label": (
            "FSANZ lists Caramel IV (INS 150d) as a food additive; "
            "the Code gives GMP for the listed permission."
        ),
        "restriction": (
            "Condition type: GMP. Use must comply with the applicable "
            "food-category permissions and the Food Standards Code."
        ),
        "reason": (
            "Food Standards Code Schedule 15 lists Caramel IV — "
            "ammonia sulphite process (INS 150d) with GMP."
        ),
    },
    {
        "ingredient": "citric acid",
        "label": (
            "FSANZ lists Citric acid (INS 330) as a permitted additive; "
            "the applicable Schedule entries use GMP where specified."
        ),
        "restriction": (
            "Condition type: GMP / food-category specific. Exact "
            "permission depends on the relevant food category in the Code."
        ),
        "reason": (
            "Food Standards Code additive permissions identify Citric "
            "acid as INS 330; applicable permissions and conditions "
            "are category-specific."
        ),
    },
    {
        "ingredient": "guar gum",
        "label": (
            "FSANZ lists Guar gum (INS 412). The 2026 FSANZ supporting "
            "material shows a GMP permission in the Australia New Zealand "
            "Food Standards Code and category-specific MPL examples."
        ),
        "restriction": (
            "Condition type: GMP / food-category MPL. Some categories "
            "may use GMP while specific foods can have numerical limits."
        ),
        "reason": (
            "FSANZ 2026 supporting material identifies INS 412 Guar gum "
            "with GMP in the Code and shows category-specific limits "
            "in comparison tables."
        ),
    },
    {
        "ingredient": "potassium chloride",
        "label": (
            "FSANZ Schedule 8 identifies Potassium chloride as INS 508."
        ),
        "restriction": (
            "Condition type: food-category specific. The applicable "
            "Schedule 15 permission and any category-specific limits "
            "must be checked for the intended food."
        ),
        "reason": (
            "Food Standards Code Schedule 8 lists Potassium chloride "
            "under INS 508."
        ),
    },
    {
        "ingredient": "sodium carbonate",
        "label": (
            "FSANZ identifies sodium carbonate/sodium carbonates under "
            "the INS 500 group; permitted use depends on the relevant "
            "Food Standards Code permission."
        ),
        "restriction": (
            "Condition type: food-category specific. Check the applicable "
            "Schedule 15 entry, food category and any MPL/GMP condition."
        ),
        "reason": (
            "Food Standards Code additive schedules identify the INS 500 "
            "sodium-carbonates group."
        ),
    },
    {
        "ingredient": "disodium 5'-ribonucleotides",
        "label": (
            "FSANZ lists Disodium 5'-ribonucleotides (INS 635) as a "
            "flavour enhancer; current FSANZ supporting material shows "
            "GMP for the Australia New Zealand Food Standards Code."
        ),
        "restriction": (
            "Condition type: GMP / food-category specific. The applicable "
            "food-category permission must be checked in the Code."
        ),
        "reason": (
            "FSANZ 2026 supporting material lists INS 635 with GMP in "
            "the Australia New Zealand Food Standards Code."
        ),
    },
]


def ensure_column(conn, table, column, sql_type):
    cols = {
        row[1]
        for row in conn.execute(
            f"PRAGMA table_info({table})"
        ).fetchall()
    }

    if column not in cols:
        conn.execute(
            f"ALTER TABLE {table} ADD COLUMN {column} {sql_type}"
        )


def get_jurisdiction(conn):
    row = conn.execute(
        """
        SELECT id, rowid
        FROM jurisdictions
        WHERE name = 'Australia/New Zealand'
        """
    ).fetchone()

    if row is None:
        conn.execute(
            """
            INSERT INTO jurisdictions
            (
                name,
                code,
                type,
                authority,
                official_source,
                additive_source,
                data_status,
                priority,
                notes
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "Australia/New Zealand",
                "AU-NZ",
                "REGIONAL",
                "Food Standards Australia New Zealand (FSANZ)",
                FSANZ_SOURCE,
                FSANZ_SOURCE,
                "VERIFIED_SOURCE",
                5,
                (
                    "Official FSANZ Food Standards Code source. "
                    "Use and conditions are food-category specific."
                ),
            ),
        )

        row = conn.execute(
            """
            SELECT id, rowid
            FROM jurisdictions
            WHERE name = 'Australia/New Zealand'
            """
        ).fetchone()

    jurisdiction_id, rowid = row

    if jurisdiction_id is None:
        jurisdiction_id = rowid

        conn.execute(
            """
            UPDATE jurisdictions
            SET id = ?
            WHERE rowid = ?
            """,
            (jurisdiction_id, rowid),
        )

    return jurisdiction_id


def get_ingredient_id(conn, canonical_name):
    row = conn.execute(
        """
        SELECT id, rowid
        FROM ingredients
        WHERE canonical_name = ?
        """,
        (canonical_name,),
    ).fetchone()

    if row is None:
        raise RuntimeError(
            f"Ingredient '{canonical_name}' is not present "
            "in the current database."
        )

    ingredient_id, rowid = row

    if ingredient_id is None:
        ingredient_id = rowid

        conn.execute(
            """
            UPDATE ingredients
            SET id = ?
            WHERE rowid = ?
            """,
            (ingredient_id, rowid),
        )

    return ingredient_id


def upsert_record(conn, ingredient_id, jurisdiction_id, item):
    conn.execute(
        """
        INSERT INTO regulatory_records
        (
            ingredient_id,
            jurisdiction_id,
            status,
            label,
            restriction,
            reason,
            authority,
            source_url,
            source_document,
            verified_date,
            source_type
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(ingredient_id, jurisdiction_id)
        DO UPDATE SET
            status = excluded.status,
            label = excluded.label,
            restriction = excluded.restriction,
            reason = excluded.reason,
            authority = excluded.authority,
            source_url = excluded.source_url,
            source_document = excluded.source_document,
            verified_date = excluded.verified_date,
            source_type = excluded.source_type
        """,
        (
            ingredient_id,
            jurisdiction_id,
            "CHECK_CONDITIONS",
            item["label"],
            item["restriction"],
            item["reason"],
            "Food Standards Australia New Zealand (FSANZ)",
            FSANZ_SOURCE,
            FSANZ_DOCUMENT,
            TODAY,
            "OFFICIAL_REFERENCE",
        ),
    )


def main():
    conn = sqlite3.connect(DB_PATH)

    try:
        for column, sql_type in [
            ("code", "TEXT"),
            ("type", "TEXT"),
            ("authority", "TEXT"),
            ("official_source", "TEXT"),
            ("additive_source", "TEXT"),
            ("data_status", "TEXT"),
            ("priority", "INTEGER"),
            ("notes", "TEXT"),
        ]:
            ensure_column(
                conn,
                "jurisdictions",
                column,
                sql_type,
            )

        for column, sql_type in [
            ("source_document", "TEXT"),
            ("verified_date", "TEXT"),
            ("source_type", "TEXT"),
        ]:
            ensure_column(
                conn,
                "regulatory_records",
                column,
                sql_type,
            )

        jurisdiction_id = get_jurisdiction(conn)

        added = 0

        for item in RECORDS:
            ingredient_id = get_ingredient_id(
                conn,
                item["ingredient"],
            )

            upsert_record(
                conn,
                ingredient_id,
                jurisdiction_id,
                item,
            )

            added += 1

        conn.commit()

        total = conn.execute(
            """
            SELECT COUNT(*)
            FROM regulatory_records
            WHERE jurisdiction_id = ?
            """,
            (jurisdiction_id,),
        ).fetchone()[0]

        print(
            f"✅ Australia/New Zealand records added/updated: {added}"
        )
        print(
            "Australia/New Zealand regulatory records in database: "
            f"{total}"
        )

    finally:
        conn.close()


if __name__ == "__main__":
    main()
