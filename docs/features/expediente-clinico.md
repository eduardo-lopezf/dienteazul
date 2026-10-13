# Expediente clínico electrónico — composition, disclosure and interchange

> Status: draft. Spec last updated: 2026-09-30.
> Decisions behind it: [ADR 0032](../adr/0032-clinical-record-is-append-only.md)
> (the record is append-only) and
> [ADR 0033](../adr/0033-disclosure-requires-a-recorded-authorisation.md)
> (disclosure requires a recorded authorisation).
>
> **Every regulatory statement here is an engineering reading, not legal
> advice, and is marked for local review before it ships.** What is
> settled is the *shape*: what the record is, which module answers for
> which part, and what may never leave without an authorisation.

## Why

A clinic that cannot hand a patient their record, or send a colleague the
relevant part of it, is not running a clinical system — it is running a
database with a nice interface over it. Today Diente Azul is the second
thing. Everything a dental record needs is already stored, and none of it
can leave the building as a record.

The temptation is to add an `expediente` table and copy data into it.
That is the failure this spec exists to prevent. The record is not a new
place to keep clinical data; it is a *view* of data seven modules already
own, and the moment it becomes a copy it starts drifting from the source
and there are two truths about a patient's allergies.

Two things genuinely are new: the **authorisations** that permit a
disclosure, and the **artifacts** produced by one. Everything else is a
projection.

## 1. The record is a composition, not a table

A composition has a header and ordered sections, each holding dated
entries. That is the shape of a paper *expediente*, and — not
coincidentally — of both interchange formats worth targeting later: HL7
CDA R2 and FHIR `Composition`. Building the internal model in that shape
means the export formats are mappings rather than rewrites.

| Part | Content | Source |
|---|---|---|
| Header | Patient, clinic (custodian), responsible professional + licence, date, jurisdiction, purpose | `patients`, `clinics`, `professionals`, `PrivacyPolicy` |
| Sections | Identification, antecedents, odontogram status, periodontal charting, evolution notes, therapeutic plan, imaging, consents | one per contributing module (§2) |
| Entries | A dated, attributed clinical fact | the owning module's rows |

`patient_timeline` is already the chronological spine — it carries
`source_table`, `source_id`, `occurred_at` and an `event_data` JSONB
across 35 event types. The record does not replace it; it groups the same
material **clinically** (by section and episode) where the timeline
groups it **chronologically** (by event). Both views ship.

**Non-goal:** a `record` module that owns clinical rows. It owns the
composition logic, the disclosures and the produced artifacts — nothing
that another module is already the authority on.

## 2. The contract: `get_record_sections()`

Modules already answer for their own data through
`get_subject_contributors()` ([ADR 0026](../adr/0026-subject-rights-are-a-module-contract.md)),
and 16 of them implement it. The clinical record uses the same *pattern*
and a **separate contract**, because it answers a different question:

| | `SubjectContributor` (exists) | `RecordSection` (new) |
|---|---|---|
| Question | "What do you hold about this person?" | "What of yours belongs in a clinical record?" |
| Audience | The data subject, a regulator | Another clinician |
| Includes billing | Yes — it is their data | **No** — a referral is not a financial document |
| Ordering | By module | Clinically, by section and episode |
| Needs coding | No | Yes, for interchange (§7) |
| Erasure semantics | Central to it | Not applicable — see ADR 0032 |

A module may implement both, one, or neither. `billing`, `payments`,
`verifactu` and `accounting_export` implement only the subject
contract — a clinical disclosure that carries invoice data is a privacy
defect, not a feature.

Sketch — the sharp edges, not the full signature:

```python
RecordSection(
    name="allergies",                    # unprefixed; registry adds the module
    title_key="record.section.allergies",  # i18n, never a literal
    category=SectionCategory.ANTECEDENTS,
    collect=_collect_allergies,          # (db, clinic_id, patient_id, scope) -> [RecordEntry]
)
```

Each `RecordEntry` carries, at minimum:

- `occurred_at` — **clinical time, not row-creation time.** A surgery
  recorded today that happened in 2019 sorts into 2019.
- `authored_by` — the professional and licence per
  [ADR 0032](../adr/0032-clinical-record-is-append-only.md), distinct
  from the account that typed it.
- `status` — active, ended, or retracted. Retracted entries are excluded
  from disclosures by default and never silently dropped from the record.
- `codes` — empty until §7; the field exists from the start so adding
  coding is not a migration of every section.

Contributing modules: `patients`, `patients_clinical`, `clinical_notes`,
`odontogram`, `periodontogram`, `treatment_plan`, `media`, `agenda`.
Whether `recalls` contributes a "recommended follow-up" section is **TBD**
— clinically meaningful, arguably commercial.

### ASA physical status is an assessment, not a profile field

*Built 2026-10-12 in `patients_clinical` — see the
[commitments register](../technical/commitments-register.md) for the two
open questions below and how they were settled.*

The ASA Physical Status Classification (I–VI, with the `E` modifier for
emergencies) is what tells the operator whether this patient can be
treated in the chair as usual (I–II), needs precautions and a shorter
appointment (III), or should not be treated electively outside a hospital
setting (IV+). In a dental practice it is the single most load-bearing
summary on the pre-anaesthetic surface, and Diente Azul does not have it:
no column, no enum, no reference anywhere in the codebase.

The inputs are already there. `patients_clinical_medical_context` holds
pregnancy and week, anticoagulant use with INR value and date, smoking,
alcohol, and prior adverse reactions to anaesthesia — the factors a
clinician weighs to arrive at a class. What is missing is the conclusion.

**It must not be modelled as a mutable field on the patient profile.** An
ASA class is a clinician's judgement about a patient *at a point in
time*; a patient who was ASA II before a cardiac event is not
retroactively ASA III. Under
[ADR 0032](../adr/0032-clinical-record-is-append-only.md) that makes it a
dated, attributed entry like any other clinical fact: superseded by a new
assessment, never overwritten. The record section shows the current class
with its date and assessor, and the history behind it.

Two consequences worth settling before it is built:

- **Who may assess.** ASA is a clinical judgement, so the write
  permission is not the one that edits demographics. **TBD**, same
  governance question as `record.disclose` (§3).
- **Whether it drives an alert.** A class of III or higher shown quietly
  in a section nobody opens is worse than not having it. The intended
  shape is that it surfaces on the same alert surface as allergies.

### Confirming a plan contributes an episode

The request that started this spec was "create the record from a
treatment plan". The relationship is the other way round: the plan is one
section of a lifelong, patient-scoped record, and a patient with no plan
still has allergies and radiographs.

What does hold is the pattern already established when budget creation
moved behind plan confirmation: **confirming a treatment plan appends an
episode** — a structured entry with diagnosis, therapeutic plan and
responsible professional — to the record. The plan contributes to the
record; it does not create it.

## 3. Where it appears

A top-level *Expediente* entry sitting next to *Pacientes* forces a
choice every time — they are the same thing seen twice. The split that
avoids it:

- **The record itself lives inside the patient**, as a view on the detail
  page ([ADR 0011](../adr/0011-detail-page-shared-components.md)),
  alongside the existing timeline. Default axis: what happened and when.
  Density uses the existing `compact` mode — a record is dense by nature
  and the design system's calm is achieved by subtraction, not by
  spacing a chart until it needs scrolling.
- **The new menu entry is for record *operations***, which are global and
  fit nowhere on one patient's page:

  | Screen | Purpose |
  |---|---|
  | Disclosures | Outgoing and incoming, with status and scope |
  | Authorisations | Pending signature, active, revoked, expiring |
  | Imports | External records being reconciled (§6) |
  | Access log | Who read or exported which record, when |

Permissions follow [ADR 0005](../adr/0005-relative-permissions.md), so
the module returns them unprefixed: `record.read`, `record.export`,
`record.disclose`, `record.authorise`. Who gets `disclose` is **TBD** and
is a clinical-governance question, not a technical one — the defensible
default is that it is not a reception-desk permission.

Every screen added here owes a user-manual page in **both** locales per
the root `CLAUDE.md` checklist.

## 4. Formats: three layers, one composition

Reaching for FHIR first is the common mistake. Nothing in a dental
referral circuit consumes it today, and Mexico's NOM-024-SSA3-2012 asks
for CDA R2 with CIE-10, not FHIR.

| Layer | Format | Role | Phase |
|---|---|---|---|
| Legal / human | **PDF/A-3**, signed | What the patient receives, what gets printed, what survives an archive. A-3 because it *embeds* the structured payload — one file, both audiences | 1 |
| Portable / own | **DPMF** (`.dpm`), extended | Diente Azul↔Diente Azul transfer and backup. The format and its reader already exist in `migration_import` | 1 |
| Interoperable | **FHIR R4 Bundle** (`type=document`); **CDA R2** | Only when a real counterparty needs it, or NOM-024 certification is pursued | 3 |

**The rule that makes this affordable: all three are projections of one
composition, never three independent serialisers.** A section added once
appears in every format.

**Imaging is referenced, not embedded.** Dentistry means periapicals,
panoramics and CBCT; `docs/technical/todos.md` already scopes a DICOM
phase. A disclosure carries a pointer plus a web-viewable rendering, and
the DICOM original travels on request. Embedding studies in a document
produces files nobody can email.

## 5. The authorisation protocol

Governed by [ADR 0033](../adr/0033-disclosure-requires-a-recorded-authorisation.md):
nothing leaves without a `Disclosure` naming recipient, purpose, scope
and basis. This section is the flow that produces one.

### Two consents, not one

Both are called *consentimiento* in the clinic and they authorise
different acts. Conflating them is the mistake this subsection exists to
prevent.

| | **Consent to disclose** | **Informed consent to treat** |
|---|---|---|
| Authorises | Sending the record to someone | Performing a procedure on the patient |
| Governed by | [ADR 0033](../adr/0033-disclosure-requires-a-recorded-authorisation.md), data-protection law | Ley General de Salud **Art. 51 Bis 1** (MX); NOM-004 §*cartas de consentimiento informado* |
| Asks | "may we share this?" | "do you understand the risks and alternatives, and do you accept?" |
| Attaches to | A disclosure | A procedure, a plan, an episode |
| State today | Designed, phase 2 | **Not built** |

Art. 51 Bis 1 gives the patient a right to *sufficient, clear, timely and
truthful* information about their condition and about the risks and
alternatives of the procedures indicated for them. That is an obligation
on the clinical act, not on the data transfer, and nothing in Diente Azul
discharges it today.

The nearest thing that exists is `budget_signatures` — and it is not it.
A signed budget records that the patient accepted a **price**. Reusing it
as evidence of clinical consent would produce exactly the document a
clinic cannot defend: a commercial acceptance presented as proof the
risks were explained.

What it does give is the mechanism. The capture paths are the same ones
flow B uses below — tablet signature in the chair, or an expiring link
with second-factor verification — so informed consent is a new artifact
over proven plumbing, not new plumbing. Its content per procedure
(risks, alternatives, the professional who explained them) is **TBD** and
is the part that needs clinical and legal authorship rather than
engineering. Once captured it is filed in the record, which is where
NOM-004 expects the consent letter to live, and it becomes a record
section like any other.

### The four flows

**A — Referral for continuity of care** (the common case, and the one
that must stay fast). The dentist picks the recipient, the sections and a
clinical justification; the disclosure is recorded and sent. No patient
signature, because the basis is provision of care — but the patient is
notified that it happened, through the existing notifications gateway.
If this flow is slower than attaching a PDF to a personal email, the
feature has failed.

**B — Share at the patient's request** (second opinion, third party,
insurer). Requires express authorisation. Two capture paths, both already
built here:

- *In clinic*: signed on a tablet, reusing the signature capture behind
  budget acceptance (`budget_signatures`) and the touch rules of
  [ADR 0022](../adr/0022-touch-adaptation-is-capability-driven.md).
- *Remote*: an expiring link with second-factor verification, exactly the
  mechanism of [ADR 0006](../adr/0006-budget-public-link-2-factor-auth.md).
  Same infrastructure, different payload.

**C — Incoming request** from a hospital, colleague or insurer. The
clinic never answers directly. The request is logged, the patient is
asked to authorise (path B), and only then does a disclosure exist. An
unauthorised request expires visibly rather than sitting in someone's
inbox.

**D — The patient's own copy.** A subject access request, already
[ADR 0026](../adr/0026-subject-rights-are-a-module-contract.md) territory
— no third-party authorisation, but identity verification, and the
clinical projection rather than the raw subject export.

### What the patient signs

Scope in clinical language, not table names: *"Historia clínica y
antecedentes, radiografías del 2024 en adelante, plan de tratamiento
actual"*. Plus recipient, purpose, expiry, and the revocation right —
stated with its real limit, that revoking stops future sending and
cannot recall what was already sent. The signed artifact is filed **in
the record**, which is where NOM-004 expects the consent letter to live.

For minors and patients under guardianship the authoriser comes from
`patients_clinical_legal_guardian`, and the disclosure records the
capacity they acted in.

### Revocation

A new entry, never a deletion. It closes the authorisation for future
use; prior disclosures keep their manifest and digest, because "what did
they receive" must stay answerable after consent ends.

## 6. Import and export

**Export** runs the composition through a format projection (§4) under a
disclosure (§5). The produced artifact is retained with its digest —
a disclosure that cannot reproduce what it sent is not evidence.

**Import** reuses the workflow `migration_import` already proved: upload,
validate, **propose**, let an operator decide row by row, then execute,
with each `MappingDecision` persisted. An external record raises the same
problem a migration does — reconciling someone else's codes, teeth
notation and identities against yours — and the answer is the same:
never auto-merge clinical data, always let a human adjudicate.

Two dental-specific traps for the importer: **tooth notation** (Diente Azul
uses FDI/ISO 3950; a US-origin record will be Universal) and units in
periodontal charting. Both must be declared on import, not inferred.

## 7. Clinical coding — the gate for interchange

There is no coding anywhere in the codebase today: no CIE-10, no SNOMED,
no SNODENT, no procedure codes. Without them a disclosure can only carry
prose, and prose is not interchange.

Minimum viable is far smaller than the full catalogues:

- **Diagnoses**: CIE-10 chapter **K00–K14** (oral cavity, salivary glands
  and jaws) — tens of codes, not thousands. NOM-024 asks for CIE-10.
- **Procedures**: map the existing treatment catalogue to one procedure
  code set. Which one is **TBD** and jurisdiction-dependent.

The catalogue already has a category/specialty structure to hang codes
on, so this is an additive mapping rather than a re-modelling. It gates
phase 3 entirely and nothing before it.

## 8. Phases

| Phase | Contents | Gate |
|---|---|---|
| **0 — Immutability** | [ADR 0032](../adr/0032-clinical-record-is-append-only.md): stop hard-deleting in `patients_clinical`, amendments append in `clinical_notes`, attribution carries the licence. **Partly done — see below** | Nothing else is worth building on mutable clinical data |
| **1 — Composition** | `record` module, `get_record_sections()`, patient-level view, new menu entry, PDF/A-3 + DPMF export with digest chaining. **Started — see below** | Phase 0 |
| **2 — Authorisation** | [ADR 0033](../adr/0033-disclosure-requires-a-recorded-authorisation.md): disclosures, the four flows, signature capture, access log | Phase 1 |
| **3 — Coding** | CIE-10 K00–K14, procedure mapping | Phase 1 |
| **4 — Interchange** | FHIR R4 Bundle, CDA R2 if certification is pursued, DICOM transport | Phases 2 and 3 |

Phase 0 is three bounded corrections to existing modules and carries the
one migration risk worth naming: it rewrites populated clinical tables,
which is the class of change that has already broken a deploy here. It
gets tested against a database with rows.

### Phase 0, where it actually stands

Two of the three corrections have landed, one at a time, each verified against
a database with rows before the next started. Nothing downstream starts until
the phase closes — this is a partial phase, not a partial gate.

| Correction | State |
|---|---|
| `patients_clinical` stops hard-deleting | **Done** (2026-09-25). `pc_0002`: the four history tables carry `ended_at`, `retracted_at` + `retraction_reason` and `recorded_by_user_id`; the six per-row deletions became retractions; the bulk form reconciles by id instead of deleting every row on every save |
| Amendments append in `clinical_notes` | **Done** (2026-09-26). `cn_0005`: the superseded body lands in `clinical_note_versions` with its number, when it stopped being current, who replaced it and why; the note keeps the current text, plus `version` and `amended_at`. `GET /notes/{id}/versions` reads the history. A save that changes nothing writes no version |
| Emergency contacts and legal guardians | **Pending.** They are 1:1 rows keyed by `patient_id`, so append-only means re-keying the tables — a larger change than the history entries, and not the patient-safety case |
| Attribution carries the licence | **Done** (2026-09-28). `pro_0003` gives a directory professional a `user_id`; `pc_0003` and `cn_0006` add the clinical author to the history entries, the notes and their versions, resolved from the acting account's profile |
| The contract test that keeps the rule true | **Pending.** ADR 0032 names its shape: a module declaring clinical sections may not call `db.delete()` against its own clinical tables |

Both migrations are covered by `backend/tests/test_clinical_record_migrations_with_rows.py`,
which upgrades, downgrades and upgrades again over seeded clinical rows. It is
the test that caught the branch-ordering failure below, and it is where the
third correction's migrations go too.

**Attribution, and the two things that had to be solved first.** Both were
found while building the first correction, and both are now closed:

1. *Nothing linked an account to a directory professional.* `professionals` is
   deliberately independent of `users` — a colleague can be in the directory
   with no account — and the only bridge was a lowercased email comparison
   used to display "has system access here". Deriving clinical authorship from
   that would be a guess written into a document whose purpose is to be
   evidence. **Resolved** by `professionals.user_id` (`pro_0003`): an admin
   states the link, in a field on the professional's form. It is not
   backfilled from email, for the same reason it is not inferred at write
   time.
2. *A foreign key to `professionals` broke a fresh install.* `patients_clinical`
   rides the core linear chain, which boot applies first, while `professionals`
   is a removable module on its own branch applied afterwards — so the
   constraint referred to a table that did not exist yet and `alembic upgrade`
   died on an empty database. The empty-schema round-trip did not catch it,
   because it upgrades to `heads` — every branch, in an order that happened to
   work. **Resolved** with `depends_on = ("professionals",)`, which the project
   already used in `liq_0001` to reach the same table from another branch. Note
   the label names `pro_0001` — the revision that creates the table — not the
   branch head.

What the entries now carry: `recorded_by_user_id` / `authored_by_professional_id`
on the clinical rows, resolved from the acting account's profile. **An account
with no profile leaves the professional empty**, which is the honest answer:
the case ADR 0032 describes — an assistant typing what a dentist is
responsible for — needs the responsible professional to be *asked for*, and
nothing asks yet. That is the remaining gap, and it is a screen, not a
blocker: the column, the link and the resolution are in place, so phase 1's
header can name a professional and a licence wherever one was recorded.

## 9. Regulatory coverage — NOM-004-SSA3-2012 (MX)

*An engineering reading of the norm's content requirements against what
the codebase holds, pending the legal review this document is conditioned
on. It exists to answer "how much of NOM-004 do we already meet?" with
something better than a feeling.*

| NOM-004 element | Where it lives | State |
|---|---|---|
| Ficha de identificación | `patients` | **Done** |
| Antecedentes personales patológicos | `patients_clinical` — allergy, medication, systemic disease, surgical history | **Done** |
| Antecedentes personales no patológicos | `patients_clinical.medical_context` — smoking, alcohol | **Partial** — habits only |
| Antecedentes heredo-familiares | — | **Missing.** No table; the seven `patients_clinical` tables cover the patient, not the family |
| Padecimiento actual | `clinical_notes` (`diagnosis`) | **Partial** — free prose, no structure |
| Interrogatorio por aparatos y sistemas | — | **Missing** |
| Exploración física | `odontogram`, `periodontogram` | **Partial** — oral exam yes, general physical no |
| Resultados de estudios de laboratorio y gabinete | `media` | **Partial** — imaging is stored; lab results have nowhere to go |
| Diagnósticos o problemas clínicos | `clinical_notes`, `odontogram` | **Partial** — recorded, uncoded until §7 |
| Pronóstico | — | **Missing** |
| Indicación terapéutica | `treatment_plan` | **Done** |
| Notas de evolución | `clinical_notes` | **Done** |
| Notas de interconsulta / referencia | flow A, §5 | **Designed**, phase 2 |
| Cartas de consentimiento informado | — | **Missing** — see *Two consents, not one* (§5) |
| Nombre y firma de quien la elabora | `authored_by_professional_id` + licence | **Done** in phase 0 |
| No borrado; correcciones anotadas | [ADR 0032](../adr/0032-clinical-record-is-append-only.md) | **Mostly done** — two 1:1 tables pending (§8) |
| Conservación mínima 5 años | `retention_reason` ([ADR 0026](../adr/0026-subject-rights-are-a-module-contract.md)) | **Designed**; the floor per jurisdiction is an open question |

**The honest summary:** the *custody* requirements — attribution,
immutability, retention — are largely met, because phase 0 went at them
directly. The *content* requirements are met for everything a dental
practice records natively and missing for everything a general medical
history carries: family history, systems review, prognosis, lab results,
and informed consent.

That gap is not an oversight to be closed by adding fifteen columns. Four
of those five are general-medicine surfaces in a dental product, and a
clinic that needs a full *historia clínica general* is describing a
different product. What is worth deciding, and is **TBD**, is whether
Diente Azul claims NOM-004 compliance for the dental record specifically —
a defensible position — or pursues the general expediente, which is a
scope decision, not a backlog item. Informed consent is the exception:
it is squarely dental, squarely required, and squarely missing.

### Phase 1, where it actually stands

The module exists and is installable from *Configuración → Módulos*
(`auto_install=False`, `removable=True`), and the contract it rests on is
settled in [ADR 0034](../adr/0034-the-record-is-composed-not-stored.md).

| Piece | State |
|---|---|
| `record` module, registered and installable | **Done.** No models, no migrations — it owns no clinical data, which is the design (§1), not an omission |
| `get_record_sections()` contract | **Done.** `RecordSection` / `RecordEntry` / `SectionCategory` in `app.core.record`; the hook on `BaseModule` defaults to `[]`. In core, not in the module, or a contributing module would have to depend on an optional one |
| Composition + read endpoint | **Done.** `GET /api/v1/record/patients/{id}`, `record.read`. Empty sections still returned; retracted entries excluded unless asked for; a failing section logged and returned empty rather than denying the rest |
| First contributor | **Done.** `patients_clinical` — allergies, medications, systemic diseases, surgical history, carrying clinical time, lifecycle state and the professional responsible |
| The other contributors | **Pending.** `patients` (identification), `clinical_notes` (evolution), `odontogram`, `periodontogram`, `treatment_plan` (therapeutic plan), `media` (imaging), `agenda`. Whether `recalls` contributes is still open |
| Patient-level view + menu entry | **Pending.** The module declares an empty Nuxt layer, ready for it |
| PDF/A-3 + DPMF export, digest chaining | **Pending.** Needs the header to name a professional and a licence, which phase 0 unblocked |

**`depends = ["patients", "professionals"]`**, and the shortness is the point:
contributing modules are reached through the core contract, so the record never
imports them. `patients_clinical`, `clinical_notes`, `odontogram`,
`periodontogram`, `treatment_plan`, `media` and `agenda` are deliberately *not*
dependencies — uninstall one and the record is shorter, not broken. What is
declared is what the header reads directly: who the record is about, and which
professional answers for it. Expect `media` to join when phase 2 produces
artifacts.

## Open questions

- Which role holds `record.disclose`. Clinical governance, not technical.
- Whether `recalls` contributes a clinical section.
- Which procedure code set, per jurisdiction.
- Retention floors per jurisdiction, expressed through the existing
  `retention_reason` — needs the counsel review this whole document is
  conditioned on.
- Whether a `SELF`-custody tenant gets the same disclosure UI when there
  is no subprocessor in the path ([ADR 0028](../adr/0028-self-hosting-is-the-premium-tier.md)).
- **Where clinical authorship comes from.** Blocking, and described under
  *Phase 0, where it actually stands*.
