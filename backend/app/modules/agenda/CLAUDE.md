# Agenda module

Appointments, scheduling, cabinets. Owns the `Appointment` entity and
its state machine.

## Public API

Routes mounted at `/api/v1/agenda/`. See `router.py` for the full
surface (appointments CRUD, transitions, cabinet assignments, kanban).

## Dependencies

`manifest.depends` is empty, and **the agenda imports no other module**
(ADR 0039) — not even under `TYPE_CHECKING`. A test reads the source and
fails on any `app.modules.<other>` import.

What it needs from its neighbours comes through core contracts
(`app/core/contracts.py`), looked up in `integrations.py`:

| Need | Contract | Supplied by |
|---|---|---|
| Patients | `PatientDirectory` | `patients` |
| Professionals | `ProfessionalDirectory` | `professionals` |
| Planned treatments | `PlannedTreatments` | `treatment_plan` |
| Breaks / off hours | `WorkingHours` | `schedules` |

`integrates` lists only the owners of tables its foreign keys point at
(`patients`, `professionals`, `catalog`, `treatment_plan`). There are no
ORM relationships to those rows: `presenter.py` builds the API response
by asking each directory once per page. To use a new piece of another
module, widen its contract and its provider — do not import it.

An appointment can be booked with no patient, no professional and no
treatments (ADR 0037). When a professional *is* assigned it references
the clinic directory's `professionals.id`, never a product-account ID.
While the Professionals App runs a professional is still required; that
rule is the service's, not the schema's.

**A contract with no supplier means the App is off.** The agenda then
(1) refuses a new link — `_check_links` in the service — (2) hides the
stored ones — the presenter leaves them out, ids included — and (3)
deletes nothing, so they show again when the App returns. A new link
needs all three, plus a test in `tests/test_agenda_optional_links.py`.
On the frontend the same question is `useAgendaLinks()`.

`appointments.title` names an appointment that has no patient.

## Contracts offered

`providers.py` supplies `AppointmentBook` (ADR 0039) — the patient of an
appointment, a patient's appointment ids, and the notes left on planned
treatments during visits. `clinical_notes` consumes it instead of
importing `models.py`. Widen this contract rather than let another module
import the agenda's tables.

## Permissions

`agenda.appointments.{read,write}`, `agenda.cabinets.{read,write}`.

## Tools exposed

Agent tools in `tools.py` (wrap `AppointmentService`, no logic duplicated).
Write tools use `ctx.supervisor_id` (the human in the loop) for audit columns.

| Tool | Category | Wraps | Permission |
|---|---|---|---|
| `get_day_overview` | READ | `AppointmentService.list_appointments` | `agenda.appointments.read` |
| `get_appointment` | READ | `AppointmentService.get_appointment` | `agenda.appointments.read` |
| `list_cabinets` | READ | `CabinetService.list_cabinets` | `agenda.cabinets.read` |
| `list_professionals` | READ | `kanban_service._fetch_professionals` | `agenda.appointments.read` |
| `book_appointment` | WRITE | `AppointmentService.create_appointment` | `agenda.appointments.write` |
| `reschedule_appointment` | WRITE | `AppointmentService.update_appointment` | `agenda.appointments.write` |
| `update_appointment_status` | WRITE | `AppointmentService.transition` | `agenda.appointments.write` |
| `cancel_appointment` | DESTRUCTIVE | `AppointmentService.cancel_appointment` | `agenda.appointments.write` |

`update_appointment_status` excludes `cancelled` (that's `cancel_appointment`,
DESTRUCTIVE). Invalid transitions return the allowed next states from
`VALID_TRANSITIONS` so the agent can self-correct instead of retry-looping.

`find_free_slots` is intentionally **not** here — free-slot computation belongs to
`schedules`, which will register its own tool. Agenda does not cross that boundary.

## Asked before completing

`GET /appointments/{id}/completion-check` → `plans_lacking_consent`: the
plans with a treatment still pending in this visit whose required
informed consent is not signed (`AppointmentService.plans_lacking_consent`,
through the `PlannedTreatments` and `PlanConsents` contracts — empty when
either App is off). A notice, never a stop: `transition` does not read
it. Every frontend path into `completed` awaits
`useCompletionCheck().confirm(appointment)` first; the question is
rendered once by `CompletionCheckHost.vue`.

## Frontend slots exposed

- `appointment.completed.followup` — rendered by `AppointmentQuickActions.vue`
  after a successful transition to `completed`. Sibling modules
  (e.g. `recalls`) register components that prompt the receptionist
  for a follow-up action. Modal stays hidden when no registrations
  exist. Slot ctx: `{ appointment }`.
- `appointment.patient.alerts` — rendered by `AppointmentModal.vue` under
  the patient picker, once a patient is chosen. What whoever books should
  know before picking a time; `patients_clinical` puts the ASA III/IV
  notice there. Slot ctx: `{ patientId }`.

## Events emitted

- `appointment.scheduled` — new appointment
- `appointment.updated` — generic update
- `appointment.status_changed` — published alongside specific status events; payload carries `from_status`/`to_status`/`changed_at`/`changed_by`
- `appointment.cabinet_changed` — cabinet (re)assignment, payload includes `from_cabinet_id`/`to_cabinet_id` (nullable)
- `agenda.visit_note_updated` — visit-level note (reuses `AppointmentTreatment.notes`)

## Events consumed

None.

## Lifecycle

- `removable=False`. Most modules depend on appointments.

## Gotchas

- **Resolve composables in `setup`, never inside a watcher or handler.**
  Anything reaching `useApi` also reaches `useI18n`, which throws "Must be
  called at the top of a `setup` function" from a callback — and the
  callback's remaining work is silently lost. `AppointmentModal` did this
  with `useAppointmentNotesIndicator()` on close, so the note indicator it
  meant to refresh never refreshed.
- **The card timer is a duration, not a minute count.** `formatDurationShort`
  rolls up to hours past 90 minutes and to days past a day: the agenda is
  browsed on days that are not today, where an unbounded minute count
  ("retrasada 8749 min") is a number nobody can read.

- **Schedules must NOT be a dependency.** The `schedules` module depends
  on agenda; the data flow is one-way. Never declare
  `depends: ["schedules"]` here. See `schedules/CLAUDE.md`.
  It is declared in `integrates` instead, along with `treatment_plan`
  (ADR 0037): linked when it runs, done without when it does not.
- **Status transitions go through `AppointmentService.transition`** —
  it publishes both the specific status event and the generic
  `appointment.status_changed`.
- **Cabinet assignment uses `assign_cabinet`** — it publishes
  `appointment.cabinet_changed` with both old and new ids.
- **Mobile free-slot computation is client-side** (#61). The composable
  `frontend/composables/useFreeSlots.ts` derives gaps from already-loaded
  appointments + the optional `schedules` availability payload. Do not
  add a backend free-slot endpoint without ADR — the data flow stays
  client-side and the schedules dependency stays optional.
- **Professional identity.** `Appointment.professional_id` is a directory
  profile that is active and of type `dentist` or `hygienist`.
- **The grids drag on Pointer Events, never mouse events.** The week and
  day grids share `composables/useSlotGridDrag.ts`; the kanban has its
  own pointer implementation because it hit-tests columns rather than
  snapping to a slot. Do not reintroduce `mousedown`/`mousemove` or HTML5
  `draggable` here — Chrome on Android delivers neither while a finger is
  moving, which is how create, move and resize came to be silently
  broken on tablets. See `docs/technical/touch-adaptation.md`.
- **`start_time` / `end_time` are the clinic's wall clock, not instants.**
  The offset they carry is a storage artifact. Read them with
  `wallClockDate` / `formatWallClockTime` / `parseIsoParts` from
  `frontend/utils/date.ts`; serialize day boundaries with `toWallClockIso`.
  Plain `new Date(start_time)` moves the hands by the browser's offset and
  is how the same appointment came to be drawn at 12:00 on the grid and
  06:00 on the kanban card, listed at 11:30 in the patient record while the
  calendar said 17:30, counted as upcoming after it had happened, and filed
  under the previous day in deep links and per-day counts. Comparing two
  appointments with `new Date()` is fine — both shift equally — but
  anything that renders, buckets by day, or compares against *now* is not.
- **"Today" on the dashboard is the clinic's day.** `useHomeAgenda`
  resolves it through `clinicTimezone`; the greeting above those tiles does
  the same. Reading the browser's day instead put the header and the tile
  on different dates for anyone working outside the clinic's zone.
- **Calendar geometry reads `useDensity().effective`, not `density`.**
  The preference can say "compact" while a coarse pointer forces the
  touch scale; reading the preference puts the drag maths 10 px per slot
  out of step with the CSS variable that is actually drawn.

## Related ADRs

- `docs/adr/0001-modular-plugin-architecture.md`
- `docs/adr/0003-event-bus-over-direct-imports.md`

## CHANGELOG

See `./CHANGELOG.md`.
