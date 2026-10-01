"""Dataset export and quality report."""
from __future__ import annotations

from collections import Counter
from datetime import date
from pathlib import Path

import pandas as pd

from .models import Company, Enrichment

COLUMNS = [
    "nom", "secteur", "description", "site_web", "ville", "taille",
    "email_contact_generique", "page_recrutement", "source_url",
    "date_collecte", "statut_prospection", "notes",
]


def build_frame(
    rows: list[tuple[Company, Enrichment]], default_status: str, collected_on: date
) -> pd.DataFrame:
    records = []
    for company, enr in rows:
        notes = [f"enrichissement={enr.status}"]
        notes.extend(f"{k}={v}" for k, v in company.extra.items() if v)
        records.append({
            "nom": company.nom,
            "secteur": company.secteur,
            "description": company.description or enr.activite,
            "site_web": company.site_web,
            "ville": company.ville,
            "taille": enr.taille,
            "email_contact_generique": company.email_contact_generique or enr.email_contact_generique,
            "page_recrutement": company.page_recrutement or enr.page_recrutement,
            "source_url": company.source_url,
            "date_collecte": collected_on.isoformat(),
            "statut_prospection": default_status,
            "notes": "; ".join(notes),
        })
    return pd.DataFrame.from_records(records, columns=COLUMNS)


def write_outputs(frame: pd.DataFrame, csv_path: Path, xlsx_path: Path) -> None:
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(csv_path, index=False, encoding="utf-8-sig")
    frame.to_excel(xlsx_path, index=False, engine="openpyxl")


def write_report(
    frame: pd.DataFrame,
    rows: list[tuple[Company, Enrichment]],
    expected: int,
    count_warning: str | None,
    path: Path,
) -> None:
    skipped = [(c.nom, e.status) for c, e in rows if e.status not in ("ok", "not_attempted")]
    reasons = Counter(status for _, status in skipped)
    lines = [
        "# Rapport qualite",
        "",
        f"- Lignes: {len(frame)} (attendu: environ {expected})",
    ]
    if count_warning:
        lines.append(f"- Ecart: {count_warning}")
    lines += ["", "## Champs manquants", "", "| Champ | Manquants | Taux |", "|---|---|---|"]
    for column in COLUMNS:
        missing = int((frame[column].fillna("").astype(str).str.strip() == "").sum())
        rate = missing / len(frame) if len(frame) else 0.0
        lines.append(f"| {column} | {missing} | {rate:.0%} |")
    lines += ["", "## Entreprises ignorees ou en echec", ""]
    if reasons:
        lines += [f"- {reason}: {count}" for reason, count in sorted(reasons.items())]
        lines += ["", "| Entreprise | Raison |", "|---|---|"]
        lines += [f"| {name} | {reason} |" for name, reason in skipped]
    else:
        lines.append("Aucune.")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
