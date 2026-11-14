import type { BillingSummary, OverdueInvoice } from '~~/app/types'
import type { SchedulingSummary } from '../composables/useReports'

/**
 * Made-up figures for the widget examples in Settings → Widgets
 * (ADR 0040). Nobody here exists; dates are built around *now*.
 */
function daysAgo(days: number): string {
  const d = new Date(Date.now() - days * 86_400_000)
  return d.toISOString().split('T')[0] as string
}

export function sampleOverdueInvoices(): OverdueInvoice[] {
  const rows: [string, number, string][] = [
    ['Laura Demo', 42, '1850.00'],
    ['Iván Muestra', 21, '920.00'],
    ['Carmen Modelo', 9, '450.00']
  ]
  return rows.map(([patient_name, days, balance], i) => ({
    id: `preview-invoice-${i + 1}`,
    invoice_number: `F-2026-00${i + 1}`,
    patient_name,
    issue_date: daysAgo(days + 30),
    due_date: daysAgo(days),
    days_overdue: days,
    balance_due: balance
  }))
}

function scheduling(total: number, completed: number): SchedulingSummary {
  return {
    period_start: daysAgo(6),
    period_end: daysAgo(0),
    total_appointments: total,
    completed,
    cancelled: 2,
    no_show: 1,
    scheduled: total - completed - 3,
    confirmed: 0,
    checked_in: 0,
    in_treatment: 0,
    completion_rate: (completed / total) * 100,
    cancellation_rate: (2 / total) * 100,
    no_show_rate: (1 / total) * 100
  }
}

function billing(invoiced: string): BillingSummary {
  return {
    period_start: daysAgo(6),
    period_end: daysAgo(0),
    total_invoiced: invoiced,
    total_paid: invoiced,
    total_pending: '0.00',
    invoice_count: 12,
    paid_count: 12,
    overdue_count: 0,
    vat_breakdown: []
  }
}

/** This week and the one before, so every figure has a trend. */
export function sampleWeekGlance() {
  return {
    current: { sched: scheduling(48, 41), bill: billing('38400.00') },
    previous: { sched: scheduling(44, 36), bill: billing('35100.00') }
  }
}
