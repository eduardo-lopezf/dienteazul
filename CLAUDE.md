# CLAUDE.md

Working notes for AI agents on Diente Azul.

## Project

Diente Azul — open-source dental clinic management software with a modular plugin architecture.

| Component | Tech |
|-----------|------|
| Backend | FastAPI (Python 3.11+), SQLAlchemy 2.0, Alembic |
| Frontend | Vue 3, Nuxt 3, Nuxt UI, TypeScript |
| Database | PostgreSQL (asyncpg) |
| Auth | JWT (access + refresh) |
| Container | Docker Compose |

License: BSL 1.1 (converts to Apache 2.0 after 4 years).

---

## Modular architecture (read first)

Diente Azul is built as independent modules under `backend/app/modules/<name>/` with matching Nuxt layers. Treat the boundary as a contract.

**Hard rules:**
- Respect module isolation. Do **not** create cross-module dependencies that are not declared in the module's `manifest.depends` or `manifest.integrates`.
- Prefer the **event bus** for cross-module reactions. Direct service-to-service imports across modules are forbidden unless the target is in `depends` or `integrates`.
- Cross-module FKs are allowed **only** when the target is in `depends` or `integrates`. CI rejects migrations otherwise.
- **A screen hosts other Apps through slots** ([ADR 0041](./docs/adr/0041-a-screen-hosts-other-apps-through-slots.md)). The Patients App's frontend uses no component and calls no API of a module outside it; `frontend/tests/app-frontend-isolation.test.ts` fails if it does. To show your module's part of a patient, register a tab (`patient.detail.tabs`) or a slot entry with a `loader` — never import into the host.
- **Prefer a core contract to an import** ([ADR 0039](./docs/adr/0039-modules-reach-each-other-through-core-contracts.md)). To validate or label another module's record, ask `contracts.provider(Contract)` (`app/core/contracts.py`); the owner supplies it from `get_providers()`. `None` means that App is off. `agenda` imports no other module — keep it that way: widen a contract instead.
- **`depends` is required, `integrates` is optional** ([ADR 0037](./docs/adr/0037-a-module-integrates-with-what-it-can-live-without.md)). A module must keep working while something it `integrates` is disabled: guard with `module_registry.is_installed()`, offer none of its records, write nothing to it, delete nothing. Columns pointing at an integration are nullable.
- Each module owns its Alembic branch (`branch_labels = ("<name>",)`). Never thread one module's revisions through another's chain — uninstall safety depends on it (issue #56).
- Permissions are namespaced: a module returns `resource.action` from `get_permissions()`; the registry prefixes with the module name.
- **`core_module.state` decides what runs** ([ADR 0018](./docs/adr/0018-install-state-is-the-mount-authority.md)). Never derive routes, handlers, tools, permissions, jobs or migration targets from what is on disk. `module_registry.list_discovered()` is the inventory; `list_modules()` / `is_installed()` is the active set.
- **`backend/apps.json` can hold a whole App back** ([ADR 0038](./docs/adr/0038-apps-json-switches-apps-for-the-whole-deployment.md)): its modules stay `installed` but are not mounted, and their dependents keep running — unless an App lists the one switched off in its `requires_apps`, and then it goes off with it ([ADR 0053](./docs/adr/0053-an-app-can-declare-the-apps-it-goes-off-with.md); only the Clinical record does, with Patients). So a module in `depends` may not be running — check `module_registry.is_installed()` before calling into it, and on the frontend send people to the agenda through `useAppointmentBooking()`, never `router.push('/appointments')`. A page that belongs to an App in `apps.json` gets a row in `frontend/app/config/appRoutes.ts` so `useAppRouteGuard` can turn visits away while the App is off.
- **Switching a module off is `disable`, never `uninstall`** ([ADR 0035](./docs/adr/0035-apps-are-disabled-not-uninstalled.md)). A disabled module keeps its tables and its branch keeps being migrated; only what is mounted changes. Do not write code that assumes a module's tables are absent because it is not running.

**Before adding a feature, read `docs/technical/creating-modules.md`** — it is the source of truth for module structure, lifecycle, manifest, slots, events, tools/agents, and migrations.

**Engineering posture:**
- Think deeply before coding. Avoid over-engineering. Build only what the task needs.
- Refactor opportunistically when you spot duplication or drift, but keep refactors scoped — no drive-by rewrites.
- Do not introduce tech debt. If a shortcut is unavoidable, surface it explicitly in the PR description.

---

## When adding X, do Y (agent checklists)

| Trigger | Required actions |
|---------|------------------|
| New page that belongs to an App in `backend/apps.json` | Add its path prefix to `frontend/app/config/appRoutes.ts`. Without it the page stays reachable by URL while the App is off. |
| New App, or a module changes App | Edit `backend/apps.json` — every module belongs to exactly one App ([ADR 0044](./docs/adr/0044-the-app-organises-the-module-holds-the-code.md)). Create `docs/apps/<app>/{README.md,CHANGELOG.md}`. Add the App to `IMPORTS`/`REQUIRES` in `backend/tests/test_app_isolation.py`, its title and summary to `settings.apps.catalog` in both locales, its icon (and its settings page, if it has one) to `frontend/app/config/appCatalog.ts`, and its pages to `frontend/app/config/appRoutes.ts`. Run `python backend/scripts/generate_catalogs.py`. Never move a module's folder for it. |
| New module | Create `backend/app/modules/<name>/CLAUDE.md` + `CHANGELOG.md`. Create `docs/technical/<name>/{overview,events,permissions}.md`. If the module has Nuxt pages, also `docs/user-manual/{en,es}/<name>/{index.md, screens/<slug>.md}` per page. Run `python backend/scripts/generate_catalogs.py`. Follow `docs/checklists/new-module.md`. |
| New screen (page under `<module>/frontend/pages/**`) | Create both `docs/user-manual/en/<module>/screens/<slug>.md` and `docs/user-manual/es/<module>/screens/<slug>.md` with the [frontmatter contract](./docs/technical/documentation-portal.md#2-frontmatter-contract-the-part-claude-relies-on). Screenshots into `docs/screenshots/<module>/`. |
| New interactive surface (any screen or component with controls) | Nothing to do for tap targets — `main.css` enforces the 44 px minimum under `(pointer: coarse)`. If the surface's cells are units of time or anatomy rather than buttons, put `data-dense` on a container **and** pair it with a real touch interaction; it is a debt marker, never a way to silence the audit. Add the route to `frontend/tests/e2e/tablet-touch.spec.ts` if it matters on tablet. See [`docs/technical/touch-adaptation.md`](./docs/technical/touch-adaptation.md) ([ADR 0022](./docs/adr/0022-touch-adaptation-is-capability-driven.md)). |
| New model column holding personal data | Classify it on the column: `mapped_column(..., info=pii(PiiKind.NAME))` ([ADR 0025](./docs/adr/0025-pii-is-classified-on-the-column.md)). `PiiKind` picks the redaction token family; pass `data_class=` when it is not a plain `IDENTIFIER` (billing → `FINANCIAL`). `tests/test_pii_redaction_contract.py` fails on a personal-looking column that carries neither a classification nor a reasoned entry in its `_NOT_PERSONAL` allowlist. |
| Module calls an external service | Declare it in `manifest.egress` ([ADR 0027](./docs/adr/0027-egress-is-declared-in-the-manifest.md)): `target` (id matched against `TENANT_EGRESS_ALLOWED`), `subprocessor` (legal name for the DPA), `purpose` (prose a clinic can show a patient), `data_classes` and `required`. Re-run `generate_catalogs.py` — `docs/subprocessors-catalog.md` is generated and CI fails on drift. `tests/test_egress_declarations.py` fails when a module imports an HTTP/SMTP client without declaring. |
| New module (or new table) holding patient data | Implement `get_subject_contributors()` in the module's `privacy.py` ([ADR 0026](./docs/adr/0026-subject-rights-are-a-module-contract.md)). Every contributor `export`s; it then either supplies `anonymize` (use `anonymize_instance(row)` — it reads the `pii()` classification and spares `FINANCIAL` columns) **or** states a `retention_reason` saying why the law forbids erasure. Supplying neither raises. A module that skips the hook contributes nothing to an export and survives an erasure request silently. |
| New endpoint | Document under the gating permission's row in `docs/technical/<module>/permissions.md`. Bump `last_verified_commit` on every screen MD whose `related_endpoints` covers it. |
| New event published or consumed | Publish with `event_bus.publish_after_commit(db, ...)` (ADR 0019). Add to `EventType` in `backend/app/core/events/types.py`. Add row to `docs/technical/<module>/events.md`. Re-run `generate_catalogs.py`. Document publisher payload in module CLAUDE.md. |
| New permission | Return from `get_permissions()` (no module prefix). List in `manifest.role_permissions`. Add row to `docs/technical/<module>/permissions.md`. Add to `frontend/app/config/permissions.ts` if user-facing. |
| New agent-exposed capability | Declare a `Tool` in `backend/app/modules/<name>/tools.py` and return it from the module's `get_tools()`. **Wrap an existing service method — never duplicate business logic.** Filter by `ctx.clinic_id`. Set `permissions=[...]` to the gating RBAC string the HTTP route uses, and `category` conservatively (`WRITE` for mutations, `DESTRUCTIVE` for deletes/irreversible side-effects). Set `exposes_free_text=True` if the result is free prose (it is then excluded from the cloud LLM path under redaction). **Return native values (UUID/Decimal/datetime/Pydantic) — `jsonify` at the registry chokepoint coerces them; don't hand-`str()`/`.isoformat()`/`float()`.** Return PII under the **column's own name** (`first_name`, `phone`, `email`, `national_id`) so the classification on that column tokenizes it ([ADR 0025](./docs/adr/0025-pii-is-classified-on-the-column.md)); a key you invent is not covered by anything. `full_name`, `patient_name` and `mobile` are the composed keys the redactor also knows. Government-document names (`curp`, `rfc`, `dni`, …) tokenize only under the tenant's `PrivacyPolicy.jurisdictions` ([ADR 0023](./docs/adr/0023-privacy-policy-and-custody-modes.md)). Document it under "Tools exposed" in the module CLAUDE.md. See [`docs/technical/copilot-agentic-architecture.md`](./docs/technical/copilot-agentic-architecture.md) §3. |
| Touched a screen's behaviour or visuals | Update the matching screen MD in **both** `docs/user-manual/{en,es}/<module>/screens/`. Refresh screenshots if visuals changed. Bump `last_verified_commit` in each locale. |
| Architectural decision | Copy `docs/adr/TEMPLATE.md` → `docs/adr/NNNN-title.md`. |
| New domain term (ES↔EN) | Append to `docs/glossary.md`. |
| New documentation file | Pick the folder by type from the **Documentation policy** table below. Never drop new files at `docs/` root. |
| Touched any module | Update its `backend/app/modules/<name>/CHANGELOG.md` under `## Unreleased`. |
| Cross-module FK or import | Target module MUST be in `manifest.depends` or `manifest.integrates`. CI rejects otherwise. |

Full docs-update recipe: [`docs/checklists/updating-docs.md`](./docs/checklists/updating-docs.md).
Architecture + rationale: [`docs/technical/documentation-portal.md`](./docs/technical/documentation-portal.md) ([ADR 0009](./docs/adr/0009-documentation-portal.md)).

Reference material:

- Checklists: `docs/checklists/`
- Per-module CLAUDE.md template: `docs/checklists/module-claude-template.md`
- ADRs: `docs/adr/` (start with 0001 for the modular contract)
- Glossary: `docs/glossary.md`
- Apps catalog: `docs/apps-catalog.md` (auto-generated); what each App is for: `docs/apps/<app>/`
- Module catalog: `docs/modules-catalog.md` (auto-generated)
- Event catalog: `docs/events-catalog.md` (auto-generated)
- Reference modules to copy from: `patients` (simple), `schedules` (removable), `treatment_plan` (heavy deps), `verifactu` (compliance)

---

## Documentation policy

`/docs` is organized by **type** of doc. Pick the folder from the table; never drop new files at `docs/` root. CI (`scripts/check_docs_layout.py`) enforces this.

| Doc type | Folder |
|----------|--------|
| End-user / admin how-to (Spanish, screenshots) | `docs/user-manual/` |
| Product feature spec / UX brief (*what* + *why*) | `docs/features/` |
| Cross-cutting tech reference, tech plans, module-author guide | `docs/technical/` |
| Module-specific deep-dive | `docs/modules/<name>.md` |
| Architectural decision (rule + rationale) | `docs/adr/NNNN-title.md` |
| Agent / dev checklist | `docs/checklists/` |
| Diagram source (Mermaid / PlantUML) | `docs/diagrams/` |
| Image asset (PNG / SVG) | `docs/screenshots/` |
| Operational runbook / end-to-end workflow | `docs/workflows/` |
| What an App is for + its changelog | `docs/apps/<app>/` (`README.md`, `CHANGELOG.md`) |
| Auto-generated catalog | `docs/` root, suffix `-catalog.md` |

**Only these files live at `docs/` root:** `README.md` (taxonomy index), `glossary.md`, `events-catalog.md`, `modules-catalog.md`, `subprocessors-catalog.md`, `apps-catalog.md`. Anything else fails CI.

Decision tree + folder descriptions: [`docs/README.md`](./docs/README.md).

---

## Quick start

```bash
docker-compose up
docker-compose exec backend python -m pytest -v
cd backend && ruff check . && ruff format --check .
cd frontend && npm run lint

# Reset DB + reseed demo data (destructive — wipes the dev database)
./scripts/reset-db.sh        # drop, alembic upgrade heads
./scripts/seed-demo.sh       # demo clinic, users, sample data

# Demo login
# admin@demo.clinic / demo1234
```

---

## RBAC

Source of truth: `backend/app/core/auth/permissions.py`.

Roles get **core** grants from `ROLE_PERMISSIONS` plus **module** grants
merged at runtime from each module's `manifest.role_permissions` (prefixed
with the module name) via `get_role_permissions()`. The core table is
deliberately small — clinical/module permissions live in the modules:

```python
ROLE_PERMISSIONS: Final[dict[str, list[str]]] = {
    "admin": ["*"],                                # wildcard — every namespace
    "dentist": ["agents.view", "agents.supervise"],
    "hygienist": [],
    "assistant": [],
    "receptionist": [],
}
# A module manifest contributes, e.g.:
#   role_permissions = {"receptionist": ["patients.read", "patients.write"]}
# → merged in as "patients.read" / "patients.write" for receptionist.
```

Wildcards: `*` = all; `module.*` = all in that module. Matching strips the
trailing `.*` to a dotted prefix, so `billing.*` matches `billing.x.y` but
not `billing_x.y`.

**Backend — protect endpoints:** (permission strings are module-prefixed)
```python
from app.core.auth.dependencies import get_clinic_context, require_permission

@router.get("/patients")
async def list_patients(
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: Annotated[None, Depends(require_permission("patients.read"))],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    ...
```

**Frontend — single source of truth:** `frontend/app/config/permissions.ts`. Always reference `PERMISSIONS.resource.action`, never hardcode strings.

```typescript
import { PERMISSIONS } from '~/config/permissions'
const { can, canAny, isAdmin } = usePermissions()
if (can(PERMISSIONS.patients.write)) { /* ... */ }
```

```vue
<UButton
  v-if="can(PERMISSIONS.patients.write)"
  icon="i-lucide-plus"
  @click="..."
>
  {{ t('patients.create') }}
</UButton>
```

Adding a permission: return it from the module's `get_permissions()` (unprefixed) → grant it to roles in the module's `manifest.role_permissions` → `require_permission("module.resource.action")` on the endpoint → add to `config/permissions.ts` → use via `usePermissions().can(PERMISSIONS.x.y)`. (Core-level permissions like `admin.*`/`agents.*` are the exception — those live in `ROLE_PERMISSIONS`/`CORE_PERMISSIONS`.)

---

## Frontend patterns

Composables:

| Composable | Purpose |
|------------|---------|
| `useAuth` | `user`, `permissions`, `login()`, `logout()` |
| `usePermissions` | `can()`, `canAny()`, `isAdmin` |
| `useApi` | HTTP client with auth + token refresh |
| `useClinic` | `currentClinic`, `cabinets` |
| `useModules` | Navigation (filtered by permissions) |
| `useUsers` | User management (admin) |

State via `useState` (SSR-compatible):
```typescript
const user = useState<User | null>('auth:user', () => null)
```

API calls:
```typescript
import type { ApiResponse, PaginatedResponse, Patient } from '~/types'
const api = useApi()

const list = await api.get<PaginatedResponse<Patient>>('/api/v1/patients')        // .data is Patient[]
const one  = await api.get<ApiResponse<Patient>>('/api/v1/patients/123')          // .data is Patient
const made = await api.post<ApiResponse<Patient>>('/api/v1/patients', { ... })    // .data is Patient
```

UI: Nuxt UI (`UButton`, `UInput`, `UCard`, `UModal`, `USelect`, `UFormField`, `UBadge`, `UAvatar`, `USkeleton`).

TS aliases: **both point at the host, never at the layer.** `~` = host app root (`frontend/app`), `~~` = host frontend root (`frontend`) — use it for shared types: `import type { Patient } from '~~/app/types'`.

A module's own files are reached with a **relative path**, not `~/`. This line used to read "`~` = layer root", and following it produced
`import … from '~/components/treatment-plans/planDraftLineUtils'`, which
resolves against `frontend/app/components/` — where a module's components
are not — and fails to compile. `~/config/permissions` works from a module
only because it lands on the host's own `frontend/app/config/permissions.ts`.

---

## Backend patterns

### Endpoint shape

```python
from app.core.schemas import ApiResponse, PaginatedApiResponse

@router.get("/resources", response_model=PaginatedApiResponse[ResourceResponse])
async def list_resources(
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: Annotated[None, Depends(require_permission("module.resource.read"))],
    db: Annotated[AsyncSession, Depends(get_db)],
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
) -> PaginatedApiResponse[ResourceResponse]:
    items, total = await ResourceService.list(db, ctx.clinic_id, page, page_size)
    return PaginatedApiResponse(
        data=[ResourceResponse.model_validate(i) for i in items],
        total=total, page=page, page_size=page_size,
    )

@router.post("/resources", response_model=ApiResponse[ResourceResponse], status_code=201)
async def create_resource(
    data: ResourceCreate,
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: Annotated[None, Depends(require_permission("module.resource.write"))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ApiResponse[ResourceResponse]:
    resource = await ResourceService.create(db, ctx.clinic_id, data.model_dump())
    return ApiResponse(data=ResourceResponse.model_validate(resource))
```

### Service layer

Business logic only, no HTTP concerns. Static methods on a `ResourceService` class. Routers stay thin.

### Transactions

An endpoint's writes are committed as it returns, **before** the response is sent, by the app-wide `commit_before_response` dependency ([ADR 0031](./docs/adr/0031-writes-commit-before-the-response.md)). Do not add a per-endpoint `db.commit()` for that. `get_db`'s own commit runs after the response, so it only catches work done while a response streams.

### More than one process

A deployment may run several backends against one database
([ADR 0051](./docs/adr/0051-a-backend-process-is-one-of-several.md)). Write
as if yours is one of them:

- A module-level variable is a cache or a registry rebuilt at boot, never
  the only copy of a decision. What another process must honour goes in the
  database, and the others read it (`module_gate` is the example).
- Periodic work is declared in `get_scheduled_jobs()`, never with
  `scheduler.add_job`: only the process with `SCHEDULER_ENABLED` runs it.
- A startup step that writes goes inside `advisory_lock(BOOT_LOCK)` in the
  lifespan (`app/core/advisory_locks.py`).

`replicas/docker-compose.yml` is the bench to try a change against two of
each; [`docs/technical/running-replicas.md`](./docs/technical/running-replicas.md)
says how.

### Multi-tenancy (mandatory)

Every query MUST filter by `clinic_id`:

```python
# CORRECT
select(Patient).where(Patient.clinic_id == ctx.clinic_id)

# WRONG — security vulnerability
select(Patient).where(Patient.id == patient_id)
```

The same rule applies inside agent tool handlers.

---

## Database conventions

```python
class MyModel(Base):
    __tablename__ = "my_models"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    clinic_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("clinics.id"), nullable=False, index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
```

- UUID primary keys, TIMESTAMPTZ timestamps, JSONB for flexible fields.
- Soft delete via `status` (never hard-delete patient data).
- Index `clinic_id` on every multi-tenant table.

Migrations live in `backend/app/modules/<name>/migrations/versions/` on a per-module branch. See `docs/technical/creating-modules.md` §3 (`migrations/`) for the branching rules and the `--branch-label` invocation.

```bash
docker-compose exec backend alembic upgrade heads     # plural — multiple branches
```

`heads` is the manual, "give me the whole schema" command. **Boot does not
use it**: `docker-entrypoint.sh` upgrades the core linear chain only, and
per-module branches are applied by the lifespan processor for the modules
`core_module.state` marks `installed`. Running `heads` by hand on a database
where a module was uninstalled re-creates that module's tables.

---

## API conventions

Wrappers from `backend/app/core/schemas.py`:

| Case | Schema |
|------|--------|
| Single item | `ApiResponse[T]` |
| Paginated list | `PaginatedApiResponse[T]` |
| Error | `ErrorResponse` |

**Exception:** auth token endpoints (`/login`, `/register`, `/refresh`) return raw tokens, not wrapped.

Status codes: `200` GET/PUT, `201` POST, `204` DELETE, `400` bad request, `401` unauth, `403` forbidden, `404` not found, `409` conflict, `422` validation.

---

## Module quick reference

Full guide: `docs/technical/creating-modules.md`. Skeleton:

```python
class MyModule(BaseModule):
    manifest = {
        "name": "mymodule",
        "version": "0.1.0",
        "category": "official",        # or "community"
        "depends": ["patients"],       # declared dependencies — enforced
        "installable": True,
        "auto_install": False,
        "removable": True,
        "role_permissions": {"admin": ["*"]},
    }

    def get_models(self) -> list: return [MyModel]
    def get_router(self) -> APIRouter: return router
    def get_permissions(self) -> list[str]: return ["resource.read", "resource.write"]
    def get_event_handlers(self) -> dict: return {"patient.created": self._on_patient_created}
    def get_tools(self) -> list[Tool]: return []   # mandatory, even if empty
```

Event bus — **publish after the commit, never from inside the transaction**
([ADR 0019](./docs/adr/0019-events-publish-after-commit.md)). Handlers run in
their own sessions, so anything announced after a mere `flush()` is invisible
to them:

```python
from app.core.events import event_bus

# Queues on the session; UnitOfWorkSession dispatches it once the
# transaction commits (and drops it on rollback). Not a coroutine.
event_bus.publish_after_commit(db, "patient.created", {"patient_id": str(patient.id)})
```

`await event_bus.publish(...)` is only for callers that have already committed
(background workers owning their session). `tests/test_event_transaction_boundary.py`
holds the allowlist and fails on any new direct publish.

A handler that raises does not abort the dispatch, but it is no longer
invisible: the bus records it in `core_event_failure` (event, handler, payload,
error) and admins read it at `GET /api/v1/events/failures`
([ADR 0020](./docs/adr/0020-handler-failures-are-recorded.md)). There is no
automatic retry — handlers are not uniformly idempotent.

---

## Testing

```bash
docker-compose exec backend python -m pytest -v
docker-compose exec backend python -m pytest tests/test_auth.py -v
docker-compose exec backend python -m pytest --cov=app
```

**The suite runs against its own database.** Every test does
`create_all`/`drop_all`, so `conftest.py` resolves a dedicated `*_test`
database (`dental_clinic` → `dental_clinic_test`), creates it on first run,
and prints the target at session start. `DATABASE_URL` is redirected, never
used as-is — a run cannot touch the dev database or its demo login. CI
already sets `DATABASE_URL` to `dental_clinic_test`, which is used verbatim.
Override with `TEST_DATABASE_URL`; the name must end in `_test`.

An interrupted run leaves its tables behind (`create_all` skips existing
ones), so the session start drops and recreates the `public` schema.

The backend image is multi-stage: `docker-compose.yml` builds the `dev`
target (adds the `[dev]` extra — pytest, ruff), while deploys build `prod`,
the last stage, which has neither. Keep `prod` last in the Dockerfile.

Isolation has **two halves**: overriding `get_db` covers request-scoped
sessions, and `conftest.py` also rebinds the global `engine` /
`async_session_maker`, because event handlers and background tasks
(`patient_timeline`, `payments`, `recalls`, `copilot`, `treatment_plan`,
`migration_import`, ...) open their own sessions and bypass the override.
`tests/test_db_isolation.py` pins both halves.

Fixtures from `conftest.py`: `db_session`, `client`, `auth_headers`.

```python
@pytest.mark.asyncio
async def test_create_patient(client: AsyncClient, auth_headers: dict):
    response = await client.post(
        "/api/v1/patients",
        json={"first_name": "John", "last_name": "Doe"},
        headers=auth_headers,
    )
    assert response.status_code == 201
```

For modules with `removable=True`, also cover the round-trip uninstall (see `docs/technical/creating-modules.md` §9).

---

## Environment

```bash
DATABASE_URL=postgresql+asyncpg://dental:dental_dev@db:5432/dental_clinic
SECRET_KEY=your-secret-key-min-32-chars
ENVIRONMENT=development   # development | test | production
TESTING=false
```

---

## Troubleshooting

- **"relation does not exist"** (missing/half-migrated schema): `./scripts/reset-db.sh` then `./scripts/seed-demo.sh` — destructive, it drops every table, so confirm before running it on a database you care about. Manual fallback: `DELETE FROM alembic_version;` then `alembic upgrade heads`.
- **Frontend changes not showing**: `docker-compose up -d --build frontend`.
- **Permission denied but should have access**: check `clinic_memberships` row, exact permission string, `/me` payload, then re-login.

---

## Code style

- Code in English; UI strings in Spanish (i18n).
- Python: type hints required, ruff for lint/format.
- TypeScript: strict mode, ESLint.
- Commits: Conventional Commits (`feat:`, `fix:`, `docs:`).
- No over-engineering. No tech debt. Refactor when it pays off, not preemptively.

---


## 1. Think Before Coding
Don't assume. Don't hide confusion. Surface tradeoffs.

Before implementing:
- State your assumptions explicitly. If uncertain, ask.
- If multiple interpretations exist, present them.
- If a simpler approach exists, say so.
- If something is unclear, stop. Name what's confusing.

## 2. Simplicity First
Minimum code that solves the problem. Nothing speculative.

- No features beyond what was asked.
- No abstractions for single-use code.
- No “flexibility” that wasn't requested.
- No error handling for impossible scenarios.
- If 200 lines could be 50, rewrite it.

## 3. Surgical Changes
Touch only what you must. Clean up only your own mess.

- Don't “improve” adjacent code or formatting.
- Don't refactor things that aren't broken.
- Match existing style, even if you'd do it differently.
- If you notice dead code, mention it — don't delete it.

## 4. Goal-Driven Execution
Define success criteria. Loop until verified.

Transform tasks into verifiable goals:
- “Add validation” → “Write tests, then make them pass”
- “Fix the bug” → “Reproduce it in a test, then fix”
- “Refactor X” → “Ensure tests pass before and after”
