"""Egress declared in the manifest, and audited against the policy.

`PrivacyPolicy.egress_allowed` was default-deny with nothing to compare
against: the policy could permit OpenAI while nothing said which modules
reach anything at all. These pin the declaration, the audit that reads
it, and — the part that keeps it honest — that a module making outbound
calls cannot stay silent about them.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path

import pytest

from app.core.plugins.loader import discover_and_register
from app.core.plugins.manifest import Manifest, ManifestError
from app.core.plugins.registry import module_registry
from app.core.privacy import DataClass, PrivacyPolicy
from app.core.privacy.egress import EgressDeclaration, EgressError, audit_egress, log_egress_audit


def _manifest(**egress) -> Manifest:
    return Manifest.from_dict({"name": "m", "version": "1", "egress": [egress]})


class TestDeclarationShape:
    def test_parses_a_full_entry(self) -> None:
        manifest = _manifest(
            target="openai",
            subprocessor="OpenAI, L.L.C.",
            purpose="Respuestas del copiloto.",
            data_classes=["clinical"],
            residency="us",
            required=False,
        )
        entry = manifest.egress[0]
        assert entry.target == "openai"
        assert entry.data_classes == {DataClass.CLINICAL}
        assert entry.required is False
        assert entry.carries_personal_data

    def test_target_must_be_an_id(self) -> None:
        # It is matched against TENANT_EGRESS_ALLOWED, so it has to be
        # something an operator can type without guessing at casing.
        with pytest.raises(ManifestError, match="lower-case id"):
            _manifest(target="Open AI", subprocessor="X", purpose="y")

    @pytest.mark.parametrize("missing", ["target", "subprocessor", "purpose"])
    def test_the_three_required_fields(self, missing: str) -> None:
        entry = {"target": "t", "subprocessor": "S", "purpose": "p"}
        del entry[missing]
        with pytest.raises(ManifestError, match="is missing"):
            _manifest(**entry)

    def test_unknown_data_class_is_refused(self) -> None:
        with pytest.raises(ManifestError, match="Unknown data_class"):
            _manifest(target="t", subprocessor="S", purpose="p", data_classes=["secret"])

    def test_no_data_classes_means_nothing_personal_leaves(self) -> None:
        entry = _manifest(target="t", subprocessor="S", purpose="p").egress[0]
        assert not entry.carries_personal_data

    def test_egress_must_be_a_list(self) -> None:
        with pytest.raises(ManifestError, match="egress must be a list"):
            Manifest.from_dict({"name": "m", "version": "1", "egress": {"target": "t"}})

    def test_absent_egress_means_nothing_leaves(self) -> None:
        assert Manifest.from_dict({"name": "m", "version": "1"}).egress == ()

    def test_survives_the_snapshot_round_trip(self) -> None:
        # The snapshot is what gets persisted into core_module.
        original = _manifest(
            target="kapso", subprocessor="Kapso", purpose="p", data_classes=["identifier"]
        )
        snapshot = original.to_snapshot()
        assert snapshot["egress"] == [
            {
                "target": "kapso",
                "subprocessor": "Kapso",
                "purpose": "p",
                "data_classes": ["identifier"],
                "residency": "unspecified",
                "required": True,
            }
        ]
        assert Manifest.from_dict(snapshot).egress == original.egress


class TestAudit:
    @pytest.fixture(autouse=True)
    def _modules(self) -> None:
        discover_and_register()
        for module in module_registry.list_discovered():
            module_registry.activate(module.name)

    def _policy(self, *allowed: str) -> PrivacyPolicy:
        return PrivacyPolicy.managed(
            jurisdictions=frozenset({"MX"}),
            regulations=frozenset({"lfpdppp"}),
            data_residency="mx-central",
            egress_allowed=frozenset(allowed),
        )

    def test_default_deny_reports_every_destination(self) -> None:
        findings = audit_egress(self._policy())
        targets = {f.declaration.target for f in findings}
        assert {"openai", "kapso", "aeat", "smtp"} <= targets

    def test_a_permitted_destination_disappears(self) -> None:
        findings = audit_egress(self._policy("openai"))
        assert "openai" not in {f.declaration.target for f in findings}

    def test_nothing_to_report_when_all_declared(self) -> None:
        assert audit_egress(self._policy("openai", "kapso", "aeat", "smtp", "facturama")) == []

    def test_findings_carrying_personal_data_are_flagged_as_leaks(self) -> None:
        # A boot log full of equal-looking lines hides the one that
        # matters, so the severity distinguishes a licence check from a
        # disclosure the clinic never agreed to.
        findings = audit_egress(self._policy())
        assert all(f.severity == "leak" for f in findings)

    def test_boot_says_it_out_loud(self, caplog: pytest.LogCaptureFixture) -> None:
        with caplog.at_level(logging.WARNING, logger="app.core.privacy.egress"):
            log_egress_audit(self._policy())
        assert "openai" in caplog.text
        assert "does not permit" in caplog.text

    def test_boot_is_quiet_when_everything_is_declared(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        with caplog.at_level(logging.WARNING, logger="app.core.privacy.egress"):
            log_egress_audit(self._policy("openai", "kapso", "aeat", "smtp", "facturama"))
        assert "does not permit" not in caplog.text


class TestRealModulesDeclare:
    """A module that calls out must say so.

    The signal is an **HTTP or SMTP client import** in the module's own
    source, not a URL: a first pass grepping for ``https?://`` flagged a
    placeholder string in ``billing/hooks.py`` and a spec link in a
    ``migration_import`` docstring. A URL is text; a client is a call.
    """

    # Modules whose outbound call lives in core rather than in their own
    # source. ``copilot`` reaches OpenAI through ``app/core/llm/`` and
    # ``notifications`` sends mail through ``app/core/email/`` — both
    # still declare the egress, because the declaration is about where
    # the data goes, not about which file dials.
    _CALLS_THROUGH_CORE = {"copilot", "notifications"}

    _CLIENTS = re.compile(
        r"^\s*(?:import|from)\s+(httpx|aiohttp|requests|urllib\.request|smtplib|aiosmtplib|zeep)\b",
        re.MULTILINE,
    )

    def test_modules_making_outbound_calls_declare_egress(self) -> None:
        import app.modules as modules_pkg

        root = Path(modules_pkg.__file__).parent

        discover_and_register()
        undeclared = []
        for module in module_registry.list_discovered():
            if module.name in self._CALLS_THROUGH_CORE or module.get_manifest().egress:
                continue
            module_dir = root / module.name
            if not module_dir.is_dir():
                continue
            for path in module_dir.rglob("*.py"):
                if self._CLIENTS.search(path.read_text(encoding="utf-8")):
                    undeclared.append(f"{module.name}: {path.name}")
                    break

        assert not undeclared, (
            "These modules import an HTTP or SMTP client but declare no egress, so "
            "they are missing from the subprocessor register a clinic shows its "
            f"patients. Add manifest['egress']: {undeclared}"
        )

    def test_the_check_can_actually_see_a_client(self) -> None:
        # A pattern that matched nothing would make the guard vacuous.
        import app.modules as modules_pkg

        client = Path(modules_pkg.__file__).parent / "whatsapp_kapso" / "client.py"
        assert self._CLIENTS.search(client.read_text(encoding="utf-8"))

    def test_the_known_destinations_are_declared(self) -> None:
        discover_and_register()
        declared = {
            entry.target
            for module in module_registry.list_discovered()
            for entry in module.get_manifest().egress
        }
        assert declared == {"openai", "kapso", "aeat", "smtp", "facturama"}

    def test_every_declaration_names_a_real_subprocessor(self) -> None:
        # The register goes into a processing agreement, so "OpenAI" is
        # not enough and neither is an empty purpose.
        discover_and_register()
        for module in module_registry.list_discovered():
            for entry in module.get_manifest().egress:
                assert len(entry.subprocessor) > 5, (module.name, entry.target)
                assert len(entry.purpose) > 20, (module.name, entry.target)


class TestDirectConstruction:
    def test_blank_target_refused(self) -> None:
        with pytest.raises(EgressError, match="target cannot be empty"):
            EgressDeclaration(target="  ", subprocessor="S", purpose="p")

    def test_uppercase_target_refused(self) -> None:
        with pytest.raises(EgressError, match="lower-case id"):
            EgressDeclaration(target="OpenAI", subprocessor="S", purpose="p")
