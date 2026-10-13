---
module: treatment_plan
screen: treatments_plans_id
route: /treatments/plans/[id]
related_endpoints:
  - DELETE /api/v1/treatment_plan/treatment-plans/{plan_id}
  - DELETE /api/v1/treatment_plan/treatment-plans/{plan_id}/items/{item_id}
  - GET /api/v1/treatment_plan/treatment-plans
  - GET /api/v1/treatment_plan/treatment-plans/patient/{patient_id}
  - GET /api/v1/treatment_plan/treatment-plans/pipeline
  - GET /api/v1/treatment_plan/treatment-plans/{plan_id}
  - PATCH /api/v1/treatment_plan/treatment-plans/{plan_id}/items/reorder
  - PATCH /api/v1/treatment_plan/treatment-plans/{plan_id}/items/{item_id}/complete
  - PATCH /api/v1/treatment_plan/treatment-plans/{plan_id}/items/{item_id}/reopen
  - PATCH /api/v1/treatment_plan/treatment-plans/{plan_id}/status
  - POST /api/v1/treatment_plan/treatment-plans
  - POST /api/v1/budget/plans/{plan_id}/addendum
  - POST /api/v1/treatment_plan/treatment-plans/{plan_id}/close
  - POST /api/v1/treatment_plan/treatment-plans/{plan_id}/apply-template
  - GET /api/v1/treatment_plan/treatment-plans/{plan_id}/proposals
  - POST /api/v1/treatment_plan/treatment-plans/{plan_id}/proposals
  - POST /api/v1/treatment_plan/treatment-plans/{plan_id}/confirm
  - POST /api/v1/treatment_plan/treatment-plans/{plan_id}/contact-log
  - POST /api/v1/budget/plans/{plan_id}/budget
  - POST /api/v1/treatment_plan/treatment-plans/{plan_id}/items
  - POST /api/v1/treatment_plan/treatment-plans/{plan_id}/link-budget
  - POST /api/v1/treatment_plan/treatment-plans/{plan_id}/reactivate
  - POST /api/v1/treatment_plan/treatment-plans/{plan_id}/reopen
  - POST /api/v1/treatment_plan/treatment-plans/{plan_id}/sync-budget
  - PUT /api/v1/treatment_plan/treatment-plans/{plan_id}
  - PUT /api/v1/treatment_plan/treatment-plans/{plan_id}/items/{item_id}
  - GET /api/v1/treatment_plan/treatment-plans/{plan_id}/items/{item_id}/prescriptions
  - POST /api/v1/treatment_plan/treatment-plans/{plan_id}/items/{item_id}/prescriptions
  - GET /api/v1/treatment_plan/prescriptions/{prescription_id}/pdf
related_permissions:
  - treatment_plan.plans.read
  - treatment_plan.plans.write
  - treatment_plan.plans.confirm
  - treatment_plan.plans.close
  - treatment_plan.plans.reactivate
  - treatment_plan.prescriptions.read
  - treatment_plan.prescriptions.write
related_paths:
  - backend/app/modules/treatment_plan/frontend/pages/treatments/plans/[id].vue
  - backend/app/modules/treatment_plan/frontend/components/clinical/PlanDetailView.vue
  - backend/app/modules/treatment_plan/frontend/components/clinical/PlanNextActionBar.vue
  - backend/app/modules/treatment_plan/frontend/components/clinical/PlanTreatmentList.vue
  - backend/app/modules/treatment_plan/frontend/components/clinical/modals/PlanItemDetailModal.vue
  - backend/app/modules/treatment_plan/frontend/components/clinical/modals/PlanItemPrescriptionModal.vue
  - backend/app/modules/treatment_plan/prescriptions.py
  - backend/app/modules/treatment_plan/proposals.py
  - backend/app/modules/treatment_plan/router.py
last_verified_commit: f9ad75a
---

# Treatment plan detail

Plan view: header with patient, professional, and status; main
column with the items (catalog or odontogram tooth treatment); and
sidebar with the linked budget, executions, and contacts. This is
where you confirm, sync with the budget, mark items as performed,
and close or reactivate.

## Building the plan

There are three ways to get treatments into a draft plan, and they
combine:

- **Apply template.** Brings in a whole plan shape (see
  [New plan](./treatments_plans_new.md)). It can be applied more than
  once, so a plan can be hygiene phase + single implant. The dialog
  carries a search box that filters templates by name and by the
  treatments they contain; it does not offer individual treatments
  here, because the chart already does that. Templates are **grouped
  by specialty**; the ones the clinic saved from its own plans come
  first, under *The clinic's own*. Only those of enabled specialties
  are shown.
- **Propose from the chart.** The button appears with a count when the
  patient has findings charted that nothing is planned for. The list
  pairs each finding with the matching treatment — caries →
  composite, pulpitis on a molar → molar endodontics — and **Add**
  brings them all in. The finding stays on the chart: the diagnosis
  and the plan are separate things, and the caries is still there
  until it is treated. Untick a row whose suggestion does not fit and
  add that one by hand from the bar.
- **Treatment bar.** Pick the treatment and click the tooth. The
  treatment **stays armed** after each application, so 16, 26 and 36
  are three clicks, not three searches. The badge in the header says
  what is armed; the ✕ or `Esc` releases it. For a whole quadrant,
  use the **Quadrant 1–4** buttons next to the badge: they confirm,
  naming the teeth, before creating anything.

The plan list is grouped by **stage of care**: emergency,
stabilisation, rehabilitation, maintenance. Each item's stage comes
from the catalog. Dragging reorders within a stage; to move something
to another stage, change the treatment's stage.

**Save as template** lives in the **···** menu: treatments and their
stages are saved, teeth and prices are not.

## Payment schedule

The **Payment schedule** card records what was agreed to be paid, and
when — a different question from "what is owed for work already done",
which the collections card answers. On a big case the money is agreed
up front, so one reading zero while the other is on track is normal.
**They are never added together**: both settle against the same
payments.

**Agree a schedule** offers three splits of the plan total: by phase
(each phase at its own price), 30/40/30, and monthly. From there every
instalment carries its own **label**, **date** and **amount**, all three
editable — the split only writes the first draft. That is how you agree
something like "5,000 on signing and the rest over six months": pick the
monthly split with seven instalments and adjust the amounts.

The instalments must add up to the plan total; until they do, the notice
says what they add up to and the save button will not continue. The date may be left blank: a
milestone like "before surgery" has no date until surgery is booked,
and without one it never shows as overdue.

Instalments are covered in order by what the patient pays, and each
shows **Pending**, **Partial**, **Paid** or **Overdue**.

**Edit** (the pencil) opens the schedule as it was agreed, not a fresh
split. Any row can be removed, or another added directly below it —
which is what you need to halve an instalment the patient cannot manage.
It can be renegotiated after money has been collected: what was paid
re-covers the new instalments in order.

Cancelling a schedule does not erase it: a superseded agreement is part
of what happened.

## At a glance

- **Status chip.** The header chip reflects the state: `draft`,
  `pending`, `active`, `completed`, `closed`. Actions change with
  the state.
- **Items** — add, reorder, complete. Each item references a
  catalog item and, optionally, an odontogram tooth treatment.
  Completing an item publishes
  `treatment_plan.treatment_completed` (with
  `treatment_category_key` for recalls).
- **Doctor per treatment.** Every item carries its own
  `assigned_professional_id`. New items inherit the plan's doctor.
  Click the coloured chip next to the item name to assign a
  different professional (e.g. filling by Dr A, endodontics by
  Dr B). When two or more doctors are involved in the plan, the
  chip colours make the mix visible at a glance. The chip stays
  editable while the item is pending, even after the plan is
  validated and the budget is active — reassignment is operational
  and does not change the patient-facing contract. Once an item is
  marked as completed, the chip becomes a read-only indicator and
  keeps showing `assigned_professional_id` (the clinician
  responsible for the treatment); completion can be triggered by
  reception or an admin on behalf of the clinician, so "who clicked
  Complete" is intentionally not the chart's reference.
- **Linked budget.** **Generate budget** / **Link to existing
  budget** / **Sync** buttons as needed. The plan publishes
  `treatment_plan.treatment_added / _removed /
  budget_sync_requested` so `budget` keeps the budget up to date.
- **Contacts** — front-desk touchpoint history. Useful when the
  plan is *pending* awaiting acceptance.
- **Clinical notes.** Can be attached to the plan from the
  `clinical_notes` module (slot `patient.detail.clinical.notes`).
- **The treatment's own dialog.** Tap a treatment's box and it opens:
  professional, price, teeth, sessions and where its money stands
  (earned, collected, outstanding). Its footer holds same-sized blue
  buttons: **Añadir nota** (or **Notas (n)** once it has some),
  **Programar recordatorio**, **Cobrar** (only while something is
  outstanding) and **Receta médica**; the last cell is **Marcar como
  completado** in green, or **Reabrir tratamiento** once it is done. The row keeps only what changes the
  plan (complete, remove), which is what stops "open something" and
  "change the plan" sitting a finger apart.

## What happens next

Under the title, a bar names **the one thing** that moves the plan on,
and carries the button that does it. It exists because a plan changes
hands three times — the dentist plans it, the patient accepts the budget,
reception books the chair — and the handover was invisible: confirmed
plans sat still with the budget unsent, nobody aware it was theirs.

| The bar says… | Because… | And the button goes to… |
|---|---|---|
| **Add the treatments** | the draft is empty | — (the chart, or a template) |
| **Confirm the plan** | it has treatments and is still a draft | *Confirmar plan* |
| **Generate the budget** | the plan moved on without one | *Generar presupuesto* |
| **Send the budget to the patient** | it exists but has not been sent | the budget |
| **Waiting on the patient** | it is sent; their turn | the budget |
| **The budget expired / was rejected / is cancelled** | it needs renewing or renegotiating | the budget |
| **N treatments without a price** | they were added after confirmation | *Price the addition* |
| **Book the first / the next appointment** | treatments remain and no future visit | *Programar cita* |
| **Next appointment: …** | all set | — |
| **Every treatment is done** | only collecting and closing are left | — |

Always **one**: a list of everything outstanding is a report, and the
report is exactly what nobody read. On a completed or closed plan the bar
is absent. It renders in the patient record too, buttons and all; someone
without write access to the record sees the sentence without them.

Colour says whose turn it is: blue, yours; amber, something went wrong;
green or grey, nothing to do.

## Confirm a plan

> Requires `treatment_plan.plans.confirm`.

1. On a `draft` plan, click **Confirm**.
2. The plan moves to `pending` and the Budgets app creates its draft
   budget right away.
3. If the budget did not get created, the plan's next step is
   **Generate budget**, which creates it.

**If the clinic requires informed consent** (Clinical record App, on by
default), the plan is not confirmed until the patient signs an informed
consent letter written for that plan. Clicking *Confirm* shows the notice
*The informed consent is missing* with the **Write the letter** button,
which leads to the patient's consents: the letter written there is filed
for the plan and, once signed, *Back to the plan* returns to confirm it.
The rule is switched off under *Settings → Clinical → Consent templates*.

**Marking a treatment as performed without the letter.** On a plan already
under way that lacks the letter (confirmed before it was required, or the
patient revoked it), marking a treatment as performed asks first: **Write
the letter** or **Mark as performed without the letter**. Going on without
it, the plan shows in red *The informed consent letter is missing* and
each performed treatment the *No letter* mark, until the letter is signed.

**If the Budgets app is not enabled**, a confirmed plan goes straight to
*In treatment*: there is no budget to accept and the budget actions are
not offered. Once the app is enabled the plan offers **Generate budget**.

## What a treatment offers, by plan status

It depends on where the plan is, not on whether it has a budget:

| The plan is… | On a treatment you can… |
|---|---|
| **Draft** | Edit and **remove** it (from its dialog or the row's trash). Completing or charging **asks to confirm the plan** first. |
| **In progress** (pending or active) | **Complete**, **charge** and **add** new treatments. Editing or removing one already accepted **asks to reopen the plan**. |
| Completed or closed | Read it; reactivating the plan is the way back. |

- **Charging or completing on a draft** opens *Confirmar plan* with the
  reason written on it: "to complete or charge a treatment, the whole plan
  has to be confirmed first". **Confirm** and the plan moves to *Awaiting
  acceptance*, its draft budget is produced, and what you asked for is
  carried out.
  **Cancel** and the plan stays a draft, untouched.
- **Editing or removing on a plan in progress** opens *Reabrir plan para
  editar*, which warns that **the current budget will be cancelled**.
  Reopening puts the plan back to draft, to be confirmed again.
- Reopening is for an administrator or the professional the case is
  assigned to. Anyone else sees "you do not have permission to reopen this
  plan" and the plan does not move.
- Under the *what happens next* bar, a grey note recalls that **a confirmed
  plan's treatments are no longer edited there** and what changing them
  costs (reopening cancels the budget). It follows the plan's **status**,
  not whether a budget exists: an active plan with no budget is settled too
  and used to say nothing. On a finished plan it reads *Plan terminado*, and only a closed one is
  pointed at reactivating, since that is the only one with the button.
  Grey on purpose: this is where a plan spends most of its life, and an
  amber warning that is right every day stops being read.
- Notes, recalls and prescriptions work in either state: they are clinical
  acts, not changes to the plan.
- The **Cobros de este plan** card offers no *Cobrar* while the plan is a
  draft; it says what is missing.

### This plan's charges

The card carries four figures, and every one of them is **this plan's**:

- **To charge for this plan**, large and on top: the only one that calls
  for an action.
- **Planned**: what the whole plan is worth.
- **Performed**: the part actually carried out, which is what may be
  charged. A 19,020 plan with 120 performed can charge 120.
- **Collected**: how much of that is in.

Below, and **only when it adds something**, a line gives what the patient
owes *in total*, across every plan. It can exceed the plan's own: a
patient owes what they owe across the practice, and reading one figure as
the other is how the wrong amount gets asked for.

While nothing has been performed, the card states the rule: *it becomes
chargeable as you complete treatments*. That sentence answers the
question a 0 on a plan worth thousands otherwise raises.

### Adding to a plan in progress

Finding a second caries halfway through a plan is ordinary, and it used to
be expensive: you had to reopen the plan, which **cancelled the budget the
patient had already signed**, confirm it again and have them accept it all
over.

**Adding is now allowed while the plan is in progress.** It changes none of
the lines the patient agreed to, so their budget is left alone.

1. Tap the tooth on the chart. The plan is confirmed, so the chart is
   read-only and answers with a notice — and on it, **Añadir tratamiento en
   el {tooth}**.
2. The builder's own search panel opens, already fixed on that tooth. Pick
   the treatment and it joins the plan.
3. The bar at the top turns into **"N treatments without a price"**, with
   **Price the addition**.
4. That produces a **separate budget** holding only the new work, in draft,
   which the patient accepts on its own. The signed one is untouched, and
   both hang off the plan.

None of this is needed while the plan's budget is still a **draft**: what
you add joins it by itself, because nobody has been shown a figure yet.

**Editing or removing** a treatment already accepted still asks to reopen
the plan. That is the difference: adding takes nothing away from the
patient, changing a price or dropping a line does.

## Mark items as performed

> Requires `treatment_plan.plans.write` and a plan **in progress**.

1. On the item, click the ✓ on the row or **Mark as completed** inside
   its dialog.
2. `treatment_plan.treatment_completed` is published. `recalls` can
   suggest a follow-up recall based on `treatment_category_key`.
3. The app then asks **whether to charge now or leave it pending**.
   It is the cheapest moment to charge — the patient is still in the
   chair — but leaving it pending is as real an answer: a clinic that
   bills monthly does it every day, and the amount stays in "pending
   to charge" either way.
4. To record a clinical note, open it from the treatment's dialog
   (**Añadir nota**, contributed by `clinical_notes`).

**Removing an item from the plan** (the trash icon on the row) asks
for confirmation: it cascades into the odontogram treatment and the
associated budget line.

## Prescription

> Writing one requires `treatment_plan.prescriptions.write` (admin and
> dentist). Seeing and reprinting them, `treatment_plan.prescriptions.read`
> (also hygienist, assistant and reception).

1. In the treatment's dialog tap **Receta médica**.
2. **Doctor que firma** starts on the professional assigned to the
   treatment; pick another from the directory if needed. Their
   **professional licence** (cédula) shows underneath, or a warning when
   none is on file (the prescription would print without it — fill it in
   from the *Profesionales* menu).
3. Type the **instructions**: medication, dose, frequency, duration.
4. Tap **Generar receta**. A tab opens with a print-ready PDF: clinic
   details (name, address, phone, email), the doctor's name and licence,
   patient, age, date, treatment, the instructions and a signature line.

The prescription **is kept** on the record and listed under *Recetas
anteriores* with a **Imprimir** button. The doctor's name and licence are
copied when it is generated, so a reprint still says what the patient
took to the pharmacy even if the directory changes. Removing the
treatment from the plan does not delete it.

## A closed treatment, and how to reopen it

A treatment reads as **Cerrado** when it is completed **and** there is
nothing left to charge for it. It is not a stored state: it is derived
from the money, so it cannot drift from the ledger. The
**prescription** stays available on a closed treatment.

If a treatment was marked done by mistake — closed, or still with money
outstanding — open it and press **Reopen treatment**. The dialog says
what will happen first; once you confirm with **Yes, reopen**:

- The treatment **goes back to pending** and no longer counts as done,
  on the chart too.
- **Its charge is withdrawn.** It no longer shows as outstanding, on the
  plan or on the patient's account.
- **What was already paid is not refunded.** It stays as the patient's
  credit and covers the treatment once you complete it for real. Giving
  the money back is a refund, recorded in Finanzas.
- If the plan was **completed**, it goes back to **Active**,
  because it now has work outstanding.
- On a **multi-session** treatment only the last completed session is
  reopened; earlier ones stay done and charged.
- The **plan history** records it as *Treatment reopened*.

A treatment on a **closed** plan cannot be reopened: reactivate the plan
first.

## Multi-session treatments

Some catalog items (e.g. crown, root canal) carry a **session
template** with a label and price per step. When the treatment is
added to a plan, one session is created per step.

- The item header shows an **X/Y sessions** progress chip.
- Below the item, the session list renders one row per session (✓
  icon when completed, dashed circle when pending).
- Click the check on a pending session to mark it done — publishes
  `treatment_plan.item_session_completed`; `payments` records an
  "earned" entry for that amount.
- The item is finalized automatically when the last pending session
  is completed (the legacy completion flow runs at that point).
- Cancel a session if it was not delivered — no earned entry is
  generated.

## Change the plan's doctor

> Requires `treatment_plan.plans.write`.

1. Open **Edit plan** and pick a new professional.
2. If there are pending items still assigned to the previous
   doctor, a confirmation appears: *"Reassign pending treatments?"*.
3. Choose **Yes, reassign pending** to push all matching pending
   items onto the new doctor in the same save. Items with an
   explicit override (different doctor) and completed items are
   never touched.
4. Choose **No, keep as they are** to update only the plan-level
   doctor; the items stay where they were.

## Close or reactivate

> Closing requires `treatment_plan.plans.close`. Reactivating
> requires `treatment_plan.plans.reactivate`.

1. **Close** — pick reason: rejected, expired, cancelled,
   abandoned, or *other*. Publishes `treatment_plan.closed` with
   `closure_reason`.
2. **Reactivate** — back to `draft`. Publishes
   `treatment_plan.reactivated`.

**A plan with payments can only be closed.** Once the patient has paid
anything into this plan — to its budget, or money on account that covers
treatments already done — the plan **cannot be cancelled** (*Cancel plan*
with the *Cancelled by clinic* reason) **or deleted**. The screen shows
*“Error, hay algún cobro en el plan de tratamiento. Favor de cerrar este
plan de tratamiento”* and the dialog stays open: pick another reason (for
example *Patient abandoned* or *Other reason*) and press **Close plan**. A fully
refunded payment no longer counts.

## Permissions

| What you see / can do | Permission |
|-----------------------|------------|
| View detail, items, and contacts | `treatment_plan.plans.read` |
| Add/reorder items, complete them, log contacts | `treatment_plan.plans.write` |
| Confirm (draft → pending) | `treatment_plan.plans.confirm` |
| Close | `treatment_plan.plans.close` |
| Reactivate | `treatment_plan.plans.reactivate` |
| See and reprint prescriptions | `treatment_plan.prescriptions.read` |
| Write a prescription | `treatment_plan.prescriptions.write` |

## Troubleshooting

- **Confirmed the plan but no budget appears.** Click **Generate
  budget** or **Link to existing budget**. Confirming does not
  auto-create a budget unless you use *Generate* afterwards.
- **Patient accepted the budget but the plan is still pending.**
  Check that `budget.accepted` is flowing (the `budget` module must
  be installed and the budget actually accepted). The
  `on_budget_accepted` handler moves it to *active*.
- **Cannot delete an item.** The item is already marked as done.
  Completed items remain as history.
- **Cannot complete an item.** Your role lacks
  `treatment_plan.plans.write`.
- **Clicking a tooth does nothing.** The plan is under way: the
  odontogram stays **read-only** while a live budget is attached. The
  click now raises a notice carrying a **Reopen** button, which sends
  the plan back to draft and cancels that budget — the same button as
  the header, and it asks for confirmation first. When the notice
  offers no button it is because reopening belongs to an administrator
  or a professional assigned to the case, or because the plan is
  already completed or closed.
