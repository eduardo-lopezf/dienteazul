# Architecture Decision Records

Why we record decisions here:

- The repo grows; the *why* behind a constraint stops being obvious.
- AI agents and new contributors need durable, searchable context for
  rules they will otherwise question or accidentally undo.
- `git log` carries the *what*. ADRs carry the *why* + the *trade-offs
  considered* + the *consequences* if you break the rule.

## Convention

- Filename: `NNNN-kebab-title.md` — zero-padded sequence, never reused.
- One decision per file. Short. ≤1 page when possible.
- Every ADR uses the same structure: see `TEMPLATE.md`.
- Status: `proposed` → `accepted` → optionally `superseded by NNNN` /
  `deprecated`. Never delete an ADR; supersede it.
- Date: the date status changed (ISO `YYYY-MM-DD`).
- Cite source files (`path:line`) and tests so the rule is verifiable.

## ADR vs `features/` / `technical/`

- `docs/adr/` — historical decisions that shape today's code. Read to
  understand why a rule exists.
- `docs/features/` — forward-looking product / UX briefs. *What* and
  *why* of a feature being shaped.
- `docs/technical/` — implementation plans and cross-cutting tech
  reference. *How* a feature is being built.

A design brief or tech plan may graduate to an ADR once the decision
is locked in and worth defending against future drift.

## When to write a new ADR

Triggers (any one):

- A rule has been broken once and we want to make sure it isn't again.
- A reviewer asked "why is it this way?" and the answer isn't in code.
- We chose between two reasonable approaches and the loser will keep
  resurfacing.
- A constraint is imposed by an external system (regulator, vendor,
  licensor) and we need to capture it once.

## Index

| #    | Title | Status | Date |
|------|-------|--------|------|
| 0001 | [Modular plugin architecture](0001-modular-plugin-architecture.md) | accepted | 2026-04-27 |
| 0002 | [Per-module Alembic branches](0002-per-module-alembic-branches.md) | accepted | 2026-04-27 |
| 0003 | [Event bus over direct cross-module imports](0003-event-bus-over-direct-imports.md) | accepted | 2026-04-27 |
| 0004 | [BSL 1.1 license, Apache 2.0 after 4 years](0004-bsl-license.md) | accepted (amended) | 2026-04-27 |
| 0005 | [Relative permissions, registry-prefixed namespacing](0005-relative-permissions.md) | accepted | 2026-04-27 |
| 0006 | [Budget public link two-factor authentication](0006-budget-public-link-2-factor-auth.md) | accepted | 2026-04-28 |
| 0007 | [Polymorphic attachment owner registry in `media`](0007-polymorphic-attachment-registry.md) | accepted | 2026-05-02 |
| 0008 | [Photo storage retention is documented but not enforced (yet)](0008-photo-storage-retention-stub.md) | accepted | 2026-05-02 |
| 0009 | [Documentation portal: VitePress, filesystem-as-contract, in-app help](0009-documentation-portal.md) | accepted | 2026-05-02 |
| 0010 | [Payments as a primitive module; billing depends on payments](0010-payments-as-primitive-module.md) | accepted | 2026-05-13 |
| 0011 | [Detail-page shared components](0011-detail-page-shared-components.md) | accepted | 2026-05-13 |
| 0012 | [Multi-tenancy en Diente Azul core — brief](0012-multi-tenancy-brief.md) | proposed | 2026-05-17 |
| 0013 | [Periodontogram snapshots are immutable dated rows, not an event stream](0013-periodontogram-snapshot-model.md) | accepted | 2026-05-26 |
| 0014 | [Copilot proactivity v1: deterministic morning digest email](0014-copilot-proactivity.md) | accepted | 2026-06-11 |
| 0015 | [Aggregate the copilot "Pendientes" feed through the tool registry](0015-copilot-pending-aggregation.md) | accepted | 2026-06-15 |
| 0016 | [Channel-adapter architecture for the notifications gateway](0016-channel-adapter-architecture.md) | accepted | 2026-06-26 |
| 0017 | [Inbound replies + conversation thread in communication_messages](0017-inbound-conversation.md) | accepted | 2026-06-26 |
| 0018 | [Install state is the authority on what runs](0018-install-state-is-the-mount-authority.md) | accepted | 2026-08-26 |
| 0019 | [Events are published after the transaction commits](0019-events-publish-after-commit.md) | accepted | 2026-08-26 |
| 0020 | [Handler failures are recorded, not just logged](0020-handler-failures-are-recorded.md) | accepted | 2026-08-26 |
| 0021 | [Module layers are typechecked, behind a shrinking baseline](0021-module-layers-are-typechecked.md) | accepted | 2026-08-26 |
| 0022 | [Touch adaptation is capability-driven, not width- or UA-driven](0022-touch-adaptation-is-capability-driven.md) | accepted | 2026-08-27 |
| 0023 | [Custody is a tenant property, declared in three modes](0023-privacy-policy-and-custody-modes.md) | accepted (amended) | 2026-08-28 |
| 0024 | [The control plane holds what constrains the customer](0024-control-plane-holds-what-constrains-the-customer.md) | accepted | 2026-08-28 |
| 0025 | [PII is classified on the column, and the classification is enforced](0025-pii-is-classified-on-the-column.md) | accepted | 2026-08-28 |
| 0026 | [Subject rights are a module contract, and erasure must be justified](0026-subject-rights-are-a-module-contract.md) | accepted | 2026-08-29 |
| 0027 | [Egress is declared in the manifest, and reported before it is blocked](0027-egress-is-declared-in-the-manifest.md) | accepted | 2026-08-29 |
| 0028 | [Self-hosting is the premium tier, activated by a signed key](0028-self-hosting-is-the-premium-tier.md) | accepted | 2026-08-31 |
| 0029 | [Security is a set of invariants with chokepoints, not a list of practices](0029-security-invariants-with-chokepoints.md) | proposed | 2026-09-01 |
| 0030 | [A session ends after an hour without interaction, and login resumes it](0030-sessions-end-after-an-hour-idle.md) | accepted | 2026-09-16 |
| 0031 | [A request's writes are committed before its response is sent](0031-writes-commit-before-the-response.md) | accepted | 2026-09-22 |
| 0032 | [The clinical record is append-only, and every entry names a licensed author](0032-clinical-record-is-append-only.md) | proposed | 2026-09-22 |
| 0033 | [Disclosure requires a recorded authorisation, and the authorisation is part of the record](0033-disclosure-requires-a-recorded-authorisation.md) | accepted | 2026-09-22 |
| 0035 | [Apps are disabled, not uninstalled, and every database carries the whole schema](0035-apps-are-disabled-not-uninstalled.md) | accepted | 2026-09-30 |
| 0036 | [An App is a declared group of modules](0036-an-app-is-a-declared-group-of-modules.md) | accepted | 2026-09-30 |
| 0037 | [A module integrates with what it can live without](0037-a-module-integrates-with-what-it-can-live-without.md) | accepted | 2026-10-01 |
| 0038 | [`apps.json` switches Apps for the whole deployment](0038-apps-json-switches-apps-for-the-whole-deployment.md) | accepted | 2026-10-01 |
| 0039 | [A module reaches another's data through a core contract, not an import](0039-modules-reach-each-other-through-core-contracts.md) | accepted | 2026-10-01 |
| 0040 | [Widgets are read from the slot registry; APIs are declared in `apps.json`](0040-widgets-are-read-from-the-registry-apis-are-declared-in-apps-json.md) | accepted | 2026-10-02 |
| 0041 | [A screen hosts other Apps through slots, never by naming them](0041-a-screen-hosts-other-apps-through-slots.md) | accepted | 2026-10-02 |
| 0042 | [Core Apps must stay separable from the backend process](0042-core-apps-must-stay-separable.md) | accepted | 2026-10-02 |
| 0043 | [The workspace is the base App, and every App has a tier](0043-the-workspace-is-the-base-app.md) | accepted | 2026-10-03 |
| 0044 | [The App organises; the module holds the code](0044-the-app-organises-the-module-holds-the-code.md) | accepted | 2026-10-03 |
| 0045 | [A consent is a record entry, written from the clinic's own text](0045-a-consent-is-a-record-entry.md) | accepted | 2026-10-03 |
| 0046 | [Letterheads belong to the clinic, and a document carries its own professional's](0046-the-letterhead-belongs-to-the-clinic.md) | accepted | 2026-10-04 |
| 0047 | [A specialty is a reference pack the clinic enables, edits and can restore](0047-a-specialty-is-a-reference-pack.md) | accepted | 2026-10-04 |
| 0048 | [The reference catalogue is data: one file per specialty, every treatment explicit](0048-the-reference-catalogue-is-data.md) | accepted | 2026-10-04 |
| 0049 | [The control plane is a separate service, and a tenant is a stack](0049-the-control-plane-is-a-separate-service.md) | accepted | 2026-10-05 |
| 0050 | [A deployed image is pinned, carries only what runs, and is audited](0050-a-deployed-image-is-pinned-stripped-and-audited.md) | accepted | 2026-10-06 |
| 0051 | [A backend process is one of several](0051-a-backend-process-is-one-of-several.md) | accepted | 2026-10-07 |
| 0053 | [An App can declare the Apps it goes off with](0053-an-app-can-declare-the-apps-it-goes-off-with.md) | accepted | 2026-10-12 |
