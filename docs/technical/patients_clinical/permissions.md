---
module: patients_clinical
last_verified_commit: 0000000
---

# Patients Clinical — permissions

> _Scaffolded stub — replace with proper documentation when this module is next touched._

Returned by `PatientsClinicalModule.get_permissions()`
(relative names; the registry namespaces them as `patients_clinical.<name>`).

| Permission | Allows | Required by |
|------------|--------|-------------|
| `patients_clinical.medical.read` | See a patient's health questionnaires and print the blank form. | `GET /patients/{id}/questionnaires`, `GET /patients/{id}/questionnaire-form` |
| `patients_clinical.medical.write` | Record a health questionnaire, or take one back. | `POST /patients/{id}/questionnaires`, `POST /patients/{id}/questionnaires/{qid}/retract` |
| `patients_clinical.medical.read` | See a patient's ASA class and the assessments behind it. | `GET /patients/{id}/asa` |
| `patients_clinical.asa.read` | See a patient's current ASA class — nothing else: no date, no reason, no assessor. Granted to every role, reception included: it is what the booking dialog shows. | `GET /patients/{id}/asa/class` |
| `patients_clinical.asa.write` | Assess a patient's ASA physical status, or take an assessment back. A clinical judgement, so it is not the permission that edits the history. | `POST /patients/{id}/asa`, `POST /patients/{id}/asa/{aid}/retract` |
| `patients_clinical.medical.read` | _Describe what this allows._ | _List the endpoints._ |
| `patients_clinical.medical.write` | _Describe what this allows._ | _List the endpoints._ |
| `patients_clinical.emergency.read` | _Describe what this allows._ | _List the endpoints._ |
| `patients_clinical.emergency.write` | _Describe what this allows._ | _List the endpoints._ |

## Role assignment

See `backend/app/core/auth/permissions.py` for the canonical role table.

## Adding a new permission

1. Add the relative name to `get_permissions()` in
   `backend/app/modules/patients_clinical/__init__.py` (or `module.py`).
2. Add the namespaced form to the relevant role(s) in
   `backend/app/core/auth/permissions.py`.
3. Add a row to the table above.
4. Annotate the endpoint(s) with `Depends(require_permission(...))`.
5. Update `frontend/app/config/permissions.ts` if it gates UI.
