import sqlite3

DB_PATH = "foodreg.db"
TODAY = "2026-10-04"

# Saudi Arabia's food-additive framework.
# SFDA identifies SFDA.FD 2500 / SFDA.FD-GSO 2500 as the
# regulation for additives permitted for use in foodstuffs.
SOURCE_URL = (
    "https://sfda.gov.sa/en/faq/how-do-i-know-permitted-food-additives"
)

ADDITIVE_STANDARD_URL = (
    "https://www.sfda.gov.sa/sites/default/files/2019-06/"
    "AdditivesPermittedUseFoodStuffs.pdf"
)

SOURCE_DOCUMENT = (
    "SFDA.FD/GSO 2500 — Additives Permitted for Use in Food Stuffs"
)

# These six additives are relevant to the current Maggi test dataset.
# Status is intentionally CHECK_CONDITIONS because Saudi/GSO rules
# depend on the exact food category and permitted level/use.
RECORDS = [
    {
        "ingredient": "citric acid",
        "label": (
            "Citric Acid (INS 330) is included in the Saudi/GCC "
            "food-additive regulatory framework."
        ),
        "restriction": (
            "Condition type: food-category-specific / GMP check. "
            "Confirm the applicable food category and maximum level "
            "in SFDA.FD/GSO 2500 before concluding compliance."
        ),
    },
    {
        "ingredient": "guar gum",
        "label": (
            "Guar Gum (INS 412) is included in the Saudi/GCC "
            "food-additive regulatory framework."
        ),
        "restriction": (
            "Condition type: food-category-specific / GMP check. "
            "Confirm the applicable food category and permitted "
            "level in SFDA.FD/GSO 2500."
        ),
    },
    {
        "ingredient": "potassium chloride",
        "label": (
            "Potassium Chloride (INS 508) is included in the "
            "Saudi/GCC food-additive regulatory framework."
        ),
        "restriction": (
            "Condition type: food-category-specific use check. "
            "The permitted level/use depends on the food category "
            "and applicable notes in SFDA.FD/GSO 2500."
        ),
    },
    {
        "ingredient": "sodium carbonate",
        "label": (
            "Sodium Carbonate (INS 500(i)) is included in the "
            "Saudi/GCC food-additive regulatory framework."
        ),
        "restriction": (
            "Condition type: food-category-specific use check. "
            "Confirm the applicable category and conditions in "
            "SFDA.FD/GSO 2500."
        ),
    },
    {
        "ingredient": "caramel iv",
        "label": (
            "Caramel IV / Sulfite Ammonia Caramel (INS 150d) is "
            "listed in the Saudi/GCC additive standard."
        ),
        "restriction": (
            "Condition type: colour + food-category maximum-level "
            "check. The applicable maximum level depends on the "
            "food category and notes in SFDA.FD/GSO 2500."
        ),
    },
    {
        "ingredient": "disodium 5'-ribonucleotides",
        "label": (
            "Disodium 5'-Ribonucleotides (INS 635) are included in "
            "the Saudi/GCC food-additive regulatory framework."
        ),
        "restriction": (
            "Condition type: flavour-enhancer / food-category-specific "
            "use check. Confirm the exact permitted level and food "
            "category in SFDA.FD/GSO 2500."
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
    name = "Saudi Arabia"

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
                "Saudi Arabia",
                "SA",
                "COUNTRY",
                "Saudi Food and Drug Authority (SFDA)",
                SOURCE_URL,
                ADDITIVE_STANDARD_URL,
                "VERIFIED_SOURCE",
                12,
                (
                    "SFDA identifies SFDA.FD 2500 / SFDA.FD-GSO 2500 "
                    "as the technical regulation for additives permitted "
                    "for use in foodstuffs. Exact permission depends on "
                    "food category, level and applicable notes."
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
                "SFDA.FD/GSO 2500 — Additives Permitted for Use "
                "in Food Stuffs."
            ),
            "Saudi Food and Drug Authority (SFDA)",
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

        print(f"✅ Saudi Arabia records added/updated: {added}")
        print(f"Saudi Arabia regulatory records in database: {total}")
        print(
            "ℹ️ Saudi Arabia records use CHECK_CONDITIONS because "
            "SFDA.FD/GSO 2500 permissions depend on food category/use."
        )

    finally:
        conn.close()


if __name__ == "__main__":
    main()
