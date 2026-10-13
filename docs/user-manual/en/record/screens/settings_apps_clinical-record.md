---
module: record
screen: settings_apps_clinical-record
route: /settings/apps/clinical-record
related_endpoints:
  - GET /api/v1/record/format
  - PUT /api/v1/record/format
related_permissions:
  - record.read
  - record.configure
  - admin.clinic.read
  - admin.clinic.write
related_paths:
  - backend/app/modules/record/frontend/pages/settings/apps/clinical-record.vue
last_verified_commit: f9ad75a
---

# Clinical record settings

**Settings → Apps → Clinical record → Configure.** How the clinical record
is put together in this clinic. What is chosen here applies to the whole
clinic, on every patient's *Record* tab and on the document that is printed
or handed over.

## Permissions

- `record.read` — see the format.
- `record.configure` — change it (admin only).

## Letterheads

The documents' letterhead is no longer set up here: it is under
**Settings → General → Letterheads**, because it heads every App's
documents and must stay editable with the Clinical record disabled. Each
professional still has their own under *Settings → Account → My
letterhead*.

## Sections and order

Each section of the record has a switch and arrows to move it up or down.

- **Turning a section off** removes it from the *Record* tab and from what
  can be printed or handed over. **It deletes nothing**: the data stays
  where it is written, and turning it back on brings it back.
- **The order** is the one the record follows on screen and on paper.
- A section added by an App enabled later appears at the end.

## What the record should hold

The points the *Record* tab reviews for each patient. Turn off the ones
that do not apply to your clinic; they stop showing as pending.

## Consent templates

A shortcut to the texts of the consent letters.

## Saving and restoring

Nothing changes until **Save** is pressed. **Reset** returns to the default
format — every section, in the order of a paper record, every point
reviewed — and has to be saved too.
