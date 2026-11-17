"""Export helpers for processed DRX curves and classifications."""

from __future__ import annotations

import csv
import json
from pathlib import Path


def save_json(path: str | Path, payload: dict | list) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as fp:
        json.dump(payload, fp, ensure_ascii=False, indent=2)
        fp.write("\n")
    return path


def save_curve_csv(path: str | Path, two_theta: list[float], intensity: list[float]) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="") as fp:
        writer = csv.DictWriter(fp, fieldnames=["two_theta", "intensity"])
        writer.writeheader()
        for theta, value in zip(two_theta, intensity):
            writer.writerow({"two_theta": theta, "intensity": value})
    return path


def read_curve_csv(path: str | Path) -> tuple[list[float], list[float]]:
    two_theta = []
    intensity = []
    with open(path, "r", encoding="utf-8", newline="") as fp:
        reader = csv.DictReader(fp)
        for row in reader:
            two_theta.append(float(row["two_theta"]))
            intensity.append(float(row["intensity"]))
    return two_theta, intensity
