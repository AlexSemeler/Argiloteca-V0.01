"""Grouping and conservative N/G/C interpretation for DRX diffractograms."""

from __future__ import annotations

import re
from collections import defaultdict
from pathlib import Path


PREPARATION_ALIASES = {
    "natural": "natural",
    "glicolado": "glicolado",
    "glicolada": "glicolado",
    "glycolated": "glicolado",
    "calcinado": "calcinado",
    "calcinada": "calcinado",
    "calcined": "calcinado",
    "indeterminado": "indeterminado",
}


def infer_preparation(value: str | None) -> dict:
    """Infer preparation from file/sample name using explicit markers."""
    stem = Path(str(value or "")).stem.strip()
    upper = stem.upper()
    rules = (
        (r"(?:^|[-_])(?:N|NAT|NATURAL)$", "natural", "marcador natural no nome"),
        (r"(?:^|[-_])(?:G|GLY|GLICOL|GLICOLADA)$", "glicolado", "marcador glicolado no nome"),
        (r"(?:^|[-_])(?:C|CAL|CALC|CALCINADA)$", "calcinado", "marcador calcinado no nome"),
        (r"(?:CAL|CALC|CALCINADA|500|550)", "calcinado", "marcador textual/temperatura"),
        (r"N$", "natural", "sufixo N"),
        (r"G$", "glicolado", "sufixo G"),
        (r"C$", "calcinado", "sufixo C"),
    )
    for pattern, preparation, evidence in rules:
        if re.search(pattern, upper):
            return {
                "preparation": preparation,
                "sample_base": sample_base(stem, preparation),
                "evidence": evidence,
            }
    return {
        "preparation": "indeterminado",
        "sample_base": stem,
        "evidence": "sem marcador N/G/C reconhecido",
    }


def normalize_preparation(value: str | None, fallback_name: str | None = None) -> dict:
    normalized = PREPARATION_ALIASES.get(str(value or "").strip().lower())
    inferred = infer_preparation(fallback_name)
    if normalized:
        inferred["preparation"] = normalized
        inferred["evidence"] = "preparo informado no manifesto"
        inferred["sample_base"] = sample_base(Path(str(fallback_name or "")).stem, normalized)
    return inferred


def sample_base(stem: str, preparation: str) -> str:
    marker_patterns = {
        "natural": (r"[-_](?:N|NAT|NATURAL)$", r"N$"),
        "glicolado": (r"[-_](?:G|GLY|GLICOL|GLICOLADA)$", r"G$"),
        "calcinado": (r"[-_](?:C|CAL|CALC|CALCINADA)$", r"C$"),
    }.get(preparation, ())
    result = stem
    for pattern in marker_patterns:
        result = re.sub(pattern, "", result, flags=re.IGNORECASE)
    return result or stem


def group_ngc(rows: list[dict]) -> list[dict]:
    """Group rows by sample-base and identify N/G/C completeness."""
    grouped = defaultdict(list)
    enriched = []
    for row in rows:
        name = row.get("filename") or row.get("original_filename") or row.get("sample_code") or row.get("id")
        prep = normalize_preparation(row.get("preparation"), name)
        sample_key = row.get("sample_base") or prep["sample_base"] or row.get("sample_code") or name
        enriched_row = {**row, "_ngc_preparation": prep["preparation"], "_ngc_evidence": prep["evidence"]}
        grouped[str(sample_key)].append(enriched_row)
        enriched.append(enriched_row)

    result = []
    for base, items in sorted(grouped.items()):
        by_prep = defaultdict(list)
        for item in items:
            by_prep[item["_ngc_preparation"]].append(item)
        has_known = any(key in by_prep for key in ("natural", "glicolado", "calcinado"))
        complete = all(key in by_prep for key in ("natural", "glicolado", "calcinado"))
        duplicates = {
            key: [item.get("id") or item.get("filename") for item in values]
            for key, values in by_prep.items()
            if key != "indeterminado" and len(values) > 1
        }
        status = "completo" if complete else ("incompleto" if has_known else "indeterminado")
        evidence = [item["_ngc_evidence"] for item in items if item.get("_ngc_evidence")]
        group = {
            "sample_base": base,
            "natural": _first_id(by_prep.get("natural")),
            "glicolada": _first_id(by_prep.get("glicolado")),
            "calcinada": _first_id(by_prep.get("calcinado")),
            "status": status,
            "duplicates": duplicates,
            "indeterminados": [_first_id([item]) for item in by_prep.get("indeterminado", [])],
            "evidence": sorted(set(evidence)),
        }
        group["basal_interpretation"] = interpret_basal_evidence(items)
        group["ngc_score"] = score_ngc_trajectory(items, sample_base=base)
        result.append(group)
    return result


def _first_id(items):
    if not items:
        return None
    item = items[0]
    return item.get("id") or item.get("diffractogram_id") or item.get("filename") or item.get("sample_code")


def interpret_basal_evidence(items: list[dict]) -> dict:
    """Return conservative assisted basal evidence for grouped N/G/C curves."""
    by_prep = {item.get("_ngc_preparation") or item.get("preparation"): item for item in items}
    natural = _basal_windows(by_prep.get("natural"))
    glycolated = _basal_windows(by_prep.get("glicolado"))
    calcined = _basal_windows(by_prep.get("calcinado"))
    evidence = []
    suggestions = []

    if glycolated.get("17A"):
        evidence.append("pico próximo de 17 Å após glicolação")
        suggestions.append("compatível com esmectita expansiva")
    if natural.get("15A"):
        evidence.append("pico próximo de 15 Å no natural")
    if natural.get("14A") and glycolated.get("14A"):
        evidence.append("pico próximo de 14 Å estável entre natural e glicolado")
        suggestions.append("compatível com clorita, requer revisão")
    if natural.get("10A"):
        evidence.append("pico próximo de 10 Å")
        suggestions.append("compatível com ilita/mica")
    if natural.get("7A"):
        evidence.append("pico próximo de 7 Å")
        suggestions.append("compatível com caulinita/clorita, requer revisão")
    if calcined and natural.get("7A") and not calcined.get("7A"):
        evidence.append("pico próximo de 7 Å alterado/desaparecido após calcinação")
        suggestions.append("alteração térmica compatível com fase 1:1, pendente de curadoria")

    if not evidence:
        suggestions.append("evidência insuficiente")
    return {
        "status": "interpretação assistida, pendente de curadoria",
        "suggestions": sorted(set(suggestions)),
        "evidence": evidence,
    }


def _basal_windows(item: dict | None) -> dict[str, dict]:
    if not item:
        return {}
    peaks = item.get("basal_peaks") or item.get("peaks") or item.get("detected_peaks") or []
    found = {}
    for peak in peaks:
        d_value = _d_value(peak)
        if d_value is None:
            continue
        if 16.2 <= d_value <= 17.8:
            found["17A"] = peak
        if 14.4 <= d_value <= 15.8:
            found["15A"] = peak
        if 13.4 <= d_value <= 14.6:
            found["14A"] = peak
        if 9.5 <= d_value <= 10.5:
            found["10A"] = peak
        if 6.8 <= d_value <= 7.4:
            found["7A"] = peak
    return found


def _d_value(peak: dict):
    value = (
        peak.get("d")
        or peak.get("d_spacing")
        or peak.get("d_angstrom")
        or peak.get("center_d_angstrom")
        or peak.get("expected_d")
    )
    try:
        value = float(value)
    except (TypeError, ValueError):
        return None
    return value


def score_ngc_trajectory(items: list[dict], sample_base: str | None = None) -> dict:
    """Score a conservative natural/glycolated/calcined basal trajectory.

    The score supports triage and reporting. It never confirms a mineral on its
    own; hypotheses remain assisted interpretations pending curation.
    """
    by_prep = {item.get("_ngc_preparation") or item.get("preparation"): item for item in items}
    natural = by_prep.get("natural")
    glycolated = by_prep.get("glicolado")
    calcined = by_prep.get("calcinado")
    missing = []
    if not natural:
        missing.append("natural")
    if not glycolated:
        missing.append("glicolado")
    if not calcined:
        missing.append("calcinado")

    n = _basal_windows(natural)
    g = _basal_windows(glycolated)
    c = _basal_windows(calcined)
    n_basal = n.get("15A") or n.get("14A")
    g_expanded = g.get("17A")
    c_collapsed = c.get("10A")

    n_d = _d_value(n_basal) if n_basal else None
    g_d = _d_value(g_expanded) if g_expanded else None
    c_d = _d_value(c_collapsed) if c_collapsed else None
    shift_ng = round(g_d - n_d, 4) if g_d is not None and n_d is not None else None
    shift_gc = round(c_d - g_d, 4) if c_d is not None and g_d is not None else None

    completeness = (3 - len(missing)) / 3
    expansion = 0.0
    if n_basal and g_expanded and shift_ng is not None and shift_ng >= 1.0:
        expansion = 1.0
    elif g_expanded:
        expansion = 0.65

    collapse = 0.0
    if g_expanded and c_collapsed and shift_gc is not None and shift_gc <= -5.0:
        collapse = 1.0
    elif c_collapsed and (n_basal or g_expanded):
        collapse = 0.55

    stability_10 = _stability_score(n.get("10A"), g.get("10A"), c.get("10A"))
    stability_14 = _stability_score(n.get("14A"), g.get("14A"), c.get("14A"))
    stability_7 = _stability_score(n.get("7A"), g.get("7A"), c.get("7A"))
    stability = max(stability_10, stability_14, stability_7)
    score = round(
        (0.20 * completeness)
        + (0.25 * expansion)
        + (0.20 * collapse)
        + (0.20 * stability)
        + (0.15 * max(expansion, collapse, stability)),
        4,
    )

    evidence = []
    hypotheses = []
    if n_basal:
        evidence.append(_peak_text("Natural", n_basal))
    if g_expanded:
        evidence.append(_peak_text("Glicolado", g_expanded))
    if c_collapsed:
        evidence.append(_peak_text("Calcinado", c_collapsed))
    if expansion >= 1.0 and collapse >= 1.0:
        hypotheses.append("compatível com esmectita/montmorilonita expansiva")
        evidence.append("expansão N→G e colapso G→C coerentes")
    elif expansion > 0:
        hypotheses.append("compatível com argilomineral expansivo; requer calcinação/curadoria")
    if stability_10 >= 0.65 and not g_expanded:
        hypotheses.append("compatível com ilita/mica por estabilidade em ~10 Å")
    if stability_14 >= 0.65 and not g_expanded:
        hypotheses.append("compatível com clorita/vermiculita; revisar comportamento térmico")
    if stability_7 > 0:
        hypotheses.append("compatível com caulinita/clorita, requer revisão por sobreposição em ~7 Å")
    if not hypotheses:
        hypotheses.append("evidência insuficiente para hipótese mineralógica N/G/C")

    warnings = [f"preparo {name} ausente" for name in missing]
    confidence = "baixa"
    if score >= 0.75 and not missing:
        confidence = "alta"
    elif score >= 0.45:
        confidence = "média"

    return {
        "sample_base": sample_base,
        "score": score,
        "confidence": confidence,
        "status": "trio completo" if not missing else ("trio incompleto" if len(missing) < 3 else "indeterminado"),
        "components": {
            "completude_tratamentos": round(completeness, 4),
            "expansao_n_g": round(expansion, 4),
            "colapso_g_c": round(collapse, 4),
            "estabilidade_10a": round(stability_10, 4),
            "estabilidade_14a": round(stability_14, 4),
            "estabilidade_7a": round(stability_7, 4),
        },
        "shifts": {
            "natural_to_glycolated": shift_ng,
            "glycolated_to_calcined": shift_gc,
        },
        "hypotheses": sorted(set(hypotheses)),
        "evidence": sorted(set(evidence)),
        "warnings": warnings,
        "basal_peaks": {
            "natural": _peak_payload(n_basal),
            "glicolado": _peak_payload(g_expanded),
            "calcinado": _peak_payload(c_collapsed),
        },
    }


def _stability_score(*peaks: dict | None) -> float:
    count = len([peak for peak in peaks if peak])
    if count >= 3:
        return 1.0
    if count == 2:
        return 0.75
    if count == 1:
        return 0.35
    return 0.0


def _peak_text(label: str, peak: dict) -> str:
    d_value = _d_value(peak)
    theta = peak.get("two_theta") or peak.get("center_2theta")
    relative = peak.get("relative_intensity") or peak.get("intensity_relative")
    parts = [label]
    if d_value is not None:
        parts.append(f"d {d_value:.2f} Å")
    try:
        theta = float(theta)
        parts.append(f"2θ {theta:.2f}°")
    except (TypeError, ValueError):
        pass
    try:
        relative = float(relative)
        parts.append(f"I rel. {relative:.1f}%")
    except (TypeError, ValueError):
        pass
    return " com pico em ".join([parts[0], " / ".join(parts[1:])]) if len(parts) > 1 else label


def _peak_payload(peak: dict | None) -> dict | None:
    if not peak:
        return None
    return {
        "d": _d_value(peak),
        "two_theta": peak.get("two_theta") or peak.get("center_2theta"),
        "relative_intensity": peak.get("relative_intensity") or peak.get("intensity_relative"),
    }
