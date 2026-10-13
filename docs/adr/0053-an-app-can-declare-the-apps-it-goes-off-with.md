# 0053 — An App can declare the Apps it goes off with

- **Status:** accepted
- **Date:** 2026-10-12
- **Deciders:** Eduardo (product owner)
- **Tags:** apps, modules, clinical-record

## Context

[ADR 0038](0038-apps-json-switches-apps-for-the-whole-deployment.md)
switches an App off in `backend/apps.json` and leaves its dependents
running: Agenda off must not mean Recalls and Treatment plans off. A
cascade to every dependent was considered there and rejected.

That is the right default and the wrong answer for one pair. The Clinical
record App (`record`, `consents`) is a reading of the patient's file: its
only screens are tabs on the patient's page, and every route it has is
`/patients/{id}/…`. With Patients off and the Clinical record still
mounted, the deployment serves consent letters and printable records of
patients nobody can open — reachable by API, absent from every screen.

The stated rule is the other way round too. Patients must run without the
Clinical record: it *integrates* with it
([ADR 0037](0037-a-module-integrates-with-what-it-can-live-without.md)),
through record sections and slots, and imports nothing from it.

## Decision

**An App may list, in `apps.json`, the Apps it cannot run without
(`requires_apps`). When any of them is disabled, it is disabled with
them.** The default stays as ADR 0038 left it: an App that lists nothing
keeps running whatever its dependencies do.

- The Clinical record lists `["patients"]`. Nobody else lists anything.
- It is resolved when the file is read (`read_app_catalog`), so
  everything that asks whether an App is enabled gets the same answer:
  what is mounted, the permissions granted, the Apps screen, the
  operator's console. It carries through a chain.
- The App reads as disabled, with `held_back_by` naming the App that took
  it down — which is how the Apps screen tells "switched off" from
  "switched off together with Patients".
- It is declared, not derived from `manifest.depends`: `depends` says what
  a module imports, and most modules that import `patients` should keep
  running without its screens.
- The other direction needs no declaration and gets a test: with the
  Clinical record disabled, Patients boots whole.

## Consequences

### Good

- "Patients off" no longer leaves a clinical record mounted with no
  patient screen to reach it from.
- The exception is visible in one file, next to the switch it modifies.

### Bad / accepted trade-offs

- **Two rules about dependents instead of one.** Whoever reads ADR 0038
  has to know this one exists; both link to each other.
- **Per-deployment only.** A clinic's own selection (`clinics.apps`) is
  not resolved this way. It does not need to be today — Patients is a
  core App, so no clinic is without it — and it will when a core App can
  be left out of a clinic.
- An App switched off this way still shows its modules as `installed`,
  like any disabled App.

## Alternatives considered

- **Cascade to every dependent** — rejected in ADR 0038 for Agenda, and
  still wrong: Treatments depends on Patients and must keep its catalogue
  and plans.
- **Derive it from `depends`** — the same cascade under another name.
- **Leave it mounted and guard each route** — every new route of the
  Clinical record would have to remember.
- **Hard-code the pair in `apps.py`** — one line shorter, and the next
  pair would be a code change instead of a line in the file.

## How to verify the rule still holds

- `backend/tests/test_app_catalog.py` — the shipped file declares it for
  the Clinical record only; Patients off takes the Clinical record and
  nothing else; the Clinical record off leaves Patients running; a chain
  resolves; an unknown or self-referring `requires_apps` is refused; and
  two full boots, one without the Clinical record and one without
  Patients.
- By hand, 2026-10-12, Clinical record disabled: `/api/v1/record` and
  `/api/v1/consents` answer 404; the patient's page loses the *Expediente*
  and *Consentimientos* tabs and keeps the rest, the ASA card included;
  `/settings/apps/clinical-record` sends back home.

## References

- `backend/app/core/plugins/apps.py` — `requires_apps`, `held_back_by`,
  `_switch_off_with_required`
- `backend/apps.json`
- [ADR 0038](0038-apps-json-switches-apps-for-the-whole-deployment.md)
