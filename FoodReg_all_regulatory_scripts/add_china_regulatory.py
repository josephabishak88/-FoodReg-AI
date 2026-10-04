import sqlite3

DB_PATH = "foodreg.db"
TODAY = "2026-10-04"

# Official publication of China's current food-additive use standard.
SOURCE_URL = (
    "https://www.nhc.gov.cn/sps/c100088/202403/"
    "bda120e678df4a49a8beb90852559d7c.shtml"
)

SOURCE_DOCUMENT = (
    "GB 2760-2024 — Food Safety National Standard: "
    "Standards for the Use of Food Additives"
)

# Exact additive entries were cross-checked against current GB 2760-2024
# searchable database mirrors for INS/CNS identity and use-framework.
# The official NHC publication remains the primary regulatory source.
#
# We intentionally use CHECK_CONDITIONS rather than blanket AUTHORIZED,
# because GB 2760-2024 permissions are food-category/use specific.
RECORDS = [
    {
        "ingredient": "citric acid",
        "label": (
            "Citric Acid is covered by China's GB 2760-2024 "
            "food-additive use standard."
        ),
        "restriction": (
            "Condition type: food-category-specific use standard. "
            "Check the Chinese food category and permitted maximum "
            "use level before concluding compliance."
        ),
        "reason": (
            "GB 2760-2024, current national food-safety standard "
            "for food-additive use."
        ),
    },
    {
        "ingredient": "guar gum",
        "label": (
            "Guar Gum (INS 412 / CNS 20.025) appears in the current "
            "GB 2760-2024 additive-use framework."
        ),
        "restriction": (
            "Condition type: food-category-specific / quantum-satis "
            "where the standard specifies it, with category-specific "
            "exceptions and maximum levels. Confirm the product category."
        ),
        "reason": (
            "GB 2760-2024; current entry identifies Guar Gum as INS 412."
        ),
    },
    {
        "ingredient": "potassium chloride",
        "label": (
            "Potassium Chloride is covered by China's current "
            "food-additive use standard."
        ),
        "restriction": (
            "Condition type: food-category-specific use standard. "
            "The exact permitted use and maximum level depend on the "
            "Chinese food category."
        ),
        "reason": (
            "GB 2760-2024, current national food-safety standard "
            "for food-additive use."
        ),
    },
    {
        "ingredient": "sodium carbonate",
        "label": (
            "Sodium Carbonate is covered by China's current "
            "food-additive use standard."
        ),
        "restriction": (
            "Condition type: food-category-specific use standard. "
            "Confirm the exact Chinese food category and permitted use."
        ),
        "reason": (
            "GB 2760-2024, current national food-safety standard "
            "for food-additive use."
        ),
    },
    {
        "ingredient": "caramel iv",
        "label": (
            "Caramel Colour Class IV (INS 150d) is specifically listed "
            "in the GB 2760-2024 framework."
        ),
        "restriction": (
            "Condition type: category-specific maximum level / "
            "quantum-satis depending on the listed food category. "
            "For example, the current standard contains food-category "
            "entries with specified g/kg levels as well as entries "
            "using production-need limits."
        ),
        "reason": (
            "GB 2760-2024; INS 150d is identified as "
            "Caramel Colour Class IV."
        ),
    },
    {
        "ingredient": "disodium 5'-ribonucleotides",
        "label": (
            "Disodium 5'-Ribonucleotide (INS 635 / CNS 12.004) is "
            "listed in current GB 2760-2024 additive data."
        ),
        "restriction": (
            "Condition type: food-category-specific use standard. "
            "The exact permitted level and use must be matched to "
            "the Chinese food category."
        ),
        "reason": (
            "GB 2760-2024; current additive data identifies "
            "Disodium 5'-Ribonucleotide as INS 635."
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
    name = "China"

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
                "China",
                "CN",
                "COUNTRY",
                "National Health Commission (NHC) / State Administration for Market Regulation (SAMR)",
                SOURCE_URL,
                SOURCE_URL,
                "VERIFIED_SOURCE",
                10,
                (
                    "GB 2760-2024 is China's current food-additive "
                    "use standard. Exact permission is food-category "
                    "and use dependent; the NHC official publication "
                    "is the primary source."
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
            item["reason"],
            "National Health Commission (NHC) / State Administration for Market Regulation (SAMR)",
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

        print(f"✅ China records added/updated: {added}")
        print(f"China regulatory records in database: {total}")
        print(
            "ℹ️ China records use CHECK_CONDITIONS because "
            "GB 2760-2024 permissions depend on food category/use."
        )

    finally:
        conn.close()


if __name__ == "__main__":
    main()
