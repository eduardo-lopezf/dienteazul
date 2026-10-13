# 0038 — `apps.json` switches Apps for the whole deployment

- **Status:** accepted
- **Date:** 2026-10-01
- **Deciders:** Eduardo (maintainer)
- **Tags:** modules, apps, lifecycle, boot

## Context

[ADR 0036](0036-an-app-is-a-declared-group-of-modules.md) made an App a
named group of modules, with its catalog in code and an `enabled` flag
that did nothing. Two things were missing: a place an operator can edit
without touching Python, and a flag that means something.

Switching an App off has a harder half. `recalls`, `notifications`,
`clinical_notes`, `treatment_plan`, `reports` and `migration_import` all
declare `agenda` in `depends`, and the lifecycle refuses to disable a
module while a dependent runs
([ADR 0035](0035-apps-are-disabled-not-uninstalled.md)). Following that
rule, turning Agenda off would turn most of the product off with it.
The requirement is the opposite: the rest keeps working and, where it
used to offer an appointment, says it cannot.

## Decision

**`backend/apps.json` lists every App with `"status": "enabled"` or
`"disabled"`. A disabled App's modules are not mounted. Nothing else
about them changes.**

```json
{ "apps": [
  { "name": "agenda", "version": "0.1", "status": "enabled",
    "modules": ["agenda", "schedules"] }
] }
```

1. **One file, one deployment.** It is read once at boot and cached for
   the life of the process; an edit takes effect at the next restart.
2. **It filters, it does not decide.** What runs is
   `core_module.state == installed` *minus* the modules of disabled
   Apps. `installed_module_names()` applies it, so routes, handlers,
   tools, permissions and jobs all follow; `/modules/-/active` applies
   it too, so the menu entry goes. `core_module` is never written: the
   records stay `installed`, the tables stay migrated, and setting the
   flag back restores everything. This narrows
   [ADR 0018](0018-install-state-is-the-mount-authority.md) — the
   database still says what is installed, the file says what the
   deployment lets run.
3. **It does not cascade.** Modules that `depend` on a disabled App's
   modules keep running. They can, because the App's code is still on
   disk and its tables are still there; only its mounted surface is
   gone.
4. **A disabled App's pages send the visitor home.** Every layer is
   compiled into the frontend, so the routes still exist. The table in
   `frontend/app/config/appRoutes.ts` says which path prefixes belong to
   which App, and `useAppRouteGuard`, run by the default layout,
   redirects a visit to `/` with a notice. One mechanism for every App;
   a page does not guard itself.
5. **The rest of the product says so and carries on.** Anywhere another
   app offers to book an appointment goes through
   `useAppointmentBooking()`, which answers "No se pueden crear citas"
   instead of navigating. Agenda's own widgets and buttons are gated by
   `agenda.*` permissions, which nobody holds while it is not mounted,
   so they disappear on their own.

Before them sits **Workspace**, the base App, with no modules and always enabled ([ADR 0043](0043-the-workspace-is-the-base-app.md)). Twelve Apps are declared after it, and every module belongs to exactly
one (`test_every_module_belongs_to_an_app`). Core: **Agenda** (`agenda`,
`schedules`), **Patients** (`patients`, `patients_clinical`,
`patient_timeline`, `media`), **Recalls** (`recalls`), **Treatments**
(`catalog`, `treatment_plan`, `odontogram`, `periodontogram`,
`clinical_notes`). Optional, until they are classified: **Budgets &
payments** (`budget`, `payments`, `billing`, `verifactu`,
`accounting_export`), **Cash desk** (`cashbox`, `liquidations`),
**Communications** (`notifications`, `whatsapp_kapso`), **Professionals**
(`professionals`), **Clinical record** (`record`), **Reports**
(`reports`), **AI** (`copilot`), **Data migration** (`migration_import`).

The treatment catalog was first left out of Treatments, because `catalog`
also owns VAT types and specialties, which Billing and Professionals
use. It is part of Treatments now: there is no treatment without a
catalog, and an App that shipped without it could not stand as a core
App. The price is paid only while Treatments is off, and is known:
invoices are written with no VAT type to pick and a professional has no
specialty to choose. Both screens keep working. Moving VAT types to
where invoices live would remove the first.

With Treatments off, Agenda still books appointments — with no
treatments — shows "No se pueden asignar tratamientos" where the picker
was, refuses new links, and hides the stored ones until the App returns
([ADR 0037](0037-a-module-integrates-with-what-it-can-live-without.md)).

A malformed file — unknown status, an App listed twice, a module in two
Apps — raises `AppCatalogError`. Boot then takes the existing fallback
for unreadable state: mount everything and log the exception.

**The file is read once, at boot.** An edit takes effect at the next restart, not before. Two things keep that from being a surprise: in development the server watches `apps.json` and restarts itself (`--reload-include apps.json` in `docker-compose.yml`), and `GET /api/v1/apps` reports `pending_enabled` when the file on disk differs from what is running, which Settings → Apps shows as "Se deshabilitará al reiniciar" / "Se habilitará al reiniciar".

## Consequences

### Good

- An operator turns an App off by editing one line and restarting, and
  on by reversing it. No data is touched in either direction.
- A module absent from `apps.json` is unaffected, so Apps can be
  declared one at a time.

### Bad / accepted trade-offs

- **Global, not per tenant.** Every database served by the deployment
  gets the same answer. Per-tenant selection needs this stored per
  database.
- **`depends` is no longer a guarantee that the dependency is
  running.** A module that depends on an App's module must behave as if
  it merely integrates with it
  ([ADR 0037](0037-a-module-integrates-with-what-it-can-live-without.md)).
  For Agenda the frontend entry points are covered; two things are not:
  - `migration_import` creates appointments through
    `AppointmentService` directly, App or no App.
  - Settings → cabinets writes through `/api/v1/agenda/cabinets`; with
    Agenda off it fails with the generic error rather than a message.
- With Treatments off, a patient link carrying `?tab=clinical` opens on
  an empty area: the Clínico tab is rightly gone, and nothing falls back
  to the summary.
- **Settings → Apps shows the App as disabled while its modules still
  read `installed`** in the list below. Both are true: installed, and
  held back.
- **Historical data stays visible** where other apps read it — reports
  still count past appointments.
- The routes of a disabled App remain in the frontend build. They
  redirect home with a notice rather than not existing, and the guard
  is client-side: the server renders the page once before it leaves.
- **Other apps still show a disabled App's data.** With Patients off,
  Recalls, treatment plans and invoices list patients exactly as
  before — they read the tables themselves. Only what the App *offers*
  (its screens, its pickers) goes.
- **With Treatments off, `treatment_plan` misses `budget.accepted`,
  `budget.rejected`, `budget.renegotiated`, `appointment.completed` and
  `clinic.created`**, and nothing replays them when it returns.

## Alternatives considered

- **Mark the App's modules `disabled` in `core_module`.** The existing
  rule would refuse, or with a cascade take six dependents down. It
  would also make a per-database fact out of a per-deployment choice.
- **Cascade to dependents.** Coherent, and not what was asked: Agenda
  off must not mean Recalls and Treatment plans off. An App that does
  want it declares it, one by one
  ([ADR 0053](0053-an-app-can-declare-the-apps-it-goes-off-with.md)).
- **An environment variable.** Fine for one flag, awkward for a list of
  Apps with versions and modules.

## How to verify the rule still holds

- `backend/tests/test_app_catalog.py` — the shipped file, the parsing
  errors, a disabled App's modules held back with their state
  untouched, and a full boot with Agenda off: no `agenda` or `schedules`
  routes or permissions, dependents mounted.
- `frontend/tests/e2e/settings-apps.spec.ts` — the catalog as shipped.
- `backend/tests/test_agenda_treatments_optional.py` — booking with
  Treatments off, refused links, hidden stored links.
- By hand, 2026-10-01, Treatments disabled: the appointment modal shows
  the notice, and home, agenda, the patient record and `/treatments`
  load with no failed API call.
- By hand, 2026-10-01: with Agenda disabled, the menu entry is gone,
  home and the patient record load with no failed API call, "Cita" on a
  patient shows the notice, and `/appointments` redirects home.

## References

- `backend/apps.json`
- `backend/app/core/plugins/apps.py`, `service.py` (`installed_module_names`), `router.py`
- `frontend/app/composables/useAppointmentBooking.ts`, `useModules.ts` (`isActive`)
- `frontend/app/config/appRoutes.ts`, `frontend/app/composables/useAppRouteGuard.ts`
- `backend/app/modules/patients/frontend/components/shared/PatientVisualSelector.vue` — the notice for any screen that embeds the picker
