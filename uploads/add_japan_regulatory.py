import sqlite3

DB_PATH = "foodreg.db"
TODAY = "2026-10-04"

SOURCE_URL = (
    "https://www.mhlw.go.jp/stf/seisakunitsuite/"
    "bunya/kenkou_iryou/shokuhin/syokuten/"
    "kouteisho9e.html"
)

SOURCE_DOCUMENT = (
    "MHLW 9th Edition Official Compendium of Food Additives "
    "and Standards for Foods, Additives, etc."
)

RECORDS = [
    {
        "ingredient": "citric acid",
        "label": (
            "Japan's MHLW framework lists citric acid as a food additive; "
            "an official MHLW notice identifies anhydrous citric acid for "
            "use as a food acidulant."
        ),
        "restriction": (
            "Condition type: Japan-specific additive/use-standard check. "
            "The intended food use must comply with the applicable Japanese "
            "food-additive standards and use requirements."
        ),
        "reason": (
            "MHLW Food Sanitation Act framework and official notice on "
            "citric acid as a food acidulant."
        ),
    },
    {
        "ingredient": "guar gum",
        "label": (
            "MHLW's official food-additive standards include a Japanese "
            "specification monograph for Guar Gum (グァーガム)."
        ),
        "restriction": (
            "Condition type: additive specification / use-standard check. "
            "The official monograph sets identity and purity specifications; "
            "the applicable food-use standard must also be checked."
        ),
        "reason": (
            "MHLW Standards for Foods, Additives, etc. contain the Guar Gum "
            "specification monograph."
        ),
    },
    {
        "ingredient": "potassium chloride",
        "label": (
            "MHLW's official food-additive standards include Potassium "
            "Chloride (塩化カリウム) with a defined specification."
        ),
        "restriction": (
            "Condition type: additive specification / use-standard check. "
            "The food-use purpose and applicable Japanese use standards "
            "must be checked for the product."
        ),
        "reason": (
            "MHLW Standards for Foods, Additives, etc. include the "
            "Potassium Chloride specification."
        ),
    },
    {
        "ingredient": "sodium carbonate",
        "label": (
            "MHLW's official food-additive standards include Sodium "
            "Carbonate (炭酸ナトリウム) with a defined specification."
        ),
        "restriction": (
            "Condition type: additive specification / use-standard check. "
            "The applicable Japanese food-use requirement must be checked."
        ),
        "reason": (
            "MHLW Standards for Foods, Additives, etc. include the "
            "Sodium Carbonate specification."
        ),
    },
    {
        "ingredient": "caramel iv",
        "label": (
            "MHLW's official food-additive standards contain a dedicated "
            "Caramel IV (Sulfite ammonia caramel) specification."
        ),
        "restriction": (
            "Condition type: additive specification / use-standard check. "
            "The Japanese use standard for the intended food application "
            "must be checked separately from the quality specification."
        ),
        "reason": (
            "MHLW Standards for Foods, Additives, etc. contain the "
            "Caramel IV (Sulfite ammonia caramel) monograph."
        ),
    },
    {
        "ingredient": "disodium 5'-ribonucleotides",
        "label": (
            "MHLW's food-additive framework includes Disodium "
            "5'-Ribonucleotide (5'-リボヌクレオチド二ナトリウム), "
            "and the official compendium contains its food analysis method."
        ),
        "restriction": (
            "Condition type: additive specification / use-standard check. "
            "The applicable Japanese use standard for the food category "
            "must be checked for the specific product."
        ),
        "reason": (
            "MHLW official food-additive list/framework and the official "
            "food testing material for Disodium 5'-Ribonucleotide."
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
    row = conn.execute(
        """
        SELECT id, rowid
        FROM jurisdictions
        WHERE name = 'Japan'
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
                "Japan",
                "JP",
                "COUNTRY",
                "Ministry of Health, Labour and Welfare (MHLW)",
                SOURCE_URL,
                SOURCE_URL,
                "VERIFIED_SOURCE",
                6,
                (
                    "Official MHLW food-additive standards and "
                    "Food Sanitation Act framework. Ingredient use "
                    "must be checked against applicable Japanese "
                    "use standards."
                ),
            ),
        )

        row = conn.execute(
            """
            SELECT id, rowid
            FROM jurisdictions
            WHERE name = 'Japan'
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
            "CHECK_CONDITIONS",
            item["label"],
            item["restriction"],
            item["reason"],
            "Ministry of Health, Labour and Welfare (MHLW)",
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
            f"✅ Japan records added/updated: {added}"
        )
        print(
            f"Japan regulatory records in database: {total}"
        )

    finally:
        conn.close()


if __name__ == "__main__":
    main()
