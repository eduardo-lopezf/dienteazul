"""Migration import module — DPMF importer.

Optional, installable/removable module that consumes a Dental Practice
Migration Format (DPMF v0.1) file produced by `dental-bridge` and
hydrates Diente Azul's core modules with the extracted data.

Issue #78. The on-disk format is frozen and documented in
https://github.com/dentaltix/dental-bridge/blob/main/spec/dpmf-v0.1.md
— this module is the receiving end.

Key invariants:

- Cross-module FKs are confined to `media.documents` (binary staging).
  All other writes go through each target module's service layer so
  business events fire normally.
- `verifactu` is intentionally **not** declared in `manifest.depends`:
  Portuguese / French clinics must be able to import without it. The
  fiscal-document mapper detects verifactu at runtime via the module
  registry and gates legal-hash preservation behind operator opt-in.
- Idempotent: every persisted Diente Azul row is recorded in
  ``entity_mappings`` keyed by ``(clinic_id, source_system,
  canonical_uuid, entity_type)`` so re-running a job is a no-op.
"""

from fastapi import APIRouter

from app.core.plugins import BaseModule
from app.core.scheduling import ScheduledJob

from .lifecycle import install, uninstall
from .models import (
    EntityMapping,
    ExportJob,
    FileStaging,
    ImportCreatedRow,
    ImportJob,
    ImportWarning,
    MappingDecision,
    RawEntity,
)
from .router import router


class MigrationImportModule(BaseModule):
    """Optional module that imports a DPMF file into the current clinic."""

    manifest = {
        "name": "migration_import",
        "version": "0.1.0",
        "summary": (
            "Importa datos de pacientes, citas, presupuestos, pagos y "
            "documentos desde un archivo DPMF generado por dental-bridge."
        ),
        "author": "Diente Azul Core Team",
        "license": "BSL-1.1",
        "category": "official",
        # Nothing is required (ADR 0037): the App runs on its own and
        # writes into whichever of these is running. A kind of record
        # whose App is off is skipped with a warning, and shows as such
        # in the preview (``mappers.ENTITY_REQUIRES``). ``verifactu`` is
        # detected at runtime the same way.
        "depends": [],
        "integrates": [
            "patients",
            "patients_clinical",
            "catalog",
            "odontogram",
            "treatment_plan",
            "media",
            "clinical_notes",
            "agenda",
            "schedules",
            "recalls",
            "professionals",
            "budget",
            "payments",
            "billing",
            # Consent letters and their templates (Clinical record App).
            "consents",
        ],
        # Project convention: optional modules ship off; admin activates.
        "installable": True,
        "auto_install": False,
        "removable": True,
        "role_permissions": {
            # Migration is admin-only by default. A clinic operator
            # role can be widened from the manifest later if needed.
            "admin": ["*"],
        },
        "frontend": {
            "layer_path": "frontend",
            "navigation": [],  # surfaced via the settings registry, not the sidebar
        },
    }

    def get_models(self) -> list:
        return [
            ImportJob,
            EntityMapping,
            FileStaging,
            ImportWarning,
            # Was missing here while its table existed, so the list the
            # core reads off this method was one short of the branch: the
            # pre-drop backup (`processor._tables_for`) left the
            # operator's catalog decisions out of the dump, and the
            # foreign-key check that blocks a removal could not see a
            # reference to them.
            MappingDecision,
            RawEntity,
            ExportJob,
            ImportCreatedRow,
        ]

    def get_router(self) -> APIRouter:
        return router

    def get_subject_contributors(self) -> list:
        from . import privacy

        return privacy.get_subject_contributors()

    def get_scheduled_jobs(self) -> list[ScheduledJob]:
        from .tasks import expire_exports

        return [
            ScheduledJob(
                id="migration_import_expire_exports",
                func=expire_exports,
                trigger="interval",
                trigger_args={"hours": 1},
                name="Remove export files past their retention (hourly)",
            ),
        ]

    def get_permissions(self) -> list[str]:
        return [
            "job.read",
            "job.write",
            "job.execute",
            "binary.write",
            "export.run",
        ]

    def get_event_handlers(self) -> dict:
        # No internal subscriptions: the progress counter is now bumped
        # in the same session+commit boundary as the entity inserts (see
        # ``service._run_pipeline``). The
        # ``MIGRATION_ENTITY_PERSISTED`` event is still emitted once per
        # batch for external consumers that want to react to migration
        # progress.
        return {}

    async def install(self, ctx) -> None:  # noqa: D401 — lifecycle hook
        await install(ctx)

    async def uninstall(self, ctx) -> None:  # noqa: D401 — lifecycle hook
        await uninstall(ctx)
