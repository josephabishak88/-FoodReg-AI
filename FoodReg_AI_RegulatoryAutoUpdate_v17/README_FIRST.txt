FOODREG AI V17

1. Replace your existing app.py with the included app.py.
2. Keep regulatory_update_engine.py in the same folder as app.py.
3. Do NOT replace foodreg.db.
4. Run: python -m streamlit run app.py

V17 adds a Regulatory Update Center inside the app. It monitors configured official source pages,
records source changes, and queues them for human review. It does NOT silently edit regulatory_records.

Optional command-line monitor: run_regulatory_update.bat

The updater stores its own tables in foodreg.db:
- regulatory_source_registry
- regulatory_source_snapshots
- regulatory_update_runs
- regulatory_change_events

A source change is evidence that the source changed, not proof that the law changed. Human verification
is required before legal/regulatory records are modified.
