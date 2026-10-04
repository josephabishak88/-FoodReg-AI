import sqlite3

DB_PATH = "foodreg.db"
TODAY = "2026-10-04"

SOURCE_URL = (
    "https://food.ec.europa.eu/food-safety/"
    "food-improvement-agents/additives/database_en"
)

SOURCE_DOCUMENT = (
    "European Commission Food Additives Database / "
    "Regulation (EC) No 1333/2008, Annex II"
)

RECORDS = [
    {
        "ingredient": "citric acid",
        "ins": "330",
        "label": (
            "EU Union list includes Citric acid (E330) as an authorised "
            "food additive; conditions of use depend on the food category."
        ),
        "restriction": (
            "Use is subject to the category-specific conditions and maximum "
            "levels in Annex II of Regulation (EC) No 1333/2008."
        ),
        "reason": (
            "European Commission additives database and Annex II "
            "of Regulation (EC) No 1333/2008."
        ),
    },
    {
        "ingredient": "guar gum",
        "ins": "412",
        "label": (
            "EU Union list includes Guar gum (E412) as an authorised "
            "food additive; the Union list specifies conditions of use."
        ),
        "restriction": (
            "Use is subject to the food-category conditions and footnotes "
            "in Annex II; the Union list includes quantum satis entries "
            "for applicable categories."
        ),
        "reason": (
            "European Commission additives database and Annex II "
            "of Regulation (EC) No 1333/2008."
        ),
    },
    {
        "ingredient": "potassium chloride",
        "ins": "508",
        "label": (
            "EU Union list includes Potassium chloride (E508) as an "
            "authorised food additive in applicable food categories."
        ),
        "restriction": (
            "The permitted use and level depend on the relevant food "
            "category and conditions in Annex II."
        ),
        "reason": (
            "European Commission additives database and Annex II "
            "of Regulation (EC) No 1333/2008."
        ),
    },
    {
        "ingredient": "sodium carbonate",
        "ins": "500",
        "label": (
            "EU Union list includes Sodium carbonates (E500) as an "
            "authorised food additive in applicable categories."
        ),
        "restriction": (
            "Use is category-specific. Annex II contains food-category "
            "conditions, including uses where E500 is permitted quantum satis "
            "or subject to specific restrictions."
        ),
        "reason": (
            "European Commission additives database and Annex II "
            "of Regulation (EC) No 1333/2008."
        ),
    },
    {
        "ingredient": "caramel iv",
        "ins": "150d",
        "label": (
            "EU Union list includes Sulphite ammonia caramel (E150d), "
            "Caramel IV, as a permitted food colour."
        ),
        "restriction": (
            "Use is subject to the food-category conditions and colour "
            "requirements in Annex II; E150d is listed among authorised "
            "food colours."
        ),
        "reason": (
            "European Commission additives database and Annex II "
            "of Regulation (EC) No 1333/2008."
        ),
    },
    {
        "ingredient": "disodium 5'-ribonucleotides",
        "ins": "635",
        "label": (
            "EU Union list includes Disodium 5'-ribonucleotides (E635) "
            "as an authorised food additive in applicable categories."
        ),
        "restriction": (
            "Use is subject to the applicable food-category conditions "
            "and maximum levels in Annex II."
        ),
        "reason": (
            "European Commission additives database and Annex II "
            "of Regulation (EC) No 1333/2008."
        ),
    },
]


def columns(conn, table):
    return {
        row[1]
        for row in conn.execute(
            f"PRAGMA table_info({table})"
        ).fetchall()
    }


def ensure_column(conn, table, column, sql_type):
    if column not in columns(conn, table):
        conn.execute(
            f"ALTER TABLE {table} ADD COLUMN "
            f"{column} {sql_type}"
        )


def get_or_create_jurisdiction(conn):
    name = "European Union"

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
            (name, code, type, authority,
             official_source, additive_source,
             data_status, priority, notes)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                name,
                "EU",
                "REGIONAL",
                "European Commission",
                SOURCE_URL,
                SOURCE_URL,
                "VERIFIED_SOURCE",
                2,
                (
                    "European Union food-additive information is based "
                    "on the Union list in Annex II of Regulation (EC) "
                    "No 1333/2008."
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
            "in the ingredients table."
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
            "European Commission",
            SOURCE_URL,
            SOURCE_DOCUMENT,
            TODAY,
            "OFFICIAL_REFERENCE",
        ),
    )


def main():
    conn = sqlite3.connect(DB_PATH)

    try:
        ensure_column(
            conn, "jurisdictions", "code", "TEXT"
        )
        ensure_column(
            conn, "jurisdictions", "type", "TEXT"
        )
        ensure_column(
            conn, "jurisdictions", "authority", "TEXT"
        )
        ensure_column(
            conn, "jurisdictions",
            "official_source", "TEXT"
        )
        ensure_column(
            conn, "jurisdictions",
            "additive_source", "TEXT"
        )
        ensure_column(
            conn, "jurisdictions",
            "data_status", "TEXT"
        )
        ensure_column(
            conn, "jurisdictions",
            "priority", "INTEGER"
        )
        ensure_column(
            conn, "jurisdictions", "notes", "TEXT"
        )

        ensure_column(
            conn, "regulatory_records",
            "source_document", "TEXT"
        )
        ensure_column(
            conn, "regulatory_records",
            "verified_date", "TEXT"
        )
        ensure_column(
            conn, "regulatory_records",
            "source_type", "TEXT"
        )

        jurisdiction_id = get_or_create_jurisdiction(
            conn
        )

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
            f"✅ European Union records added/updated: {added}"
        )
        print(
            f"European Union regulatory records in database: {total}"
        )

    finally:
        conn.close()


if __name__ == "__main__":
    main()
