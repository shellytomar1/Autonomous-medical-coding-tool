from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from typing import Optional


def _extract_json_object(raw: str) -> dict:
    raw = (raw or "").strip()
    if not raw:
        return {}
    try:
        return json.loads(raw)
    except Exception:
        pass

    # Fallback when model wraps JSON in extra text/code fences.
    m = re.search(r"\{.*\}", raw, flags=re.DOTALL)
    if not m:
        return {}
    try:
        return json.loads(m.group(0))
    except Exception:
        return {}


@dataclass
class AINLPEngine:
    """
    Optional LLM engine used to improve extraction/mapping quality.
    Enabled only when OPENAI_API_KEY exists.
    """

    model: str = "gpt-4o-mini"

    def is_enabled(self) -> bool:
        return bool(os.getenv("OPENAI_API_KEY"))

    def extract_patient_and_diseases(self, text: str) -> tuple[Optional[str], list[str]]:
        if not self.is_enabled():
            return None, []

        try:
            from openai import OpenAI

            client = OpenAI()
            prompt = (
                "You are a clinical coding assistant.\n"
                "Extract patient name and only positive diseases/diagnoses/conditions from the note.\n"
                "Exclude negated findings (no/denies/without), symptoms-only terms, exam-only statements, and section labels.\n"
                "Return strict JSON with keys: patient_name (string or null), diseases (array of strings).\n\n"
                f"CLINICAL_NOTE:\n{text[:16000]}"
            )
            res = client.responses.create(
                model=self.model,
                input=prompt,
                temperature=0,
            )
            payload = _extract_json_object(res.output_text)
            name = payload.get("patient_name")
            diseases = payload.get("diseases") or []
            clean = []
            for d in diseases:
                if isinstance(d, str):
                    d2 = " ".join(d.split()).strip(" ,;.")
                    if d2:
                        clean.append(d2)
            return (name if isinstance(name, str) and name.strip() else None, clean)
        except Exception:
            return None, []

    def suggest_icd10_for_disease(self, disease: str) -> Optional[str]:
        """
        Ask LLM for likely ICD-10-CM code (best-effort fallback).
        Caller must validate returned code against local ICD dataset.
        """
        if not self.is_enabled():
            return None

        try:
            from openai import OpenAI

            client = OpenAI()
            prompt = (
                "Return only JSON. Map the disease phrase to a likely ICD-10-CM diagnosis code.\n"
                "Output schema: {\"icd10_code\": \"<code or null>\"}\n"
                "If uncertain, return null.\n\n"
                f"Disease phrase: {disease}"
            )
            res = client.responses.create(
                model=self.model,
                input=prompt,
                temperature=0,
            )
            payload = _extract_json_object(res.output_text)
            code = payload.get("icd10_code")
            if isinstance(code, str) and code.strip():
                return code.strip().upper()
            return None
        except Exception:
            return None

