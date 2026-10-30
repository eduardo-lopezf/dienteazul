"""Productividad reports as downloadable tables.

Each builder returns the files of one report screen: the same figures the
screen shows, in the same period, one CSV per card. Nothing is computed
here — every row comes from the report services, so the download and the
screen cannot disagree (and a fix to an aggregation fixes both).

Headers are the column names a person will read in Excel, in Spanish and
snake_case, and they double as the row dict's keys — the convention
``accounting_export`` already set.
"""

from __future__ import annotations

from datetime import date
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exports import period_filename, to_csv

from .services import BillingReportService, BudgetReportService, SchedulingReportService

#: Re-exported so the router reads one name for both halves of the feature.
period_name = period_filename


# The services answer in the keys the database stores — ``sent``, ``monday``,
# ``direct_debit`` — and the screen translates them on the way out. A file
# opened in Excel has no screen to do that, and "sent" in a column headed
# "estado" reads as a bug, so the words live here. The backend has no i18n
# and the clinic's UI is Spanish, so there is nothing to negotiate.
# They mirror `budget.status.*`, `invoice.payments.methods.*` and
# `common.days.*` in `frontend/i18n/locales/es.json`.
BUDGET_STATUS_ES = {
    "draft": "Borrador",
    "sent": "Enviado",
    "accepted": "Aceptado",
    "completed": "Completado",
    "invoiced": "Facturado",
    "rejected": "Rechazado",
    "expired": "Caducado",
    "cancelled": "Cancelado",
}

PAYMENT_METHOD_ES = {
    "cash": "Efectivo",
    "card": "Tarjeta",
    "bank_transfer": "Transferencia",
    "direct_debit": "Domiciliación",
    "insurance": "Aseguradora",
    "other": "Otro",
}

WEEKDAY_ES = {
    "monday": "Lunes",
    "tuesday": "Martes",
    "wednesday": "Miércoles",
    "thursday": "Jueves",
    "friday": "Viernes",
    "saturday": "Sábado",
    "sunday": "Domingo",
}


def _label(table: dict[str, str], key: str | None) -> str:
    """The Spanish word, or the raw key when the table does not know it.

    Falling back to the key keeps an unknown value visible instead of
    turning it into an empty cell somebody has to investigate.
    """
    if key is None:
        return ""
    return table.get(key, key)


async def billing_files(
    db: AsyncSession,
    clinic_id: UUID,
    date_from: date,
    date_to: date,
    separator: str,
) -> dict[str, bytes]:
    """Facturación: the period's invoicing, plus the two *as of today* tables."""
    summary = await BillingReportService.get_summary(db, clinic_id, date_from, date_to)
    by_method = await BillingReportService.get_by_payment_method(db, clinic_id, date_from, date_to)
    by_professional = await BillingReportService.get_by_professional(
        db, clinic_id, date_from, date_to
    )
    vat = await BillingReportService.get_vat_summary(db, clinic_id, date_from, date_to)
    overdue = await BillingReportService.get_overdue_invoices(db, clinic_id, limit=1000)
    gaps = await BillingReportService.get_numbering_gaps(db, clinic_id)

    resumen = [
        {
            "desde": summary["period_start"],
            "hasta": summary["period_end"],
            "total_facturado": summary["total_invoiced"],
            "facturas": summary["invoice_count"],
            "total_cobrado": summary["total_paid"],
            "facturas_pagadas": summary["paid_count"],
            "pendiente_de_cobro_hoy": summary["total_pending"],
            "facturas_vencidas_hoy": summary["overdue_count"],
        }
    ]

    return {
        "resumen.csv": to_csv(
            resumen,
            [
                "desde",
                "hasta",
                "total_facturado",
                "facturas",
                "total_cobrado",
                "facturas_pagadas",
                "pendiente_de_cobro_hoy",
                "facturas_vencidas_hoy",
            ],
            separator,
        ),
        "por-metodo-de-pago.csv": to_csv(
            [
                {
                    "metodo": _label(PAYMENT_METHOD_ES, row["payment_method"]),
                    "importe": row["total_amount"],
                    "pagos": row["payment_count"],
                }
                for row in by_method
            ],
            ["metodo", "importe", "pagos"],
            separator,
        ),
        "por-profesional.csv": to_csv(
            [
                {
                    "profesional": row["professional_name"],
                    "total_facturado": row["total_invoiced"],
                    "facturas": row["invoice_count"],
                }
                for row in by_professional
            ],
            ["profesional", "total_facturado", "facturas"],
            separator,
        ),
        "desglose-iva.csv": to_csv(
            [
                {
                    "tipo_iva": row["vat_name"],
                    "porcentaje": row["vat_rate"],
                    "base": row["base_amount"],
                    "cuota": row["tax_amount"],
                    "total": row["total_amount"],
                }
                for row in vat
            ],
            ["tipo_iva", "porcentaje", "base", "cuota", "total"],
            separator,
        ),
        "facturas-vencidas.csv": to_csv(
            [
                {
                    "factura": row["invoice_number"],
                    "paciente": row["patient_name"],
                    "fecha_emision": row["issue_date"],
                    "fecha_vencimiento": row["due_date"],
                    "dias_de_retraso": row["days_overdue"],
                    "pendiente": row["balance_due"],
                }
                for row in overdue
            ],
            [
                "factura",
                "paciente",
                "fecha_emision",
                "fecha_vencimiento",
                "dias_de_retraso",
                "pendiente",
            ],
            separator,
        ),
        "huecos-de-numeracion.csv": to_csv(
            [
                {
                    "serie": row["series_prefix"],
                    "ejercicio": row["year"],
                    "numeros_que_faltan": ", ".join(str(n) for n in row["missing_numbers"]),
                }
                for row in gaps
            ],
            ["serie", "ejercicio", "numeros_que_faltan"],
            separator,
        ),
    }


async def budget_files(
    db: AsyncSession,
    clinic_id: UUID,
    date_from: date,
    date_to: date,
    separator: str,
) -> dict[str, bytes]:
    """Presupuestos: what was quoted in the period and how it was answered."""
    summary = await BudgetReportService.get_summary(db, clinic_id, date_from, date_to)
    by_status = await BudgetReportService.get_by_status(db, clinic_id, date_from, date_to)
    by_professional = await BudgetReportService.get_by_professional(
        db, clinic_id, date_from, date_to
    )
    by_treatment = await BudgetReportService.get_by_treatment(db, clinic_id, date_from, date_to)

    resumen = [
        {
            "desde": summary["period_start"],
            "hasta": summary["period_end"],
            "creados": summary["total_created"],
            "importe_total": summary["total_amount"],
            "aceptados": summary["accepted_count"],
            "importe_aceptado": summary["accepted_amount"],
            "rechazados": summary["rejected_count"],
            "pendientes": summary["pending_count"],
            "completados": summary["completed_count"],
            "tasa_de_aceptacion": summary["acceptance_rate"],
            "valor_medio": summary["average_value"],
        }
    ]

    return {
        "resumen.csv": to_csv(
            resumen,
            [
                "desde",
                "hasta",
                "creados",
                "importe_total",
                "aceptados",
                "importe_aceptado",
                "rechazados",
                "pendientes",
                "completados",
                "tasa_de_aceptacion",
                "valor_medio",
            ],
            separator,
        ),
        "por-estado.csv": to_csv(
            [
                {
                    "estado": _label(BUDGET_STATUS_ES, row["status"]),
                    "presupuestos": row["count"],
                    "importe": row["total_amount"],
                }
                for row in by_status
            ],
            ["estado", "presupuestos", "importe"],
            separator,
        ),
        "por-profesional.csv": to_csv(
            [
                {
                    "profesional": row["professional_name"],
                    "presupuestos": row["budget_count"],
                    "importe": row["total_amount"],
                    "aceptados": row["accepted_count"],
                    "tasa_de_aceptacion": row["acceptance_rate"],
                }
                for row in by_professional
            ],
            ["profesional", "presupuestos", "importe", "aceptados", "tasa_de_aceptacion"],
            separator,
        ),
        "por-tratamiento.csv": to_csv(
            [
                {
                    "tratamiento": row["treatment_name"],
                    "apariciones": row["occurrence_count"],
                    "cantidad": row["total_quantity"],
                    "importe": row["total_amount"],
                }
                for row in by_treatment
            ],
            ["tratamiento", "apariciones", "cantidad", "importe"],
            separator,
        ),
    }


async def scheduling_files(
    db: AsyncSession,
    clinic_id: UUID,
    date_from: date,
    date_to: date,
    separator: str,
) -> dict[str, bytes]:
    """Agenda: how the period's appointments went, and who worked them."""
    summary = await SchedulingReportService.get_summary(db, clinic_id, date_from, date_to)
    first_visits = await SchedulingReportService.get_first_visits(db, clinic_id, date_from, date_to)
    by_professional = await SchedulingReportService.get_hours_by_professional(
        db, clinic_id, date_from, date_to
    )
    by_cabinet = await SchedulingReportService.get_cabinet_utilization(
        db, clinic_id, date_from, date_to
    )
    by_day = await SchedulingReportService.get_by_day_of_week(db, clinic_id, date_from, date_to)

    resumen = [
        {
            "desde": summary["period_start"],
            "hasta": summary["period_end"],
            "citas": summary["total_appointments"],
            "completadas": summary["completed"],
            "canceladas": summary["cancelled"],
            "no_show": summary["no_show"],
            "tasa_de_completado": summary["completion_rate"],
            "tasa_de_cancelacion": summary["cancellation_rate"],
            "tasa_de_no_show": summary["no_show_rate"],
            "pacientes_nuevos": first_visits["new_patients"],
            "tasa_de_primeras_visitas": first_visits["first_visit_rate"],
        }
    ]

    return {
        "resumen.csv": to_csv(
            resumen,
            [
                "desde",
                "hasta",
                "citas",
                "completadas",
                "canceladas",
                "no_show",
                "tasa_de_completado",
                "tasa_de_cancelacion",
                "tasa_de_no_show",
                "pacientes_nuevos",
                "tasa_de_primeras_visitas",
            ],
            separator,
        ),
        "por-profesional.csv": to_csv(
            [
                {
                    "profesional": row["professional_name"],
                    "citas": row["appointment_count"],
                    "completadas": row["completed_count"],
                    "canceladas": row["cancelled_count"],
                    "no_show": row["no_show_count"],
                    "horas": row["total_hours"],
                }
                for row in by_professional
            ],
            ["profesional", "citas", "completadas", "canceladas", "no_show", "horas"],
            separator,
        ),
        "por-gabinete.csv": to_csv(
            [
                {
                    "gabinete": row["cabinet"],
                    "citas": row["appointment_count"],
                    "completadas": row["completed_count"],
                    "horas": row["total_hours"],
                }
                for row in by_cabinet
            ],
            ["gabinete", "citas", "completadas", "horas"],
            separator,
        ),
        "por-dia-de-la-semana.csv": to_csv(
            [
                {
                    "dia": _label(WEEKDAY_ES, row["day_name"]),
                    "citas": row["appointment_count"],
                    "completadas": row["completed_count"],
                    "canceladas": row["cancelled_count"],
                    "no_show": row["no_show_count"],
                }
                for row in by_day
            ],
            ["dia", "citas", "completadas", "canceladas", "no_show"],
            separator,
        ),
    }
