# Autonomous Medical Coding Tool (Python)

This project is a HealthTech-focused NLP pipeline that reads unstructured clinical notes (TXT/PDF), extracts medical conditions, maps them to ICD-10-CM codes, and exports structured coding output as CSV/Excel.

## What This Project Does

- Reads one or many medical records from:
  - `.txt`, `.text`, `.md`, `.pdf`
  - individual file paths or whole directories
- Extracts:
  - patient identifier (single-file mode: inferred from note)
  - disease/condition mentions
- Maps extracted diseases to ICD-10-CM using a multi-source strategy:
  1. Local validated ICD-10-CM dataset from `icd-mappings`
  2. NLM Clinical Tables ICD-10-CM API fallback
  3. Last-resort fuzzy fallback (configurable behavior in code)
- Exports structured output with columns:
  - `Patient Name`
  - `Extracted Disease`
  - `ICD-10 Code`

## Why It Was Built

Clinical notes are often noisy and unstructured. This tool reduces manual coding effort by combining:

- deterministic biomedical NLP (SciSpacy + heuristics),
- optional AI augmentation (OpenAI),
- and validated ICD lookup datasets.

## Architecture

### Core Modules

- `main.py`
  - CLI entrypoint
  - supports single-file and multi-file batch mode
- `medical_coding_tool/file_reader.py`
  - reads TXT/PDF safely (`pdfplumber` + `PyPDF2` fallback)
- `medical_coding_tool/ner.py`
  - disease extraction and patient name extraction
  - problem-list-aware parsing
  - negation/noise filtering (e.g., ignores many `no ...` findings)
- `medical_coding_tool/icd10_mapper.py`
  - ICD mapping logic (local + government API fallback)
  - code normalization and validation
- `medical_coding_tool/ai_engine.py`
  - optional OpenAI-assisted extraction/coding
  - enabled only when `--use-ai` and `OPENAI_API_KEY` are provided
- `medical_coding_tool/pipeline.py`
  - orchestration:
    - `process_medical_record(...)`
    - `process_multiple_medical_records(...)`

## Data Flow (End-to-End)

1. Input file(s) are collected from path(s) passed to `--input`.
2. Text is extracted from TXT/PDF.
3. Conditions are extracted via NLP heuristics and biomedical model.
4. (Optional) AI adds/cleans extracted diseases and suggests codes.
5. ICD mapper validates and selects ICD-10-CM codes.
6. Output table is generated and exported as CSV/XLSX.
7. CLI prints completion message with saved file path and row count.

## Installation

```bash
cd /Users/shellytomar/Documents/github/medical-coding-tool
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Usage

### 1) Single file (local NLP only, zero-cost)

```bash
.venv/bin/python main.py \
  --input "/path/to/patient_1.pdf" \
  --output "/path/to/output.csv" \
  --no-xlsx
```

### 2) Multiple files into one consolidated output

```bash
.venv/bin/python main.py \
  --input "/path/to/patient_1.pdf" "/path/to/patient_2.pdf" \
  --output "/path/to/all_patients_output.csv" \
  --no-xlsx
```

### 3) Whole folder input

```bash
.venv/bin/python main.py \
  --input "/path/to/folder_with_notes" \
  --output "/path/to/all_patients_output.csv" \
  --no-xlsx
```

### 4) AI-augmented run (optional)

```bash
export OPENAI_API_KEY="your_key_here"

.venv/bin/python main.py \
  --input "/path/to/folder_with_notes" \
  --output "/path/to/all_patients_output.csv" \
  --use-ai \
  --ai-model "gpt-4o-mini" \
  --no-xlsx
```

## Batch Mode Behavior

When multiple files are passed, the tool writes a single merged output file.

- `Patient Name` is set to the input filename stem (as requested).
- All extracted disease/code rows from all files are appended together.

## Output Example

| Patient Name | Extracted Disease | ICD-10 Code |
| --- | --- | --- |
| patient_1 | Type 2 diabetes mellitus | E11.9 |
| patient_1 | Essential hypertension | I10 |
| patient_2 | Carpal tunnel syndrome | G56.00 |

## Notes and Limitations

- This is a coding-assist tool, not a replacement for certified coder review.
- Forced fallback matching can improve coverage but may reduce precision for ambiguous text.
- Extraction quality depends on note structure (Problem List sections map best).
- Model compatibility warnings can appear if SciSpacy model/spaCy versions differ.

## Troubleshooting

- `ModuleNotFoundError`:
  - Ensure VS Code interpreter is `.venv/bin/python`.
- `No ICD-10 code found` for noisy phrases:
  - verify note quality and Problem List presence;
  - enable `--use-ai` to improve extraction/mapping.
- PDF extraction quality issues:
  - OCR-heavy PDFs may need preprocessing.

## Security / Privacy

- Do not commit patient-identifiable data or API keys.
- `.env` and local secrets are ignored by `.gitignore`.

## Repository Setup and Push to GitHub

Initialize and push this project:

```bash
cd /Users/shellytomar/Documents/github/medical-coding-tool
git init
git add .
git commit -m "Initial commit: autonomous medical coding tool"
git branch -M main
git remote add origin https://github.com/<your-username>/<your-repo>.git
git push -u origin main
```

If your repo already exists on GitHub, just replace `<your-username>/<your-repo>`.

