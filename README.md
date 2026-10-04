# FoodReg AI

### AI-Powered Food Ingredient & Regulatory Intelligence Platform

FoodReg AI is an AI-powered platform for analyzing food ingredient labels and supporting regulatory intelligence across multiple jurisdictions.

The system combines **OCR, ingredient normalization, allergen detection, nutrition analysis, regulatory databases, government-document intelligence, and human-in-the-loop review** into a unified workflow.

> **Note:** FoodReg AI is a decision-support and information system. It does not provide legal advice or automatically determine regulatory compliance.

---

## Overview

FoodReg AI is designed to transform unstructured food-label information into structured, interpretable insights.

A typical workflow is:

```text
Food Label
    ↓
OCR & Text Extraction
    ↓
Ingredient Normalization
    ↓
Ingredient & Allergen Analysis
    ↓
Nutrition Analysis
    ↓
Regulatory Intelligence
    ↓
Evidence & Jurisdiction Comparison
    ↓
Human Review
```

The platform also supports analysis of official regulatory documents, allowing potential regulatory information to be extracted and routed through a review workflow.

---

## Key Features

### Ingredient Label OCR

- Extracts ingredient information from food-label images
- Uses PaddleOCR for text recognition
- Supports image preprocessing and enhancement
- Handles OCR normalization and noisy text
- Maps ingredient aliases and INS codes

### Ingredient Intelligence

Provides structured information about detected ingredients, including:

- Normalized ingredient names
- Ingredient aliases
- INS / E-number references
- Ingredient classifications
- Regulatory records

### Allergen Detection

Identifies potential allergens from extracted ingredient information and highlights them for further review.

### Nutrition Analysis

Extracts and organizes available nutritional information such as:

- Calories
- Protein
- Carbohydrates
- Fat
- Sugar
- Sodium
- Other available nutritional values

### Regulatory Intelligence

Supports regulatory comparison across multiple jurisdictions using structured regulatory records and source evidence.

The system distinguishes between:

- Database information
- Official-source evidence
- International references
- AI/OCR-extracted information
- Human-verified information

A missing regulatory record is **not interpreted as approval or safety**.

### Government Document Intelligence

Official regulatory documents can be uploaded and analyzed to identify potential regulatory proposals.

```text
Official Document
      ↓
Text Extraction
      ↓
OCR Fallback
      ↓
Proposal Extraction
      ↓
Review Queue
      ↓
Human Decision
```

Scanned PDFs can be processed using **PaddleOCR and pypdfium2**.

### Human-in-the-Loop Review

Potential regulatory changes are not automatically treated as confirmed regulatory updates.

Instead:

```text
AI Extraction
     ↓
Candidate Proposal
     ↓
Human Review
   ↙       ↘
Approve   Reject
   ↓
Database
```

This approach helps maintain a clear separation between automated extraction and verified regulatory information.

---

## Technology Stack

| Technology | Purpose |
|---|---|
| Python | Core development |
| Streamlit | Web application |
| PaddleOCR | OCR and document text extraction |
| OpenCV | Image processing |
| Pandas | Data processing |
| NumPy | Numerical operations |
| SQLite | Regulatory database |
| RapidFuzz | Fuzzy ingredient matching |
| pypdf | PDF text extraction |
| pypdfium2 | PDF rendering for OCR |
| Pillow | Image processing |

---

## Project Architecture

```text
                       FoodReg AI
                           │
        ┌──────────────────┼──────────────────┐
        │                  │                  │
        ▼                  ▼                  ▼
   Food Label        Regulatory Docs      Database
        │                  │                  │
        ▼                  ▼                  │
      OCR             Text / OCR              │
        │                  │                  │
        └──────────┬───────┘                  │
                   ▼                          │
          Information Extraction              │
                   │                          │
          ┌────────┼────────┐                 │
          ▼        ▼        ▼                 │
      Ingredient  Allergen  Nutrition         │
      Analysis    Analysis  Analysis          │
          │        │        │                 │
          └────────┼────────┘                 │
                   ▼                          │
          Regulatory Intelligence ────────────┤
                   │                          │
                   ▼                          │
             Evidence & Review               │
                   │                          │
                   ▼                          │
            Verified Information ─────────────┘
```

---

## Government Document Intelligence

FoodReg AI supports regulatory document processing for PDF, HTML, and text-based sources.

The document workflow is designed around **proposal generation rather than automatic regulatory modification**.

```text
PDF / HTML / TXT
      ↓
Text Extraction
      ↓
OCR for Scanned Documents
      ↓
Regulatory Proposal Detection
      ↓
Review Queue
      ↓
Approve / Reject
      ↓
Versioned Regulatory Records
```

For scanned PDFs, the current implementation supports CPU-based OCR using PaddleOCR and pypdfium2.

---

## Database

FoodReg AI uses SQLite for local regulatory intelligence.

### Core tables

```text
ingredients
ingredient_aliases
jurisdictions
regulatory_records
```

### Regulatory update and review tables

```text
regulatory_source_registry
regulatory_source_snapshots
regulatory_update_runs
regulatory_change_events
regulatory_document_proposals
regulatory_record_versions
```

---

## Installation

### 1. Clone the repository

```bash
git clone https://github.com/josephabishak88/-FoodReg-AI.git
cd -FoodReg-AI
```

### 2. Create a virtual environment

**Windows**

```powershell
python -m venv venv
venv\Scripts\activate
```

**Linux / macOS**

```bash
python3 -m venv venv
source venv/bin/activate
```

### 3. Install dependencies

```bash
pip install -r requirements.txt
```

### 4. Run the application

```bash
streamlit run app.py
```

The application will then be available through the local Streamlit interface.

---

## Regulatory Safety Principles

FoodReg AI follows several principles when handling regulatory information.

**Missing data ≠ approval**

A missing database record does not mean that an ingredient is approved, prohibited, or safe.

**AI extraction ≠ confirmed legislation**

Information extracted through OCR or AI processing is treated as candidate information until verified.

**Evidence matters**

Regulatory information should be interpreted together with its supporting source and context.

**Human verification**

Potential regulatory changes can be reviewed before becoming trusted regulatory records.

---

## Project Structure

```text
FoodReg-AI/
│
├── app.py
├── foodreg.db
│
├── ingredient_normalizer.py
├── ingredient_text_normalizer.py
│
├── regulatory_database.py
├── regulatory_database_all_countries.py
├── jurisdiction_registry.py
│
├── database_setup.py
├── seed_database.py
├── populate_regulatory_data.py
│
├── regulatory_update_engine.py
├── regulatory_document_intelligence.py
│
├── requirements.txt
├── README.md
├── PROJECT_INFO.md
└── .gitignore
```

---

## Development & Validation

Before committing major changes:

```powershell
python -m py_compile app.py
```

Check the repository:

```powershell
git status
```

Commit and push updates:

```powershell
git add .
git commit -m "Update FoodReg AI"
git push
```

---

## Why I Built This

Building FoodReg AI highlighted that a practical AI application involves much more than training an OCR model.

The real challenge is connecting:

```text
Unstructured Input
      ↓
OCR
      ↓
Normalization
      ↓
Structured Data
      ↓
Regulatory Information
      ↓
Evidence
      ↓
Human Verification
```

The project explores how AI can be used not only to automate extraction, but also to **organize complex information, connect evidence, and support better human decision-making**.

---

## Future Improvements

Potential future development areas include:

- Expanded regulatory coverage
- Improved OCR accuracy
- Additional document formats
- Automated source monitoring
- More advanced ingredient knowledge graphs
- Improved regulatory comparison
- Cloud deployment
- Multilingual food-label support
- Enhanced evidence traceability

---

## Disclaimer

FoodReg AI is an experimental AI-powered information and decision-support platform.

The information generated by this application should not be considered legal, regulatory, medical, or compliance advice.

Regulatory requirements may change over time. Important decisions should always be verified against the latest applicable official sources and, where appropriate, qualified professionals.

---

## Author

**Joseph D. Abishak**

B.Tech — Computer Science & Engineering  
Artificial Intelligence & Data Science

**Areas of Interest**

- Artificial Intelligence
- Machine Learning
- Data Science
- Computer Vision
- Data Analytics
- AI-powered Applications

---

### FoodReg AI

**From food-label data to structured regulatory intelligence.**
