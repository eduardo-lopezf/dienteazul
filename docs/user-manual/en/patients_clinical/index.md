---
module: patients_clinical
last_verified_commit: 0000000
---

# Patients Clinical

> _Scaffolded stub — replace with proper documentation when this module is next touched._

Landing page for the `patients_clinical` module in the end-user manual.

## Health questionnaire

**Patient record → Health questionnaire.** What the patient declares at a
visit: reason for the visit, blood group, allergies, twelve yes/no
questions (with their cause) and the checklist of conditions.

- **On screen:** *New questionnaire*. A question left unanswered stays
  unasked, not "no".
- **Signature:** at the end of the on-screen form the patient signs with a
  finger, a stylus or the mouse. Their name is offered; when a guardian
  or a representative signs, change the name and say so under *Signs
  as*. The signature is required to save; the list marks the signed
  ones and opening one shows the signature and who signed. If the patient
  prefers to sign by hand, use *On paper*: both ways are equally valid.
- **On paper:** *Print blank form* produces the sheet with the patient's
  data; it is filled in by hand, scanned and uploaded from *New
  questionnaire → On paper*. The reason for the visit is typed separately
  so it shows in the record.
- A saved questionnaire is not edited: the next visit fills in another.
  One saved by mistake is taken back with *Retract*, leaving a trace.
- It does not replace the medical history: the allergies, medication and
  diseases the clinic keeps current stay where they are.
- At the foot of the form, and above the signature on the blank sheet, is
  the clinic's **reference regulation** (*Settings → General → Record
  regulation*).

## ASA classification

**Patient file → Summary → ASA classification.** The patient's physical
status on the ASA scale, as a clinician assessed it on a given day.

- The card shows the current class, when it was assessed and by whom.
- *Assess* opens the dialog: pick the class (I to IV), tick the emergency
  procedure box (E modifier) if it applies, and note what it rests on.
- An assessment is not edited. When the patient's condition changes,
  assess again: the earlier one stays in the history. If one was saved by
  mistake, *Retract* takes it back on the record, and the one before it
  is the current class again.
- A class of III or higher shows among the alerts of the file, next to
  the allergies.
- When **booking an appointment**, the dialog warns if the patient is ASA
  III or IV, with the date of the assessment and what it rests on. It
  does not stop the booking. Reception sees only the class ("ASA IV") and the
  recommendation; what it means, when it was assessed, by whom and on
  what grounds is shown only to whoever can read the medical history.
- Assessing needs `patients_clinical.asa.write` (dentists and
  administrators). Whoever can only read the history sees the class and
  its history.

## Screens

This module ships no Nuxt pages of its own.

## Permissions

- `patients_clinical.medical.read`
- `patients_clinical.medical.write`
- `patients_clinical.asa.read`
- `patients_clinical.asa.write`
- `patients_clinical.emergency.read`
- `patients_clinical.emergency.write`

## Technical references

- [Technical overview](../../../technical/patients_clinical/overview.md)
- [Permissions](../../../technical/patients_clinical/permissions.md)
- [Events](../../../technical/patients_clinical/events.md)
