# consents

Consent letters: informed consent to treat, and consent to the use of
personal data. Part of the **Clinical record** App
([`docs/apps/clinical_record/`](../../../../docs/apps/clinical_record/README.md)).

## Public API

Routes mounted at `/api/v1/consents`. See
[`docs/technical/consents/`](../../../../docs/technical/consents/overview.md).

- Templates: `GET/POST /templates`, `PUT /templates/{id}`.
- Consents: `GET/POST /patients/{patient_id}`, `GET/PUT /{id}`,
  `GET /{id}/pdf`, `POST /{id}/sign`, `/decline`, `/revoke`, `/discard`.

## Dependencies

`manifest.depends = ["patients"]`,
`manifest.integrates = ["professionals", "media"]`.

The patient is validated through `PatientDirectory`; the professional who
explained a consent is read through `ProfessionalDirectory` and stored as
a **snapshot** — id, name, licence — with no foreign key (ADR 0039,
ADR 0042). `plan_id` is likewise an id without a foreign key, and so is
the scan of a letter signed on paper (`signature_data.document_id`),
checked through `PatientDocuments`. `professionals` and `media` are not
imported. The one import is `patients.models.Patient`, in `pdf.py`, to
print the patient's data on the sheet.

## Permissions

`consents.read`, `consents.write`, `consents.templates.write`.

## Tools exposed

None. Reading a consent to an agent hands it a signature and free text;
writing one is a clinical act with a person's name on it.

## Events emitted / consumed

None.

## Frontend slots

Registers the *Consentimientos* tab in `patient.detail.tabs` and a settings
page (`consent-templates`, category `clinical`). No pages of its own.

## Rules that are not obvious

- **A consent is a record entry** ([ADR 0045](../../../../docs/adr/0045-a-consent-is-a-record-entry.md),
  ADR 0032). Only a `draft` is edited. `signed`, `declined` and `revoked`
  are never edited or deleted; a revocation is a state and a date on the
  same row. There is no delete endpoint, and there must not be one.
- **The body is a copy.** A consent stores the text the patient saw and
  the template version. Editing a template bumps its version and reaches
  no letter already written.
- **An informed consent cannot be signed without naming who explained
  it** — Art. 51 Bis 1 puts the duty on a person. With the Professionals
  App off, drafts and data-use consents still work; naming a professional
  is refused, so informed consents wait.
- **Two ways to sign, one record.** `signature_method` is `screen` (the
  drawing is in `signature_data.png`) or `paper` (`signature_data.document_id`
  is the scan, a document of the same patient in Media). On paper the
  scan *is* the signature: `sign` refuses `paper` without one. The frontend
  uploads the file to Media's own endpoint first, then signs.
- **The PDF is a form, not the record.** `pdf.py` prints the letter with
  ruled lines for what is written by hand. The lines around the text —
  who informs, who accepts, two witnesses, place and date — follow
  NOM-004 §10.1.1; the text itself stays the clinic's. A letter signed on
  paper still prints as the blank form: the signed sheet is the scan.
- **Media can archive the scan.** Nothing stops a user with
  `media.documents.write` from archiving the document a paper consent
  points at. Known gap.
- **No legal text ships with the module.** Templates are the clinic's.
  Do not seed wording that reads as legal advice.
- **`conformity` is a third kind**: agreement with a concluded treatment.
  Same mechanism, no professional required, satisfies neither consent, and
  says nothing about money — it does not look at the patient's balance.
- **Two consents, not one.** `informed` and `data_use` share a mechanism
  and nothing else; neither substitutes for the other, and a signed budget
  substitutes for neither.
- **Subject rights:** exported, never erased (`privacy.py` states the
  retention reason).

## A plan waits for its consent

`providers.py` offers `PlanConsents.lacks_required_consent` (core contract):
true when the clinic asks for it (`clinic.settings["consents"]
["require_informed_for_plan"]`, **off unless set to true**) and the plan
has no `informed` consent that is `signed` and carries its `plan_id`.
`treatment_plan` asks it on confirm and answers `409`; it never imports
this module. Not asked with Professionals off — an informed consent
cannot be signed without naming who explained it, and a rule nobody can
meet would stop every plan. `GET/PUT /settings` reads and writes the
switch (`consents.read` / `consents.templates.write`).

## Not built yet

Remote signing by expiring link; enforcement of a data-use consent before
messaging a patient; guardians read from `patients_clinical`.

## CHANGELOG

See `./CHANGELOG.md`.
