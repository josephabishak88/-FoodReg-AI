import sqlite3

DB_PATH = "foodreg.db"
TODAY = "2026-10-04"

SOURCE_URL = 'https://www.health.gov.za/food-control-regulations/'
SOURCE_DOCUMENT = 'Foodstuffs, Cosmetics and Disinfectants Act regulations on food additives'

RECORDS = [
        {
            "ingredient": 'citric acid',
            "label": 'The National Department of Health lists food-additive regulations under Food Control. Citric Acid (INS 330) is evaluated here against that framework.',
            "restriction": 'Condition type: regulation / food-category-use check. Match the additive to the applicable regulation and food category.',
        },
        {
            "ingredient": 'guar gum',
            "label": 'The National Department of Health lists food-additive regulations under Food Control. Guar Gum (INS 412) is evaluated here against that framework.',
            "restriction": 'Condition type: regulation / food-category-use check. Match the additive to the applicable regulation and food category.',
        },
        {
            "ingredient": 'potassium chloride',
            "label": 'The National Department of Health lists food-additive regulations under Food Control. Potassium Chloride (INS 508) is evaluated here against that framework.',
            "restriction": 'Condition type: regulation / food-category-use check. Match the additive to the applicable regulation and food category.',
        },
        {
            "ingredient": 'sodium carbonate',
            "label": 'The National Department of Health lists food-additive regulations under Food Control. Sodium Carbonate (INS 500(i)) is evaluated here against that framework.',
            "restriction": 'Condition type: regulation / food-category-use check. Match the additive to the applicable regulation and food category.',
        },
        {
            "ingredient": 'caramel iv',
            "label": 'The National Department of Health lists food-additive regulations under Food Control. Caramel IV (INS 150d) is evaluated here against that framework.',
            "restriction": 'Condition type: regulation / food-category-use check. Match the additive to the applicable regulation and food category.',
        },
        {
            "ingredient": "disodium 5'-ribonucleotides",
            "label": "The National Department of Health lists food-additive regulations under Food Control. Disodium 5'-Ribonucleotides (INS 635) is evaluated here against that framework.",
            "restriction": 'Condition type: regulation / food-category-use check. Match the additive to the applicable regulation and food category.',
        }
]


def ensure_column(conn, table, column, sql_type):
    cols = {
        row[1]
        for row in conn.execute(f"PRAGMA table_info({table})").fetchall()
    }
    if column not in cols:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {sql_type}")


def get_jurisdiction(conn):
    name = 'South Africa'
    row = conn.execute(
        "SELECT id, rowid FROM jurisdictions WHERE name = ?", (name,)
    ).fetchone()

    if row is None:
        conn.execute(
            """
            INSERT INTO jurisdictions
            (name, code, type, authority, official_source, additive_source,
             data_status, priority, notes)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                'South Africa',
                'ZA',
                "COUNTRY",
                'National Department of Health — Food Control',
                SOURCE_URL,
                SOURCE_URL,
                "VERIFIED_SOURCE",
                19,
                'South Africa maintains food-additive regulations under the Foodstuffs, Cosmetics and Disinfectants Act; exact permissions are category/use dependent.',
            ),
        )
        row = conn.execute(
            "SELECT id, rowid FROM jurisdictions WHERE name = ?", (name,)
        ).fetchone()

    jurisdiction_id, rowid = row
    if jurisdiction_id is None:
        jurisdiction_id = rowid
        conn.execute(
            "UPDATE jurisdictions SET id = ? WHERE rowid = ?",
            (jurisdiction_id, rowid),
        )
    return jurisdiction_id


def get_ingredient_id(conn, canonical_name):
    row = conn.execute(
        "SELECT id, rowid FROM ingredients WHERE canonical_name = ?",
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
            "UPDATE ingredients SET id = ? WHERE rowid = ?",
            (ingredient_id, rowid),
        )
    return ingredient_id


def upsert_record(conn, ingredient_id, jurisdiction_id, item):
    conn.execute(
        """
        INSERT INTO regulatory_records
        (
            ingredient_id, jurisdiction_id, status, label, restriction,
            reason, authority, source_url, source_document,
            verified_date, source_type
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
            SOURCE_DOCUMENT,
            'National Department of Health — Food Control',
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
            ("code", "TEXT"), ("type", "TEXT"), ("authority", "TEXT"),
            ("official_source", "TEXT"), ("additive_source", "TEXT"),
            ("data_status", "TEXT"), ("priority", "INTEGER"),
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
            ingredient_id = get_ingredient_id(conn, item["ingredient"])
            upsert_record(conn, ingredient_id, jurisdiction_id, item)
            added += 1

        conn.commit()

        total = conn.execute(
            "SELECT COUNT(*) FROM regulatory_records WHERE jurisdiction_id = ?",
            (jurisdiction_id,),
        ).fetchone()[0]

        print(f"✅ South Africa records added/updated: {added}")
        print(f"South Africa regulatory records in database: {total}")
        print(
            "ℹ️ Records use CHECK_CONDITIONS because exact permission "
            "depends on the applicable food/additive conditions."
        )
    finally:
        conn.close()


if __name__ == "__main__":
    main()
