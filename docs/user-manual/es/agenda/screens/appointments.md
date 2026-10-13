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

# Citas

Calendario operativo de la clínica. Desde aquí ves las citas de la
semana o el día, las creas arrastrando sobre un hueco libre, las
mueves a otro profesional o gabinete y las haces avanzar por su
flujo (programada → confirmada → en sala → completada → cobrada).

## De un vistazo

- **Cuatro vistas** — semana, día y kanban en escritorio, y una vista
  móvil de un día simplificada en pantallas pequeñas. El selector
  vive en la cabecera, salvo en móvil donde solo existe la vista
  diaria.
- **Filtros por gabinete y profesional** — chips encima del
  calendario. Las citas sin gabinete asignado **siempre** se ven,
  para que recepción pueda arrastrarlas al gabinete que toque.
- **Drag, resize y arrastre entre días** — arrastra una cita a otra
  hora o profesional para moverla; arrastra su borde inferior para
  cambiarle la duración. Si solapa con otra del mismo profesional o
  gabinete, sale un aviso pero la operación se guarda.
- **En tablet, con el dedo** — toca una cita para abrirla; mantén
  pulsado unos instantes para **seleccionarla** (se resalta y le crece
  el asa inferior) y entonces arrástrala para moverla o tira del asa
  para cambiarle la duración. Toca un hueco libre para crear ahí: la
  duración se elige en el modal, no arrastrando. En kanban, mantén
  pulsada una tarjeta y arrástrala a otra columna.
- **En tablet, la orientación cambia la disposición, no los gestos** —
  en vertical se abre la vista de **Día** (una semana de siete columnas
  no cabe a lo ancho), el kanban reparte sus columnas en dos filas y la
  cabecera pasa a dos líneas. Si eliges tú una vista, girar la tablet ya
  no te la cambia. Girar nunca cambia cómo funciona un gesto.
- **En vertical, la vista de Día cabe entera a lo ancho** — las columnas
  se estrechan para repartirse el ancho que hay, así que tienes el día
  completo delante sin arrastrar en horizontal. Si la clínica tiene
  tantos profesionales que las columnas dejarían de leerse, entonces sí
  se arrastra; poner la tablet en horizontal siempre les da más sitio.
- **Navegación de fechas en la cabecera** — los botones anterior / hoy /
  siguiente y la fecha viven junto al título, y avanzan de semana en
  semana o de día en día según la vista activa.
- **Conflictos del backend** — si el servidor rechaza una cita por
  solape (HTTP 409) el calendario refresca la vista y muestra un
  *toast* de error; nada queda inconsistente.
- **Vista kanban del día** — las citas se agrupan por estado
  (programada, confirmada, en sala…). Sirve para que la consulta vea
  de un vistazo qué le toca a continuación.

## Crear una cita

> Requiere `agenda.appointments.write`.

1. En la vista semanal/diaria, pulsa o arrastra sobre un hueco libre.
   En kanban o móvil, pulsa **Nueva cita** o el botón flotante.
2. Selecciona paciente, motivo y duración. El profesional y el
   gabinete se preseleccionan según el hueco desde el que abriste el
   modal.
3. **Guardar**. Se publica el evento `appointment.scheduled` para que
   módulos como notificaciones puedan enviar la confirmación.

### Si alguna app no está habilitada

La agenda funciona aunque la clínica no tenga Pacientes, Profesionales
o Tratamientos. En el formulario, en lugar del selector, verás el
aviso correspondiente:

- **«No se pueden asignar pacientes»** — la cita se guarda sin
  paciente. Escribe un **título** para reconocerla en el calendario.
- **«No se pueden asignar profesionales»** — la cita se guarda sin
  profesional y aparece en la columna **Sin profesional** de la vista
  de día.
- **«No se pueden asignar tratamientos»** — la cita se guarda sin
  tratamientos.

Las citas que ya tenían paciente, profesional o tratamientos no los
pierden: dejan de mostrarse mientras la app está apagada y vuelven a
verse cuando se habilita.

## Mover o redimensionar

> Requiere `agenda.appointments.write`.

1. Arrastra la tarjeta a otra hora, día o profesional para mover.
2. Arrastra su borde inferior para cambiar la duración.
3. Si la nueva posición solapa con otra cita del mismo profesional o
   gabinete verás un aviso amarillo, pero la cita queda guardada. Si
   el backend rechaza la operación (HTTP 409 por una colisión más
   estricta), la vista se refresca y la cita vuelve a su posición
   original.

## Avanzar el estado

> Requiere `agenda.appointments.write`.

1. Abre la cita pulsando sobre ella.
2. En el panel de **Acciones rápidas** elige la siguiente transición
   disponible: *Confirmar*, *En sala*, *Completar*, *Cancelar*.
   **Cancelar** pide confirmación: está junto a *Guardar* en el pie del
   modal y al paciente se le avisa según la configuración de
   notificaciones.
3. Al transicionar a **completada** aparece un modal de seguimiento
   con acciones de módulos hermanos (p. ej. *Programar recall*). El
   modal solo se muestra si hay módulos que lo aporten.

### Finalizar una cita sin carta de consentimiento

Si la clínica exige consentimiento informado para sus planes y la cita
trabaja sobre un plan que no tiene carta firmada, **Finalizar cita**
pregunta antes: *Crear la carta* abre los consentimientos del paciente
para ese plan, y *Finalizar sin carta* sigue adelante. La regla viene
apagada; se activa en *Configuración → Clínica → Plantillas de
consentimiento*.

## Permisos

| Lo que ves / puedes hacer | Permiso |
|---------------------------|---------|
| Ver calendario, abrir citas, ver historial de gabinete | `agenda.appointments.read` |
| Crear, mover, redimensionar, cancelar, transicionar | `agenda.appointments.write` |
| Ver los gabinetes (chips de filtro) | `agenda.cabinets.read` |
| Editar la nota clínica de la visita | `clinical_notes.notes.write` |

## Resolución de problemas

- **No veo el botón "Nueva cita".** Tu rol no tiene
  `agenda.appointments.write`.
- **No salen profesionales en el filtro.** No hay dentistas o higienistas
  activos en el directorio de Profesionales. Crea o activa su perfil desde
  *Profesionales*.
- **Una cita movida vuelve a su sitio.** El backend rechazó el cambio
  con HTTP 409 (típicamente porque el profesional o el gabinete tiene
  otra cita en esa franja). Mira el *toast* de error y prueba otra
  hora.
- **El calendario solo va de 08:00 a 21:00.** El módulo `schedules`
  no está instalado o no tiene horario configurado; la agenda usa la
  ventana por defecto.
- **La hora de una cita es siempre la de la clínica.** No cambia porque
  abras la aplicación desde otro país o con el portátil en otro huso: una
  cita de las 17:30 se lee 17:30 en el calendario, en el kanban y en la
  ficha del paciente. Si ves la misma cita con dos horas distintas en dos
  pantallas, es un fallo — repórtalo.
