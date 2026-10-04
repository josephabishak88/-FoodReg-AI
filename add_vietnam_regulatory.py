import sqlite3

DB_PATH = "foodreg.db"
TODAY = "2026-10-04"

SOURCE_URL = 'https://moh.gov.vn/en_US/hoat-dong-cua-lanh-dao-bo/-/asset_publisher/k206Q9qkZOqn/content/thong-tu-so-24-2019-tt-byt-quy-inh-ve-quan-ly-va-su-dung-phu-gia-thuc-pham'
SOURCE_DOCUMENT = 'Circular No. 24/2019/TT-BYT on Management and Use of Food Additives, as amended by Circular 17/2023/TT-BYT'

RECORDS = [
        {
            "ingredient": 'citric acid',
            "label": "Vietnam's Circular 24/2019/TT-BYT establishes the food-additive list, use, management and responsibilities, with later amendments. Citric Acid (INS 330) is evaluated here against that framework.",
            "restriction": 'Condition type: permitted-list + food-category maximum-level check. Verify the current Vietnamese additive list and exact food application.',
        },
        {
            "ingredient": 'guar gum',
            "label": "Vietnam's Circular 24/2019/TT-BYT establishes the food-additive list, use, management and responsibilities, with later amendments. Guar Gum (INS 412) is evaluated here against that framework.",
            "restriction": 'Condition type: permitted-list + food-category maximum-level check. Verify the current Vietnamese additive list and exact food application.',
        },
        {
            "ingredient": 'potassium chloride',
            "label": "Vietnam's Circular 24/2019/TT-BYT establishes the food-additive list, use, management and responsibilities, with later amendments. Potassium Chloride (INS 508) is evaluated here against that framework.",
            "restriction": 'Condition type: permitted-list + food-category maximum-level check. Verify the current Vietnamese additive list and exact food application.',
        },
        {
            "ingredient": 'sodium carbonate',
            "label": "Vietnam's Circular 24/2019/TT-BYT establishes the food-additive list, use, management and responsibilities, with later amendments. Sodium Carbonate (INS 500(i)) is evaluated here against that framework.",
            "restriction": 'Condition type: permitted-list + food-category maximum-level check. Verify the current Vietnamese additive list and exact food application.',
        },
        {
            "ingredient": 'caramel iv',
            "label": "Vietnam's Circular 24/2019/TT-BYT establishes the food-additive list, use, management and responsibilities, with later amendments. Caramel IV (INS 150d) is evaluated here against that framework.",
            "restriction": 'Condition type: permitted-list + food-category maximum-level check. Verify the current Vietnamese additive list and exact food application.',
        },
        {
            "ingredient": "disodium 5'-ribonucleotides",
            "label": "Vietnam's Circular 24/2019/TT-BYT establishes the food-additive list, use, management and responsibilities, with later amendments. Disodium 5'-Ribonucleotides (INS 635) is evaluated here against that framework.",
            "restriction": 'Condition type: permitted-list + food-category maximum-level check. Verify the current Vietnamese additive list and exact food application.',
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
    name = 'Vietnam'
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
                'Vietnam',
                'VN',
                "COUNTRY",
                'Ministry of Health — Vietnam',
                SOURCE_URL,
                SOURCE_URL,
                "VERIFIED_SOURCE",
                26,
                "Vietnam's Ministry of Health says additives must be permitted for the food, not exceed maximum levels, and be used only for an appropriate technological function.",
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
            'Ministry of Health — Vietnam',
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

        print(f"✅ Vietnam records added/updated: {added}")
        print(f"Vietnam regulatory records in database: {total}")
        print(
            "ℹ️ Records use CHECK_CONDITIONS because exact permission "
            "depends on the applicable food/additive conditions."
        )
    finally:
        conn.close()


if __name__ == "__main__":
    main()
