"""calendar_feed — the clinic's agenda as a calendar subscription.

The user copies one URL into Google Calendar, Apple Calendar or Outlook
and their appointments show up there. It needs no Google Cloud project,
no OAuth client and no verified domain, which is the whole point: those
are what a two-way Google Calendar integration would need, and they are
not available yet (ADR 0061).

Read-only and one-way by nature — a calendar client subscribed to a feed
never writes back. Part of the Agenda App (ADR 0044): without an agenda
there is nothing to publish, so it goes off when the agenda does and
needs no `requires_apps` entry of its own. Nothing leaves the clinic
until a user creates a subscription.
"""

from fastapi import APIRouter

from app.core.plugins import BaseModule

from .models import CalendarFeed
from .public_router import public_router
from .router import router


class CalendarFeedModule(BaseModule):
    """Publishes a user's agenda as an iCalendar feed."""

    manifest = {
        "name": "calendar_feed",
        "version": "0.1.0",
        "summary": "Publishes a user's agenda as an iCalendar (.ics) subscription URL.",
        "author": "Diente Azul Core Team",
        "license": "BSL-1.1",
        "category": "official",
        # Nothing is required: this module owns one table of its own and
        # reads everything else through contracts (ADR 0039). With the
        # Agenda App off it issues no new subscription and the documents
        # it serves are empty — the subscriptions survive, and fill again
        # when the App returns (ADR 0037).
        "depends": [],
        "integrates": ["agenda", "professionals"],
        "installable": True,
        # The App in ``apps.json`` is the switch for this feature
        # (ADR 0038), so the module installs with the deployment rather
        # than waiting to be enabled on its own: enabling the App and
        # then hunting for a module to enable is a step nobody would
        # find. Nothing leaves the clinic by default either way — no
        # subscription exists until a user asks for one.
        "auto_install": True,
        # Nothing of record here — a token and the last time it was
        # polled. Uninstalling loses the URLs, nothing else.
        "removable": True,
        "role_permissions": {
            "admin": ["*"],
            "dentist": ["subscription.manage"],
            "hygienist": ["subscription.manage"],
            "assistant": ["subscription.manage"],
            "receptionist": ["subscription.manage"],
        },
        "frontend": {
            "layer_path": "frontend",
            # No screen of its own: the card lives in the host's APIs
            # page through a slot (ADR 0041).
            "navigation": [],
        },
    }

    def get_models(self) -> list:
        return [CalendarFeed]

    def get_router(self) -> APIRouter:
        # The public document rides the same prefix: it is authenticated
        # by the token in its own path, not by a session (ADR 0061).
        combined = APIRouter()
        combined.include_router(router)
        combined.include_router(public_router)
        return combined

    def get_permissions(self) -> list[str]:
        return ["subscription.manage"]

    def get_tools(self) -> list:
        from . import tools

        return tools.get_tools()
