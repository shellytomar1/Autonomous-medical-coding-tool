from __future__ import annotations

from dataclasses import dataclass
import importlib.resources as resources
from functools import lru_cache
import re
from typing import Optional

from rapidfuzz import fuzz, process
import requests


def _format_icd10cm(code: str) -> str:
    """
    Convert ICD-10-CM code format from the dataset's dotless style (e.g., A0100)
    to dot form (e.g., A01.00).
    """
    code = (code or "").strip().upper().replace(".", "")
    if not code:
        return code
    if len(code) <= 3:
        return code
    return f"{code[:3]}.{code[3:]}"


def _normalize_condition_text(text: str) -> str:
    t = (text or "").lower().strip()
    if not t:
        return t
    t = re.sub(r"\b(of|the|a|an)\b", " ", t)
    t = re.sub(r"\b(right|left|bilateral|unilateral)\b", " ", t)
    t = re.sub(r"\bwithout complication\b", " ", t)
    t = re.sub(r"\s+", " ", t).strip(" ,;.-")
    return t


@lru_cache(maxsize=1)
def _load_icd10cm_choices() -> tuple[list[str], list[str]]:
    """
    Loads the validated ICD-10-CM release file bundled with `icd-mappings`.

    Returns:
      choices: list of lowercased descriptions
      codes: corresponding code strings (dotless), same index as choices
    """
    import icdmappings  # noqa: F401

    package = "icdmappings.data_files.ICD_10_CM_2024_release"
    filename = "icd10cm-codes-2024.txt"
    choices: list[str] = []
    codes: list[str] = []

    with resources.files(package).joinpath(filename).open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            # Format: CODE<spaces>DESCRIPTION
            # Example: A0101   Typhoid meningitis
            code, rest = line.split(None, 1)
            choices.append(rest.lower())
            codes.append(code.upper())

    return choices, codes


@lru_cache(maxsize=1)
def _load_valid_icd10cm_codes() -> set[str]:
    _, codes = _load_icd10cm_choices()
    return {c.upper().replace(".", "") for c in codes}


@dataclass
class ICD10CMCodeMapper:
    """
    Maps extracted disease mentions to ICD-10-CM codes using fuzzy matching against
    the validated ICD-10-CM description dataset bundled with `icd-mappings`.
    """

    # Use a fairly strict cutoff to reduce obvious false positives.
    score_cutoff: int = 85
    # If True, always return the best available code candidate.
    force_best_match: bool = True

    def map_condition_to_icd10cm(self, condition: str) -> Optional[str]:
        condition = (condition or "").strip()
        if not condition:
            return None

        choices, codes = _load_icd10cm_choices()
        query = _normalize_condition_text(condition)

        # 1) Rule-based shortcuts for common generic mentions.
        #    This improves accuracy for cases where fuzzy matching otherwise
        #    prefers overly specific variants (e.g., "diabetes mellitus" ->
        #    "neonatal diabetes mellitus").
        preferred_code = self._map_condition_via_rules(query, choices, codes)
        if preferred_code is not None:
            return preferred_code

        # Use token-sort ratio for robustness to word order.
        # extractOne is fast and works well for a single disease mention.
        result = process.extractOne(
            query,
            choices,
            scorer=fuzz.WRatio,
            score_cutoff=self.score_cutoff,
        )
        if result:
            matched_description, score, matched_index = result
            matched_code = codes[matched_index]
            return _format_icd10cm(matched_code)

        # 3) Government source fallback (NLM ClinicalTables ICD-10-CM API).
        gov_code = self._query_nlm_icd10cm_api(query)
        if gov_code:
            valid = self.normalize_code_if_valid(gov_code)
            if valid:
                return valid

        # 4) Last-resort local best candidate without score cutoff.
        if self.force_best_match:
            fallback = process.extractOne(
                query,
                choices,
                scorer=fuzz.WRatio,
                score_cutoff=0,
            )
            if fallback:
                _, _, idx = fallback
                return _format_icd10cm(codes[idx])
        return None

    def map_conditions(self, conditions: list[str]) -> dict[str, Optional[str]]:
        out: dict[str, Optional[str]] = {}
        for c in conditions:
            out[c] = self.map_condition_to_icd10cm(c)
        return out

    def is_valid_icd10cm_code(self, code: str) -> bool:
        if not code:
            return False
        normalized = code.strip().upper().replace(".", "")
        return normalized in _load_valid_icd10cm_codes()

    def normalize_code_if_valid(self, code: str) -> Optional[str]:
        if not self.is_valid_icd10cm_code(code):
            return None
        return _format_icd10cm(code)

    def _query_nlm_icd10cm_api(self, query: str) -> Optional[str]:
        """
        U.S. NLM ClinicalTables ICD-10-CM search endpoint:
        https://clinicaltables.nlm.nih.gov/apidoc/icd10cm/v3/doc.html
        """
        if not query:
            return None
        try:
            url = "https://clinicaltables.nlm.nih.gov/api/icd10cm/v3/search"
            params = {
                "sf": "code,name",
                "terms": query,
                "maxList": 7,
            }
            response = requests.get(url, params=params, timeout=8)
            response.raise_for_status()
            payload = response.json()
            # Typical shape:
            # [totalCount, matchedTerms, [codes...], [[code, name], ...]]
            if not isinstance(payload, list) or len(payload) < 3:
                return None
            codes = payload[2]
            if isinstance(codes, list) and codes:
                code = str(codes[0]).strip().upper()
                return code if code else None
            return None
        except Exception:
            return None

    def _pick_best_by_preferred_substrings(
        self,
        query: str,
        choices: list[str],
        codes: list[str],
        preferred_substrings: list[str],
    ) -> Optional[str]:
        best: tuple[int, str] | None = None  # (score, code)

        for sub in preferred_substrings:
            sub_low = sub.lower()
            for desc, code in zip(choices, codes):
                if sub_low in desc:
                    # Score candidates relative to the query to pick a stable winner
                    # when multiple descriptions share the substring.
                    score = fuzz.token_sort_ratio(query, desc)
                    if best is None or score > best[0]:
                        best = (score, code)
            if best is not None:
                # Prefer earlier substrings if they yield at least one candidate.
                break

        return _format_icd10cm(best[1]) if best else None

    def _map_condition_via_rules(
        self,
        query: str,
        choices: list[str],
        codes: list[str],
    ) -> Optional[str]:
        q = query.strip()

        if not q:
            return None

        # Diabetes mellitus (generic -> "other specified ... without complications" as a best-effort default).
        if "diabetes mellitus" in q:
            if "neonatal" in q:
                return self._pick_best_by_preferred_substrings(
                    q,
                    choices,
                    codes,
                    ["neonatal diabetes mellitus"],
                )
            if "type 1" in q:
                return self._pick_best_by_preferred_substrings(
                    q,
                    choices,
                    codes,
                    ["type 1 diabetes mellitus without complications", "type 1 diabetes mellitus"],
                )
            if "type 2" in q:
                return self._pick_best_by_preferred_substrings(
                    q,
                    choices,
                    codes,
                    ["type 2 diabetes mellitus without complications", "type 2 diabetes mellitus"],
                )
            if "gestational" in q or "pregnancy" in q or "childbirth" in q:
                return self._pick_best_by_preferred_substrings(
                    q,
                    choices,
                    codes,
                    ["unspecified diabetes mellitus in pregnancy", "unspecified diabetes mellitus in childbirth"],
                )

            # Generic diabetes mellitus without explicit type/modifier.
            return self._pick_best_by_preferred_substrings(
                q,
                choices,
                codes,
                ["other specified diabetes mellitus without complications", "diabetes mellitus without complications", "diabetes mellitus"],
            )

        # Hypertension (generic -> essential/primary hypertension)
        if "hypertension" in q:
            if "pulmonary hypertension" in q or "portal hypertension" in q:
                # Let fuzzy matcher handle more specific hypertension types for now.
                return None
            return self._pick_best_by_preferred_substrings(
                q,
                choices,
                codes,
                ["essential (primary) hypertension"],
            )

        # Asthma (generic -> unspecified asthma, uncomplicated)
        if "asthma" in q:
            if "status asthmaticus" in q:
                return self._pick_best_by_preferred_substrings(
                    q,
                    choices,
                    codes,
                    ["unspecified asthma with status asthmaticus"],
                )
            if "exacerbation" in q or "acute" in q:
                return self._pick_best_by_preferred_substrings(
                    q,
                    choices,
                    codes,
                    ["unspecified asthma with (acute) exacerbation"],
                )
            return self._pick_best_by_preferred_substrings(
                q,
                choices,
                codes,
                ["unspecified asthma, uncomplicated"],
            )

        return None

