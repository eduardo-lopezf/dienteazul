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

# Detalle del plan de tratamiento

Vista del plan: cabecera con paciente, profesional y estado;
columna principal con los ítems (catálogo o tratamiento odontograma)
y columna lateral con presupuesto enlazado, ejecuciones y contactos.
Aquí se confirma, sincroniza con el presupuesto, marca ítems como
ejecutados y se cierra o reactiva.

## Construir el plan

Hay tres formas de meter tratamientos en un plan en borrador, y se
combinan:

- **Aplicar plantilla.** Trae una forma completa de plan (ver
  [Nuevo plan](./treatments_plans_new.md)). Se puede aplicar varias
  veces, así que un plan puede ser fase higiénica + implante
  unitario. La ventana lleva un buscador que filtra las plantillas por
  nombre y por los tratamientos que llevan dentro; aquí no ofrece
  tratamientos sueltos, porque para eso ya está el odontograma. Las
  plantillas aparecen **agrupadas por especialidad**; las que la clínica
  guardó de sus propios planes van primero, bajo *De la clínica*. Solo
  salen las de las especialidades habilitadas.
- **Proponer desde el odontograma.** El botón aparece con un número
  cuando el paciente tiene hallazgos marcados en la ficha para los que
  no hay nada planificado. La lista empareja cada hallazgo con el
  tratamiento que le corresponde — caries → obturación, pulpitis en
  molar → endodoncia molar — y con **Añadir** entran todos. El
  hallazgo se queda en el odontograma: el diagnóstico y el plan son
  cosas distintas y la caries sigue ahí hasta que se trate.
  Desmarca la fila si la propuesta no encaja y añádelo a mano desde
  la barra.
- **Barra de tratamientos.** Elige el tratamiento y haz clic en el
  diente. El tratamiento **sigue armado** después de aplicarlo, así
  que 16, 26 y 36 son tres clics, no tres búsquedas. La chapa de la
  cabecera dice qué está armado; la ✕ o `Esc` lo sueltan. Para un
  cuadrante entero, usa los botones **Cuadrante 1–4** que aparecen
  junto a la chapa: pide confirmación nombrando las piezas antes de
  crear nada.

La lista del plan se agrupa por **fase**: urgencia, estabilización,
rehabilitación, mantenimiento. La fase de cada partida sale del
catálogo. Arrastrar reordena dentro de una fase; para mover algo a
otra fase, cambia la fase del tratamiento.

**Guardar como plantilla** está en el menú **···**: se guardan los
tratamientos y sus fases, no los dientes ni los precios.

## Calendario de pagos

La tarjeta **Calendario de pagos** guarda lo que se pactó cobrar y
cuándo, que es una pregunta distinta de «qué se debe por trabajo
hecho» — esa la responde la tarjeta de cobros. En un caso grande el
dinero se pacta por adelantado, así que es normal que una diga 0 y la
otra vaya al día. **No se suman**: las dos se saldan contra los mismos
pagos.

**Pactar calendario** propone tres repartos del total del plan: por
fases (cada fase, su precio), 30/40/30 y mensual. A partir de ahí cada
plazo lleva su **etiqueta**, su **fecha** y su **importe**, los tres
editables: el reparto sólo escribe el primer borrador. Así se pactan
cosas como «5.000 a la firma y el resto en seis mensualidades» — elige
el reparto mensual con siete plazos y ajusta los importes.

Los plazos tienen que sumar el total del plan; mientras no cuadren, el
aviso dice cuánto suman y el botón de guardar no deja continuar. La fecha puede quedarse en blanco — un hito
como «antes de la cirugía» no tiene fecha hasta que se agenda, y sin
fecha nunca aparece como vencido.

Los plazos se cubren en orden con lo que el paciente va pagando, y cada
uno muestra **Pendiente**, **Parcial**, **Pagado** o **Vencido**.

**Editar** (el lápiz) abre el calendario tal como se pactó, no un
reparto nuevo. Cada fila se puede quitar, o añadir otra justo debajo —
que es lo que hace falta para partir un plazo en dos cuando el paciente
no puede con uno. Se puede renegociar aunque ya se haya cobrado: lo
pagado vuelve a cubrir los plazos nuevos en orden.

Anular un calendario no lo borra: un acuerdo superado es parte de lo que
pasó.

## De un vistazo

- **Estado y chip.** El chip en la cabecera refleja el estado:
  `draft`, `pending`, `active`, `completed`, `closed`. Las acciones
  cambian según el estado.
- **Ítems** — añadir, reordenar, completar. Cada ítem referencia un
  ítem del catálogo y, opcionalmente, un tratamiento del odontograma.
  Al completar un ítem se publica
  `treatment_plan.treatment_completed` (con `treatment_category_key`
  para recalls).
- **Doctor por tratamiento.** Cada ítem lleva su propio
  `assigned_professional_id`. Los nuevos ítems heredan el doctor del
  plan. Pulsa el chip de color junto al nombre del tratamiento para
  asignar a otro profesional (p. ej. empaste por Dr. A, endodoncia
  por Dr. B). Cuando intervienen dos o más doctores en el plan, el
  color del chip deja visible la mezcla de un vistazo. El chip
  sigue editable mientras el ítem esté pendiente, incluso después
  de validar el plan y de que el presupuesto esté activo —
  reasignar es operativo y no cambia el acuerdo con el paciente.
  Al completarlo, el chip pasa a ser un indicador de solo lectura
  que sigue mostrando `assigned_professional_id` (el doctor
  responsable del tratamiento); marcarlo como completado puede
  hacerlo recepción o un admin en nombre del clínico, así que
  "quién pulsó Completar" no es la referencia del chart.
- **Presupuesto enlazado.** Botones **Generar presupuesto** /
  **Enlazar con presupuesto existente** / **Sincronizar** según el
  caso. El plan publica `treatment_plan.treatment_added /
  _removed / budget_sync_requested` para que `budget` mantenga el
  presupuesto al día.
- **Contactos** — historial de toques de recepción. Útil cuando el
  plan está en *pendiente* esperando aceptación.
- **Notas clínicas.** Pueden engancharse al plan desde el módulo
  `clinical_notes` (slot `patient.detail.clinical.notes`).
- **Ficha del tratamiento.** Toca el recuadro de un tratamiento y se
  abre su ventana: profesional, precio, dientes, sesiones y el estado
  del dinero (ejecutado, cobrado, pendiente). Al pie, como botones
  azules del mismo tamaño, están **Añadir nota** (o **Notas (n)** si ya
  tiene), **Programar recordatorio**, **Cobrar** (solo si queda algo
  pendiente) y **Receta médica**; en la última casilla, **Marcar como
  completado** en verde, o **Reabrir tratamiento** si ya está hecho. La
  fila se queda solo con lo que cambia el plan
  (completar, quitar), que es lo que evita confundir «abrir algo» con
  «cambiar el plan» a un dedo de distancia.

## Qué toca ahora

Bajo el título, una franja dice **la única cosa** que hace avanzar el
plan, y lleva el botón que la hace. Existe porque un plan cambia de
manos tres veces —el dentista lo planifica, el paciente acepta el
presupuesto, recepción reserva el sillón— y el paso de una a otra no se
veía: planes confirmados se quedaban parados con el presupuesto sin
enviar, sin que nadie supiera que le tocaba.

| La franja dice… | Porque… | Y el botón lleva a… |
|---|---|---|
| **Añade los tratamientos** | el borrador está vacío | — (el odontograma o una plantilla) |
| **Confirma el plan** | hay tratamientos y sigue en borrador | *Confirmar plan* |
| **Genera el presupuesto** | el plan avanzó sin presupuesto | *Generar presupuesto* |
| **Envía el presupuesto al paciente** | existe pero está sin enviar | el presupuesto |
| **Esperando respuesta del paciente** | está enviado; le toca a él | el presupuesto |
| **El presupuesto ha caducado / lo rechazó / está anulado** | hay que renovarlo o renegociarlo | el presupuesto |
| **N tratamientos sin presupuestar** | se añadieron después de confirmar | *Presupuestar lo añadido* |
| **Agenda la primera / la próxima cita** | quedan tratamientos y no hay cita futura | *Programar cita* |
| **Próxima cita: …** | todo en orden | — |
| **Todos los tratamientos están hechos** | solo queda cobrar y cerrar | — |

Es siempre **una sola**: una lista de todo lo pendiente es un informe, y
el informe es justo lo que nadie leía. En un plan terminado o cerrado la
franja no aparece. En la ficha del paciente sale igual, botones incluidos;
quien no pueda escribir en la historia clínica ve la frase sin ellos.

El color dice de quién es el turno: azul, tuyo; ámbar, algo que se ha
torcido; verde o gris, nada que hacer.

## Confirmar un plan

> Requiere `treatment_plan.plans.confirm`.

1. Sobre un plan en `draft`, pulsa **Confirmar**.
2. El plan pasa a `pending` y la app Presupuestos crea su presupuesto en
   borrador al instante.
3. Si el presupuesto no llegó a crearse, el siguiente paso del plan es
   **Generar presupuesto**, que lo crea.

**Si la clínica exige consentimiento informado** (app Expediente clínico,
activado por defecto), el plan no se confirma hasta que el paciente firme
una carta de consentimiento informado escrita para ese plan. Al pulsar
*Confirmar* aparece el aviso *Falta el consentimiento informado* con el
botón **Crear la carta**, que lleva a los consentimientos del paciente:
la carta que se escribe ahí queda ligada al plan y, una vez firmada, se
vuelve al plan con *Volver al plan* y se confirma. La regla se apaga en
*Configuración → Clínica → Plantillas de consentimiento*.

**Marcar un tratamiento como realizado sin carta.** En un plan ya en curso
al que le falta la carta (se confirmó antes de exigirla, o el paciente la
revocó), al marcar un tratamiento como realizado la pantalla pregunta
primero: **Crear la carta** o **Marcar como realizado sin carta**. Si se
sigue sin ella, el plan muestra en rojo *Falta la carta de consentimiento
informado* y cada tratamiento realizado la marca *Sin carta*, hasta que la
carta se firme.

**Si la app Presupuestos no está habilitada**, el plan confirmado pasa
directamente a *En tratamiento*: no hay presupuesto que aceptar y no se
ofrecen las acciones de presupuesto. Cuando la app se habilite, el plan
ofrecerá **Generar presupuesto**.

## Qué se puede hacer según el estado del plan

Lo que ofrece un tratamiento depende de dónde esté el plan, no de si
tiene presupuesto:

| El plan está… | En el tratamiento puedes… |
|---|---|
| **Borrador** | Editarlo y **eliminarlo** (desde su ventana o la papelera de la fila). Completar o cobrar **pide confirmar el plan** primero. |
| **En proceso** (en curso o activo) | **Completar**, **cobrar** y **añadir** tratamientos nuevos. Editar o eliminar uno ya aceptado **pide reabrir el plan**. |
| Completado o cerrado | Consultar; reactivar el plan es la puerta de vuelta. |

- **Cobrar o completar en un borrador** abre la ventana *Confirmar plan*
  con el motivo escrito: «Para completar o cobrar un tratamiento, primero
  hay que confirmar todo el plan». Si **confirmas**, el plan pasa a
  *Esperando aceptación*, se genera su presupuesto borrador y se hace lo
  que habías pedido. Si **cancelas**, el plan sigue en borrador y no se toca nada.
- **Editar o eliminar en un plan en proceso** abre *Reabrir plan para
  editar*, que avisa de que **se cancelará el presupuesto vigente**. Al
  reabrir, el plan vuelve a borrador y habrá que confirmarlo de nuevo.
- Reabrir el plan es de un administrador o del profesional asignado al
  caso. Quien no lo sea ve el aviso *«No tienes permisos para reabrir
  este plan»* y el plan no se mueve.
- Bajo la franja de *qué toca ahora*, una nota gris recuerda que **los
  tratamientos de un plan confirmado ya no se editan ahí** y qué cuesta
  cambiarlos (reabrir anula el presupuesto). Aparece por el **estado** del
  plan, no por si tiene presupuesto: un plan activo sin presupuesto también
  está fijado y antes no decía nada. En un plan terminado o cerrado cambia
  a *Plan terminado*, y solo el cerrado remite a reactivarlo, porque es el
  único que tiene ese botón. Es gris a propósito: es el estado normal de un plan
  durante casi toda su vida, y un aviso ámbar que acierta todos los días
  deja de leerse.
- Notas, recordatorios y recetas funcionan en cualquiera de los dos
  estados: son actos clínicos, no cambios del plan.
- La tarjeta **Cobros de este plan** no ofrece *Cobrar* mientras el plan
  sea un borrador; dice qué falta.

### Cobros de este plan

La tarjeta lleva cuatro cifras, y todas son **de este plan**:

- **Por cobrar de este plan**, arriba y en grande: lo único que exige
  una acción.
- **Presupuestado**: lo que vale el plan entero.
- **Realizado**: la parte que ya se ha ejecutado, que es lo que se puede
  cobrar. Un plan de 19.020 con 120 realizados sólo puede cobrar 120.
- **Cobrado**: lo que de eso ya ha entrado.

Debajo, y **sólo cuando aporta algo**, una línea dice lo que el paciente
debe *en total*, contando otros planes. Puede ser mayor que la del plan:
un paciente debe lo que debe en toda la clínica, y confundir las dos
cifras es como se acaba pidiendo el importe equivocado.

Si el plan aún no tiene nada ejecutado, la tarjeta explica la regla:
*se va pudiendo cobrar a medida que completas tratamientos*. Esa frase
responde a la pregunta que deja un 0 sobre un plan de miles.

### Añadir a un plan en curso

Encontrar una caries nueva a mitad de tratamiento es lo normal, y antes
salía caro: había que reabrir el plan, lo que **anulaba el presupuesto que
el paciente ya había firmado**, reconfirmarlo y hacérselo aceptar otra vez.

Ahora **añadir está permitido con el plan en curso**. No cambia ninguna de
las líneas que el paciente aceptó, así que su presupuesto no se toca.

1. Toca la pieza en el odontograma. Como el plan está confirmado, el
   odontograma está en solo lectura y responde con un aviso: ahí aparece
   **Añadir tratamiento en el {pieza}**.
2. Se abre el mismo buscador del constructor, ya fijado en esa pieza.
   Eliges el tratamiento y entra en el plan.
3. La franja de arriba pasa a decir **«N tratamientos sin presupuestar»**,
   con el botón **Presupuestar lo añadido**.
4. Al pulsarlo se crea un **presupuesto aparte** solo con lo nuevo, en
   borrador, que el paciente acepta por su cuenta. El firmado sigue
   intacto, y los dos quedan colgados del plan.

Si el presupuesto del plan todavía está en **borrador** no hace falta nada
de esto: lo que añades entra en él solo, porque nadie ha visto aún ninguna
cifra.

**Editar o eliminar** un tratamiento ya aceptado sigue pidiendo reabrir el
plan. Esa es la diferencia: añadir no le quita nada al paciente, cambiar el
precio o quitar una línea sí.

## Marcar ítems como ejecutados

> Requiere `treatment_plan.plans.write` y un plan **en proceso**.

1. En el ítem, pulsa el ✓ de la fila o **Marcar como completado**
   dentro de su ventana.
2. Se publica `treatment_plan.treatment_completed`. `recalls` puede
   sugerir un próximo recall basado en `treatment_category_key`.
3. Acto seguido la aplicación pregunta **si cobras ahora o lo dejas
   pendiente**. Es el momento más barato para cobrar —el paciente
   sigue en el sillón— pero *dejar pendiente* es una respuesta tan
   válida como la otra: una clínica que factura a fin de mes lo hace
   todos los días, y el importe queda igualmente en «pendiente de
   cobrar».
4. Para anotar una nota clínica, ábrela desde la ventana del
   tratamiento (**Añadir nota**, lo aporta `clinical_notes`).

**Quitar un ítem del plan** (icono de papelera en la fila) pide
confirmación: la baja arrastra el tratamiento del odontograma y la
línea de presupuesto asociada.

## Receta médica

> Escribir una receta requiere `treatment_plan.prescriptions.write`
> (administrador y dentista). Verlas y reimprimirlas,
> `treatment_plan.prescriptions.read` (también higienista, auxiliar y
> recepción).

1. En la ventana del tratamiento pulsa **Receta médica**.
2. **Doctor que firma** viene con el profesional asignado al
   tratamiento; puedes elegir otro del directorio. Debajo se ve su
   **cédula profesional**, o un aviso si no la tiene registrada (la
   receta saldría sin ella: complétala en el menú *Profesionales*).
3. Escribe las **indicaciones**: medicamento, dosis, frecuencia y
   duración.
4. Pulsa **Generar receta**. Se abre una pestaña con el PDF listo para
   imprimir: datos de la clínica (nombre, dirección, teléfono, correo),
   nombre y cédula del doctor, paciente, edad, fecha, tratamiento, las
   indicaciones y la línea de firma.

La receta **queda guardada** en el expediente y aparece en *Recetas
anteriores* con su botón **Imprimir**. El nombre y la cédula del doctor
se copian al generarla: si mañana cambian en el directorio, la
reimpresión sigue diciendo lo que llevó el paciente a la farmacia. Si
quitas el tratamiento del plan, la receta no se borra.

## Tratamiento cerrado, y cómo reabrirlo

Un tratamiento aparece como **Cerrado** cuando está completado **y** no
queda nada por cobrar de él. No es un estado que se guarde: se deduce
del dinero, así que no puede desincronizarse del libro. La **receta
médica** está disponible también con el tratamiento cerrado.

Si marcaste un tratamiento como hecho por error —esté cerrado o todavía
con cobro pendiente—, ábrelo y pulsa **Reabrir tratamiento**. La ventana
te explica qué va a pasar antes de hacerlo; al confirmar con **Sí,
reabrir**:

- El tratamiento **vuelve a pendiente** y deja de contar como hecho,
  también en el odontograma.
- **Se retira su cargo.** Ya no aparece como pendiente de cobro ni en el
  plan ni en la cuenta del paciente.
- **Lo que ya se cobró no se devuelve.** Queda como saldo a favor del
  paciente y cubrirá el tratamiento cuando lo completes de verdad. Si lo
  que quieres es devolver el dinero, eso se hace en Finanzas.
- Si el plan estaba **completado**, vuelve a **Activo**, porque
  ahora tiene trabajo pendiente.
- En un tratamiento de **varias sesiones** solo se reabre la última
  sesión que se completó; las anteriores siguen hechas y cobradas.
- Queda anotado en el **historial del plan** como *Tratamiento
  reabierto*.

No se puede reabrir un tratamiento de un plan **cerrado**: primero hay
que reactivar el plan.

## Tratamientos en varias sesiones

Algunos tratamientos del catálogo (p.ej. corona, endodoncia) tienen
una **plantilla de sesiones** con nombre e importe por paso. Al
añadirlos al plan se crea automáticamente una sesión por cada paso.

- El item muestra un chip **X/Y sesiones** con el progreso.
- Bajo el item aparece la lista de sesiones (icono ✓ por completada,
  círculo punteado por pendiente).
- Pulsa el check de cada sesión para marcarla realizada — publica
  `treatment_plan.item_session_completed` y `payments` registra una
  entrada de "trabajo realizado" por ese importe.
- El item se finaliza automáticamente al completar la última sesión
  pendiente (entonces se ejecuta el flujo legacy de cierre).
- Cancela una sesión si no llegó a hacerse: no genera cobro.

## Cambiar el doctor del plan

> Requiere `treatment_plan.plans.write`.

1. Abre **Editar plan** y selecciona otro profesional.
2. Si hay tratamientos pendientes asignados al doctor anterior,
   aparece un confirm: *"¿Reasignar los tratamientos pendientes?"*.
3. Pulsa **Sí, reasignar pendientes** para mover todos los ítems
   pendientes que coincidían con el doctor anterior al nuevo en el
   mismo guardado. Los ítems con override explícito (otro doctor)
   y los completados no se tocan nunca.
4. Pulsa **No, dejar como están** si solo quieres cambiar el
   doctor del plan; los ítems mantienen su asignación.

## Cerrar o reactivar

> Cerrar requiere `treatment_plan.plans.close`. Reactivar requiere
> `treatment_plan.plans.reactivate`.

1. **Cerrar** — elige motivo: rechazado, expirado, cancelado,
   abandono u *otro*. Publica `treatment_plan.closed` con
   `closure_reason`.
2. **Reactivar** — vuelve al estado `draft`. Publica
   `treatment_plan.reactivated`.

**Un plan con cobros solo se puede cerrar.** Si el paciente ya pagó algo
de este plan —a su presupuesto, o dinero a cuenta que cubre tratamientos
ya hechos— el plan **no se puede cancelar** (*Cancelar plan* con el
motivo *Cancelado por la clínica*) **ni borrar**. Sale el aviso *«Error,
hay algún cobro en el plan de tratamiento. Favor de cerrar este plan de
tratamiento»* y la ventana sigue abierta: elige otro motivo (por ejemplo
*Paciente abandonó* u *Otro motivo*) y pulsa **Cerrar plan**. Un cobro
devuelto por completo ya no cuenta.

## Permisos

| Lo que ves / puedes hacer | Permiso |
|---------------------------|---------|
| Ver detalle, ítems y contactos | `treatment_plan.plans.read` |
| Añadir/reordenar ítems, completarlos, registrar contactos | `treatment_plan.plans.write` |
| Confirmar (draft → pending) | `treatment_plan.plans.confirm` |
| Cerrar | `treatment_plan.plans.close` |
| Reactivar | `treatment_plan.plans.reactivate` |
| Ver y reimprimir recetas | `treatment_plan.prescriptions.read` |
| Escribir una receta | `treatment_plan.prescriptions.write` |

## Resolución de problemas

- **Confirmé el plan pero el presupuesto no aparece.** Pulsa
  **Generar presupuesto** o **Enlazar con presupuesto existente**.
  Confirmar no crea automáticamente el presupuesto a menos que se
  use *Generar* después.
- **El paciente aceptó el presupuesto pero el plan sigue en
  pendiente.** Comprueba que el evento `budget.accepted` está
  fluyendo (el módulo `budget` ha de estar instalado y el
  presupuesto realmente aceptado). El handler
  `on_budget_accepted` lo mueve a *activo*.
- **No puedo borrar un ítem.** El ítem ya está marcado como hecho.
  Los ítems completados quedan como histórico.
- **No me deja completar un ítem.** Tu rol no tiene
  `treatment_plan.plans.write`.
- **Hago clic en un diente y no pasa nada.** El plan está en curso: el
  odontograma se queda en **solo lectura** mientras haya un presupuesto
  vivo. Al hacer clic sale un aviso con el botón **Reabrir**, que
  devuelve el plan a borrador cancelando ese presupuesto — el mismo
  botón de la cabecera, y pide confirmación antes de nada. Si el aviso
  no ofrece ese botón es porque reabrir es cosa de un administrador o de
  un profesional asignado al caso, o porque el plan ya está completado o
  cerrado.
