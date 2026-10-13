---
module: agenda
screen: list
route: /appointments
related_endpoints:
  - DELETE /api/v1/agenda/appointments/{appointment_id}
  - DELETE /api/v1/agenda/cabinets/{cabinet_id}
  - GET /api/v1/agenda/appointments
  - GET /api/v1/agenda/appointments/{appointment_id}
  - GET /api/v1/agenda/appointments/{appointment_id}/cabinet-history
  - GET /api/v1/agenda/appointments/{appointment_id}/completion-check
  - GET /api/v1/agenda/appointments/{appointment_id}/transitions
  - GET /api/v1/agenda/cabinets
  - GET /api/v1/agenda/kanban/day
  - PATCH /api/v1/agenda/appointment-treatments/{appointment_treatment_id}
  - PATCH /api/v1/agenda/appointments/{appointment_id}/cabinet
  - POST /api/v1/agenda/appointments
  - POST /api/v1/agenda/appointments/{appointment_id}/transitions
  - POST /api/v1/agenda/cabinets
  - PUT /api/v1/agenda/appointments/{appointment_id}
  - PUT /api/v1/agenda/cabinets/{cabinet_id}
related_permissions:
  - agenda.appointments.read
  - agenda.appointments.write
  - agenda.cabinets.read
  - agenda.cabinets.write
related_paths:
  - backend/app/modules/agenda/frontend/pages/appointments/index.vue
  - backend/app/modules/agenda/router.py
last_verified_commit: 44b3f36
---

# Appointments

The clinic's operational calendar. Browse the week or the day,
create appointments by dragging on free slots, move them between
professionals and rooms, and walk them through their workflow
(scheduled → confirmed → in-room → completed → billed).

## At a glance

- **Four views** — weekly, daily, and kanban on desktop; a simplified
  one-day mobile view on small screens. The view selector lives in
  the header, except on mobile where only the daily view exists.
- **Cabinet and professional filters** — chips above the calendar.
  Appointments with no room assigned are **always** visible so the
  front desk can drag them onto the right room.
- **Drag, resize, and across-day moves** — drag a card to a different
  hour or professional to move it; drag the lower edge to change its
  duration. If it overlaps with another appointment for the same
  professional or room a warning toast appears, but the operation is
  still saved.
- **On a tablet, by finger** — tap an appointment to open it; press and
  hold to **select** it (it lifts and its bottom handle grows), then
  drag to move it or pull the handle to change its duration. Tap a free
  slot to create there: the duration is set in the modal rather than by
  dragging. In kanban, long-press a card and drag it to another column.
- **On a tablet, orientation changes the layout, not the gestures** —
  held upright it opens on the **Day** view (a seven-column week does not
  fit across), the kanban wraps its columns into two rows, and the header
  falls to two lines. Once you pick a view yourself, rotating no longer
  changes it. Rotating never changes how a gesture behaves.
- **Upright, the Day view fits every professional across the screen** —
  the columns narrow to share the width the tablet has, so the whole day
  is in front of you without dragging sideways. A clinic with enough
  professionals that the columns would stop being readable scrolls
  instead; turning the tablet on its side always gives them more room.
- **Date navigation lives in the header** — previous / today / next and
  the date sit next to the title, and step by week or by day depending
  on the active view.
- **Backend conflicts** — if the server rejects a placement (HTTP 409)
  the calendar refreshes and shows an error toast; the appointment
  snaps back to its previous slot.
- **Daily kanban** — appointments group by status (scheduled,
  confirmed, in-room…). Lets the clinical team see at a glance what
  is coming next.

## Create an appointment

> Requires `agenda.appointments.write`.

1. On the weekly or daily view, click or drag on a free slot. On
   kanban or mobile, tap **New appointment** or the floating button.
2. Pick the patient, reason, and duration. The professional and the
   room are pre-selected based on the slot you opened the modal from.
3. **Save**. The `appointment.scheduled` event is published so
   sibling modules (like notifications) can send the confirmation.

### When an app is not enabled

The agenda works even if the clinic runs without Patients,
Professionals or Treatments. In the form, where the picker would be,
you will see the matching notice:

- **"Patients cannot be assigned"** — the appointment is saved with no
  patient. Type a **title** so you can recognise it on the calendar.
- **"Professionals cannot be assigned"** — the appointment is saved with
  nobody assigned and shows in the **Unassigned** column of the day
  view.
- **"Treatments cannot be assigned"** — the appointment is saved with no
  treatments.

Appointments that already had a patient, a professional or treatments
keep them: they stop being shown while the app is off and show again
when it is enabled.

## Move or resize

> Requires `agenda.appointments.write`.

1. Drag the card to a different time, day, or professional to move it.
2. Drag the lower edge to change the duration.
3. If the new position overlaps another appointment with the same
   professional or room you'll see a yellow warning, but the change is
   saved. If the backend rejects it (HTTP 409 for a stricter
   collision), the view refreshes and the card returns to its
   original slot.

## Advance the status

> Requires `agenda.appointments.write`.

1. Open the appointment by clicking on it.
2. In the **Quick actions** panel pick the next available transition:
   *Confirm*, *In-room*, *Complete*, *Cancel*. **Cancel** asks for
   confirmation: it sits next to *Save* in the modal footer, and the
   patient is notified according to your notification settings.
3. When transitioning to **completed** a follow-up modal appears with
   actions contributed by sibling modules (e.g. *Schedule recall*).
   The modal stays hidden when no module contributes to it.

### Completing an appointment without a consent letter

When the clinic requires informed consent for its plans and the
appointment works on a plan with no signed letter, **Complete
appointment** asks first: *Write the letter* opens the patient's consents
for that plan, and *Complete without the letter* goes on. The rule comes
switched off; it is switched on in *Settings → Clinic → Consent
templates*.

## Permissions

| What you see / can do | Permission |
|-----------------------|------------|
| View the calendar, open appointments, see room history | `agenda.appointments.read` |
| Create, move, resize, cancel, transition | `agenda.appointments.write` |
| See clinic rooms (filter chips) | `agenda.cabinets.read` |
| Edit a visit's clinical note | `clinical_notes.notes.write` |

## Troubleshooting

- **"New appointment" button is missing.** Your role lacks
  `agenda.appointments.write`.
- **No professionals show up in the filter.** There are no active dentists
  or hygienists in the Professionals directory. Create or activate their
  profile under *Professionals*.
- **A moved appointment snaps back.** The backend rejected the change
  with HTTP 409 (typically because the professional or room already
  has another appointment in that slot). Check the error toast and
  try a different time.
- **The calendar only runs 08:00–21:00.** The `schedules` module is
  not installed or has no schedule configured; the agenda falls back
  to its default window.
- **An appointment's time is always the clinic's.** It does not change
  because you opened the app from another country or with your laptop in
  another timezone: a 17:30 appointment reads 17:30 on the calendar, on the
  kanban and on the patient record. Seeing the same appointment at two
  different times on two screens is a bug — report it.
