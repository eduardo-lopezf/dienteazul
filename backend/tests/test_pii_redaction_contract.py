"""The PHI boundary is a contract, not a convention.

CLAUDE.md tells module authors to name PII fields with redactor-known
keys. An instruction an author can forget is not a boundary, and this one
was forgotten repeatedly: ``billing_tax_id`` was never redacted, and
``LegalGuardian.dni`` fell out of coverage during a jurisdiction
refactor. Both were columns that plainly held a person's identifier.

So the rule is enforced here, in the same shape as
``test_event_transaction_boundary.py``: a pattern finds the columns that
look personal, and every one of them must either carry a ``pii()``
classification or sit in an allowlist that a human had to edit on
purpose.
"""

from __future__ import annotations

import importlib
import re
from pathlib import Path
from types import ModuleType

import pytest

import app
from app.core.agents.redaction import _SYNTHETIC_KEYS, ALL_JURISDICTIONS, Redactor
from app.core.privacy import PiiKind, PiiTag, classified_columns, pii_columns
from app.database import Base

# Column names that look like they hold personal data. Deliberately
# broad — a false positive costs one allowlist line and a moment's
# thought, a false negative ships PII to a cloud model in cleartext.
_LOOKS_PERSONAL = re.compile(
    r"(^|_)(name|phone|mobile|telephone|email|dni|nif|nie|cif|curp|rfc|ine|national_id|tax_id)(_|$)",
    re.IGNORECASE,
)

# Columns that match the pattern and are **not** personal data. Each entry
# is a decision: adding one means someone looked at the column and
# concluded no person is identified by it.
_NOT_PERSONAL: frozenset[tuple[str, str]] = frozenset(
    {
        # Catalog entries — a substance, a condition, a room, a template.
        # The name of a thing, not of a person.
        ("patients_clinical_allergy", "name"),
        ("patients_clinical_medication", "name"),
        ("patients_clinical_systemic_disease", "name"),
        ("cabinets", "name"),
        ("whatsapp_kapso_templates", "name"),
        # The shape of a plan ("primera visita", "implante unitario"),
        # authored by the clinic and reused across patients. Tokenizing it
        # would redact a workflow label as if it named someone.
        ("plan_templates", "name"),
        ("notification_templates", "provider_template_name"),
        # Machinery: module registry, tool calls, agent and adapter names.
        ("agents", "name"),
        ("agent_approval_queue", "tool_name"),
        ("agent_audit_logs", "tool_name"),
        ("core_module", "name"),
        ("core_module_operation_log", "module_name"),
        ("core_external_id", "module_name"),
        ("core_external_id", "table_name"),
        # The import ledger names a table and a row id, never a person.
        ("migration_import_created_rows", "table_name"),
        ("clinic_channel_settings", "adapter_name"),
        # ``national_id_type`` is the *kind* of document (curp / ine /
        # passport), never the number itself.
        ("patients", "national_id_type"),
        # Meta's opaque handle for a WhatsApp sender. Not a phone number
        # despite the name; the number itself is ``display_phone_number``
        # and is classified.
        ("whatsapp_kapso_settings", "phone_number_id"),
        # A boolean. Matches only because the pattern sees ``email_``.
        ("notification_preferences", "email_enabled"),
    }
)


def _model_tables() -> dict[str, object]:
    """Every table that belongs to a declared model, keyed by name.

    Two things this must not depend on:

    * **Import order.** ``Base.metadata`` only holds the models something
      imported, so a module whose ``models.py`` no test touched would be
      invisible here and its columns would pass unchecked. Every
      ``models.py`` under ``app/`` is imported first.
    * **Tables other tests inject.** ``test_module_yaml_loader`` registers
      a synthetic ``seed_demo_items`` table directly on the shared
      metadata; it belongs to no model, so it is filtered out by keying
      on the ``__tablename__`` values the model classes declare.
    """
    declared: set[str] = set()
    for module in _import_all_model_modules():
        for obj in vars(module).values():
            table_name = getattr(obj, "__tablename__", None)
            if isinstance(table_name, str):
                declared.add(table_name)
    return {name: t for name, t in Base.metadata.tables.items() if name in declared}


# Files that declare tables. Not just ``models.py`` — core's plugin
# registry keeps its own in ``db_models.py``, and missing it would let
# those tables through unchecked.
_MODEL_FILES = ("models.py", "db_models.py")


def _import_all_model_modules() -> list[ModuleType]:
    app_dir = Path(app.__file__).parent
    modules = []
    for pattern in _MODEL_FILES:
        for path in sorted(app_dir.rglob(pattern)):
            dotted = ".".join(("app", *path.relative_to(app_dir).with_suffix("").parts))
            modules.append(importlib.import_module(dotted))
    return modules


# A table is *declared* by assigning ``__tablename__``. Merely reading the
# attribute — ``getattr(model, "__tablename__")`` in the plugin
# processor, ``row.__tablename__`` in an export — is not a declaration,
# and matching on the bare name made every such reader a false positive.
_DECLARES_TABLE = re.compile(r"^\s*__tablename__\s*(:[^=]+)?=", re.MULTILINE)


def test_every_table_declaring_file_is_covered() -> None:
    """The importer must reach every file that declares a table.

    A new one (say ``core/billing/tables.py``) would otherwise leave its
    columns invisible to the whole contract, silently.
    """
    app_dir = Path(app.__file__).parent
    declaring = {
        path.name
        for path in app_dir.rglob("*.py")
        if _DECLARES_TABLE.search(path.read_text(encoding="utf-8"))
    }
    missed = declaring - set(_MODEL_FILES)
    assert not missed, f"files declare tables but are not imported by this test: {missed}"


def test_the_declaration_pattern_still_matches_models() -> None:
    # A pattern that matched nothing would make the guard above vacuous.
    app_dir = Path(app.__file__).parent
    models = (app_dir / "modules" / "patients" / "models.py").read_text(encoding="utf-8")
    assert _DECLARES_TABLE.search(models)


def _personal_looking_columns() -> list[tuple[str, str]]:
    return [
        (table_name, column.key)
        for table_name, table in sorted(_model_tables().items())
        for column in table.columns  # type: ignore[attr-defined]
        if _LOOKS_PERSONAL.search(f"_{column.key}_")
    ]


class TestEveryPersonalColumnIsClassified:
    def test_no_unclassified_personal_columns(self) -> None:
        classified = set(classified_columns())
        missing = [
            (table, column)
            for table, column in _personal_looking_columns()
            if (table, column) not in classified and (table, column) not in _NOT_PERSONAL
        ]
        assert not missing, (
            "These columns look personal but carry no pii() classification, so the "
            "redactor will not tokenize them on the way to a cloud model. Classify "
            "them in the model, or add them to _NOT_PERSONAL with a reason: "
            f"{missing}"
        )

    def test_allowlist_has_no_stale_entries(self) -> None:
        # An entry that no longer matches (renamed, dropped, or since
        # classified) is a decision nobody is making any more.
        live = set(_personal_looking_columns())
        classified = set(classified_columns())
        stale = [entry for entry in _NOT_PERSONAL if entry not in live or entry in classified]
        assert not stale, f"_NOT_PERSONAL entries no longer apply: {stale}"

    def test_the_pattern_actually_matches_something(self) -> None:
        # Guards against a regex edit that quietly disables the check.
        assert len(_personal_looking_columns()) > 20


class TestRedactorCoversTheClassification:
    def test_every_classified_column_is_redacted(self) -> None:
        redactor = Redactor(enabled=True)
        uncovered = {
            column: kind.value
            for column, kind in pii_columns().items()
            if redactor._kind_for_key.get(column) is None
        }
        assert not uncovered, f"classified but not in the redactor's key map: {uncovered}"

    def test_kinds_match_the_classification(self) -> None:
        redactor = Redactor(enabled=True)
        mismatched = {
            column: (kind.value, redactor._kind_for_key.get(column))
            for column, kind in pii_columns().items()
            if redactor._kind_for_key.get(column) != kind.value
        }
        assert not mismatched, f"column classified as one kind, redacted as another: {mismatched}"

    @pytest.mark.parametrize("jurisdictions", [frozenset({"MX"}), frozenset({"ES"}), None])
    def test_coverage_holds_under_every_jurisdiction(self, jurisdictions) -> None:
        # Jurisdiction selects *document names*; it must never be able to
        # switch off a column the schema itself classified.
        redactor = Redactor(enabled=True, jurisdictions=jurisdictions)
        for column in pii_columns():
            assert redactor._kind_for_key.get(column) is not None, (column, jurisdictions)

    def test_synthetic_keys_are_not_silently_shadowed(self) -> None:
        # A synthetic key exists because no column carries it. If a column
        # later takes that name with a different kind, the schema wins and
        # the synthetic entry becomes a lie — catch that here.
        columns = pii_columns()
        conflicts = {
            key: (kind, columns[key].value)
            for key, kind in _SYNTHETIC_KEYS.items()
            if key in columns and columns[key].value != kind
        }
        assert not conflicts, (
            f"synthetic key disagrees with the column of the same name: {conflicts}"
        )


class TestClassificationShape:
    def test_tags_are_well_formed(self) -> None:
        for (table, column), tag in classified_columns().items():
            assert isinstance(tag, PiiTag), (table, column)
            assert isinstance(tag.kind, PiiKind), (table, column)

    def test_known_offenders_stay_covered(self) -> None:
        # The two columns this contract exists because of.
        columns = pii_columns()
        assert columns.get("billing_tax_id") is PiiKind.NATIONAL_ID
        assert ("patients_clinical_legal_guardian", "dni") in classified_columns()

    def test_all_jurisdictions_is_the_fallback(self) -> None:
        assert Redactor(enabled=True).jurisdictions == ALL_JURISDICTIONS
