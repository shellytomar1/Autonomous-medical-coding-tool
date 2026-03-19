from __future__ import annotations

from pathlib import Path
from typing import Optional

import pandas as pd

from medical_coding_tool.ai_engine import AINLPEngine
from medical_coding_tool.exceptions import NoDiseasesFoundError, NoCodesFoundError
from medical_coding_tool.file_reader import read_text_from_file
from medical_coding_tool.icd10_mapper import ICD10CMCodeMapper
from medical_coding_tool.ner import SciSpacyExtractor


def _default_output_paths(input_path: Path) -> tuple[Path, Path]:
    base = input_path.with_suffix("")
    csv_path = base.parent / f"{base.name}_medical_coding.csv"
    xlsx_path = base.parent / f"{base.name}_medical_coding.xlsx"
    return csv_path, xlsx_path


def _export_dataframe(
    df: pd.DataFrame,
    *,
    output_path: Optional[str],
    export_xlsx: bool,
    input_path: Path,
) -> None:
    if output_path:
        out = Path(output_path).expanduser().resolve()
        if out.suffix.lower() == ".xlsx":
            df.to_excel(out, index=False)
        else:
            df.to_csv(out, index=False)
        return

    csv_path, xlsx_path = _default_output_paths(input_path)
    df.to_csv(csv_path, index=False)
    if export_xlsx:
        df.to_excel(xlsx_path, index=False)


def process_medical_record(
    file_path: str,
    *,
    output_path: Optional[str] = None,
    export_xlsx: bool = True,
    strict: bool = False,
    use_ai: bool = False,
    ai_model: str = "gpt-4o-mini",
    patient_name_override: Optional[str] = None,
    export_output: bool = True,
) -> pd.DataFrame:
    """
    Orchestrates the full workflow:
      1) Read .txt/.pdf
      2) Extract patient name and diseases/conditions (SciSpacy NER + heuristics)
      3) Map diseases to ICD-10-CM codes (validated ICD dataset via icd-mappings)
      4) Export results as CSV/XLSX

    Returns the resulting DataFrame regardless of whether codes were found.
    """
    input_path = Path(file_path).expanduser().resolve()
    if not input_path.exists():
        raise FileNotFoundError(str(input_path))

    text = read_text_from_file(str(input_path))
    extractor = SciSpacyExtractor()
    mapper = ICD10CMCodeMapper()
    ai_engine = AINLPEngine(model=ai_model) if use_ai else None

    patient_name = patient_name_override or extractor.extract_patient_name(text)
    diseases = extractor.extract_conditions(text)

    # Optional AI augmentation step for stronger extraction quality.
    if ai_engine is not None and ai_engine.is_enabled():
        ai_name, ai_diseases = ai_engine.extract_patient_and_diseases(text)
        if ai_name and (patient_name == "Unknown" or len(ai_name) >= len(patient_name)):
            patient_name = ai_name
        # Merge NLP + AI diseases with normalization-based de-dup.
        merged = []
        seen = set()
        for d in diseases + ai_diseases:
            n = " ".join((d or "").lower().split())
            if not n or n in seen:
                continue
            seen.add(n)
            merged.append(d)
        diseases = merged

    rows: list[dict[str, str]] = []
    if not diseases:
        # Required error handling: explicitly reflect "no codes found"-type scenarios.
        # Here we distinguish "no extracted diseases".
        rows.append(
            {
                "Patient Name": patient_name,
                "Extracted Disease": "No diseases extracted from record",
                "ICD-10 Code": "N/A",
            }
        )
        df = pd.DataFrame(rows, columns=["Patient Name", "Extracted Disease", "ICD-10 Code"])
        if export_output:
            _export_dataframe(df, output_path=output_path, export_xlsx=export_xlsx, input_path=input_path)
        if strict:
            raise NoDiseasesFoundError("No diseases/conditions were extracted from the input record.")
        return df

    disease_to_code = mapper.map_conditions(diseases)
    any_mapped = any(v for v in disease_to_code.values())

    # Optional AI coding fallback for unmapped diseases.
    if ai_engine is not None and ai_engine.is_enabled():
        for disease, code in list(disease_to_code.items()):
            if code is not None:
                continue
            ai_code = ai_engine.suggest_icd10_for_disease(disease)
            valid_code = mapper.normalize_code_if_valid(ai_code) if ai_code else None
            if valid_code:
                disease_to_code[disease] = valid_code
                any_mapped = True

    for disease, code in disease_to_code.items():
        if code is None:
            rows.append(
                {
                    "Patient Name": patient_name,
                    "Extracted Disease": disease,
                    "ICD-10 Code": "No ICD-10 code found",
                }
            )
        else:
            rows.append(
                {
                    "Patient Name": patient_name,
                    "Extracted Disease": disease,
                    "ICD-10 Code": code,
                }
            )

    df = pd.DataFrame(rows, columns=["Patient Name", "Extracted Disease", "ICD-10 Code"])
    if export_output:
        _export_dataframe(df, output_path=output_path, export_xlsx=export_xlsx, input_path=input_path)

    if not any_mapped:
        # Required error handling: "No codes found" for extracted diseases.
        if strict:
            raise NoCodesFoundError("Extracted diseases could not be mapped to ICD-10-CM codes.")

    return df


def process_multiple_medical_records(
    file_paths: list[str],
    *,
    output_path: Optional[str] = None,
    export_xlsx: bool = True,
    strict: bool = False,
    use_ai: bool = False,
    ai_model: str = "gpt-4o-mini",
) -> pd.DataFrame:
    """
    Process multiple TXT/PDF notes and export a single consolidated output file.

    For batch mode, Patient Name is set to the input filename stem as requested.
    """
    if not file_paths:
        raise ValueError("No input files provided.")

    all_frames: list[pd.DataFrame] = []
    first_path = Path(file_paths[0]).expanduser().resolve()

    for fp in file_paths:
        p = Path(fp).expanduser().resolve()
        patient_name_from_filename = p.stem
        df = process_medical_record(
            file_path=str(p),
            output_path=None,
            export_xlsx=False,
            strict=strict,
            use_ai=use_ai,
            ai_model=ai_model,
            patient_name_override=patient_name_from_filename,
            export_output=False,
        )
        all_frames.append(df)

    merged = pd.concat(all_frames, ignore_index=True)
    _export_dataframe(merged, output_path=output_path, export_xlsx=export_xlsx, input_path=first_path)
    return merged

