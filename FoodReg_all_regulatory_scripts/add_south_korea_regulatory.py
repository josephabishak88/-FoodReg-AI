import sqlite3

DB_PATH = "foodreg.db"
TODAY = "2026-10-04"

SOURCE_URL = (
    "https://www.mfds.go.kr/brd/m_211/view.do?"
    "Data_stts_gubun=C9999&seq=14980"
)

SOURCE_DOCUMENT = (
    "MFDS Food Additives Code — "
    "Food Additives Standards and Specifications "
    "(Notice No. 2026-50, 2026-07-13)"
)

# Conservative entries:
# The current MFDS Code is the controlling Korean source.
# The database records the verified regulatory framework reference,
# while the UI status remains CHECK_CONDITIONS so the app does not
# imply unrestricted authorization without checking the exact Korean
# food-category/use standard.
RECORDS = [
    {
        "ingredient": "citric acid",
        "label": (
            "MFDS maintains Citric Acid within the current Korean "
            "Food Additives Code framework."
        ),
        "restriction": (
            "Condition type: Korea-specific food-category/use-standard "
            "check. The current Korean Code must be checked for the "
            "specific food and permitted use."
        ),
        "reason": (
            "MFDS Food Additives Code, current notice No. 2026-50."
        ),
    },
    {
        "ingredient": "guar gum",
        "label": (
            "MFDS maintains Guar Gum within the current Korean "
            "Food Additives Code; MFDS amendments have also specified "
            "use-standard changes for Guar Gum."
        ),
        "restriction": (
            "Condition type: food-category/use standard. Korean rules "
            "can include category-specific maximum-use requirements; "
            "the current Code must be checked for the intended food."
        ),
        "reason": (
            "MFDS Food Additives Code and MFDS published amendments "
            "concerning Guar Gum use standards."
        ),
    },
    {
        "ingredient": "potassium chloride",
        "label": (
            "MFDS maintains Potassium Chloride within the Korean "
            "Food Additives Code framework."
        ),
        "restriction": (
            "Condition type: Korea-specific food-category/use-standard "
            "check. Confirm the current Korean Code for the intended "
            "food application."
        ),
        "reason": (
            "MFDS Food Additives Code, current notice No. 2026-50."
        ),
    },
    {
        "ingredient": "sodium carbonate",
        "label": (
            "MFDS maintains Sodium Carbonate within the Korean "
            "Food Additives Code framework."
        ),
        "restriction": (
            "Condition type: food-category/use-standard check. "
            "The current Korean Code must be checked for the exact "
            "food category and permitted use."
        ),
        "reason": (
            "MFDS Food Additives Code, current notice No. 2026-50."
        ),
    },
    {
        "ingredient": "caramel iv",
        "label": (
            "MFDS maintains caramel colouring specifications within "
            "the Korean Food Additives Code framework."
        ),
        "restriction": (
            "Condition type: additive specification + food-use "
            "standard check. The current Korean Code must be checked "
            "for the exact caramel class and food category."
        ),
        "reason": (
            "MFDS Food Additives Code, current notice No. 2026-50."
        ),
    },
    {
        "ingredient": "disodium 5'-ribonucleotides",
        "label": (
            "MFDS maintains nucleotide flavour-enhancer standards "
            "within the Korean Food Additives Code framework."
        ),
        "restriction": (
            "Condition type: food-category/use-standard check. "
            "The current Korean Code must be checked for the exact "
            "additive entry and food category."
        ),
        "reason": (
            "MFDS Food Additives Code, current notice No. 2026-50."
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
    name = "South Korea"

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
                "South Korea",
                "KR",
                "COUNTRY",
                "Ministry of Food and Drug Safety (MFDS)",
                SOURCE_URL,
                SOURCE_URL,
                "VERIFIED_SOURCE",
                9,
                (
                    "The Korean version of the MFDS Food Additives Code "
                    "is the legally controlling source. English versions "
                    "are provided for reference only."
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
            "CHECK_CONDITIONS",
            item["label"],
            item["restriction"],
            item["reason"],
            "Ministry of Food and Drug Safety (MFDS)",
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
            f"✅ South Korea records added/updated: {added}"
        )
        print(
            f"South Korea regulatory records in database: {total}"
        )
        print(
            "ℹ️ South Korea records use CHECK_CONDITIONS; "
            "the Korean MFDS Code is the controlling legal source."
        )

    finally:
        conn.close()


if __name__ == "__main__":
    main()
