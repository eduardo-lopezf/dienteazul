# Record — overview

The clinical record as a composition. One module, no clinical tables.

## What it is

A patient's *expediente* is spread across the modules that treat them:
demographics in `patients`, antecedents in `patients_clinical`, evolution notes
in `clinical_notes`, tooth status in `odontogram`, charting in
`periodontogram`, therapeutic plans in `treatment_plan`, radiographs in
`media`. This module assembles those into a header plus ordered sections of
dated, attributed entries — the shape of a paper record, and of both
interchange formats worth targeting later, so an export becomes a mapping
rather than a rewrite.

**It owns none of that data**, and the design says so out loud
([`docs/features/expediente-clinico.md`](../../features/expediente-clinico.md)):

> The temptation is to add an `expediente` table and copy data into it. That is
> the failure this spec exists to prevent. The record is not a new place to
> keep clinical data; it is a *view* of data seven modules already own, and the
> moment it becomes a copy it starts drifting from the source and there are two
> truths about a patient's allergies.

So the module has no models and no migrations, like `reports`.

## Who contributes

| Category | Section | Module |
|---|---|---|
| Identification | `identification` | `patients` |
| Antecedents | `health_questionnaires`, `asa_assessments`, `family_history`, `medical_context`, `allergies`, `medications`, `systemic_diseases`, `surgical_history` | `patients_clinical` |
| Odontogram | `chart` — findings and treatments, with teeth and surfaces | `odontogram` |
| Periodontal | `chartings` — one per probing, with its indices | `periodontogram` |
| Evolution | `notes` — clinical notes only, administrative ones left out | `clinical_notes` |
| Therapeutic plan | `plans` (no prices, no internal notes), `prescriptions` | `treatment_plan` |
| Imaging | `imaging` — radiographs and photographs, not administrative documents | `media` |
| Consents | `consents` | `consents` |

The composition also returns `professionals`: name and licence of whoever
the entries name as clinically responsible.

## What a record should hold

`coverage` in the response: ten requirements of a dental record and
whether this patient's meets each — complete identification (date of
birth, sex, address), the reason for the visit (a health questionnaire
with its chief complaint), family history, personal history, dental chart,
diagnosis (on a plan, or as a diagnosis note), prognosis, treatment plan,
evolution notes, a signed informed consent. Computed in `coverage.py` from
the composed sections, retracted entries excluded.

It is this product's reading of NOM-004-SSA3-2012 for a dental practice —
**an engineering reading, pending legal review** — and a check of
presence, not of quality. "Not met" also means "never asked": the record
cannot tell a patient with no family history from one nobody asked.

## Where it shows

The *Expediente* tab of the patient record (`patient.detail.tabs`,
permission `record.read`). It is a screen for someone already entitled to
the chart.

## The clinic's format

`GET/PUT /api/v1/record/format`, edited at *Settings → Apps → Clinical
record*. Three lists stored in `clinic.settings["record_format"]`:
`hidden_sections`, `section_order`, `disabled_requirements`. Applied in
`RecordService.compose`, so the tab, the PDF and the scope a disclosure
accepts all follow it. Hiding deletes nothing.

The head of the printed record is a **letterhead**
(`app.core.letterhead`, [ADR 0046](../../adr/0046-the-letterhead-belongs-to-the-clinic.md)):
that of the professional who hands the record over, or the clinic's when
they have none — never another professional's. Letterheads are edited in the
Workspace's settings (*Settings → General → Letterheads*), not on this
App's page; they are not part of the record's format.

## Handing it over

Printing or giving a copy is a **disclosure**
([ADR 0033](../../adr/0033-disclosure-requires-a-recorded-authorisation.md)),
and the only way a printable record comes to exist:
`POST /patients/{id}/disclosures` (`record.disclose`).

| Purpose | Evidence required |
|---|---|
| `continuity_of_care` | The clinical justification |
| `patient_copy` | `identity_verified` |
| `authorised_third_party` | What the patient signed, described |
| `legal_requirement` | The authority and its order |

The request names the sections to include; an unknown one, or a scope
with nothing in it, is refused. Retracted entries are never included. The
PDF is stored in `record_disclosure` as it left, with its SHA-256 and a
manifest of the entries it carried, and `GET /disclosures/{id}/document`
serves those bytes — nothing is regenerated. Each disclosure is an entry
of the record (`record.disclosures`, last in reading order).

The PDF's wording is `labels.json`, generated from the frontend locales
by `backend/scripts/generate_record_labels.py`.

## The contract

A contributing module returns `RecordSection` objects from
`get_record_sections()`. The vocabulary lives in `app.core.record`, not in this
module, for the reason that settled the same question for subject rights: a
contributing module would otherwise have to import from an **optional** module
and declare it in `manifest.depends`, which inverts the dependency and makes
`record` required by `patients_clinical`, which is not removable. Core owning
the types keeps every arrow pointing inward.

```python
RecordSection(
    name="allergies",                      # unprefixed; the registry adds the module
    title_key="record.section.allergies",  # i18n, never a literal
    category=SectionCategory.ANTECEDENTS,
    collect=_collect_allergies,            # (db, clinic_id, patient_id) -> [RecordEntry]
    order=10,
)
```

Each `RecordEntry` carries clinical time (`occurred_at` — a surgery recorded
today that happened in 2019 sorts into 2019), a lifecycle `status` (active /
ended / retracted, the distinction ADR 0032 settled), the professional
responsible and the account that typed it, where the fact lives
(`source_table` / `source_id`), and a `codes` list that stays empty until the
coding phase — the field exists from the start so adding coding is not a
migration of every section.

### It is not `SubjectContributor`

Same pattern, different contract, because they answer different questions:

| | `SubjectContributor` | `RecordSection` |
|---|---|---|
| Question | "What do you hold about this person?" | "What of yours belongs in a clinical record?" |
| Audience | The data subject, a regulator | Another clinician |
| Billing data | Yes — it is their data | **No** — a referral is not a financial document |
| Ordering | By module | Clinically, by section |
| Erasure | Central to it | Not applicable (ADR 0032) |

A module may implement both, one, or neither. `billing`, `payments`,
`verifactu` and `accounting_export` implement only the subject contract, and a
test pins that they contribute nothing here.

## Composition rules

- **Installed modules only.** The fan-out asks `module_registry.list_modules()`
  (ADR 0018), so an uninstalled module makes the record shorter, not broken.
- **Empty sections are returned.** "This module holds nothing about this
  patient" is an answer; a missing section leaves the reader unable to tell it
  was asked.
- **A failing section is logged and returned empty.** One module's bug must not
  deny a clinician the rest of the chart mid-consultation.
- **Retracted entries are excluded by default**, reachable with
  `include_retracted=true`. Never deleted — "what did the chart say that day"
  has to stay answerable — but not part of what a colleague is handed.
- **Entries sort by clinical time**, not by when they were typed.

## What this module does not do yet

Phases 1–4 of the spec. The composition and its read endpoint exist; the
patient-level view, the exports (PDF/A-3, DPMF), the disclosures and
authorisations, the coding and the interchange formats do not. See
*Phase 0, where it actually stands* in the spec for what is blocking what.
