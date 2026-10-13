# Changelog — record module

## Unreleased

- feat(expediente): la pestaña *Expediente* y el expediente impreso
  muestran la **normativa de referencia** de la clínica
  (`app.core.regulation`). Se configura en *Configuración → General →
  Normativa del expediente*; la página de la app enlaza ahí.

- refactor(expediente): **el membrete sale de este módulo**. La edición de
  membretes (el de la clínica y el de cada profesional) y *Mi membrete*
  pasan a Espacio de trabajo: *Configuración → General → Membretes* y
  *Configuración → Cuenta → Mi membrete*. Con Expediente clínico
  deshabilitado no había dónde editarlos, y el cuestionario de salud los
  sigue imprimiendo. La página de la app conserva un enlace. *Mi membrete*
  ya no pide `record.read`.

- fix(record): las descargas de documentos protegidos usan `useApi` y la sesión HttpOnly del mismo origen.
- feat(expediente): página **Mi membrete** (Configuración → Cuenta): cada
  profesional configura su propio membrete — logotipo, encabezado, línea
  adicional — sin pasar por la administración. Solo el suyo: el de la
  clínica y el de un colega le están vedados. Una cuenta que no está
  vinculada a un profesional no tiene membrete propio y la página lo dice.

- feat(expediente): **membrete en el expediente impreso**. El PDF sale con
  el membrete del profesional que entrega el expediente o, si no tiene uno
  propio, con el de la clínica — nunca con el de otro doctor (ADR 0046).
  Es el mismo mecanismo que usan las cartas de consentimiento y el
  cuestionario de salud. Los membretes se administran desde la página del
  Expediente clínico (el de la clínica y uno por profesional), pero son de
  la clínica, no de este módulo:
  `/api/v1/auth/clinic/settings/letterheads`.

- feat(expediente): **formato del expediente por clínica**. Página nueva,
  *Configuración → Apps → Expediente clínico → Configurar*
  (`/settings/apps/clinical-record`): qué secciones lleva el expediente,
  en qué orden y qué puntos revisa la comprobación. Aplica a la pestaña
  *Expediente* y al documento que se imprime.
  - `GET/PUT /api/v1/record/format`; se guarda en los ajustes de la
    clínica (`record_format`). Un formato vacío es el de siempre.
  - Ocultar una sección no borra nada; una sección oculta tampoco se
    puede entregar.
  - Permiso nuevo `record.configure` (solo administrador).

- feat(expediente): la comprobación pasa de nueve a diez requisitos: se
  añade **motivo de consulta**, que cumple un cuestionario de salud. El
  expediente gana la sección *Cuestionarios de salud*, y las notas de
  evolución muestran los signos vitales.

- feat(expediente): **imprimir o entregar el expediente, con registro**
  (ADR 0033). Botón *Imprimir o entregar* en la pestaña Expediente: se
  indica el motivo (continuidad de la atención, copia para el paciente,
  tercero autorizado, requerimiento de autoridad), a quién se entrega, la
  constancia que ese motivo exige y qué secciones se incluyen. Se genera
  un PDF con exactamente esas secciones, sin entradas anuladas.
  - Tabla `record_disclosure` (migración `exp_0002`), la primera del
    módulo: destinatario, motivo, constancia, alcance, manifiesto de las
    entradas incluidas y el documento tal como salió, con su SHA-256.
  - Sin la constancia no sale nada: una referencia pide su justificación
    clínica; una copia para el paciente, comprobar su identidad; un
    tercero, la autorización firmada; una autoridad, su requerimiento.
  - Cada entrega es una entrada del expediente (sección *Entregas del
    expediente*) y su documento se puede volver a abrir: se sirve el
    guardado, no se regenera.
  - Permiso nuevo `record.disclose` (admin y dentista).
  - El módulo deja de ser desinstalable: guarda constancias (ADR 0035).
  - `labels.json` y `backend/scripts/generate_record_labels.py`: el PDF
    usa las mismas palabras que la pantalla.
- feat(core): categoría `DISCLOSURES` en `SectionCategory`.

- feat(expediente): **qué debe tener el expediente**. La composición
  devuelve `coverage`: nueve requisitos del expediente dental —
  identificación completa, antecedentes heredo-familiares, antecedentes
  personales, odontograma, diagnóstico, pronóstico, plan de tratamiento,
  notas de evolución y consentimiento informado firmado — y si este
  paciente los cumple. La pestaña *Expediente* lo muestra arriba, con lo
  que falta. Es una lectura de ingeniería de la NOM-004-SSA3-2012,
  pendiente de revisión legal, y comprueba presencia, no calidad
  (`coverage.py`).

- feat(expediente): pestaña **Expediente** en la ficha del paciente
  (`patient.detail.tabs`): el expediente clínico completo en orden de
  lectura — identificación, antecedentes, odontograma, periodontogramas,
  notas de evolución, planes y recetas, radiografías y fotografías,
  consentimientos. Cada entrada con su fecha clínica, sus datos y el
  profesional responsable. Opciones para ocultar las secciones vacías y
  para mostrar las entradas anuladas. Solo lectura.
- feat(expediente): la composición devuelve `professionals` — nombre y
  cédula de los profesionales que las entradas nombran como responsables,
  leídos del contrato `ProfessionalDirectory`.
- El expediente pasa de 5 a 13 secciones: `patients`, `odontogram`,
  `periodontogram`, `clinical_notes`, `treatment_plan` y `media` aportan
  ahora las suyas, y `patients_clinical` añade el contexto médico.

- feat(expediente): nace el módulo **`record`**, instalable desde
  *Configuración → Módulos*. Compone el expediente clínico de un paciente a
  partir de lo que guardan los módulos instalados: cabecera y secciones
  ordenadas de entradas fechadas y atribuidas.

  **No posee ningún dato clínico**, y eso es el diseño, no una carencia. Lo
  dice la especificación: *«el expediente no es un sitio nuevo donde guardar
  datos clínicos; es una vista de datos que ya poseen siete módulos, y en el
  momento en que se vuelve copia empieza a separarse del original y hay dos
  verdades sobre las alergias de un paciente»*. Por eso no tiene modelos ni
  migraciones, como `reports`.

- feat(core): contrato `get_record_sections()` en `BaseModule`, con el
  vocabulario (`RecordSection`, `RecordEntry`, `SectionCategory`) en
  `app.core.record`. Vive en el core por la misma razón que
  `SubjectContributor`: si viviera en este módulo, los módulos que aportan
  tendrían que importarlo y declararlo en `depends`, lo que invertiría la
  dependencia y haría obligatorio un módulo opcional para `patients_clinical`,
  que no es desinstalable.

  Es un contrato **distinto** del de derechos del sujeto, no una
  reutilización: responden preguntas distintas para lectores distintos, y la
  diferencia que más importa es que `billing`, `payments`, `verifactu` y
  `accounting_export` aportan **cero** aquí. Una divulgación clínica que lleve
  datos de facturación es un defecto de privacidad, no una función.

- feat(expediente): `GET /api/v1/record/patients/{id}` devuelve la composición.
  Las secciones vuelven **aunque estén vacías** —«este módulo no guarda nada de
  este paciente» es una respuesta, y una sección ausente deja al lector sin
  saber si se preguntó—. Las entradas retractadas se omiten salvo que se pidan
  explícitamente: nunca se borran, pero una entrada que no debió existir no es
  lo que se le entrega a un colega.

  Si la sección de un módulo falla, se registra y vuelve vacía en lugar de
  negar el resto del expediente a quien lo está leyendo.

- feat(antecedentes): `patients_clinical` es el primer módulo que aporta —
  alergias, medicación, enfermedades sistémicas e historia quirúrgica, cuatro
  secciones porque así se leen—. Cada entrada lleva tiempo **clínico** (una
  cirugía de 2019 anotada hoy ordena en 2019), el estado del ciclo de vida y el
  profesional responsable, todo leído de lo que las filas ya dicen desde la
  fase 0.
