"""What Communications links to, and whether each link is live.

Patients, the agenda, budgets, payments, invoices, the catalog and
professionals belong to other Apps the deployment can switch off. They are
``integrates`` of this module, not ``depends`` (ADR 0037): the App keeps
running — settings, templates, the history — while any of them is off.

- Patients off: nothing is sent to a patient and nothing of the patient's
  is read. The event handlers stand still; a message still enqueued for a
  patient (by hand, by the agent) is recorded as skipped
  (``patients_unavailable``).
- Agenda, budgets or invoices off: their events stop arriving, and the
  reminders and notices that hang from them are not sent.
- Professionals off: messages go out without the professional's name.
"""

from __future__ import annotations

from app.core.plugins.registry import module_registry

PATIENTS_UNAVAILABLE = "The Patients app is not enabled: nothing can be sent to a patient"
#: The reason recorded on a message skipped because Patients is off.
SKIP_PATIENTS_UNAVAILABLE = "patients_unavailable"


def running(*modules: str) -> bool:
    """Whether every one of ``modules`` is running here."""
    return all(module_registry.is_installed(module) for module in modules)
