"""CSV and ZIP helpers for the modules that hand tables to a person.

Two conventions, both learned from Excel rather than from the format:

* **UTF-8 BOM.** Without it Excel-ES reads the file as Latin-1 and every
  accent in a patient's name becomes mojibake.
* **The separator decides the decimal mark.** A Spanish Excel pairs ``;``
  with comma decimals and ``,`` with dots; mixing them silently turns the
  money column into text, which is worse than an error because the sums
  at the bottom are simply wrong.

Lives in core because more than one module exports tables (``billing``'s
accountant bundle, the Productividad reports) and a second copy of these
twenty lines is how the two would drift apart. Named ``exports`` and not
``csv`` so nothing in this package has to think about shadowing stdlib.
"""

from __future__ import annotations

import csv
import io
import zipfile
from datetime import date
from decimal import Decimal
from typing import Any

#: Excel-ES reads this as "UTF-8", not as a stray character.
UTF8_BOM = b"\xef\xbb\xbf"


def fmt_value(value: Any, separator: str = ",") -> str:
    """One cell, written the way the chosen separator expects it."""
    if isinstance(value, Decimal):
        text = f"{value:.2f}"
        return text.replace(".", ",") if separator == ";" else text
    if isinstance(value, float):
        text = f"{value:.2f}"
        return text.replace(".", ",") if separator == ";" else text
    if isinstance(value, bool):
        return "1" if value else "0"
    return "" if value is None else str(value)


def to_csv(rows: list[dict], headers: list[str], separator: str = ",") -> bytes:
    """A CSV whose columns are ``headers``, read from each row by that key."""
    buf = io.StringIO()
    writer = csv.writer(buf, delimiter=separator)
    writer.writerow(headers)
    for row in rows:
        writer.writerow([fmt_value(row.get(header), separator) for header in headers])
    return UTF8_BOM + buf.getvalue().encode("utf-8")


def period_filename(stem: str, date_from: date, date_to: date, suffix: str = "zip") -> str:
    """``facturacion_2026-09-01_2026-09-30.zip`` — the range is the filename.

    A downloads folder with three files called ``informe.zip`` is a folder
    nobody can use.
    """
    return f"{stem}_{date_from.isoformat()}_{date_to.isoformat()}.{suffix}"


def to_zip(files: dict[str, bytes]) -> bytes:
    """Several files in one download, in the order given."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, content in files.items():
            archive.writestr(name, content)
    return buf.getvalue()
