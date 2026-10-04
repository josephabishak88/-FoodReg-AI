import sqlite3

DB_PATH = "foodreg.db"
TODAY = "2026-10-04"

SOURCE_URL = (
    "https://www.fao.org/fao-who-codexalimentarius/"
    "codex-texts/dbs/gsfa/en/"
)

SOURCE_DOCUMENT = (
    "Codex General Standard for Food Additives (GSFA) "
    "CXS 192-1995 — Online Database"
)

RECORDS = [
    {
        "ingredient": "caramel iv",
        "label": (
            "Codex GSFA lists Caramel IV - sulfite ammonia caramel "
            "(INS 150d) with food-category-specific provisions."
        ),
        "restriction": (
            "Condition type: food-category specific / maximum level. "
            "The permitted level and notes vary by food category; "
            "for example, the GSFA database shows category-specific "
            "mg/kg limits and use notes."
        ),
        "reason": (
            "Codex GSFA Online Database. Searchable by additive name "
            "and INS number; category entries include maximum levels "
            "and notes for INS 150d."
        ),
    },
    {
        "ingredient": "citric acid",
        "label": (
            "Codex GSFA lists Citric acid (INS 330) with provisions "
            "that vary by food category."
        ),
        "restriction": (
            "Condition type: food-category specific. Some category "
            "entries use GMP/quantum-satis style provisions, while "
            "others have specific notes or limits."
        ),
        "reason": (
            "Codex GSFA Online Database contains INS 330 entries "
            "for multiple food categories."
        ),
    },
    {
        "ingredient": "guar gum",
        "label": (
            "Codex GSFA lists Guar gum (INS 412) with category-specific "
            "provisions; GMP is used in applicable GSFA tables."
        ),
        "restriction": (
            "Condition type: GMP / food-category specific. The applicable "
            "food category determines the GSFA provision."
        ),
        "reason": (
            "Codex GSFA Online Database includes INS 412 and "
            "category-specific provisions."
        ),
    },
    {
        "ingredient": "potassium chloride",
        "label": (
            "Codex GSFA lists Potassium chloride (INS 508) with "
            "food-category-specific provisions."
        ),
        "restriction": (
            "Condition type: food-category specific. The relevant "
            "Codex food category and associated provision must be checked."
        ),
        "reason": (
            "Codex GSFA Online Database includes INS 508 and its "
            "associated Codex food-category references."
        ),
    },
    {
        "ingredient": "sodium carbonate",
        "label": (
            "Codex GSFA lists Sodium carbonate (INS 500(i)) with "
            "food-category-specific provisions."
        ),
        "restriction": (
            "Condition type: food-category specific. Applicable "
            "food-category provisions and any maximum levels or notes "
            "must be checked."
        ),
        "reason": (
            "Codex GSFA Online Database includes INS 500(i) Sodium carbonate."
        ),
    },
    {
        "ingredient": "disodium 5'-ribonucleotides",
        "label": (
            "Codex GSFA lists Disodium 5'-ribonucleotides (INS 635) "
            "with food-category-specific provisions."
        ),
        "restriction": (
            "Condition type: food-category specific. Certain categories "
            "show specific use notes; the applicable food category must "
            "be checked before drawing a conclusion."
        ),
        "reason": (
            "Codex GSFA Online Database includes INS 635 with "
            "category-specific entries and notes."
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
    name = "Codex GSFA"

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
                name,
                "CODEX",
                "INTERNATIONAL_REFERENCE",
                "Codex Alimentarius Commission / FAO-WHO",
                SOURCE_URL,
                SOURCE_URL,
                "VERIFIED_SOURCE",
                1,
                (
                    "International reference only. Codex GSFA is not "
                    "national law and should not be presented as a "
                    "country's legal approval."
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
            f"Ingredient '{canonical_name}' is not present "
            "in foodreg.db"
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
            "Codex Alimentarius Commission / FAO-WHO",
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
            f"✅ Codex GSFA records added/updated: {added}"
        )
        print(
            f"Codex GSFA regulatory records in database: {total}"
        )
        print(
            "ℹ️ Codex is stored as an international reference, "
            "not as a country."
        )

    finally:
        conn.close()


if __name__ == "__main__":
    main()
