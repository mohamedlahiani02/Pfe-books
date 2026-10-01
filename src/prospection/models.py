"""Data models."""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Company:
    nom: str
    secteur: str = ""
    description: str = ""
    site_web: str = ""
    ville: str = ""
    source_url: str = ""
    email_contact_generique: str = ""
    page_recrutement: str = ""
    extra: dict[str, str] = field(default_factory=dict)


@dataclass
class Enrichment:
    activite: str = ""
    taille: str = ""
    email_contact_generique: str = ""
    page_recrutement: str = ""
    status: str = "not_attempted"
