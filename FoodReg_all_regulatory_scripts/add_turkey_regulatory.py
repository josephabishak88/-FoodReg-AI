import sqlite3

DB_PATH = "foodreg.db"
TODAY = "2026-10-04"

SOURCE_URL = 'https://www.tarimorman.gov.tr/EYDB/Lists/BirimSayfalari/Attachments/9/Food%20Literacy%20Hand%20Book_EN_Screen-2025-2.pdf'
SOURCE_DOCUMENT = 'Turkish Food Codex — Regulation on Food Additives (Official Gazette No. 28693, 30 June 2013)'

RECORDS = [
        {
            "ingredient": 'citric acid',
            "label": "Turkey's Ministry of Agriculture and Forestry identifies the Turkish Food Codex Regulation on Food Additives as the legal framework for additive use and limits. Citric Acid (INS 330) is evaluated here against that framework.",
            "restriction": 'Condition type: food-category-specific use/limit check. Confirm the applicable food and additive in the Turkish Food Codex.',
        },
        {
            "ingredient": 'guar gum',
            "label": "Turkey's Ministry of Agriculture and Forestry identifies the Turkish Food Codex Regulation on Food Additives as the legal framework for additive use and limits. Guar Gum (INS 412) is evaluated here against that framework.",
            "restriction": 'Condition type: food-category-specific use/limit check. Confirm the applicable food and additive in the Turkish Food Codex.',
        },
        {
            "ingredient": 'potassium chloride',
            "label": "Turkey's Ministry of Agriculture and Forestry identifies the Turkish Food Codex Regulation on Food Additives as the legal framework for additive use and limits. Potassium Chloride (INS 508) is evaluated here against that framework.",
            "restriction": 'Condition type: food-category-specific use/limit check. Confirm the applicable food and additive in the Turkish Food Codex.',
        },
        {
            "ingredient": 'sodium carbonate',
            "label": "Turkey's Ministry of Agriculture and Forestry identifies the Turkish Food Codex Regulation on Food Additives as the legal framework for additive use and limits. Sodium Carbonate (INS 500(i)) is evaluated here against that framework.",
            "restriction": 'Condition type: food-category-specific use/limit check. Confirm the applicable food and additive in the Turkish Food Codex.',
        },
        {
            "ingredient": 'caramel iv',
            "label": "Turkey's Ministry of Agriculture and Forestry identifies the Turkish Food Codex Regulation on Food Additives as the legal framework for additive use and limits. Caramel IV (INS 150d) is evaluated here against that framework.",
            "restriction": 'Condition type: food-category-specific use/limit check. Confirm the applicable food and additive in the Turkish Food Codex.',
        },
        {
            "ingredient": "disodium 5'-ribonucleotides",
            "label": "Turkey's Ministry of Agriculture and Forestry identifies the Turkish Food Codex Regulation on Food Additives as the legal framework for additive use and limits. Disodium 5'-Ribonucleotides (INS 635) is evaluated here against that framework.",
            "restriction": 'Condition type: food-category-specific use/limit check. Confirm the applicable food and additive in the Turkish Food Codex.',
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
    name = 'Turkey'
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
                'Turkey',
                'TR',
                "COUNTRY",
                'Ministry of Agriculture and Forestry — Turkish Food Codex',
                SOURCE_URL,
                SOURCE_URL,
                "VERIFIED_SOURCE",
                25,
                'The Turkish Ministry states that the Turkish Food Codex Regulation on Food Additives specifies which additives may be used in which foods and their limits.',
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
            'Ministry of Agriculture and Forestry — Turkish Food Codex',
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

        print(f"✅ Turkey records added/updated: {added}")
        print(f"Turkey regulatory records in database: {total}")
        print(
            "ℹ️ Records use CHECK_CONDITIONS because exact permission "
            "depends on the applicable food/additive conditions."
        )
    finally:
        conn.close()


if __name__ == "__main__":
    main()
