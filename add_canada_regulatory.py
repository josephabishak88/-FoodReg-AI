import sqlite3

DB_PATH = "foodreg.db"
TODAY = "2026-10-04"

RECORDS = [
    {
        "ingredient": "caramel iv",
        "label": (
            "Health Canada lists Caramel as a permitted food colour; "
            "CFIA identifies Caramel with E150a, E150b, E150c and E150d."
        ),
        "restriction": (
            "Use depends on the permitted food categories and conditions "
            "in the List of Permitted Food Colours. Most listed uses are "
            "Good Manufacturing Practice, with some category-specific limits."
        ),
        "reason": (
            "Health Canada List of Permitted Food Colours; "
            "CFIA food-colours reference maps Caramel to E150d."
        ),
        "source": (
            "https://www.canada.ca/en/health-canada/services/food-nutrition/"
            "food-safety/food-additives/lists-permitted/3-colouring-agents.html"
        ),
        "document": "Health Canada List of Permitted Food Colours",
    },
    {
        "ingredient": "citric acid",
        "label": (
            "Health Canada lists Citric Acid as a permitted food additive "
            "with uses including preservative and sequestering-agent functions."
        ),
        "restriction": (
            "Permitted use is food-category specific. Several entries use "
            "Good Manufacturing Practice, while other categories have "
            "specific maximum levels or combined-use conditions."
        ),
        "reason": (
            "Health Canada Lists of Permitted Food Additives, including "
            "the Preservatives and Sequestering Agents lists."
        ),
        "source": (
            "https://www.canada.ca/en/health-canada/services/food-nutrition/"
            "food-safety/food-additives/lists-permitted.html"
        ),
        "document": "Health Canada Lists of Permitted Food Additives",
    },
    {
        "ingredient": "guar gum",
        "label": (
            "Health Canada lists Guar Gum as a permitted emulsifying, "
            "stabilizing or thickening agent."
        ),
        "restriction": (
            "Use is food-category specific. Conditions include GMP in some "
            "categories and numerical maximums such as 5,000 ppm or 1.0% "
            "in specified foods."
        ),
        "reason": (
            "Health Canada List of Permitted Emulsifying, Gelling, "
            "Stabilizing or Thickening Agents."
        ),
        "source": (
            "https://www.canada.ca/en/health-canada/services/food-nutrition/"
            "food-safety/food-additives/lists-permitted/"
            "4-emulsifying-gelling-stabilizing-thickening-agents.html"
        ),
        "document": (
            "Health Canada List of Permitted Emulsifying, Gelling, "
            "Stabilizing or Thickening Agents"
        ),
    },
    {
        "ingredient": "potassium chloride",
        "label": (
            "Health Canada lists Potassium Chloride as a permitted food "
            "additive for specified uses."
        ),
        "restriction": (
            "Use is food-category specific. The current acidity-regulators "
            "list, for example, specifies Potassium Chloride for beer at GMP."
        ),
        "reason": (
            "Health Canada List of Permitted Acidity Regulators and "
            "Acid-Reacting Materials."
        ),
        "source": (
            "https://www.canada.ca/en/health-canada/services/food-nutrition/"
            "food-safety/food-additives/lists-permitted/"
            "10-adjusting-agents.html"
        ),
        "document": (
            "Health Canada List of Permitted Acidity Regulators and "
            "Acid-Reacting Materials"
        ),
    },
    {
        "ingredient": "sodium carbonate",
        "label": (
            "Health Canada lists Sodium Carbonate as a permitted additive "
            "for specified food uses."
        ),
        "restriction": (
            "Use is food-category specific. Conditions include GMP in "
            "specified categories and additional combined-use or maximum-"
            "level requirements for some foods."
        ),
        "reason": (
            "Health Canada Lists of Permitted Food Additives, including "
            "Acidity Regulators and Starch-Modifying Agents."
        ),
        "source": (
            "https://www.canada.ca/en/health-canada/services/food-nutrition/"
            "food-safety/food-additives/lists-permitted.html"
        ),
        "document": "Health Canada Lists of Permitted Food Additives",
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
    row = conn.execute(
        """
        SELECT id, rowid
        FROM jurisdictions
        WHERE name = 'Canada'
        """
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
                "Canada",
                "CA",
                "COUNTRY",
                "Health Canada",
                "https://www.canada.ca/en/health-canada/"
                "services/food-nutrition/food-safety/"
                "food-additives/lists-permitted.html",
                "https://www.canada.ca/en/health-canada/"
                "services/food-nutrition/food-safety/"
                "food-additives/lists-permitted.html",
                "VERIFIED_SOURCE",
                4,
                "Official Health Canada permitted-food-additives lists.",
            ),
        )

        row = conn.execute(
            """
            SELECT id, rowid
            FROM jurisdictions
            WHERE name = 'Canada'
            """
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


def get_ingredient_id(conn, name):
    row = conn.execute(
        """
        SELECT id, rowid
        FROM ingredients
        WHERE canonical_name = ?
        """,
        (name,),
    ).fetchone()

    if row is None:
        raise RuntimeError(
            f"Ingredient '{name}' is not present in foodreg.db"
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
            "Health Canada",
            item["source"],
            item["document"],
            TODAY,
            "OFFICIAL_REFERENCE",
        ),
    )


def main():
    conn = sqlite3.connect(DB_PATH)

    try:
        # Compatibility with the current/legacy schema.
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
            f"✅ Canada records added/updated: {added}"
        )
        print(
            f"Canada regulatory records in database: {total}"
        )
        print(
            "ℹ️ INS 635 was not added because a sufficiently direct "
            "current official Health Canada source was not verified."
        )

    finally:
        conn.close()


if __name__ == "__main__":
    main()
