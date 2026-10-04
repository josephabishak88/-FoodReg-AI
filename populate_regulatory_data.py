import sqlite3
from datetime import date

DB_PATH = "foodreg.db"

TODAY = "2026-10-04"

INGREDIENTS = [
    {
        "name": "citric acid",
        "ins": "330",
        "aliases": ["citric acid", "e330", "ins 330"],
    },
    {
        "name": "guar gum",
        "ins": "412",
        "aliases": ["guar gum", "gum guar", "e412", "ins 412"],
    },
    {
        "name": "calcium carbonate",
        "ins": "170",
        "aliases": ["calcium carbonate", "e170", "ins 170", "ins 170(i)"],
    },
    {
        "name": "potassium chloride",
        "ins": "508",
        "aliases": ["potassium chloride", "e508", "ins 508"],
    },
    {
        "name": "sodium carbonate",
        "ins": "500(i)",
        "aliases": ["sodium carbonate", "e500", "ins 500", "ins 500(i)"],
    },
]

JURISDICTIONS = [
    {
        "name": "India",
        "code": "IN",
        "type": "NATIONAL",
        "authority": "FSSAI",
        "official_source": "https://www.fssai.gov.in/",
        "additive_source": "FSSAI Food Additives Compendium",
        "data_status": "REFERENCE",
        "priority": 1,
    },
    {
        "name": "United States",
        "code": "US",
        "type": "NATIONAL",
        "authority": "U.S. FDA",
        "official_source": "https://www.fda.gov/food",
        "additive_source": "FDA Substances Added to Food (EAFUS)",
        "data_status": "REFERENCE",
        "priority": 1,
    },
]

# These are intentionally conservative prototype records.
# A record means the official source contains regulatory information;
# it does NOT mean unrestricted use in every food category.
RECORDS = [
    # -----------------------------------------------------
    # INDIA
    # -----------------------------------------------------
    {
        "ingredient": "calcium carbonate",
        "jurisdiction": "India",
        "status": "CHECK_CONDITIONS",
        "label": "Listed by FSSAI as Calcium carbonate (INS 170(i)).",
        "restriction": "Food-category and technological-purpose conditions apply; the cited FSSAI compendium entry shows GMP for the listed use.",
        "reason": "FSSAI Food Additives Compendium, Version XXV (23.09.2022).",
        "authority": "FSSAI",
        "source_url": "https://www.fssai.gov.in/upload/uploadfiles/files/Compendium_Food_Additives_Regulations_21_10_2022.pdf",
        "source_document": "Compendium_Food_Additives_Regulations_21_10_2022.pdf",
        "source_type": "OFFICIAL_REFERENCE",
        "verified_date": TODAY,
    },
    {
        "ingredient": "citric acid",
        "jurisdiction": "India",
        "status": "CHECK_CONDITIONS",
        "label": "Listed by FSSAI as Citric acid (INS 330).",
        "restriction": "The cited FSSAI processing-aid entry specifies permitted product categories and GMP/functional-use conditions; category-specific rules must be checked.",
        "reason": "FSSAI official food-additives / processing-aids material.",
        "authority": "FSSAI",
        "source_url": "https://comments.fssai.gov.in/Bestviewwl.aspx?NOTIFICATION_ID=4353",
        "source_document": "FSSAI official notification/ePC material",
        "source_type": "OFFICIAL_REFERENCE",
        "verified_date": TODAY,
    },

    # -----------------------------------------------------
    # UNITED STATES
    # -----------------------------------------------------
    {
        "ingredient": "guar gum",
        "jurisdiction": "United States",
        "status": "CHECK_CONDITIONS",
        "label": "FDA lists guar gum in its Substances Added to Food inventory and cites 21 CFR 184.1339.",
        "restriction": "Use is subject to the applicable FDA regulation and conditions; this record is not a blanket approval for every food/use.",
        "reason": "FDA Substances Added to Food inventory; 21 CFR 184.1339 is cited.",
        "authority": "U.S. FDA",
        "source_url": "https://hfpappexternal.fda.gov/scripts/fdcc/index.cfm?id=GUARGUM&set=FoodSubstances",
        "source_document": "FDA Substances Added to Food",
        "source_type": "OFFICIAL_REFERENCE",
        "verified_date": TODAY,
    },
    {
        "ingredient": "citric acid",
        "jurisdiction": "United States",
        "status": "CHECK_CONDITIONS",
        "label": "FDA lists citric acid in its Substances Added to Food inventory and cites multiple 21 CFR provisions, including 184.1033.",
        "restriction": "Use is subject to the cited 21 CFR provisions and applicable conditions of use.",
        "reason": "FDA Substances Added to Food inventory.",
        "authority": "U.S. FDA",
        "source_url": "https://hfpappexternal.fda.gov/scripts/fdcc/index.cfm?id=CITRICACID&set=FoodSubstances",
        "source_document": "FDA Substances Added to Food",
        "source_type": "OFFICIAL_REFERENCE",
        "verified_date": TODAY,
    },
    {
        "ingredient": "calcium carbonate",
        "jurisdiction": "United States",
        "status": "CHECK_CONDITIONS",
        "label": "FDA lists calcium carbonate in its Substances Added to Food inventory and cites food-additive provisions including 184.1191.",
        "restriction": "Use is subject to the cited 21 CFR provisions and applicable conditions of use.",
        "reason": "FDA Substances Added to Food inventory.",
        "authority": "U.S. FDA",
        "source_url": "https://hfpappexternal.fda.gov/scripts/fdcc/index.cfm?id=CALCIUMCARBONATE&set=foodsubstances",
        "source_document": "FDA Substances Added to Food",
        "source_type": "OFFICIAL_REFERENCE",
        "verified_date": TODAY,
    },
    {
        "ingredient": "potassium chloride",
        "jurisdiction": "United States",
        "status": "CHECK_CONDITIONS",
        "label": "FDA lists potassium chloride in its Substances Added to Food inventory and cites 21 CFR 184.1622.",
        "restriction": "Use is subject to the cited 21 CFR provisions and applicable conditions of use.",
        "reason": "FDA Substances Added to Food inventory.",
        "authority": "U.S. FDA",
        "source_url": "https://hfpappexternal.fda.gov/scripts/fdcc/index.cfm?id=POTASSIUMCHLORIDE&set=FoodSubstances",
        "source_document": "FDA Substances Added to Food",
        "source_type": "OFFICIAL_REFERENCE",
        "verified_date": TODAY,
    },
    {
        "ingredient": "sodium carbonate",
        "jurisdiction": "United States",
        "status": "CHECK_CONDITIONS",
        "label": "FDA lists sodium carbonate in its Substances Added to Food inventory and cites food-additive provisions including 184.1742.",
        "restriction": "Use is subject to the cited 21 CFR provisions and applicable conditions of use.",
        "reason": "FDA Substances Added to Food inventory.",
        "authority": "U.S. FDA",
        "source_url": "https://hfpappexternal.fda.gov/scripts/fdcc/index.cfm?id=SODIUMCARBONATE&set=FoodSubstances",
        "source_document": "FDA Substances Added to Food",
        "source_type": "OFFICIAL_REFERENCE",
        "verified_date": TODAY,
    },
]


def table_columns(conn, table):
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return {row[1] for row in rows}


def add_missing_columns(conn, table, expected_columns):
    existing = table_columns(conn, table)
    for column_name, column_type in expected_columns.items():
        if column_name not in existing:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column_name} {column_type}")
    conn.commit()


def backfill_ids(conn, table):
    if "id" not in table_columns(conn, table):
        return
    try:
        conn.execute(f"UPDATE {table} SET id = rowid WHERE id IS NULL")
        conn.commit()
    except sqlite3.OperationalError:
        pass


def ensure_unique_index(conn, index_name, table, columns):
    try:
        conn.execute(f"CREATE UNIQUE INDEX IF NOT EXISTS {index_name} ON {table} ({', '.join(columns)})")
        conn.commit()
    except sqlite3.IntegrityError:
        print(f"⚠️ Could not create unique index {index_name}; duplicate legacy rows may exist.")


def ensure_schema(conn):
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS ingredients (
            id INTEGER PRIMARY KEY AUTOINCREMENT, canonical_name TEXT UNIQUE NOT NULL, ins_code TEXT, cas_number TEXT, description TEXT
        );
        CREATE TABLE IF NOT EXISTS ingredient_aliases (
            id INTEGER PRIMARY KEY AUTOINCREMENT, ingredient_id INTEGER NOT NULL, alias TEXT NOT NULL, UNIQUE (ingredient_id, alias), FOREIGN KEY (ingredient_id) REFERENCES ingredients(id)
        );
        CREATE TABLE IF NOT EXISTS jurisdictions (
            id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT UNIQUE NOT NULL, code TEXT, type TEXT, authority TEXT, official_source TEXT, additive_source TEXT, data_status TEXT, priority INTEGER, notes TEXT
        );
        CREATE TABLE IF NOT EXISTS regulatory_records (
            id INTEGER PRIMARY KEY AUTOINCREMENT, ingredient_id INTEGER NOT NULL, jurisdiction_id INTEGER NOT NULL, status TEXT NOT NULL, label TEXT, restriction TEXT, reason TEXT, food_category TEXT, maximum_level TEXT, unit TEXT, conditions TEXT, authority TEXT, source_url TEXT, source_document TEXT, effective_date TEXT, verified_date TEXT, source_type TEXT, notes TEXT, UNIQUE (ingredient_id, jurisdiction_id), FOREIGN KEY (ingredient_id) REFERENCES ingredients(id), FOREIGN KEY (jurisdiction_id) REFERENCES jurisdictions(id)
        );
        """
    )
    add_missing_columns(conn, "ingredients", {"canonical_name":"TEXT","ins_code":"TEXT","cas_number":"TEXT","description":"TEXT","id":"INTEGER"})
    add_missing_columns(conn, "ingredient_aliases", {"id":"INTEGER","ingredient_id":"INTEGER","alias":"TEXT"})
    add_missing_columns(conn, "jurisdictions", {"name":"TEXT","code":"TEXT","type":"TEXT","authority":"TEXT","official_source":"TEXT","additive_source":"TEXT","data_status":"TEXT","priority":"INTEGER","notes":"TEXT","id":"INTEGER"})
    add_missing_columns(conn, "regulatory_records", {"id":"INTEGER","ingredient_id":"INTEGER","jurisdiction_id":"INTEGER","status":"TEXT","label":"TEXT","restriction":"TEXT","reason":"TEXT","food_category":"TEXT","maximum_level":"TEXT","unit":"TEXT","conditions":"TEXT","authority":"TEXT","source_url":"TEXT","source_document":"TEXT","effective_date":"TEXT","verified_date":"TEXT","source_type":"TEXT","notes":"TEXT"})
    for table in ["ingredients","ingredient_aliases","jurisdictions","regulatory_records"]:
        backfill_ids(conn, table)
    ensure_unique_index(conn, "idx_ingredients_canonical_name", "ingredients", ["canonical_name"])
    ensure_unique_index(conn, "idx_ingredient_aliases_pair", "ingredient_aliases", ["ingredient_id","alias"])
    ensure_unique_index(conn, "idx_jurisdictions_name", "jurisdictions", ["name"])
    ensure_unique_index(conn, "idx_regulatory_records_pair", "regulatory_records", ["ingredient_id","jurisdiction_id"])
    conn.commit()


def upsert_ingredient(conn, item):
    conn.execute(
        """
        INSERT INTO ingredients (canonical_name, ins_code)
        VALUES (?, ?)
        ON CONFLICT(canonical_name)
        DO UPDATE SET ins_code = excluded.ins_code
        """,
        (item["name"], item["ins"]),
    )

    row = conn.execute(
        "SELECT id, rowid FROM ingredients WHERE canonical_name = ?",
        (item["name"],),
    ).fetchone()

    if row is None:
        raise RuntimeError(
            f"Ingredient was not found after upsert: {item['name']}"
        )

    ingredient_id, rowid = row

    # Legacy databases may have an id column that is not an INTEGER PRIMARY KEY.
    # In that case SQLite can insert NULL into id, so use rowid and persist it.
    if ingredient_id is None:
        ingredient_id = rowid
        conn.execute(
            "UPDATE ingredients SET id = ? WHERE rowid = ?",
            (ingredient_id, rowid),
        )
        conn.commit()

    for alias in item["aliases"]:
        conn.execute(
            """
            INSERT OR IGNORE INTO ingredient_aliases
            (ingredient_id, alias)
            VALUES (?, ?)
            """,
            (ingredient_id, alias),
        )

    return ingredient_id


def upsert_jurisdiction(conn, item):
    conn.execute(
        """
        INSERT INTO jurisdictions
        (name, code, type, authority, official_source,
         additive_source, data_status, priority)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(name)
        DO UPDATE SET
            code = excluded.code,
            authority = excluded.authority,
            official_source = excluded.official_source,
            additive_source = excluded.additive_source,
            data_status = excluded.data_status,
            priority = excluded.priority
        """,
        (
            item["name"],
            item["code"],
            item["type"],
            item["authority"],
            item["official_source"],
            item["additive_source"],
            item["data_status"],
            item["priority"],
        ),
    )

    row = conn.execute(
        "SELECT id, rowid FROM jurisdictions WHERE name = ?",
        (item["name"],),
    ).fetchone()

    if row is None:
        raise RuntimeError(
            f"Jurisdiction was not found after upsert: {item['name']}"
        )

    jurisdiction_id, rowid = row

    if jurisdiction_id is None:
        jurisdiction_id = rowid
        conn.execute(
            "UPDATE jurisdictions SET id = ? WHERE rowid = ?",
            (jurisdiction_id, rowid),
        )
        conn.commit()

    return jurisdiction_id


def upsert_record(conn, record, ingredient_ids, jurisdiction_ids):
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
            ingredient_ids[record["ingredient"]],
            jurisdiction_ids[record["jurisdiction"]],
            record["status"],
            record["label"],
            record["restriction"],
            record["reason"],
            record["authority"],
            record["source_url"],
            record["source_document"],
            record["verified_date"],
            record["source_type"],
        ),
    )


def main():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON")

    ensure_schema(conn)

    ingredient_ids = {}
    for item in INGREDIENTS:
        ingredient_ids[item["name"]] = upsert_ingredient(
            conn,
            item,
        )

    jurisdiction_ids = {}
    for item in JURISDICTIONS:
        jurisdiction_ids[item["name"]] = upsert_jurisdiction(
            conn,
            item,
        )

    for record in RECORDS:
        upsert_record(
            conn,
            record,
            ingredient_ids,
            jurisdiction_ids,
        )

    conn.commit()

    ingredient_count = conn.execute(
        "SELECT COUNT(*) FROM ingredients"
    ).fetchone()[0]

    record_count = conn.execute(
        "SELECT COUNT(*) FROM regulatory_records"
    ).fetchone()[0]

    print("✅ Regulatory database updated")
    print(f"Ingredients in database: {ingredient_count}")
    print(f"Regulatory records: {record_count}")
    print("Added source-backed prototype coverage for:")
    print("  • Citric acid (INS 330)")
    print("  • Guar gum (INS 412)")
    print("  • Calcium carbonate (INS 170)")
    print("  • Potassium chloride (INS 508)")
    print("  • Sodium carbonate (INS 500 family)")
    print("Jurisdictions: India + United States")

    conn.close()


if __name__ == "__main__":
    main()
