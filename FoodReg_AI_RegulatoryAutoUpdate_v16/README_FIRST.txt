FOODREG AI - REGULATORY AUTO-UPDATE ENGINE

1. Replace your existing app.py with this folder's app.py.
2. Copy regulatory_update_engine.py beside app.py.
3. Start FoodReg AI normally:
   python -m streamlit run app.py
4. Open the sidebar -> Regulatory Update Center -> Check official sources now.
5. For scheduled checks, run run_regulatory_update.bat using Windows Task Scheduler.

IMPORTANT:
The updater monitors authoritative source changes and creates a pending review event. It does NOT silently rewrite legal/regulatory statuses. A changed source must be reviewed before your regulatory_records table is changed.

The updater creates its own audit tables inside foodreg.db:
- regulatory_source_registry
- regulatory_source_snapshots
- regulatory_update_runs
- regulatory_change_events

It does not alter the schema of regulatory_records.
