from __future__ import annotations

import re
import subprocess
import sys
from dataclasses import dataclass
from typing import Optional


_PATIENT_NAME_REGEXES: list[re.Pattern[str]] = [
    # Common structured forms:
    re.compile(r"(?im)^\s*patient\s*name\s*[:\-]\s*(?P<name>[A-Z][A-Za-z'\-]+(?:\s+[A-Z][A-Za-z'\-]+){0,3})\s*$"),
    re.compile(r"(?im)^\s*name\s*[:\-]\s*(?P<name>[A-Z][A-Za-z'\-]+(?:\s+[A-Z][A-Za-z'\-]+){0,3})\s*$"),
    # Inline:
    re.compile(r"(?i)\bpatient\s*name\s*[:\-]\s*(?P<name>[A-Z][A-Za-z'\-]+(?:\s+[A-Z][A-Za-z'\-]+){0,3})\b"),
    re.compile(r"(?i)\bname\s*[:\-]\s*(?P<name>[A-Z][A-Za-z'\-]+(?:\s+[A-Z][A-Za-z'\-]+){0,3})\b"),
    # Narrative style often seen in HPI.
    re.compile(r"(?im)^\s*(?P<name>[A-Z][a-z]+)\s+presents\b"),
]


# Heuristics: these are the kinds of terms that often appear in clinical notes.
_CONDITION_STARTERS = [
    "diagnosed with",
    "diagnosis of",
    "history of",
    "hx of",
    "suffers from",
    "presents with",
    "known for",
]

_CONDITION_KEYWORDS = {
    # Generic disease markers
    "disease",
    "disorder",
    "syndrome",
    "condition",
    # Common medical endings / markers
    "itis",
    "itis ",
    "itis.",
    "malign",
    "cancer",
    "carcinoma",
    "tumor",
    "tumour",
    "leuk",
    "lymphoma",
    "fibrosis",
    "sclerosis",
    "failure",
    "insufficiency",
    "hypertension",
    "hypotension",
    "diabetes",
    "asthma",
    "copd",
    "pneumonia",
    "stroke",
    "arthritis",
    "obesity",
    "depression",
    "anxiety",
    "seizure",
    "epilepsy",
    "migraine",
}

_NEGATION_PATTERNS = [
    r"\bno\b",
    r"\bdenies\b",
    r"\bwithout\b",
    r"\bnegative for\b",
    r"\bfree of\b",
]

_NON_DISEASE_NOISE = {
    "present illness note",
    "review of systems",
    "physical exam",
    "assessment",
    "plan",
    "clinic",
    "follow up",
    "follow-up consultation",
    "history type",
    "complexity",
    "active",
    "none recorded",
}


def _normalize_ws(s: str) -> str:
    return " ".join((s or "").replace("\x00", " ").split())


def _clean_condition_phrase(phrase: str) -> str:
    phrase = _normalize_ws(phrase).strip(" ,;.")
    phrase = re.sub(r"(?i)^(?:history of|hx of|diagnosed with|diagnosis of|suffers from|presents with|known for)\s+", "", phrase).strip()
    # Remove common abbreviations like "s/p" or "s/p:" found in some notes.
    phrase = re.sub(r"(?i)\b(?:s/p|sp)\s*", "", phrase).strip()
    return phrase


def _split_multiple_diseases(phrase: str) -> list[str]:
    """
    Split a phrase like "diabetes and hypertension, and asthma" into individual items.
    This is intentionally conservative; it shouldn't over-split complex names.
    """
    phrase = _normalize_ws(phrase)
    if not phrase:
        return []

    # Split on " and " and commas/semicolons.
    parts = re.split(r"\s*(?:,|;|\band\b)\s*", phrase)
    # Keep only non-trivial parts.
    out = []
    for p in parts:
        p = _clean_condition_phrase(p)
        if len(p) >= 3:
            out.append(p)
    return out


def _looks_negated(phrase: str) -> bool:
    p = phrase.lower()
    return any(re.search(rx, p) for rx in _NEGATION_PATTERNS)


def _looks_noisy(phrase: str) -> bool:
    p = phrase.lower()
    if len(p.split()) > 14:
        return True
    return any(token in p for token in _NON_DISEASE_NOISE)


def _extract_problem_list_conditions(text: str) -> list[str]:
    """
    Pull diagnoses from 'Problem List' section first, which is usually cleaner
    and closer to billable diagnoses than free narrative ROS text.
    """
    m = re.search(r"(?is)\bproblem\s+list\b(?P<section>.*?)(?=\bprocedures\b|\bsocial history\b|\bfamily history\b|$)", text)
    if not m:
        return []

    section = m.group("section")
    conditions: list[str] = []
    for raw_line in section.splitlines():
        line = " ".join(raw_line.split()).strip(" -\t")
        if not line:
            continue

        # Strip tail metadata after diagnosis phrase.
        line = re.split(r"\bActive\b|\bHistory\b|\bType:\b|\bComplexity:\b|\b\d{2}/\d{2}/\d{4}\b", line, maxsplit=1)[0].strip(" ,;.-")
        if len(line) < 3:
            continue
        if _looks_negated(line) or _looks_noisy(line):
            continue

        # Skip very generic non-disease administrative entries.
        if line.lower() in {"follow-up consultation", "sleep rest pattern finding"}:
            continue
        conditions.append(line)
    return conditions


def _try_install_scispacy_model(model_url: str, *, timeout_s: int = 600) -> None:
    # Install the tar.gz directly via pip so the runtime can `spacy.load()` it.
    # This requires network access at runtime.
    cmd = [sys.executable, "-m", "pip", "install", "--quiet", model_url]
    subprocess.run(cmd, check=True, timeout=timeout_s)


@dataclass
class SciSpacyExtractor:
    """
    Extracts patient name and condition mentions using `en_core_sci_sm` (SciSpacy).
    """

    model_name: str = "en_core_sci_sm"
    # SciSpacy docs provide a stable model URL; version pinned here for reproducibility.
    model_url: str = "https://s3-us-west-2.amazonaws.com/ai2-s2-scispacy/releases/v0.5.4/en_core_sci_sm-0.5.4.tar.gz"

    _nlp: Optional[object] = None

    def _load_nlp(self) -> None:
        if self._nlp is not None:
            return

        import spacy  # local import to keep startup cost low

        try:
            self._nlp = spacy.load(self.model_name)
            return
        except Exception:
            # Attempt a one-time download/install from the known SciSpacy URL.
            _try_install_scispacy_model(self.model_url)
            self._nlp = spacy.load(self.model_name)

    def extract_patient_name(self, text: str) -> str:
        self._load_nlp()
        assert self._nlp is not None

        # 1) Prefer explicit patterns.
        for rx in _PATIENT_NAME_REGEXES:
            m = rx.search(text)
            if m and m.groupdict().get("name"):
                return m.group("name").strip()

        # 2) Fallback: use NER spans labeled ENTITY and filter to look like names.
        doc = self._nlp(text)
        candidate_ents = []
        for ent in getattr(doc, "ents", []) or []:
            ent_text = _normalize_ws(ent.text)
            if ent.label_ != "ENTITY":
                continue
            # Heuristic: person names are often 2+ capitalized tokens.
            tokens = ent_text.split()
            if len(tokens) >= 2 and all(t[:1].isupper() for t in tokens[:2]):
                candidate_ents.append((len(ent_text), ent_text))
        if candidate_ents:
            # Pick the longest plausible name span.
            candidate_ents.sort(reverse=True)
            return candidate_ents[0][1]

        return "Unknown"

    def extract_conditions(self, text: str, *, max_conditions: int = 25) -> list[str]:
        self._load_nlp()
        assert self._nlp is not None

        conditions: list[str] = []

        # 0) Prefer explicit problem list diagnoses when present.
        conditions.extend(_extract_problem_list_conditions(text))

        # 1) Regex-based extraction for high precision on common note templates.
        #    Example: "Diagnosed with diabetes mellitus and hypertension."
        for starter in _CONDITION_STARTERS:
            # Capture up to punctuation/newline. Keep it non-greedy and bounded.
            pattern = re.compile(
                rf"(?is)\b{re.escape(starter)}\b\s*(?P<cond>.+?)(?=(?:\.|\n|;|$))"
            )
            for m in pattern.finditer(text):
                raw = m.group("cond")
                for part in _split_multiple_diseases(raw):
                    if _looks_negated(part) or _looks_noisy(part):
                        continue
                    conditions.append(part)

        # 2) SciSpacy NER entities (label is generally ENTITY in `en_core_sci_sm`).
        doc = self._nlp(text)
        for ent in getattr(doc, "ents", []) or []:
            ent_text = _normalize_ws(ent.text)
            if ent.label_ != "ENTITY":
                continue
            ent_text_l = ent_text.lower()
            # Drop obvious non-condition words that the model may capture.
            if ent_text_l in {"patient", "diagnosed", "history of", "hx of"}:
                continue
            if len(ent_text) < 3:
                continue
            if _looks_negated(ent_text) or _looks_noisy(ent_text):
                continue

            # Keep entities that look condition-ish by keyword or common disease suffixes.
            if any(k in ent_text_l for k in _CONDITION_KEYWORDS) or re.search(r"\b(?:-itis|-itis\b|-itis\b|itis|cancer|carcinoma)\b", ent_text_l):
                cleaned = _clean_condition_phrase(ent_text)
                if cleaned:
                    conditions.append(cleaned)

        # 3) De-duplicate while preserving order (normalized comparison).
        seen = set()
        deduped: list[str] = []
        for c in conditions:
            c_norm = re.sub(r"[^a-z0-9]+", " ", c.lower()).strip()
            if not c_norm or c_norm in seen:
                continue
            seen.add(c_norm)
            deduped.append(c)

        # 4) Cap to avoid runaway extraction for very long notes.
        return deduped[:max_conditions]

