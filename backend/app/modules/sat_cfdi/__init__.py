"""SAT (CFDI 4.0) module — Mexico.

Turns billing's invoices into CFDIs stamped by a PAC (Facturama). Plugs
into billing through ``BillingComplianceHook`` for ``MX``; billing never
imports it. The hook only writes ``pending`` CFDIs; stamping runs after
commit (ADR 0067). Design: ``docs/features/sat-cfdi.md``.

So far: the issuer (SAT settings and CSD), the queue, the RFC check and
cancellation requests. Nothing is sent to the PAC yet.
"""

from fastapi import APIRouter

from app.core.plugins import BaseModule

from .models import SatCertificate, SatCfdi, SatReceiver, SatSettings
from .router import router


class SatCfdiModule(BaseModule):
    manifest = {
        "name": "sat_cfdi",
        "version": "0.1.0",
        "summary": "Facturación electrónica CFDI 4.0 ante el SAT para clínicas en México.",
        "author": "Diente Azul Core Team",
        "license": "BSL-1.1",
        "category": "official",
        "depends": ["billing"],
        "installable": True,
        # Runs for every deployment; each clinic switches it on from the
        # Budgets & payments App's settings (`optional_modules` in
        # apps.json, ADR 0066), the advanced and clinic tiers only.
        "auto_install": True,
        # Stamped CFDIs are kept five years: switched off with `disable`
        # (ADR 0035), never uninstalled.
        "removable": False,
        "role_permissions": {
            "admin": ["*"],
            "receptionist": ["cfdi.read", "receiver.write"],
        },
        "egress": [
            {
                "target": "facturama",
                "subprocessor": "Facturama (facturama.mx), PAC autorizado por el SAT",
                "residency": "unspecified",
                "data_classes": ["identifier", "financial"],
                "purpose": (
                    "Sellar y timbrar los CFDI ante el SAT. Sale el CSD de la "
                    "clínica (certificado, llave privada y su contraseña) y, al "
                    "timbrar, el RFC, nombre, régimen y código postal fiscal del "
                    "receptor de cada factura y sus conceptos."
                ),
                "required": True,
            }
        ],
        "frontend": {
            "layer_path": "frontend",
            # A page of Settings → Billing (`plugins/settings.client.ts`),
            # no navigation entry of its own.
            "navigation": [],
        },
    }

    def __init__(self) -> None:
        # Registered on every boot, like any compliance hook; the registry
        # hands it out only while this module is live (`module_name`).
        from app.modules.billing.hooks import BillingHookRegistry

        from .hook import SatCfdiHook

        BillingHookRegistry.register(SatCfdiHook())

    def get_models(self) -> list:
        return [SatCfdi, SatSettings, SatCertificate, SatReceiver]

    def get_router(self) -> APIRouter:
        return router

    def get_permissions(self) -> list[str]:
        return ["cfdi.read", "receiver.write", "settings.read", "settings.configure"]

    def get_subject_contributors(self) -> list:
        from . import privacy

        return privacy.get_subject_contributors()

    def get_scheduled_jobs(self) -> list:
        from app.core.scheduling import ScheduledJob

        from .stamping import stamp_due

        return [
            ScheduledJob(
                id="sat_cfdi_stamp",
                func=stamp_due,
                trigger="interval",
                trigger_args={"minutes": 1},
                name="Stamp pending CFDIs with Facturama (every minute)",
            )
        ]

    def get_tools(self) -> list:
        # Stamping and cancelling stay manual, as billing's issue does.
        return []
