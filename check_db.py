import sqlite3

conn = sqlite3.connect("foodreg.db")

query = """
SELECT
    i.canonical_name,
    i.ins_code,
    j.name,
    r.status
FROM regulatory_records r
JOIN ingredients i
    ON r.ingredient_id = i.id
JOIN jurisdictions j
    ON r.jurisdiction_id = j.id
WHERE i.canonical_name IN (
    'caramel iv',
    "disodium 5'-ribonucleotides"
)
ORDER BY i.canonical_name, j.name
"""

rows = conn.execute(query).fetchall()

print("\nRegulatory records:\n")

for row in rows:
    print(row)

conn.close()