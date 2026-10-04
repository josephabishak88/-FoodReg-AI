from __future__ import annotations

import shutil
import sqlite3
import tempfile
import unittest
from pathlib import Path

import regulatory_document_intelligence as docintel
import regulatory_update_engine as updater


class FoodRegCoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="foodreg_test_"))
        self.db = self.tmp / "foodreg.db"
        updater.DB_PATH = self.db
        with sqlite3.connect(self.db) as conn:
            conn.executescript(
                """
                CREATE TABLE ingredients (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    canonical_name TEXT UNIQUE NOT NULL,
                    ins_code TEXT,
                    cas_number TEXT,
                    description TEXT
                );
                CREATE TABLE ingredient_aliases (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ingredient_id INTEGER NOT NULL,
                    alias TEXT NOT NULL,
                    UNIQUE (ingredient_id, alias)
                );
                CREATE TABLE jurisdictions (
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
                );
                CREATE TABLE regulatory_records (
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
                );
                INSERT INTO ingredients(canonical_name, ins_code) VALUES ('Citric Acid','330');
                INSERT INTO ingredient_aliases(ingredient_id, alias) VALUES (1,'citric acid');
                INSERT INTO jurisdictions(name, authority, priority) VALUES ('Testland','Test Authority',1);
                INSERT INTO regulatory_records(ingredient_id, jurisdiction_id, status, label, authority)
                    VALUES (1,1,'NO_RESTRICTION','Permitted','Test Authority');
                """
            )
        updater.ensure_update_schema()

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_document_extraction(self) -> None:
        text = (
            "Citric Acid (INS 330) is restricted to beverages with a maximum "
            "level of 500 mg/kg. Effective date: 2026-10-01."
        )
        proposals = docintel.extract_regulatory_proposals(
            text,
            [{"canonical_name": "Citric Acid", "ins_code": "330", "aliases": ["citric acid"]}],
            "Testland",
            "Test Authority",
        )
        self.assertTrue(proposals)
        self.assertEqual(proposals[0]["status"], "RESTRICTED")
        self.assertEqual(proposals[0]["maximum_level"], "500")
        self.assertEqual(proposals[0]["unit"], "mg/kg")

    def test_approval_creates_record_version(self) -> None:
        proposals = updater.propose_document_changes(
            "Citric Acid (INS 330) is restricted to beverages with a maximum level of 500 mg/kg.",
            "Testland",
            "Test Authority",
            source_url="https://example.invalid/rule.pdf",
            source_document="rule.pdf",
        )
        self.assertTrue(proposals)
        with sqlite3.connect(self.db) as conn:
            proposal_id = conn.execute(
                "SELECT id FROM regulatory_document_proposals ORDER BY id DESC LIMIT 1"
            ).fetchone()[0]
        result = updater.approve_proposal(proposal_id, reviewer="test", note="Fixture approval")
        self.assertTrue(result["ok"])
        with sqlite3.connect(self.db) as conn:
            status = conn.execute(
                "SELECT status, maximum_level, unit FROM regulatory_records WHERE ingredient_id=1 AND jurisdiction_id=1"
            ).fetchone()
            versions = conn.execute("SELECT COUNT(*) FROM regulatory_record_versions").fetchone()[0]
            state = conn.execute(
                "SELECT proposal_state FROM regulatory_document_proposals WHERE id=?", (proposal_id,)
            ).fetchone()[0]
        self.assertEqual(status, ("RESTRICTED", "500", "mg/kg"))
        self.assertEqual(versions, 1)
        self.assertEqual(state, "APPROVED")


if __name__ == "__main__":
    unittest.main(verbosity=2)
