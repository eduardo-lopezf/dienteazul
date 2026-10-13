# Changelog — patients_clinical module

## Unreleased

- feat(patients_clinical): **aviso de ASA III/IV al agendar**. Al elegir
  al paciente en la ventana de cita aparece su clase vigente cuando es III
  (aviso) o IV (alerta), con la fecha, quién la valoró y en qué se basa.
  Es un aviso: no impide guardar la cita.
  - En el aviso, recepción ve solo «Paciente ASA IV» y la recomendación:
    ni el significado de la clase, ni la fecha, ni quién la valoró, ni en
    qué se basa.
  - **Recepción ve la clase, sin el detalle clínico.** Permiso nuevo
    `patients_clinical.asa.read`, para todos los roles, y
    `GET /patients/{id}/asa/class`: la clase vigente, nada más (ni
    la fecha). Quién la valoró y en qué se basa solo lo ve quien puede leer el
    historial médico.

- feat(patients_clinical): **firma del paciente en el cuestionario de
  salud en pantalla**. Al pie del formulario el paciente (o su tutor o
  representante) firma con el dedo, un lápiz o el ratón. Se guarda con el
  cuestionario: el dibujo, el nombre de quien firma, en calidad de qué, la
  fecha y la normativa de referencia que el formulario mostraba ese día.
  - **Es obligatoria**: un cuestionario contestado en pantalla no se
    guarda sin la firma (dibujo y nombre). La alternativa igual de válida
    es *En papel*: subir el cuestionario firmado a mano (PDF o foto). El
    servidor rechaza uno que no traiga ni firma ni archivo.
  - En papel no se firma en pantalla: la firma está en la hoja subida.
  - El dibujo se clasifica como dato personal: una solicitud de supresión
    lo elimina. No viaja en el expediente compuesto; sí quién firmó y
    cuándo.
  - Migración `pc_0007`. El lienzo de firma pasa al núcleo
    (`frontend/app/components/shared/SignaturePad.vue`).

- feat(patients_clinical): el cuestionario de salud muestra la
  **normativa de referencia** de la clínica: al pie del formulario en
  pantalla y, en la hoja en blanco, encima de la firma del paciente. El
  texto es de la clínica (`app.core.regulation`), no del módulo.

- feat(patients_clinical): **clasificación ASA** del paciente. Una
  valoración es un juicio clínico fechado y atribuido (clase I–IV,
  modificador E, en qué se basa): no se edita, una nueva la sustituye y
  una equivocada se anula (ADR 0032). La más reciente no anulada es la
  clase vigente.
  - Tarjeta *Clasificación ASA* en el Resumen del paciente, con la clase
    vigente, su fecha y quién la valoró; desde ahí se valora de nuevo y
    se lee el historial.
  - Una clase III aparece entre las alertas del paciente como *alta*; IV,
    como *crítica*. Las clases V y VI de la escala no se ofrecen: no son
    pacientes de consultorio.
  - Permiso propio `patients_clinical.asa.write` (dentista y
    administrador), distinto del que edita el historial médico.
  - API: `GET/POST /patients/{id}/asa`, `POST …/asa/{aid}/retract`.
    Migración `pc_0006`.
  - Llega al expediente como la sección `asa_assessments`.
  - `compute_alerts` recibe ahora la clínica además del paciente.

- fix(patients_clinical): las cargas y aperturas de cuestionarios usan el BFF autenticado de mismo origen.
- fix(types): la tarjeta de antecedentes del Resumen usaba `a.id` como
  `key` de las alergias, y `AllergyEntry` no tiene `id`: todas las filas
  compartían una clave `undefined`. Pasa a usar el índice, como el
  formulario. Estaba en la base del typecheck.

- feat(patients_clinical): el cuestionario de salud en blanco lleva el
  **membrete del profesional que lo imprime** o, si no tiene uno propio,
  el de la clínica (`app.core.letterhead`, ADR 0046).

- feat(patients_clinical): **cuestionario de salud**. Lo que el paciente
  declara en su consulta, como en la historia clínica en papel: motivo de
  consulta, grupo sanguíneo, alergias, 12 preguntas de sí/no con su causa
  y 67 padecimientos para marcar.
  - Tabla `patients_clinical_health_questionnaire` (migración `pc_0005`).
    Es una declaración fechada: no se edita; una visita nueva es un
    cuestionario nuevo y uno equivocado se anula (ADR 0032).
  - Pestaña *Cuestionario de salud* en la ficha del paciente: se contesta
    en pantalla, o se imprime en blanco, se llena a mano y se sube
    escaneado (el archivo queda en los documentos del paciente).
  - `GET/POST /patients/{id}/questionnaires`, `POST …/{qid}/retract` y
    `GET /patients/{id}/questionnaire-form` (la hoja en blanco, en PDF).
  - Las preguntas y los padecimientos están fijos en `questionnaire.py`,
    con versión. Su redacción vive en las traducciones del frontend
    (`healthQuestionnaire`) y se copia al PDF con
    `backend/scripts/generate_record_labels.py`.
  - Aporta la sección *Cuestionarios de salud* al expediente clínico, y
    entra en la exportación y anonimización de derechos del paciente.

- feat(patients_clinical): **antecedentes heredo-familiares**. Tabla nueva
  `patients_clinical_family_history` (migración `pc_0004`): padecimiento,
  familiar (madre, padre, hermano/a, abuelo/a, hijo/a, otro) y notas. Se
  capturan en el formulario de historial médico, en una sección propia, y
  viajan con el resto del historial (`family_history` en
  `GET/PUT /patients/{id}/medical-history`). Nacen con las reglas del
  resto de antecedentes (ADR 0032): lo que se quita del formulario se
  anula, no se borra. Aportan su sección al expediente clínico y entran en
  la exportación y la anonimización de derechos del paciente.

- feat(patients_clinical): aporta al expediente clínico la sección **Contexto médico** (embarazo, anticoagulantes, hábitos, reacciones a la anestesia), además de los antecedentes.

- feat(widgets): «Historial médico» (Resumen de la ficha) y «Alertas
  médicas» (cabecera de la ficha) se listan en Configuración → Widgets,
  con datos ficticios (ADR 0040). `useMedicalHistory` y
  `usePatientAlerts` no llaman a la API dentro de un ejemplo
  (`utils/previewSamples.ts`).

- refactor(clínico): `professionals` pasa de `depends` a `integrates` y
  deja de importarse
  ([ADR 0039](../../../../docs/adr/0039-modules-reach-each-other-through-core-contracts.md)).
  El profesional responsable de una entrada se pregunta a
  `ProfessionalDirectory.for_account`. Con la App Profesionales apagada
  la entrada se guarda igual, con la cuenta que la escribió y sin
  profesional; la clave foránea y los datos ya guardados no cambian.

- feat(clínico): una entrada de antecedentes **nombra al profesional
  responsable** (`recorded_by_professional_id`, `pc_0003`). Se resuelve desde la
  ficha de directorio de la cuenta que la escribe (`professionals.user_id`), así
  que se rellena sola en el caso normal: el dentista registrando la historia de
  su paciente. Una cuenta sin ficha lo deja vacío, que es la respuesta
  verdadera; el caso que describe el ADR —un auxiliar escribiendo lo que dicta
  un dentista— necesita que alguien *pregunte* quién responde, y todavía nadie
  pregunta.

  La clave foránea cruza de rama con `depends_on = ("professionals",)`, como ya
  hace `liq_0001`. Sin eso fallaba en toda base vacía, que es lo que obligó a
  aplazar la columna en `pc_0002`.

- feat(clínico): **los antecedentes dejan de borrarse.** Alergias, medicación,
  enfermedades sistémicas e historia quirúrgica ganan el ciclo de vida que pide
  el [ADR 0032](../../../../docs/adr/0032-clinical-record-is-append-only.md):
  `ended_at` (era cierto y dejó de serlo), `retracted_at` + `retraction_reason`
  (nunca debió constar) y `recorded_by_user_id`. Son dos columnas y no un
  `deleted_at` porque son dos cosas distintas: una medicación suspendida sigue
  siendo historia y debe leerse; una alergia retractada deja de disparar
  avisos. Ninguna de las dos borra la fila.

  Las seis bajas por fila pasan a ser retractaciones. Una alergia a la
  penicilina quitada por un toque equivocado ya no desaparece sin rastro — era
  un defecto de seguridad del paciente antes que de cumplimiento.

- fix(clínico): **guardar el formulario de antecedentes reescribía la historia
  entera.** `PUT /medical-history` borraba todas las filas de las cuatro tablas
  e insertaba otras nuevas en cada guardado. No hacía falta un error: la vía
  normal destruía la historia en cada visita, así que una alergia perdía la
  fecha en que se registró por primera vez y el expediente no podía decir desde
  cuándo constaba.

  Ahora se reconcilia por id: una línea con id actualiza su fila, una sin id es
  entrada nueva, y una fila viva que el formulario ya no trae se **retracta**.
  Los ids ya iban y venían —el formulario edita el objeto que devolvió el GET—
  pero se validaban contra los esquemas de alta, que no tienen `id`, y Pydantic
  los descartaba; de ahí que solo quedara reemplazar el bloque. Se añaden
  esquemas `*Submit` que sí lo llevan, así que la pantalla no cambia.

  Quitar una línea se lee como retractación y no como fecha de fin: el
  formulario no pregunta *cuándo* dejó de ser cierto, e inventarlo pondría en
  el expediente una afirmación clínica que nadie hizo.

- **Pendiente, y por qué.** El ADR 0032 pide además que cada entrada nombre al
  **profesional colegiado** responsable. No está, por dos motivos verificados:

  1. No existe vínculo entre una cuenta y una ficha del directorio.
     `professionals` es independiente de `users` a propósito, y el único puente
     es una comparación de correos que sirve para mostrar «tiene acceso».
     Deducir de ahí la autoría clínica sería una conjetura escrita en un
     documento cuyo objeto es servir de prueba.
  2. La clave foránea no sobrevive a una instalación nueva. Este módulo está en
     la cadena central de migraciones, que el arranque aplica primero;
     `professionals` es un módulo desinstalable en su propia rama, que se aplica
     después. El primer borrador de `pc_0002` la incluía y fallaba con
     `relation "professionals" does not exist` en cualquier base vacía.

  La columna se retira hasta que el producto decida de dónde sale la autoría.

- test(clínico): `test_clinical_history_migration_with_rows.py` — la migración
  contra una base **con pacientes dentro**, que es lo que el ADR exige por su
  nombre y lo que la prueba de ida y vuelta existente no cubre: esa parte de
  vacío y llega a `heads`, con todas las ramas en un orden que resultó
  funcionar. Fue la que encontró el fallo de orden entre ramas.

- fix(i18n): la banda de alertas del paciente usaba tres claves ausentes.
  `common.collapse` y `common.expand` estaban tapadas por su valor por
  defecto; `common.more` no lo tenía, así que el contador de alertas ocultas
  se leía «+2 common.more». Las tres añadidas en es y en.

- feat(privacy): `get_subject_contributors()` — this module now answers
  for its own data when a patient exercises portability or erasure
  ([ADR 0026](../../../../docs/adr/0026-subject-rights-are-a-module-contract.md)).
  Two sections: `clinical_history` and `contacts`. The contacts one is
  the only place a **third party's** data (emergency contact, legal
  guardian) hangs off a patient record, and it is erased with them.

- fix(privacy): classified this module's personal columns with `pii()`
  so the copilot's PHI boundary derives them from the schema instead of a
  hand-kept list ([ADR 0025](../../../../docs/adr/0025-pii-is-classified-on-the-column.md)).

- fix(i18n): the legal-guardian ID field was labelled "DNI/NIE" in
  Spanish, a document this deployment's patient records cannot even
  represent (`national_id_type` accepts `curp`/`ine`/`passport`). Label
  is now "Identificación" with the three accepted documents as the
  placeholder. English was already neutral and is untouched.

- fix(events): publish through ``event_bus.publish_after_commit(db, ...)``
  instead of announcing from inside the caller's open transaction.
  Handlers read through their own sessions, so a flushed-but-uncommitted
  row was invisible to them (audit S2). See
  [ADR 0019](../../../../docs/adr/0019-events-publish-after-commit.md).

- refactor(types): drop the ``as unknown as Record<string, unknown>`` cast in ``useMedicalHistory`` now that ``useApi`` accepts ``object`` payloads.
- Added per-module `CLAUDE.md` for AI-agent context (2026-04-27).

## 0.1.0 — initial

- Normalized medical history, allergies, medications, emergency contacts.
- `patient.medical_updated` event for the timeline.
- Role-scoped permissions: hygienists read-only on medical, write on emergency.
