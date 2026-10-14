"""Spreadsheets in: an ``.xlsx`` or ``.csv`` read, mapped and turned into a ``.dpm``."""

from .appointments import convert_appointments
from .balances import convert_balances
from .common import SOURCE_SYSTEM, region_of, sheet_hash
from .kinds import KINDS, missing_required, template_for
from .patients import (
    FIELDS,
    convert_patients,
    suggest_fields,
    template_bytes,
)
from .reader import MAX_BYTES, SUFFIXES, Sheet, SheetError, read_sheet

__all__ = [
    "KINDS",
    "convert_appointments",
    "convert_balances",
    "missing_required",
    "template_for",
    "FIELDS",
    "MAX_BYTES",
    "SOURCE_SYSTEM",
    "SUFFIXES",
    "Sheet",
    "SheetError",
    "convert_patients",
    "read_sheet",
    "region_of",
    "sheet_hash",
    "suggest_fields",
    "template_bytes",
]
