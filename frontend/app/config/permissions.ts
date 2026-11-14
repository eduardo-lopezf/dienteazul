/**
 * Centralized permission configuration.
 *
 * All permission checks should reference this config instead of
 * hardcoding permission strings throughout the codebase.
 */

// Resource-action permission mapping
export const PERMISSIONS = {
  patients: {
    read: 'patients.read',
    write: 'patients.write'
  },
  medicalHistory: {
    read: 'patients_clinical.medical.read',
    write: 'patients_clinical.medical.write'
  },
  asa: {
    read: 'patients_clinical.asa.read',
    write: 'patients_clinical.asa.write'
  },
  emergencyContact: {
    read: 'patients_clinical.emergency.read',
    write: 'patients_clinical.emergency.write'
  },
  appointments: {
    read: 'agenda.appointments.read',
    write: 'agenda.appointments.write'
  },
  calendarFeed: {
    manage: 'calendar_feed.subscription.manage'
  },
  users: {
    read: 'admin.users.read',
    write: 'admin.users.write'
  },
  odontogram: {
    read: 'odontogram.read',
    write: 'odontogram.write',
    treatmentsRead: 'odontogram.treatments.read',
    treatmentsWrite: 'odontogram.treatments.write'
  },
  purchasing: {
    suppliersRead: 'purchasing.suppliers.read',
    suppliersWrite: 'purchasing.suppliers.write',
    ordersRead: 'purchasing.orders.read',
    ordersWrite: 'purchasing.orders.write',
    ordersReceive: 'purchasing.orders.receive'
  },
  inventory: {
    stockRead: 'inventory.stock.read',
    stockWrite: 'inventory.stock.write',
    stockAdjust: 'inventory.stock.adjust',
    itemsRead: 'inventory.items.read',
    itemsWrite: 'inventory.items.write',
    implantsRead: 'inventory.implants.read',
    implantsWrite: 'inventory.implants.write'
  },
  catalog: {
    read: 'catalog.read',
    write: 'catalog.write',
    admin: 'catalog.admin'
  },
  budget: {
    read: 'budget.read',
    write: 'budget.write',
    admin: 'budget.admin',
    renegotiate: 'budget.renegotiate',
    acceptInClinic: 'budget.accept_in_clinic'
  },
  professionals: {
    read: 'professionals.read',
    write: 'professionals.write'
  },
  billing: {
    read: 'billing.read',
    write: 'billing.write',
    admin: 'billing.admin'
  },
  notifications: {
    templatesRead: 'notifications.templates.read',
    templatesWrite: 'notifications.templates.write',
    preferencesRead: 'notifications.preferences.read',
    preferencesWrite: 'notifications.preferences.write',
    logsRead: 'notifications.logs.read',
    send: 'notifications.send',
    settingsRead: 'notifications.settings.read',
    settingsWrite: 'notifications.settings.write'
  },
  reports: {
    billingRead: 'reports.billing.read',
    budgetsRead: 'reports.budgets.read',
    schedulingRead: 'reports.scheduling.read',
    materialsRead: 'reports.materials.read',
    summaryRead: 'reports.summary.read',
    actionableRead: 'reports.actionable.read',
    summaryWrite: 'reports.summary.write'
  },
  documents: {
    read: 'media.documents.read',
    write: 'media.documents.write'
  },
  attachments: {
    read: 'media.attachments.read',
    write: 'media.attachments.write'
  },
  treatmentPlans: {
    read: 'treatment_plan.plans.read',
    write: 'treatment_plan.plans.write',
    confirm: 'treatment_plan.plans.confirm',
    close: 'treatment_plan.plans.close',
    reactivate: 'treatment_plan.plans.reactivate',
    prescriptionsRead: 'treatment_plan.prescriptions.read',
    prescriptionsWrite: 'treatment_plan.prescriptions.write'
  },
  clinicalNotes: {
    read: 'clinical_notes.notes.read',
    write: 'clinical_notes.notes.write'
  },
  privacy: {
    subjectRead: 'privacy.subject.read',
    subjectExport: 'privacy.subject.export',
    subjectErase: 'privacy.subject.erase'
  },
  agents: {
    view: 'agents.view',
    supervise: 'agents.supervise',
    configure: 'agents.configure',
    manage: 'agents.manage'
  },
  consents: {
    read: 'consents.read',
    write: 'consents.write',
    templatesWrite: 'consents.templates.write'
  },
  admin: {
    clinicRead: 'admin.clinic.read',
    clinicWrite: 'admin.clinic.write'
  },
  migrationImport: {
    jobRead: 'migration_import.job.read',
    jobWrite: 'migration_import.job.write',
    jobExecute: 'migration_import.job.execute',
    binaryWrite: 'migration_import.binary.write',
    exportRun: 'migration_import.export.run'
  },
  payments: {
    recordRead: 'payments.record.read',
    recordWrite: 'payments.record.write',
    recordRefund: 'payments.record.refund',
    reportsRead: 'payments.reports.read'
  },
  record: {
    // The clinical record is read-only for now. `export`, `disclose` and
    // `authorise` arrive with the endpoints that use them — a permission with
    // nothing behind it is a promise the UI starts making on its own.
    read: 'record.read',
    // Printing or handing the record over (ADR 0033).
    disclose: 'record.disclose',
    // How the clinic lays its record out. Admin only.
    configure: 'record.configure'
  },
  commissions: {
    agreementRead: 'commissions.agreement.read',
    agreementWrite: 'commissions.agreement.write'
  },
  memberships: {
    planRead: 'memberships.plan.read',
    planWrite: 'memberships.plan.write',
    membershipRead: 'memberships.membership.read',
    membershipWrite: 'memberships.membership.write'
  },
  liquidations: {
    settlementRead: 'liquidations.settlement.read',
    settlementIssue: 'liquidations.settlement.issue',
    commissionWrite: 'liquidations.commission.write'
  },
  cashbox: {
    movementRead: 'cashbox.movement.read',
    movementWrite: 'cashbox.movement.write',
    closingRead: 'cashbox.closing.read',
    closingWrite: 'cashbox.closing.write',
    closingReopen: 'cashbox.closing.reopen'
  },
  satCfdi: {
    cfdiRead: 'sat_cfdi.cfdi.read',
    receiverWrite: 'sat_cfdi.receiver.write',
    settingsRead: 'sat_cfdi.settings.read',
    settingsConfigure: 'sat_cfdi.settings.configure'
  },
  verifactu: {
    settingsRead: 'verifactu.settings.read',
    settingsConfigure: 'verifactu.settings.configure',
    queueManage: 'verifactu.queue.manage',
    recordsRead: 'verifactu.records.read',
    environmentPromote: 'verifactu.environment.promote'
  },
  recalls: {
    read: 'recalls.read',
    write: 'recalls.write',
    delete: 'recalls.delete'
  },
  whatsappKapso: {
    settingsRead: 'whatsapp_kapso.settings.read',
    settingsWrite: 'whatsapp_kapso.settings.write'
  },
  schedules: {
    clinicHoursRead: 'schedules.clinic_hours.read',
    clinicHoursWrite: 'schedules.clinic_hours.write',
    professionalRead: 'schedules.professional.read',
    professionalWrite: 'schedules.professional.write',
    professionalOwnRead: 'schedules.professional.own.read',
    professionalOwnWrite: 'schedules.professional.own.write'
  },
  periodontogram: {
    read: 'periodontogram.read',
    write: 'periodontogram.write'
  },
  copilot: {
    chat: 'copilot.chat',
    historyRead: 'copilot.history.read',
    historyReadAll: 'copilot.history.read_all',
    supervise: 'copilot.supervise',
    configure: 'copilot.configure'
  },
  accountingExport: {
    read: 'accounting_export.export.read',
    run: 'accounting_export.export.run'
  }
} as const
