import sqlite3
from pathlib import Path


DB_PATH = Path(__file__).resolve().parent / "foodreg.db"


def get_connection():
    return sqlite3.connect(DB_PATH)


def create_database():

    conn = get_connection()
    cursor = conn.cursor()

    # =====================================================
    # INGREDIENTS
    # =====================================================

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS ingredients (
            ingredient_id INTEGER PRIMARY KEY AUTOINCREMENT,
            canonical_name TEXT NOT NULL UNIQUE,
            ins_number TEXT,
            e_number TEXT,
            cas_number TEXT,
            functional_class TEXT
        )
    """)


    # =====================================================
    # ALIASES
    # =====================================================

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS ingredient_aliases (
            alias_id INTEGER PRIMARY KEY AUTOINCREMENT,
            ingredient_id INTEGER NOT NULL,
            alias TEXT NOT NULL,
            FOREIGN KEY (ingredient_id)
                REFERENCES ingredients(ingredient_id),
            UNIQUE(ingredient_id, alias)
        )
    """)


    # =====================================================
    # JURISDICTIONS
    # =====================================================

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS jurisdictions (
            jurisdiction_id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE,
            code TEXT,
            jurisdiction_type TEXT,
            authority TEXT,
            official_source TEXT
        )
    """)


    # =====================================================
    # REGULATORY RECORDS
    # =====================================================

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS regulatory_records (
            record_id INTEGER PRIMARY KEY AUTOINCREMENT,

            ingredient_id INTEGER NOT NULL,

            jurisdiction_id INTEGER NOT NULL,

            status TEXT NOT NULL,

            label TEXT,

            restriction TEXT,

            reason TEXT,

            food_category TEXT,

            maximum_level TEXT,

            unit TEXT,

            conditions TEXT,

            authority TEXT,

            source_url TEXT,

            source_document TEXT,

            effective_date TEXT,

            verified_date TEXT,

            source_type TEXT,

            notes TEXT,

            FOREIGN KEY (ingredient_id)
                REFERENCES ingredients(ingredient_id),

            FOREIGN KEY (jurisdiction_id)
                REFERENCES jurisdictions(jurisdiction_id),

            UNIQUE(
                ingredient_id,
                jurisdiction_id
            )
        )
    """)


    # =====================================================
    # INDEXES
    # =====================================================

    cursor.execute("""
        CREATE INDEX IF NOT EXISTS
        idx_ingredient_name
        ON ingredients(canonical_name)
    """)

    cursor.execute("""
        CREATE INDEX IF NOT EXISTS
        idx_alias_name
        ON ingredient_aliases(alias)
    """)

    cursor.execute("""
        CREATE INDEX IF NOT EXISTS
        idx_record_ingredient
        ON regulatory_records(ingredient_id)
    """)

    cursor.execute("""
        CREATE INDEX IF NOT EXISTS
        idx_record_jurisdiction
        ON regulatory_records(jurisdiction_id)
    """)


    conn.commit()
    conn.close()


if __name__ == "__main__":

    create_database()

    print("=" * 60)
    print("FoodReg AI database created successfully.")
    print(f"Database: {DB_PATH}")
    print("=" * 60)