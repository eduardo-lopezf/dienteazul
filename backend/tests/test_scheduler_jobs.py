"""Registry-driven scheduler job declaration (ADR 0014 import-coupling fix).

Modules declare periodic jobs via ``BaseModule.get_scheduled_jobs()``;
the scheduler iterates the registered modules instead of importing task
functions directly. These are pure unit tests — no DB, no APScheduler
start.
"""

from __future__ import annotations

import pytest
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from app.config import Settings, settings
from app.core import scheduler as scheduler_module
from app.core.scheduler import _build_trigger, init_scheduler
from app.core.scheduling import ScheduledJob
from app.modules.budget import BudgetModule
from app.modules.copilot import CopilotModule
from app.modules.notifications import NotificationsModule
from app.modules.sat_cfdi import SatCfdiModule
from app.modules.treatment_plan import TreatmentPlanModule


def test_modules_declare_their_jobs() -> None:
    expected = {
        NotificationsModule: {"appointment_reminders", "notifications_dispatch_outbox"},
        BudgetModule: {"expire_budgets", "send_budget_reminders", "purge_budget_access_logs"},
        TreatmentPlanModule: {"auto_close_expired_plans"},
        CopilotModule: {"copilot_morning_digests"},
        SatCfdiModule: {"sat_cfdi_stamp"},
    }
    for module_cls, ids in expected.items():
        jobs = module_cls().get_scheduled_jobs()
        assert {j.id for j in jobs} == ids
        for job in jobs:
            assert callable(job.func)
            assert job.trigger in ("cron", "interval")


def test_base_module_default_is_no_jobs() -> None:
    # A module that doesn't override the hook contributes nothing — the
    # whole point of decoupling the scheduler from module imports.
    from app.modules.patients import PatientsModule

    assert PatientsModule().get_scheduled_jobs() == []


def test_build_trigger_maps_spec_to_apscheduler() -> None:
    cron = _build_trigger(
        ScheduledJob(id="x", func=lambda: None, trigger="cron", trigger_args={"hour": 2}, name="x")
    )
    assert isinstance(cron, CronTrigger)

    interval = _build_trigger(
        ScheduledJob(
            id="y", func=lambda: None, trigger="interval", trigger_args={"minutes": 5}, name="y"
        )
    )
    assert isinstance(interval, IntervalTrigger)


def test_the_scheduler_is_on_unless_a_deployment_turns_it_off() -> None:
    # One backend is the deployment everybody has: it must keep running
    # its jobs without being told to.
    assert Settings.model_fields["SCHEDULER_ENABLED"].default is True


def test_a_process_with_the_scheduler_off_creates_none(monkeypatch: pytest.MonkeyPatch) -> None:
    """With several backends, all but one start without a scheduler.

    ``TESTING`` is lifted so the switch under test is the one that
    decides. Were it ignored, ``init_scheduler`` would build a scheduler
    and try to start it — outside an event loop, which fails loudly.
    """
    monkeypatch.setattr(settings, "TESTING", False)
    monkeypatch.setattr(settings, "SCHEDULER_ENABLED", False)
    monkeypatch.setattr(scheduler_module, "scheduler", None)

    init_scheduler()

    assert scheduler_module.scheduler is None
