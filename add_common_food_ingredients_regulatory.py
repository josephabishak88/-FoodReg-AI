import sqlite3
from pathlib import Path
from datetime import date

DB_PATH = Path(__file__).with_name('foodreg.db')
TODAY = date.today().isoformat()

# Official source references used for this first ordinary-food coverage pass.
SOURCES = {
    'India': {
        'authority': 'Food Safety and Standards Authority of India (FSSAI)',
        'url': 'https://fssai.gov.in/food-law/regulations/compendium/food-products-standards',
        'document': 'Food Safety and Standards (Food Products Standards and Food Additives) Regulations, 2011 — product-standard chapters',
        'status': 'CHECK_CONDITIONS',
        'condition': 'Product-category standard and applicable quality, safety and labelling requirements apply; exact standard depends on the food form/category.',
    },
    'United States': {
        'authority': 'U.S. Food and Drug Administration (FDA)',
        'url': 'https://www.fda.gov/food/nutrition-food-labeling-and-critical-foods/standards-identity-food',
        'document': 'FDA Standards of Identity for Food; applicable 21 CFR food standards and general food law',
        'status': 'CHECK_CONDITIONS',
        'condition': 'Applicable food standard, composition rule, and labelling requirements depend on the product and ingredient form.',
    },
    'European Union': {
        'authority': 'European Commission / EUR-Lex',
        'url': 'https://eur-lex.europa.eu/eli/reg/2008/1333/2026-08-18/eng',
        'document': 'Regulation (EC) No 1333/2008 on food additives, consolidated 2026; Regulation (EU) No 1169/2011 on food information to consumers',
        'status': 'CHECK_CONDITIONS',
        'condition': 'Ordinary food ingredients are governed by the applicable food/product and information rules; additive authorisation is a separate framework. Exact requirements depend on the food/category.',
    },
    'Canada': {
        'authority': 'Canadian Food Inspection Agency (CFIA)',
        'url': 'https://inspection.canada.ca/en/about-cfia/acts-and-regulations/list-acts-and-regulations/documents-incorporated-reference/canadian-food-compositional-standards-0',
        'document': 'Canadian Food Compositional Standards (CFCS), incorporated by reference into the Food and Drug Regulations',
        'status': 'CHECK_CONDITIONS',
        'condition': 'Compositional standards apply to defined food products; exact requirements depend on the product standard and ingredient form.',
    },
    'Australia/New Zealand': {
        'authority': 'Food Standards Australia New Zealand (FSANZ)',
        'url': 'https://www.foodstandards.gov.au/food-standards-code/legislation',
        'document': 'Australia New Zealand Food Standards Code — applicable food/product, ingredient and labelling standards',
        'status': 'CHECK_CONDITIONS',
        'condition': 'Applicable Food Standards Code requirements depend on the food category, composition and labelling context.',
    },
    'Great Britain': {
        'authority': 'UK Food Standards Agency (FSA)',
        'url': 'https://www.food.gov.uk/print/pdf/node/355',
        'document': 'FSA General Food Law overview for Great Britain; applicable domestic and assimilated food law',
        'status': 'CHECK_CONDITIONS',
        'condition': 'Food must comply with applicable GB food safety, composition and labelling law; exact product rules depend on the food category.',
    },
    'Northern Ireland': {
        'authority': 'UK Food Standards Agency (FSA) / EU food law framework',
        'url': 'https://www.food.gov.uk/print/pdf/node/355',
        'document': 'FSA General Food Law overview; EU food law continues to apply to food in Northern Ireland in the relevant circumstances',
        'status': 'CHECK_CONDITIONS',
        'condition': 'Applicable EU food law and Northern Ireland domestic enforcement requirements depend on the product and circumstances.',
    },
}

INGREDIENT_NOTES = {
    'wheat flour': ('Wheat Flour', None, 'Cereal/flour ingredient; product standard and allergen/labelling rules may apply.'),
    'salt': ('Salt', None, 'Salt/seasoning ingredient; composition and product-standard rules may apply.'),
    'sugar': ('Sugar', None, 'Sugar/sweetening ingredient; product-standard and labelling requirements may apply.'),
    'edible starch': ('Edible Starch', None, 'Starch ingredient; requirements depend on source, processing and product category.'),
    'edible vegetable oil': ('Edible Vegetable Oil', None, 'Edible oil ingredient; identity/composition and labelling requirements may apply.'),
    'wheat gluten': ('Wheat Gluten', None, 'Wheat/gluten ingredient; allergen declaration requirements may apply.'),
    'hydrolysed groundnut protein': ('Hydrolysed Groundnut Protein', None, 'Groundnut/peanut-derived protein ingredient; allergen and composition requirements may apply.'),
    'mixed spices': ('Mixed Spices', None, 'Composite spice ingredient; exact requirements depend on constituent spices, composition and food category.'),
}


def ensure_column(conn, table, column, sql_type):
    cols = {row[1] for row in conn.execute(f'PRAGMA table_info({table})').fetchall()}
    if column not in cols:
        conn.execute(f'ALTER TABLE {table} ADD COLUMN {column} {sql_type}')


def ensure_schema(conn):
    conn.execute('''
        CREATE TABLE IF NOT EXISTS ingredients (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            canonical_name TEXT UNIQUE NOT NULL,
            ins_code TEXT,
            cas_number TEXT,
            description TEXT
        )
    ''')
    conn.execute('''
        CREATE TABLE IF NOT EXISTS jurisdictions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE NOT NULL,
            code TEXT,
            type TEXT,
            authority TEXT,
            official_source TEXT,
            additive_source TEXT,
            data_status TEXT,
            priority INTEGER,
            notes TEXT
        )
    ''')
    conn.execute('''
        CREATE TABLE IF NOT EXISTS regulatory_records (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
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
            UNIQUE (ingredient_id, jurisdiction_id)
        )
    ''')

    for column, sql_type in [
        ('code', 'TEXT'), ('type', 'TEXT'), ('authority', 'TEXT'),
        ('official_source', 'TEXT'), ('additive_source', 'TEXT'),
        ('data_status', 'TEXT'), ('priority', 'INTEGER'), ('notes', 'TEXT'),
    ]:
        ensure_column(conn, 'jurisdictions', column, sql_type)

    for column, sql_type in [
        ('food_category', 'TEXT'), ('maximum_level', 'TEXT'), ('unit', 'TEXT'),
        ('conditions', 'TEXT'), ('source_document', 'TEXT'),
        ('verified_date', 'TEXT'), ('source_type', 'TEXT'), ('notes', 'TEXT'),
    ]:
        ensure_column(conn, 'regulatory_records', column, sql_type)


def get_or_create_ingredient(conn, canonical_name, description):
    row = conn.execute(
        'SELECT id FROM ingredients WHERE LOWER(TRIM(canonical_name)) = LOWER(TRIM(?))',
        (canonical_name,),
    ).fetchone()
    if row:
        return row[0]

    cur = conn.execute(
        'INSERT INTO ingredients (canonical_name, description) VALUES (?, ?)',
        (canonical_name, description),
    )
    return cur.lastrowid


def get_or_create_jurisdiction(conn, name, source):
    row = conn.execute(
        'SELECT id FROM jurisdictions WHERE name = ?',
        (name,),
    ).fetchone()
    if row:
        jurisdiction_id = row[0]
        conn.execute(
            '''UPDATE jurisdictions
               SET authority = ?, official_source = ?, additive_source = ?,
                   data_status = ?, notes = ?
               WHERE id = ?''',
            (
                source['authority'], source['url'], source['url'],
                'VERIFIED_SOURCE',
                source['document'],
                jurisdiction_id,
            ),
        )
        return jurisdiction_id

    cur = conn.execute(
        '''INSERT INTO jurisdictions
           (name, code, type, authority, official_source, additive_source,
            data_status, priority, notes)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)''',
        (
            name,
            '',
            'JURISDICTION',
            source['authority'],
            source['url'],
            source['url'],
            'VERIFIED_SOURCE',
            100,
            source['document'],
        ),
    )
    return cur.lastrowid


def upsert_record(conn, ingredient_id, jurisdiction_id, ingredient_name, source, note):
    label = 'Ordinary food ingredient / product-standard reference'
    reason = source['document']
    conn.execute(
        '''INSERT INTO regulatory_records
           (ingredient_id, jurisdiction_id, status, label, restriction,
            reason, food_category, maximum_level, unit, conditions,
            authority, source_url, source_document, verified_date,
            source_type, notes)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT(ingredient_id, jurisdiction_id)
           DO UPDATE SET
               status = excluded.status,
               label = excluded.label,
               restriction = excluded.restriction,
               reason = excluded.reason,
               conditions = excluded.conditions,
               authority = excluded.authority,
               source_url = excluded.source_url,
               source_document = excluded.source_document,
               verified_date = excluded.verified_date,
               source_type = excluded.source_type,
               notes = excluded.notes''',
        (
            ingredient_id,
            jurisdiction_id,
            source['status'],
            label,
            'Not treated as a blanket approval; exact product/category requirements must be checked.',
            reason,
            '',
            '',
            '',
            source['condition'],
            source['authority'],
            source['url'],
            source['document'],
            TODAY,
            'OFFICIAL_REFERENCE',
            note,
        ),
    )


def main():
    if not DB_PATH.exists():
        raise FileNotFoundError(f'FoodReg database not found: {DB_PATH}')

    conn = sqlite3.connect(DB_PATH)
    try:
        ensure_schema(conn)
        added_ingredients = 0
        updated_records = 0

        for key, (canonical, _ins, note) in INGREDIENT_NOTES.items():
            before = conn.execute(
                'SELECT COUNT(*) FROM ingredients WHERE LOWER(TRIM(canonical_name)) = LOWER(TRIM(?))',
                (canonical,),
            ).fetchone()[0]
            ingredient_id = get_or_create_ingredient(conn, canonical, note)
            if before == 0:
                added_ingredients += 1

            for jurisdiction_name, source in SOURCES.items():
                jurisdiction_id = get_or_create_jurisdiction(conn, jurisdiction_name, source)
                upsert_record(conn, ingredient_id, jurisdiction_id, canonical, source, note)
                updated_records += 1

        conn.commit()

        total_ingredients = conn.execute('SELECT COUNT(*) FROM ingredients').fetchone()[0]
        total_records = conn.execute('SELECT COUNT(*) FROM regulatory_records').fetchone()[0]

        print('✅ Common food-ingredient regulatory coverage added/updated')
        print(f'New ordinary ingredients added: {added_ingredients}')
        print(f'Regulatory records added/updated: {updated_records}')
        print(f'Ingredients in database: {total_ingredients}')
        print(f'Regulatory records in database: {total_records}')
        print('Jurisdictions covered in this pass: ' + ', '.join(SOURCES.keys()))
        print('')
        print('⚠️ These are product-standard/reference records, not blanket approvals.')
        print('Exact composition, food-category, allergen and labelling rules must be checked for the actual product.')
    finally:
        conn.close()


if __name__ == '__main__':
    main()
