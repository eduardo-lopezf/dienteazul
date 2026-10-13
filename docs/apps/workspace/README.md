# Espacio de trabajo (`workspace`)

- **Tier:** base  ·  **Version:** 0.1
- **Declared in:** `backend/apps.json`  ·  **Composition and requirements:** [Apps catalog](../../apps-catalog.md)

## What it is for

The App every workspace runs on: the clinic, its users, roles and permissions, sign-in, the shell (menu, home page and its widgets) and Settings. It is the core (`backend/app/core/`) and the host frontend (`frontend/app/`), not a group of modules.

## Modules

None. The core and the host frontend.

## With this App off

It cannot be switched off: the catalog loader refuses a base App that is `disabled`.

## Notes

- Settings → Apps → Espacio de trabajo is its own page. Its first section, *Inicio*, chooses which widgets the home page shows and in what order, per clinic (`clinic.settings.home_layout`).
- It hosts what the other Apps contribute: menu entries, home widgets, settings pages.

## Decisions

- [0043](../../adr/0043-the-workspace-is-the-base-app.md)
- [0041](../../adr/0041-a-screen-hosts-other-apps-through-slots.md)

## Letterheads

*Settings → General → Letterheads* (`/settings/general/letterheads`), and
each professional's own under *Settings → Account → My letterhead*. They
belong to the Workspace, not to the Clinical record: a letterhead heads
every App's printed documents ([ADR 0046](../../adr/0046-the-letterhead-belongs-to-the-clinic.md)),
so it stays editable whichever optional App is off.

What heads **everything the clinic prints**: the record, the consent
letters and the blank health questionnaire.

- **Clinic**: the default letterhead.
- **One per professional**: under *Own letterhead for* choose the
  professional and press *Add*; the card appears with their name and
  licence already offered as the extra line.

Each card has:

- **Logo**: a PNG or JPG of up to 512 KB. Saved the moment it is chosen.
- **Heading**: left empty, it is the clinic's name.
- **Extra line**: free text — the professional and their licence, a
  speciality.
- **Show address** and **Show phone and email**: the clinic's own details;
  here you only decide whether they appear.
- Its own **Save** button, and *Remove letterhead*.

#### Which letterhead each document carries

It is not chosen when printing; the system decides:

- **Consent letter**: that of the professional who explained it.
- **Record** and **blank questionnaire**: that of the professional who
  prints or hands it over.
- If that professional has no letterhead of their own, or whoever prints
  is not one of the clinic's professionals, the clinic's is used.
- **Another doctor's letterhead is never used.**

From this page they are managed by whoever may change the clinic's
details. In addition, **each professional can set up their own** under
*Settings → Account → My letterhead*, without being able to touch the
clinic's or a colleague's. Their account has to be linked to their
professional profile for that.

## Record regulation

*Settings → General → Record regulation* (`/settings/general/record-regulation`):
the standard the clinic's clinical record refers to, as one line of text.

- **It is the clinic's.** The product offers the standard it knows for the
  clinic's country (Mexico: *NOM-004-SSA3-2012, Del expediente clínico*)
  until the clinic writes its own; an empty line shows none.
- **Where it shows:** the health questionnaire — at the foot of the form
  on screen and above the patient's signature on the blank sheet — the
  *Expediente* tab, and the printed record.
- **It is a reference, not a certificate.** Naming a standard does not
  state that the record meets it; that reading is the clinic's and its
  counsel's.
- It lives in the Workspace (`app.core.regulation`,
  `GET/PUT /api/v1/auth/clinic/settings/record-regulation`) because two
  Apps print it, and Patients must show it with the Clinical record off.
