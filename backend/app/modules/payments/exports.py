"""The collections report as downloadable tables.

One CSV per card of `/reports/payments`, built from the same
`PaymentReportsService` the screen reads — nothing is recomputed here, so
the file and the screen cannot disagree.

**Off-books boundary (ADR 0010).** This is the collection axis and only
the collection axis: what came in, what went back out, what is owed by
age. No column is ever placed next to what was invoiced, and none is
derived from that difference. A reader who wants the invoice axis
exports Facturación, which is a separate file by design.
"""

from __future__ import annotations

from datetime import date
from typing import Literal
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exports import to_csv

from .service import PaymentReportsService

Granularity = Literal["day", "week", "month", "year"]

#: The words for the keys the database stores. The screen translates
#: these on the way out; a CSV opened in Excel has no screen to do it.
#: Mirrors `invoice.payments.methods.*` in `frontend/i18n/locales/es.json`.
PAYMENT_METHOD_ES = {
    "cash": "Efectivo",
    "card": "Tarjeta",
    "bank_transfer": "Transferencia",
    "direct_debit": "Domiciliación",
    "insurance": "Aseguradora",
    "other": "Otro",
}

#: ``RefundReason`` (schemas.py), in the clinic's words. These have no
#: i18n key to mirror: `payments.refund.reasonCodes.*` is missing from the
#: locales, so the refund dialog shows the raw code too.
REFUND_REASON_ES = {
    "duplicate": "Cobro duplicado",
    "overpaid": "Cobro de más",
    "treatment_cancelled": "Tratamiento cancelado",
    "dispute": "Reclamación",
    "other": "Otro",
}


def _label(table: dict[str, str], key: str | None) -> str:
    """The Spanish word, or the raw key when the table does not know it."""
    if key is None:
        return ""
    return table.get(key, key)


async def collection_files(
    db: AsyncSession,
    clinic_id: UUID,
    currency: str,
    timezone: str,
    date_from: date,
    date_to: date,
    granularity: Granularity,
    separator: str,
) -> dict[str, bytes]:
    """Cobros: the period's collection, and the debt as it stands today."""
    summary = await PaymentReportsService.summary(
        db, clinic_id, currency, date_from, date_to, timezone
    )
    trends = await PaymentReportsService.trends(
        db, clinic_id, currency, date_from, date_to, granularity, timezone
    )
    by_method = await PaymentReportsService.by_method(db, clinic_id, date_from, date_to)
    by_professional = await PaymentReportsService.by_professional(
        db, clinic_id, date_from, date_to, timezone
    )
    aging = await PaymentReportsService.aging_receivables(db, clinic_id, currency)
    refunds = await PaymentReportsService.refunds_report(
        db, clinic_id, currency, date_from, date_to, timezone
    )

    resumen = [
        {
            "desde": summary.period_start,
            "hasta": summary.period_end,
            "moneda": summary.currency,
            "cobrado": summary.total_collected,
            "devuelto": summary.total_refunded,
            "cobrado_neto": summary.net_collected,
            "cobros": summary.payment_count,
            "devoluciones": summary.refund_count,
            "tasa_de_devoluciones": summary.refund_ratio,
            "saldo_a_favor_pacientes_hoy": summary.patient_credit_total,
            "pendiente_de_cobro_hoy": summary.clinic_receivable_total,
        }
    ]

    return {
        "resumen.csv": to_csv(
            resumen,
            [
                "desde",
                "hasta",
                "moneda",
                "cobrado",
                "devuelto",
                "cobrado_neto",
                "cobros",
                "devoluciones",
                "tasa_de_devoluciones",
                "saldo_a_favor_pacientes_hoy",
                "pendiente_de_cobro_hoy",
            ],
            separator,
        ),
        "evolucion.csv": to_csv(
            [
                {
                    "inicio_del_tramo": point.bucket_start,
                    "cobrado": point.collected,
                    "devuelto": point.refunded,
                    "neto": point.net,
                }
                for point in trends.points
            ],
            ["inicio_del_tramo", "cobrado", "devuelto", "neto"],
            separator,
        ),
        "por-metodo.csv": to_csv(
            [
                {
                    "metodo": _label(PAYMENT_METHOD_ES, row.method),
                    "importe": row.total,
                    "movimientos": row.count,
                }
                for row in by_method
            ],
            ["metodo", "importe", "movimientos"],
            separator,
        ),
        "por-profesional.csv": to_csv(
            [
                {
                    "profesional": row.professional_name or "",
                    "tratamiento_ejecutado": row.total_earned,
                    "movimientos": row.count,
                }
                for row in by_professional
            ],
            ["profesional", "tratamiento_ejecutado", "movimientos"],
            separator,
        ),
        "antiguedad-hoy.csv": to_csv(
            [
                {
                    "tramo": bucket.label,
                    "pendiente": bucket.total,
                    "pacientes": bucket.patient_count,
                }
                for bucket in aging.buckets
            ],
            ["tramo", "pendiente", "pacientes"],
            separator,
        ),
        "devoluciones-por-motivo.csv": to_csv(
            [
                {
                    "motivo": _label(REFUND_REASON_ES, row.get("reason_code")),
                    "importe": row.get("total"),
                    "devoluciones": row.get("count"),
                }
                for row in refunds.by_reason
            ],
            ["motivo", "importe", "devoluciones"],
            separator,
        ),
    }
