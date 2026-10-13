# Glossary

Source of truth for Diente Azul terminology. Code is in English; UI strings
are in Spanish (i18n). When the same concept has both forms, list both.

When you introduce a new domain term in code or UI, append it here. Keep
definitions to one or two sentences — link to deeper docs (`docs/`,
ADRs) for the full story.

## Clinical

| EN (code) | ES (UI) | Definition |
|---|---|---|
| Workspace (base App) | Espacio de trabajo | The App every workspace runs on: the clinic, its users and permissions, the shell with its home page and widgets, settings. Declared in `apps.json` with tier `base`, no modules, never disabled (ADR 0043). Not the Settings category once called the same, now "Clínica y horarios". |
| Core App | App core | An App every workspace is set up with (tier `core`): Agenda, Patients, Recalls, Treatments. |
| Informed consent | Consentimiento informado | The letter in which a named professional explains a procedure, its risks and alternatives, and the patient accepts or declines (LGS Art. 51 Bis 1, NOM-004). Module `consents`, kind `informed`. Not a signed budget. |
| Family history | Antecedentes heredo-familiares | Conditions that run in the patient's family, each with the relative it concerns. `patients_clinical_family_history`; part of the medical history form and of the composed record. |
| Prognosis | Pronóstico | How the professional expects a plan to go: `favorable`, `reserved` (*reservado*) or `unfavorable`, with a reason. On the treatment plan, next to its diagnosis. Not the per-tooth periodontal prognosis. |
| Record coverage | Qué debe tener el expediente | The check of what a dental record is expected to hold against one patient's record (`record/coverage.py`). An engineering reading of NOM-004, pending legal review. |
| Disclosure | Entrega del expediente | One handing-over of a patient's record: recipient, purpose, evidence, the sections included and the document as it left, with its digest. Table `record_disclosure`; itself an entry of the record. Never edited or deleted (ADR 0033). |
| Health questionnaire | Cuestionario de salud | What a patient declares at a visit — chief complaint, yes/no questions with their cause, conditions ticked — kept as given, on screen or as a scanned sheet. `patients_clinical_health_questionnaire`. A dated declaration, not the curated medical history. |
| Chief complaint | Motivo de consulta | Why the patient came, in their words. A field of the health questionnaire. |
| Vital signs | Signos vitales | Blood pressure, heart and respiratory rate, temperature, taken at a visit and kept on the clinical note about it (`clinical_notes.vitals`). |
| Agreement with the treatment | Conformidad con el tratamiento | A letter the patient signs when a treatment is concluded to their satisfaction. Module `consents`, kind `conformity`. Not a consent, and says nothing about money. |
| Reference regulation | Normativa de referencia | The standard a clinic's clinical record names (in Mexico, NOM-004-SSA3-2012). One line of text the clinic sets; shown on the health questionnaire and on the record. A reference, not a statement of compliance. |
| ASA class | Clasificación ASA | The patient's physical status on the ASA scale (I–IV here — V and VI are not offered — `E` for an emergency procedure), as a clinician judged it on a given day. An appended assessment, never a field of the profile; the newest not retracted is the current one. |
| Specialty pack | Especialidad (paquete de referencia) | A discipline's reference catalogue — treatments and plan templates — that a clinic enables, edits and can restore (ADR 0047). Not an App: data, per clinic, inside Treatments. |
| Sub-area | Subárea | A grouping of a discipline's reference treatments for reading (orthodontics: fixed appliances, aligners, retention…). Belongs to the reference, not to the clinic's catalogue; not a sub-specialty and not something a clinic enables. |
| Reference catalogue | Catálogo de referencia | The treatments a specialty pack ships with, held as data, one JSON file per discipline (`catalog/reference/`, ADR 0048). A starting point a clinic copies and edits; its prices are placeholders. |
| Data-use consent | Consentimiento de uso de datos | The patient's consent to the clinic processing their personal data, against the privacy notice shown. Module `consents`, kind `data_use`. |
| Patient | Paciente | A person registered in the clinic. Soft-deleted via `status`, never hard-deleted. |
| Appointment | Cita | A scheduled visit. Has a state machine (`scheduled → confirmed → checked_in → in_treatment → completed`/`no_show`/`cancelled`). |
| Treatment | Tratamiento | A clinical procedure performed on a patient (often tied to a tooth/surface). |
| Treatment plan | Plan de tratamiento | Bundle of proposed treatments with status, used to drive budgets. |
| Odontogram | Odontograma | The per-patient tooth chart. Tracks conditions and treatments per tooth/surface. |
| Tooth | Diente | Identified by FDI numbering (11–48 permanent, 51–85 deciduous). |
| Surface | Cara/superficie | A face of a tooth (mesial/distal/occlusal/lingual/vestibular). |
| Visit note | Nota de visita | Free-text note attached to an `AppointmentTreatment`. |
| Clinical note | Nota clínica | Free-text note in the `clinical_notes` module. Polymorphic over four `note_type` values (administrative, diagnosis, treatment, treatment_plan). |
| Administrative note | Nota administrativa | Receptionist / admin note attached to a patient with no clinical context (e.g. "called complaining of tooth pain", "rescheduled to next week"). |
| Diagnosis note | Nota de diagnóstico | Note taken during a diagnosis session, optionally tied to a specific tooth. |
| Treatment note | Nota de tratamiento | Note attached to a `Treatment` row (odontogram). Travels with the treatment from diagnosis through plan and completion. |
| Clinical record | Expediente clínico | The whole of a patient's clinical documentation, composed by the `record` module out of the modules that own each part. Not a table: the record is a *view*, and a copy of it would drift from the source. |
| Record section | Sección del expediente | One module's part of a clinical record — allergies, evolution notes, charting. A module declares its own through `get_record_sections()`. |
| Record entry | Entrada del expediente | One dated, attributed clinical fact inside a section. Carries clinical time (when it happened, not when it was typed), its lifecycle state and the professional responsible. |
| Retracted entry | Entrada retractada | An entry that should never have been recorded — wrong patient, a mistaken tap. It stops driving alerts and leaves disclosures, and is never deleted: what the chart said that day stays answerable. Distinct from an *ended* entry, which was true and stopped being true. |
| Disclosure | Divulgación | A record, or part of one, leaving the clinic — to a colleague, an insurer, the patient. Requires a recorded authorisation (ADR 0033). |
| Patient summary | Ficha resumen | Default landing tab on the patient record. Shows the patient header plus the recent-clinical-notes feed across every type. |
| Hygienist | Higienista | Role with read-only patient access + full appointment access. |
| Dentist | Dentista | Role with full clinical access. |
| Assistant | Asistente | Operative role; full patient + appointment access, no clinical writes. |
| Receptionist | Recepcionista | Front-desk role; patients + appointments. |

## Imaging (issue #55)

| EN (code) | ES (UI) | Definition |
|---|---|---|
| Document | Documento | Any patient file in the `media` module — PDFs, photos, X-rays. |
| Media kind | Tipo de medio | Top-level Document classification (`photo` / `xray` / `document` / `scan` / `video`). Drives the gallery vs document-list UI. |
| Media category | Categoría | Photo / X-ray bucket — `intraoral`, `extraoral`, `xray`, `clinical`, `other`. |
| Media subtype | Subtipo | Leaf taxonomy node — `frontal`, `panoramic`, `before`, etc. See `media/photo_taxonomy.py`. |
| Intraoral | Intraoral | Photos taken inside the mouth — frontal / lateral / occlusal / palatal / lingual. |
| Extraoral | Extraoral | Photos of the face — profile, smile, three-quarter, frontal_face, rest. |
| Occlusal | Oclusal | Bite-surface intraoral view (`occlusal_upper` / `occlusal_lower`). |
| Panoramic | Panorámica | Panoramic dental X-ray. |
| Periapical | Periapical | Per-tooth X-ray covering the root and surrounding bone. |
| Bitewing | Bitewing / Aleta de mordida | Inter-proximal X-ray showing crowns + alveolar crests. |
| Cephalometric | Cefalométrica | Lateral or postero-anterior skull X-ray (`cephalometric_lateral` / `cephalometric_pa`). |
| CBCT | CBCT / TC de haz cónico | Cone-beam computed tomography. |
| Before / After | Antes / Después | Paired clinical photos linked via `paired_document_id`. |
| Attachment | Adjunto | A `MediaAttachment` row linking a Document to an arbitrary owner (`patient`, `treatment`, `plan`, `plan_item`, `appointment_treatment`, `clinical_note`). |
| Owner registry | Registro de dueños | The `media.attachment_registry` global. Each consumer module registers its own `owner_type` strings + a resolver. See ADR 0007. |

## Scheduling

| EN (code) | ES (UI) | Definition |
|---|---|---|
| Cabinet | Gabinete | A clinical room/operatory/chair. Appointments are assigned to a cabinet. |
| Agenda | Agenda | The calendar UI module. Owns `Appointment` entities. |
| Schedules (module) | Horarios | The clinic-hours / opening-hours module (issue #39). **Different from agenda** — agenda must not depend on schedules; data flows the other way via events. |
| Clinic hours | Horario de clínica | Open/closed slots defined in the schedules module. |
| Professional hours | Horario del profesional | Optional per-professional availability override. |

## Recalls

| EN (code) | ES (UI) | Definition |
|---|---|---|
| Recall | Recordatorio | A scheduled call-back for a patient who left without booking the next visit. Owned by the `recalls` module. |
| Call list | Lista de llamadas | The monthly worked list at `/recalls`. Front desk works it row by row. |
| Recall reason | Motivo de recordatorio | Why the patient is being recalled (`hygiene`, `checkup`, `ortho_review`, `implant_review`, `post_op`, `treatment_followup`, `other`). |
| Snooze | Posponer | Bump a recall's `due_month` forward N months without losing its history. |
| Contact attempt | Intento de contacto | One row in `recall_contact_attempts`: channel + outcome + note. Logged every time the front desk reaches out. |
| Needs review | Revisar | Bucket for recalls whose patient was archived or marked `do_not_contact` after the recall existed — surfaced in a separate filter, not deleted. |

## Billing

| EN (code) | ES (UI) | Definition |
|---|---|---|
| Finance | Finanzas | The sidebar section grouping Cobros, Presupuestos and Facturas as tabs. A navigation grouping, not a domain entity — the three remain distinct, and Factura stays a fiscal document under Veri*Factu. |
| Budget | Presupuesto | A pre-invoice quote sent to the patient. Has its own workflow (`draft → sent → accepted → rejected`). |
| Invoice | Factura | A fiscal document. Spanish clinics must comply with Veri\*Factu (see verifactu module). |
| Credit note | Factura rectificativa | An invoice correction document. |
| Payment | Pago | Money received against an invoice. Can be partial. |
| Catalog | Catálogo | Module that holds priced services and products. |
| To collect | Por cobrar | Money **earned and not yet collected**: a treatment has been performed and nothing has covered it. Reserved wording — *Pendiente* is left for work not done yet (a treatment) and for an instalment not yet due, so the three never wear the same word on one screen. |
| Awaiting acceptance | Esperando aceptación | The plan status `pending`: the dentist confirmed it, the patient has not accepted the budget. It used to read "En curso", which claimed treatment was under way on a plan whose budget had not even been sent. |

## Compliance (ES)

| Term | Definition |
|---|---|
| Veri\*Factu | Spanish AEAT mandatory e-invoicing regime (RD 1007/2023). Implemented by the `verifactu` module. |
| AEAT | Agencia Estatal de Administración Tributaria — Spanish tax authority. |
| FNMT | Spanish certificate authority issuing the digital certs used for AEAT mTLS. |
| SIF | Sistema Informático de Facturación — invoicing software. Regulated under RD 1007/2023 art. 13. |
| Producer | "Productor del SIF" — the legally responsible party for compliance. See `backend/app/modules/verifactu/README.md`. |
| Declaración responsable | Producer's signed compliance declaration. Required before enabling Veri\*Factu in `prod`. |
| RegistroAlta / RegistroAnulacion | Veri\*Factu submission entries. |
| Huella | SHA-256 chained hash linking each fiscal record to the previous one. |
| Sociedades | Spanish corporations — Veri\*Factu mandatory from 2027-01-01. |
| Autónomos | Spanish self-employed (IRPF) — Veri\*Factu mandatory from 2027-07-01. |

## Module system

| Term | Definition |
|---|---|
| Module | A self-contained feature under `backend/app/modules/<name>/` plus its co-located frontend layer. See `docs/technical/creating-modules.md`. |
| App | What a clinic chooses: a named, versioned group of modules declared in `backend/apps.json` (Agenda = `agenda` + `schedules`), where it is `enabled` or `disabled` for the whole deployment. See ADR 0036, ADR 0038. |
| Enabled / disabled (Habilitada / Deshabilitada) | Whether a module runs. A disabled module keeps its tables and data and is still migrated; only what is mounted changes. Stored as `installed` / `disabled` in `core_module.state`. See ADR 0035. |
| Manifest | The `manifest` dict on a `BaseModule` subclass. Identity, dependencies, permissions, install policy. Schema in `backend/app/core/plugins/manifest.py`. |
| Entry point | `pyproject.toml` registration under `[project.entry-points."dienteazul.modules"]` so the loader can discover the module. |
| `depends` | Manifest field. List of modules this one needs at load time. Cross-module FKs and direct imports are only allowed against modules listed here. |
| Contract / provider | A `Protocol` in `app/core/contracts.py` and the module-supplied object that implements it. How one module reads another's data without importing it; no provider means the owning App is off. See ADR 0039. |
| `integrates` | Manifest field. Modules linked when they run and done without when they do not: imports and FKs allowed, but not pulled in by `enable` and free to be disabled. See ADR 0037. |
| `installable` / `auto_install` / `removable` | Manifest policy flags. `auto_install=False` means the module starts disabled until an operator enables it. |
| `branch_labels` | Alembic per-module migration branch label. Each module owns its branch — never thread one module's revisions through another's chain (issue #56). See ADR 0002. |
| `role_permissions` | Manifest field that grants role → permissions. Permissions in here must also be returned by `get_permissions()` (validated by `manifest_validator.py`). |
| Event bus | In-process pub/sub. See `backend/app/core/events/`. Preferred mechanism for cross-module reactions. See ADR 0003. |
| Event type | A constant in `backend/app/core/events/types.py` `EventType`. Naming convention `entity.action` (e.g. `patient.created`). |
| Tool | An action a module exposes to AI agents via `get_tools()`. Mandatory for write-capable modules. Namespaced as `<module>.<tool_name>`. |
| Agent | A `BaseAgent` subclass a module ships, registered via `get_agents()`. |
| Reference module | A module marked as canonical example others should copy. Today: `patients` (foundational), `schedules` (removable, isolation-critical), `treatment_plan` (heavy deps). |
| Frontend layer | The `frontend/` subdir inside a backend module. Loaded as a Nuxt layer. |
