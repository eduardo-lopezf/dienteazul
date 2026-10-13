# Changelog — treatment_plan module

## Unreleased

- feat(treatment_plan): **la carta se pide antes de marcar un tratamiento
  como realizado**. En un plan en curso sin carta de consentimiento
  informado firmada (confirmado antes de exigirla, o con la carta
  revocada), completar un tratamiento o una sesión pregunta primero:
  *Crear la carta* o *Marcar como realizado sin carta*. Si se sigue sin
  ella, el plan muestra una alerta roja —*Falta la carta de consentimiento
  informado*— y cada tratamiento realizado, la marca *Sin carta*, hasta
  que la carta se firme. El servidor no lo impide: es un aviso.
  - El detalle del plan lleva `informed_consent_missing`.

- feat(treatment_plan): **confirmar un plan pide su consentimiento
  informado** cuando la clínica lo exige (app Expediente clínico). Sin la
  carta firmada, `POST …/confirm` responde `409 informed_consent_required`
  y el plan sigue en borrador; la pantalla lo dice y lleva a los
  consentimientos del paciente para escribirla. Con Expediente clínico
  apagado nadie lo pide. La regla la decide `consents` (contrato
  `PlanConsents`); este módulo no lo importa.

- fix(treatment_plan): la descarga de recetas usa el transporte BFF autenticado con refresh compartido entre pestañas.
- feat(treatment_plan): **el selector de plantillas agrupa por
  especialidad**. Con 125 plantillas de referencia la rejilla plana ya no
  se podía recorrer. Las que la clínica guardó de sus propios planes van
  primero (*De la clínica*); el buscador filtra dentro de los grupos.
  El buscador rápido del odontograma (nuevo plan y detalle) agrupa igual
  las plantillas que encuentra, y también los tratamientos sueltos, cada
  uno bajo una sola especialidad.
  - API: cada plantilla de `GET /plan-templates` (y las respuestas de
    crear, editar y guardar desde un plan) lleva `specialty`
    (`key`, `names`), con el nombre que la clínica le dio a la
    especialidad; `null` en las propias.

- feat(treatment_plan): **plantillas de plan para todas las
  especialidades**. De 20 a 125 plantillas de referencia: entre cuatro y
  ocho más por cada especialidad que no era Ortodoncia, incluidas
  Odontopediatría y Rehabilitación Oral, que no tenían ninguna. Cubren
  las secuencias habituales (endodoncia + perno + corona, implante con
  elevación de seno, cordal impactado, prótesis completa, pulpotomía y
  corona, entre otras). Solo datos en `templates_seed.py`.
  - Cada plantilla usa solo tratamientos de su especialidad o de una de
    las diez de base, así que una clínica que la habilita la recibe
    entera; una prueba lo comprueba.
  - Una clínica que ya tiene la especialidad las recibe al pulsar
    *Añadir N nuevos* en *Configuración → Apps → Tratamientos*, o con
    `scripts/backfill_plan_templates.py`. Las plantillas existentes no
    cambian.
  - Contenido sin revisión clínica.

- feat(treatment_plan): **plantillas de plan por especialidad**. Cada
  plantilla de referencia pertenece a una especialidad y la clínica la
  recibe solo mientras la tiene habilitada. De 8 a 20 plantillas: cinco
  de Ortodoncia (estudio, fija completa, alineadores, interceptiva,
  retención) y una por cada especialidad nueva. Siguen a la especialidad
  por eventos del catálogo: al habilitarla se instalan y se muestran, al
  deshabilitarla se ocultan, al restaurarla vuelven a la referencia. Las
  plantillas que la clínica guardó de sus propios planes no se tocan.

- feat(treatment_plan): el detalle del plan muestra el **diagnóstico y el
  pronóstico** y permite editarlos después de crear el plan
  (`PlanDiagnosisCard`). Antes solo se podían escribir al crearlo y el
  detalle no los mostraba.

- feat(treatment_plan): **pronóstico** del plan, junto al diagnóstico:
  `prognosis` (`favorable` | `reserved` | `unfavorable`) y
  `prognosis_notes` (migración `tp_0014`). Se indica al crear el plan, en
  *Más opciones*, se muestra en el detalle y forma parte de la sección
  *Planes de tratamiento* del expediente clínico.

- feat(treatment_plan): aporta al expediente clínico las secciones **Planes de tratamiento** (diagnóstico y tratamientos, sin precios ni notas internas) y **Recetas** (`record.py`).

- refactor(treatment_plan): `PlannedTreatmentSelector` vive ahora en esta
  capa y no en la app base (ADR 0044).

- fix(treatment_plan): el número de plan es el **mayor del año más uno**,
  no el recuento más uno. Contando, en cuanto faltaba una fila el
  siguiente número caía sobre un plan existente y crear planes fallaba
  con `uq_treatment_plan_number`. Misma regla que los presupuestos.

- refactor(treatment_plan): `professionals`, `agenda` y `media` pasan de
  `depends` a `integrates` y dejan de importarse (ADR 0039, ADR 0042). El
  módulo ya solo importa y exige `patients` de fuera de la App.
  - Profesionales: validación, nombres y firmante de recetas por
    `ProfessionalDirectory`. Con la App apagada no se puede asignar a
    nadie ni emitir recetas; lo demás funciona.
  - Agenda: `on_appointment_completed` usa `planned_items` del evento en
    vez de leer `appointment_treatments`.
  - Media: el dueño de adjuntos `plan_item` se registra en
    `app.core.attachments`.
  - Se quitan las relaciones ORM `assigned_professional` (plan e ítem);
    las claves foráneas no cambian.

- refactor(treatment_plan): **el plan ya no llama a Presupuestos ni a
  Cobros** ([ADR 0042](../../../../docs/adr/0042-core-apps-must-stay-separable.md)).
  `budget` y `payments` pasan de `depends` a `integrates` y no se importan.
  Confirmar, reabrir y borrar publican eventos y `budget` crea, cancela o
  borra el presupuesto en su propia transacción; el plan se enlaza al oír
  `budget.created_for_plan`. Las lecturas van por los contratos
  `PlanBudgets` y `Collections`. `plan.budget` deja de ser una relación.
- **Cambio de comportamiento:** la respuesta de `POST …/confirm` ya no
  trae `budget_id`; hay que releer el plan (el frontend ya lo hacía). Si
  la creación del presupuesto falla, el plan queda confirmado y su
  siguiente paso es «generar presupuesto».
- feat(treatment_plan): con la App Presupuestos apagada un plan confirmado
  pasa directamente a `active`, no queda bloqueado ni «sin presupuestar», y
  al volver la App se puede generar su presupuesto. Con Cobros apagada, un
  plan se puede borrar o cancelar sin la comprobación de cobros.
- removed: `POST …/generate-budget` y `POST …/budget-addendum`; ahora son
  `POST /api/v1/budget/plans/{id}/budget` y `/addendum`.
- feat(treatment_plan): evento `treatment_plan.deleted`; contrato
  `PlanQuotes` para que `budget` lea el plan.

- feat(treatment_plan): la pestaña «Clínico» de la ficha del paciente es
  ahora de este módulo (ADR 0041). `ClinicalTab` y
  `DiagnosisModeContainer` llegan desde `patients` y la pestaña se
  registra en `patient.detail.tabs`; se muestra, como antes, a quien
  pueda leer el odontograma o los planes.
- feat(treatment_plan): el módulo ofrece el contrato del core
  `PlannedTreatments` desde `providers.py` (ADR 0039): validar ítems
  planificados y describirlos para quien los enlaza. Esa descripción la
  armaba antes el esquema de la agenda leyendo modelos de tres módulos.
- feat(treatment_plan): «Agendar» en el detalle del plan pasa por
  `useAppointmentBooking()`, y la nota de visita queda en solo lectura
  cuando la app Agenda está deshabilitada (`backend/apps.json`, ADR
  0038): la nota se guarda a través de la API de agenda.
- feat(treatment_plan): **un tratamiento sin precio deja de sumar cero en silencio.** El constructor cuenta las líneas que el catálogo no valora y lo dice junto al total, con enlace al catálogo para quien pueda editarlo; se repite en el paso del botón *Crear* y en la ventana de *Confirmar plan* —«N tratamientos entran sin precio, así que el presupuesto no los cobrará»—, que es el momento en que esa cifra se convierte en el presupuesto que el paciente firma. La línea ya mostraba «-», pero nadie lee un guion cuando debajo hay un total. Avisa y no impide: hay trabajo que se presupuesta caso por caso, y vale la misma regla que para los conflictos del odontograma.
- fix(treatment_plan): la descripción de *Confirmar plan* seguía diciendo que al confirmar «los tratamientos quedan bloqueados», que dejó de ser cierto al permitirse añadir. Ahora dice lo que pasa: se puede seguir añadiendo, y cambiar o quitar lo que ya está pide reabrir. De paso nombra el estado nuevo, *Esperando aceptación*.

- feat(treatment_plan): **la bandeja deja de recibir a una clínica vacía con siete pestañas vacías.** Mientras no haya ningún plan, `/treatments/plans` muestra `PlansFirstRun`: una instrucción —crear el primero— y las tres piezas de las que se construye un plan (catálogo, profesionales, pacientes), marcadas contando los datos reales por HTTP, no con pasos de asistente. Lo que falta lleva su enlace; sin catálogo el botón queda apagado explicando por qué, porque el constructor abriría un odontograma en el que no hay nada que añadir. La decisión se toma con el total de planes de cualquier estado, no con el de la pestaña, y la pantalla espera esa respuesta tras un esqueleto: por defecto habría pintado las pestañas para arrancarlas después, que es justo el parpadeo que esto quita.
- fix(treatment_plan): `test_add_item_blocked_when_budget_generated` fijaba la regla anterior (409 al añadir con presupuesto vivo). Pasa a `test_add_item_allowed_after_the_budget_exists` y afirma 201, que es el contrato nuevo; quitar y editar siguen con sus pruebas de 409. El docstring de `_is_plan_locked` decía «cualquier cambio estructural» y ahora nombra a sus tres llamantes.
- feat(treatment_plan): **añadir a un plan en curso ya no anula el presupuesto firmado.** Encontrar otra caries a mitad de tratamiento obligaba a reabrir el plan —cancelando el presupuesto que el paciente había aceptado—, reconfirmar y hacérselo aceptar otra vez. Ahora `add_item` no pasa por `_is_plan_locked`: añadir no toca ninguna línea acordada. Lo nuevo se valora con un **añadido**, `POST /treatment-plans/{id}/budget-addendum` (`plans.write`), un segundo borrador que lleva el número del plan; `plan.budget_id` sigue apuntando al que se acordó. Editar o eliminar una línea aceptada sigue devolviendo 409. Nueva franja *N tratamientos sin presupuestar*, y desde el odontograma bloqueado se puede **Añadir tratamiento en el {pieza}** reutilizando el buscador del constructor. Pineado en `tests/test_treatment_plan_addendum.py`.
- feat(treatment_plan): `unbudgeted_items` deduce qué tratamientos no cubre ningún presupuesto vivo del plan cruzando `budget_items.treatment_id`, que ya existía: sin columna nueva, sin migración y sin backfill, así que los planes anteriores responden bien desde la primera petición. El detalle lo expone como `unbudgeted_count`, y `other_budgets` lista los añadidos para que no queden inalcanzables desde el plan que los produjo.

- fix(treatment_plan): **el banner de bloqueo sigue el estado del plan, y baja la voz.** Se decidía por el presupuesto, así que discrepaba de la regla que la pantalla aplica en los dos sentidos: un plan `active` sin presupuesto estaba fijado y no decía nada, y un plan `completed` seguía gritando que estaba bloqueado. Ahora aparece para todo lo que no sea borrador, con tres textos —*Plan confirmado* (reabrir anula el presupuesto {n}, o sin la coletilla si no hay), *Plan terminado* completado, *Plan terminado* cerrado con la vía de reactivar, que es el único que tiene ese botón—. Deja el ámbar fijo por los tokens del tema: era el estado normal de un plan durante casi toda su vida pintado del color de un aviso, y además ignoraba el modo oscuro.
- fix(treatment_plan): **`pending` deja de llamarse «En curso».** Un plan confirmado con el presupuesto sin enviar anunciaba que el tratamiento estaba en marcha; ahora es *Esperando aceptación*, que es lo que espera. Cambia en el badge, en el filtro de estados y en el encabezado de la ficha. Va con el criterio de vocabulario nuevo en `docs/glossary.md`: *Pendiente* queda para el trabajo por hacer, y el dinero ganado y sin cobrar es *Por cobrar*.
- feat(treatment_plan): **el plan dice qué toca ahora.** Nueva franja bajo el stepper con la única acción que lo hace avanzar y el botón que la ejecuta: *Añade los tratamientos*, *Confirma el plan*, *Genera el presupuesto*, *Envía el presupuesto al paciente*, *Esperando respuesta del paciente*, presupuesto caducado/rechazado/anulado, *Agenda la primera/próxima cita*, *Próxima cita: …*, o nada en un plan terminado. La lee `TreatmentPlanService.next_action`, que el detalle devuelve en `next_action` (`GET /treatment-plans/{id}`), porque el estado del presupuesto y la existencia de una cita futura no estaban ambos en lo que carga la pantalla. Existía el hueco: un plan confirmado se quedaba parado con el presupuesto sin enviar y el stepper decía «Confirmar ✓», sin que nadie supiera que le tocaba. Siempre una sola acción. Aparece igual en la ficha del paciente, con sus botones; quien no tenga permiso de escritura ve solo la frase. Pineado en `tests/test_treatment_plan_next_action.py`.

- feat(treatment_plan): **lo que ofrece un tratamiento depende del estado del plan.** En borrador se edita y se elimina (nuevo *Eliminar tratamiento* en su ventana), y completar o cobrar abre *Confirmar plan* explicando por qué; al confirmar, el plan pasa a en curso, se genera su presupuesto y se ejecuta lo que se había pedido; al cancelar, sigue en borrador. En proceso se completa y se cobra, y editar o eliminar abre *Reabrir plan*, que cancela el presupuesto vigente; si el usuario no puede reabrir (no es administrador ni el profesional asignado) recibe el aviso de permisos y nada se mueve. Antes el bloqueo dependía del presupuesto, así que un plan activo sin presupuesto era editable y un borrador reabierto estaba congelado. Completar exige además `plans.write`. Pineado en `frontend/tests/e2e/tablet-plan-gates.spec.ts`.
- fix(treatment_plan): la tarjeta *Plan activo* del resumen del paciente enlazaba a la ruta antigua `/treatment-plans/{id}`, que solo existe como redirección del servidor. Navegando dentro de la app (p. ej. agenda → ficha → plan) el cliente aplicaba la regla literalmente y acababa en `/treatments/plans/**`: error al cargar y «No encontrado» hasta refrescar. Ahora enlaza a `/treatments/plans/{id}`. Además, la página del plan muestra el esqueleto de carga hasta que responde la primera petición, en vez de pintar «No encontrado» antes de haber cargado. Pineado en `tablet-touch.spec.ts`.

- feat(treatment_plan): **un plan con cobros solo se puede cerrar.** `DELETE /treatment-plans/{id}` y `POST /close` con motivo `cancelled_by_clinic` responden 409 `PLAN_HAS_COLLECTIONS` si el paciente pagó algo del plan; el cliente muestra «Error, hay algún cobro en el plan de tratamiento. Favor de cerrar este plan de tratamiento» y la ventana de cierre sigue abierta para elegir otro motivo. `payments` entra en `manifest.depends` (solo lectura). `PlansListPanel` ya no dice «eliminado» cuando el borrado falla.
- test(treatment_plan): las pruebas de sesiones quitaban su captura con `event_bus._handlers.pop(...)`, que borraba también los handlers reales (el de `payments` que genera los cargos); las pruebas que corrían después lo hacían sin ellos. Ahora usan `event_bus.unsubscribe(evento, _capture)`.
- feat(treatment_plan): borrar un plan borra también sus presupuestos, en la misma transacción (`BudgetService.delete_for_plan`).
- feat(treatment_plan): en *Paciente → Clínica → Planes* **toda la tarjeta
  del plan abre el plan** (clic o Enter; `role="link"`). Se quitan los
  botones *Ver detalle* y *Programar cita* de `TreatmentPlanMiniCard`;
  *Activar* y *Generar presupuesto* se quedan y no propagan el clic. El
  evento `schedule` de la tarjeta y de `PlansListView`, y
  `handleSchedule` en `PlansMode`, desaparecen con el botón.

- feat(treatment_plan): **reabrir un tratamiento completado por error.**
  Nuevo `PATCH /treatment-plans/{id}/items/{item_id}/reopen`
  (`plans.write`): la línea y la sesión que la cerró vuelven a
  `pending`, el tratamiento del odontograma vuelve a `planned`, un plan
  `completed` vuelve a `active` y el historial anota `item_reopened`.
  Publica `treatment_plan.item_session_reopened` y `payments` retira el
  cargo, así que **ya no queda como pendiente de cobro**; lo cobrado queda
  como saldo a favor. En varias sesiones solo se reabre la última. Rechazado
  en un plan cerrado. El botón **Reabrir tratamiento** de la ventana del
  tratamiento sale ahora en cualquier tratamiento completado (antes solo en
  los cerrados, y solo desbloqueaba acciones) y pide confirmación diciendo
  qué cargo se retira y qué pasa con lo cobrado.

- feat(treatment_plan): **receta médica** desde la ventana del tratamiento.
  Se elige el doctor que firma (por defecto el asignado, con su cédula a la
  vista), se escriben las indicaciones y **Generar receta** abre un PDF
  listo para imprimir con los datos de la clínica, nombre y cédula del
  doctor, paciente, edad y fecha. Queda guardada en la tabla nueva
  `treatment_prescriptions` (migración `tp_0013`) con el doctor copiado,
  para que la reimpresión diga lo mismo; sobrevive a quitar el tratamiento
  del plan y entra en la exportación del paciente. Permisos nuevos
  `prescriptions.read` / `prescriptions.write`. Endpoints:
  `GET|POST /treatment-plans/{id}/items/{item_id}/prescriptions` y
  `GET /prescriptions/{id}/pdf`.

- change(treatment_plan): las acciones de la ventana del tratamiento ya no
  son iconos bajo **Acciones**: van al pie como botones de texto azules
  del mismo tamaño, en una rejilla de columnas iguales con el texto
  centrado. **Marcar como completado** sigue en verde y ocupa la última
  celda (un tratamiento pendiente queda en un 2×2); **Reabrir tratamiento**
  ocupa ese sitio cuando ya está completado. El diálogo pide la forma de
  texto a los módulos que las aportan con `labelled: true`.

- change(treatment_plan): **cada tratamiento del plan tiene su propia
  ventana**, y la fila se queda solo con lo que cambia el plan.

  La fila llevaba cinco objetivos a un dedo de distancia — nota,
  recordatorio, chip de doctor, ✓ y papelera — donde los dos que *abren*
  algo se ven igual que los dos que *cambian* el plan. Tocar el recuadro
  abre ahora `PlanItemDetailModal`: profesional, precio, dientes, sesiones
  y el estado del dinero, con *añadir nota*, *programar recordatorio* y
  *cobrar* agrupados bajo el epígrafe **Acciones**. Las tres las aportan
  sus módulos (`clinical_notes` y `recalls` por
  `odontogram.condition.actions`, `payments` por el slot nuevo
  `treatment_plan.item.collect`); el plan no importa código de ninguno.

- feat(treatment_plan): al completar un tratamiento, la aplicación pregunta
  **si se cobra ahora o se deja pendiente**. Es el momento más barato para
  cobrar —el paciente sigue en el sillón— y las dos salidas son respuestas
  de verdad: una clínica que factura a fin de mes deja pendiente todos los
  días, y el importe queda igual en «pendiente de cobrar».

  El botón de cobrar lo pone `payments` en el slot; el plan solo lo coloca
  y le pasa `{patientId, patientName, budgetId, amount}`. `ModuleSlot` no
  reenvía eventos hacia arriba, así que el aviso de «ya está cobrado» viaja
  como un callback dentro del ctx — el ctx es todo el contrato.

- fix(treatment_plan): la ficha de un tratamiento completado que aún tiene
  cobro pendiente ya no dibuja un pie vacío. No tenía nada que ofrecer ahí
  —ni completar ni reabrir— y una barra gris en blanco se lee como un control
  que no cargó.

- feat(treatment_plan): un tratamiento completado y sin nada por cobrar se
  muestra como **Cerrado**, y su ventana ofrece **Reabrir**.

  «Cerrado» se **deduce** (completado + `pending <= 0`), no se guarda: así
  no puede desincronizarse del libro, y una devolución registrada en
  Finanzas lo reabre sola sin que nadie tenga que acordarse de tocar el
  plan. Sin `payments` legible no hay insignia — «no queda nada pendiente»
  y «no podemos ver el dinero» no son la misma afirmación.

  **Reabrir desbloquea las acciones de la ventana y nada más.** No
  descompleta el tratamiento y no devuelve el dinero. Descompletarlo
  dejaría en `payments` una entrada *earned* por un trabajo que el plan
  ya no da por hecho —dinero que el paciente seguiría pareciendo deber— y
  `payments` no tiene hoy ningún manejador que revierta eso. Hacerlo bien
  pide un evento de reversión en `payments`; hasta entonces, el botón no
  promete lo que el libro no cumpliría.

- refactor(treatment_plan): el nombre visible de un ítem sale de
  `planItemName`, compartido por la lista, la ventana del tratamiento y el
  aviso de cobro. Eran tres copias en camino, y un nombre distinto entre
  ellas se lee como dos tratamientos distintos. De paso desaparecen tres
  errores de tipo que estaban en la baseline: la rama `migrated` lee campos
  que no están en `ClinicalType` ni en `TreatmentBrief`, y ahora lo dice en
  un sitio en vez de tropezar con ello.

### Added

- **The plan builder opens holding the patient's charted findings.** Reached
  from a patient's record, `/treatments/plans/new` now seeds its draft lines
  from `GET /treatment-plans/patient/{patient_id}/proposals` — the same
  `SUGGESTIONS` mapping that until now only ran *after* a plan existed. The
  dentist reviews and drops instead of redrawing what the clinic already
  diagnosed, and a clash with the real chart shows while drawing rather than
  as a warning at the end. `CatalogItemBrief` gained `default_phase` so a
  seeded line carries its stage of care.

- **A dismissed finding stays dismissed for that plan.** Deleting one of the
  seeded lines now records the decision (`plan_dismissed_findings`, migration
  `tp_0012`) and the plan stops proposing it. Bound to the plan, not to the
  finding: the chart keeps showing it and the patient's next plan offers it
  again.

- feat(treatment_plan): mientras el plan se dibuja, **toda** línea es
  editable, no solo su fase y su nota. La pantalla ya prometía que nada se
  escribe hasta *Crear*; lo que faltaba era poder cobrar esa promesa. La
  corrección más frecuente en un odontograma que nadie ha contrastado
  todavía con un paciente no es «tratamiento equivocado» sino «pieza
  equivocada» —el 16 por el 26, un segundo premolar por un primero— y hasta
  ahora la única salida era borrar la línea y volver a buscar el
  tratamiento: mucho trabajo para deshacer un toque.

  - **Piezas.** Cada una es una chapa con su ✕, y *Elegir en el
    odontograma* le entrega el gráfico a esa línea: un toque añade la pieza,
    otro la quita, y el gráfico resalta lo que la línea lleva. Se elige
    donde se eligió la primera vez. Un campo numérico o un desplegable de
    32 dientes serían una segunda manera, peor, de decir lo mismo en una
    pantalla cuyo argumento entero es que el odontograma es el formulario.
  - **Caras**, solo donde el catálogo describe el tratamiento por caras.
    Se guardan en orden de odontograma pase lo que pase, para que las
    mismas tres caras no se impriman distinto según cuál se marcó última.
  - Precio y tratamiento siguen sin editarse, y por escrito en el
    componente: el precio es del catálogo y cambiarlo pertenece al
    presupuesto; cambiar el tratamiento es quitar y añadir.

  El límite es el que ya existía: una vez creado el plan, editar pasa por
  **Reabrir**. Esta ventana es barata justamente porque no hay nada escrito
  detrás.

  Aparece un estado nuevo que antes no era alcanzable —una línea de diente
  sin ninguna pieza, porque ahora se le pueden quitar— y se resuelve donde
  toca: se puede vaciar (una corrección tiene que poder pasar por ahí), se
  marca en ámbar en la lista y bloquea *Continuar* nombrando el
  tratamiento. El servidor contesta a eso con un 422; mejor una frase junto
  al botón.

  Las reglas viven en `planDraftLineUtils.ts`, fuera del componente, con 19
  pruebas unitarias: son lo que merece pinchar, y montar un componente es
  mal sitio para probarlas. Dos pruebas e2e cubren las dos caras del
  límite: editar antes de crear, y el gráfico cerrado después.

- fix(treatment_plan): dibujar sobre una cara concreta nunca registraba la
  cara. `addTreatment` leía `requires_surfaces` del ítem que devuelve
  `/catalog/items/search`, y ese resumen no trae el campo, así que la
  condición era siempre `undefined`. Ahora se resuelve contra el catálogo
  de odontograma que la pantalla ya carga, con el valor del propio ítem por
  delante para quien sí lo mande.

- feat(treatment_plan): hacer clic en el odontograma de un plan en curso ya
  no es un silencio. El cartel de «Plan bloqueado» vive arriba del todo y el
  odontograma queda un scroll por debajo, así que lo primero que hace
  cualquiera es pinchar un diente y ver que no pasa nada.

  `PlanDetailView` escucha el nuevo `readonlyInteraction` del gráfico y
  compone el aviso donde se saben las dos cosas que hacen falta: el estado
  del plan y los derechos de quien mira. Las ramas siguen a los botones que
  de verdad están en pantalla — el aviso no ofrece **Reabrir** si la cabecera
  no lo está ofreciendo, porque proponer una acción que el usuario no puede
  ejecutar es peor que el silencio:

  - con `can_reopen` (plan en `pending`/`active` y quien mira es
    administrador o profesional asignado): el aviso lleva **Reabrir**, que
    abre el mismo modal de confirmación que la cabecera. Reabrir tira un
    presupuesto que el paciente puede haber visto, así que el aviso es un
    atajo a la decisión, nunca la decisión;
  - plan en curso sin esos derechos: se dice de quién es reabrirlo;
  - plan completado o cerrado: se dice que ya no admite cambios;
  - sin `odontogram.write` (el `readonly` que baja de la ficha): se dice que
    falta el permiso, porque ahí reabrir no arreglaría nada.

  El aviso lleva un `id` fijo, así que pinchar tres dientes seguidos
  actualiza un único toast en vez de apilar una columna.

- chore(treatment_plan): `PlanDraftChart` se marca `data-dense`, por lo mismo
  que `OdontogramChart`, cuyo `ToothQuadrant` comparte.

- fix(treatment_plan): el buscador de tratamientos y plantillas levantaba el
  teclado nada más abrirse en tablet. El panel abre a propósito sobre una
  lista —los tratamientos que la clínica usó últimamente, que suelen ser la
  respuesta— y el `autofocus` la tapaba: en una tablet en horizontal, cuatro
  de las ocho filas quedaban detrás del teclado. Ahora el campo se enfoca con
  ratón y se deja en paz con el dedo (`useDevice().isTouch`), que es la regla
  del repo: decide la capacidad, no el ancho de la ventana.

  Auditado a 767×1024 con puntero grueso: ningún control por debajo de 44 px
  ni en el panel ni en la página, sin desbordes horizontales, y tocar un
  diente, una fila reciente o un resultado de búsqueda funciona. El selector
  de plantillas del detalle de plan pasa igual (tarjetas de 232×97–132 px).

- fix(treatment_plan): añadir una sesión a mano devolvía 500 y no guardaba
  nada. `add_session_manual` agregaba la fila a la colección y devolvía la
  partida **sin hacer flush**; `id` es un `default=uuid4` de Python, así que
  llegaba a `None` al serializador y Pydantic rechazaba la respuesta — con lo
  que la fila se revertía. El endpoint no había funcionado nunca: un
  tratamiento largo solo podía tener las sesiones que trajera su plantilla de
  catálogo, y no había forma de añadirle una revisión después.

  Encontrado al reconstruir el acto quirúrgico del plan de Juan Pérez, que
  lleva ocho sesiones de seguimiento.


- feat(treatment_plan): **el alta de plan se dibuja primero y se firma
  después.** La pantalla abre en un odontograma en blanco; tocas una pieza,
  dices qué necesita, y solo cuando el plan ya está en pantalla pregunta de
  quién era la boca.

  El orden anterior era el inverso —paciente, título, profesional, y el
  «qué» lo construías luego desde el odontograma— y es el inverso del que
  sigue quien acaba de mirar una boca. Además había **dos** altas: la
  página `/treatments/plans/new` y una ventana dentro de la ficha del
  paciente que ni siquiera ofrecía plantillas, que es justo la que se usa en
  tablet. Ahora hay una sola pantalla y los dos caminos llegan a ella; desde
  la ficha, con el paciente y el título ya puestos.

  Piezas nuevas, todas en el módulo:

  - `PlanDraftChart` — el odontograma sin paciente. Deliberadamente **no** es
    `OdontogramChart`: aquel está atado a un paciente, lo consulta y escribe
    tratamientos en el servidor, y aquí no hay ni paciente ni nada que
    escribir. Comparte lo que importa — el mismo `ToothQuadrant`, así que un
    diente se ve, se resalta y se toca igual — y la misma escalera de zoom,
    que está medida contra tablets reales.
  - `PlanTreatmentSearch` — el panel que se abre al tocar. Antes de teclear
    ofrece *usados recientemente*; al teclear busca plantillas y catálogo a
    la vez. Una plantilla elegida desde una pieza se despliega en cliente:
    sus líneas por diente toman esa pieza, las de boca completa ninguna, y
    todas quedan editables antes de escribir nada.
  - `PlanDraftLines` — el plan mientras se dibuja, con fase y nota por línea.

  **Nada se escribe hasta *Crear***: el paciente (si es nuevo), el plan y
  todas las líneas van en una secuencia al final. Un plan abandonado a
  media exploración no deja rastro.

  La contrapartida, y es real: **el odontograma está en blanco**, así que
  nada impide planificar una corona sobre una pieza ausente. El paso del
  paciente cierra el hueco hasta donde puede —lee su odontograma real y
  avisa de lo que choca— pero **avisa, no bloquea**. Un dentista que dice
  que el plan está bien acierta más que una regla sobre el plan.

  La comprobación de «pieza ausente» lee `tooth_records.general_condition`,
  no los tratamientos: una pieza que falta es una propiedad del diente, no
  algo que alguien tratara, y una comprobación que solo mirara tratamientos
  no habría avisado de nada (en el juego de datos de demo hay 6 piezas
  ausentes y **cero** tratamientos de tipo `missing`/`extraction`). Los
  tratamientos se leen igualmente, para el caso de la extracción ya hecha, y
  a través del composable del odontograma porque normaliza `performed` a
  `existing`; llamando a la URL a pelo vuelve el valor crudo y la
  comparación no casa nunca en silencio.

  `POST /treatment-plans/{id}/catalog-items` pasa a recibir **líneas**
  (`{lines: [{catalog_item_id, tooth_numbers, surfaces, phase, notes}]}`) en
  vez de una lista de ids con una lista de dientes común: un plan dibujado
  en un odontograma lleva una corona en el 16 y una obturación en el 24, y
  una lista de dientes por petición solo sabría decir «todos estos en todos
  esos». `_create_treatments` acepta ahora caras y nota, que solo llegan de
  una línea dibujada a mano — una plantilla describe una forma, y ni la cara
  con caries ni una nota sobre este paciente pertenecen a una forma.

  Se retira `TreatmentPlanModal.vue`. **Ojo con lo que se va con él**: su
  rama de edición (título, profesional, notas y el reasignado en cascada de
  los ítems pendientes) ya era inalcanzable antes de este cambio —ninguna
  pantalla le pasaba `:plan`—, así que `PUT /treatment-plans/{id}` y su
  `reassign_pending_items` se quedan sin ningún llamador en la interfaz. El
  comportamiento sigue cubierto por los tests de backend; si se quiere editar
  un plan ya creado, hay que darle una pantalla nueva.

- fix(treatment_plan): el selector de plantillas decía «Todavía no hay
  plantillas» mientras las cargaba. El render de servidor llega con la
  lista vacía y sin petición hecha, así que el estado vacío se mostraba
  como si fuera una respuesta —y en una tablet lenta dura lo suficiente
  para que alguien se lo crea y se ponga a construir el plan a mano. Ahora
  el bloque gris cubre hasta que la primera petición vuelve, y el aviso
  solo aparece cuando de verdad no hay ninguna.

- change(treatment_plan): la lista de planes de la pestaña *Clínico* deja
  de mostrar los borradores. Esa vista responde a «en qué punto está el
  tratamiento de este paciente», y un plan a medio escribir no es una
  respuesta: ocupaba sitio y empujaba hacia abajo los planes que sí
  importan. Siguen listados, editables y borrables en *Tratamientos →
  Planes → Todos*, cuyo filtro por estado incluye *Borrador*, así que no
  queda trabajo inalcanzable. Los planes anteriores (completados y
  cerrados) se mantienen plegados al final de la lista.

  Filtrado por exclusión y no por lista blanca, para que el grupo
  `otherPlans` siga cazando cualquier estado que este fichero aún no
  conozca. `hasPlans` cuenta ahora sobre lo visible: un paciente cuyos
  únicos planes sean borradores ve el estado vacío, no un encabezado sin
  nada debajo. `clinical.plans.drafts` queda sin uso — señalada, no
  borrada.

- change(treatment_plan): *Completados* y *Cerrados* se funden en una sola
  sección plegable, **Planes anteriores**. Para quien lee el historial son
  la misma cosa —tratamiento terminado— y tenerlos separados dejaba el
  pasado del paciente detrás de dos paneles colapsados distintos. Se
  mantiene el orden que envía el servidor, así que lo más reciente queda
  arriba, y la etiqueta de estado de cada tarjeta sigue diciendo cuál de
  los dos es. Nueva clave `clinical.plans.previous` (es y en);
  `clinical.plans.completed` y `clinical.plans.closed` quedan sin uso —
  señaladas, no borradas.

- fix(buscador): buscar por nombre no funcionaba, por tres motivos distintos.
  1. En la pestaña **Todos** no filtraba **nada**: el cliente enviaba
     `search=`, pero ni el endpoint ni `TreatmentPlanService.list` tenían ese
     parámetro y FastAPI descarta los desconocidos en silencio, así que la
     lista volvía entera y parecía rota en vez de vacía.
  2. **El nombre completo no encontraba a nadie.** La bandeja comparaba la
     cadena entera contra cada columna por separado, y ninguna contiene
     «Juan» y «Pérez» a la vez. Ahora se parte en palabras: cada una debe
     casar con algo (AND entre palabras, OR entre columnas), así que «Juan
     Pérez» y «Pérez Juan» llegan al mismo paciente y «Juan» solo sigue
     listando a todos los Juanes.
  3. **Los acentos rompían la búsqueda.** `ILIKE` entre «Perez» y «Pérez» no
     casa. Ambos lados se pliegan con `translate()` — no con la extensión
     `unaccent`, que exige `CREATE EXTENSION` y en Postgres gestionado suele
     estar vetada.
- feat(ui): la pestaña «Listado» pasa a llamarse **Todos**.
- fix(ui): una búsqueda sin resultados decía «Este plan no tiene
  tratamientos» —el mensaje de un plan vacío, no el de una búsqueda—.
  Nadie lo había visto porque, mientras la búsqueda no filtraba, la lista
  nunca se quedaba vacía; arreglarla lo destapó. Clave propia:
  `treatmentPlans.noSearchResults`.
- feat(planes): **historial de cambios** al pie de la ficha. Nueva tabla
  `treatment_plan_history` (migración `tp_0011`), escrita en cada transición,
  alta/baja de tratamiento y reasignación. La fila entra en la **misma
  transacción** que el cambio que describe: un historial que sobreviva a un
  cambio revertido es peor que no tenerlo. Endpoint
  `GET /treatment-plans/{id}/history`.
- feat(planes): **Reabrir** se limita a un administrador o a un profesional
  asignado al caso — el del plan o el de cualquiera de sus tratamientos, así
  que un plan con varios especialistas los admite a todos. Los derechos se
  derivan de quién está asignado *ahora*, de modo que reasignar el plan
  traspasa el permiso sin más bookkeeping. Si el profesional asignado no tiene
  cuenta, solo el administrador puede.
  El puente entre cuenta y ficha de directorio es el número de colegiado
  (`users.professional_id` ↔ `professionals.license_number`): `Professional`
  no tiene `user_id` a propósito. Es blando, y por eso la regla vive en el
  servidor y el cliente pregunta en vez de imitarla.
- feat(planes): `reopen` acepta `active` además de `pending`. Con la
  activación por asistencia, la regla anterior dejaba sin reabrir justo los
  planes recién arrancados — los que más se editan, porque esa primera visita
  es donde se decide el tratamiento real.
- feat(planes): completar un tratamiento también arranca el plan. La regla
  de asistencia escuchaba solo `appointment.completed`, así que marcar un
  tratamiento directamente sobre el plan —sin cita, que es como se registra
  a menudo una primera consulta— dejaba el plan en `pending` con trabajo ya
  hecho contra él. Los tres caminos que terminan un tratamiento
  (`_finalize_item`, `on_appointment_completed`, `on_treatment_performed`)
  pasan ahora por `_sync_plan_lifecycle`, que ejecuta el arranque y después
  el cierre. El orden importa: `_check_and_complete_plan` solo cierra planes
  `active`, de modo que un plan de un solo tratamiento confirmado y ejecutado
  del tirón se quedaba encallado en `pending` con todo completado; ahora
  cruza las dos transiciones y acaba en `completed`.
- feat(scripts): `backfill_started_plans.py` arranca los planes cuyo paciente
  **ya vino** antes de que la asistencia moviera el estado. La regla en
  caliente escucha `appointment.completed`, así que solo sirve para visitas
  futuras; esto es la pasada única sobre las que ya ocurrieron. Cuenta como
  «el paciente vino» cualquiera de las dos cosas: una cita completada ligada
  al plan, **o** un tratamiento del plan marcado como realizado. Lo segundo
  no sobra: una clínica puede marcar un tratamiento directamente sobre el
  plan (`completed_without_appointment`) —así se registra a menudo una
  primera consulta— y entonces no existe ninguna cita. Un backfill atado solo
  a citas pasaría de largo justo por esos. Solo mueve planes en `pending`.
  Va en seco por defecto; escribe con `--apply`.
- fix(ui): en la ficha del paciente, la sección que agrupa los planes por
  estado decía PENDIENTES sobre tarjetas con el badge «En curso». Usaba
  `clinical.plans.pending`, que es la palabra del **contador de
  tratamientos** («8 pendientes») y no del estado del plan — renombrar esa
  clave habría roto el contador. La sección apunta ahora a
  `treatmentPlans.status.pending`, el mismo vocabulario que el badge, así
  que los dos quedan sincronizados por construcción.

- feat(planes): la primera consulta a la que acude el paciente pone el plan
  **En tratamiento**. Hasta ahora `pending → active` solo ocurría al aceptarse
  el presupuesto, de modo que un plan con el paciente ya sentado en el sillón
  seguía figurando en «Confirmar». Ahora `appointment.completed` activa todo
  plan al que esa cita esté ligada. La consulta que activa **no** necesita
  llevar tratamientos marcados como ejecutados: una primera visita de
  diagnóstico normalmente no marca ninguna, y es justo la que arranca el plan,
  así que la consulta de activación es más amplia que el bucle de completado.
  Sigue siendo idempotente y solo mueve planes en `pending`: un `draft` no se
  salta la confirmación.
- fix(bandeja): «Por presupuestar» y «Esperando paciente» pasan a admitir
  `pending` **y** `active`. Ambas colas hablan del presupuesto, no del plan;
  atadas a `pending` habrían dejado escapar justo los planes recién activados
  por asistencia, y el presupuesto sin firmar habría dejado de perseguirse en
  cuanto el paciente pisara la clínica.

- fix(bandeja): un plan reabierto y vuelto a confirmar desaparecía de la
  bandeja. `reopen` cancela el presupuesto enlazado pero deja el enlace
  puesto; al volver a confirmar, `create_from_plan_snapshot` creaba un
  presupuesto nuevo — su comprobación de idempotencia ignora los
  cancelados — y `confirm` lo tiraba, porque solo guardaba el enlace
  cuando `budget_id` era NULL. El plan se quedaba en `pending` apuntando
  a un presupuesto cancelado, combinación que no cumple el `tab_where` de
  ninguna pestaña, así que solo se le veía en *Listado*; el presupuesto
  bueno quedaba huérfano. Ahora `confirm` adopta siempre el presupuesto
  que se le devuelve. El efecto en cadena era peor de lo que parecía:
  `budget` localiza el plan a activar buscando hacia atrás por
  `treatment_plans.budget_id`, así que con el presupuesto huérfano la
  búsqueda devolvía nada, el handler de «presupuesto aceptado» se salía por
  su rama de huérfano y aceptar el presupuesto **no** llevaba el plan a
  `active`; el presupuesto enlazado ni siquiera se podía enviar, porque
  estaba cancelado.
- feat(bandeja): nueva primera pestaña **En curso** — los planes en marcha
  (`pending` + `active`), del movimiento más reciente al más antiguo. Es la
  pestaña por defecto. Recepción da un plan por arrancado cuando el paciente
  acude a la consulta de diagnóstico, antes de que se acepte el presupuesto,
  de modo que una pestaña limitada a `active` escondía justo lo que estaban
  siguiendo.
- fix(ui): el paso 3 del stepper de la ficha del plan pasa a llamarse
  **En tratamiento** (antes «En curso»). Al renombrar el estado `pending`
  a «En curso» quedaba una contradicción visible: el listado decía que el
  plan estaba «En curso» mientras la ficha mostraba «En curso» como paso 3
  todavía sin alcanzar, con el plan parado en «Confirmar». «En curso» queda
  como el término paraguas de lo que está en marcha (pestaña y badge de
  `pending`), y el paso 3 nombra lo que de verdad describe: presupuesto
  aceptado y tratamiento en ejecución.
- fix(bandeja): las filas se solapaban en tablet vertical — el número de
  plan, el badge y «Tratamientos» se pisaban. El diseño decidía si la fila
  cabía en horizontal con un breakpoint de *viewport* (`md:`), y en vertical
  el viewport mide 800 px mientras la tarjeta apenas llega a 500: la fila se
  ponía horizontal en una caja que no la aguantaba. Ahora la decisión la toma
  una *container query* sobre la propia tarjeta (56rem), que es la única
  anchura que importa. Dos efectos secundarios que también se arreglan: el
  nombre largo no recortaba con puntos suspensivos porque a un flex
  intermedio le faltaba `min-w-0`, y las columnas «Tratamientos»,
  «Presupuesto» y «días en estado» ya no desaparecen en vertical — se
  reparten en una línea envuelta bajo el paciente. Cubierto por
  «bandeja rows never overlap their own text» en `tablet-touch.spec.ts`.
- fix(ui): con siete pestañas, en tablet vertical Nuxt UI repartía el ancho
  y dejaba todas las etiquetas en puntos suspensivos («En…», «Por pre…»,
  «Ce…»). Ahora la tira conserva su ancho natural y se desplaza en
  horizontal. `TreatmentPlanMiniCard` tenía el mismo mapa de colores
  desactualizado que el badge y se ha alineado también.
- fix(ui): el estado `pending` se lee **En curso** (antes «Pendiente»,
  que no decía pendiente de qué). Además `TreatmentPlanStatusBadge` no
  tenía color para `pending` ni `closed` —y sí para un `cancelled` que
  ningún plan usa—, así que un plan confirmado salía del mismo gris que
  un borrador y parecía sin tocar.

- fix(ui): on a tablet in landscape the Create button of the new-plan
  form could not be reached, and the device had to be rotated to save.
  It sits directly under two textareas at the very end of a
  document-scrolled page, so the on-screen keyboard covers it exactly
  while those fields are being typed in — and with the page already at
  its scroll end there is nothing left to scroll it clear of. Short
  viewports now carry enough room below the action row (332 px measured
  at 1024x600) to scroll it above the keyboard. Taller viewports are
  untouched.
- feat(cobros): el plan enseña el dinero. Cada sesión completada lleva su
  chip — **Cobrado** o **Quedan X** — y cada cabecera de fase, lo que queda
  por cobrar de esa fase. Antes el plan era la única pantalla de toda la
  cadena que no decía nada de dinero: se completaba un tratamiento y había
  que irse a la ficha del paciente para saber que ya se podía cobrar.

- feat(cobros): nuevo slot `treatment_plan.detail.sidebar`, donde `payments`
  pone su tarjeta con lo pendiente del paciente y el botón «Cobrar». El plan
  no importa nada de payments: le pasa el paciente, el presupuesto y el
  estado, y payments hace el resto.

- feat(plantillas): líneas opcionales. Una forma de plan rara vez es todo o
  nada: un caso ortognático necesita ortodoncia pre y postquirúrgica, pero la
  clínica puede derivarla, y la mentoplastia depende del mentón. Meterlas a la
  fuerza obligaba a aplicar la plantilla y borrar filas; dejarlas fuera,
  a acordarse de añadirlas en casi todos los pacientes. Ahora `is_optional`
  marca la línea como decisión: al aplicar la plantilla sale marcada —el autor
  la puso por algo— y se quita con un clic. Las líneas fijas no se pueden
  quitar; intentarlo es un 400.

- feat(plantillas): aplicar una plantilla dice qué se ha quedado fuera. Si la
  clínica no tiene (o ha retirado) el tratamiento de una línea, esa línea se
  omite en vez de tumbar toda la aplicación, pero vuelve en `skipped` y el
  aviso la nombra. Un plan que llega en silencio con un tratamiento de menos
  es peor que uno que lo dice. `POST .../apply-template` pasa a devolver
  `{items, skipped}`.

- fix(plantillas): el `PUT` de una plantilla respondía con las líneas
  anteriores aunque en base de datos quedaban las nuevas — el mapa de
  identidad de la sesión devolvía la colección previa. `get` ahora usa
  `populate_existing`.

- fix(ui): las etiquetas de sesión se partían letra a letra («Ape / rtur /
  a y»). La fila metía siete elementos en una línea dentro de la columna
  estrecha del plan y todos menos la etiqueta eran `shrink-0`, así que la
  etiqueta se quedaba con unos pocos píxeles y `break-words` rompía por
  carácter. Ahora importe, fecha y acciones viajan como un bloque que baja a
  la segunda línea cuando la etiqueta no conserva el 55% de la fila; en
  pantallas anchas todo sigue cabiendo en una sola línea.

- feat(propuestas): «Proponer desde el odontograma». Los hallazgos ya están
  en la ficha — un dentista marcó la caries del 16 — y volver a teclearlos
  como partidas del plan era reintroducir un hecho clínico que el sistema ya
  guarda. Ahora el plan en borrador lista los hallazgos sin tratamiento
  planificado, cada uno con el tratamiento que le propone
  (`caries → obturación`, `pulpitis en molar → endodoncia molar`, contando
  raíces por posición FDI), y con un clic entran todos. El hallazgo no se
  toca: el diagnóstico y el plan son registros distintos y la caries debe
  seguir dibujada hasta que se trate. La tabla de propuestas es criterio
  clínico comprimido y se equivocará: por eso propone lo menos invasivo y
  no crea nada hasta que se marca la fila.

- feat(plantillas): un plan se puede empezar desde una plantilla. Una
  plantilla es una forma recurrente — la secuencia de tratamientos con su
  fase — y nunca lleva dientes: esos se dan al aplicarla. La regla de
  aplicación es una sola frase, para que sea predecible: cada tratamiento
  por diente se crea una vez por cada diente indicado, los de boca completa
  una vez, y los de arcada una por arcada (las dos si no se indican
  dientes). Se envían ocho plantillas de partida (primera visita, fase
  higiénica, periodontal básico, endo + reconstrucción + corona, implante
  unitario, cordales, ortodoncia, estética) y, lo que de verdad importa,
  **cualquier plan se puede guardar como plantilla**: las formas buenas de
  una clínica son las suyas. Nuevos endpoints bajo `/plan-templates` y
  `POST /treatment-plans/{id}/apply-template`; permiso nuevo
  `plans.templates` para curarlas (leerlas basta con `plans.read`).

- feat(ui): la lista del plan se agrupa por fase del tratamiento. El dato
  ya se guardaba en cada partida desde `tp_0008` y no se mostraba en
  ninguna parte, así que un plan se leía como una lista plana en orden de
  clic. Ahora se lee como lo que es — urgencia, estabilización,
  rehabilitación — que es además como se le explica al paciente. Arrastrar
  reordena dentro de una fase; cambiar de fase es una decisión clínica, no
  un arrastre. Un plan sin fases se ve exactamente igual que antes.

- feat(ui): el formulario de alta pregunta dos cosas — quién y qué forma de
  plan — en lugar de cinco, cuatro de ellas opcionales y ninguna clínica.
  El título lo pone la plantilla, las notas se pliegan bajo «Más opciones»
  (se escriben después de ver al paciente, no al crear el plan) y el
  profesional viene preseleccionado, como ya hacía el modal: la misma
  acción daba dos planes distintos según por dónde entraras.

- fix(ui): los campos del alta ocupaban ~110 px dentro de una tarjeta
  ancha; les faltaba `w-full`.


- feat(privacy): `get_subject_contributors()` — este módulo ya responde
  cuando un paciente ejerce portabilidad o supresión
  ([ADR 0026](../../../../docs/adr/0026-subject-rights-are-a-module-contract.md)).
  Planes con sus partidas y sesiones. Registro asistencial: se conservan.

- fix(ui): pipeline pagination works — same Nuxt UI v2-props-on-v4
  problem as media and catalog.

- fix(ui): removing a plan item asks for confirmation — the removal
  cascades into the odontogram and the associated budget line, and the
  control is a bare trash icon in a list row (audit S5).

- fix(events): publish through ``event_bus.publish_after_commit(db, ...)``
  instead of announcing from inside the caller's open transaction.
  Handlers read through their own sessions, so a flushed-but-uncommitted
  row was invisible to them (audit S2). See
  [ADR 0019](../../../../docs/adr/0019-events-publish-after-commit.md).

- feat(nav)!: the module no longer owns a menu entry. The pipeline moved
  from `/treatment-plans` to `/treatments/plans` (detail and new-plan pages
  follow), reached through the "Tratamientos" section owned by `catalog`.
  Server-side 301s keep existing bookmarks and already-sent links working.
  API paths are unchanged — only the frontend routes moved.

- feat(phases): `PlannedTreatmentItem.phase` records the stage of care for
  this patient (migration `tp_0008`, `depends_on = cat_0007`). Seeded from
  the catalog item's `default_phase` when the treatment is added, then owned
  by the plan — the same extraction is an emergency for one patient and a
  planned rehabilitation step for another, so reading through to the catalog
  row would be wrong. `phase` accepted on item create/update.

- fix(professionals): ``assigned_professional_id`` on ``treatment_plans``
  and ``planned_treatment_items`` now points at ``professionals.id``
  (directory) instead of ``users.id``, matching the ``agenda``/``schedules``
  directory-professional rewire (``ag_0006``/``sch_0002``). Creating a plan
  with an assigned professional was failing with a 500
  (``ForeignKeyViolationError``) because the frontend already sends a
  directory professional id. Migration ``tp_0007`` backfills existing rows
  via the same deterministic account→profile mapping. Adds ``professionals``
  to ``manifest.depends``. ``_validate_professional_in_clinic`` now checks
  the directory instead of ``clinic_memberships``, and ``create()`` calls it
  (previously only ``update()``/``add_item`` did, so a bad id on create
  reached the database unchecked).

- refactor(scheduler): declare the ``auto_close_expired_plans`` cron job
  via ``get_scheduled_jobs()`` instead of being imported by name in
  ``app/core/scheduler.py``.

- feat(ux): ``PlanDetailView`` wires the new ``PlanNotesTimeline``
  ``item-hover`` event into the existing ``hoveredItemId`` highlight
  pipeline, so hovering or focusing a note in the timeline pulses the
  matching tooth/arch on the odontogram. Treatment-source notes resolve
  via ``itemByTreatmentId``; visit-source via ``itemByPlanItemId``;
  plan-level notes no-op.
- feat(sessions): plan items now own 1..N ``PlannedTreatmentItemSession``
  rows that capture the named, billable steps of a multi-session
  treatment (e.g. crown: "Toma de medidas" 200€ + "Colocación" 600€).
  Sessions are snapshotted from the catalog template at ``add_item``
  time (scaled if the treatment price overrides the catalog total) and
  are independent thereafter. New endpoints:
  - ``PATCH /items/{id}/sessions/{sid}/complete`` — publishes
    ``treatment_plan.item_session_completed`` (consumed by ``payments`` →
    earned ledger). Finalizes the parent item once all sessions are
    terminal and at least one was completed.
  - ``PATCH /items/{id}/sessions/{sid}/cancel`` — terminate a session
    without generating an earned entry.
  - ``PUT /items/{id}/sessions/{sid}`` — edit label/amount/notes on a
    pending session.
  - ``POST /items/{id}/sessions`` + ``DELETE /items/{id}/sessions/{sid}``
    — append/remove a session manually.
  The legacy ``PATCH /items/{id}/complete`` keeps working: it advances the
  next pending session. Migration ``tp_0006`` creates the new table and
  backfills one row per existing item.
- fix(events): ``on_treatment_performed`` handler uses
  ``SELECT FOR UPDATE SKIP LOCKED`` when looking up the matching
  planned item. Avoids a deadlock that surfaced as a client timeout
  on ``PATCH /treatment-plans/{id}/items/{id}/complete``: under the
  async-first event bus (sprint 3) the parent transaction held the
  row lock on ``planned_treatment_items`` and the handler — running
  inline before the parent commit, in a new session — blocked
  trying to update the same row. When the row is locked we skip
  silently; the originator's UPDATE drives the state transition.
- feat(plans): per-item assigned professional. `PlannedTreatmentItem` gains
  `assigned_professional_id` (FK to `users.id`, nullable). New items inherit
  the plan's doctor by default; the API and `PlanItemDoctorChip` lets the
  clinician override it (e.g. fillings by Dr A, endodontics by Dr B). When
  the plan-level doctor changes, the cascade is opt-in via a new write-only
  `reassign_pending_items` flag on `TreatmentPlanUpdate` — only pending items
  still pointing at the previous plan doctor are reassigned; explicit
  overrides and completed items are left alone. Migration `tp_0005` backfills
  existing items from the parent plan. Event payload
  `treatment_plan.treatment_added` now carries `assigned_professional_id`
  (additive, safe for the `budget` subscriber). Doctor reassignment bypasses
  the plan-lock guard (`_is_plan_locked`) — reassigning who performs a
  treatment doesn't change the patient-facing contract, so it stays
  available even after the plan is validated and the budget is active.
  Completed/cancelled items reject doctor changes (400) — the planned
  doctor is frozen at completion time. The completed-items section of
  `PlanTreatmentList` shows a read-only chip with the
  `assigned_professional_id` (the responsible clinician), not
  ``completed_by``: reception or an admin can mark items complete on
  behalf of the clinician and the chart's reference should stay on the
  treatment owner.
- fix(clinical/plans): treatment names in `PlanTreatmentList` no longer truncate with ellipsis and now take the full available row width — switched `truncate` to `break-words` and replaced the flex row with a `grid-cols-[1fr_auto]` layout so the name column grows deterministically into the free space before wrapping.
- refactor(perms): migrate hardcoded ``can('treatment_plan.plans.write')`` and ``can('clinical_notes.notes.write')`` strings in the treatment-plans page, ``PlansListPanel`` and ``VisitNotePanel`` to ``PERMISSIONS.treatmentPlans.write`` / ``PERMISSIONS.clinicalNotes.write``.
- perf(list): collapse the duplicated ``items → treatment`` eager-load
  chain in ``TreatmentPlanService.list`` into a single chain that
  attaches both ``Treatment.teeth`` and ``Treatment.catalog_item``
  through ``.options(...)``. Halves the SQLAlchemy batch queries
  per page.
- perf(cron): ``auto_close_expired_plans`` processes clinics
  concurrently behind an ``asyncio.Semaphore(5)`` instead of
  serially, so a slow clinic does not delay the rest of the run.
- chore(events): all publishers in this module now ``await
  event_bus.publish(...)`` — bus is async-first as of core sprint 3.
- docs(user-manual): reescribir pantallas con guía operativa (ES + EN).
- **0.2.0 (issue #55)** — `TreatmentMedia` model + `treatment_media`
  table dropped (migration `tp_0004`, depends on `med_0002`). Existing
  rows are migrated into `media.media_attachments` with
  `owner_type='plan_item'`; the legacy `media_type` enum maps onto the
  new `media_kind` / `media_category` / `media_subtype` columns on
  `documents`. Service methods `add_media` / `remove_media` and the
  `POST/DELETE /treatment-plans/items/{id}/media` endpoints are gone
  — clients call `POST /api/v1/media/attachments` with
  `owner_type='plan_item'` instead. New `owner_resolvers.py` registers
  the `plan_item` resolver with `media.attachment_registry` at module
  import time.

- Enrich `treatment_plan.treatment_completed` event payload with a
  `treatment_category_key` snapshot (issue #62, recalls). Allows
  sibling modules to map completed treatments to follow-up policies
  without importing catalog or treatment_plan models. Loaded via
  the existing `_treatment_loader` selectinload chain (now also
  pulls `catalog_item.category`); event-handler paths use a small
  helper query when the relationships aren't already loaded.

- Patient detail → Clínica → Planes: `PlansMode` paginates plans at
  page_size=20. `PlansListView` now exposes `page` / `total-pages`
  props and renders the shared `PaginationBar` below the grouped lists.
- Added per-module `CLAUDE.md` for AI-agent context (2026-04-27).
- Documented one string-literal event (`treatment_plan.items_reordered`)
  that is not yet in the `EventType` enum.

### Changed (frontend, 2026-04-30)

- Unified `Planes de tratamiento` and `Bandeja de planes` into a single
  page at `/treatment-plans` with six tabs (5 pipeline workflow tabs +
  `Listado`). The dedicated `/treatment-plans/pipeline` route and the
  `nav.pipeline` sidebar entry are removed; pipeline content is now
  reachable as the default tab on the merged page. Tab body extracted to
  reusable `PipelineTabPanel` and `PlansListPanel` components.

### Removed (2026-04-29)

- Legacy unlock flow (`POST /treatment-plans/{id}/unlock`,
  `TreatmentPlanService.unlock`, `treatment_plan.unlocked` event,
  ``Modificar plan`` button + modal). Superseded by the new workflow:
  ``Reabrir`` for ``pending`` plans and ``Renegociar`` from the
  budget UI for accepted budgets.

### Added (frontend, 2026-04-29 — PR2)

- Page `/treatment-plans/pipeline` (bandeja de planes) with five
  tabs powered by the new `usePipeline` composable. Search box +
  call/WhatsApp quick-actions per row.
- Workflow modals (`components/clinical/modals/`):
  `ConfirmPlanModal`, `ReopenPlanModal`, `ClosePlanModal`,
  `ReactivatePlanModal`, `ContactLogModal`.
- `useTreatmentPlans` gains `confirmPlan`, `reopenPlan`, `closePlan`,
  `reactivatePlan`, `logContact` actions wired to the PR1 endpoints.
- `PlanDetailView` exposes `Confirm` / `Reopen` / `Reactivate` buttons
  contextual to the plan status; the legacy "Cancel plan" button now
  delegates to the unified `ClosePlanModal` (closure_reason +
  closure_note).
- Navigation entry `nav.pipeline` linked to the bandeja.
- Status filter on the plans index updated to the new state set.

### Added (plan/budget workflow rework, 2026-04-29 — PR1)

- New plan states: `pending` (between confirm and accept) and `closed`
  (terminal non-completed state) with `closure_reason`, `closure_note`,
  `closed_at`, `confirmed_at` columns.
- Workflow transitions: `confirm` (draft → pending, auto-creates draft
  budget via direct call to BudgetService), `reopen`, `close`,
  `reactivate`, plus `accept_from_budget` / `reject_from_budget` for
  the budget event handlers.
- New endpoints:
  - `POST /treatment-plans/{id}/{confirm,reopen,close,reactivate}`
  - `POST /treatment-plans/{id}/contact-log`
  - `GET  /treatment-plans/pipeline` (5-tab cross-module bandeja).
- Granular permissions `plans.{confirm,close,reactivate}`.
  Receptionist role gains close + reactivate.
- Three new events with snapshot payloads:
  `treatment_plan.{confirmed,closed,reactivated}`. Subscribers
  (patient_timeline) consume payload data only — no cross-module ORM
  reads.
- `auto_close_expired_plans` cron (daily 03:00) — closes pending plans
  whose budget has been expired beyond the per-clinic threshold.
- Plan ↔ budget direct call carve-out: `confirm()` calls
  `BudgetService.create_from_plan_snapshot` synchronously (budget is
  in `manifest.depends`). Documented in CLAUDE.md.

### Removed

- Legacy `cancelled` plan status (migrated to
  `closed` + `closure_reason='cancelled_by_clinic'`).

### Removed (issue #60 — clinical-notes extraction)

- `ClinicalNote` and `ClinicalNoteAttachment` models, schemas, service
  (`notes_service.py`) and router endpoints. Ownership moved to the new
  `clinical_notes` module.
- `treatment_plan.{plan,item}_note_created` events (replaced by
  `clinical_notes.{administrative,diagnosis,treatment,plan}_created`).
- `note_body` and `attachment_document_ids` fields from
  `CompleteItemRequest`. The client now POSTs a follow-up note to
  `/api/v1/clinical_notes/notes` after a successful completion.
- `note_templates.py` (moved into `clinical_notes`).
- Frontend components `PlanNotesTimeline.vue`, `PatientClinicalNotesByPlan.vue`,
  `useClinicalNotes` composable. Replacement components are provided by
  the `clinical_notes` Nuxt layer with the same names so existing
  imports (`<PlanNotesTimeline />`) keep resolving.

## 0.1.0 — initial

- Treatment plan CRUD with status workflow.
- Items linked to catalog services and odontogram tooth treatments.
- Clinical notes at plan and item level with media attachments.
- Bidirectional sync with `budget` via events.
- Subscribes to `appointment.completed`, `budget.accepted`,
  `odontogram.treatment.performed`.
