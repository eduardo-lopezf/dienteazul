"""Mapper registry — one mapper per DPMF entity type.

A mapper is anything with an ``async apply(...)`` method (duck-typed via
:class:`base.Mapper`). The :data:`MAPPERS` dict maps DPMF entity_type →
mapper instance; entries missing from the dict fall back to
:data:`FALLBACK_MAPPER` (writes a :class:`RawEntity` row for forward-compat).

Adding a new mapper:

1. Drop a module under ``mappers/`` with a class implementing
   ``async apply(ctx, *, entity_type, payload, raw, canonical_uuid,
   source_id, source_system)``.
2. Add it to :data:`MAPPERS` below.
3. Ensure the target module is listed in
   ``MigrationImportModule.manifest['depends']`` (unless integration is
   runtime-tolerant like ``verifactu``).
"""

from __future__ import annotations

from .applied_treatment import AppliedTreatmentMapper
from .applied_treatment_phase import AppliedTreatmentPhaseMapper
from .appointment import AppointmentMapper
from .base import MapperContext, MappingResolver, ProfessionalFilterOptions, running
from .budget import BudgetMapper
from .budget_line import BudgetLineMapper
from .catalog import CatalogItemMapper as TreatmentCatalogItemMapper
from .catalog_item import CatalogItemMapper
from .catalog_variant import CatalogVariantMapper
from .debt import DebtMapper
from .document import DocumentMapper
from .fiscal_document import FiscalDocumentMapper
from .fiscal_document_line import FiscalDocumentLineMapper
from .native import (
    HISTORIES,
    MEDICAL_ENTRIES,
    ClinicalNoteMapper,
    ClinicalTreatmentMapper,
    CollectionContactMapper,
    ConsentTemplateMapper,
    DocumentAttachmentMapper,
    EarnedEntryMapper,
    HealthQuestionnaireMapper,
    MedicalContextMapper,
    PatientConsentMapper,
    PatientInvoiceMapper,
    PatientPaymentMapper,
    PaymentScheduleMapper,
    PrescriptionMapper,
    StoredDocumentMapper,
    ToothRecordMapper,
    TreatmentBudgetMapper,
    TreatmentPlanMapper,
)
from .patient import PatientMapper
from .patient_alert import PatientAlertMapper
from .patient_client_link import PatientClientLinkMapper
from .payment import PaymentMapper
from .pharmacological_history import PharmacologicalHistoryMapper
from .professional import ProfessionalMapper
from .raw import RawEntityMapper
from .recall import RecallMapper
from .user import UserMapper

PatientMapperInst = PatientMapper()
ProfessionalMapperInst = ProfessionalMapper()
UserMapperInst = UserMapper()
DocumentMapperInst = DocumentMapper()
PaymentMapperInst = PaymentMapper()
FiscalDocumentMapperInst = FiscalDocumentMapper()
FiscalDocumentLineMapperInst = FiscalDocumentLineMapper()
AppointmentMapperInst = AppointmentMapper()
TreatmentCatalogItemMapperInst = TreatmentCatalogItemMapper()
CatalogItemMapperInst = CatalogItemMapper()
CatalogVariantMapperInst = CatalogVariantMapper()
BudgetMapperInst = BudgetMapper()
BudgetLineMapperInst = BudgetLineMapper()
AppliedTreatmentMapperInst = AppliedTreatmentMapper()
AppliedTreatmentPhaseMapperInst = AppliedTreatmentPhaseMapper()
PatientClientLinkMapperInst = PatientClientLinkMapper()
PatientAlertMapperInst = PatientAlertMapper()
PharmacologicalHistoryMapperInst = PharmacologicalHistoryMapper()
DebtMapperInst = DebtMapper()
RecallMapperInst = RecallMapper()
FALLBACK_MAPPER = RawEntityMapper()

#: Entity type → the modules its rows are written into. With any of them
#: off the whole type is skipped, with one warning, and the preview says
#: so beforehand. A type not listed writes only into the core.
ENTITY_REQUIRES: dict[str, tuple[str, ...]] = {
    "patient": ("patients",),
    "patient_client_link": ("patients",),
    "patient_alert": ("patients", "patients_clinical"),
    "pharmacological_history": ("patients", "patients_clinical"),
    "patient_document": ("patients", "media"),
    "appointment": ("patients", "agenda"),
    "catalog_item": ("agenda",),
    "treatment_catalog_item": ("catalog",),
    "treatment_catalog_variant": ("catalog",),
    "budget": ("patients", "budget"),
    "budget_line": ("budget", "catalog"),
    "applied_treatment": ("patients", "odontogram", "treatment_plan"),
    "applied_treatment_phase": ("treatment_plan",),
    "debt": ("patients", "payments"),
    "payment": ("patients", "payments"),
    "fiscal_document": ("patients", "billing"),
    "fiscal_document_line": ("billing",),
    "recall": ("patients", "recalls"),
    **{entry: ("patients", "patients_clinical") for entry in MEDICAL_ENTRIES},
    "medical_context": ("patients", "patients_clinical"),
    "tooth_record": ("patients", "odontogram"),
    "clinical_treatment": ("patients", "odontogram"),
    "treatment_budget": ("patients", "budget", "catalog"),
    "patient_payment": ("patients", "payments"),
    "earned_entry": ("patients", "payments"),
    "treatment_plan": ("patients", "treatment_plan", "odontogram"),
    "patient_invoice": ("patients", "billing"),
    "clinical_note": ("patients", "clinical_notes"),
    "consent_template": ("consents",),
    "patient_consent": ("patients", "consents"),
    "stored_document": ("patients", "media"),
    "health_questionnaire": ("patients", "patients_clinical"),
    "prescription_record": ("patients", "treatment_plan"),
    "payment_schedule": ("patients", "payments"),
    "collection_contact": ("patients", "payments"),
    "document_attachment": ("patients", "media"),
    "budget_change": ("budget",),
    "invoice_change": ("billing",),
    "plan_change": ("treatment_plan",),
}

#: Entity type → modules that only add to its rows. With one off the rows
#: are imported without that part (a note, a link to a budget).
ENTITY_ENRICHES: dict[str, tuple[str, ...]] = {
    "appointment": ("clinical_notes",),
    "applied_treatment": ("clinical_notes", "budget"),
    "patient_alert": ("clinical_notes",),
}


def missing_for(entity_type: str) -> list[str]:
    """The modules ``entity_type`` needs that are not running."""
    return [m for m in ENTITY_REQUIRES.get(entity_type, ()) if not running(m)]


def partial_for(entity_type: str) -> list[str]:
    """The modules that would add to ``entity_type`` and are not running."""
    return [m for m in ENTITY_ENRICHES.get(entity_type, ()) if not running(m)]


MAPPERS: dict[str, object] = {
    "patient": PatientMapperInst,
    "professional": ProfessionalMapperInst,
    "user": UserMapperInst,
    "patient_document": DocumentMapperInst,
    "payment": PaymentMapperInst,
    "fiscal_document": FiscalDocumentMapperInst,
    "fiscal_document_line": FiscalDocumentLineMapperInst,
    "appointment": AppointmentMapperInst,
    "treatment_catalog_item": TreatmentCatalogItemMapperInst,
    "treatment_catalog_variant": CatalogVariantMapperInst,
    "catalog_item": CatalogItemMapperInst,
    "budget": BudgetMapperInst,
    "budget_line": BudgetLineMapperInst,
    "applied_treatment": AppliedTreatmentMapperInst,
    "applied_treatment_phase": AppliedTreatmentPhaseMapperInst,
    "patient_client_link": PatientClientLinkMapperInst,
    "patient_alert": PatientAlertMapperInst,
    "pharmacological_history": PharmacologicalHistoryMapperInst,
    "debt": DebtMapperInst,
    "recall": RecallMapperInst,
    # Diente Azul's own records, read back field by field (``native.py``).
    **MEDICAL_ENTRIES,
    "medical_context": MedicalContextMapper(),
    "tooth_record": ToothRecordMapper(),
    "clinical_treatment": ClinicalTreatmentMapper(),
    "treatment_budget": TreatmentBudgetMapper(),
    "patient_payment": PatientPaymentMapper(),
    "earned_entry": EarnedEntryMapper(),
    "treatment_plan": TreatmentPlanMapper(),
    "patient_invoice": PatientInvoiceMapper(),
    "clinical_note": ClinicalNoteMapper(),
    "consent_template": ConsentTemplateMapper(),
    "patient_consent": PatientConsentMapper(),
    "stored_document": StoredDocumentMapper(),
    "health_questionnaire": HealthQuestionnaireMapper(),
    "prescription_record": PrescriptionMapper(),
    "payment_schedule": PaymentScheduleMapper(),
    "collection_contact": CollectionContactMapper(),
    "document_attachment": DocumentAttachmentMapper(),
    **HISTORIES,
}

__all__ = [
    "ENTITY_ENRICHES",
    "ENTITY_REQUIRES",
    "FALLBACK_MAPPER",
    "MAPPERS",
    "MapperContext",
    "MappingResolver",
    "ProfessionalFilterOptions",
    "missing_for",
    "partial_for",
    "running",
]
