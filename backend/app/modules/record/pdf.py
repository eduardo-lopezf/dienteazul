"""The composed record as a document.

Rendered only for a :class:`~.models.Disclosure` — see ``disclosure.py``,
the one caller. The first page says what the document is: whose record,
handed to whom, why, by whom and when, and which sections it carries.

The wording comes from ``labels.json``, a copy of the screen's own
translations: a record reads the same on paper as on the *Expediente* tab.
"""

from __future__ import annotations

import asyncio
import json
import re
from datetime import date, datetime
from functools import cache
from html import escape
from io import BytesIO
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth.models import Clinic
from app.core.contracts import PersonBrief
from app.core.letterhead import LETTERHEAD_CSS, render_letterhead
from app.core.record import EntryStatus, RecordEntry
from app.core.regulation import record_regulation

from .models import Disclosure
from .service import ComposedRecord

#: Said by the entry's summary, or of no use on paper.
_HIDDEN = frozenset(
    {
        "first_name",
        "last_name",
        "name",
        "procedure",
        "condition",
        "items",
        "media_category",
        "chief_complaint",
    }
) | {"scan_document_id", "document_sha256"}

_TEXT = {
    "es": {
        "title": "Expediente clínico",
        "regulation": "Normativa de referencia",
        "patient": "Paciente",
        "generated": "Generado el",
        "folio": "Folio de entrega",
        "purpose": "Motivo de la entrega",
        "recipient": "Se entrega a",
        "by": "Entrega",
        "license": "Cédula",
        "sections": "Contenido",
        "empty": "Sin registros.",
        "confidential": (
            "Documento confidencial con datos personales sensibles. Su entrega quedó "
            "registrada en el expediente del paciente."
        ),
        "purposes": {
            "continuity_of_care": "Continuidad de la atención (referencia o interconsulta)",
            "patient_copy": "Copia para el paciente",
            "authorised_third_party": "Tercero autorizado por el paciente",
            "legal_requirement": "Requerimiento de autoridad",
        },
    },
    "en": {
        "title": "Clinical record",
        "regulation": "Reference regulation",
        "patient": "Patient",
        "generated": "Generated",
        "folio": "Disclosure ref.",
        "purpose": "Purpose",
        "recipient": "Handed to",
        "by": "Disclosed by",
        "license": "Licence",
        "sections": "Contents",
        "empty": "Nothing recorded.",
        "confidential": (
            "Confidential document with sensitive personal data. Its disclosure was "
            "recorded in the patient's record."
        ),
        "purposes": {
            "continuity_of_care": "Continuity of care (referral or consultation)",
            "patient_copy": "Copy for the patient",
            "authorised_third_party": "Third party authorised by the patient",
            "legal_requirement": "Requirement of an authority",
        },
    },
}

_ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}")
_CODE = re.compile(r"^[a-z]+(_[a-z]+)+$")


@cache
def _labels() -> dict[str, Any]:
    return json.loads((Path(__file__).parent / "labels.json").read_text(encoding="utf-8"))


def _day(value: date | datetime) -> str:
    return value.strftime("%d/%m/%Y")


def _value(key: str, value: Any, labels: dict[str, Any]) -> str:
    if isinstance(value, bool):
        return labels["yes"] if value else labels["no"]
    if isinstance(value, datetime | date):
        return _day(value)
    if isinstance(value, int | float):
        return str(value)
    if isinstance(value, str):
        if _ISO_DATE.match(value):
            return _day(date.fromisoformat(value[:10]))
        coded = labels["value"].get(key, {}).get(value)
        if coded:
            return coded
        return value.replace("_", " ") if _CODE.match(value) else value
    if isinstance(value, list):
        if key == "teeth":
            return ", ".join(
                str(tooth)
                if isinstance(tooth, int)
                else f"{tooth['tooth_number']}"
                + (f" ({', '.join(tooth['surfaces'])})" if tooth.get("surfaces") else "")
                for tooth in value
            )
        if key == "form_data":
            # What a form asks to write, each value under its own label.
            return " · ".join(
                f"{_value('form_field', item['field'], labels)}: {item['value']}" for item in value
            )
        if key == "affirmative_answers":
            return " · ".join(
                _value("question", item["question"], labels)
                + (f" — {item['detail']}" if item.get("detail") else "")
                for item in value
            )
        return ", ".join(_value(key, item, labels) for item in value)
    if isinstance(value, dict):
        return ", ".join(str(part) for part in value.values() if part not in (None, ""))
    return ""


def _entry(
    entry: RecordEntry, labels: dict[str, Any], authors: dict, text: dict, zone: ZoneInfo | None
) -> str:
    lines = []
    for key, value in entry.detail.items():
        if key in _HIDDEN or value in (None, ""):
            continue
        shown = _value(key, value, labels)
        if shown and shown != entry.summary:
            label = labels["field"].get(key, key)
            lines.append(
                f"<span class='kv'><span class='k'>{escape(label)}:</span> {escape(shown)}</span>"
            )
    items = "".join(
        "<li>"
        + escape(
            " · ".join(
                filter(
                    None,
                    [
                        item.get("treatment") or "—",
                        ", ".join(str(tooth) for tooth in item.get("teeth") or []),
                        _value("status", item.get("status") or "", labels),
                    ],
                )
            )
        )
        + "</li>"
        for item in entry.detail.get("items") or []
    )
    author = authors.get(entry.authored_by_professional_id)
    signed = ""
    if author is not None:
        name = f"{author.first_name} {author.last_name}".strip()
        licence = f" · {text['license']} {author.license_number}" if author.license_number else ""
        signed = f"<div class='author'>{escape(name + licence)}</div>"
    ended = (
        f" <span class='state'>({escape(labels['status']['ended'])})</span>"
        if entry.status is EntryStatus.ENDED
        else ""
    )
    return f"""
    <tr>
      <td class="when">{_day(entry.occurred_at.astimezone(zone))}</td>
      <td>
        <div class="summary">{escape(entry.summary)}{ended}</div>
        <div class="detail">{" ".join(lines)}</div>
        {f"<ul>{items}</ul>" if items else ""}
        {signed}
      </td>
    </tr>"""


def _render_html(
    record: ComposedRecord,
    disclosure: Disclosure,
    clinic: Clinic | None,
    discloser: PersonBrief | None,
    generated: datetime,
    letterhead: str,
) -> str:
    locale = disclosure.locale if disclosure.locale in _TEXT else "es"
    text, labels = _TEXT[locale], _labels()[locale]
    authors = {person.id: person for person in record.professionals}
    regulation = record_regulation(clinic) if clinic is not None else None
    regulation_line = (
        f"<p class='notice'>{escape(text['regulation'])}: {escape(regulation)}</p>"
        if regulation
        else ""
    )

    identity = next(
        (
            s.entries[0]
            for s in record.sections
            if s.qualified_name == "patients.identification" and s.entries
        ),
        None,
    )
    by = ""
    if discloser is not None:
        by = f"{discloser.first_name} {discloser.last_name}".strip()
        if discloser.license_number:
            by += f" · {text['license']} {discloser.license_number}"

    def title(section) -> str:
        return labels["section"].get(section.title_key, section.name)

    body = []
    for section in record.sections:
        # Newest first, as on the screen.
        rows = "".join(
            _entry(entry, labels, authors, text, generated.tzinfo)
            for entry in reversed(section.entries)
        )
        body.append(
            f"<h2>{escape(title(section))}</h2>"
            + (
                f"<table class='entries'>{rows}</table>"
                if rows
                else f"<p class='none'>{text['empty']}</p>"
            )
        )

    cover = [
        (text["patient"], identity.summary if identity else ""),
        (text["recipient"], disclosure.recipient_name),
        (text["purpose"], text["purposes"].get(disclosure.purpose, disclosure.purpose)),
        (text["by"], by),
        (text["generated"], generated.strftime("%d/%m/%Y %H:%M")),
        (text["sections"], ", ".join(title(section) for section in record.sections)),
    ]
    cover_rows = "".join(
        f"<tr><td class='k'>{escape(label)}</td><td>{escape(value)}</td></tr>"
        for label, value in cover
        if value
    )
    folio = disclosure.id.hex[:8].upper()

    return f"""<!DOCTYPE html>
<html lang="{locale}">
<head>
<meta charset="utf-8">
<title>{text["title"]}</title>
<style>
  @page {{ size: letter; margin: 16mm 18mm 18mm;
           @bottom-left {{ content: "{text["folio"]} {folio}"; font-size: 8pt; color: #555; }}
           @bottom-right {{ content: counter(page) " / " counter(pages); font-size: 8pt; color: #555; }} }}
  body {{ font-family: "Helvetica Neue", Arial, sans-serif; font-size: 9.5pt; color: #111; }}
{LETTERHEAD_CSS}
  h1 {{ font-size: 12pt; letter-spacing: 0.06em; text-transform: uppercase; margin: 2px 0 6px; }}
  table {{ width: 100%; border-collapse: collapse; }}
  .cover td {{ padding: 2px 0; vertical-align: top; }}
  .cover .k {{ width: 34mm; color: #555; }}
  .notice {{ font-size: 8pt; color: #555; margin: 6px 0 4px; }}
  h2 {{ font-size: 10.5pt; margin: 14px 0 4px; padding-bottom: 2px; border-bottom: 0.6pt solid #999;
        break-after: avoid; }}
  .entries td {{ padding: 4px 0; vertical-align: top; border-bottom: 0.4pt solid #ddd; }}
  .when {{ width: 22mm; color: #555; white-space: nowrap; }}
  .summary {{ white-space: pre-wrap; }}
  .detail {{ font-size: 8.5pt; color: #333; }}
  .kv {{ margin-right: 10px; }}
  .k {{ color: #666; }}
  .author, .state {{ font-size: 8.5pt; color: #555; }}
  ul {{ margin: 2px 0 0 14px; padding: 0; font-size: 8.5pt; }}
  .none {{ color: #777; margin: 2px 0; }}
</style>
</head>
<body>
  {letterhead}
  <h1>{text["title"]}</h1>
  <table class="cover">{cover_rows}</table>
  <p class="notice">{text["confidential"]}</p>
  {regulation_line}
  {"".join(body)}
</body>
</html>"""


def _html_to_pdf(html: str) -> bytes:
    from weasyprint import HTML

    buffer = BytesIO()
    HTML(string=html).write_pdf(buffer)
    return buffer.getvalue()


async def render_record_pdf(
    db: AsyncSession,
    record: ComposedRecord,
    disclosure: Disclosure,
    discloser: PersonBrief | None,
) -> bytes:
    clinic = await db.get(Clinic, record.clinic_id)
    generated = record.composed_at
    try:
        if clinic is not None:
            generated = generated.astimezone(ZoneInfo(clinic.timezone))
    except Exception:  # unknown tz id — the composition's own time still stands
        pass
    # The head of whoever hands the record over — theirs, or the clinic's.
    letterhead = await render_letterhead(
        db, record.clinic_id, disclosure.disclosed_by_professional_id
    )
    html = _render_html(record, disclosure, clinic, discloser, generated, letterhead)
    # WeasyPrint is CPU-bound; keep the event loop free.
    return await asyncio.to_thread(_html_to_pdf, html)
