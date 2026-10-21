"""The reference catalogue, read from ``reference/<specialty>.json``.

One file per recognised discipline (ADR 0047, ADR 0048). A file is what a
specialist reviews: the discipline's name, its sub-areas, and its
treatments — each saying everything about itself. Nothing is derived from
the shape of a code: the disciplines a treatment belongs to, its browsing
category, its stage of care and its sub-area are written on it.

A treatment is written **once**, in the file of the discipline it belongs
to first, and lists every discipline that claims it (``specialties``). The
panoramic radiograph lives in ``general.json`` and names Radiology too.

The files are validated when this module is imported: an unknown field, a
repeated code, or a treatment naming a discipline, a category or a
sub-area that does not exist stops the application from starting, rather
than seeding a clinic with a catalogue that is quietly wrong.
"""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

REFERENCE_DIR = Path(__file__).parent / "reference"

#: Every recognised discipline, in the order they are offered. There is a
#: file for each, and no file for anything else.
SPECIALTY_ORDER: tuple[str, ...] = (
    "general",
    "higiene",
    "endodoncia",
    "periodoncia",
    "cirugia",
    "implantologia",
    "ortodoncia",
    "odontopediatria",
    "estetica",
    "rehabilitacion",
    "radiologia",
    "patologia_oral",
    "medicina_oral",
    "dolor_orofacial",
    "odontologia_sueno",
    "protesis_laboratorio",
    "odontogeriatria",
)

#: The browsing categories a treatment may be filed under (``seed.CATEGORIES``).
CATEGORY_KEYS: tuple[str, ...] = (
    "diagnostico",
    "preventivo",
    "restauradora",
    "endodoncia",
    "periodoncia",
    "cirugia",
    "ortodoncia",
    "estetica",
    "protesis",
    "pediatrica",
)

Phase = Literal[
    "urgencia",
    "diagnostico",
    "preventivo",
    "estabilizacion",
    "rehabilitacion",
    "estetica",
    "mantenimiento",
]
Scope = Literal["tooth", "multi_tooth", "global_mouth", "global_arch"]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Names(_Strict):
    es: str = Field(min_length=1)
    en: str = Field(min_length=1)


class Subarea(_Strict):
    key: str = Field(pattern=r"^[a-z_]+$")
    names: Names


class SessionTemplate(_Strict):
    sequence: int | None = None
    labels: dict[str, str] = {}
    default_price: Decimal


class ReferenceTreatment(_Strict):
    """One treatment of the reference catalogue."""

    code: str = Field(pattern=r"^[A-Z0-9][A-Z0-9-]*$", max_length=50)
    names: Names
    descriptions: dict[str, str] | None = None
    #: Where the treatment is found when browsing the catalogue.
    category: str
    #: Its sub-area within the discipline whose file it is in.
    subarea: str
    #: Every discipline that claims it. The file's own comes first.
    specialties: list[str] = Field(min_length=1)
    #: Stage of care a plan files it under by default.
    phase: Phase
    scope: Scope
    #: The teeth it can be done on: a primary tooth, a permanent one, or any.
    dentition: Literal["both", "deciduous", "permanent"] = "both"
    #: A starting point for the clinic to replace, not a tariff.
    price: Decimal | None = None
    cost_price: Decimal | None = None
    minutes: int | None = Field(default=None, ge=0)
    vat_type: str = "exempt"
    pricing_strategy: str = "flat"
    pricing_config: dict[str, Any] | None = None
    surface_prices: dict[str, Any] | None = None
    requires_appointment: bool | None = None
    is_diagnostic: bool | None = None
    requires_surfaces: bool | None = None
    material_notes: str | None = None
    #: What it draws on the tooth chart, when it draws anything.
    odontogram_treatment_type: str | None = None
    visualization_rules: list[dict[str, Any]] | None = None
    visualization_config: dict[str, Any] | None = None
    #: Per-session billing template, for treatments paid over several visits.
    sessions: list[SessionTemplate] | None = None


class SpecialtyFile(_Strict):
    key: str
    names: Names
    #: Enabled in every new clinic. The rest are enabled on request.
    baseline: bool
    subareas: list[Subarea]
    treatments: list[ReferenceTreatment]

    @model_validator(mode="after")
    def _consistent(self) -> SpecialtyFile:
        known = {subarea.key for subarea in self.subareas}
        if len(known) != len(self.subareas):
            raise ValueError(f"{self.key}: a sub-area is listed twice")
        for treatment in self.treatments:
            if treatment.subarea not in known:
                raise ValueError(f"{treatment.code}: unknown sub-area {treatment.subarea!r}")
            if treatment.specialties[0] != self.key:
                raise ValueError(f"{treatment.code}: its file's discipline must come first")
        return self


def _load() -> dict[str, SpecialtyFile]:
    files: dict[str, SpecialtyFile] = {}
    for path in sorted(REFERENCE_DIR.glob("*.json")):
        try:
            parsed = SpecialtyFile.model_validate(json.loads(path.read_text(encoding="utf-8")))
        except ValueError as error:
            raise ValueError(f"reference/{path.name}: {error}") from error
        if parsed.key != path.stem:
            raise ValueError(f"reference/{path.name}: key {parsed.key!r} does not match the file")
        files[parsed.key] = parsed

    if set(files) != set(SPECIALTY_ORDER):
        raise ValueError(
            "reference/: expected one file per discipline; "
            f"missing {sorted(set(SPECIALTY_ORDER) - set(files))}, "
            f"unexpected {sorted(set(files) - set(SPECIALTY_ORDER))}"
        )

    seen: dict[str, str] = {}
    for key in SPECIALTY_ORDER:
        for treatment in files[key].treatments:
            if treatment.code in seen:
                raise ValueError(
                    f"{treatment.code} is in both {seen[treatment.code]}.json and {key}.json"
                )
            seen[treatment.code] = key
            if treatment.category not in CATEGORY_KEYS:
                raise ValueError(f"{treatment.code}: unknown category {treatment.category!r}")
            unknown = set(treatment.specialties) - set(SPECIALTY_ORDER)
            if unknown:
                raise ValueError(f"{treatment.code}: unknown disciplines {sorted(unknown)}")
    return {key: files[key] for key in SPECIALTY_ORDER}


#: discipline key -> its file, in ``SPECIALTY_ORDER``.
SPECIALTY_FILES: dict[str, SpecialtyFile] = _load()

#: code -> (the discipline whose file holds it, the treatment).
BY_CODE: dict[str, tuple[str, ReferenceTreatment]] = {
    treatment.code: (key, treatment)
    for key, file in SPECIALTY_FILES.items()
    for treatment in file.treatments
}


def seed_item(treatment: ReferenceTreatment) -> dict[str, Any]:
    """A reference treatment in the shape the catalogue's columns take."""
    item: dict[str, Any] = {
        "internal_code": treatment.code,
        "names": treatment.names.model_dump(),
        "treatment_scope": treatment.scope,
        "dentition": treatment.dentition,
        "default_price": treatment.price,
        "default_duration_minutes": treatment.minutes,
        "vat_type": treatment.vat_type,
        "pricing_strategy": treatment.pricing_strategy,
    }
    optional = {
        "descriptions": treatment.descriptions,
        "cost_price": treatment.cost_price,
        "pricing_config": treatment.pricing_config,
        "surface_prices": treatment.surface_prices,
        "requires_appointment": treatment.requires_appointment,
        "is_diagnostic": treatment.is_diagnostic,
        "requires_surfaces": treatment.requires_surfaces,
        "material_notes": treatment.material_notes,
        "odontogram_treatment_type": treatment.odontogram_treatment_type,
        "visualization_rules": treatment.visualization_rules,
        "visualization_config": treatment.visualization_config,
    }
    item.update({name: value for name, value in optional.items() if value is not None})
    if treatment.sessions is not None:
        item["sessions"] = [
            {
                **({"sequence": s.sequence} if s.sequence is not None else {}),
                "labels": s.labels,
                "default_price": s.default_price,
            }
            for s in treatment.sessions
        ]
    return item


def treatments_by_category() -> dict[str, list[dict[str, Any]]]:
    """Every reference treatment, grouped by browsing category."""
    grouped: dict[str, list[dict[str, Any]]] = {key: [] for key in CATEGORY_KEYS}
    for file in SPECIALTY_FILES.values():
        for treatment in file.treatments:
            grouped[treatment.category].append(seed_item(treatment))
    return grouped
