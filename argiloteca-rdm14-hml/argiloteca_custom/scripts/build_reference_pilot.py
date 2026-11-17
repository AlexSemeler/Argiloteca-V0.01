#!/usr/bin/env python3
"""Build the bounded COD-inorganic/AMCSD pilot from pinned local CIFs.

No network or database writes. Uses the existing open_patterns simulator.
"""
import argparse
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import sys
import tempfile
import warnings

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from argiloteca_custom.scripts.open_patterns.fetch_open_patterns import simulate_cif_pattern
from pymatgen.io.cif import CifParser
from pymatgen.analysis.structure_matcher import StructureMatcher


def build(source_dir, output):
    source_dir, output = Path(source_dir), Path(output)
    plan = json.loads((source_dir / "source-plan.json").read_text())
    rows, rejected, known = [], [], []
    for item in plan["references"]:
        path = source_dir / item["filename"]
        try:
            content = path.read_bytes()
            with warnings.catch_warnings(record=True) as notes:
                parser = CifParser(str(path), check_cif=True)
                structure = parser.parse_structures(primitive=False)[0]
                metadata = next(iter(parser.as_dict().values()))
                sim = simulate_cif_pattern(path, wavelength_a=1.5406)
            name = str(metadata.get("_chemical_name_mineral", "")).strip("'\"")
            if name.casefold() != item["mineral_name"].casefold():
                raise ValueError("Mineral name differs from the source selection plan.")
            if not sim or len(sim["peaks"]) < 2:
                raise ValueError("No usable calculated pattern.")
            # Selected inorganic formulas are reviewed in the plan; carbonates remain allowed.
            title = str(metadata.get("_publ_section_title", "")).strip()
            authors = metadata.get("_publ_author_name", [])
            if isinstance(authors, str):
                authors = [authors]
            citation = "; ".join(authors) + " (" + str(metadata.get("_journal_year", "?")) + "). " + title
            citation += ". " + str(metadata.get("_journal_name_full", "")) + " " + str(metadata.get("_journal_volume", ""))
            group = item["source"] + ":" + item["source_id"]
            for prior_structure, prior_group, prior_mineral in known:
                if prior_mineral == item["mineral_id"] and StructureMatcher().fit(prior_structure, structure):
                    group = prior_group
                    break
            known.append((structure, group, item["mineral_id"]))
            rows.append({**{k: v for k, v in item.items() if k not in {"filename"}},
                         "reference_id": item["source"].lower() + ":" + item["source_id"],
                         "source_sha256": hashlib.sha256(content).hexdigest(), "source_revision": item.get("source_revision", "hash-pinned"),
                         "structure_group": group, "citation": citation,
                         "doi": metadata.get("_journal_paper_doi"), "formula": structure.composition.reduced_formula,
                         "cell": list(structure.lattice.parameters), "pattern_kind": "calculated",
                         "conditions": title, "preparation": "unknown_not_an_ngc_measurement",
                         "wavelength_angstrom": 1.5406, "two_theta_range": [2, 70],
                         "source_date": plan["downloaded_at"], "inorganic_selection": "reviewed_mineral_formula_not_carbon_exclusion",
                         "warnings": sorted(set(str(n.message) for n in notes)),
                         "peaks": [{"d_angstrom": p["d_A"], "relative_intensity": p["relative_intensity"],
                                    "hkl": p.get("hkl"), "two_theta": p["two_theta_deg"]} for p in sim["peaks"]]})
        except Exception as exc:
            rejected.append({"filename": item["filename"], "reason": str(exc)})
    payload = {"schema_version": "argiloteca.drx.reference_pilot_index.v1", "index_version": "cod-amcsd-pilot-20261020-v2",
               "engine": {"name": "pymatgen.XRDCalculator", "pymatgen": importlib.metadata.version("pymatgen"),
                          "pymatgen-core": importlib.metadata.version("pymatgen-core"), "wavelength_angstrom": 1.5406,
                          "symprec": 0, "two_theta_range": [2, 70], "intensity_scaling": "maximum_100"},
               "source_plan_sha256": hashlib.sha256((source_dir / "source-plan.json").read_bytes()).hexdigest(),
               "coverage": {"minerals": sorted({r["mineral_id"] for r in rows}), "rejected": rejected,
                            "scope": "bounded_pilot_not_complete_amcsd_or_cod_inorganics"}, "references": rows}
    if rejected or {r["source"] for r in rows} != {"AMCSD", "COD"}:
        raise ValueError(json.dumps({"error": "Incomplete pilot; index was not activated", "rejected": rejected}))
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(mode="w", dir=output.parent, delete=False) as stream:
        json.dump(payload, stream, indent=2, ensure_ascii=False, allow_nan=False)
        tmp = Path(stream.name)
    os.replace(tmp, output)
    return {"references": len(rows), "minerals": len(payload["coverage"]["minerals"]), "rejected": rejected}


if __name__ == "__main__":
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("source_dir")
    cli.add_argument("output")
    args = cli.parse_args()
    print(json.dumps(build(args.source_dir, args.output)))
