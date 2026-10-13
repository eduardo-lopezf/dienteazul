# Expediente clínico (`clinical_record`)

- **Tier:** optional  ·  **Version:** 0.1
- **Declared in:** `backend/apps.json`  ·  **Composition and requirements:** [Apps catalog](../../apps-catalog.md)

## What it is for

The patient's clinical record as a document, and what makes it one under NOM-004-SSA3-2012 and Ley General de Salud Art. 51 Bis 1: the record composed from what the other Apps hold (`record`), and the consent letters — informed consent to treat and consent to the use of personal data (`consents`).

## Modules

- [`record`](../../technical/record/overview.md) — code in `backend/app/modules/record/` ([notes](../../../backend/app/modules/record/CLAUDE.md))
- [`consents`](../../technical/consents/overview.md) — code in `backend/app/modules/consents/` ([notes](../../../backend/app/modules/consents/CLAUDE.md))

## With this App off

Not verified.

## Notes

- Goes off with Patients: it lists it in `requires_apps`, so disabling Patients disables this App too ([ADR 0053](../../adr/0053-an-app-can-declare-the-apps-it-goes-off-with.md)). Patients runs without it.
- Requires Patients; `record` also requires Professionals, `consents` only integrates with it. Neither module is installed by default.
- Scope decided for NOM-004: the dental record, plus family history and prognosis. Built so far: consent letters. Pending: family history, prognosis, and a per-patient check of what the norm asks for.
- The legal wording of consents is the clinic's; the App supplies the mechanism and the custody.

## Decisions

- [0045](../../adr/0045-a-consent-is-a-record-entry.md)
- [0034](../../adr/0034-the-record-is-composed-not-stored.md)
