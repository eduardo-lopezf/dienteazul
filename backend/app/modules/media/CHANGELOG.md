# Changelog — media module

## Unreleased

- feat(media): las subidas de documentos y fotografías dependen de `require_storage_room` (core): se rechazan con `403 Storage limit reached` cuando no caben en el espacio en disco que permite el nivel de la clínica.
- fix(media): cargas, vistas previas y descargas usan `useApi` con sesión HttpOnly, CSRF y recuperación de refresh.
- feat(media): el contrato `PatientDocuments` ofrece `usage_by_kind`:
  cuánto pesan los archivos de los pacientes por clase clínica
  (`media_kind`), archivados incluidos. Lo usa *Configuración → Cuenta →
  Espacio en disco*. Es de toda la base de datos, no de una clínica: la
  cifra es la del tenant.

- feat(media): aporta al expediente clínico la sección **Radiografías y fotografías** (`record.py`). Los documentos administrativos quedan fuera.

- feat(media): ofrece el contrato `PatientDocuments` (ADR 0039): si un
  documento es un archivo vivo de un paciente. Lo usa `consents` para
  archivar el escaneo de una carta firmada en papel, sin importar `media`.

- refactor(media): el registro de dueños de adjuntos pasa a
  `app/core/attachments.py`; `media/attachment_registry.py` lo reexporta.
  Así un módulo registra su `owner_type` sin importar `media` (ADR 0039).

- feat(media): el módulo registra por primera vez sus piezas de la ficha
  del paciente (ADR 0041): la pestaña «Galería» en `patient.detail.tabs`
  y el modo Documentos en `patient.detail.administracion.documents`.
  Antes la ficha las incrustaba por nombre.
- feat(i18n): el módulo tiene **fichero de idiomas**. No tenía ninguno: sus
  pantallas —galería de fotos, subida y visor de documentos— funcionaban
  enteras con el segundo argumento de `t(clave, 'por defecto')`, unas 100
  cadenas que **no se podían traducir**.

  Y no era «todo en castellano»: los textos por defecto estaban escritos
  mitad en un idioma y mitad en otro, así que la interfaz en español decía
  *Patient gallery*, *Add photo*, *All*, *X-ray*, *No photos yet*, *Loading
  document...* y *Zoom in*. Ahora dice *Galería del paciente*, *Añadir
  foto*, *Todas*, *Radiografía*, *Todavía no hay fotos*…, y en inglés dice
  lo que debe.

  101 claves (`documents.*` y `photoGallery.*`) en es y en, declaradas en el
  `nuxt.config` de la capa con el mismo patrón que `payments` y `schedules`.
  **Retirados los 123 valores por defecto** de los componentes: eran lo que
  mantenía el problema invisible, porque la pantalla se veía bien mientras
  intlify avisaba en cada render.

  Tres claves salían **en crudo** en pantalla, sin texto por defecto que las
  tapara: `documents.filter.allTypes` en el filtro de la galería de
  documentos, y `common.view` / `common.download` en los botones de la
  tarjeta y del visor. Eso lo veía el usuario como «documents.filter.allTypes».

  `photoGallery.showingOf` recibía una plantilla de JavaScript
  (`` `Showing ${n} of ${total}` ``) como valor por defecto, así que nunca
  fue un mensaje: ahora es `Mostrando {count} de {total}` con parámetros de
  verdad.

  Las claves de vocabulario compartido que usaban estos componentes
  —`actions.change`, `common.optional`, `common.upload`, `common.uploading`,
  `common.view`, `common.download`— van al fichero del host, no al del
  módulo: un módulo que definiera `common.*` estaría apropiándose de
  vocabulario de todos.

- feat(privacy): `get_subject_contributors()` — este módulo ya responde
  cuando un paciente ejerce portabilidad o supresión
  ([ADR 0026](../../../../docs/adr/0026-subject-rights-are-a-module-contract.md)).
  Metadatos de documentos y adjuntos. Registro asistencial: se conservan. **Los ficheros en disco no se tocan** (ADR 0008).

- fix(ui): document pagination works. `UPagination` was passed the Nuxt
  UI v2 props (`v-model` + `page-count`) on a v4 component, which
  ignores both — the control rendered at defaults and clicking a page
  did nothing, leaving documents past the first page unreachable
  (audit S5).

- fix(events): publish through ``event_bus.publish_after_commit(db, ...)``
  instead of announcing from inside the caller's open transaction.
  Handlers read through their own sessions, so a flushed-but-uncommitted
  row was invisible to them (audit S2). See
  [ADR 0019](../../../../docs/adr/0019-events-publish-after-commit.md).

- fix(events): repair the `patient.archived` cascade, which had never
  run (audit event-bus #1, #95). The handler signature took
  `(self, db, data)` but the bus calls `handler(data)`, raising
  `TypeError` on every archive; it also read `data["clinic_id"]` while
  the publisher sent only `patient_id`. Handler now takes `(data)`,
  opens its own session + commits (publish-before-commit), and guards a
  missing payload. Depends on the patients publisher now emitting
  `clinic_id`.

- perf(lists): drop the ``select_from(query.subquery())`` count
  anti-pattern in ``DocumentService.list_documents`` and
  ``PhotoService.list_photos``; both lists now count via a direct
  ``COUNT(Document.id)`` over the same filter set.
- Added per-module `CLAUDE.md` for AI-agent context (2026-04-27).
- **0.2.0 (issue #55)** — Photo gallery + generalized polymorphic
  attachments (2026-05-02):
  - `Document` gains `media_kind`, `media_category`, `media_subtype`,
    `captured_at`, `paired_document_id`, `tags` columns. New
    `media_attachments` table replaces both `clinical_note_attachments`
    and `treatment_media`.
  - New endpoints: photo upload (`POST /patients/{id}/photos`) with
    EXIF + Pillow thumbnail generation, gallery list, before/after
    pairing, `/attachments` polymorphic CRUD.
  - Owner-type registry in `attachment_registry.py` — clinical_notes
    and treatment_plan register their owner_types at import time
    (ADR 0007).
  - New permissions `media.attachments.read` / `media.attachments.write`.
  - New events `media.photo_uploaded`, `media.attachment_linked`,
    `media.attachment_unlinked`, `media.pair_created`,
    `media.pair_removed`.
  - Pillow added as a backend dependency.
  - HEIC / HEIF / WebP / GIF added to the photo MIME allowlist.

## 0.1.0 — initial

- Local storage backend with MIME and size validation.
- `document.uploaded`, `document.deleted` events.
- Subscribes to `patient.archived` for cascade.
