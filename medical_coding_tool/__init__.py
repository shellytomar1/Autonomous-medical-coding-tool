"""
Medical coding tool package.

Primary entrypoint for the workflow is `process_medical_record` in `pipeline.py`.

New in v2.0:
- Autonomous AI agent with self-correcting validation loop
- RAG-enhanced ICD-10 code retrieval
- LangChain-based prompt engineering and agentic orchestration
"""

from medical_coding_tool.agent import (
    SelfCorrectingCodeValidator,
    RAGICD10Retriever,
    AutonomousMedicalCodingAgent,
    ValidationResult,
)

__all__ = [
    "SelfCorrectingCodeValidator",
    "RAGICD10Retriever",
    "AutonomousMedicalCodingAgent",
    "ValidationResult",
]

