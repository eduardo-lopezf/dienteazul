---
module: consents
last_verified_commit: 0d60d45
---

# Consents

The patient's consent letters. Part of the **Clinical record** App.

## What it does

- **Informed consent.** The letter in which a professional explains a
  procedure, its risks and its alternatives, and the patient accepts or
  declines. It cannot be signed without naming the professional who
  explained it.
- **Use of personal data.** The patient accepts the clinic's privacy notice.

## Where it is

- **Patient record → Consents.** Lists the patient's letters. *New consent*
  writes a draft from a template; *Sign* shows the text to the patient and
  captures their signature (or records that they decline). *Print* opens
  the letter as a PDF.
- **Settings → Clinic → Consent templates.** The clinic's texts: one per
  procedure, and the privacy notice. Editing a template creates a new
  version; letters already written do not change.

## Two ways to sign

- **On screen.** The patient signs with a finger, a stylus or the mouse.
- **On paper.** In *Sign* choose *On paper* and press *Print*: the letter
  comes out with the patient's data and the text already written, and
  ruled lines to fill in by hand — diagnosis, treatment plan, place and
  date, and the signatures of the patient or person responsible, of who
  informed and of two witnesses. Once signed, scan or photograph it,
  upload it under *Scanned signed letter* (PDF, JPG or PNG) and press
  *Save signed letter*. The file is kept in the patient's documents and
  the letter becomes **Signed**, marked *Signed on paper*; the *Scan*
  button opens it.

## Consent before confirming a plan

The letter is not mandatory: the rule comes switched off. Once the
clinic switches it on, a treatment plan is not confirmed without a signed
informed consent letter written for that plan, and marking a treatment as
performed or completing an appointment of that plan asks for the letter
first.

- From the plan, *Confirm* says it is missing and **Write the letter**
  opens this tab for that plan. The letter saved is marked *For a plan*.
- Only an **informed consent** letter counts, **signed** (on screen or on
  paper) and not revoked. A letter for another plan, or the consent to
  the use of data, does not stand in for it.
- Switch it off with *Require informed consent to confirm a plan*, under
  *Settings → Clinical → Consent templates*.

## Worth knowing

- Without the scan a paper letter cannot be marked as signed: the scan is
  the signature the record keeps.

- A draft can be edited or discarded. **A signed letter is never edited or
  deleted**: if the patient takes their consent back it is **revoked**, and
  what they signed and when they withdrew it stay on record.
- Signed, declined and revoked letters appear in the patient's clinical
  record.
- The wording of the templates is the clinic's and its legal adviser's; the
  program ships no legal text.
- With the Professionals app disabled nobody can be named as having
  explained the procedure, so an informed consent cannot be signed.

## Permissions

- `consents.read`
- `consents.write`
- `consents.templates.write`

## Technical references

- [Technical overview](../../../technical/consents/overview.md)
- [Permissions](../../../technical/consents/permissions.md)
