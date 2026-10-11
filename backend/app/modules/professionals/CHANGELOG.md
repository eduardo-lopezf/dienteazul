# Changelog — professionals module

## Unreleased

- feat(professionals): la subida del retrato depende de `require_storage_room` (core): se rechaza con `403 Storage limit reached` cuando no cabe en el espacio en disco que permite el nivel de la clínica.
- fix(professionals): cargas y vistas previas de fotos usan `useApi` y la sesión HttpOnly del mismo origen.
- refactor(professionals): `useProfessionals` vive ahora en esta capa
  (`frontend/composables/`) y no en la app base (ADR 0044).

- feat(professionals): `ProfessionalDirectory.briefs` devuelve también
  `license_number`, que una receta debe mostrar. Lo usa `treatment_plan`.

- feat(professionals): `ProfessionalDirectory` gana `for_account`
  (ADR 0039): el perfil que una cuenta *es* en la clínica, sin crearlo
  nunca. Envuelve `ProfessionalService.for_user`; lo usa
  `patients_clinical` para atribuir una entrada clínica.

- feat(professionals): `ProfessionalDirectory` gana
  `profile_for_account` (ADR 0039): el perfil del directorio que
  corresponde a una cuenta de usuario, creándolo si falta. Es la lógica
  que antes vivía en la siembra de `schedules`, escribiendo en esta
  tabla desde fuera.
- feat(professionals): el módulo ofrece el contrato del core `ProfessionalDirectory` (validar, listar y resumir profesionales, y crear el perfil espejo de una cuenta antigua, que antes hacía la agenda escribiendo en esta tabla) desde
  `providers.py` (ADR 0039), para que otros módulos lo consulten sin
  importarlo.
- feat(profesionales): una ficha del directorio puede **nombrar la cuenta** con
  la que esa persona entra al sistema (`user_id`, `pro_0003`). El directorio
  sigue siendo independiente de `users` —un colaborador puede estar sin cuenta,
  y por eso la columna admite nulo—, pero ahora se puede responder a «qué
  profesional es quien está operando el sistema», que es de donde sale la
  autoría de una anotación clínica
  ([ADR 0032](../../../../docs/adr/0032-clinical-record-is-append-only.md)).

  **No se deduce del correo.** `has_system_access` compara correos para dar una
  pista, y una pista es el peso justo de una coincidencia: dos personas
  comparten una dirección familiar, alguien cambia de correo, una clínica
  reutiliza uno. Una autoría clínica escrita en un documento que sirve de
  prueba no puede apoyarse en eso, así que el vínculo lo declara un
  administrador. Sin relleno automático en la migración, por lo mismo.

  Dos negativas en la validación, ambas por lo que corromperían: una cuenta sin
  membresía en la clínica (nombraría a un extraño como autor de sus registros,
  400) y una cuenta ya vinculada a otra ficha de la misma clínica (haría
  irresoluble quién responde por una entrada, 409). Índice único parcial por
  clínica, porque la misma persona puede tener ficha en dos.

  En la pantalla es un desplegable **Cuenta vinculada** en el formulario, que
  solo ofrece cuentas con acceso a esta clínica y omite las ya tomadas. Si el
  perfil no puede listar cuentas, el campo no aparece y el resto del formulario
  sigue funcionando.

- feat(ui): a row opens the professional's card instead of the edit form.
  The pencil is gone: the whole row is one button, so the common intent —
  finding out who someone is — is what a click answers, and editing is a
  deliberate step inside the card. Being a real `<button>` it also takes
  keyboard focus and the 44 px touch minimum without extra markup.

  The card is a read-first presentation: a 96 px portrait against a
  tinted band, the profile type, status and disciplines as chips, and a
  mosaic of tiles below with licence, email, phone and system access.
  Email and phone are links. Tiles are only built for facts the profile
  actually has, so a sparse record reads as a short card rather than a
  grid of dashes.

- fix(ui): portraits now appear in the directory. The list rendered
  `photo_url` straight into `<img src>`, which can never work — the
  `/photo` endpoint requires a Bearer header an `<img>` cannot send, so
  every row fell back to initials. The list now fetches them as blobs
  through the same helper the edit form already used, revoking the object
  URLs when the results change or the page unmounts.

  Removed `resolvePhotoUrl` with it: it prepended the API origin, which
  does nothing about the missing header, and sat next to the loader that
  works. Lint had been flagging it as unused since it was written.

- fix(privacy): classified this module's personal columns with `pii()`
  so the copilot's PHI boundary derives them from the schema instead of a
  hand-kept list ([ADR 0025](../../../../docs/adr/0025-pii-is-classified-on-the-column.md)).

- feat(specialties)!: `specialty` is no longer free text. Replaced by a
  many-to-many link to the catalog's `specialties` table via
  `professional_specialties` (migration `pro_0002`, `depends_on = cat_0004`).
  The same discipline names were being typed into three places — this column,
  the treatment catalog, and a hardcoded list in the professionals page — so a
  stray accent split one discipline in two. Many-to-many because a dentist who
  does both endodontics and periodontics is ordinary. Existing values are
  preserved for clinical staff: each distinct (clinic, specialty) is matched
  against the catalog by name across locales, created when missing, then
  linked. Collaborator labels ("Laboratorio", "Proveedor") are roles, not
  disciplines, so they move to `notes` rather than polluting the catalog, and
  the UI hides the field for non-clinical types. `manifest.depends` gains
  `catalog`. Requests take `specialty_ids` (authoritative on update);
  responses carry an eager-loaded `specialties` list. Search by discipline
  matches through the link. A specialty from another clinic returns 400.

- feat: profile responses now include `has_system_access` — true when the
  profile's email matches a user with a membership in this clinic. Surfaced
  in the profile modal next to "Activo" as a read-only "Usuario con acceso"
  indicator; computed at response time, not stored.

- feat(scheduling): adds the `hygienist` profile type. Active dentists and
  hygienists are now the scheduling source of truth for Agenda and Schedules.

- Initial release of the clinic directory for dentists and collaborators.
- Adds profile fields for photo URL, specialty, professional-license number,
  contact information, notes and active status.
- Adds `professionals.read` and `professionals.write` permissions, REST
  endpoints and the `/professionals` sidebar screen.
- Adds the isolated `pro_0001` Alembic branch and `professionals` table.
