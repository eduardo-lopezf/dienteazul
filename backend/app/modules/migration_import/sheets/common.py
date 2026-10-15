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


# --- What a column holds, read from its values -----------------------------
#
# For a column whose name says nothing ("Dato 3"): most of its values are
# emails, phones, ID documents, dates, times or amounts. Only a guess the
# person confirms, like the one from the name — and the name wins.

_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_CURP = re.compile(r"^[A-Z]{4}\d{6}[HM][A-Z]{5}[A-Z0-9]\d$", re.IGNORECASE)
_RFC = re.compile(r"^[A-ZÑ&]{3,4}\d{6}[A-Z0-9]{3}$", re.IGNORECASE)
_DATE = re.compile(r"^\d{1,4}[/.\-]\d{1,2}[/.\-]\d{1,4}")
_TIME = re.compile(r"^\d{1,2}[:.h]\d{2}(:\d{2})?\s*([ap]\.?m\.?)?$", re.IGNORECASE)


def value_kind(value: str, region: str | None = None) -> str | None:
    """``email``, ``id_document``, ``date``, ``time``, ``phone`` or ``amount``."""
    text = value.strip()
    if not text:
        return None
    if _EMAIL.match(text):
        return "email"
    if _CURP.match(text) or _RFC.match(text):
        return "id_document"
    if _DATE.match(text):
        return "date"
    if _TIME.match(text):
        return "time"
    digits = re.sub(r"\D", "", text)
    if 8 <= len(digits) <= 15 and re.fullmatch(r"[+\d\s().\-]+", text):
        return "phone"
    if parse_amount(text) is not None:
        return "amount"
    return None


def column_kind(values: list[str], region: str | None = None) -> str | None:
    """What most of a column's non-empty values are, if most agree."""
    kinds = [value_kind(v, region) for v in values if v.strip()]
    if not kinds:
        return None
    best = max(set(kinds), key=kinds.count)
    return best if best is not None and kinds.count(best) * 10 >= len(kinds) * 8 else None


def suggest_by_content(
    rows: list[list[str]],
    chosen: list[str | None],
    by_kind: dict[str, tuple[str, ...]],
    region: str | None = None,
) -> list[str | None]:
    """Fill the columns the names left blank, from their values.

    ``by_kind`` maps a value kind to the fields it can be, in preference
    order; a field already taken is not offered twice."""
    taken = {field for field in chosen if field}
    result = list(chosen)
    for index, field in enumerate(chosen):
        if field is not None:
            continue
        kind = column_kind([row[index] for row in rows[:200]], region)
        for candidate in by_kind.get(kind or "", ()):
            if candidate not in taken:
                result[index] = candidate
                taken.add(candidate)
                break
    return result


def infer_date_order(values: list[str]) -> str | None:
    """``dmy``, ``mdy`` or ``ymd`` when the values say so, else ``None``.

    "25/03/2026" can only be day first; "03/25/2026" only month first; a
    four-digit first part is year first (ISO dates, which Excel cells
    become, are read as such whatever the order). A file whose dates all fit both
    ways says nothing — the person chooses, as before."""
    seen: set[str] = set()
    for value in values:
        parts = re.split(r"[/.\-]", value.strip()[:10])
        if len(parts) != 3 or not all(p.isdigit() for p in parts):
            continue
        a, b, _ = (int(p) for p in parts)
        if len(parts[0]) == 4:
            # ISO (what an Excel date cell becomes) reads the same whatever
            # the order chosen; only 2026/03/25 says something.
            if value.strip()[4] != "-":
                seen.add("ymd")
        elif a > 12 >= b:
            seen.add("dmy")
        elif b > 12 >= a:
            seen.add("mdy")
    return next(iter(seen)) if len(seen) == 1 else None
