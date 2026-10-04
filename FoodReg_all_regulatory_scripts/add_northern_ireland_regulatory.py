import sqlite3

DB_PATH = "foodreg.db"
TODAY = "2026-10-04"

SOURCE_URL = (
    "https://www.gov.uk/government/publications/"
    "approved-additives-and-e-numbers/"
    "approved-additives-and-e-numbers"
)

SOURCE_DOCUMENT = (
    "FSA Approved additives and E numbers — Northern Ireland"
)

RECORDS = [
    {
        "ingredient": "caramel iv",
        "label": (
            "FSA lists Sulphite ammonia caramel (E150d) as an approved "
            "additive for Northern Ireland."
        ),
        "restriction": (
            "Condition type: food-category specific. Northern Ireland "
            "uses Regulation (EU) 1333/2008 and its applicable amendments; "
            "most additives are only permitted in certain foods and may "
            "have quantitative limits."
        ),
        "reason": (
            "FSA Approved additives and E numbers guidance; "
            "Northern Ireland section applies Regulation (EU) 1333/2008 "
            "and Commission Regulation (EU) 2022/63."
        ),
    },
    {
        "ingredient": "citric acid",
        "label": (
            "FSA lists Citric acid (E330) as an approved food additive "
            "for Northern Ireland."
        ),
        "restriction": (
            "Condition type: food-category specific / quantitative limits. "
            "The FSA states additives must be checked against the applicable "
            "Northern Ireland legislation."
        ),
        "reason": (
            "FSA Approved additives and E numbers; E330 is listed under "
            "the 'Others' additive group."
        ),
    },
    {
        "ingredient": "guar gum",
        "label": (
            "FSA lists Guar gum (E412) as an approved emulsifier, "
            "stabiliser, thickener or gelling agent for Northern Ireland."
        ),
        "restriction": (
            "Condition type: food-category specific / quantitative limits. "
            "Use must follow the applicable food-category permissions "
            "and limits."
        ),
        "reason": (
            "FSA Approved additives and E numbers; E412 is listed "
            "under emulsifiers, stabilisers, thickeners and gelling agents."
        ),
    },
    {
        "ingredient": "potassium chloride",
        "label": (
            "FSA lists Potassium chloride (E508) as an approved food "
            "additive for Northern Ireland."
        ),
        "restriction": (
            "Condition type: food-category specific / quantitative limits. "
            "The applicable Regulation (EU) 1333/2008 conditions must be checked."
        ),
        "reason": (
            "FSA Approved additives and E numbers; E508 is listed "
            "under the 'Others' additive group."
        ),
    },
    {
        "ingredient": "sodium carbonate",
        "label": (
            "FSA lists Sodium carbonates (E500) as an approved food "
            "additive for Northern Ireland."
        ),
        "restriction": (
            "Condition type: food-category specific / quantitative limits. "
            "Applicable Annex II/III conditions must be checked."
        ),
        "reason": (
            "FSA Approved additives and E numbers; E500 is listed "
            "under the 'Others' additive group."
        ),
    },
    {
        "ingredient": "disodium 5'-ribonucleotides",
        "label": (
            "FSA lists Disodium 5'-ribonucleotides (E635) as an approved "
            "food additive for Northern Ireland."
        ),
        "restriction": (
            "Condition type: food-category specific / quantitative limits. "
            "The applicable Northern Ireland legislation must be checked "
            "for the intended food category."
        ),
        "reason": (
            "FSA Approved additives and E numbers; E635 is listed "
            "under the 'Others' additive group."
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
    name = "Northern Ireland"

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
                "NI",
                "REGION",
                "Food Standards Agency (FSA)",
                SOURCE_URL,
                SOURCE_URL,
                "VERIFIED_SOURCE",
                8,
                (
                    "Northern Ireland food-additive rules differ from "
                    "Great Britain; EU Regulation 1333/2008 applies in "
                    "Northern Ireland under the Windsor Framework."
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
            "OFFICIAL_GUIDANCE",
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
            f"✅ Northern Ireland records added/updated: {added}"
        )
        print(
            f"Northern Ireland regulatory records in database: {total}"
        )

    finally:
        conn.close()


if __name__ == "__main__":
    main()
