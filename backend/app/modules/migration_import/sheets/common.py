"""What every kind of sheet shares: reading a value the way it was meant.

Dates follow the order the person chose — 03/04 is never guessed —
phones go to international format with the clinic's country, amounts
read both 1,234.50 and 1.234,50, and column names are matched to fields
without accents or case.
"""

from __future__ import annotations

import hashlib
import re
import unicodedata
import uuid
from datetime import date, datetime, time
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

SOURCE_SYSTEM = "spreadsheet"
NAMESPACE = uuid.UUID("6f1d3c52-5b8e-4e0a-9b2f-1c7d4a9e8b31")

DATE_FORMATS: dict[str, tuple[str, ...]] = {
    "dmy": ("%d/%m/%Y", "%d-%m-%Y", "%d.%m.%Y", "%d/%m/%y", "%d-%m-%y"),
    "mdy": ("%m/%d/%Y", "%m-%d-%Y", "%m/%d/%y"),
    "ymd": ("%Y/%m/%d", "%Y.%m.%d"),
}

# Country a clinic is in, from its currency when the address does not say.
_COUNTRY_OF_CURRENCY = {
    "MXN": "MX",
    "EUR": "ES",
    "USD": "US",
    "COP": "CO",
    "ARS": "AR",
    "CLP": "CL",
}


def plain(text: str) -> str:
    folded = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    return re.sub(r"\s+", " ", folded).strip().lower()


def suggest(headers: list[str], fields: dict[str, tuple[str, ...]]) -> list[str | None]:
    """The field each column most likely holds, each field at most once.

    ``ratio`` ≥ 85 and not ``WRatio``: the looser scorer matched "Fecha
    de alta" to the ID document.
    """
    from rapidfuzz import fuzz

    candidates: list[tuple[float, int, str]] = []
    for index, header in enumerate(headers):
        name = plain(header)
        for field, synonyms in fields.items():
            score = max(fuzz.ratio(name, plain(s)) for s in synonyms)
            if score >= 85:
                candidates.append((score, index, field))
    chosen: list[str | None] = [None] * len(headers)
    taken: set[str] = set()
    for _score, index, field in sorted(candidates, reverse=True):
        if chosen[index] is None and field not in taken:
            chosen[index] = field
            taken.add(field)
    return chosen


def region_of(clinic: Any) -> str | None:
    country = ((getattr(clinic, "address", None) or {}).get("country") or "").strip().upper()
    if len(country) == 2:
        return country
    return _COUNTRY_OF_CURRENCY.get(getattr(clinic, "currency", None) or "")


def parse_date(value: str, order: str) -> date | None:
    try:
        return date.fromisoformat(value[:10])  # what Excel cells come back as
    except ValueError:
        pass
    for fmt in DATE_FORMATS.get(order, ()):
        try:
            return datetime.strptime(value, fmt).date()
        except ValueError:
            continue
    return None


_TIME_FORMATS = ("%H:%M", "%H:%M:%S", "%I:%M %p", "%I:%M:%S %p", "%I %p", "%H.%M", "%Hh%M")


def parse_time(value: str) -> time | None:
    text = value.strip().upper().replace("A.M.", "AM").replace("P.M.", "PM").replace(".", ":")
    text = re.sub(r"\s*(AM|PM)$", r" \1", text)
    for fmt in _TIME_FORMATS:
        try:
            return datetime.strptime(text, fmt.replace(".", ":")).time()
        except ValueError:
            continue
    return None


def parse_phone(value: str, region: str | None) -> str | None:
    import phonenumbers

    try:
        number = phonenumbers.parse(value, None if value.startswith("+") else region)
    except phonenumbers.NumberParseException:
        return None
    if not phonenumbers.is_possible_number(number):
        return None
    return phonenumbers.format_number(number, phonenumbers.PhoneNumberFormat.E164)


def parse_amount(value: str) -> Decimal | None:
    """``1,234.50``, ``1.234,50``, ``$ -80``, ``(80)`` — the last separator
    followed by one or two digits is the decimal one."""
    text = value.strip()
    negative = text.startswith("(") and text.endswith(")")
    text = re.sub(r"[^\d,.\-]", "", text)
    if text.startswith("-"):
        negative, text = True, text[1:]
    if not text or "-" in text:
        return None
    last = max(text.rfind(","), text.rfind("."))
    if last != -1 and 1 <= len(text) - last - 1 <= 2:
        whole, cents = text[:last], text[last + 1 :]
        text = re.sub(r"[,.]", "", whole) + "." + cents
    else:
        text = re.sub(r"[,.]", "", text)
    try:
        amount = Decimal(text)
    except InvalidOperation:
        return None
    return -amount if negative else amount


def sheet_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def row_uuid(digest: str, line: int, kind: str = "") -> str:
    """The same row of the same file always gets the same id."""
    key = f"{digest}:{line}" if not kind else f"{kind}:{digest}:{line}"
    return str(uuid.uuid5(NAMESPACE, key))
