import sqlite3

DB_PATH = "foodreg.db"
TODAY = "2026-10-04"

SOURCE_URL = (
    "https://data.food.gov.uk/regulated-products/"
    "food_authorisations"
)

SOURCE_DOCUMENT = (
    "Food Standards Agency — Register of Food Additive Authorisations "
    "for Great Britain"
)

RECORDS = [
    {
        "ingredient": "citric acid",
        "label": (
            "FSA Register lists Citric acid (E330) as Authorised in "
            "England, Scotland and Wales."
        ),
        "restriction": (
            "Condition type: food-category specific. Terms of authorisation "
            "refer to the assimilated Regulation (EC) No. 1333/2008, "
            "Annex II and Annex III."
        ),
        "reason": (
            "FSA Register of Food Additive Authorisations, E330."
        ),
    },
    {
        "ingredient": "guar gum",
        "label": (
            "FSA Register lists Guar gum (E412) as Authorised in "
            "England, Scotland and Wales."
        ),
        "restriction": (
            "Condition type: food-category specific. The GB register "
            "points to the assimilated food-additives legislation for "
            "the applicable conditions of use."
        ),
        "reason": (
            "FSA Register of Food Additive Authorisations, E412."
        ),
    },
    {
        "ingredient": "potassium chloride",
        "label": (
            "FSA Register lists Potassium chloride (E508) as Authorised "
            "in England, Scotland and Wales."
        ),
        "restriction": (
            "Condition type: food-category specific. The applicable "
            "conditions of use are set through the assimilated "
            "Regulation (EC) No. 1333/2008 framework."
        ),
        "reason": (
            "FSA Register of Food Additive Authorisations, E508."
        ),
    },
    {
        "ingredient": "sodium carbonate",
        "label": (
            "FSA Register lists Sodium carbonates (E500) as Authorised "
            "in England, Scotland and Wales."
        ),
        "restriction": (
            "Condition type: food-category specific. Applicable use "
            "conditions are set through the assimilated food-additives "
            "legislation."
        ),
        "reason": (
            "FSA Register of Food Additive Authorisations, E500."
        ),
    },
    {
        "ingredient": "caramel iv",
        "label": (
            "FSA Register lists Sulphite ammonia caramel (E150d) as "
            "Authorised in England, Scotland and Wales."
        ),
        "restriction": (
            "Condition type: quantum satis / food-category specific. "
            "The register identifies E150d in Group II, food colours "
            "authorised at quantum satis, with use conditions linked "
            "to Annex II and Annex III."
        ),
        "reason": (
            "FSA Register of Food Additive Authorisations, E150d."
        ),
    },
    {
        "ingredient": "disodium 5'-ribonucleotides",
        "label": (
            "FSA Register lists Disodium 5'-ribonucleotides (E635) as "
            "Authorised in England, Scotland and Wales."
        ),
        "restriction": (
            "Condition type: food-category specific. The GB register "
            "links the conditions of use to Annex II and Annex III "
            "of the assimilated food-additives regulation."
        ),
        "reason": (
            "FSA Register of Food Additive Authorisations, E635."
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
    name = "Great Britain"

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
                "GB",
                "REGION",
                "Food Standards Agency (FSA)",
                SOURCE_URL,
                SOURCE_URL,
                "VERIFIED_SOURCE",
                7,
                (
                    "Great Britain means England, Scotland and Wales. "
                    "Northern Ireland has a separate EU-law framework "
                    "for many food rules."
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
            "AUTHORISED",
            item["label"],
            item["restriction"],
            item["reason"],
            "Food Standards Agency (FSA)",
            SOURCE_URL,
            SOURCE_DOCUMENT,
            TODAY,
            "OFFICIAL_REGISTER",
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
            f"✅ Great Britain records added/updated: {added}"
        )
        print(
            f"Great Britain regulatory records in database: {total}"
        )

    finally:
        conn.close()


if __name__ == "__main__":
    main()
