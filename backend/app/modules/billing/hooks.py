"""Billing compliance hooks for country module extensibility.

This module provides an interface for country-specific compliance modules
(e.g., verifactu-es for Spain, factur-x for France) to integrate with
the billing system without the billing module knowing about specific countries.

The billing module NEVER imports or references any country module directly.
Country modules register themselves via the BillingHookRegistry.
"""

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

if TYPE_CHECKING:
    from app.core.auth.models import Clinic

    from .models import Invoice, InvoicePayment


class BillingComplianceHook(ABC):
    """Interface for country-specific compliance modules.

    Any country compliance module (verifactu-es, factur-x-fr, sdi-it, etc.)
    implements this interface and registers with BillingHookRegistry.
    The billing module does not know which countries exist.

    Example implementation for Spain (in separate module):

        class VerifactuHook(BillingComplianceHook):
            @property
            def country_code(self) -> str:
                return "ES"

            def get_required_fields(self) -> list[str]:
                return ["billing_tax_id"]  # NIF obligatorio

            async def on_invoice_issued(self, invoice, db) -> dict:
                # Generate hash, QR code, etc.
                return {"hash": "...", "qr": "...", "aeat_id": "..."}

            def enhance_pdf_data(self, pdf_data, invoice) -> dict:
                pdf_data["qr_code"] = self._generate_qr(invoice)
                pdf_data["legal_notices"].append("Texto legal España")
                return pdf_data
    """

    @property
    @abstractmethod
    def country_code(self) -> str:
        """ISO country code (ES, FR, IT, PT, DE...).

        This determines which clinic configurations use this hook.
        """
        pass

    @property
    def name(self) -> str:
        """Human-readable name for this compliance module."""
        return f"Compliance module for {self.country_code}"

    @property
    def module_name(self) -> str | None:
        """The module that owns this hook.

        A module registers its hook when it is discovered, which happens
        whether or not it is installed; the registry hands the hook out
        only while this module is live (ADR 0018, 0035, 0038). ``None``
        means always — for hooks no module owns, as in tests.
        """
        return None

    async def validate_before_issue(
        self, invoice: "Invoice", db: AsyncSession
    ) -> tuple[bool, str | None]:
        """Validate invoice before issuing.

        Called before transitioning to 'issued' status.
        Use this for country-specific validation rules.

        Args:
            invoice: Invoice being issued
            db: Database session

        Returns:
            (is_valid, error_message): Tuple with validation result.
            If is_valid is False, error_message explains the problem.

        Example:
            # Validate Spanish NIF format
            if not self._validate_nif(invoice.billing_tax_id):
                return False, "Invalid NIF format"
            return True, None
        """
        return True, None  # Default: no validation

    async def on_invoice_issued(self, invoice: "Invoice", db: AsyncSession) -> dict[str, Any]:
        """Hook called after invoice is issued.

        Use this to:
        - Calculate document hash
        - Generate QR code
        - Submit to tax authority
        - Register in chain/ledger

        Args:
            invoice: Issued invoice
            db: Database session

        Returns:
            Dict of compliance data to store in invoice.compliance_data[country_code]
            Returns empty dict if no data to store.

        Example:
            return {
                "hash": "sha256...",
                "previous_hash": "sha256...",
                "qr_data": "https://...",
                "submission_id": "AEAT-123",
                "submitted_at": datetime.now(UTC).isoformat(),
            }
        """
        return {}  # Default: no compliance data

    async def on_credit_note_issued(
        self, credit_note: "Invoice", original_invoice: "Invoice", db: AsyncSession
    ) -> dict[str, Any]:
        """Hook called after a credit note (rectificativa) is issued.

        This hook is called AFTER the credit note transitions to "issued" status.
        Use it for country-specific compliance requirements.

        DEFAULT BEHAVIOR (no hook override):
            - Original invoice: Status UNCHANGED (remains valid)
            - Credit note: Status "issued" with negative balance
            - Both documents coexist as valid fiscal documents
            - Patient balance = sum of all invoice balances

        COUNTRY-SPECIFIC OVERRIDES:
            Override this hook to record what the tax authority needs about
            the credit note — an egreso CFDI for the SAT, a rectificativa for
            Verifactu — and return it as compliance data. Never call the
            authority here: write the pending record and let a scheduled job
            send it after commit (ADR 0067). Never set the original
            invoice's status either; cancelling it goes through billing's
            cancel endpoint (:meth:`on_invoice_cancelled`).

        Args:
            credit_note: The newly issued credit note (negative amounts)
            original_invoice: The invoice being rectified
            db: Database session (for any additional queries/updates)

        Returns:
            Dict of compliance data to store in credit_note.compliance_data

        Example (Mexico SAT):
            ```python
            async def on_credit_note_issued(self, credit_note, original_invoice, db):
                cfdi = await queue_egreso(db, credit_note, related=original_invoice)
                return {"MX": {"cfdi_id": str(cfdi.id), "state": "pending"}}
            ```
        """
        return {}  # Default: no compliance data, no status changes

    async def on_payment_recorded(
        self, invoice: "Invoice", link: "InvoicePayment", db: AsyncSession
    ) -> dict[str, Any]:
        """Hook called after a payment is applied to an issued invoice.

        Called in the same transaction, once the ``InvoicePayment`` is
        flushed and the invoice's status recomputed (``partial`` /
        ``paid``). Mexico's SAT needs a payment complement for every
        payment on a deferred (PPD) invoice. Like every hook it must not
        call an outside service: write what will be sent and let a
        scheduled job send it after commit (ADR 0067).

        Args:
            invoice: Invoice receiving the payment
            link: The new ``InvoicePayment``; its ``payment_id`` leads to the
                payment's date and method
            db: Database session

        Returns:
            Dict of compliance data to merge into invoice.compliance_data
        """
        return {}  # Default: no compliance data

    @property
    def cancellation_needs_confirmation(self) -> bool:
        """Whether an issued invoice stays ``issued`` until the authority
        confirms its cancellation.

        ``False`` (default): billing marks it ``cancelled`` right after
        :meth:`on_invoice_cancelled`. ``True``: billing leaves it
        ``issued`` and the module calls
        ``InvoiceWorkflowService.mark_cancelled`` once the authority
        answers — Mexico's SAT may wait for the receiver's acceptance.
        """
        return False

    async def before_cancel(
        self,
        invoice: "Invoice",
        reason: str,
        substitute: "Invoice | None",
        db: AsyncSession,
    ) -> tuple[bool, str | None]:
        """Validate a cancellation before anything changes.

        ``reason`` is the code the user chose (for the SAT, ``01``–``04``);
        ``substitute`` the invoice that replaces this one, when given.

        Returns:
            (is_valid, error_message), as :meth:`validate_before_issue`.
        """
        return True, None

    async def on_invoice_cancelled(
        self,
        invoice: "Invoice",
        reason: str,
        substitute: "Invoice | None",
        cancelled_by: UUID,
        db: AsyncSession,
    ) -> dict[str, Any]:
        """Hook called when an issued invoice is cancelled.

        Write the cancellation request; a scheduled job sends it after
        commit (ADR 0067). See :attr:`cancellation_needs_confirmation` for
        when the invoice becomes ``cancelled``; ``cancelled_by`` is who
        asked, for the module to pass to ``mark_cancelled`` then.

        Returns:
            Dict of compliance data to merge into invoice.compliance_data
        """
        return {}

    def enhance_pdf_data(self, pdf_data: dict, invoice: "Invoice") -> dict:
        """Modify PDF data before generation.

        Use this to add:
        - QR codes
        - Country-specific legal text
        - Compliance stamps/watermarks
        - Additional fields required by country

        Args:
            pdf_data: Dict with PDF template data
            invoice: Invoice being rendered

        Returns:
            Modified pdf_data dict

        Example:
            pdf_data["qr_code"] = self._generate_qr(invoice)
            pdf_data["legal_notices"] = pdf_data.get("legal_notices", [])
            pdf_data["legal_notices"].append(
                "Factura generada conforme al RD 1619/2012"
            )
            return pdf_data
        """
        return pdf_data  # Default: no changes

    def get_required_fields(self) -> list[str]:
        """List of required fields for this country.

        Fields are validated before issuing.
        Use dot notation for nested fields: "billing_address.postal_code"

        Returns:
            List of required field paths

        Example for Spain:
            return ["billing_tax_id"]  # NIF required

        Example for France:
            return ["billing_tax_id", "billing_address.postal_code"]
        """
        return []  # Default: no required fields

    def get_pdf_template(self) -> str | None:
        """Optional custom PDF template name for this country.

        Returns:
            Template name or None to use default
        """
        return None  # Default: use standard template

    async def can_edit_billing_party(
        self, invoice: "Invoice", db: AsyncSession
    ) -> tuple[bool, str | None]:
        """Whether the billing party (NIF/name/address) of an issued invoice
        can still be edited under this country's compliance rules.

        Default returns ``(False, ...)`` — most countries treat issued
        invoices as immutable. Verifactu overrides this to allow editing
        when the latest fiscal record is in a correctable state
        (``rejected`` / ``failed_validation``) — AEAT never registered
        the original data so Subsanación with corrected data is legal.
        """

        return False, "Issued invoices are immutable for this country."

    async def regenerate_after_party_change(
        self, invoice: "Invoice", db: AsyncSession
    ) -> dict[str, Any]:
        """Re-render the compliance record after a billing-party edit.

        Called by the billing workflow right after persisting the new
        ``billing_*`` fields. Implementations should re-run their hash
        chain / submission step from the updated invoice. Returns the
        same shape as :meth:`on_invoice_issued` so callers can merge
        the result into ``Invoice.compliance_data``.

        Default: no-op.
        """

        return {}


class BillingHookRegistry:
    """Registry for compliance hooks.

    Country modules register their hooks here.
    The billing module queries this registry to find applicable hooks.

    Usage by country module:

        # In verifactu_es/__init__.py
        class VerifactuModule(BaseModule):
            def on_load(self):
                BillingHookRegistry.register(VerifactuHook())

            def on_unload(self):
                BillingHookRegistry.unregister("ES")
    """

    _hooks: dict[str, BillingComplianceHook] = {}

    @classmethod
    def register(cls, hook: BillingComplianceHook) -> None:
        """Register a compliance hook.

        Args:
            hook: Hook instance to register

        Example:
            BillingHookRegistry.register(VerifactuHook())
        """
        cls._hooks[hook.country_code] = hook

    @classmethod
    def unregister(cls, country_code: str) -> None:
        """Unregister a compliance hook.

        Useful for testing or when module is unloaded.

        Args:
            country_code: ISO country code to unregister
        """
        cls._hooks.pop(country_code, None)

    @staticmethod
    def _live(
        hook: BillingComplianceHook | None, clinic: "Clinic | None" = None
    ) -> BillingComplianceHook | None:
        """The hook, while its module is live — and, for a clinic, while
        the clinic has it: an optional module it has not switched on
        (ADR 0066), or one of an App it lacks, is outside it."""
        if hook is None or hook.module_name is None:
            return hook
        from app.core.plugins.apps import modules_outside
        from app.core.plugins.registry import module_registry

        if not module_registry.is_installed(hook.module_name):
            return None
        if clinic is not None and hook.module_name in modules_outside(
            clinic.apps, clinic.account_tier, clinic.modules
        ):
            return None
        return hook

    @classmethod
    def get(cls, country_code: str) -> BillingComplianceHook | None:
        """Get hook by country code.

        Args:
            country_code: ISO country code (ES, FR, etc.)

        Returns:
            Hook instance, or None if none is registered or its module is
            not live
        """
        return cls._live(cls._hooks.get(country_code))

    @classmethod
    def get_for_clinic(cls, clinic: "Clinic") -> BillingComplianceHook | None:
        """Get hook for a clinic based on its configuration.

        Reads the country setting from clinic.settings and returns
        the appropriate hook if one is registered.

        Args:
            clinic: Clinic entity with settings

        Returns:
            Hook instance, or None if no hook is registered for the clinic's
            country, its module is not live, or the clinic does not have it
        """
        settings = clinic.settings or {}
        country = settings.get("country", "")
        return cls._live(cls._hooks.get(country), clinic)

    @classmethod
    def get_all(cls) -> dict[str, BillingComplianceHook]:
        """Get all registered hooks whose module is live.

        Returns:
            Dict mapping country codes to hooks
        """
        return {code: hook for code, hook in cls._hooks.items() if cls._live(hook)}

    @classmethod
    def is_registered(cls, country_code: str) -> bool:
        """Check if a country has a registered hook.

        Args:
            country_code: ISO country code

        Returns:
            True if a hook is registered and its module is live
        """
        return cls.get(country_code) is not None

    @classmethod
    def clear(cls) -> None:
        """Clear all registered hooks.

        Primarily for testing purposes.
        """
        cls._hooks.clear()
