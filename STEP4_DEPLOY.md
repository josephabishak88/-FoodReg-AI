# FoodReg AI — Step 4 Release / Deployment

## 1. Local release test
From the project directory:

```powershell
python -m py_compile app.py regulatory_update_engine.py regulatory_document_intelligence.py
python release_health_check.py
python -m unittest -v test_foodreg.py
```

## 2. Start locally

```powershell
python -m streamlit run app.py
```

## 3. Regulatory updater

The V18 design keeps legal-record changes behind human approval. Run source monitoring from the app's Regulatory Update Center or with the project's update runner.

## 4. Docker deployment

```powershell
docker build -t foodreg-ai .
docker run --rm -p 8501:8501 -v "${PWD}:/app" foodreg-ai
```

Then open `http://localhost:8501`.

## 5. Data safety

- Back up `foodreg.db` before applying approved regulatory proposals.
- Do not commit private product labels or API credentials.
- Missing regulatory data must remain distinguishable from approval/no-restriction.
- Source changes should remain auditable through the updater tables.
