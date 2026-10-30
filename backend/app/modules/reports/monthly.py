"""The clinic's month on one page.

What a dentist takes to the accountant, the partner or the kitchen
table: the period's money, agenda and quotes, in that order, on a single
sheet with the clinic's letterhead. Nothing here is a new figure — every
number comes from the same services the Productividad screens read, so a
page printed on Monday and the screen on Tuesday tell the same story.

**One page is the whole point.** A second page turns a glance into a
document nobody reads, so sections are summaries and lists are capped;
anything longer belongs in the CSV export.

A section appears only while the App that feeds it runs (ADR 0037), and
the collection figures arrive through the `CollectionReport` contract
(ADR 0039) rather than an import of `payments`.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from html import escape
from io import BytesIO
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth.models import Clinic
from app.core.contracts import CollectedPeriod, CollectionReport, ProducedBy, provider
from app.core.letterhead import LETTERHEAD_CSS, render_letterhead
from app.core.utils.currency import format_currency

from .integrations import running
from .services import BillingReportService, BudgetReportService, SchedulingReportService

#: Enough to show who carried the month without spilling onto page two.
TOP_PROFESSIONALS = 5

_CSS = """
  @page { size: A4; margin: 14mm 14mm 12mm 14mm; }
  body { font-family: "Helvetica", "Arial", sans-serif; font-size: 9.5pt; color: #111; }
  h1 { font-size: 15pt; margin: 10px 0 2px; }
  .period { color: #444; font-size: 9pt; margin-bottom: 10px; }
  .grid { display: flex; flex-wrap: wrap; gap: 6px; margin-bottom: 10px; }
  .kpi { flex: 1 1 22%; border: 0.8pt solid #ddd; border-radius: 3pt; padding: 6px 8px; }
  .kpi .label { font-size: 7.5pt; text-transform: uppercase; letter-spacing: .04em; color: #666; }
  .kpi .value { font-size: 13pt; font-weight: 700; }
  .kpi .hint { font-size: 7.5pt; color: #666; }
  h2 { font-size: 10pt; margin: 10px 0 4px; border-bottom: 0.8pt solid #ddd; padding-bottom: 2px; }
  table { width: 100%; border-collapse: collapse; font-size: 9pt; }
  th { text-align: left; font-size: 7.5pt; text-transform: uppercase; color: #666; padding: 2px 0; }
  td { padding: 2px 0; border-top: 0.4pt solid #eee; }
  td.n { text-align: right; font-variant-numeric: tabular-nums; }
  .note { font-size: 7.5pt; color: #666; margin-top: 10px; }
"""


def _money(value: Decimal | None, currency: str) -> str:
    return format_currency(value or Decimal("0"), currency)


def _pct(value: float | None) -> str:
    return "—" if value is None else f"{value:.1f}%"


def _kpi(label: str, value: str, hint: str = "") -> str:
    hint_html = f'<div class="hint">{escape(hint)}</div>' if hint else ""
    return (
        '<div class="kpi">'
        f'<div class="label">{escape(label)}</div>'
        f'<div class="value">{escape(value)}</div>'
        f"{hint_html}</div>"
    )


def _rows(headers: list[str], rows: list[list[str]], numeric_from: int = 1) -> str:
    """A small table, or nothing at all when there is nothing to say."""
    if not rows:
        return '<p class="note">Sin datos en este periodo.</p>'
    head = "".join(f"<th>{escape(h)}</th>" for h in headers)
    body = ""
    for row in rows:
        cells = "".join(
            f'<td class="n">{escape(cell)}</td>'
            if i >= numeric_from
            else f"<td>{escape(cell)}</td>"
            for i, cell in enumerate(row)
        )
        body += f"<tr>{cells}</tr>"
    return f"<table><tr>{head}</tr>{body}</table>"


async def _collection(
    db: AsyncSession, clinic: Clinic, date_from: date, date_to: date
) -> tuple[CollectedPeriod | None, list[ProducedBy]]:
    """The money, if the App that owns it is running."""
    report = provider(CollectionReport)
    if report is None:
        return None, []
    collected = await report.collected_in_period(
        db, clinic.id, clinic.currency, clinic.timezone, date_from, date_to
    )
    produced = await report.produced_by_professional(
        db, clinic.id, clinic.timezone, date_from, date_to
    )
    return collected, produced


async def build_html(db: AsyncSession, clinic: Clinic, date_from: date, date_to: date) -> str:
    """The page, in the order a clinic owner asks its questions."""
    currency = clinic.currency
    letterhead = await render_letterhead(db, clinic.id, None)

    collected, produced = await _collection(db, clinic, date_from, date_to)

    sections: list[str] = []
    kpis: list[str] = []

    if collected is not None:
        average = (
            collected.net_collected / collected.payment_count
            if collected.payment_count
            else Decimal("0")
        )
        kpis += [
            _kpi(
                "Caja cobrada",
                _money(collected.net_collected, currency),
                f"{collected.payment_count} cobros",
            ),
            _kpi("Ticket medio", _money(average, currency)),
            _kpi(
                "Pendiente de cobro",
                _money(collected.receivable_today, currency),
                "a día de hoy",
            ),
        ]

    if running("agenda"):
        scheduling = await SchedulingReportService.get_summary(db, clinic.id, date_from, date_to)
        first_visits = await SchedulingReportService.get_first_visits(
            db, clinic.id, date_from, date_to
        )
        kpis.append(
            _kpi(
                "Pacientes nuevos",
                str(first_visits["new_patients"]),
                f"{scheduling['total_appointments']} citas",
            )
        )
        sections.append(
            "<h2>Agenda</h2>"
            + _rows(
                ["Indicador", "Valor"],
                [
                    ["Citas en el periodo", str(scheduling["total_appointments"])],
                    ["Completadas", str(scheduling["completed"])],
                    ["Canceladas", str(scheduling["cancelled"])],
                    ["No-shows", str(scheduling["no_show"])],
                    ["Tasa de completado", _pct(scheduling["completion_rate"])],
                    ["Tasa de no-show", _pct(scheduling["no_show_rate"])],
                ],
            )
        )

    if produced:
        top = sorted(produced, key=lambda row: row.total, reverse=True)[:TOP_PROFESSIONALS]
        sections.append(
            "<h2>Producción por profesional</h2>"
            + _rows(
                ["Profesional", "Tratamiento ejecutado", "Movimientos"],
                [
                    [
                        row.professional_name or "Sin asignar",
                        _money(row.total, currency),
                        str(row.count),
                    ]
                    for row in top
                ],
            )
        )

    if running("budget"):
        budgets = await BudgetReportService.get_summary(db, clinic.id, date_from, date_to)
        sections.append(
            "<h2>Presupuestos</h2>"
            + _rows(
                ["Indicador", "Valor"],
                [
                    ["Creados", str(budgets["total_created"])],
                    ["Importe presupuestado", _money(budgets["total_amount"], currency)],
                    ["Aceptados", str(budgets["accepted_count"])],
                    ["Importe aceptado", _money(budgets["accepted_amount"], currency)],
                    ["Tasa de aceptación", _pct(budgets["acceptance_rate"])],
                ],
            )
        )

    if running("billing"):
        billing = await BillingReportService.get_summary(db, clinic.id, date_from, date_to)
        sections.append(
            "<h2>Facturación</h2>"
            + _rows(
                ["Indicador", "Valor"],
                [
                    ["Facturado en el periodo", _money(billing["total_invoiced"], currency)],
                    ["Facturas emitidas", str(billing["invoice_count"])],
                    ["Pendiente de cobro (hoy)", _money(billing["total_pending"], currency)],
                    ["Facturas vencidas (hoy)", str(billing["overdue_count"])],
                ],
            )
        )

    body = (f'<div class="grid">{"".join(kpis)}</div>' if kpis else "") + "".join(sections)

    return f"""<!DOCTYPE html>
<html lang="es"><head><meta charset="utf-8">
<style>{LETTERHEAD_CSS}{_CSS}</style></head>
<body>
{letterhead}
<h1>Informe de productividad</h1>
<div class="period">Del {date_from.strftime("%d/%m/%Y")} al {date_to.strftime("%d/%m/%Y")}</div>
{body}
<p class="note">Las cifras marcadas «a día de hoy» no dependen del periodo:
describen el estado actual de la clínica. Lo cobrado y lo facturado son ejes
distintos y no se restan entre sí.</p>
</body></html>"""


async def render_pdf(db: AsyncSession, clinic: Clinic, date_from: date, date_to: date) -> bytes:
    """The page as a PDF. WeasyPrint, like every other document here."""
    from weasyprint import HTML

    html = await build_html(db, clinic, date_from, date_to)
    buffer = BytesIO()
    HTML(string=html).write_pdf(buffer)
    return buffer.getvalue()


def filename(clinic_id: UUID, date_from: date, date_to: date) -> str:  # noqa: ARG001
    return f"productividad_{date_from.isoformat()}_{date_to.isoformat()}.pdf"
