# Record module

The clinical record (*expediente clínico*) as a **composition**: a header and
ordered sections of dated, attributed entries, assembled from the modules that
own the data.

Spec: [`docs/features/expediente-clinico.md`](../../../../docs/features/expediente-clinico.md).
Decisions behind it: [ADR 0032](../../../../docs/adr/0032-clinical-record-is-append-only.md)
(the record is append-only) and [ADR 0033](../../../../docs/adr/0033-disclosure-requires-a-recorded-authorisation.md)
(disclosure requires a recorded authorisation).

## Public API

Routes mounted at `/api/v1/record/`.

- `GET /patients/{patient_id}` — the composition; `record.read`.
  `?include_retracted=true` adds the entries that were taken back.
- `POST /patients/{patient_id}/disclosures` — hand the record over: produces
  the PDF, stores it, records to whom and why; `record.disclose`.
- `GET /patients/{patient_id}/disclosures` — every disclosure; `record.read`.
- `GET /format` (`record.read`), `PUT /format` (`record.configure`) — the
  clinic's record format: hidden sections, their order, skipped
  requirements. Stored in `clinic.settings["record_format"]`.
- `GET /disclosures/{id}/document` — the PDF exactly as it left;
  `record.disclose`.

## Frontend

One page of its own: `/settings/apps/clinical-record`, the Clinical record
App's settings — the clinic's record format. Listed in
`frontend/app/config/appRoutes.ts` and linked from the App's card through
`frontend/app/config/appCatalog.ts`.

Registers the *Expediente* tab in `patient.detail.tabs`
(`components/record/PatientRecordTab.vue`), gated by `record.read`. It
renders whatever sections come back, generically: labels from
`record.field.<column>`, coded values from `record.value.<column>.<code>`
or from the owning screen's own translations (`recordFormat.ts`). A new
section needs a `record.section.<name>` title and labels for its `detail`
keys — no component.

## Dependencies

`manifest.depends = ["patients", "professionals"]` — deliberately short.

Contributing modules are reached through `get_record_sections()`, a **core**
contract, so this module never imports them. `patients_clinical`,
`clinical_notes`, `odontogram`, `periodontogram`, `treatment_plan`, `media` and
`agenda` are therefore **not** dependencies: when one is uninstalled the record
simply has fewer sections. What is declared is what the header reads directly —
who the record is about, and which professional answers for it.

Expect `media` to join when phase 2 produces artifacts, and possibly
`notifications` for the patient notice that a disclosure happened.

## Permissions

`record.read`, `record.disclose` and `record.configure` (the format; admin
only — no role is granted it). `disclose` is granted to admin and
dentist — not hygienist, assistant or reception: handing a record over is a
clinical-governance act. That default is this module's, and a clinic may
want it otherwise. `authorise` arrives with the endpoints that use it.

## Data ownership

**No clinical data, on purpose.** One table, `record_disclosure`: the act
of handing the record over — recipient, purpose, evidence, scope, a
manifest of the entries included, and the document as it left with its
SHA-256. Not other modules' data, so it belongs here.

## Tools exposed

None yet. An agent-addressable "read this patient's whole clinical record" is a
disclosure in everything but name, and it waits for the authorisation phase to
say who may ask for one.

## Events

None emitted or consumed yet. Phase 2's disclosure will publish one.

## Lifecycle

`installable=True`, `auto_install=False`, `removable=False`: it holds
evidence now, so it is disabled, never uninstalled (ADR 0035).

## Gotchas

- **Never add a clinical table here.** The spec exists to prevent exactly that:
  *"The record is not a new place to keep clinical data; it is a view of data
  seven modules already own, and the moment it becomes a copy it starts
  drifting from the source and there are two truths about a patient's
  allergies."* A section that needs data nobody owns means the owning module is
  missing a column, not that the record needs a table.

- **Phase 0's guarantees do not live here and must not move here.** Append-only
  history (`patients_clinical`), note versions (`clinical_notes`) and the
  account↔professional link (`professionals`) are corrections inside the
  modules that own that data. Uninstalling this module must not make a clinical
  table deletable again.

- **Sections come back empty rather than missing.** "This module holds nothing
  about this patient" is an answer; an absent section leaves the reader unable
  to tell it was asked.

- **A failing section does not deny the rest of the record.** `compose()` logs
  the exception and returns that section empty. A clinician mid-consultation
  loses one section, not the chart.

- **Retracted entries are excluded by default, never dropped.** They stay
  reachable with `include_retracted=true`, because "what did the chart say on
  the day of the procedure" has to stay answerable (ADR 0032) — but they are
  not part of what a colleague is handed.

- **The format is applied in `compose()`, once, for everyone.** A hidden
  section is absent from the tab, from the PDF and from what a disclosure
  may name; the order is the clinic's. Coverage is computed *before*
  hiding — a consent on file counts whether or not its section shows —
  and then loses the requirements the clinic skips. An empty format is the
  default; a section the order does not mention keeps its default place,
  so a newly enabled module's section still appears.

- **Letterheads are not this module's**, and neither are their screens:
  they are edited in the Workspace (`/settings/general/letterheads`,
  `/settings/account/my-letterhead`, host components). They are the clinic's (`app.core.letterhead`, ADR 0046): the clinic's own
  and one per professional. `pdf.py` asks `render_letterhead` for the head
  of whoever hands the record over (`disclosed_by_professional_id`) and
  never builds or picks one. Do not add a "choose letterhead" option to a
  disclosure: a record must not leave under another doctor's head. The
  page guards those cards with `admin.clinic.*`, not `record.configure`;
  *Mi membrete* needs no permission beyond being that professional — the
  server decides (`_may_touch_letterhead` in the core auth router).

- **`coverage` checks presence, by section name.** `coverage.py` holds the
  list of what a dental record is expected to hold (this product's reading
  of NOM-004, pending legal review) and matches sections by their
  qualified name — still no import of a contributing module. A module
  that renames a section or a `detail` key it relies on (`diagnosis_notes`,
  `prognosis`, `note_type`, `kind`, `status`) breaks a requirement
  silently; `TestCoverage` is what notices. Retracted entries never
  satisfy a requirement.

- **Reading is not handing over, and there is one way to hand over.** The
  tab shows the record to someone already entitled to the chart. A
  printable record exists only through `DisclosureService.disclose`
  (ADR 0033): it refuses without the evidence the purpose asks for,
  renders exactly the sections in scope, never a retracted entry, and
  stores the document with its digest. `render_record_pdf` has that one
  caller, pinned by `tests/test_record_disclosure.py`. Do not add a print
  button, an export or an agent tool on the side.

- **A disclosure is never edited or deleted**, and is itself an entry of
  the record (section `record.disclosures`, last in reading order).
  Re-opening one serves the stored bytes; nothing is regenerated.

- **`labels.json` is a copy of the screen's wording.** The PDF is rendered
  by the backend, which cannot read the frontend locales at run time.
  After touching the `record` block of `frontend/i18n/locales/*.json`, or
  a translation a coded value borrows, run
  `python backend/scripts/generate_record_labels.py` from the host.

- **Not built from ADR 0033:** structured, time-boxed authorisations and
  their revocation (the evidence is free text today); the legal guardian
  as authoriser; digest chaining between disclosures; a notice to the
  patient; remote delivery. Each disclosure stands alone.

- **`title_key`, never a literal.** A record is read in the clinic's language
  and exported in the patient's. The contract refuses a section without one.

## Related ADRs

- `docs/adr/0018-install-state-is-the-mount-authority.md` — the fan-out asks
  `list_modules()`, the installed set, not what is on disk.
- `docs/adr/0026-subject-rights-are-a-module-contract.md` — the sibling
  contract, and why this is a separate one.
- `docs/adr/0032-clinical-record-is-append-only.md`
- `docs/adr/0033-disclosure-requires-a-recorded-authorisation.md`

## CHANGELOG

See `./CHANGELOG.md`.
