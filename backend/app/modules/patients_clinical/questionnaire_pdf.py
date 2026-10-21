"""The health questionnaire as a blank sheet to fill in by hand — the adult
form, or the pediatric one (odontología pediátrica) a parent or guardian
fills in and signs, closing with their consent to the child's care.

Who the patient is comes printed; everything they declare is left to
write. The filled-in sheet is scanned and filed with a questionnaire
(``scan_document_id``). Nothing clinical is printed here — a record with
its answers leaves the clinic through a disclosure, not through this.

The wording is ``questionnaire_labels.json``, a copy of the screen's. The
head of the sheet is the clinic's letterhead (``app.core.letterhead``).
"""

from __future__ import annotations

import asyncio
import json
from datetime import date
from functools import cache
from html import escape
from io import BytesIO
from pathlib import Path
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth.models import Clinic
from app.core.letterhead import LETTERHEAD_CSS, render_letterhead
from app.core.regulation import record_regulation
from app.modules.patients.models import Patient

from .questionnaire import (
    CONDITION_GROUPS,
    PEDIATRIC_CONDITION_GROUPS,
    PEDIATRIC_QUESTION_GROUPS,
    QUESTIONS,
)

#: Questions that ask for a cause, on a line of their own.
_WITH_CAUSE = frozenset({"medical_care_2y", "hospitalized_5y", "taking_medication"})


@cache
def _labels() -> dict[str, Any]:
    path = Path(__file__).parent / "questionnaire_labels.json"
    return json.loads(path.read_text(encoding="utf-8"))


def _age(born: date | None) -> str:
    if born is None:
        return ""
    today = date.today()
    return str(today.year - born.year - ((today.month, today.day) < (born.month, born.day)))


def _address(address: dict | None) -> str:
    if not address:
        return ""
    city = " ".join(filter(None, [address.get("postal_code"), address.get("city")]))
    return ", ".join(p for p in [address.get("street"), city, address.get("state")] if p)


def _field(label: str, value: str | None, width: int) -> str:
    return (
        f"<td class='k'>{escape(label)}:</td>"
        f"<td class='line' style='width:{width}%'>{escape(value or '')}&nbsp;</td>"
    )


def render_html(
    patient: Patient, locale: str, letterhead: str, regulation: str | None = None
) -> str:
    text = _labels().get(locale) or _labels()["es"]
    yes, no = ("SÍ", "NO") if locale != "en" else ("YES", "NO")

    # What the sheet is kept under, said above the line the patient signs.
    regulation_line = (
        f"<p class='regulation'>{escape(text['regulation'])}: {escape(regulation)}</p>"
        if regulation
        else ""
    )

    questions = []
    for number, key in enumerate(QUESTIONS, start=1):
        ask = text["which"] if key == "taking_medication" else text["cause"]
        cause = (
            f"<tr><td></td><td colspan='3' class='cause'>{escape(ask)}: "
            "<span class='rule'></span></td></tr>"
            if key in _WITH_CAUSE
            else ""
        )
        questions.append(
            f"<tr><td class='n'>{number}.</td><td>{escape(text['questions'][key])}</td>"
            f"<td class='box'><span></span></td><td class='box'><span></span></td></tr>{cause}"
        )

    groups = []
    for keys in CONDITION_GROUPS.values():
        items = "".join(
            f"<div class='cond'><span class='tick'></span>{escape(text['conditions'][key])}</div>"
            for key in keys
        )
        groups.append(f"<div class='group'>{items}</div>")

    return f"""<!DOCTYPE html>
<html lang="{escape(locale)}">
<head>
<meta charset="utf-8">
<title>{escape(text["title"])}</title>
<style>
  @page {{ size: letter; margin: 16mm 20mm;
           @bottom-right {{ content: counter(page); font-size: 9pt; }} }}
  body {{ font-family: "Helvetica Neue", Arial, sans-serif; font-size: 10pt; color: #000; }}
{LETTERHEAD_CSS}
  table {{ width: 100%; border-collapse: collapse; }}
  .fields {{ margin-bottom: 8px; }}
  .fields td {{ vertical-align: bottom; padding: 0; }}
  .k {{ white-space: nowrap; width: 1%; padding-right: 4px !important; }}
  .line {{ border-bottom: 0.8pt solid #000; padding: 0 4px 1px !important; }}
  h1 {{ text-align: center; font-size: 11pt; font-style: italic; text-transform: uppercase;
        margin: 12px 0 0; border-top: 1.5pt solid #000; padding-top: 8px; }}
  .sub {{ text-align: center; font-size: 8pt; font-style: italic; margin-bottom: 8px; }}
  .b {{ font-weight: 700; font-style: italic; }}
  .questions td {{ padding: 2.5px 0; vertical-align: top; }}
  .questions th {{ font-size: 8pt; font-style: italic; }}
  .n {{ width: 6mm; }}
  .box {{ width: 11mm; text-align: center; }}
  .box span, .tick {{ display: inline-block; width: 5mm; height: 3.2mm; border: 0.8pt solid #000; }}
  .cause {{ padding-bottom: 5px !important; }}
  .rule {{ display: inline-block; width: 110mm; border-bottom: 0.8pt solid #000; }}
  .intro {{ font-weight: 700; font-style: italic; margin: 0 0 8px; text-align: justify; }}
  .group {{ columns: 3; column-gap: 6mm; margin-bottom: 9px; padding-bottom: 6px;
            border-bottom: 0.4pt solid #999; }}
  .cond {{ break-inside: avoid; font-style: italic; font-size: 9.5pt; padding: 1.5px 0 1.5px 7mm;
           text-indent: -7mm; }}
  .tick {{ margin-right: 5px; vertical-align: -2px; }}
  .ruled {{ border-bottom: 0.8pt solid #000; height: 7mm; }}
  .regulation {{ margin: 6mm 0 0; font-size: 8.5pt; color: #333; }}
  .sign {{ margin-top: 12mm; }}
  .sign td {{ vertical-align: top; }}
  .hand {{ border-top: 0.8pt solid #000; text-align: center; font-weight: 700; font-style: italic;
           font-size: 9pt; padding-top: 2px; }}
  .page {{ break-before: page; }}
</style>
</head>
<body>
  {letterhead}
  <table class="fields"><tr>
    {_field(text["lastName"], patient.last_name, 38)}
    {_field(text["name"], patient.first_name, 32)}
    {_field(text["age"], _age(patient.date_of_birth), 6)}
  </tr></table>
  <table class="fields"><tr>{_field(text["address"], _address(patient.address), 88)}</tr></table>
  <table class="fields"><tr>
    {_field(text["phone"], patient.phone, 30)}<td style="width:60%"></td>
  </tr></table>

  <h1>{escape(text["title"])}</h1>
  <div class="sub">({escape(text["confidential"])})</div>
  <table class="fields b"><tr>
    {_field(text["takenAt"], "", 44)}{_field(text["time"], "", 26)}
  </tr></table>
  <table class="fields b"><tr>{_field(text["chiefComplaint"], "", 60)}</tr></table>
  <div class="ruled"></div>
  <table class="fields b" style="margin-top:9px"><tr>
    {_field(text["bloodType"], "", 16)}<td style="width:60%"></td>
  </tr></table>
  <table class="fields b"><tr>{_field(text["allergies"], "", 86)}</tr></table>

  <table class="questions">
    <tr><th></th><th></th><th>{yes}</th><th>{no}</th></tr>
    {"".join(questions)}
  </table>

  <div class="page">
    <p class="intro">{escape(text["conditionsIntro"])}</p>
    {"".join(groups)}
    <table class="fields"><tr>{_field(text["drugsDetail"], "", 70)}</tr></table>
    <div class="b" style="margin-top:8px">{escape(text["otherConditions"])}</div>
    <div class="ruled"></div><div class="ruled"></div>
    {regulation_line}
    <table class="sign"><tr>
      <td style="width:58%"><div class="hand">{escape(text["signature"])}</div></td>
      <td style="width:10%"></td>
      <td style="width:32%"><div class="hand">{escape(text["date"])}</div></td>
    </tr></table>
  </div>
</body>
</html>"""


#: Pediatric questions whose detail line asks "which one", "when" or "to what".
_PEDIATRIC_DETAIL: dict[str, str] = {
    "plays_sport": "which",
    "current_illness": "which",
    "taking_medication": "which",
    "head_face_accident": "when",
    "allergic": "toWhat",
    "tonsillectomy": "when",
    "adenoidectomy": "when",
    "prolonged_illness": "which",
    "receives_medical_care": "why",
    "prior_surgery": "which",
    "anesthesia_reaction": "which",
}


def render_pediatric_html(
    patient: Patient, locale: str, letterhead: str, regulation: str | None = None
) -> str:
    """The pediatric form, after the paper one clinics use: who the child is
    comes printed; the rest is written by the parent or guardian, who signs
    the consent at the foot."""
    text = _labels().get(locale) or _labels()["es"]
    ped = text["pediatric"]
    yes, no = ("SÍ", "NO") if locale != "en" else ("YES", "NO")
    gender = ped["genders"].get(patient.gender or "", "")
    address = patient.address or {}

    def fields(*cells: tuple[str, str | None, int]) -> str:
        return "<table class='fields'><tr>" + "".join(_field(*c) for c in cells) + "</tr></table>"

    def questions(group: str) -> str:
        rows = []
        for key in PEDIATRIC_QUESTION_GROUPS[group]:
            ask = _PEDIATRIC_DETAIL.get(key)
            detail = (
                f"<td class='cause'>{escape(ped['detail'][ask])} <span class='rule s'></span></td>"
                if ask
                # Kept even empty, so every block's boxes line up.
                else "<td class='cause'></td>"
            )
            rows.append(
                f"<tr><td>{escape(text['questions'][key])}</td>"
                f"<td class='box'><span></span></td><td class='box'><span></span></td>{detail}</tr>"
            )
        return (
            f"<table class='questions'><tr><th></th><th>{yes}</th><th>{no}</th><th></th></tr>"
            + "".join(rows)
            + "</table>"
        )

    conditions = "".join(
        f"<div class='cond'><span class='tick'></span>{escape(text['conditions'][key])}</div>"
        for keys in PEDIATRIC_CONDITION_GROUPS.values()
        for key in keys
    )
    regulation_line = (
        f"<p class='regulation'>{escape(text['regulation'])}: {escape(regulation)}</p>"
        if regulation
        else ""
    )
    f = ped["fields"]

    return f"""<!DOCTYPE html>
<html lang="{escape(locale)}">
<head>
<meta charset="utf-8">
<title>{escape(ped["title"])}</title>
<style>
  @page {{ size: letter; margin: 14mm 18mm;
           @bottom-right {{ content: counter(page); font-size: 9pt; }} }}
  body {{ font-family: "Helvetica Neue", Arial, sans-serif; font-size: 9.5pt; color: #000; }}
{LETTERHEAD_CSS}
  table {{ width: 100%; border-collapse: collapse; }}
  .fields {{ margin-bottom: 5px; }}
  .fields td {{ vertical-align: bottom; padding: 0; }}
  .k {{ white-space: nowrap; width: 1%; padding-right: 4px !important; }}
  .line {{ border-bottom: 0.8pt solid #000; padding: 0 4px 1px !important; }}
  h1 {{ text-align: center; font-size: 13pt; letter-spacing: 1px; margin: 8px 0 2px; }}
  .date {{ text-align: right; margin-bottom: 6px; }}
  h2 {{ font-size: 9.5pt; text-transform: uppercase; margin: 10px 0 4px; }}
  .questions td {{ padding: 2px 0; vertical-align: bottom; }}
  .questions th {{ font-size: 8pt; width: 10mm; }}
  .questions th:first-child, .questions th:last-child {{ width: auto; }}
  .box {{ width: 10mm; text-align: center; }}
  .box span, .tick {{ display: inline-block; width: 5mm; height: 3.2mm; border: 0.8pt solid #000; }}
  .cause {{ width: 45%; white-space: nowrap; }}
  .rule {{ display: inline-block; width: 110mm; border-bottom: 0.8pt solid #000; }}
  .rule.s {{ width: 60mm; }}
  .conds {{ columns: 2; column-gap: 8mm; }}
  .cond {{ break-inside: avoid; padding: 1.5px 0; }}
  .tick {{ margin-right: 5px; vertical-align: -2px; }}
  .ruled {{ border-bottom: 0.8pt solid #000; height: 6mm; }}
  .consent {{ margin-top: 8mm; text-align: justify; font-size: 9pt; }}
  .regulation {{ margin: 3mm 0 0; font-size: 8.5pt; color: #333; }}
  .sign {{ margin-top: 14mm; }}
  .hand {{ border-top: 0.8pt solid #000; text-align: center; font-weight: 700; font-size: 9pt;
           padding-top: 2px; }}
  .page {{ break-before: page; }}
</style>
</head>
<body>
  {letterhead}
  <h1>{escape(ped["title"])}</h1>
  <div class="date">{escape(text["date"])}: <span class="rule s" style="width:35mm"></span></div>

  {
        fields(
            (f["patientName"], f"{patient.first_name} {patient.last_name}", 50),
            (f["sex"], gender, 12),
            (text["age"], _age(patient.date_of_birth), 6),
        )
    }
  {
        fields(
            (
                f["birthDate"],
                patient.date_of_birth.strftime("%d/%m/%Y") if patient.date_of_birth else "",
                18,
            ),
            (text["address"], address.get("street"), 60),
        )
    }
  {
        fields(
            (f["city"], address.get("city"), 34),
            (f["postalCode"], address.get("postal_code"), 12),
            (text["phone"], patient.phone, 20),
        )
    }
  {fields((f["school"], "", 40), (f["school_grade"], "", 14), (f["siblings"], "", 8))}
  {
        fields(
            (f["guardian_name"], "", 40),
            (f["guardian_occupation"], "", 20),
            (text["phone"], "", 14),
        )
    }
  {fields((f["physician_name"], "", 80))}
  {
        fields(
            (f["weight"], "", 14),
            (f["height"], "", 14),
            (f["blood_pressure"], "", 14),
            (f["temperature"], "", 14),
        )
    }
  {fields((f["behavior"], "", 80))}

  <h2>{escape(ped["sections"]["dental"])}</h2>
  {fields((text["chiefComplaint"], "", 70))}
  {questions("dental")}
  <h2>{escape(ped["sections"]["habits"])}</h2>
  {questions("habits")}

  <h2>{escape(ped["sections"]["medical"])}</h2>
  {questions("medical")}
  <p style="margin:6px 0 3px">{escape(ped["conditionsIntro"])}</p>
  <div class="conds">{conditions}</div>

  <div class="page">
    <h2>{escape(ped["sections"]["history"])}</h2>
    {fields((f["current_health"], "", 70))}
    {fields((f["last_physical_exam"], "", 70))}
    {questions("history")}
    <div style="margin-top:6px">{escape(text["otherConditions"])}</div>
    <div class="ruled"></div><div class="ruled"></div>

    <p class="consent">{escape(ped["consent"])}</p>
    {regulation_line}
    <table class="sign"><tr>
      <td style="width:58%"><div class="hand">{escape(ped["signature"])}</div></td>
      <td style="width:10%"></td>
      <td style="width:32%"><div class="hand">{escape(text["date"])}</div></td>
    </tr></table>
  </div>
</body>
</html>"""


def _html_to_pdf(html: str) -> bytes:
    from weasyprint import HTML

    buffer = BytesIO()
    HTML(string=html).write_pdf(buffer)
    return buffer.getvalue()


async def render_blank_pdf(
    db: AsyncSession,
    patient: Patient,
    professional_id: UUID | None,
    locale: str = "es",
    kind: str = "adult",
) -> bytes:
    """``professional_id`` is whoever prints the sheet, when they are one
    of the clinic's professionals: the form carries their letterhead."""
    letterhead = await render_letterhead(db, patient.clinic_id, professional_id)
    # WeasyPrint is CPU-bound; keep the event loop free.
    clinic = await db.get(Clinic, patient.clinic_id)
    regulation = record_regulation(clinic) if clinic is not None else None
    render = render_pediatric_html if kind == "pediatric" else render_html
    return await asyncio.to_thread(_html_to_pdf, render(patient, locale, letterhead, regulation))
