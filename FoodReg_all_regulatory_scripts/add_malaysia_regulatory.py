import sqlite3

DB_PATH = "foodreg.db"
TODAY = "2026-10-04"

SOURCE_URL = "https://hq.moh.gov.my/fsq/peraturanperaturan-makanan-1985"

SOURCE_DOCUMENT = (
    "Malaysia Food Regulations 1985 — Updated August 2026 "
    "(P.U.(A) 48/2026)"
)

RECORDS = [
    {
        "ingredient": "citric acid",
        "label": (
            "Citric Acid is regulated under Malaysia's Food "
            "Regulations 1985 food-additive framework."
        ),
        "restriction": (
            "Condition type: Malaysia food-category/use-standard check. "
            "Confirm the applicable schedule and permitted use for the "
            "specific food."
        ),
    },
    {
        "ingredient": "guar gum",
        "label": (
            "Guar Gum is covered by Malaysia's regulated food-additive "
            "framework."
        ),
        "restriction": (
            "Condition type: food-category/use-standard check. "
            "Confirm the applicable schedule and permitted level for "
            "the specific food."
        ),
    },
    {
        "ingredient": "potassium chloride",
        "label": (
            "Potassium Chloride is covered by Malaysia's regulated "
            "food-additive framework."
        ),
        "restriction": (
            "Condition type: food-category/use-standard check. "
            "Confirm the applicable schedule and permitted level for "
            "the specific food."
        ),
    },
    {
        "ingredient": "sodium carbonate",
        "label": (
            "Sodium Carbonate is covered by Malaysia's regulated "
            "food-additive framework."
        ),
        "restriction": (
            "Condition type: food-category/use-standard check. "
            "Confirm the applicable schedule and permitted level for "
            "the specific food."
        ),
    },
    {
        "ingredient": "caramel iv",
        "label": (
            "Caramel IV is handled within Malaysia's food-colour and "
            "food-additive regulatory framework."
        ),
        "restriction": (
            "Condition type: colour/use-standard check. Confirm the "
            "specific permitted colour class, food category and any "
            "applicable quantitative condition."
        ),
    },
    {
        "ingredient": "disodium 5'-ribonucleotides",
        "label": (
            "Disodium 5'-Ribonucleotides are handled within Malaysia's "
            "regulated food-additive framework."
        ),
        "restriction": (
            "Condition type: food-category/use-standard check. Confirm "
            "the applicable schedule and permitted level for the "
            "specific food."
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
    name = "Malaysia"

    row = conn.execute(
        """
        SELECT id, rowid
        FROM jurisdictions
        WHERE name = ?
        """,
        (name,),
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
                "Malaysia",
                "MY",
                "COUNTRY",
                "Ministry of Health Malaysia — Food Safety and Quality Division",
                SOURCE_URL,
                SOURCE_URL,
                "VERIFIED_SOURCE",
                11,
                (
                    "Malaysia regulates food additives under the Food "
                    "Regulations 1985. The Ministry of Health publishes "
                    "the current consolidated regulations and schedules. "
                    "Exact additive permission is food-category/use "
                    "dependent and must be checked against the applicable "
                    "schedule."
                ),
            ),
        )

        row = conn.execute(
            """
            SELECT id, rowid
            FROM jurisdictions
            WHERE name = ?
            """,
            (name,),
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
            f"Ingredient '{canonical_name}' is not present in foodreg.db"
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
            (
                "Malaysia Food Regulations 1985 — current consolidated "
                "regulatory framework."
            ),
            "Ministry of Health Malaysia — Food Safety and Quality Division",
            SOURCE_URL,
            SOURCE_DOCUMENT,
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
            ensure_column(conn, "jurisdictions", column, sql_type)

        for column, sql_type in [
            ("source_document", "TEXT"),
            ("verified_date", "TEXT"),
            ("source_type", "TEXT"),
        ]:
            ensure_column(conn, "regulatory_records", column, sql_type)

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

        print(f"✅ Malaysia records added/updated: {added}")
        print(f"Malaysia regulatory records in database: {total}")
        print(
            "ℹ️ Malaysia records use CHECK_CONDITIONS because "
            "Food Regulations 1985 permissions depend on food category/use."
        )

    finally:
        conn.close()


if __name__ == "__main__":
    main()
