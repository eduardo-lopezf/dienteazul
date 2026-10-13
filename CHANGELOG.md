# Changelog

All notable changes to Diente Azul are documented here. Format loosely
follows [Keep a Changelog](https://keepachangelog.com/) and the project
uses [Semantic Versioning](https://semver.org/).

The `v2.0` line is the first to ship with the post-Fase-B module
architecture: the monolithic `clinical` module is gone, replaced by
four purpose-built modules, and every official module now ships its
frontend as a Nuxt layer under its own Python package.

## [Unreleased]

### Added

- **Operations endpoint for the control plane** (`/api/v1/ops`,
  [ADR 0049](docs/adr/0049-the-control-plane-is-a-separate-service.md)
  rule 4; reference in
  [docs/technical/operations-endpoint.md](docs/technical/operations-endpoint.md)).
  `GET /ops/usage` returns the deployment's database and file storage and
  each clinic's share of both; `GET /ops/clinics/{id}/log` returns its
  members' sign-ins and sign-outs and where records were created. Sizes,
  counts and identifiers only — no person's name, e-mail or record
  content. Opened by a short-lived token signed with the new
  `CONTROL_PLANE_SECRET`; absent (`404`) while that is unset, and always
  under `self` custody. `POST /ops/clinics` creates a clinic with its
  holder as administrator: under the individual tiers (`basic`, `medium`,
  `advanced`) the clinic record is the holder's own practice, with their
  name and RFC; the other tiers take the clinic's details. The holder's
  cédula goes to `users.professional_id`, and the password is a temporary
  one the control plane generates and never stores (ADR 0049 rule 6,
  amended).
- **A password that has to be replaced at the first sign-in**
  (`users.must_change_password`, migration `0016`). While it is set
  `get_clinic_context` answers `403` to everything; the account can read
  `/auth/me` and call the new `POST /api/v1/auth/password` — the first way
  a user has of changing their own password — which clears it. The app
  holds such an account on the new `/change-password` screen. The holder
  of a clinic created through `POST /ops/clinics` starts that way.
- **A clinic only has the Apps chosen for it.** `clinics.apps` is now
  applied, per request: the routes of a module whose App is not on the
  clinic's list answer `404` to its members, `/modules/-/active` leaves
  those modules out (so menu, route guard and slots follow), `/auth/me`
  leaves out their permissions, and `GET /apps` reports `enabled` for the
  caller's clinic. A clinic with no list (`NULL`) keeps everything the
  deployment runs. Event handlers and scheduled jobs are not narrowed.
- **The operator's list of Apps is the file, read every time.**
  `GET /ops/apps` reads `apps.json` on each request (`read_app_catalog`)
  instead of the copy cached at boot, and reports `pending_enabled` for an
  App whose status in the file differs from what is running. What is
  mounted is still decided at boot.
- **The holder of a clinic the control plane created is welcomed.** After
  replacing the first password they review the clinic's details, set its
  hours and cabinets or skip them, and accept or decline the privacy
  agreement (`/onboarding`, `clinics.onboarding_pending`, migration
  `0022`). Accepting records `privacy_accepted_at`
  (`POST /auth/clinic/onboarding/accept`); declining deactivates the
  clinic (`…/decline`) until the operator reactivates it. Until then the
  backend answers `403 Onboarding required` to everything the welcome
  does not use. The version accepted is kept
  (`clinics.privacy_accepted_version`, migration `0024`), and a clinic
  that accepted an earlier one has its administrators asked again.
- **A clinic can be given limits of its own.** `clinics.limits`
  (migration `0021`) overrides its tier's limit by limit;
  `PUT /ops/clinics/{id}/limits` sets it, and a limit left out keeps
  following the tier.
- **A clinic can be moved to another account tier on its own.**
  `PUT /ops/clinics/{id}/tier` changes the tier, adds the Apps the new
  one makes mandatory and leaves the rest; the new tier's limits hold
  from the next request.
- **An account tier can be given limits, and they are held.**
  `tier_limits` (migration `0020`) says how many users a clinic of a tier
  may add besides its holder and how much disk its files may take; the
  control plane writes it with `PUT /ops/limits`. `POST /auth/users` and
  every upload into the clinic's folder answer `403` past the limit
  (`app/core/auth/limits.py`). A tier with no row has no limit, so an
  installation without a control plane is unchanged. Settings → Apps →
  Espacio de trabajo shows the clinic what it is allowed and what it uses
  (`GET /auth/clinic/limits`, `admin.clinic.read`).
- **A clinic's Apps can be changed one at a time by the operator.**
  `PUT /ops/clinics/{id}/apps` sets what a clinic has and what it is
  offered, and nothing else, under the rules of creation; it takes effect
  at the clinic's next request.
- **A clinic can be offered Apps to switch on itself.**
  `clinics.available_apps` (migration `0018`) holds the Apps a clinic
  does not have and may enable; the operator sets it through
  `POST`/`PATCH /ops/clinics`. Settings → Apps shows them with a
  *Habilitar* button (`POST /api/v1/apps/{name}/enable`,
  `admin.clinic.write`), which also switches on what the App requires and
  takes effect at once — menu and permissions are read again. There is
  still no way to switch an App off from the clinic.
- **An account held to a password change is taken to it, not told
  "access denied".** The API client sends the user to `/change-password`
  on the backend's `403 Password change required`, as a net under the
  auth middleware: an app that loaded anyway showed "Acceso denegado" on
  every screen with no way forward. `/change-password` no longer bounces
  a signed-in user away.
- **A clinic can be deactivated** (`clinics.deactivated_at`, migration
  `0017`): `POST /ops/clinics/{id}/deactivate` closes it to its members
  without deleting anything, `…/reactivate` opens it again. `GET
  /ops/usage` now gives each clinic a live `status` — `active` (someone is
  signed in), `offline`, `inactive` (no sign-in in fifteen days) or
  `deactivated` — and, once deactivated, the date from which it may be
  deleted for good, ten days later. No route deletes a clinic.
- **A clinic can be created with the specialties chosen for it.** `GET
  /ops/specialties` lists the disciplines (new core contract
  `ReferenceSpecialties`, supplied by `catalog`); `POST /ops/clinics`
  takes `specialties` and passes it on `clinic.created`.
- **One e-mail, one account, one clinic.** `POST /ops/clinics` refuses
  (`409`) an e-mail whose account already belongs to a clinic: a new
  account needs another e-mail, or that user removed from their clinic
  first. An account that belongs to none becomes the holder as it is
  (`holder_existed`). A user's clinics are read oldest first
  (`User.memberships`, `get_clinic_context`, `/auth/me`, `/auth/refresh`),
  so "the first clinic" is the same one on every request.
- **A clinic can be read, changed and — outside production — deleted by
  the operator.** `GET /ops/clinics/{id}` returns everything it was
  created with; `PATCH` changes tier, time zone, tax id, the clinic's own
  details, Apps and specialties under the rules of creation, publishing
  the new `clinic.specialties_set` for the catalog to follow; `DELETE`
  removes the clinic with every row and file of its own and the accounts
  that belonged to no other clinic (`app/core/ops/purge.py`), and answers
  `403` when `ENVIRONMENT=production`.
- **The operator's console manages staff accounts.** `GET
  /ops/clinics/{id}/users` lists a clinic's accounts with their role,
  `PATCH /ops/users/{id}` corrects a profile — names, e-mail,
  professional id, never the password — and `DELETE /ops/users/{id}`
  deletes an account for good **outside production only**: it answers
  `403` when `ENVIRONMENT=production`, and `409` anywhere if records
  still point at the account. ADR 0049 rule 5 is amended: the operator
  sees staff accounts, still no patient data.
- **A clinic is created with a chosen set of Apps.** `GET /ops/apps`
  lists the deployment's Apps with what each requires and the account
  tiers it is mandatory for; `POST /ops/clinics` takes `apps`, refuses a
  set that lacks a mandatory App or a requirement, and stores it in the
  new `clinics.apps` (migration `0015`, nullable: existing clinics keep
  `NULL`, meaning all). **Recorded, not enforced** — every clinic still
  sees every App the deployment runs. `apps.json` gains
  `core_for_tiers`, so an optional App can be core for some account
  tiers: Professionals is, for `clinic`, `clinic_pro` and `hospital`.

- **ADR 0051 — a backend process is one of several**
  ([docs/adr/0051](docs/adr/0051-a-backend-process-is-one-of-several.md)),
  with its working reference in
  [`docs/technical/running-replicas.md`](docs/technical/running-replicas.md)
  and a section in `CLAUDE.md`. Five rules for code that may run as more
  than one process: startup work that writes is serialised, periodic jobs
  run in one process, a module-level variable is never the record, a
  per-process limit is a setting whose default describes one process, and
  every frontend replica runs the same image. It also lists what is not
  covered — first of all that a restart still reaches one process.
  Production keeps running one of each; the entries below are what the
  rules cost in code.

- **A bench for running replicas** — `replicas/docker-compose.yml`, for
  development only. Two backends and two frontends on the images a
  deployment runs, behind an nginx that spreads requests over them and
  says which one answered (`X-Replica`); the app on `localhost:8080`, the
  API on `localhost:8081`. It is a project of its own with its own
  database, and it sits in a folder of its own because the repository's
  `.env` sets `COMPOSE_PROJECT_NAME`, which would otherwise make it the
  development project. Nothing in `docker-compose.yml`, the deploy files or
  the application changed. What it showed on its first run: two backends
  booting together on an empty database raced on the migrations — one
  crashed on `alembic_version` and came back on Docker's restart (closed
  since, see "El arranque del backend se hace de uno en uno" below) — and
  each replica starts its own scheduler, which is still so.

  The frontend needed no change to run on it. Its server keeps nothing
  between requests: the session is two cookies, and the one module-level
  value (`systemInitialized`, in the auth middleware) only ever sticks at
  `true`. The browser suite — 135 tests, every spec but `session-idle`,
  which hard-codes `localhost:3000` — passes against two frontends and two
  backends, requests split evenly between each pair and not one 5xx. Run
  it with `BENCH_ENVIRONMENT=test`, which keeps the login rate limit out of
  the way; the file's header has the command. What replicas of the
  frontend do require is that they all run the same image: two builds of
  the same code already differ in their build id, and two builds of
  different code in the names of their chunks.

- **Fire-and-forget work is tracked** — `app/core/background.py`. `spawn`
  keeps a reference to the task until it finishes (the loop keeps only a
  weak one, so detached work could be collected mid-write) and `drain`
  waits for what is still running. The test suite drains before dropping
  the schema: a straggler writing through its own session deadlocked
  against `DROP TABLE`, which took out four odontogram tests on CI — two
  of them only because the failed teardown left the previous test's rows
  behind. Pinned by `tests/test_background_tasks.py`.

- **A session can now be ended** — invariant 3 of
  [ADR 0029](docs/adr/0029-security-invariants-with-chokepoints.md),
  backend half. `auth_sessions` holds one row per refresh token keyed by
  its `jti`, all rows from one login sharing a `family_id`. Refreshing
  rotates: the presented token is spent and a successor issued. A spent
  or revoked token presented again means two holders and no way to tell
  which is the thief, so the whole family is revoked and the event
  logged. `POST /auth/logout` reaches the server — until now
  `useAuth.logout()` cleared a cookie and left the refresh valid for its
  full seven days. Previously the only revocation was
  `User.token_version`, a global switch incremented in one place, so a
  clinic that lost a laptop could not end that session without ending
  every other one. Not covered: tokens still live in JS-readable cookies,
  and the access token paired with a revoked refresh survives its
  remaining 15 minutes.

- **Dependency advisories are now checked, weekly and on every PR** —
  the first of ADR 0029's out-of-scope items to land, in its own
  `security-audit.yml` rather than in `ci.yml`: a vulnerability is
  published on the world's schedule, so it needs a `schedule:` trigger
  that the two-hour test suite should not inherit. `pip-audit` for the
  backend, `npm audit --audit-level=high` for the frontend, with the full
  low/moderate picture printed alongside. The first run found 10 Python
  and 7 npm advisories. Three npm fixes were taken via `overrides`
  (`dompurify` 3.4.12→3.4.14, which patches an XSS bypass in the very
  library that sanitises copilot LLM output; `nanoid`; `js-yaml`), and
  the `ecdsa` advisory is ignored with a reason — it is reachable only
  through python-jose's EC algorithms, both encode and decode pin HS256,
  and upstream has published no fix. The npm gate runs through
  `scripts/audit-gate.mjs` rather than `npm audit --audit-level=high`,
  because npm has no per-advisory exception and there is exactly one
  advisory out of reach: `nuxt`'s fix is 4.5.x, which needs
  `@nuxtjs/i18n` v10 — bisected, the build fails with two
  `builtin:vite-json` errors and succeeds with the i18n module removed,
  so it is an i18n v9 incompatibility rather than a Nuxt regression, and
  a major-version migration to resolve. Exposure meanwhile is nil, not
  low: the advisory needs a `.server.vue` page rendered as an island and
  the codebase has neither. A stale exception fails the gate as loudly as
  a new advisory.

- **SQL built from string parts is now a test failure** — invariant 4 of
  [ADR 0029](docs/adr/0029-security-invariants-with-chokepoints.md).
  `tests/test_no_dynamic_sql.py` walks the AST of every file under `app/`
  and fails on an f-string, concatenation, `%` or `.format()` reaching a
  SQL-executing call, against an allowlist keyed `path.py::function` so a
  new interpolation elsewhere in a listed file is still caught. Eight of
  the nine existing call sites are safe and listed with a reason; the
  ninth was not — `migration_import.compute_logical_hash` interpolated a
  DPMF entity table name trusting a comment about the file's writer,
  while `reader.entity_iter` validated the same value from the same
  source. `is_safe_identifier` now guards both.

- **Cross-tenant reads are now swept, not assumed** — invariant 2 of
  [ADR 0029](docs/adr/0029-security-invariants-with-chokepoints.md),
  test half. `tests/test_cross_tenant_isolation.py` seeds a second clinic
  and, as an admin of the first, hits every mounted GET route taking a
  `{patient_id}` (35 across 13 modules) or a `{professional_id}`. No
  disclosure was found. Three routes did answer about a patient in
  another tenant, and all three are fixed: the billing summary and the
  payments ledger aggregated under a correct `clinic_id` filter and
  returned zeros, but never checked the patient was the caller's, and now
  404; `notifications/preferences/patient/{id}` was worse — its
  `get_or_create` wrote a row carrying the caller's `clinic_id` and an
  unvalidated `patient_id` FK, so a **GET** created a row in clinic A
  pointing at clinic B's patient, a cross-tenant write performed by a
  read. The `strict=True` xfail baseline ships empty and is meant to stay
  that way. A second sweep covers the verb with the worse ending: seven of
  the 32 mounted DELETE routes, one per module holding patient data, each
  with a foreign row seeded for it. All seven refuse, and the test compares
  the row's existence and its soft-delete markers before and after rather
  than trusting the status code — a 404 that deleted anyway would pass a
  status check and fail the clinic.

- **Every route's authorization is now proven, not assumed** — invariant 1
  of [ADR 0029](docs/adr/0029-security-invariants-with-chokepoints.md).
  `tests/test_route_authorization_coverage.py` walks all 400 mounted
  method+path pairs and fails on any that carries no permission, against
  an allowlist split into "needs no credentials" and "needs a user but no
  permission" — each entry with a reason, and each verified against the
  route's own dependency tree so an entry in the wrong bucket fails too.
  The first run found no unguarded route: all 18 exemptions are
  legitimate. It did find six `schedules` routes that authorize in the
  handler body rather than through a dependency, because the permission
  depends on the path parameter; those now carry a
  `@declares_permissions(...)` marker so the enforcement is declared
  rather than merely present. No behaviour change.

- **Security headers on every response, and secrets that must be real in
  production** — the first two invariants of
  [ADR 0029](docs/adr/0029-security-invariants-with-chokepoints.md).
  The API previously sent no security headers at all; it now sends
  `X-Content-Type-Options`, `X-Frame-Options`, a `default-src 'none'`
  CSP, `Referrer-Policy`, `X-Robots-Tag`, and HSTS in production. The
  rendered app sends the same minus the CSP, plus `no-referrer` and
  `noindex` on `/p/**` — the patient-facing budget link carries its
  token in the path, and
  [ADR 0006](docs/adr/0006-budget-public-link-2-factor-auth.md) assumed
  a `noindex` header that had never existed. Separately,
  `ENVIRONMENT=production` now refuses to boot on a `SECRET_KEY` that is
  short, still the `.env.example` placeholder, or not plausibly random,
  and on a `BUDGET_PUBLIC_SECRET_KEY` that is unset or equal to it —
  two names for one key is not two keys.

- **Privacy settings screen** — a *Privacidad* category in settings with a
  page that handles a patient's access or erasure request and shows the
  log of the ones already handled
  ([ADR 0026](docs/adr/0026-subject-rights-are-a-module-contract.md)).
  Until now the three `/api/v1/privacy` endpoints could only be reached
  with curl, which is not a procedure a clinic can follow. The screen is
  shaped by the two things that make this unlike other settings: the
  reason is required before either action runs (on an erasure it is the
  only record of the request that survives it), and the erasure sits
  behind a confirmation that restates what will happen, then reports the
  sections that legally refused — that refusal is part of the answer the
  clinic owes the patient, not an error. The export downloads as JSON,
  because a portability response is meant to leave the browser.

- **`PrivacyPolicy` — custody and regime declared per tenant**
  ([ADR 0023](docs/adr/0023-privacy-policy-and-custody-modes.md)). Three
  custody modes: `self` (the customer runs the deployment, so no operator
  of ours can reach the data), `managed` (we run it and hold the keys,
  with break-glass operator access that expires, states a reason and
  notifies the clinic) and `byok` (we run it against keys the customer
  holds). The mode determines operator access and key custody rather than
  coexisting with them as flags, so an incoherent policy cannot be
  built. Also carries `jurisdictions` (which documents exist) separately
  from `regulations` (which obligations apply), and a default-deny
  `egress_allowed` set. The policy rides on `TenantContext`;
  `SingleTenantResolver` returns the self-hosted profile, so nothing
  changes for existing deployments. **Declarative only — no component
  enforces it yet.**

- **First-time setup assistant** (issue #85). A fresh install (no users)
  now bootstraps from the UI: `GET /api/v1/auth/setup/status` reports
  whether the system is initialized, and `POST /api/v1/auth/setup`
  atomically creates the first clinic + admin user + admin membership and
  returns tokens. The endpoint is self-closing (409 once any account
  exists). The frontend redirects unauthenticated visitors of an empty
  system to a 2-step `/setup` wizard (admin account → clinic basics);
  remaining configuration is handled by the existing onboarding checklist.

### Changed

- **Dos pestañas ya no se tiran la sesión al refrescar.** Arreglar el
  refresco en el servidor dejó a la vista lo que tapaba: `useRequestFetch`
  conserva las cabeceras que reenvía de la petición entrante y descarta un
  `Headers` pasado al lado, así que `origin` y `x-csrf-token` —las dos que
  `bffFetch` existe para añadir— nunca llegaban y nuestro propio BFF
  respondía `403` a cada refresco en SSR; un render con el token de acceso
  caducado se iba al login en vez de renovar la sesión. Con eso arreglado,
  dos pestañas son dos renders, y rotar gasta el token: `sessions.rotate`
  trata la segunda presentación como un robo y revoca la familia entera, sin
  ventana de cortesía y a propósito. Medido con el servidor en frío, no
  supuesto: la segunda pestaña presentó el mismo token **4,3 s después** que
  la primera —su render había salido con la cookie que tenía al pulsar— y las
  dos perdieron la sesión (`revoked_reason = 'reuse'`). No se solapan, así
  que un cerrojo para llamadas simultáneas no servía de nada: la respuesta
  tiene que sobrevivir a la primera. Ahora el BFF rota una vez por token y
  repite esa respuesta —estado, cabeceras y cuerpo— a quien llegue con el
  mismo durante 10 s (`refreshOnce` en
  `frontend/server/api/v1/[...path].ts`), de modo que todas las pestañas
  acaban con el mismo par de cookies y la familia rota una sola vez. Solo
  recuerda las rotaciones correctas: un rechazo es la respuesta del backend a
  quien preguntó, no necesariamente al siguiente. Lo que cuesta, dicho claro:
  dentro de esa ventana un token robado se responde en vez de disparar la
  revocación —diez segundos, en un solo proceso y solo para un token que ese
  proceso acaba de rotar—; fuera de ahí, y en cualquier otra réplica
  ([ADR 0051](docs/adr/0051-a-backend-process-is-one-of-several.md)), la
  detección de reutilización está intacta. El backend sigue siendo la
  autoridad. [ADR 0054](docs/adr/0054-the-bff-replays-one-rotation-per-refresh-token.md),
  que enmienda la [0052](docs/adr/0052-sessions-use-a-same-origin-http-only-bff.md)
  en el único punto donde decía que el BFF no guarda estado de sesión. Fijado
  por `frontend/tests/e2e/auth-cross-tab.spec.ts:56`, que hay que correr con
  el frontend recién reiniciado: un servidor caliente renderiza lo bastante
  rápido para esconder el hueco.

- **The usage report binds the table name where it is a value.**
  `core/ops/usage.py` sweeps every table carrying a `clinic_id`, and the
  name reached the SQL three times: as the `FROM` identifier, as the
  argument of `pg_total_relation_size`, and as the `area` label of the
  activity log. Only the first is an identifier; the other two were
  interpolated into single-quoted literals, which `_quoted` — it doubles
  embedded double quotes — does not escape for. A table named `od'd "name`
  made the query fail to parse, which is the same door an injected name
  would walk through. Both are bound now (`CAST(:relation AS regclass)`,
  `CAST(:area_n AS text)` — a `::cast` beside a parameter swallows it in
  `text()`), and the two remaining identifier interpolations are listed in
  `tests/test_no_dynamic_sql.py` with their reason.

- **El arranque del backend se hace de uno en uno.** Arrancar no es solo
  leer: migra el esquema, reconcilia el registro de módulos, ejecuta las
  instalaciones y desinstalaciones pendientes — una de las cuales borra
  tablas — y, en una demo, siembra datos. Con un contenedor eso es una
  secuencia; con dos arrancando a la vez era una carrera, y en el banco de
  réplicas uno de los dos moría en la primera sentencia de la primera
  migración (`duplicate key … pg_type_typname_nsp_index`, al crear ambos
  `alembic_version`). Ahora tres bloqueos de PostgreSQL
  (`app/core/advisory_locks.py`) lo ordenan: uno en `alembic/env.py`, que
  cubre el entrypoint, el procesador de módulos y un `alembic upgrade` a
  mano; otro en el lifespan, alrededor de la reconciliación y del
  procesador; y otro en `scripts/seed_demo.py`. El que llega segundo
  espera, encuentra el trabajo hecho y no hace nada. Son bloqueos de
  sesión: los suelta la conexión al cerrarse, así que un proceso que muere
  no deja nada que limpiar. Con una sola réplica no cambia nada — el
  bloqueo se obtiene al instante. Con dos, la segunda tarda en estar lista
  lo que tarde la primera en terminar. Fijado por
  `tests/test_advisory_locks.py` y por
  `test_two_upgrades_at_once_both_succeed` en
  `tests/test_alembic_roundtrip.py`, que sin el bloqueo falla con ese
  mismo error.

- **El límite de intentos y el pool de conexiones son configurables.** Los
  dos eran por proceso y fijos, que es lo correcto con un backend y deja
  de serlo con varios. El limitador (login, registro, refresh, enlace
  público de presupuesto) cuenta en memoria: en el banco de réplicas, con
  dos backends, pasaron 10 logins en un minuto contra un límite de 5.
  `RATE_LIMIT_STORAGE_URI` le da un almacén común (`redis://…`); con él
  pasaron 5. Si el almacén deja de responder, cada proceso vuelve a contar
  en memoria hasta que regresa — medido: con Redis parado el login siguió
  respondiendo, sin un solo 500, y al volver el límite volvió a ser uno.
  El cliente de Redis es un extra de `pyproject.toml` (`redis`) que una
  imagen normal no instala: `--build-arg PIP_EXTRAS=redis`. El pool pasa a
  `DB_POOL_SIZE` y `DB_MAX_OVERFLOW`, con los 10 y 20 de siempre por
  defecto; cada proceso tiene el suyo, así que con varios backends la suma
  tiene que caber en el `max_connections` de PostgreSQL. Sin tocar ninguna
  variable nada cambia: mismo pool, mismo contador en memoria, misma
  imagen sin cliente de Redis. No cubierto: el freno por sesión de los
  agentes (`app/core/agents/guardrails.py`, 10 acciones por minuto) sigue
  contando por proceso, como su propio docstring ya advierte; y
  `pip-audit` en CI no ve el extra, porque no lo instala. Fijado en
  `tests/test_rate_limit_storage.py`.

- **La compuerta de módulos se cierra de verdad, en todos los backends.**
  Entre un `dienteazul modules disable` o `uninstall` y el reinicio, el
  módulo sigue montado; `module_gate` existe para que deje de responder en
  esa ventana (409) en vez de escribir en tablas que van a borrarse
  ([ADR 0018](docs/adr/0018-install-state-is-the-mount-authority.md)). Era
  un conjunto en memoria que cerraba el proceso que cambiaba el estado — y
  ese proceso es la CLI, `python -m app.cli` al lado del servidor, que
  termina al acabar la orden. El servidor nunca se enteraba. Medido en el
  banco de réplicas: `recalls` desactivado desde la CLI y los dos backends
  respondiendo 200 por él hasta que se reiniciaron. Ahora cada backend
  pregunta a `core_module` cada 5 segundos y cierra la compuerta para lo
  que tiene montado y la base dice que está apagado (`disabled`,
  `to_remove`, `uninstalled`); el cierre local e inmediato sigue ahí para
  el proceso que hace el cambio. **Esto cambia el comportamiento con un
  solo backend**: tras la orden, el módulo responde 409 hasta el
  reinicio, que es lo que la documentación ya decía que pasaba. Coste: una
  consulta pequeña cada 5 segundos mientras haya tráfico, y hasta 5
  segundos en los que una petición aún puede entrar. Lo que no cubre: el
  reinicio sigue siendo por proceso — con varios backends hay que
  reiniciarlos todos, y hasta entonces uno ya reiniciado responde 404
  donde otro responde 409 (o 200 donde otro 404, tras un `enable`). Fijado
  en `tests/test_module_gate.py`, sección "Closed from another process".

- **Las tareas programadas se pueden apagar por proceso:
  `SCHEDULER_ENABLED`.** El planificador vive dentro del proceso del
  backend, así que cada backend que lo tiene encendido ejecuta todas las
  tareas: con dos, cada recordatorio de cita, cada aviso de presupuesto y
  cada resumen matutino saldría dos veces. La variable vale `true` por
  defecto — un solo backend sigue haciendo exactamente lo mismo — y con
  varios se deja encendida en uno y se pone a `false` en el resto. En el
  banco de réplicas ese uno es un servicio aparte, `scheduler`: la misma
  imagen, sin tráfico. Medido allí: las tareas corren en `scheduler` y
  ninguna en los dos backends que atienden peticiones. Dos límites, a
  propósito de lo simple que es: nada comprueba que haya exactamente uno
  encendido (con ninguno no corre ninguna tarea, y nadie avisa), y si ese
  proceso cae las tareas esperan a que Docker lo reinicie. Fijado en
  `tests/test_scheduler_jobs.py`.

- **PostgreSQL 15.19, con la imagen fijada por versión y digest.** Las
  bases corrían sobre `postgres:15-alpine`, una etiqueta flotante que se
  descargó en julio y se quedó ahí: PostgreSQL 15.18. La 15.19 corrige 36
  CVE del servidor, varios de ejecución de código con CVSS 8.8 y dos de
  ellos en `pgcrypto`, que la base principal tiene instalado — y un
  escáner de imágenes no lista ninguno, porque PostgreSQL se compila
  desde fuente y no deja paquete que reconocer. De lo que sí lista
  (Docker Scout), la imagen nueva cierra los 10 avisos de `openssl` y los
  4 de `util-linux`: de 71 hallazgos a 57. La referencia a la imagen
  oficial pasa a `postgres:15.19-alpine3.24@sha256:f7d2…`. Es un salto
  menor: mismo volumen, sin volcar ni restaurar. De las notas de la 15.19
  no aplica nada aquí — sin slots de replicación lógica, sin `btree_gist`
  ni `ltree`, y sin funciones PGP de `pgcrypto` en el código.

- **La base corre sobre una imagen propia, sin `gosu` y sin root** —
  `postgres/Dockerfile`, etiquetada `dienteazul-postgres:15.19`. De los 57
  hallazgos que quedaban, 46 eran del runtime de Go con que está
  compilado `gosu` (go1.24.6, la versión más nueva de gosu que existe),
  las dos críticas entre ellos, y ni la imagen oficial más reciente los
  corrige. `gosu` solo sirve para bajar de root a `postgres` al arrancar;
  arrancando ya como `postgres` el entrypoint no lo toca, así que se
  quita. Quitarlo en una capa encima no basta, y está medido: el archivo
  sigue en la capa de abajo y el escáner lo sigue contando, 57 antes y
  después. Por eso la imagen se aplana — el sistema de archivos se copia
  a una imagen vacía — y vuelve a declarar los metadatos que esa copia
  pierde; el build falla si `PG_VERSION` no coincide con el binario.
  Quedan 11 hallazgos, todos de `libxml2` (1 alto), sin arreglo en
  ninguna rama de Alpine: el parche es de la 2.15.4 y Alpine sigue en
  2.13.9. Los volúmenes existentes ya eran del uid 70, así que no hay
  nada que migrar. `docker-compose.yml` y `docker-compose.coolify.yml`
  la construyen; los dos servicios de `ci.yml` siguen en la oficial,
  fijada por digest, porque Actions no construye la imagen de un
  contenedor de servicio. La etiqueta lleva la versión a propósito: un
  cambio de versión cambia la etiqueta, y una etiqueta que Compose no
  tiene es una que tiene que construir — lo contrario de la flotante
  que se quedó tres meses atrás.

- **La imagen del backend deja de llevar el compilador** —
  `backend/Dockerfile` pasa a compilar en una etapa propia y a copiar a
  la imagen final solo el entorno de Python. De 156 hallazgos de Docker
  Scout a 55, y de 1,13 GB a 729 MB. `binutils` solo sumaba 70: `gcc` y
  las cabeceras se instalaban para compilar dependencias y se quedaban
  en producción, donde nada los ejecuta. Fuera también `libcairo2`,
  `libpangocairo`, `libgdk-pixbuf` y `shared-mime-info`, que eran
  requisitos de WeasyPrint antes de la 53 y la 70 ya no carga; con ellos
  se van `libtiff` y el `libxml2` de Debian. Se queda lo que algo llama:
  `psql` y `pg_dump`, y Pango con HarfBuzz. El entorno de producción va
  **sin pip** — en la imagen sería otro hallazgo por nada —; el de
  desarrollo lo conserva. La base queda fijada por versión y digest,
  `python:3.11.17-slim-trixie`, en un solo `ARG`. Las etapas `dev` y
  `prod` siguen llamándose igual y `prod` sigue siendo la última.
  Comprobado: PDF reales de presupuesto y factura por la API, 71 tests
  (autenticación, PDF, medios, XML, procesador de módulos), `pg_dump`
  17 contra el servidor 15.19 y un arranque en frío de la imagen de
  producción sobre una base vacía. De esos 55, dos eran `python-jose` y
  `ecdsa` (la crítica y una alta), que salen en la entrada siguiente, y
  nueve el `pip`, el `setuptools` y el `wheel` que trae la propia imagen
  de Python (2 altas). Esos se desinstalan, pero desinstalarlos no basta
  — siguen en la capa de la imagen base, que es lo que lee el escáner —,
  así que la base del runtime se **aplana**: su sistema de archivos se
  copia a una imagen vacía y los metadatos que esa copia pierde se
  declaran de nuevo. Solo se aplana esa base; el entorno de Python y el
  código siguen siendo capas propias encima, así que un cambio de código
  reconstruye y publica solo el código. Con todo, la imagen queda en
  **44 hallazgos, ninguno crítico y ninguno con arreglo disponible**:
  son de Debian — 4 altas, de `libgcc`/`libstdc++`, `expat` y `zlib` — y
  ya no hay ninguno de paquetes de Python. 710 MB. Al no
  haber lockfile de Python, reconstruir resuelve de nuevo: `asyncpg`
  pasa de 0.31 a 0.32.

- **Las imágenes propias entran en la auditoría semanal**
  ([ADR 0050](docs/adr/0050-a-deployed-image-is-pinned-stripped-and-audited.md))
  — job `image-advisories` de `security-audit.yml`, la tercera pata junto a
  `pip-audit` y la puerta de `npm audit`. Para cada una —la de PostgreSQL,
  la del backend, la de producción del frontend y la del portal de
  documentación— construye la imagen, la pasa por Docker Scout y decide
  con `scripts/image_audit_gate.py`, que sigue la misma regla que
  `audit-gate.mjs`: el suelo es `high`, las excepciones van una a una con
  su razón, y una excepción falla tan alto como un hallazgo nuevo cuando
  deja de reportarse **o cuando su arreglo ya existe**. Cada imagen tiene
  su propia lista: la razón de una excepción habla de esa imagen y no vale
  para otra que lleve el mismo paquete. PostgreSQL tiene una (`libxml2`);
  el frontend y el portal, ninguna — sus informes salen vacíos —; y el
  backend, tres, todas de Debian sin paquete corregido y comprobadas
  contra la imagen: una de `libstdc++`, la de `expat` —el de Debian solo
  lo usa fontconfig; Python lleva el suyo, ya corregido— y la de `zlib`,
  cuyo rango afectado empieza por encima de la 1.3.1 que trae trixie. Eran
  cuatro: Scout dejó de reportar la otra de `libstdc++` el mismo día y la
  regla de excepciones obsoletas la sacó de la lista. Un informe que no es
  de Scout, o una imagen que el script no conoce, sale con error en vez de
  pasar por limpio. El job comprueba además algo que el escáner no puede
  ver: que el digest fijado en cada Dockerfile sigue siendo el que publica
  la etiqueta flotante de esa línea. Es la única señal para los CVE del
  propio PostgreSQL y del propio CPython, y la que habría avisado de los
  tres meses en 15.18. Necesita dos secretos del repositorio,
  `DOCKERHUB_USERNAME` y `DOCKERHUB_TOKEN`, porque Scout solo responde con
  sesión iniciada; sin ellos el job falla diciéndolo, y en un PR desde un
  fork se salta. Aparte, el `5432` de `docker-compose.yml` pasa a
  publicarse solo en `127.0.0.1`: estaba abierto a toda la red de la
  máquina.

- **El portal de documentación pasa a `nginx` slim** —
  `docs/portal/Dockerfile`. La imagen completa de nginx trae módulos que
  el portal no usa (XSLT, filtro de imágenes, GeoIP, njs) y con ellos
  `libxml2`, `libtiff` y `curl`: 18 hallazgos en Docker Scout, 5 altos.
  `nginx.conf` solo usa el núcleo, así que la base pasa a
  `nginx:1.31.6-alpine-slim`, fijada por digest, y pide por nombre y
  versión los dos paquetes que Alpine corrigió después de construirse
  esa imagen, `zlib` y `pcre2`. Resultado: **0 hallazgos**, y de 164 MB a
  92 MB. Responde igual que antes en las rutas comparadas, con las
  cabeceras CORS de la ayuda, la compresión y la caché de estáticos.
  Sigue escuchando en el 80 y arrancando como root, como la imagen
  oficial: cambiar eso es cambiar el puerto que expone el despliegue.

- **`zlib` corregido en la imagen de PostgreSQL** (CVE-2026-85091,
  desbordamiento en las escrituras `gz*` no bloqueantes, zlib 1.3.1.2 a
  1.3.2). Lo encontró el control anterior el mismo día en que se
  escribió: por la mañana la imagen tenía un hallazgo alto y por la tarde
  dos. Alpine lo arregló en 1.3.2-r1 y la imagen oficial fijada se
  construyó antes, con la r0, así que `postgres/Dockerfile` pide
  `zlib>=1.3.2-r1` con nombre y versión — el build falla si no puede
  cumplirlo — hasta que el pin se mueva a una imagen que ya lo traiga. La
  etiqueta pasa a `dienteazul-postgres:15.19-1`: el sufijo cuenta
  nuestras reconstrucciones sobre la misma versión de PostgreSQL, para
  que Compose tenga que construir en vez de reutilizar la anterior.

- **`python-jose` sale; los tokens los firma y verifica PyJWT.** La
  librería acumulaba dos fallos de confusión de algoritmo (CVE-2024-33663
  y CVE-2026-85394, que es su arreglo incompleto) sin versión corregida, y
  arrastraba a `ecdsa` con otro aviso. La auditoría los ignoraba con una
  razón que era cierta — `ALGORITHM` es HS256 con clave simétrica y todo
  `decode` fija `algorithms` —, pero era la única crítica de la imagen
  del backend y una excepción que no caducaba nunca. PyJWT ya era lo que
  usa el panel de control. El cambio son cuatro archivos:
  `core/auth/{service,dependencies,router}.py` y
  `budget/public_router.py`; `JWTError` pasa a `jwt.PyJWTError`. Los
  tokens son JWT estándar, así que **los ya emitidos siguen valiendo**:
  comprobado con tokens de acceso, de refresco y una cookie de
  presupuesto firmados por `python-jose` y verificados después, y con una
  sesión real abierta antes del cambio que se renovó tras él. `pip-audit`
  queda limpio y sus dos `--ignore-vuln` desaparecen de
  `security-audit.yml`. `tests/test_jwt_algorithm_pinning.py` se queda:
  nació para mantener honesta esa excepción, y lo que comprueba es el
  invariante, que ninguna librería debería sostener sola. PyJWT avisa de
  claves HMAC de menos de 32 bytes, así que las dos claves de prueba de
  `ci.yml` que firman tokens se alargan. Con esto la imagen del backend
  se queda sin ninguna crítica.

- **New logo.** The old mark's idea was a pun that died with the rename —
  its dot was "the *Pin* in DentalPin". The new one draws a faceted tooth
  and the Hagall+Bjarkan bind-rune in a single uniform stroke, so they read
  as one figure rather than a badge with something inside it; "Diente Azul"
  is what that rune's own brand is called, in Spanish. Shipped as
  `dienteazul-icon.svg`, `dienteazul-mark.svg` (`currentColor`, inline
  only), `dienteazul-horizontal.svg` and `favicon.svg`. The favicon is
  optically sized rather than merely scaled: heavier stroke and no crossing
  diagonals, because at 16px they close into a blot and take the rest of
  the drawing with them. **Note for whoever owns this decision:** the
  Bluetooth word and figure marks belong to Bluetooth SIG, and a dental
  product whose name translates to theirs, carrying a mark derived from
  their rune, is the shape of a trademark problem.

- **The product is renamed DentalPin → Diente Azul.** 729 occurrences
  across 242 files: `dentalpin` → `dienteazul` in code, `DentalPin` →
  `Diente Azul` in prose and UI, `DENTALPIN_*` → `DIENTEAZUL_*` in
  settings. The Python distribution, the `dienteazul.modules` entry-point
  group, `bin/dienteazul`, the demo-reset script and its cron file, the
  npm package names, the `dienteazul.tenant` Docker label, the
  `dienteazul.settings.*` browser-storage keys and the `dienteazul.com`
  domains all move with it. Logo assets become
  `dienteazul-{icon,mark,horizontal}.svg`; `favicon.svg` keeps its
  conventional name. `migration_import` gains `mig_0005`, renaming
  `dentalpin_table`/`dentalpin_id` to `dienteazul_*` — `mig_0001` still
  creates the old names on purpose, because a migration records what
  happened rather than describing the current schema, and a fresh install
  must end up where an existing one does.

  **Two things deliberately keep the old name.** The `uuid5` seed
  `"dentalpin:legacy-professional:…"` is frozen: five already-applied
  migrations derived profile ids from that exact string, and
  `professionals/providers.py` recomputes them at runtime, so changing it
  would make live code stop finding the rows those migrations wrote. It is
  an identifier, not branding. And the Docker Compose project name still
  comes from the working directory, so containers remain `dentalpin-*`
  until the directory is renamed or `COMPOSE_PROJECT_NAME` is set.

- **A request's writes are committed before its response is sent**
  ([ADR 0031](docs/adr/0031-writes-commit-before-the-response.md)).
  `get_db` committed on its way out, and FastAPI runs that exit after the
  response. A client could get `201` and read back nothing: the quick
  patient-create e2e did on CI. A failed commit came too late to change the
  status. An app-wide `commit_before_response` dependency now commits as
  the endpoint returns. Event handlers therefore finish before the response
  instead of after it. Pinned by `tests/test_commit_before_response.py`.

- **`LICENSE` gains a real Additional Use Grant.** The file carried a
  non-standard "Use Limitation" field and no Additional Use Grant at all,
  so its Terms granted only non-production use while ADR 0004 and the
  README promised free self-hosting — the licence and the documentation
  described different products. The grant now permits production use on
  exactly two routes: a trial authorization the Licensor issues (which
  ties the licence to the token mechanism the packaging brief plans,
  rather than freezing a trial length into licence text) or a separate
  commercial licence. "Production use" is defined as running a clinic on
  real records, self-hosted or hosted for you, so the line does not turn
  on who owns the server. The competing-managed-service exclusion moves
  inside the grant instead of floating as a stray field, and the Change
  Date now reads per version, which is what ADR 0004 always intended.
  **A draft, not legal advice**: it has not been reviewed by counsel.

- **The `LICENSE` names a Licensor that can actually grant a licence.**
  The field read "Diente Azul Contributors", which is not an entity able
  to grant a commercial licence or sign a key, and the Additional Use
  Grant above points both of its routes at the Licensor. It is now
  **Dentared Odontology Services S.L.**, the sole maintainer of the core
  per `COLLABORATORS.md`, whose mandatory CLA grants it the rights to
  maintain, relicense and defend the work — which is what granting a
  licence requires. The copyright line still reads "Diente Azul
  Contributors" on purpose: the same CLA states it does not transfer
  authorship, so contributors remain the owners of their work. Licensor
  and copyright holder are different roles, and merging them would claim
  more than the CLA obtained.

- **`account_tier` is mandatory at creation, and paired with a custody
  mode.** `clinics.account_tier` carried `server_default='clinic'`, so a
  clinic could come into existence without anyone deciding its tier and
  be silently sold as the current product. The default is gone
  (migration `0011`), a `CHECK` restricts the column to the taxonomy, and
  `POST /api/v1/auth/setup` now requires the tier in its payload —
  the first-run wizard grew a selector for it.

  The tier is one half of a commercial pairing whose other half is the
  deployment's custody mode, and **the entry tiers are sold hosted and
  only hosted**: `basic` and `medium` are always `managed`, every other
  tier may be `self`, `managed` or `byok`
  (`backend/app/core/privacy/tiers.py`). The pairing is deliberately
  *not* a database constraint — only one half lives in this database, and
  [ADR 0024](docs/adr/0024-control-plane-holds-what-constrains-the-customer.md)
  rule 2 keeps `custody_mode` out of the data plane precisely so a claim
  about who can read a database is not stored where its own subject can
  rewrite it. It is enforced where both halves are known at once: at
  clinic creation (`422` with the modes that tier is sold under) and at
  boot, where a lifespan audit **warns** if the custody mode was changed
  under clinics whose tier it does not serve. Warns rather than refuses,
  for the reason ADR 0028 rule 3 gives: taking a working clinic offline
  over a commercial rule is worse than the rule being briefly untrue.
  `GET /api/v1/auth/setup/status` now also reports the custody mode and
  the tiers it may create, so the wizard offers a choice that will be
  accepted. This deployment declares `clinic` + `managed` explicitly
  rather than inheriting either.

- **Self-hosting becomes the premium tier, activated by a signed licence
  key** ([ADR 0028](docs/adr/0028-self-hosting-is-the-premium-tier.md),
  with amendments to [ADR 0004](docs/adr/0004-bsl-license.md) and
  [ADR 0023](docs/adr/0023-privacy-policy-and-custody-modes.md)).
  Documentation only — nothing is implemented. The previous implicit
  model had `self` free and `managed` paid, which prices custody
  backwards: `self` is the one mode whose guarantee holds without a
  control behind it (ADR 0023's status table), and it is the mode where
  we hold none of the clinic's data, so charging for `managed` instead
  meant earning more the more patient records we custody. The key is
  verified **offline** — a phone-home would put an outbound channel into
  the one mode sold on the absence of any channel — and it gates only
  what we supply (updates, module installs, support, regulatory
  currency). It never gates clinical reads, backups, or the
  subject-rights endpoints from
  [ADR 0026](docs/adr/0026-subject-rights-are-a-module-contract.md):
  suspending those on non-payment would make the clinic breach LFPDPPP
  on our schedule. A deployment with no key runs in a labelled
  evaluation state, which is the non-production use the BSL already
  grants. Two things this exposes: `LICENSE` carries no *Additional Use
  Grant*, so its Terms grant only non-production use while ADR 0004 and
  the README were promising free self-hosting — the file needs redrafting
  by counsel, and existing production self-hosters should be
  grandfathered by name rather than argued with. The packaging side —
  the tier × delivery matrix, what may and may not be gated, and the
  four licence states — is drafted in
  [`docs/features/licensing-and-packaging.md`](docs/features/licensing-and-packaging.md),
  with every price, unit and duration explicitly left open. That brief
  also records two mechanisms as **pending**: a trial period per
  `account_tier`, and temporary access to a higher tier's features. Both
  activate through a token, and the token is deliberately *not* the
  licence key — issued often rather than once, redeemed by a user rather
  than read at boot, expiring on its own — so it is handled separately in
  the security model. Two constraints on it are not pending: expiry never
  takes away data created while the feature was available (reads,
  exports and subject rights over it must survive), and a trial is never
  the reason a clinic has the compliance floor. That floor now names an
  **export guarantee**: a clinic can always take its own data out as CSV,
  under any tier, in any licence state, with every trial and token
  expired. Recorded as a promise with its gap stated — the only export
  that ships today is the per-patient subject-rights one and it returns
  JSON, while the only CSV in the codebase belongs to the optional
  `accounting_export` module, which is precisely the kind of tier-gated
  placement the guarantee forbids. The gap is tracked in
  [`docs/technical/todos.md`](docs/technical/todos.md), together with the
  tension it has to resolve: `modules_enabled` gates what runs, so a tier
  that excludes a module would otherwise leave that module's data
  unexportable.

- **Two-plane data model recorded**
  ([ADR 0024](docs/adr/0024-control-plane-holds-what-constrains-the-customer.md)):
  the data plane holds what the customer owns, the control plane holds
  what constrains them. Fixes where `tenant_id`, `custody_mode`,
  `clinic_id` and `account_tier` are each authoritative, rules out a
  tenant→clinic foreign key (it crosses a database boundary by design),
  and specifies a signed single-row `tenant_identity` mirror so a
  restored backup can name its tenant without becoming a forgeable
  custody claim. Design only — no control plane exists yet.

- **`clinics.tenant_type` renamed to `clinics.account_tier`** (migration
  `0009`, API field and locale key `auth.accountTiers` renamed with it).
  The column holds a commercial tier for one clinic; "tenant" in this
  codebase is the DB-isolation unit a clinic lives inside (ADR 0012). With
  custody landing on the tenant (ADR 0023), a control plane would have put
  `tenants.custody_mode` next to `clinics.tenant_type` and the two would
  have read as one axis. Renamed while nothing gates on the column. The
  migration is a rename, so tiers already stored survive.

- Recorded the pending compliance work for the primary market in
  [todos](docs/technical/todos.md): the **LFPDPPP obligations** with no
  implementation at all (express written consent for health data as a
  *dato personal sensible*, the *aviso de privacidad*, and the processing
  contract that hosting implies), the **retention policies** that would
  replace each contributor's `retention_reason` prose with an actual
  window from NOM-004-SSA3-2012 and CFF art. 30, and the shape problem
  ARCO poses for `core_subject_request` — it records requests already
  executed, while statutory deadlines need them recorded on arrival.
  Flagged as unverified: Mexico's law was replaced in March 2025 and
  oversight moved away from INAI.

- Recorded the clinical-record **access log** and **break-glass operator
  access** as deliberately deferred, and deferred *together*
  ([todos](docs/technical/todos.md), amendment in
  [ADR 0023](docs/adr/0023-privacy-policy-and-custody-modes.md)).
  Break-glass built in the application alone would be theatre while an
  operator keeps a standing `psql` connection, so making `managed` true
  starts with infrastructure; and the access log is that mechanism's
  prerequisite, since an emergency session with no access log records
  nothing. Order when picked up: remove standing DB access → access log →
  break-glass sessions.

- **Modules declare where they send data**
  ([ADR 0027](docs/adr/0027-egress-is-declared-in-the-manifest.md)).
  `manifest.egress` names each external destination — its id, the
  subprocessor's legal name, the purpose, which `DataClass`es leave, and
  whether the module works without it — which finally gives
  `PrivacyPolicy.egress_allowed` something to compare against. Four
  destinations were declared: `openai` (copilot), `kapso`
  (whatsapp_kapso), `aeat` (verifactu) and `smtp` (notifications). That
  last one was the easiest to miss: reminders leave through whatever SMTP
  server the clinic configures, so the receiving party is configuration
  rather than a vendor named in code. `docs/subprocessors-catalog.md` —
  the register a clinic attaches to its DPA — is now **generated** from
  the manifests, and CI fails on drift. A boot audit names every module
  whose destination `TENANT_EGRESS_ALLOWED` does not permit, and a test
  fails when a module imports an HTTP or SMTP client without declaring.
  **Reported, not blocked**: enforcing a default-deny field nobody has
  had a release to fill in would unplug the copilot and stop reminders on
  every existing deployment.

- **Subject rights have an HTTP surface** at `/api/v1/privacy`
  ([ADR 0026](docs/adr/0026-subject-rights-are-a-module-contract.md)):
  export a patient's data, erase it, and read the log of exercised
  rights. Gated on three new core permissions
  (`privacy.subject.{read,export,erase}`) rather than on `patients.read`,
  because an export hands out every module's data on one patient in a
  single response and an erasure cannot be undone. Both require a stated
  reason, and both write a `core_subject_request` row (migration `0010`)
  recording who acted, when, why and what each section did — but **not
  what the data said**, so the record survives the erasure it documents.
  Without it, an erasure would be indistinguishable from a bug that
  emptied the columns. The export also reports, per section, whether an
  erasure would reach it and the retention reason when it would not, so a
  patient can see what cannot be removed without asking twice.

- **Every module that holds patient data now answers a subject request.**
  Coverage went from 3 modules to 16, 21 contributors in total, wired on
  the principle that decides each one: *identity is erased, the record is
  retained and thereby becomes pseudonymous*. Clinical modules (`agenda`,
  `odontogram`, `periodontogram`, `treatment_plan`, `clinical_notes`,
  `media`) and fiscal ones (`billing`, `payments`, `verifactu`) export and
  retain with a stated reason; outreach and working data (`recalls`,
  `notifications`, `patient_timeline`, `budget`, `migration_import`) are
  erased, free text included. `migration_import` was the easiest blind
  spot to miss — it keeps the source system's patient row verbatim in
  JSON, reachable only through the canonical-id mapping. A test now fails
  when a module contributes nothing and is not on an explicit
  silent-by-design list, and every contributor's queries are executed
  against a real patient so a broken parent/child chain cannot ship.
  `copilot` stays an honest gap: its transcripts hold patient names but
  its `context` blob has no shape to query. **The retention calls are a
  first pass, not settled law.**

- Classified `communication_messages.to_address` (the patient's email or
  phone) under a new `PiiKind.CONTACT`. The PII contract's name-based
  heuristic could not see it.

- **Subject rights are a module contract**
  ([ADR 0026](docs/adr/0026-subject-rights-are-a-module-contract.md)).
  `BaseModule.get_subject_contributors()` lets each module answer for its
  own data when a patient asks for a copy of their record or for it to be
  erased — core cannot, since ADR 0001 forbids it from importing module
  code. Export is unconditional; erasure is not: a contributor either
  supplies `anonymize` or states a `retention_reason`, and supplying
  neither raises at construction, so a module cannot stay silent about
  whether its data is erasable. `billing` is the case that shapes the
  design — an issued invoice is a fiscal document and declines erasure
  with a reason written for the patient. `anonymize_instance()` scrubs
  the columns ADR 0025 classified and skips `DataClass.FINANCIAL`, giving
  that field its first enforcer. Wired in `patients`,
  `patients_clinical` and `billing`; **the other 19 modules contribute
  nothing yet, and there is no HTTP surface** — see the ADR's trade-offs.

- **The deployment declares its own custody mode**
  (`TENANT_CUSTODY_MODE`, default `managed`; see *Amendment 1* of
  [ADR 0023](docs/adr/0023-privacy-policy-and-custody-modes.md)). The
  resolver previously hardcoded `self`, which meant the system asserted
  no operator could read data an operator was in fact reading. Two
  companion settings: `TENANT_JURISDICTIONS` (default `MX,ES`, which also
  widens the copilot's PHI boundary to Spanish document names) and
  `TENANT_DATA_RESIDENCY` (empty resolves to `on-prem` under `self`,
  `unspecified` otherwise — reporting `on-prem` for a hosted deployment
  would be a lie rather than a gap). An unrecognised mode refuses to
  start. **The modes state who holds what, not an enforced control:**
  `managed` names break-glass operator access and no such mechanism
  exists yet, `byok` is out of scope for this stage, and both log a
  warning naming the gap on every boot.

- **Imported patients could not be saved.** `PatientMapper` labels every
  identifier it imports from Gesdén `nif`, and the patients schema
  accepted only `curp`/`ine`/`passport`. The mapper writes to the model
  directly, so the bad value landed silently and surfaced later: the
  demographics edit modal loads `national_id_type` into its form and
  sends it back untouched, so the first save of any imported patient
  returned 422 until the user changed the dropdown by hand. The accepted
  set is now the union of both markets the deployment serves, grouped by
  jurisdiction (`NATIONAL_ID_TYPES_BY_JURISDICTION`), with the Spanish
  documents added to the edit form and both locales. Existing rows become
  valid without a data migration.

- **PII is classified on the column, and the classification is enforced**
  ([ADR 0025](docs/adr/0025-pii-is-classified-on-the-column.md)). A column
  holding personal data declares it —
  `mapped_column(..., info=pii(PiiKind.NATIONAL_ID))` — and the copilot's
  redactor derives its key map from those declarations instead of a list
  kept alongside it, which had drifted from the schema every time either
  side moved. `tests/test_pii_redaction_contract.py` fails when a
  personal-looking column carries neither a classification nor a reasoned
  allowlist entry, in the same shape as
  `test_event_transaction_boundary.py`. Writing that test found nine
  columns that were reaching the cloud model in cleartext:
  `invoices.billing_name`/`billing_tax_id`/`billing_email`,
  `budget_signatures.signed_by_name`/`signed_by_email`,
  `verifactu_settings.producer_nif`/`producer_name`,
  `verifactu_certificates.nif_titular` and
  `whatsapp_kapso_settings.display_phone_number`. The check imports every
  table-declaring file itself instead of reading `Base.metadata` as it
  finds it, so it sees all 92 model tables regardless of which tests ran
  first and ignores the synthetic tables other tests register there. The companion
  `DataClass` axis (identifier / clinical / financial / operational) is
  recorded now for the retention and subject-rights work; nothing reads
  it yet.

- **The copilot's PII redaction now follows the tenant's jurisdictions.**
  `Redactor.for_policy()` builds its key map from
  `PrivacyPolicy.jurisdictions` (ADR 0023) instead of a module-level
  constant, so an `ES` tenant tokenizes a NIE and an `MX` one a CURP. The
  field names this schema defines (`national_id`, `tax_id`,
  `billing_tax_id`, `dni`, `nif`) stay redacted under every jurisdiction.
  A redactor built without a policy falls back to every known
  jurisdiction — over-redacting rather than leaking — and an unmodelled
  country logs a warning instead of failing silently. The tenant reaches
  the request through a new `get_tenant` dependency, installed on
  `app.state` by the lifespan (the read half of ADR 0012 Fase 2a;
  `get_db` is untouched).

- **Jurisdiction wording aligned with the market.** Several Spanish
  strings still named Spanish documents over columns that hold Mexican
  ones: the `search_patients` tool description ("DNI/NIE"), the
  legal-guardian ID label, the patient billing tax-id label, and the
  clinic-info onboarding hint. They now name the documents the schema
  actually accepts (CURP / INE / passport, RFC). English strings were
  already jurisdiction-neutral and are untouched.

- **PHI redaction now covers Mexican identifiers.** The copilot's PII key
  denylist (`backend/app/core/agents/redaction.py`) carried Spanish
  document names only, so a CURP or an RFC named as such reached the cloud
  LLM in cleartext, and `Patient.billing_tax_id` was never tokenized at
  all. The keys are now split in two families: `_SCHEMA_ID_KEYS`
  (`national_id`, `tax_id`, `billing_tax_id`, `dni`, `nif` — field names
  this codebase actually uses, redacted unconditionally because the
  deployment serves both markets) and the per-jurisdiction document names,
  of which `_MEXICO_ID_KEYS` (`curp`, `rfc`, `ine`) is the active profile
  and `_SPAIN_ID_KEYS` is declared for when the selection becomes
  geography-driven.

- Removed the public `POST /api/v1/auth/register` endpoint. It created
  orphan users with no clinic membership (unusable, and unused by the UI);
  the first-run setup assistant replaces it.

- Alembic history squashed. The 29-migration main-linear chain
  inherited from Fase A collapsed into one `0001_core_initial` for
  core tables + 11 module-owned initials under
  `backend/app/modules/<name>/migrations/versions/<mod>_0001_initial.py`.
  Each module's initial lives in its own package so community module
  authors can pattern-match their own migrations on the official
  examples. Cross-module FKs live on the "late" side — the only
  circular dep (`appointment_treatments.planned_treatment_item_id`
  → `planned_treatment_items`) is created in `tp_0001` after both
  tables exist. Round-trip `upgrade head → downgrade base → upgrade
  head` is clean and `test_alembic_roundtrip` no longer xfails.

## [2.0.0] - 2026-04-21

First release on the post-Fase-B module architecture. Covers the
full Fase B refactor (B.1 → B.6), the hardening pass (B.7), and the
Playwright E2E smoke suite (B.8). `main` is stable against the
12-module layout; the `clinical` module is gone.

### Added

- **Module `patients`** (`auto_install: True, removable: False`) —
  Patient identity, demographics, billing info. Endpoints under
  `/api/v1/patients/*`. Permissions under `patients.*`.
- **Module `patients_clinical`** (`auto_install: True, removable: True`)
  — normalized medical history with 7 tables
  (`patients_clinical_medical_context`, `_allergy`, `_medication`,
  `_systemic_disease`, `_surgical_history`, `_emergency_contact`,
  `_legal_guardian`). Endpoints under `/api/v1/patients_clinical/*`.
  Alerts (`/alerts`) now derive from real rows — actual SQL analytics
  over allergies / diseases is possible.
- **Module `agenda`** (`auto_install: True, removable: True`) —
  Appointment, AppointmentTreatment, Cabinet. Cabinets promoted from
  the `clinic.cabinets` JSONB to a real table with FK
  (`appointments.cabinet_id`). Endpoints under `/api/v1/agenda/*`.
- **Module `patient_timeline`** (`auto_install: True, removable: True`)
  — cross-module audit log, populated via event subscriptions.
  Endpoints under `/api/v1/patient_timeline/*`.
- Clinic metadata endpoints moved into core auth:
  `GET/PUT /api/v1/auth/clinics`.
- Nuxt layer support for every official module. Each module now ships
  `<module>/frontend/{pages,components,composables,i18n}` and is
  auto-discovered at boot via `modules.json`.
- New pytest marker `alembic_roundtrip` for the full
  `base → head → base → head` migration-chain check; excluded from
  the default pytest run, executed as a dedicated CI step.
- CI pipeline gains `manifest-consistency` and `frontend-typecheck`
  jobs (Nuxt `prepare` pass that catches broken Vue/TS imports across
  module layers).
- Playwright browser E2E suite under `frontend/tests/e2e/` — 16
  smoke tests covering admin navigation across every module layer,
  patient detail rendering, and per-role sidebar visibility. CI `e2e`
  job boots docker-compose + seeds demo + runs Playwright.
  `./scripts/e2e.sh` wrapper for local runs.

### Changed

- **Breaking — API paths**
  - `GET /api/v1/clinical/patients/*` → `GET /api/v1/patients/*`
  - `.../medical-history`, `.../alerts`, `.../emergency-contact`,
    `.../legal-guardian` → `/api/v1/patients_clinical/patients/{id}/...`
  - `GET /api/v1/clinical/appointments/*` → `/api/v1/agenda/appointments/*`
  - `GET /api/v1/clinical/clinics/*` → `/api/v1/auth/clinics/*`
  - Patient timeline read at `/api/v1/patient_timeline/patients/{id}`
- **Breaking — permissions**
  - `clinical.patients.*` → `patients.*`
  - `clinical.patients.medical.*` → `patients_clinical.medical.*`
  - `clinical.patients.emergency.*` → `patients_clinical.emergency.*`
  - `clinical.appointments.*` → `agenda.appointments.*`
  - `clinical.appointments.cabinets.*` → `agenda.cabinets.*`
- Every official module manifest's `depends` rewritten against the
  real modules (patients / agenda / catalog / budget) instead of the
  now-removed `clinical`.
- `Patient.active_alerts` property removed (alerts compute via
  `PatientsClinicalService.compute_alerts`).
- Dashboard + Settings sidebar entries are host-owned (see
  `frontend/app/utils/moduleRegistry.ts::HOST_NAV`); modules no
  longer publish `/` or `/settings`.
- Auth rate limiter only activates in `ENVIRONMENT=production`.
  Dev + test runs were tripping the 5/min `/login` cap during manual
  reloads and Playwright runs; production semantics unchanged.

### Removed

- **Breaking — module `clinical`** — fully deleted. All downstream
  depends point at the real owning modules.
- `patients.medical_history`, `patients.emergency_contact`,
  `patients.legal_guardian` JSONB columns dropped — data migrated to
  the normalized `patients_clinical_*` tables in
  `w3x4y5z6a7b8_add_patients_clinical_tables.py`.
- `clinic.cabinets` JSONB column dropped — replaced by the `cabinets`
  table in `v2w3x4y5z6a7_add_cabinets_table.py`.

### Frontend layer conventions

- Each layer's `nuxt.config.ts` must register
  `components: [{path: './components', pathPrefix: false}]`; the host
  overrides Nuxt's default auto-scan so this is load-bearing.
- Cross-layer type imports use `~~/app/types` (rootDir-relative, = host
  frontend) instead of `~/types` (srcDir-relative, which would scope
  to the current layer).

### Known gaps (deferred)

- Alembic chain still lives as a single main-linear list. The squash
  that breaks it into per-module branches (one clean initial per
  module) is deferred; `test_alembic_roundtrip` is `xfail` until
  then and exists purely to hold the infrastructure in place.
- Docs (`docs/diagrams/*`, `CLAUDE.md` examples) still reference the
  old `/api/v1/clinical/*` paths in a handful of illustrative spots;
  the primary `docs/technical/creating-modules.md` and `docs/technical/core-api.md` are
  up to date.
