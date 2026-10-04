import sqlite3


DB_PATH = "foodreg.db"
TODAY = "2026-10-04"


INGREDIENTS = [
    {
        "name": "caramel iv",
        "ins": "150d",
        "aliases": [
            "caramel iv",
            "caramel 150d",
            "caramel class iv",
            "e150d",
            "ins 150d",
        ],
    },
    {
        "name": "disodium 5'-ribonucleotides",
        "ins": "635",
        "aliases": [
            "disodium 5'-ribonucleotides",
            "disodium 5 ribonucleotides",
            "ribonucleotides",
            "e635",
            "ins 635",
        ],
    },
]


RECORDS = [
    # -----------------------------------------------------
    # INDIA — CARAMEL IV
    # -----------------------------------------------------
    {
        "ingredient": "caramel iv",
        "jurisdiction": "India",
        "status": "CHECK_CONDITIONS",
        "label": (
            "FSSAI lists Caramel IV - sulfite ammonia caramel "
            "(INS 150d) in its food-additive compendium."
        ),
        "restriction": (
            "Use is category-specific; the cited FSSAI compendium "
            "contains maximum levels and notes for particular food categories."
        ),
        "reason": (
            "FSSAI Compendium of Food Additives Regulations "
            "(official FSSAI material)."
        ),
        "authority": "FSSAI",
        "source_url": (
            "https://www.fssai.gov.in/upload/uploadfiles/files/"
            "Compendium_Food_Additives_Regulations_16_08_2021.pdf"
        ),
        "source_document": (
            "Compendium_Food_Additives_Regulations_16_08_2021.pdf"
        ),
        "source_type": "OFFICIAL_REFERENCE",
        "verified_date": TODAY,
    },

    # -----------------------------------------------------
    # UNITED STATES — CARAMEL
    # -----------------------------------------------------
    {
        "ingredient": "caramel iv",
        "jurisdiction": "United States",
        "status": "CHECK_CONDITIONS",
        "label": (
            "FDA's color-additive summary lists Caramel as E150a-d "
            "under 21 CFR 73.85."
        ),
        "restriction": (
            "The FDA source covers the Caramel E150a-d family; "
            "food use remains subject to the applicable 21 CFR requirements "
            "and conditions. This record does not claim unrestricted use "
            "for every food or formulation."
        ),
        "reason": (
            "FDA Summary of Color Additives for Use in the United States; "
            "Caramel is listed as E150a-d under 21 CFR 73.85."
        ),
        "authority": "U.S. FDA",
        "source_url": (
            "https://www.fda.gov/industry/color-additives/"
            "summary-color-additives-use-united-states-foods-drugs-"
            "cosmetics-and-medical-devices"
        ),
        "source_document": (
            "FDA Summary of Color Additives for Use in the United States"
        ),
        "source_type": "OFFICIAL_REFERENCE",
        "verified_date": TODAY,
    },

    # -----------------------------------------------------
    # INDIA — INS 635
    # -----------------------------------------------------
    {
        "ingredient": "disodium 5'-ribonucleotides",
        "jurisdiction": "India",
        "status": "CHECK_CONDITIONS",
        "label": (
            "FSSAI lists Disodium 5'-ribonucleotides (INS 635) "
            "as a flavour enhancer."
        ),
        "restriction": (
            "Food-category and applicable additive conditions must be "
            "checked for the specific product use."
        ),
        "reason": (
            "FSSAI official Compendium of Food Additives Regulations."
        ),
        "authority": "FSSAI",
        "source_url": (
            "https://www.fssai.gov.in/upload/uploadfiles/files/"
            "Compendium_Food_Additives_Regulations_04_01_2022.pdf"
        ),
        "source_document": (
            "Compendium_Food_Additives_Regulations_04_01_2022.pdf"
        ),
        "source_type": "OFFICIAL_REFERENCE",
        "verified_date": TODAY,
    },
]


def table_columns(conn, table):
    return {
        row[1]
        for row in conn.execute(
            f"PRAGMA table_info({table})"
        ).fetchall()
    }


def ensure_column(conn, table, column, column_type):
    if column not in table_columns(conn, table):
        conn.execute(
            f"ALTER TABLE {table} ADD COLUMN {column} {column_type}"
        )
        conn.commit()


def get_or_create_ingredient(conn, item):
    conn.execute(
        """
        INSERT INTO ingredients (canonical_name, ins_code)
        VALUES (?, ?)
        ON CONFLICT(canonical_name)
        DO UPDATE SET ins_code = excluded.ins_code
        """,
        (
            item["name"],
            item["ins"],
        ),
    )

    row = conn.execute(
        """
        SELECT id, rowid
        FROM ingredients
        WHERE canonical_name = ?
        """,
        (item["name"],),
    ).fetchone()

    if row is None:
        raise RuntimeError(
            f"Could not find ingredient: {item['name']}"
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
            (
                ingredient_id,
                rowid,
            ),
        )

    for alias in item["aliases"]:
        conn.execute(
            """
            INSERT OR IGNORE INTO ingredient_aliases
            (ingredient_id, alias)
            VALUES (?, ?)
            """,
            (
                ingredient_id,
                alias,
            ),
        )

    return ingredient_id


def get_jurisdiction(conn, name):
    row = conn.execute(
        """
        SELECT id, rowid
        FROM jurisdictions
        WHERE name = ?
        """,
        (name,),
    ).fetchone()

    if row is None:
        raise RuntimeError(
            f"Jurisdiction not found: {name}"
        )

    jurisdiction_id, rowid = row

    if jurisdiction_id is None:
        jurisdiction_id = rowid

        conn.execute(
            """
            UPDATE jurisdictions
            SET id = ?
            WHERE rowid = ?
            """,
            (
                jurisdiction_id,
                rowid,
            ),
        )

    return jurisdiction_id


def upsert_record(
    conn,
    record,
    ingredient_id,
    jurisdiction_id,
):
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

    try:
        conn.execute("PRAGMA foreign_keys = ON")

        # Ensure the columns used below exist.
        ensure_column(
            conn,
            "ingredients",
            "canonical_name",
            "TEXT",
        )
        ensure_column(
            conn,
            "ingredients",
            "ins_code",
            "TEXT",
        )
        ensure_column(
            conn,
            "ingredient_aliases",
            "ingredient_id",
            "INTEGER",
        )
        ensure_column(
            conn,
            "ingredient_aliases",
            "alias",
            "TEXT",
        )
        ensure_column(
            conn,
            "jurisdictions",
            "name",
            "TEXT",
        )
        ensure_column(
            conn,
            "regulatory_records",
            "ingredient_id",
            "INTEGER",
        )
        ensure_column(
            conn,
            "regulatory_records",
            "jurisdiction_id",
            "INTEGER",
        )

        ingredient_ids = {}

        for item in INGREDIENTS:
            ingredient_ids[item["name"]] = (
                get_or_create_ingredient(
                    conn,
                    item,
                )
            )

        jurisdiction_ids = {}

        for name in {
            record["jurisdiction"]
            for record in RECORDS
        }:
            jurisdiction_ids[name] = get_jurisdiction(
                conn,
                name,
            )

        for record in RECORDS:
            upsert_record(
                conn,
                record,
                ingredient_ids[
                    record["ingredient"]
                ],
                jurisdiction_ids[
                    record["jurisdiction"]
                ],
            )

        conn.commit()

        count = conn.execute(
            "SELECT COUNT(*) FROM regulatory_records"
        ).fetchone()[0]

        print("✅ Missing regulatory records added")
        print(
            f"Total regulatory records now: {count}"
        )
        print(
            "Added:"
        )
        print(
            "  • Caramel IV (INS 150d) — India"
        )
        print(
            "  • Caramel IV (INS 150d) — United States"
        )
        print(
            "  • Disodium 5'-ribonucleotides (INS 635) — India"
        )

    finally:
        conn.close()


if __name__ == "__main__":
    main()
