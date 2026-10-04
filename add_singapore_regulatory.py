import sqlite3

DB_PATH = "foodreg.db"
TODAY = "2026-10-04"

SOURCE_URL = (
    "https://www.sfa.gov.sg/tools-and-resources/"
    "food-additives-search"
)
SOURCE_DOCUMENT = (
    "SFA Food Additives Search / "
    "List of Food Additives Permitted under Food Regulations"
)

RECORDS = [
    {
        "ingredient": "guar gum",
        "ins": "412",
        "label": (
            "SFA lists guar gum (INS 412) in the 6th Schedule "
            "with GMP conditions."
        ),
        "restriction": (
            "GMP applies; product-specific Food Regulations "
            "and any applicable food-category requirements must "
            "be checked."
        ),
        "reason": (
            "SFA permitted-food-additives list: INS 412, "
            "6th Schedule, GMP."
        ),
    },
    {
        "ingredient": "citric acid",
        "ins": "330",
        "label": (
            "SFA lists citric acid (INS 330) with specified "
            "Food Regulations and Schedule references and GMP."
        ),
        "restriction": (
            "GMP applies together with the cited regulations "
            "and schedules; exact food-category requirements "
            "must be checked."
        ),
        "reason": (
            "SFA permitted-food-additives list: INS 330, "
            "Regulations 17(2), 19(2)(a), 26(3), 125, 173, "
            "174 and 8th/17th Schedules; GMP."
        ),
    },
    {
        "ingredient": "potassium chloride",
        "ins": "508",
        "label": (
            "SFA lists potassium chloride (INS 508) under the "
            "7th and 8th Schedules with GMP."
        ),
        "restriction": (
            "GMP applies and the relevant 7th/8th Schedule "
            "conditions must be checked for the food use."
        ),
        "reason": (
            "SFA permitted-food-additives list: INS 508, "
            "7th and 8th Schedules, GMP."
        ),
    },
    {
        "ingredient": "caramel iv",
        "ins": "150d",
        "label": (
            "SFA lists Caramel IV - sulfite ammonia process "
            "(INS 150d) in the 5th Schedule (Part II) with GMP."
        ),
        "restriction": (
            "GMP applies together with the applicable colour-"
            "additive requirements in the 5th Schedule (Part II)."
        ),
        "reason": (
            "SFA permitted-food-additives list: INS 150d, "
            "5th Schedule (Part II), GMP."
        ),
    },
    {
        "ingredient": "disodium 5'-ribonucleotides",
        "ins": "635",
        "label": (
            "SFA lists disodium 5'-ribonucleotides (INS 635) "
            "and cross-references INS 627 and INS 631."
        ),
        "restriction": (
            "The SFA list cross-references INS 627 and INS 631; "
            "the applicable Regulation 23(2) and GMP conditions "
            "must be checked."
        ),
        "reason": (
            "SFA permitted-food-additives list: INS 635, "
            "see INS 627 and INS 631; those entries are under "
            "Regulation 23(2) with GMP."
        ),
    },
    {
        "ingredient": "sodium carbonate",
        "ins": "500",
        "label": (
            "SFA lists sodium carbonates (INS 500) and identifies "
            "INS 500(i) sodium carbonate under Regulation 181, "
            "7th and 8th Schedules with GMP."
        ),
        "restriction": (
            "The specific form used here is sodium carbonate "
            "(INS 500(i)); applicable Regulation 181 and the "
            "7th/8th Schedule requirements must be checked."
        ),
        "reason": (
            "SFA permitted-food-additives list: INS 500(i), "
            "sodium carbonate, Regulation 181, 7th & 8th "
            "Schedules, GMP."
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
    name = "Singapore"

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
                "SG",
                "COUNTRY",
                "Singapore Food Agency (SFA)",
                SOURCE_URL,
                SOURCE_URL,
                "VERIFIED_SOURCE",
                3,
                "Official SFA food-additives source.",
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
            "Singapore Food Agency (SFA)",
            SOURCE_URL,
            SOURCE_DOCUMENT,
            TODAY,
            "OFFICIAL_REFERENCE",
        ),
    )


def main():
    conn = sqlite3.connect(DB_PATH)

    try:
        # Compatibility with the legacy database.
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
            conn, "jurisdictions",
            "notes", "TEXT"
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

        print(
            f"✅ Singapore records added/updated: {added}"
        )

        total = conn.execute(
            """
            SELECT COUNT(*)
            FROM regulatory_records
            WHERE jurisdiction_id = ?
            """,
            (jurisdiction_id,),
        ).fetchone()[0]

        print(
            f"Singapore regulatory records in database: {total}"
        )

    finally:
        conn.close()


if __name__ == "__main__":
    main()
