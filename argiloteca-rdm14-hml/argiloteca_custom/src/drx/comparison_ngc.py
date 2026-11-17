"""Natural/glycolated/calcined preparation classification."""

from __future__ import annotations

import re
from pathlib import Path


PREPARATION_LABELS = {
    "natural": "Natural",
    "glicolado": "Glicolado",
    "calcinado": "Calcinado",
    "indeterminado": "Indeterminado",
}


def infer_preparation_from_name(path_or_name: str | Path) -> dict:
    """Infer preparation from the local file naming convention.

    The rule is explicit and intentionally conservative:
    N/-N means natural, G/-G means glycolated, C/-C means calcined.
    """
    path = Path(path_or_name)
    stem = path.stem.strip()
    upper = stem.upper()
    rules = (
        (r"(?:^|[-_])N$", "natural", "sufixo -N"),
        (r"(?:^|[-_])G$", "glicolado", "sufixo -G"),
        (r"(?:^|[-_])C$", "calcinado", "sufixo -C"),
        (r"(?:CAL|CALC|CALCIN|AQUEC|HEAT|550|500|350|300)", "calcinado", "marcador textual/temperatura"),
        (r"N$", "natural", "sufixo N"),
        (r"G$", "glicolado", "sufixo G"),
        (r"C$", "calcinado", "sufixo C"),
    )
    for pattern, preparation, evidence in rules:
        if re.search(pattern, upper):
            return {
                "preparation": preparation,
                "label": PREPARATION_LABELS[preparation],
                "confidence": "alta",
                "evidence": evidence,
                "sample_base": sample_base(stem, preparation),
            }
    return {
        "preparation": "indeterminado",
        "label": PREPARATION_LABELS["indeterminado"],
        "confidence": "baixa",
        "evidence": "sem marcador N/G/C no nome",
        "sample_base": stem,
    }


def sample_base(stem: str, preparation: str) -> str:
    marker = {"natural": "N", "glicolado": "G", "calcinado": "C"}.get(preparation)
    upper = stem.upper()
    if marker and (upper.endswith("-" + marker) or upper.endswith("_" + marker)):
        return stem[:-2]
    if marker and upper.endswith(marker):
        return stem[:-1]
    return stem


def group_by_sample_base(rows: list[dict]) -> list[dict]:
    grouped: dict[str, list[dict]] = {}
    for row in rows:
        grouped.setdefault(row["sample_base"], []).append(row)
    groups = []
    for base, items in sorted(grouped.items()):
        preparations = sorted({item["preparation"] for item in items})
        groups.append(
            {
                "sample_base": base,
                "preparations": preparations,
                "files": sorted(item["filename"] for item in items),
                "has_natural_glicolado_pair": "natural" in preparations and "glicolado" in preparations,
                "has_calcinado": "calcinado" in preparations,
            }
        )
    return groups
