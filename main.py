from __future__ import annotations

import argparse
from pathlib import Path

from medical_coding_tool.pipeline import process_medical_record, process_multiple_medical_records


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Autonomous medical coding tool (ICD-10-CM).")
    parser.add_argument(
        "--input",
        "-i",
        required=True,
        nargs="+",
        help="One or more input paths (.txt/.pdf files and/or directories).",
    )
    parser.add_argument(
        "--output",
        "-o",
        default=None,
        help="Optional output path (.csv or .xlsx). If omitted, outputs alongside input.",
    )
    parser.add_argument(
        "--no-xlsx",
        action="store_true",
        help="If set, only writes CSV output (useful in environments without Excel tooling).",
    )
    parser.add_argument(
        "--use-ai",
        action="store_true",
        help="Enable optional AI augmentation (requires OPENAI_API_KEY).",
    )
    parser.add_argument(
        "--ai-model",
        default="gpt-4o-mini",
        help="OpenAI model name when --use-ai is set.",
    )
    return parser.parse_args()


def _collect_input_files(input_values: list[str]) -> list[Path]:
    collected: list[Path] = []
    seen: set[str] = set()

    for raw in input_values:
        p = Path(raw).expanduser().resolve()
        if not p.exists():
            raise FileNotFoundError(str(p))

        if p.is_dir():
            # Collect only supported input types in deterministic order.
            candidates = sorted(
                [*p.glob("*.txt"), *p.glob("*.text"), *p.glob("*.md"), *p.glob("*.pdf")]
            )
            for c in candidates:
                key = str(c)
                if key not in seen:
                    seen.add(key)
                    collected.append(c)
        else:
            if p.suffix.lower() not in {".txt", ".text", ".md", ".pdf"}:
                continue
            key = str(p)
            if key not in seen:
                seen.add(key)
                collected.append(p)

    if not collected:
        raise ValueError("No supported input files found. Use .txt/.pdf files or a directory containing them.")
    return collected


def main() -> None:
    args = _parse_args()
    input_paths = _collect_input_files(args.input)

    if args.output:
        output_path = Path(args.output).expanduser().resolve()
        # If user gives a filename without extension, default to CSV.
        if output_path.suffix.lower() not in {".csv", ".xlsx"}:
            output_path = output_path.with_suffix(".csv")
    else:
        output_path = None

    result_df = None
    if len(input_paths) == 1:
        # Single-file workflow.
        result_df = process_medical_record(
            file_path=str(input_paths[0]),
            output_path=str(output_path) if output_path else None,
            export_xlsx=not args.no_xlsx,
            use_ai=args.use_ai,
            ai_model=args.ai_model,
        )
    else:
        # Multi-file workflow with Patient Name = filename.
        result_df = process_multiple_medical_records(
            file_paths=[str(p) for p in input_paths],
            output_path=str(output_path) if output_path else None,
            export_xlsx=not args.no_xlsx,
            use_ai=args.use_ai,
            ai_model=args.ai_model,
        )

    if output_path:
        print(f"Saved {len(result_df)} rows to {output_path}")
    else:
        first_input = input_paths[0]
        csv_default = first_input.with_suffix("").parent / f"{first_input.with_suffix('').name}_medical_coding.csv"
        if args.no_xlsx:
            print(f"Saved {len(result_df)} rows to {csv_default}")
        else:
            xlsx_default = first_input.with_suffix("").parent / f"{first_input.with_suffix('').name}_medical_coding.xlsx"
            print(f"Saved {len(result_df)} rows to {csv_default} and {xlsx_default}")


if __name__ == "__main__":
    main()

