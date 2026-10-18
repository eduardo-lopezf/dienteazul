"""Record module — the clinical record as a composition.

Composes what the installed modules hold about a patient into the shape of a
paper *expediente*: a header, and ordered sections of dated, attributed
entries. It **owns no clinical data**, and that is the point of the design
rather than an omission — see `docs/features/expediente-clinico.md`:

    The record is not a new place to keep clinical data; it is a *view* of
    data seven modules already own, and the moment it becomes a copy it
    starts drifting from the source and there are two truths about a
    patient's allergies.

So the module has no models and no migrations, like `reports`. What it will
own, when those phases arrive, is what genuinely is new: the authorisations
that permit a disclosure (phase 2) and the artifacts a disclosure produces.

**Optional and removable by design.** It is installed from *Configuración →
Módulos*; a clinic that never hands a record to anyone does not need it. The
append-only guarantees it relies on do **not** live here — they are corrections
inside `patients_clinical`, `clinical_notes` and `professionals`, where the
data lives. Uninstalling this module must not make a clinical table deletable
again, which is why those corrections could never have been encapsulated here.
"""

from fastapi import APIRouter

from app.core.plugins import BaseModule

from .router import router


class RecordModule(BaseModule):
    manifest = {
        "name": "record",
        "version": "0.1.0",
        "summary": (
            "The clinical record: composes the installed modules' clinical data "
            "into a patient-scoped document."
        ),
        "author": "Diente Azul Core Team",
        "license": "BSL-1.1",
        "category": "official",
        # Deliberately short. Contributing modules are reached through
        # `get_record_sections()`, a core contract — the record never imports
        # them, so `patients_clinical` and friends are *not* dependencies and
        # the composition simply has fewer sections when one is uninstalled.
        # What is declared is what the header reads directly: who the record is
        # about. Which professional answers for each entry comes through
        # `ProfessionalDirectory` (ADR 0039) and is left out while the
        # Professionals App is off (ADR 0037): integrated, not required.
        "depends": ["patients"],
        "integrates": ["professionals"],
        "installable": True,
        # Off by default: a clinic that never discloses a record does not need
        # it, and phase 0's clinical guarantees do not depend on it being here.
        "auto_install": False,
        # It holds evidence now — the disclosures. Disabled, never
        # uninstalled (ADR 0035).
        "removable": False,
        "role_permissions": {
            "admin": ["*"],
            "dentist": ["read", "disclose"],
            "hygienist": ["read"],
        },
        "frontend": {
            "layer_path": "frontend",
            "navigation": [],
        },
    }

    def get_models(self) -> list:
        # No clinical data, on purpose: the record is a projection. What it
        # owns is the act of handing it over.
        from .models import Disclosure

        return [Disclosure]

    def get_router(self) -> APIRouter:
        return router

    def get_permissions(self) -> list[str]:
        # `export`, `disclose` and `authorise` arrive with the endpoints that
        # use them. A permission with nothing behind it is a promise the UI
        # would start making on its own.
        # `configure`: how the clinic lays its record out. Admin only —
        # nobody else is granted it.
        return ["read", "disclose", "configure"]

    def get_record_sections(self) -> list:
        from . import record

        return record.get_record_sections()

    def get_subject_contributors(self) -> list:
        from . import privacy

        return privacy.get_subject_contributors()

    def get_tools(self) -> list:
        # Mandatory even when empty. An agent-exposed "read this patient's
        # whole clinical record" is a disclosure in everything but name, and
        # it waits for the authorisation phase to say who may ask for one.
        return []
