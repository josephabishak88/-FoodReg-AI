import sqlite3
from pathlib import Path


DB_PATH = Path(__file__).resolve().parent / "foodreg.db"


def get_connection():
    return sqlite3.connect(DB_PATH)


def get_ingredient_id(
    cursor,
    canonical_name,
    ins_number=None,
    e_number=None
):

    cursor.execute(
        """
        INSERT INTO ingredients (
            canonical_name,
            ins_number,
            e_number
        )
        VALUES (?, ?, ?)
        ON CONFLICT(canonical_name)
        DO UPDATE SET
            ins_number = excluded.ins_number,
            e_number = excluded.e_number
        """,
        (
            canonical_name,
            ins_number,
            e_number
        )
    )

    cursor.execute(
        """
        SELECT ingredient_id
        FROM ingredients
        WHERE canonical_name = ?
        """,
        (canonical_name,)
    )

    return cursor.fetchone()[0]


def get_jurisdiction_id(
    cursor,
    name,
    code,
    jurisdiction_type,
    authority,
    official_source
):

    cursor.execute(
        """
        INSERT INTO jurisdictions (
            name,
            code,
            jurisdiction_type,
            authority,
            official_source
        )
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(name)
        DO UPDATE SET
            code = excluded.code,
            authority = excluded.authority,
            official_source = excluded.official_source
        """,
        (
            name,
            code,
            jurisdiction_type,
            authority,
            official_source
        )
    )

    cursor.execute(
        """
        SELECT jurisdiction_id
        FROM jurisdictions
        WHERE name = ?
        """,
        (name,)
    )

    return cursor.fetchone()[0]


def add_alias(
    cursor,
    ingredient_id,
    alias
):

    cursor.execute(
        """
        INSERT OR IGNORE INTO ingredient_aliases (
            ingredient_id,
            alias
        )
        VALUES (?, ?)
        """,
        (
            ingredient_id,
            alias
        )
    )


def add_regulatory_record(
    cursor,
    ingredient_id,
    jurisdiction_id,
    data
):

    cursor.execute(
        """
        INSERT INTO regulatory_records (
            ingredient_id,
            jurisdiction_id,
            status,
            label,
            restriction,
            reason,
            food_category,
            maximum_level,
            unit,
            conditions,
            authority,
            source_url,
            source_document,
            effective_date,
            verified_date,
            source_type,
            notes
        )
        VALUES (
            ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
            ?, ?, ?, ?, ?, ?, ?
        )

        ON CONFLICT(
            ingredient_id,
            jurisdiction_id
        )
        DO UPDATE SET

            status = excluded.status,
            label = excluded.label,
            restriction = excluded.restriction,
            reason = excluded.reason,
            food_category = excluded.food_category,
            maximum_level = excluded.maximum_level,
            unit = excluded.unit,
            conditions = excluded.conditions,
            authority = excluded.authority,
            source_url = excluded.source_url,
            source_document = excluded.source_document,
            effective_date = excluded.effective_date,
            verified_date = excluded.verified_date,
            source_type = excluded.source_type,
            notes = excluded.notes
        """,
        (
            ingredient_id,
            jurisdiction_id,

            data.get("status"),
            data.get("label"),
            data.get("restriction"),
            data.get("reason"),
            data.get("food_category"),
            data.get("maximum_level"),
            data.get("unit"),
            data.get("conditions"),
            data.get("authority"),
            data.get("source_url"),
            data.get("source_document"),
            data.get("effective_date"),
            data.get("verified"),
            data.get("source_type"),
            data.get("notes"),
        )
    )


def seed_database():

    conn = get_connection()
    cursor = conn.cursor()


    # =====================================================
    # JURISDICTIONS
    # =====================================================

    jurisdictions = {

        "India": {
            "code": "IN",
            "type": "country",
            "authority": "FSSAI",
            "source": (
                "https://fssai.gov.in/"
                "food-law/regulations/"
            ),
        },

        "Great Britain": {
            "code": "GB",
            "type": "jurisdiction",
            "authority": "Food Standards Agency",
            "source": (
                "https://data.food.gov.uk/"
                "regulated-products/"
            ),
        },

        "United States": {
            "code": "US",
            "type": "country",
            "authority": "FDA",
            "source": (
                "https://www.fda.gov/food"
            ),
        },

        "European Union": {
            "code": "EU",
            "type": "jurisdiction",
            "authority": "European Commission",
            "source": (
                "https://food.ec.europa.eu/"
                "food-safety/food-improvement-agents/"
                "additives/database_en"
            ),
        },
    }


    jurisdiction_ids = {}

    for name, data in jurisdictions.items():

        jurisdiction_ids[name] = get_jurisdiction_id(
            cursor,

            name,

            data["code"],

            data["type"],

            data["authority"],

            data["source"]
        )


    # =====================================================
    # SODIUM BENZOATE
    # =====================================================

    sodium_benzoate_id = get_ingredient_id(
        cursor,
        "sodium benzoate",
        "211",
        "E211"
    )


    sodium_benzoate_aliases = [
        "sodium benzoate",
        "sodium benzoat",
        "benzoate of soda",
        "e211",
        "ins 211",
        "ins211",
        "211",
    ]


    for alias in sodium_benzoate_aliases:

        add_alias(
            cursor,
            sodium_benzoate_id,
            alias
        )


    sodium_benzoate_records = {

        "India": {
            "status": "LISTED",
            "label": "Listed as a food additive",
            "restriction": (
                "Use is subject to the applicable "
                "food-category conditions and limits."
            ),
            "reason": (
                "Prototype regulatory record."
            ),
            "authority": "FSSAI",
            "source_url": (
                "https://fssai.gov.in/"
                "food-law/regulations/"
            ),
            "verified": "2026-10-03",
            "source_type": "PROTOTYPE",
        },

        "Great Britain": {
            "status": "AUTHORISED",
            "label": "Authorised subject to conditions",
            "restriction": (
                "Conditions of use may apply."
            ),
            "reason": (
                "Prototype regulatory record."
            ),
            "authority": "Food Standards Agency",
            "source_url": (
                "https://data.food.gov.uk/"
                "regulated-products/"
            ),
            "verified": "2026-10-03",
            "source_type": "PROTOTYPE",
        },

        "United States": {
            "status": "REGULATED",
            "label": "Regulated under applicable requirements",
            "restriction": (
                "Applicable regulatory conditions apply."
            ),
            "reason": (
                "Prototype regulatory record."
            ),
            "authority": "FDA",
            "source_url": (
                "https://www.fda.gov/food"
            ),
            "verified": "2026-10-03",
            "source_type": "PROTOTYPE",
        },

        "European Union": {
            "status": "CHECK_CONDITIONS",
            "label": "Check applicable conditions of use",
            "restriction": (
                "Authorisation depends on applicable "
                "food category and conditions."
            ),
            "reason": (
                "Prototype regulatory record."
            ),
            "authority": "European Commission",
            "source_url": (
                "https://food.ec.europa.eu/"
                "food-safety/food-improvement-agents/"
                "additives/database_en"
            ),
            "verified": "2026-10-03",
            "source_type": "PROTOTYPE",
        },
    }


    for country, data in sodium_benzoate_records.items():

        add_regulatory_record(
            cursor,

            sodium_benzoate_id,

            jurisdiction_ids[country],

            data
        )


    # =====================================================
    # AMARANTH
    # =====================================================

    amaranth_id = get_ingredient_id(
        cursor,
        "amaranth",
        "123",
        "E123"
    )


    amaranth_aliases = [
        "amaranth",
        "e123",
        "ins 123",
        "ins123",
        "123",
        "fd&c red no. 2",
        "fdc red 2",
    ]


    for alias in amaranth_aliases:

        add_alias(
            cursor,
            amaranth_id,
            alias
        )


    amaranth_records = {

        "India": {
            "status": "IDENTIFIED",
            "label": "Additive identity identified",
            "restriction": (
                "Specific permitted uses must be "
                "verified against applicable regulations."
            ),
            "reason": (
                "Prototype regulatory record."
            ),
            "authority": "FSSAI",
            "source_url": (
                "https://fssai.gov.in/"
            ),
            "verified": "2026-10-03",
            "source_type": "PROTOTYPE",
        },

        "United States": {
            "status": "NOT_AUTHORISED",
            "label": "Not authorised in prototype record",
            "restriction": (
                "Prototype record treats the substance "
                "as not authorised for domestic food use."
            ),
            "reason": (
                "Prototype regulatory record."
            ),
            "authority": "FDA",
            "source_url": (
                "https://www.fda.gov/food"
            ),
            "verified": "2026-10-03",
            "source_type": "PROTOTYPE",
        },

        "Great Britain": {
            "status": "CHECK",
            "label": "Requires current verification",
            "restriction": (
                "Do not infer authorisation from the "
                "INS number alone."
            ),
            "reason": (
                "Prototype regulatory record."
            ),
            "authority": "Food Standards Agency",
            "source_url": (
                "https://data.food.gov.uk/"
                "regulated-products/"
            ),
            "verified": "2026-10-03",
            "source_type": "PROTOTYPE",
        },

        "European Union": {
            "status": "CHECK",
            "label": "Requires Union-list verification",
            "restriction": (
                "Do not infer authorisation from the "
                "E-number alone."
            ),
            "reason": (
                "Prototype regulatory record."
            ),
            "authority": "European Commission",
            "source_url": (
                "https://food.ec.europa.eu/"
                "food-safety/food-improvement-agents/"
                "additives/database_en"
            ),
            "verified": "2026-10-03",
            "source_type": "PROTOTYPE",
        },
    }


    for country, data in amaranth_records.items():

        add_regulatory_record(
            cursor,

            amaranth_id,

            jurisdiction_ids[country],

            data
        )


    conn.commit()
    conn.close()


if __name__ == "__main__":

    seed_database()

    print("=" * 60)
    print("Prototype regulatory data added.")
    print("Database: foodreg.db")
    print("=" * 60)