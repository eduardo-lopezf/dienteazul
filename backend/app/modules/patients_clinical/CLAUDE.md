# Patients clinical module

Normalized medical history, allergies, medications, emergency contacts.
Separate from `patients` because the data is sensitive and should be
gated by clinical roles.

## Public API

Routes mounted at `/api/v1/patients-clinical/`.

### Health questionnaire

`GET/POST /patients/{id}/questionnaires`, `POST …/{qid}/retract`,
`GET /patients/{id}/questionnaire-form` (blank PDF). A questionnaire is a
**dated declaration** — what the patient said that day — not the curated
history: allergies, medications and diseases keep living in their own
tables. It is never edited; a mistaken one is retracted. On paper, the
scan (`scan_document_id`, checked through `PatientDocuments`) is the
questionnaire and `answers` may be empty.

Answered on screen it may carry the **patient's signature**
(`signature` on create: PNG data URL, `signed_by_name`,
`signer_capacity`), stored with `signed_at` and the `regulation` the form
named that day (`app.core.regulation`) — a copy, so a later change of the
clinic's line does not move what was signed under. Refused together
with a scan. `signature_data` is `pii()`-classified so erasure
drops the drawing, and it is left out of the record section on purpose.
**One of the two is required**: the signature on screen, or the scan of
the signed sheet — `create_questionnaire` refuses a questionnaire with
neither. Rows from before the rule stay unsigned.

The form is fixed in `questionnaire.py` (`FORM_VERSION`): a changed
question is a new key, never a reworded one, or old answers change
meaning. The frontend mirrors the keys in `useHealthQuestionnaires.ts`
and holds the wording (`healthQuestionnaire.*`); after touching either,
run `python backend/scripts/generate_record_labels.py` from the host.
The blank PDF prints nothing clinical — a filled-in questionnaire leaves
the clinic only through a record disclosure.

### ASA physical status

`GET/POST /patients/{id}/asa`, `POST …/asa/{aid}/retract`. An assessment
is a **dated, attributed judgement** (`AsaAssessment`): class 1–4 (I–IV; V and VI are not offered), the `E`
modifier, what it rests on. Never edited — a new one supersedes it, a
mistaken one is retracted, and the newest not retracted is the current
class. `GET` answers `{current, history}`. Writing needs
`patients_clinical.asa.write`, its own permission on purpose. A class of
III or more is one of `compute_alerts`' alerts (`type: "asa"`).
`GET …/asa/class` (`asa.read`, every role) answers the class alone, for
the booking dialog: keep the date, the reason, the assessor and the
history out of it.

It lives here, in the Patients App, so the class is on the patient's
summary with the Clinical record off; the record reads it as the section
`asa_assessments`.

## Dependencies

`manifest.depends = ["patients"]`, `manifest.integrates = ["professionals"]`.

`professionals` is never imported: the professional behind an entry comes
from `contracts.provider(ProfessionalDirectory).for_account(...)`
(ADR 0039). With that App off the entry is written with the account and no
professional. The foreign key stays, ordered by `depends_on` in `pc_0003`.

## Permissions

`patients_clinical.medical.{read,write}`, `patients_clinical.asa.{read,write}`,
`patients_clinical.emergency.{read,write}`.

## Events emitted

- `patient.medical_updated` — consumed by `patient_timeline`.

## Events consumed

None.

## Lifecycle

- `removable=False`. Clinical decisions reference this data.

## Gotchas

- **The four history tables are append-only** ([ADR 0032](../../../../docs/adr/0032-clinical-record-is-append-only.md)).
  Allergies, medications, systemic diseases and surgical history are corrected
  by appending: `ended_at` for a fact that stopped being true, `retracted_at`
  (+ `retraction_reason`) for one that should never have been recorded. Do not
  add a `db.delete()` against them, and do not collapse the two columns into a
  `deleted_at` — a retracted allergy must stop driving alerts while a
  discontinued medication stays visible as history. Reads default to live rows;
  `include_history=True` is how the clinical record reaches the rest.

- **`replace_medical_history` reconciles, it does not replace.** The name is
  historical. It matches submitted lines to stored rows by id, inserts what is
  new and retracts what the form dropped. It used to delete every row and
  insert new ones on every save, which silently reset when each entry was first
  recorded. The bulk payload's `*Submit` schemas carry the `id` for exactly
  this; the per-row `*Create` schemas deliberately do not.

- **Emergency contacts and legal guardians still hard-delete.** They are 1:1
  rows keyed by `patient_id`, so append-only means re-keying the tables — left
  for the rest of phase 0 (`docs/features/expediente-clinico.md` §8).

- **Clinical authorship is not recorded yet**, and the two blockers are written
  down in `models.py` (`ClinicalEntryMixin`) and in `pc_0002`: there is no link
  from an account to a directory professional, and a foreign key from this
  module's chain to the `professionals` branch breaks a fresh install.

- **Hygienists do NOT have write access** to medical history.
  Receptionists read only emergency contacts (in some clinic
  configurations not even that — check role policy).
- **Allergies and medications drive UI alerts.** Schema changes here
  affect the patient header banner — coordinate frontend.
- **Audit every write.** This is the most sensitive surface in the
  product after billing.

## Related ADRs

- `docs/adr/0001-modular-plugin-architecture.md`
- `docs/adr/0005-relative-permissions.md`
- `docs/adr/0032-clinical-record-is-append-only.md`

## CHANGELOG

See `./CHANGELOG.md`.
