from __future__ import annotations


class MedicalCodingError(Exception):
    """Base class for errors in the medical coding pipeline."""


class NoDiseasesFoundError(MedicalCodingError):
    """Raised when no medical conditions/diseases are extracted."""


class NoCodesFoundError(MedicalCodingError):
    """Raised when extracted conditions cannot be mapped to ICD-10-CM codes."""

