"""Reports background tasks (APScheduler entry points).

One job: mail each clinic that asked for it the one-page summary of the
period that just closed. It opens its own session, commits explicitly,
and is idempotent — the period already sent is recorded, so a restart,
a second worker (ADR 0051) or a re-run sends nothing twice.

The send happens here and never in a request, which is the rule the
notifications gateway exists to protect. It does not go *through* that
gateway because the recipients are the clinic's own staff reading the
clinic's own figures: consent, `do_not_contact` and patient preferences
have nothing to say about it, and the outbox is a patient audit trail.
"""

from __future__ import annotations

import logging
from uuid import UUID

from sqlalchemy import select

from app.core.auth.models import Clinic
from app.core.email import EmailMessage, email_service
from app.database import async_session_maker

from . import monthly, schedule
from .models import SummarySchedule

logger = logging.getLogger(__name__)

SUBJECT = "Resumen de {clinic} · {start} a {end}"

BODY_TEXT = """Hola,

Adjunto va el resumen de {clinic} del {start} al {end}, en una página.

Lo envía Diente Azul automáticamente. Para cambiar la frecuencia o quién
lo recibe, entra en Productividad y abre el envío programado.
"""

BODY_HTML = """<p>Hola,</p>
<p>Adjunto va el resumen de <strong>{clinic}</strong> del {start} al {end},
en una página.</p>
<p style="color:#666;font-size:13px">Lo envía Diente Azul automáticamente.
Para cambiar la frecuencia o quién lo recibe, entra en Productividad y abre
el envío programado.</p>
"""


async def send_scheduled_summaries() -> None:
    """Mail the one-page summary to every clinic due today."""
    async with async_session_maker() as db:
        schedules = await schedule.active_schedules(db)

    for standing_order in schedules:
        try:
            await _send_one(standing_order.clinic_id)
        except Exception:  # noqa: BLE001 — one clinic must not stop the rest
            logger.exception(
                "reports: scheduled summary failed for clinic %s", standing_order.clinic_id
            )


async def _send_one(clinic_id: UUID) -> None:
    async with async_session_maker() as db:
        standing_order = await db.get(SummarySchedule, clinic_id)
        if standing_order is None or not standing_order.is_active:
            return
        clinic = (await db.execute(select(Clinic).where(Clinic.id == clinic_id))).scalar_one()

        today = schedule.clinic_today(clinic.timezone)
        period = schedule.period_due(standing_order.cadence, today)
        if period is None:
            return
        start, end = period
        if schedule.already_sent(standing_order, end):
            return

        pdf = await monthly.render_pdf(db, clinic, start, end)
        filename = monthly.filename(clinic.id, start, end)
        words = {
            "clinic": clinic.name,
            "start": start.strftime("%d/%m/%Y"),
            "end": end.strftime("%d/%m/%Y"),
        }

        sent_to_someone = False
        for address in standing_order.recipients:
            result = await email_service.send(
                EmailMessage(
                    to_email=address,
                    subject=SUBJECT.format(**words),
                    body_html=BODY_HTML.format(**words),
                    body_text=BODY_TEXT.format(**words),
                    attachments=[{"filename": filename, "content": pdf}],
                ),
                db=db,
                clinic_id=clinic.id,
            )
            if result.is_success:
                sent_to_someone = True
            else:
                logger.warning(
                    "reports: summary to %s failed for clinic %s: %s",
                    address,
                    clinic.id,
                    result.error_message,
                )

        # Only a send that reached somebody closes the period. A clinic
        # whose SMTP was down gets the summary on the next run instead of
        # silently never getting it.
        if sent_to_someone:
            standing_order.last_sent_for = end
            await db.commit()
