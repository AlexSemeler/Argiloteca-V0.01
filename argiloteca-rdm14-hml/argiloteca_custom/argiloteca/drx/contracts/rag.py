from __future__ import annotations

from typing import Any

from .common import ContractValidationError, as_mapping, list_value, mapping_value, number, optional_text, required_text, validate_version

RAG_RESPONSE_SCHEMA = "argiloteca.drx.rag_response.v1"


def validate_rag_response(payload: Any) -> dict:
    row = as_mapping(payload, "rag_response")
    validate_version(row)
    row["answer"] = required_text(row, "answer")
    if not isinstance(row.get("available"), bool):
        raise ContractValidationError("available deve ser booleano.")
    row["sources"] = list_value(row, "sources")
    row["model"] = optional_text(row, "model")
    row["elapsed_ms"] = number(row, "elapsed_ms", required=False)
    row["context_filters"] = mapping_value(row, "context_filters")
    row["limitations"] = list_value(row, "limitations")
    return row
