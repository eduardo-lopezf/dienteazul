# Changelog — agenda module

## Unreleased

- feat(agenda): **finalizar una cita pregunta antes por la carta de
  consentimiento** cuando la cita trabaja sobre un plan para el que la
  clínica exige consentimiento informado y no hay ninguno firmado.
  Pregunta, no impide: se puede finalizar sin carta.
  - `GET /appointments/{id}/completion-check` responde
    `plans_lacking_consent` (`plan_id`, `plan_number`); la transición no
    lo consulta. La agenda lo sabe por los contratos `PlannedTreatments` y
    `PlanConsents` (ADR 0039): no importa a nadie, y con Tratamientos o
    Expediente Clínico apagados no pregunta.
  - `useCompletionCheck().confirm(appointment)` antes de pasar a
    `completed`, en el menú de la tarjeta y al arrastrar en el kanban;
    la pregunta se pinta una vez en `CompletionCheckHost.vue`.

- feat(agenda): la ventana de cita ofrece el slot
  `appointment.patient.alerts` (`{ patientId }`), bajo el selector de
  paciente: ahí otras apps avisan lo que conviene saber antes de elegir
  hora. La agenda no sabe qué avisos son ni importa a quien los pone
  (ADR 0041). El primero es el de ASA III/IV, de Pacientes.

- feat(agenda): `appointment.completed` (y `status_changed` a
  `completed`) lleva `planned_items`: `[{planned_item_id, completed}]`,
  lo que la visita cubrió. `treatment_plan` actúa con eso y ya no lee
  las tablas de la agenda (ADR 0042).

- feat(agenda): la agenda ofrece su primer contrato, `AppointmentBook`
  (`providers.py`, ADR 0039): paciente de una cita, citas de un paciente
  y notas de visita por tratamiento planificado. Lo consume
  `clinical_notes`, que ya no importa los modelos de la agenda.

- chore(agenda): los cinco widgets se marcan con `widget: true` en su
  registro. Llevar etiqueta ya no basta para aparecer en Configuración →
  Apps → Widgets, porque las pestañas también la llevan.
- fix(agenda): la línea de tiempo de Inicio dibujaba cada cita desplazada
  por la diferencia horaria del navegador respecto a UTC, mientras su
  etiqueta decía la hora correcta: una cita de las 15:00 aparecía bajo
  las 09:00 en un equipo en UTC−6. Leía `start_time` como instante en
  lugar de como hora local de la clínica; ahora usa `wallClockDate`,
  igual que el resto de widgets. Lo destapó el ejemplo con datos
  ficticios de Configuración → Apps → Widgets.
- feat(agenda): los ejemplos de widgets en Configuración → Apps usan
  datos ficticios (`utils/previewSamples.ts`) en lugar de los de la
  clínica. `useHomeAgenda` y la tarjeta «Próxima cita» los devuelven
  cuando se renderizan dentro de un ejemplo (`useWidgetPreview`), en
  estado propio, sin tocar el que comparte el panel de Inicio y sin
  llamar a la API.
- feat(agenda): los cinco widgets que la agenda aporta a Inicio y a la
  ficha del paciente llevan ahora nombre y descripción (`labelKey` /
  `descriptionKey`), y aparecen en Configuración → Apps → Widgets con un
  ejemplo en vivo (ADR 0040). La app declara además la API «Google
  Calendar» en `backend/apps.json` como `planned`: listada, todavía sin
  integración detrás.
- refactor(agenda): el módulo ya no importa ningún otro (ADR 0039).
  Pacientes, profesionales, tratamientos planificados y horarios se
  alcanzan por contratos del core (`app/core/contracts.py`); se eliminan
  las relaciones ORM `appointment.patient`, `.professional`,
  `.planned_item` y `.catalog_item`, y `presenter.py` arma la respuesta
  preguntando a cada directorio una vez por página. La forma de la API no
  cambia. `integrates` queda en los dueños de las tablas a las que
  apuntan sus llaves foráneas: `patients`, `professionals`, `catalog` y
  `treatment_plan`.
  - fix: el kanban decidía si `schedules` estaba presente intentando
    importarlo, y la importación nunca falla; seguía usando los horarios
    con la app apagada. Ahora pregunta por el proveedor del contrato.
- refactor(agenda): la página `/appointments` ya no lleva su propia
  guardia para cuando la app está apagada; la cubre la guardia común
  `useAppRouteGuard` (ADR 0038), con el mismo aviso.
- feat(agenda): ninguna dependencia es obligatoria (ADR 0037).
  `depends` queda vacío y `patients`, `professionals`, `catalog`,
  `odontogram`, `treatment_plan` y `schedules` pasan a `integrates`.
  - Migración `ag_0007`: `appointments.professional_id` admite nulo y se
    añade `appointments.title`. Solo amplía lo que la tabla acepta; no
    toca ninguna fila.
  - Con Pacientes o Profesionales apagada, la cita se crea sin ese
    enlace, el modal muestra «No se pueden asignar pacientes» /
    «No se pueden asignar profesionales», la API rechaza con 400 un
    enlace nuevo y los ya guardados no se muestran hasta que la app
    vuelve. Sin paciente, la cita se identifica por su título.
  - Con Profesionales habilitada el profesional sigue siendo
    obligatorio: no cambia nada para una clínica que lo tiene todo.
  - La vista de día añade la columna «Sin profesional» cuando hay citas
    sin asignar o no hay directorio.
  - fix: los eventos `appointment.*` enviaban el texto `"None"` como
    `professional_id` cuando no había profesional; ahora envían `null`.
- feat(agenda): con la app Tratamientos apagada (`backend/apps.json`) la
  agenda sigue creando citas, sin tratamientos. El modal muestra «No se
  pueden asignar tratamientos» en lugar del selector, la API rechaza con
  400 un `planned_item_ids` nuevo, la nota de visita responde 409, y los
  enlaces ya guardados no se muestran: siguen en la base y vuelven al
  habilitar la app (ADR 0037).
- feat(agenda): la app Agenda (módulos `agenda` + `schedules`) se puede
  apagar para todo el despliegue desde `backend/apps.json` (ADR 0038).
  Apagada, no se montan sus rutas, permisos, tareas ni entrada de menú,
  y `/appointments` redirige al inicio con el aviso «No se pueden crear
  citas». Sus tablas y datos no se tocan.
- chore(agenda): el manifiesto declara `integrates: [treatment_plan,
  schedules]` (ADR 0037). No cambia el comportamiento: eran los dos
  enlaces que el módulo ya tenía sin declarar (la FK e import hacia
  `treatment_plan`, y el import de `schedules` en el kanban) y que
  figuraban como deuda en las pruebas de aislamiento.
- fix(agenda): cerrar la ficha de una cita lanzaba «Must be called at the
  top of a `setup` function». El `watch` de `open` en `AppointmentModal`
  llamaba a `useAppointmentNotesIndicator()` dentro del callback, y ese
  composable llega a `useApi` → `useI18n`. Además de ensuciar la consola,
  el indicador de notas que quería refrescar nunca se refrescaba. Ahora se
  resuelve en el `setup`.
- fix(agenda): el temporizador de la tarjeta de cita ya no cuenta en
  minutos sin techo. Mirando otro día decía «retrasada 8749 min»; ahora
  pasa a horas a partir de hora y media y a días a partir de 24 h
  («retrasada 6 d»). Nuevo `formatDurationShort` en `utils/date.ts`, con
  pruebas en `frontend/tests/agenda/formatDurationShort.test.ts`.

- fix(touch): una pulsación larga sobre una cita ya **no la abre al
  soltar** si el dedo se queda apoyado un poco más. El click que sigue a la
  liberación se suprimía durante 300 ms contados desde que la pulsación se
  registraba, no desde que se soltaba: sostener más de ~600 ms en total —
  la forma natural de hacer una pulsación larga — abría la cita que
  acababa de seleccionarse, y el modal tapaba el arrastre siguiente.
  `useSlotGridDrag` suprime ahora ese click en el `pointerup`, como ya
  hacía tras un arrastre. Cubierto en
  `frontend/tests/agenda/useSlotGridDrag.test.ts` y en
  `tablet-agenda.spec.ts`.

  El kanban tenía el mismo defecto sin ninguna guarda: una tarjeta
  levantada con pulsación larga y soltada en su sitio (o arrastrada con
  ratón y devuelta) abría la cita, porque el `click` de la tarjeta emitía
  siempre. Ahora se suprime tras cualquier gesto que levantó la tarjeta —
  por pulsación larga o por moverla más de 5 px —; un toque o un click
  simple siguen abriéndola. Cubierto por dos casos nuevos en
  `tablet-agenda.spec.ts`.

- fix(a11y/i18n): las flechas del navegador de fechas dicen ahora **qué
  hacen**. Eran iconos sin texto con `aria-label="Anterior"` y
  `"Siguiente"`, que a un lector de pantalla no le dice si mueve un día o
  una semana — y esas dos claves no existían en ningún idioma: estaban
  escondidas tras el segundo argumento de `t(clave, 'por defecto')`, así
  que la interfaz se veía bien mientras intlify avisaba en cada render
  (231 y 125 veces en el log del contenedor).

  En vista semanal reutilizan `appointments.prevWeek` / `nextWeek`, que ya
  existían; en día y kanban usan `previousDay` / `nextDay`, nuevas en es y
  en. Comprobado en los tres modos: «Semana anterior/siguiente», «Día
  anterior/siguiente», y ninguna advertencia durante la ejecución.

- fix(ui): en vertical, la vista de Día se salía por la derecha. La rejilla
  exigía 200 px por profesional (`200 x N + 80`), así que una clínica con
  cinco pedía 1080 px contra los ~620 que tiene una tablet en vertical: casi
  la mitad del día quedaba fuera de pantalla y había que arrastrar en
  horizontal para llegar a ella.

  La ironía es que vertical abre en Día justamente para *evitar* eso — una
  semana de siete columnas no cabe a lo ancho. Pero el suelo de 200 px es la
  única de las dos medidas que crece con el tamaño de la clínica, y nadie
  comprobó cuánto pedía Día de verdad: la semana ocultaba 112 px y Día
  ocultaba 392. En horizontal hay 1168 px y las dos vistas caben, que es por
  lo que solo se veía girando la tablet.

  Ahora el suelo depende de si hay sitio a lo ancho que gastar: 200 px por
  columna en horizontal (y se arrastra cuando la clínica es grande), y en
  vertical el mínimo en el que una tarjeta sigue siendo legible, repartiendo
  el ancho que hay. Por debajo de eso vuelve a arrastrarse, en lugar de
  estrechar las columnas hasta lo ilegible.

  La prueba que cubría esto solo comprobaba que la rejilla *estuviera* —
  nunca que **cupiera**. La nueva mide el desbordamiento y además fija el
  ancho mínimo de columna, para que no se pueda «arreglar» un desbordamiento
  futuro encogiéndolas.

- fix(agenda): el panel de inicio pedía a la API una ventana corrida. «Hoy»
  se construía con los límites del día local y se serializaba con
  `toISOString()`, que los reinterpreta como instantes: en un equipo UTC−6
  la consulta iba de las 06:00 a las 06:00 del día siguiente, así que el
  panel **perdía en silencio toda cita anterior a las seis** y se traía de
  propina las primeras del día siguiente. `toWallClockIso` existía
  justamente para esto y no se usaba aquí.

  Y «hoy» pasa a ser el día de la **clínica**. El saludo que hay justo
  encima ya mostraba la fecha de la clínica, así que la cabecera decía
  «sábado 12» mientras la tarjeta de debajo contaba las citas del viernes
  11. Si la zona aún no se conoce —primer pintado, antes de que responda
  `/auth/me`— se usa la del navegador, que es lo que había.

- fix(agenda): tres sitios más leían `start_time` con `new Date()`, que
  desplaza el reloj de la clínica por el desfase del navegador:

  - «Citas hoy» contaba como *próximas* citas ya pasadas.
  - El enlace de *Por confirmar mañana* mandaba al día anterior en citas de
    primera hora, así que la agenda abría en el día equivocado y la tarjeta
    que iba a resaltar no estaba en pantalla.
  - La tira semanal del día contaba esas mismas citas bajo la víspera.

- fix(agenda): la lista de citas de la ficha del paciente pintaba la hora en
  la zona del navegador. `start_time` es hora de pared de la clínica, cuyo
  desfase es un artefacto de almacenamiento y no un instante que convertir
  (ver `frontend/utils/date.ts`), pero `AppointmentsMode` la pasaba por
  `new Date()`. Resultado: una urgencia dibujada a las 17:30 en el calendario
  se listaba a las 11:30 en la ficha. La misma cita, dos horas, dos
  pantallas — y en los datos de demo aparecían citas a las 05:00 y 06:00.

  Es la misma regresión que el docstring de `wallClockDate` ya cuenta para el
  kanban («12:00 en la rejilla y 06:00 en la tarjeta»), arreglada entonces
  allí y no aquí. El helper existía; sólo faltaba usarlo.


- fix(core auth): `/auth/me` now returns each clinic's `timezone`. It was the
  only clock reference the frontend could have during SSR — the global auth
  middleware awaits `auth.init()` on the server, while `useClinic` fetches from
  a watcher nobody awaits and is still null there. Both construction sites
  already `selectinload` the clinic, so it costs no extra query. `useAuth`
  keeps it as `clinicTimezone`.

- fix(home): the dashboard greeting is rendered in the clinic's zone instead of
  the server's, and no longer flashes. It read `new Date()` during SSR, so the
  container (UTC) and the browser disagreed; on a night when the two straddled
  midnight the server sent "Buenas noches / jueves 3" and the client expected
  "Buenas tardes / miércoles 2". That text mismatch corrupted the hydrated DOM
  and the next client-side navigation died with `insertBefore: node is not a
  child of this node` — clicking "Tratamientos" from the dashboard landed on a
  blank page. Server and client now format the same instant (seeded through the
  payload) in the same zone.

- fix(home): the slot-driven dashboard sections render inside `<ClientOnly>`.
  Every module registers its slots from a `.client.ts` plugin, so the registry
  is empty during SSR and each `v-if="…Entries.length > 0"` resolved false on
  the server and true on the client — a structural hydration mismatch on every
  single load, and the other half of the blank page above.

- fix(agenda): read appointment times as clinic wall clocks everywhere.
  `start_time` / `end_time` carry the clinic's wall clock with an offset
  that is a storage artifact, and `utils/date.ts` already said so — but
  the kanban card, the home strip, the unconfirmed panel, the patient
  summary card and `useFreeSlots` all routed them through `new Date()`
  first. On any desk whose zone differs from the stored offset the same
  12:00 appointment was drawn at 12:00 on the calendar grid and 06:00 on
  the kanban, the "retrasada N min" timer was off by the same gap, and
  `fetchAppointments` asked the API for a window slid by that gap —
  silently dropping early-morning appointments. New `wallClockDate`,
  `formatWallClockTime` and `toWallClockIso` helpers make the reading
  rule explicit; covered by `frontend/tests/agenda/wallClock.test.ts`.
  True instants (`current_status_since`) still go through `new Date()`.

- feat(privacy): `get_subject_contributors()` — este módulo ya responde
  cuando un paciente ejerce portabilidad o supresión
  ([ADR 0026](../../../../docs/adr/0026-subject-rights-are-a-module-contract.md)).
  Citas y su rastro (tratamientos aplicados, cambios de estado y de gabinete). Registro asistencial: se conservan.

- fix(ui): a tablet held upright got the phone day-list instead of the
  agenda. The view was picked with `isMobile` (`max-width: 767px`), and a
  tablet in portrait is narrower than that while still being a tablet —
  reported from a real device. It now uses `useDevice().isPhone`, which
  tests the *shorter* side of the viewport (< 540 px) and so does not
  change when the device is rotated. The same rule corrects the opposite
  error: a phone in landscape is 915 px wide and the width test called it
  a desktop.

  Portrait now also opens on the day view rather than the week: seven
  columns need 800 px and an upright tablet has less. An explicit choice
  of view is never overridden, including by rotating.

- feat(ui): one date navigator instead of three. The week, day and
  kanban views each rendered their own identical prev / today / next row
  plus date label, stacked under the page header and the filters; the
  new `AppointmentDateNav` renders once in the page header's `#lead`
  slot and steps by week or day depending on the active view. Recovers a
  full row — ~7% of the visible day on an 800 px-tall tablet — and the
  header wraps to two lines in portrait rather than overflowing.

- refactor(ui): `AppointmentMobileDayView` → `AppointmentDayList`,
  `AppointmentMobileTimeline` → `AppointmentDayTimeline`,
  `AppointmentMobileDaySummary` → `AppointmentDayHeader`. The old names
  said where the component ran, which was already misleading — a tablet
  held upright wants that same free-slot list — and would have gone on
  being wrong as layouts move. Names now say what the component is. No
  behaviour change; the typecheck baseline moves only by those paths.

- refactor(ui): the pointer-capability branches are now a dispatcher over
  a pair of named functions (`pressAppointmentWithMouse` /
  `pressAppointmentByTouch`, `pressCardWithMouse` / `pressCardByTouch`)
  rather than conditionals inside one mixed function, so which code runs
  where is readable without tracing branches. The shared parts stay
  shared on purpose — see `docs/technical/touch-adaptation.md`.

- feat(ui): the agenda works by touch. Create, move and resize in the
  week and day grids ran on `mousedown` plus document `mousemove`, and
  the kanban on HTML5 drag-and-drop; Chrome on Android delivers neither
  while a finger is moving, so all four gestures were inoperable on a
  tablet — not awkward, impossible. All of it now runs on Pointer
  Events, one path for mouse, finger and stylus.

  By finger: tap opens an appointment, a 300 ms long press selects it,
  and a selected block drags to move or resize. Tapping an empty slot
  creates there. Kanban cards long-press and drag between columns, with
  a ghost following the pointer.

  By mouse: unchanged — no selection step, press and drag as before.

  The week and day grids now share `composables/useSlotGridDrag.ts`
  instead of carrying two near-identical copies of the drag logic.

- fix(ui): calendar geometry read `useDensity().density` (the user's
  preference) rather than `effective`, so with a coarse pointer and a
  saved "compact" preference the drag maths used 18 px slots while the
  CSS drew 28 px ones.

- feat(ui): the kanban lays its five columns out in two when the tablet
  is held in portrait, instead of demanding 1320 px of width and
  scrolling sideways while leaving most of a 1280 px-tall screen empty.

- fix(ui): mark the week grid, the day grid and the dashboard timeline
  strip as `data-dense`, so the global touch minimum sizes leave them
  alone. Without it a 15-minute slot would grow to 44 px (costing ~2 h of
  visible agenda on an 800 px screen) and the timeline chips — whose
  width encodes duration — would both distort and overflow their 36 px
  lane. See [ADR 0022](../../../../docs/adr/0022-touch-adaptation-is-capability-driven.md).

  Known gap this leaves open: appointment quick actions stay
  hover-revealed and so are unreachable by touch, because an
  always-visible button lands on the patient's name in a 28 px block.
  Fixing it needs the block redesigned, together with the move to Pointer
  Events for create/move/resize — none of which work by touch today.

- fix(ui): cancelling an appointment from the modal footer asks first. It
  sat next to Save, cancelled on one click and notified the patient
  (audit S5).

- fix(events): publish through ``event_bus.publish_after_commit(db, ...)``
  instead of announcing from inside the caller's open transaction.
  Handlers read through their own sessions, so a flushed-but-uncommitted
  row was invisible to them (audit S2). See
  [ADR 0019](../../../../docs/adr/0019-events-publish-after-commit.md).

- feat(professionals): appointments now reference active dentist/hygienist
  directory profiles instead of product accounts. Includes a conservative
  migration of existing appointment identities.

- feat(agents): two new copilot tools — `reschedule_appointment` (WRITE,
  wraps `AppointmentService.update_appointment`, surfaces `slot_conflict`
  as a structured error) and `update_appointment_status` (WRITE, wraps
  `transition`; invalid transitions return the allowed next states;
  `cancelled` stays exclusive to the DESTRUCTIVE `cancel_appointment`).

- fix(agenda): the appointments page now refetches its active window when
  the shared client data bus signals an `agenda` change (e.g. a copilot
  booking/cancellation), so externally created appointments appear without a
  manual reload. Deduped the post-save/cancel reload into `reloadActiveView`.

- fix(modal): show the correct duration when editing an appointment. The
  `selectedTreatments` watcher recomputed `formData.duration` from a
  treatment-count heuristic and clobbered the value derived from the
  appointment's start/end times during initial edit-mode population. Gated
  the watcher behind `initialDataLoaded` so only user-driven treatment
  changes adjust the duration.
- feat(agents): expose `tools.py` for the copilot agentic layer —
  `get_day_overview` (READ), `book_appointment` (WRITE),
  `cancel_appointment` (DESTRUCTIVE). Thin wrappers over
  `AppointmentService`; clinic-scoped; RBAC via existing
  `agenda.appointments.*`. `find_free_slots` deferred to `schedules`.
  Issue #81 Layer B.
- feat(agents): add `get_appointment` (READ) and `list_cabinets` (READ)
  tools. Issue #81 P0 batch.
- feat(agents): add `list_professionals` (READ) — resolves a
  professional name → id (reuses `kanban_service._fetch_professionals`).
  Staff names returned under `professional_name` (outside the redactor
  PII set) so name resolution works. Issue #81 P1 batch.

- fix(modal): suppress spurious "Se detectaron solapamientos" toast
  after creating an appointment. ``useAppointments.createAppointment``
  mutates the shared ``appointments`` array (same reactive instance the
  parent passes as ``existingAppointments``), so the just-created entry
  briefly self-overlapped with ``formData`` before the modal closed and
  the overlap watcher fired against it. Fix flips
  ``initialDataLoaded`` off at the top of ``handleSave`` — the same
  flag the modal already uses when closing — so the watcher stays quiet
  until the modal reopens.
- fix(modal-tz): "Este slot está fuera del horario" no longer fires
  for in-hours slots when the browser timezone differs from the clinic
  timezone (e.g. Madrid receptionist on an NY clinic). The pre-save
  availability check compared instants — naive form strings interpreted
  as browser-local against ``r.start``/``r.end`` carrying the clinic
  offset — which shifted the slot by the browser↔clinic gap. Now
  compares wall-clock minutes via ``parseIsoParts`` /
  ``isoPartsToDateKey``, mirroring ``useCalendarBounds`` /
  ``useBlockedSegments``.
- feat(notes)!: appointment notes promoted to the polymorphic
  ``clinical_notes`` store. The legacy free-text
  ``appointments.notes`` column is **dropped** (``ag_0005``); the
  ``Notes`` section of ``AppointmentModal`` becomes an
  ``appointment.detail.notes`` slot that ``clinical_notes`` fills with
  ``AppointmentNotesPanel`` (Clínica + Administrativa buttons +
  cronological feed). Patient-facing email templates stop carrying
  the free-text ``notes`` context key (it was internal-only by intent).
  Migration is pre-prod: no data backfill — reset dev with
  ``./scripts/reset-db.sh && ./scripts/seed-demo.sh``.
- feat(ux): `AppointmentModal` header now exposes an "Abrir ficha"
  link next to the selected patient's name. Closes the modal and
  navigates to `/patients/{id}` so receptionists/dentists can jump
  to the clinical record without first cancelling the modal and
  searching the patients list. Gated by `patients.read`; hidden
  when no patient is selected yet.
- fix(calendar-tz): ``useCalendarBounds`` and ``useBlockedSegments``
  now parse the wall-clock hour from the availability ISO string
  verbatim instead of routing it through ``new Date().getHours()``,
  which silently re-interpreted the timestamp in the browser timezone.
  Symptom: a clinic configured for ``9–14, 16–20`` in NY served to a
  Madrid browser rendered as a single ``15–20`` block (morning shift
  shifted into the afternoon, afternoon shift crossed midnight and was
  clipped). Hours are now always clinic-local regardless of browser TZ.
- fix(filters): the professional filter chip strip now scrolls
  horizontally instead of wrapping. With 50+ dentists the wrapped
  rows pushed the calendar grid below the fold, leaving only the
  afternoon visible. The chip strip is now bounded to one row with
  an ``overflow-x-auto`` track; the calendar reclaims its height.
- feat(ux): receptionist can create a new patient inline from the *Nueva cita* modal. The patient selector dropdown surfaces a ``+ Crear paciente "<query>"`` row when the typed name doesn't match an existing record; clicking it opens a 3-field mini-form (nombre, apellidos, teléfono) that POSTs to ``/api/v1/patients`` and auto-selects the created patient. Closes the 30-second "patient on the phone" workflow. See ``docs/features/agenda-quick-patient-create.md`` and ``docs/technical/agenda-quick-patient-create.md``.
- perf(scheduler): replace ``AppointmentDailyView`` overlap-grouping loop with a union-find DSU (extracted to ``composables/calculateOverlapGroups.ts``); pre-bucket appointments by professional once; switch the per-column template ``v-for`` to a Map lookup and add ``v-memo`` so dragging an appointment no longer re-renders the other columns.
- perf(scheduler): ``useBlockedSegments`` now fetches per-professional availability in parallel via ``Promise.all`` (was sequential ``for…of``).
- perf(bundle): wrap ``AppointmentCalendar`` / ``AppointmentDailyView`` / ``AppointmentKanbanView`` / ``AppointmentMobileDayView`` in ``defineAsyncComponent``; the initial ``/agenda`` payload only ships the active mode for the current viewport.
- refactor(dx): extract ``formatLocalDate`` to ``utils/date.ts`` and remove the five duplicate copies across agenda components and the page; new ``frontend/tests/agenda/calculateOverlapGroups.test.ts`` pins the DSU output against fixtures.
- refactor(types): drop the ``as unknown as Record<string, unknown>`` cast pattern in ``useAppointments`` now that ``useApi`` accepts ``object`` payloads directly.
- refactor(perms): migrate the hardcoded ``can('agenda.appointments.write')`` gate in ``UnconfirmedPanel`` to ``PERMISSIONS.appointments.write``.
- fix(isolation): declare ``odontogram`` in ``manifest.depends``. The
  service already imported ``Treatment`` to render appointment
  treatments — the dependency was real, just undeclared.
  ``KNOWN_VIOLATIONS`` allowlist trimmed accordingly.
  (``treatment_plan`` stays as a legit known violation because
  treatment_plan depends on agenda — declaring would cycle.)
- fix(isolation): ``Appointment.patient`` no longer uses
  ``back_populates="appointments"`` — the matching attribute was
  removed from the foundational ``patients`` module. The
  relationship stays one-directional (Appointment → Patient); code
  that needs the reverse side queries agenda directly.
- perf(appointments-list): count query now hits the same indexed
  filters directly instead of materialising a subquery — drops the
  list endpoint from O(rows × eager-load tree) to O(rows) once a
  clinic crosses ~10k appointments.
- docs(user-manual): reescribir pantallas con guía operativa (ES + EN).
- **Slot uniqueness now ignores terminal statuses.** Migration
  `ag_0004` rebuilds the partial unique index
  `idx_appointment_slot` with
  `WHERE status NOT IN ('cancelled', 'completed', 'no_show')`.
  Previously the index excluded only `cancelled`, so a finished
  visit kept reserving its `(clinic, cabinet, professional,
  start_time)` slot and a fresh checked-in appointment couldn't
  be assigned to that cabinet. Slot competition now only applies
  among truly active statuses.
- New frontend slot mount **`appointment.completed.followup`** in
  `AppointmentQuickActions.vue` (issue #62). After a successful
  transition to `completed`, agenda renders a follow-up modal whose
  body is filled by any sibling module registered into the slot
  (e.g. `recalls` "Schedule a recall?" prompt). Modal stays hidden
  when no module has registered into the slot — no behaviour change
  for clinics that don't install recalls.

- Week view (`AppointmentCalendar`) now paints `clinic_closed` ranges per
  day as a hatched overlay, matching the daily view. Late-start mornings,
  early-close evenings, midday gaps and fully-closed days are all
  visually blocked instead of looking bookable. Slot math extracted into
  the new `useBlockedSegments` composable; daily view refactored to use
  it, dropping inline duplication.
- `GET /api/v1/agenda/appointments` now accepts a `patient_id` filter.
  Previously the patient-detail Citas tab passed `patient_id` but the
  endpoint silently ignored it and returned the whole clinic's
  appointments. `AppointmentService.list_appointments` gained a
  keyword-only `patient_id` argument.
- Patient detail → Clínica → Citas: `AppointmentsMode` paginates with
  the shared `PaginationBar` at page_size=20, dropping the hard-coded
  page_size=100 single-page dump.
- Added per-module `CLAUDE.md` for AI-agent context (2026-04-27).
- Mobile agenda: surface free slots for quick emergency booking (#61).
  - New composable `useFreeSlots` computes busy/free/blocked timeline
    entries client-side from appointments + schedules availability.
  - New components `AppointmentMobileTimeline` and
    `AppointmentMobileDaySummary`. Single-track UX (one professional or
    one cabinet at a time), persisted in `localStorage`.
  - Min-duration filter chips (15/20/30/45/60+) hide noisy short gaps;
    short gaps render as faded pills.
  - Free-slot tap pre-fills the appointment composer with start time,
    duration and resource (professional or cabinet).
  - `AppointmentModal` now takes an optional `initialCabinet` prop and
    renders fullscreen on mobile with larger tap targets.

## 0.4.0 — initial documented version

- Appointment CRUD with full state machine.
- Cabinet assignment with `appointment.cabinet_changed` events.
- Visit-level notes via `AppointmentTreatment`.
- Kanban view backed by `kanban_service`.
