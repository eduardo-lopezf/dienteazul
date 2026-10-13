---
module: record
last_verified_commit: 0d60d45
---

# Clinical record

The patient's clinical record, gathered in one place. Part of the **Clinical
record** App.

## Screens

- [Clinical record settings](./screens/settings_apps_clinical-record.md) — which sections it carries, in what order, and which points are reviewed.

- The documents' letterhead is set up in the Workspace: *Settings →
  General → Letterheads* and *Settings → Account → My letterhead*.

## Where it is

**Patient record → Record.** It shows, in the order of a paper record:

1. Identification
2. Antecedents: health questionnaires, family history, medical context, allergies, medication, systemic diseases
   and surgical history
3. Dental chart: findings and treatments, with their teeth
4. Periodontal chartings
5. Evolution notes
6. Treatment plans and prescriptions
7. Radiographs and photographs
8. Consents

Each entry carries its clinical date (when it happened, not when it was
typed in) and, when known, the professional responsible with their licence.

The tab and the printed record show the clinic's **reference regulation**,
set up under *Settings → General → Record regulation*.

## What the record should hold

At the top of the tab, a ten-point list says what this patient's record
already holds and what it lacks: complete identification, reason for the
visit, family history,
personal history, dental chart, diagnosis, prognosis, treatment plan,
evolution notes and a signed informed consent.

- It checks that the fact **exists**, not that it is right.
- A pending point is completed where that fact is written: antecedents in
  the medical history, diagnosis and prognosis on the treatment plan, the
  consent in its tab.
- It is an indicative reading of NOM-004-SSA3-2012, pending legal review.

## Printing or handing over the record

*Print or hand over* (top right) produces the record as a PDF. The record
does not leave the clinic without a trace, so first you state:

- **The purpose**, and what that purpose requires:
  - *Continuity of care* (referral or consultation): the clinical
    justification.
  - *Copy for the patient*: tick that their identity was checked.
  - *Third party authorised by the patient* (insurer, second opinion):
    what the patient signed and until when.
  - *Requirement of an authority*: the authority and the order's reference.
- **Whom it is handed to.**
- **What is included**: choose the sections. Retracted entries are never
  included.

On confirming, the PDF opens and the disclosure appears under *Disclosures
of the record*, with date, recipient and purpose. From there, *View the
document handed over* opens exactly the PDF that was handed over, even if
the record has changed since. A disclosure is never edited or deleted.

## Worth knowing

- **It is read-only.** Data is written where it always was — the chart, the
  notes, the plan; here it is read together. There are no two copies.
- *Hide empty sections* is on by default; turned off, every section shows,
  and an empty one says nothing is recorded.
- *Show retracted* reveals entries that were taken back. They are never
  deleted: they stay, marked.
- Administrative notes, prices and administrative documents are not part
  of the record.

## Permissions

- `record.read`
- `record.disclose` — print or hand over (admin and dentist)

## Technical references

- [Technical overview](../../../technical/record/overview.md)
- [Permissions](../../../technical/record/permissions.md)
