# Treatment plan module

Patient treatment plans with budget + odontogram sync. **Heaviest
`depends` in the system** — this module is an integration hub. Read
this file before changing any cross-module flow.

## State machine

```
                    ┌── budget accepted ──┐
draft ──confirm──► pending ───────────────┼──► active ──complete──► completed
  ▲                  │   └─ visit attended ┘      │
  │                  │ rejected/expired           │ cancelled by clinic
  │                  ▼                            ▼
  └─── reactivate ◄──────       closed      ◄─────┘
                            (closure_reason)
```

`pending → active` has **two** doors, and either is enough:

- `accept_from_budget`, on `budget.accepted`; and
- `activate_from_attendance`, whenever work is recorded against the plan
  — the clinic counts a plan as under way from the first consultation the
  patient attends, which is normally well before anything is signed.

Both are idempotent and both refuse anything that is not `pending`, so a
`draft` plan never skips confirmation.

**Every completion path calls `_sync_plan_lifecycle`**, which runs the
start and then the finish. Do not call `_check_and_complete_plan`
directly from a new path: on its own it only ever finishes an `active`
plan, so a plan carried out in one go would stall in `pending` with every
item done. The three paths that finish a treatment — `_finalize_item`,
`on_appointment_completed` and `on_treatment_performed` — all route
through the hook.

`closure_reason` ∈ `{rejected_by_patient, expired,
cancelled_by_clinic, patient_abandoned, other}`. See ADR 0006 and
`docs/workflows/plan-budget-flow.md` (staff manual).

## Public API

Routes mounted at `/api/v1/treatment-plans/`.

- `GET   /treatment-plans`              — list; `treatment_plan.plans.read`
- `POST  /treatment-plans`              — create; `treatment_plan.plans.write`
- `GET   /treatment-plans/{id}`         — detail
- `PUT   /treatment-plans/{id}`         — update; status transitions
- `POST  /treatment-plans/{id}/items`   — add item from catalog or odontogram tooth treatment
- `PUT   /treatment-plans/{id}/items/reorder`
- `POST  /treatment-plans/{id}/items/{item_id}/complete`
- `PATCH /treatment-plans/{id}/items/{item_id}/reopen` — `plans.write`; completed → pending, drops the charge (see gotcha)
- `POST  /treatment-plans/{id}/confirm`     — `plans.confirm`; draft → pending
- `POST  /treatment-plans/{id}/reopen`      — pending|active → draft, cancels linked budget; admin or an assigned professional only
- `POST  /treatment-plans/{id}/close`       — `plans.close`; any → closed
- `POST  /treatment-plans/{id}/reactivate`  — `plans.reactivate`; closed → draft
- `POST  /treatment-plans/{id}/contact-log` — record reception touchpoint
- `GET   /treatment-plans/pipeline`         — bandeja (6 tabs; `en_curso` leads)
- `GET   /treatment-plans/{id}/history`     — change log + the caller's rights
- `POST  /treatment-plans/{id}/apply-template` — append a template; `plans.write`.
  Body takes `excluded_template_item_ids`; returns `{items, skipped}`.
- `POST  /treatment-plans/{id}/catalog-items` — append hand-drawn lines;
  `plans.write`. `{lines: [{catalog_item_id, tooth_numbers, surfaces, phase,
  notes}]}` in, `{items, skipped}` out, 422 naming the lines still waiting
  for a tooth. Same code underneath as `apply-template`.
- `GET   /plan-templates`                   — list; `plans.read`. Each carries `specialty` (`key`, `names`): the discipline a reference template belongs to, `null` on the clinic's own
- `POST  /plan-templates`                   — create; `plans.templates`
- `PUT   /plan-templates/{id}`              — update; items are a full replace when sent
- `DELETE /plan-templates/{id}`             — soft delete (`is_active=False`)
- `POST  /plan-templates/from-plan/{id}`    — save an existing plan as a template
- `GET   /treatment-plans/patient/{patient_id}/proposals` — the same findings
  for a patient with **no plan yet**; what the builder seeds its draft from
- `GET   /treatment-plans/{id}/proposals`   — charted findings with nothing planned yet
- `POST  /treatment-plans/{id}/proposals`   — turn accepted findings into plan items
- `POST  /treatment-plans/{id}/dismissed-findings` — findings this plan is
  deliberately not answering; `plans.write`. Idempotent per `(plan, finding)`.
- `GET   /treatment-plans/{id}/items/{item_id}/prescriptions` — the
  treatment's prescriptions, newest first; `prescriptions.read`
- `POST  /treatment-plans/{id}/items/{item_id}/prescriptions` — write one
  (`{body, professional_id}`); `prescriptions.write`. 400 when the
  professional is not in this clinic's directory.
- `GET   /prescriptions/{id}/pdf` — print-ready PDF, served `inline`;
  `prescriptions.read`

> **Notes endpoints moved.** Since issue #60 the `clinical_notes` module
> owns every clinical-note CRUD path (`/api/v1/clinical_notes/*`). The
> per-item completion endpoint here no longer accepts `note_body` — the
> client orchestrates a follow-up POST to `clinical_notes` when the
> dentist captures a note at completion time.

## Dependencies

`manifest.depends = ["patients", "odontogram", "catalog"]`,
`manifest.integrates = ["budget", "payments", "professionals", "agenda", "media"]`.
Anything not on these lists is off-limits — no imports, no FKs.

**Only `patients` is imported from outside the Treatments App** (ADR 0039,
ADR 0042; `tests/test_treatments_app_isolation.py`). The five integrations
are reached without importing them:

- `professionals`: assignments are validated and labelled, and a
  prescription's signer is read, through `ProfessionalDirectory`. With it
  off nobody can be assigned and no prescription can be issued.
- `agenda`: `appointment.completed` carries `planned_items` (what the
  visit covered); `events.on_appointment_completed` works from that alone.
- `media`: the `plan_item` attachment owner is registered in
  `app.core.attachments`, where `media` reads it.

Seams left (raw SQL on another App's table, fine while the database is
shared): `stewards_of` joins `professionals`; `next_action` and the
pipeline join `appointments`; the pipeline and `tasks.py` join `budgets`.

For `budget` and `payments`:

- A plan **asks** `budget` questions through the read-only `PlanBudgets`
  contract — the brief on `plan.budget` (put there by `_attach_budgets`,
  not a relationship), what is priced, the plan's other live budgets.
- A plan **never writes** a budget. It publishes `treatment_plan.confirmed`,
  `status_changed` and `deleted`; `budget` mints, cancels and deletes in
  its own transaction and answers with `budget.created_for_plan`, which
  `events.on_budget_created_for_plan` turns into the link. So the confirm
  response does not carry the budget — re-read the plan.
- `payments` is asked one thing, through `Collections`: whether the patient
  paid into a plan about to be deleted or cancelled.

With Budgets off a confirmed plan goes straight to `active`, nothing is
locked or "unbudgeted", and the next step skips the budget. With Payments
off the collections guard lets the plan go. Generating a budget and pricing
additions are `budget` endpoints (`POST /api/v1/budget/plans/{id}/budget`,
`/addendum`).

`assigned_professional_id` (on `TreatmentPlan` and `PlannedTreatmentItem`)
FKs to `professionals.id`, not `users.id` — the assigned doctor is a
directory profile, independent of any product account (see `professionals`
module). `created_by`/`completed_by` stay FK'd to `users.id`: those record
who performed the action in the app, not who the clinical work is
attributed to.

## Permissions

`treatment_plan.plans.{read,write}`, plus `plans.{confirm,close,reactivate}`
for the workflow transitions and `plans.templates` for curating the clinic's
plan templates, and `prescriptions.{read,write}` — writing a prescription is
a clinical act (admin, dentist); reading and reprinting is granted to
hygienist, assistant and receptionist. Clinical-note permissions live in the
`clinical_notes` module since issue #60.

## Adding to a plan already under way

`_is_plan_locked` guards **changing** a plan, not filling it. `add_item`
deliberately skips it: a treatment added to a confirmed plan takes nothing
away from what the patient agreed to, and the old route — reopen, which
cancels the signed budget, then reconfirm and have it accepted again — cost
far more than the caries that prompted it. `update_item`, `remove_item` and
`reorder_items` still refuse.

What the new work costs is answered by `unbudgeted_items`, **derived, never
stored**: a budget line already names the odontogram `Treatment` it prices
(`budget_items.treatment_id`), which is the treatment the plan item points
at, so "unpriced" is a join. No column means nothing to drift and no
backfill — plans written before this answer correctly from the first
request. The plan's budgets are the ones carrying its number plus the
current link, the rule `delete_for_plan` and `_guard_collections` already
use.

Pricing them is `budget`'s `plan_quotes.price_additions`
(`POST /api/v1/budget/plans/{id}/addendum`), which reads the plan through
`PlanQuotes`. **Gotcha:** while the plan's budget is a draft, `budget`'s own
`_on_treatment_added_to_plan` already mirrors every addition into it and
stops at anything that is not a draft — so the addendum only ever has work
to do past that point, and its draft branch is a repair path for a handler
that raised (ADR 0020 records, never retries), not the usual one.

`plan.budget_id` keeps meaning "the budget this plan was agreed on". An
addendum is beside it, not instead of it; `other_live_budgets` is what
finds it.

## Frontend slots exposed

- `treatment_plan.detail.sidebar` — rendered by `PlanDetailView.vue` above
  the treatment list. `payments` registers the collections card there. Slot
  ctx: `{ planId, patientId, patientName, budgetId, planStatus,
  itemsRevision, planTotal, planMoney, phaseTotals }`. `itemsRevision`
  changes on every completion or reopen, and is the card's only cue to
  refetch the patient's money — without it the sidebar kept the old figure
  until a reload. `planMoney` is **this plan's** four figures (planned,
  earned, collected, pending), summed here from `usePlanCollections`; it is
  `{...zeros}` for a plan with no items (the composable does not call out
  for one, and the card would otherwise fall back to the patient's whole
  debt on a plan that cannot owe anything) and `null` only when the ledger
  could not be read at all.
- `treatment_plan.item.collect` — one treatment's "Cobrar", rendered inside
  `PlanItemDetailModal` and in the prompt that follows completion.
  `payments` registers the button. Slot ctx: `{ patientId, patientName,
  budgetId, amount, label?, block?, variant?, labelled?, onCollected? }`. **The
  callback is in the ctx on purpose**: `ModuleSlot` renders a slot
  component without forwarding its events, so the ctx is the whole contract
  in both directions.
- `odontogram.condition.actions` is **consumed** here too, in the
  treatment dialog's footer. The dialog passes `labelled: true` (and so
  does the collect ctx): the contributors render a text button instead of
  the icon they draw in the odontogram's conditions list.

## Events emitted

| Event | When | Notes |
|---|---|---|
| `treatment_plan.created` | plan created | consumed by `patient_timeline` |
| `treatment_plan.status_changed` | status transition | currently no subscribers |
| `treatment_plan.confirmed` | draft → pending | snapshot payload (items, totals, patient). Subscriber: `patient_timeline`. |
| `treatment_plan.closed` | any → closed | payload includes `closure_reason`. Subscriber: `patient_timeline`. |
| `treatment_plan.reactivated` | closed → draft | Subscriber: `patient_timeline`. |
| `treatment_plan.treatment_added` | item added | snapshot payload (catalog_item_id, tooth, surfaces, unit_price, budget_id). Subscriber: `budget`. |
| `treatment_plan.treatment_removed` | item removed | payload includes `budget_id`. Subscriber: `budget`. |
| `treatment_plan.treatment_completed` | item marked done | consumed by `patient_timeline`, `recalls`. Payload includes `treatment_category_key` (snapshot, may be null) so subscribers can map a completed treatment to a follow-up policy without importing catalog or treatment_plan models (issue #62). Earned-ledger generation **moved out** of this event since the multi-session feature — see `item_session_completed` below. |
| `treatment_plan.item_session_completed` | one session of a multi-session item marked done | payload: `{plan_id, item_id, session_id, sequence, label, amount, treatment_id, patient_id, completed_by, occurred_at}`. Consumed by `payments` (earned entry, idempotent on `(treatment_id, session_id)`). Fires for every completed session — single-session items publish it once on completion. |
| `treatment_plan.item_session_reopened` | a completed item reopened, when the session that closed it was a completion | payload: `{plan_id, item_id, session_id, treatment_id, patient_id, clinic_id, reopened_by, occurred_at}`. Consumed by `payments`, which drops the earned entry for that session (and any whole-treatment row). The reverse of `item_session_completed`. |
| `treatment_plan.budget_sync_requested` | manual resync | snapshot payload includes full `items[]`. Subscriber: `budget`. |
| `treatment_plan.item_completed_without_note` | completion check | consumed by `patient_timeline` |

Clinical-note created events (`clinical_notes.{administrative,diagnosis,treatment,plan}_created`) live in the `clinical_notes` module.

> All events above are declared in `EventType` and published via the
> constants. ``items_reordered`` used to be a string-only literal —
> it now lives at `EventType.TREATMENT_PLAN_ITEMS_REORDERED`.

## Confirming waits for the informed consent

`TreatmentPlanService.confirm` asks `provider(PlanConsents)` (ADR 0039)
whether the clinic requires a signed informed consent for this plan and
lacks one. If so it raises `InformedConsentRequiredError`, the route
answers `409` with `informed_consent_required`, and the plan stays a
draft. `None` — the Clinical record App off — means nobody asks. What
counts as consent, and whether the clinic asks, is `consents`' business;
do not read its tables or its setting from here.

The same answer is on the plan detail as `informed_consent_missing`, and
it is **only a hard stop at confirmation**. A plan already under way —
confirmed before the clinic asked, or whose letter was revoked — still
has its treatments performed: `PlanDetailView` asks for the letter first
(`awaitingConsent`, item and session completion alike) and lets the
clinician go on; while work is done and the letter is missing, the plan
shows a red alert and each performed treatment a red *Sin carta* badge.
Nothing is stored: sign the letter and both go.

## Events consumed

| Event | Handler | Effect |
|---|---|---|
| `catalog.specialty_enabled` / `_disabled` / `_restored` | `on_specialty_*` | the reference plan templates of a discipline follow it: installed and shown, hidden, or put back to the reference (`PlanTemplateService.seed(specialty=…, restore=…)`, `set_specialty_active`). Templates without a `key` — saved by the clinic — are never touched. |
| `appointment.completed`         | `on_appointment_completed`  | start the plan (`pending` → `active`) for every plan the appointment links to, then mark planned items as performed. The activation query is deliberately wider than the completion loop: it does not require `completed_in_appointment`, because a diagnostic first visit usually ticks nothing off and is exactly the visit that starts the plan. |
| `budget.accepted`               | `on_budget_accepted`        | pending → active (idempotent) |
| `budget.rejected`               | `on_budget_rejected`        | pending → closed (closure_reason=rejected_by_patient) |
| `budget.renegotiated`           | `on_budget_renegotiated`    | pending → draft (budget already cancelled by publisher) |
| `odontogram.treatment.performed` | `on_treatment_performed`   | mark planned item completed when its tooth treatment is performed |

## Lifecycle

- `removable=False`. Plans tie patients ↔ budgets ↔ tooth treatments;
  removing the module would orphan all three.

## Gotchas

- **`confirm` must always adopt the budget it was handed.** `reopen`
  cancels the linked budget but leaves `plan.budget_id` pointing at it.
  `create_from_plan_snapshot` is idempotent only against *non-cancelled*
  budgets, so a re-confirmation mints a fresh draft — and `confirm` has
  to store it. Guarding the assignment on `budget_id is None` (as it did
  until the reopen→re-confirm bug) stranded the plan in `pending` against
  a cancelled budget, which satisfies no bandeja `tab_where`, so the plan
  disappeared from the pipeline while the new budget floated unreferenced.
  Pinned by `test_reconfirm_after_reopen_links_the_fresh_budget`.
  The cascade is worse than the missing link suggests: `budget` finds the
  plan to activate with a reverse lookup on `treatment_plans.budget_id`
  (`BudgetWorkflowService._lookup_plan_id`), so an orphaned budget resolves
  to `plan_id: None`, `on_budget_accepted` takes its "orphan budget" early
  return, and accepting the budget never carries the plan to `active`. The
  budget could not even be *sent* — it was cancelled. Pinned end to end by
  `test_accepting_the_budget_after_a_reopen_still_activates_the_plan`.
- **`en_curso` spans two statuses on purpose.** The leading bandeja tab is
  `p.status IN ('pending', 'active')`. Reception counts a plan as under way
  from the diagnostic visit, which happens before the budget is accepted, so
  a tab keyed to `active` alone would hide exactly the plans they are chasing.
- **Plan → budget direct call is the carve-out.** `confirm()` calls
  `BudgetService.create_from_plan_snapshot` synchronously to keep the
  draft-budget creation transactional with the state transition.
  Allowed because `budget` is in `manifest.depends`. Item-level
  add/remove sync remains event-driven (the snapshot payloads carry
  enough data so `budget` doesn't import treatment_plan).
- **Plan ↔ budget item sync goes through events**, not direct calls.
  Adding a treatment to a plan publishes
  `treatment_plan.treatment_added` with a denormalized snapshot
  (catalog_item_id, tooth, surfaces, unit_price, budget_id); the
  budget module's handler creates the matching budget line.
- **Item completion has two paths**: the user marks an item complete
  here, or the odontogram fires `odontogram.treatment.performed`. Both
  must converge to the same state — keep them idempotent.
- **Sessions are the source of earned signal.** Every plan item now
  owns ≥1 `PlannedTreatmentItemSession` (backfilled by `tp_0006`).
  Per-session completion fires `item_session_completed`; the item
  finalizes (and `treatment_completed` fires) only when every session
  is in a terminal state and at least one is `completed`. Editing a
  completed session is refused — its amount is the snapshot that
  payments already booked.
- **Completion still emits an audit event.** `treatment_plan.item_completed_without_note`
  fires whenever an item is completed; the timeline reconciles it with a
  follow-up `clinical_notes.treatment_created` event when the client
  captured a note. Don't bypass — the event is the only signal that an
  item was completed at all.
- **Don't import `clinical_notes`.** The dependency is one-way:
  `clinical_notes → treatment_plan`. The frontend calls both modules
  during completion; do not add a server-side cross-module import.
- **A template carries treatments, never teeth.** `PlanTemplate` is an
  ordered list of catalog items with a stage of care; the teeth arrive at
  apply time. The apply rule is one sentence on purpose, because a dentist
  has to be able to predict it: **every per-tooth item is created once per
  tooth supplied, whole-mouth items once, and whole-arch items once per arch
  the teeth belong to (both arches when no teeth were given).** A template
  with per-tooth items and no teeth is refused with a 422 that names the
  treatments waiting, so the UI can ask for the right thing.
- **Hand-drawn lines take the template's path, not the item path.**
  `POST /catalog-items` goes through `PlanTemplateService.add_catalog_items`
  → `_create_treatments` → `add_item`, because turning a catalog item into
  planned `Treatment` rows is where all the scope logic lives (one per tooth,
  once per arch, once for the mouth). `POST /items` is the other door and
  takes a `Treatment` that already exists — that is the odontogram's path,
  and it cannot serve a client that only knows a catalog item id. The body is
  a **list of lines**, each with its own teeth: the plan is drawn on a chart,
  so a crown on 16 and a filling on 24 arrive together.
- **The builder arrives holding what the chart already knows.** Reached from a
  record (`/treatments/plans/new?patient_id=`), it calls
  `GET /treatment-plans/patient/{id}/proposals` and turns each suggestion into
  an ordinary draft line. Before this the dentist redrew, tooth by tooth, work
  the clinic had already diagnosed, and only learned what was missed *after*
  saving, from the plan-scoped endpoint. The two endpoints share
  `PlanProposalService.for_patient`, because the finding→treatment mapping is
  clinical judgement and must have one home. Two rules keep it honest: lines
  are never seeded over an examination already in progress, and a finding the
  catalog cannot answer is skipped rather than added as a blank. Deleting a
  seeded line is a judgement, so the builder reports it to
  `POST /treatment-plans/{id}/dismissed-findings` once the plan exists and
  `list_proposals` hides it from then on. **Scoped to the plan**: the chart
  keeps showing the caries and the patient's next plan proposes it again,
  because a decision about one plan must not become a decision to leave a
  tooth alone forever. The call is best-effort — a dismissal that fails to
  record costs one redundant proposal, never the plan. The catalog
  fetch is awaited on this path only — the lines are built from it, and an
  empty catalog would draw them all as untyped fillings with no phase.
- **The create screen has no patient until the end, and that is the point.**
  `/treatments/plans/new` opens on a blank chart (`PlanDraftChart`, which
  shares `ToothQuadrant` with the real chart but fetches nothing) and holds
  the whole plan in client memory until *Crear*, which then creates the
  patient if new, the plan, and every line. Nothing is half-written if the
  screen is abandoned. The cost is that the chart cannot show what the
  patient already has, so the patient step re-reads their odontogram and
  **warns** — a missing tooth comes from `tooth_records.general_condition`,
  not from a treatment, and a check that only read treatments would warn
  about nothing.
- **A template line is either a given or a decision.** `is_optional` marks the
  ones a clinic may not offer or a patient may not need — the orthodontics of
  an orthognathic case, a genioplasty. Optional lines are offered **ticked**
  (the author put them there because they usually apply) and go out through
  `excluded_template_item_ids`. Excluding a *required* line is a 400: a
  template whose required steps can be dropped is not a shape any more.
- **`apply` reports what it left out.** A line whose catalog item the clinic
  never had or has retired is skipped instead of failing the whole
  application, and comes back in `skipped` with `reason="not_in_catalog"`.
  A plan that quietly arrives one treatment short is worse than one that says
  so. This is why `apply` returns `ApplyResult`, not a bare list.
- **`PlanTemplateService.get` uses `populate_existing`.** It is the read that
  runs straight after a write; without it the identity map hands back the
  collection as it was before `_replace_items`, and a PUT answers with the old
  line-up while the database holds the new one.
- **Templates are seeded from `clinic.created`, tolerantly.** The starter set
  lives in `templates_seed.py` and references catalog items by
  `internal_code`. Handler order against `catalog`'s own seeder is not a
  contract, so `PlanTemplateService.seed` skips codes that are not there yet,
  never overwrites a template the clinic edited, and fills in gaps on a
  re-run. `scripts/backfill_plan_templates.py` is the repair and
  existing-clinic path.
- **`_replace_items` writes by statement, not through the relationship.**
  It runs against templates that were just created and never loaded;
  touching `template.items` there triggers a lazy load the async session
  cannot service.
- **Proposals read the chart, they never write to it.** `proposals.py` lists
  findings (`Treatment` rows with a diagnostic `clinical_type`,
  `status='performed'`, no catalog link) that have no planned work on the same
  tooth, and pairs each with a catalog item resolved by `internal_code` from
  the `SUGGESTIONS` table. Accepting one creates a *new* planned Treatment;
  the finding is left alone, because the diagnosis and the plan are separate
  records and the chart should keep showing the caries until it is treated.
  The "already addressed" test is coarse on purpose — any planned treatment on
  that tooth hides the finding. Guessing whether a given plan line answers a
  given finding would be a guess.
- **`SUGGESTIONS` is clinical judgement in a table, so it stays conservative.**
  Where the honest answer depends on how much tooth is left, the least
  invasive option is proposed: upgrading a composite to a crown is a smaller
  correction than the reverse. Nothing is created until the dentist ticks the
  row.
- **The plan shows money it does not own.** `usePlanCollections` calls
  `POST /payments/summary/by-treatments` from the frontend layer — no backend
  import, nothing added to `manifest.depends`. That is the sanctioned
  cross-module read (`docs/technical/payments/cross-module-summaries.md`), the
  same one the budget and patient lists use. One call per plan feeds both the
  per-session chips and the per-phase totals; when it fails (payments not
  installed, or no `payments.record.read`) the plan renders without the money
  column, which is the correct degraded state.
- **A chip only appears once a session is earned.** A pending session is not
  "uncollected" — there is nothing to collect until the work is done, and
  saying otherwise reads as a debt the patient does not have.
- **A plan can start without an appointment ever existing.** Ticking a
  treatment off directly on the plan sets `completed_without_appointment`
  and creates no `appointment_treatments` row, so anything reasoning about
  "did the patient come" from appointments alone misses that path — it is
  how a first consultation often gets recorded.
  `scripts/backfill_started_plans.py` counts either signal and is the
  one-off pass for visits that predate the attendance rule; it is dry-run
  by default. The live path covers both since completion routes through
  `_sync_plan_lifecycle`.
- **A plan item's "closed" is derived, never stored.** Completed **and**
  nothing left to charge (`pending <= 0` from
  `payments/summary/by-treatments`). Storing it would give the ledger a
  second opinion about the same money; deriving it means a refund recorded
  in Finanzas un-closes the treatment with no second write. No `payments`
  read means no badge — "nothing pending" and "we cannot see the money" are
  different claims.
- **"Reabrir tratamiento" is a real undo, and the charge goes with it.**
  `reopen_item` sets the item and its closing session back to `pending`,
  turns the `Treatment` back to `planned` (clearing `performed_at`), moves
  a `completed` plan back to `active`, and publishes
  `item_session_reopened`; `payments.on_session_reopened` deletes the
  earned entry that completion booked. It used to be a presentation
  override that unlocked the dialog and left that entry behind — money the
  patient still appeared to owe for work the plan no longer counted as
  done. The rules:
  - **Only the act that closed the item is undone** — its most recent
    terminal session. On an eight-visit case, ticking the last visit by
    mistake must not wipe the seven that happened. When a cancellation
    closed it, the cancellation is what reverts, and no money moves.
  - **Paid money is never refunded here.** Deleting the entry leaves the
    payment alone; the FIFO walk finds one charge fewer and the money
    becomes patient credit that covers the treatment when it is completed
    for real. A refund is still Finanzas' job.
  - **An event, not a direct call**, unlike the liquidation payout: this
    module does not depend on `payments`, and the charge was booked by an
    event in the first place — reversal takes the same road. The handler
    re-raises so a failure lands in `core_event_failure` (ADR 0020).
  - **Refused on a `closed` plan** — reactivation is that plan's door.
  - An issued settlement in `liquidations` is a frozen snapshot and is not
    touched: work already paid to an associate stays paid.
- **Reopening a plan is narrower than `plans.write`.** It throws away a budget the
  patient may already have seen, so the endpoint also asks `stewards_of`:
  an administrator, or a professional assigned to the plan or to any of its
  items. The account↔professional bridge is the licence number
  (`users.professional_id` ↔ `professionals.license_number`) because
  `Professional` deliberately has no `user_id`; a professional with no
  account resolves to nobody and the plan stays admin-only. Rights are
  derived from the current assignment, so reassignment transfers them with
  no extra bookkeeping. The client never reproduces this rule — it reads
  `permissions` off the history endpoint.
- **Deleting a plan deletes its budgets.** `delete` calls
  `BudgetService.delete_for_plan(plan_number, budget_id)` in the same
  transaction — every budget the plan produced, cancelled and renegotiated
  versions included. It is the only way those budgets are deleted: the
  budget endpoint refuses them. Same direct-call carve-out as
  `confirm`/`reopen`.
- **A plan with money in it can only be closed.** `delete` and
  `close(reason="cancelled_by_clinic")` call `_guard_collections`, which asks
  `payments.LedgerService.plan_has_collections` directly (a precondition, so
  not an event) and raises `PlanHasCollectionsError` → 409
  `PLAN_HAS_COLLECTIONS`. Money counts if it is allocated to any budget the
  plan produced (net of refunds — an anticipo exists before any work) or if
  on-account money covers the plan's treatments in the FIFO walk. Any other
  closure reason still works, which is what the client's message tells the
  user to do. `PUT /status` to `closed` carries no reason and is not guarded.
- **Link to `/treatments/plans/{id}`, never `/treatment-plans/{id}`.** The
  old path survives only as a `routeRules` redirect in this layer's
  `nuxt.config.ts`, for bookmarks. The server substitutes the `**`; the
  client router does not, so an in-app link to the old path lands on
  `/treatments/plans/**` and a plan with id `**`. The summary card did this
  and only a reload rescued it.
- **The plan's status gates its treatments, not its budget.**
  `effectiveReadonly` is now `readonly || status !== 'draft'`: structural
  edits belong to a draft. It used to key off `isLocked` (a live budget),
  which left an `active` plan with no budget fully editable — work under way
  that anyone could rewrite — while a draft that had been reopened was
  frozen. The three doors follow from it, and each offers the transition
  instead of refusing: completing or charging on a draft opens
  `ConfirmPlanModal` (with a `reason` line) and carries the intent out
  afterwards (`pendingItemIntent`); editing or removing on a plan in
  progress opens `ReopenPlanModal`, gated on the server's own
  `permissions.can_reopen` — without it the user gets the error, not a door
  they cannot open. `payments` hides the sidebar's *Cobrar* on a draft,
  reading `ctx.planStatus`; it is the only plan rule that module knows.
- **`onConfirmPlan` calls `completeItemNow`, not `handleCompleteItem`.**
  Right after confirming, this view still holds the pre-confirm props, so
  the gate would bounce the user back into the dialog they just answered.
- **History rows share the caller's transaction.** `record_history` is not a
  coroutine and does not flush: a log line that outlives a rolled-back edit
  describes something that never happened.
- **Auto-close cron lives here** (`tasks.py:auto_close_expired_plans`),
  not in budget — closing a plan is a treatment_plan write and budget
  is in this module's depends, so the read of `budgets` from the
  cron query is allowed.
- **A prescription copies its doctor, not its clinic.**
  `treatment_prescriptions` stores `professional_name` and
  `professional_license` as they were when it was written — the printed
  document is what the patient carried to the pharmacy, and a reprint must
  say the same. The clinic block and the patient's name are read at print
  time. `plan_item_id` is `SET NULL`: removing a treatment hard-deletes the
  line, and the prescription is clinical history (`treatment_label` keeps
  it readable). Exported and retained through `privacy.py` like the plans.
- **The PDF opens in a tab reserved before the request.** `usePrescriptions`
  calls `window.open` synchronously on the tap and fills it once the PDF
  arrives; Safari on iPad drops a popup opened after a network round-trip.
  Headless Chromium has no PDF viewer and downloads it instead, which is
  why no e2e test asserts the tab's URL.

## Related ADRs

- `docs/adr/0001-modular-plugin-architecture.md`
- `docs/adr/0003-event-bus-over-direct-imports.md`
- `docs/adr/0006-budget-public-link-2-factor-auth.md`

## CHANGELOG

See `./CHANGELOG.md`.
