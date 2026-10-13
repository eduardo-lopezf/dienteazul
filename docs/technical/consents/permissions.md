---
module: consents
last_verified_commit: 0d60d45
---

# Consents — permissions

Returned by `ConsentsModule.get_permissions()`
(relative names; the registry namespaces them as `consents.<name>`).

| Permission | Allows | Required by |
|------------|--------|-------------|
| `consents.read` | See a patient's consent letters and the clinic's templates. | `GET /patients/{patient_id}`, `GET /{consent_id}`, `GET /{consent_id}/pdf`, `GET /templates`, `GET /settings` |
| `consents.write` | Write and edit a draft, capture the signature, record that the patient declined, revoke a signed consent, discard a draft. | `POST /patients/{patient_id}`, `PUT /{consent_id}`, `POST /{consent_id}/sign`, `/decline`, `/revoke`, `/discard` |
| `media.documents.write` (Media's) | File the scan of a letter signed on paper. Without it the sign screen offers the on-screen signature only. | `POST /api/v1/media/patients/{patient_id}/documents` |
| `consents.templates.write` | Create, reword and retire the clinic's consent texts. Granted to admin and dentist: the wording is a clinical and legal responsibility. | `POST /templates`, `PUT /templates/{template_id}`, `PUT /settings` (whether a plan waits for a signed informed consent) |

## Role assignment

From `manifest.role_permissions`: admin all; dentist `read`, `write`,
`templates.write`; hygienist, assistant and receptionist `read`, `write`.

## Adding a new permission

1. Add the relative name to `get_permissions()` in
   `backend/app/modules/consents/__init__.py` (or `module.py`).
2. Add the namespaced form to the relevant role(s) in
   `backend/app/core/auth/permissions.py`.
3. Add a row to the table above.
4. Annotate the endpoint(s) with `Depends(require_permission(...))`.
5. Update `frontend/app/config/permissions.ts` if it gates UI.
