"""The consent letter as a sheet of paper.

Two uses. A draft prints as a form: the patient's data and the text are
already on it, and the diagnosis, the plan, the names, the dates and the
signatures are ruled lines to fill in by hand. The signed sheet is then
scanned and filed (``ConsentService.sign`` with ``method="paper"``). A
letter signed on screen prints with that signature on it — a copy to hand
to the patient.

The text is the clinic's (ADR 0045); the lines around it are the ones a
*carta de consentimiento informado* carries under NOM-004-SSA3-2012 §10.1.1:
who informs, who accepts, two witnesses, place and date.

The head of the sheet is the clinic's letterhead (``app.core.letterhead``),
the same one its other printed documents carry.
"""

from __future__ import annotations

import asyncio
from datetime import date, datetime
from html import escape
from io import BytesIO
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth.models import Clinic
from app.core.letterhead import LETTERHEAD_CSS, render_letterhead
from app.core.regulation import record_regulation
from app.modules.patients.models import Patient

from .models import Consent

_LABELS = {
    "es": {
        "license": "Cédula profesional",
        "last_name": "Apellidos",
        "first_name": "Nombre",
        "age": "Edad",
        "address": "Domicilio",
        "phone": "Teléfono",
        "diagnosis": "Diagnóstico",
        "plan": "Plan de tratamiento",
        "place_date": "Lugar y fecha",
        "date": "Fecha",
        "patient_signature": "Nombre y firma del paciente o responsable",
        "accepts": "Enterado, conforme, acepto",
        "professional_signature": "Nombre y firma de quien informó",
        "witness": "Nombre y firma del testigo",
        "folio": "Folio",
        "regulation": "Normativa de referencia",
        "version": "plantilla v",
        "revoked": "Revocado el",
        "declined": "No aceptado el",
        "capacity": {
            "patient": "paciente",
            "guardian": "tutor legal",
            "representative": "representante",
        },
    },
    "en": {
        "license": "Professional licence",
        "last_name": "Last name",
        "first_name": "First name",
        "age": "Age",
        "address": "Address",
        "phone": "Phone",
        "diagnosis": "Diagnosis",
        "plan": "Treatment plan",
        "place_date": "Place and date",
        "date": "Date",
        "patient_signature": "Name and signature of the patient or person responsible",
        "accepts": "Informed, in agreement, I accept",
        "professional_signature": "Name and signature of who informed",
        "witness": "Name and signature of the witness",
        "folio": "Ref.",
        "regulation": "Reference regulation",
        "version": "template v",
        "revoked": "Revoked on",
        "declined": "Declined on",
        "capacity": {
            "patient": "patient",
            "guardian": "legal guardian",
            "representative": "representative",
        },
    },
}

_DIAGNOSIS_LINES = 3
_PLAN_LINES = 5


async def render_pdf(db: AsyncSession, consent: Consent, locale: str = "es") -> bytes:
    clinic = await db.get(Clinic, consent.clinic_id)
    patient = (
        await db.execute(
            select(Patient).where(
                Patient.id == consent.patient_id, Patient.clinic_id == consent.clinic_id
            )
        )
    ).scalar_one()
    html = _render_html(
        consent,
        clinic,
        patient,
        locale,
        # The letter answers to whoever explained it.
        await render_letterhead(db, consent.clinic_id, consent.explained_by_professional_id),
    )
    # WeasyPrint is CPU-bound; keep the event loop free.
    return await asyncio.to_thread(_html_to_pdf, html)


def _html_to_pdf(html: str) -> bytes:
    from weasyprint import HTML

    buffer = BytesIO()
    HTML(string=html).write_pdf(buffer)
    return buffer.getvalue()


def _local_date(moment: datetime | None, clinic: Clinic | None) -> date | None:
    if moment is None:
        return None
    try:
        return moment.astimezone(ZoneInfo(clinic.timezone)).date() if clinic else moment.date()
    except Exception:  # unknown tz id — the UTC date is still a date
        return moment.date()


def _age(born: date | None, on: date) -> str:
    if born is None:
        return ""
    return str(on.year - born.year - ((on.month, on.day) < (born.month, born.day)))


def _address(address: dict | None) -> str:
    if not address:
        return ""
    city = " ".join(filter(None, [address.get("postal_code"), address.get("city")]))
    parts = [address.get("street"), city, address.get("state")]
    return ", ".join(p for p in parts if p)


def _field(label: str, value: str | None, grow: int) -> str:
    """A labelled line: the value written on it, or left to fill in by hand."""
    return (
        f"<td class='k'>{label}:</td>"
        f"<td class='line' style='width:{grow}%'>{escape(value or '')}&nbsp;</td>"
    )


def _ruled(count: int, first: str | None = None) -> str:
    lines = [f"<div class='ruled'>{escape(first)}</div>"] if first else []
    lines += ["<div class='ruled'>&nbsp;</div>"] * (count - len(lines))
    return "".join(lines)


def _signature_row(caption: str, *, above: str = "", on_date: str = "", date_label: str) -> str:
    return f"""
  <table class="sign"><tr>
    <td class="who"><div class="hand">{above}</div><div class="cap">{caption}</div></td>
    <td class="gap"></td>
    <td class="when"><div class="hand">{on_date}</div><div class="cap">{date_label}<br>&nbsp;</div></td>
  </tr></table>"""


def _render_html(
    consent: Consent, clinic: Clinic | None, patient: Patient, locale: str, letterhead: str
) -> str:
    labels = _LABELS.get(locale, _LABELS["es"])
    informed = consent.kind == "informed"
    today = _local_date(consent.created_at, clinic) or date.today()
    signed_on = _local_date(consent.signed_at, clinic)
    # Only a signature drawn on screen can be printed back. One made on
    # paper is on the scan; this sheet stays the blank form it was.
    on_screen = consent.signature_method == "screen" and signed_on is not None

    # --- Under the clinic's letterhead: who informs.
    informs = ""
    if consent.explained_by_name:
        informs = escape(consent.explained_by_name)
        if consent.explained_by_license:
            informs += f" · {labels['license']} {escape(consent.explained_by_license)}"

    # --- The patient, as the record has them.
    patient_block = f"""
  <table class="fields"><tr>
    {_field(labels["last_name"], patient.last_name, 38)}
    {_field(labels["first_name"], patient.first_name, 32)}
    {_field(labels["age"], _age(patient.date_of_birth, signed_on or today), 6)}
  </tr></table>
  <table class="fields"><tr>{_field(labels["address"], _address(patient.address), 88)}</tr></table>
  <table class="fields"><tr>
    {_field(labels["phone"], patient.phone, 30)}<td style="width:60%"></td>
  </tr></table>"""

    # --- What is being consented to. Filled in by hand on the sheet.
    clinical_block = ""
    if informed:
        clinical_block = f"""
  <table class="fields dx"><tr>
    <td class="k lead">{labels["diagnosis"]}:</td><td class="line" style="width:90%">&nbsp;</td>
  </tr></table>
  {_ruled(_DIAGNOSIS_LINES - 1)}
  <h2>{labels["plan"]}</h2>
  {_ruled(_PLAN_LINES, consent.procedure_label)}"""

    # --- Signatures.
    place = escape((clinic.address or {}).get("city") or "") if clinic else ""
    date_text = signed_on.strftime("%d/%m/%Y") if on_screen else ""
    patient_above = ""
    if on_screen:
        png = (consent.signature_data or {}).get("png") or ""
        image = f"<img src='{escape(png)}' alt=''>" if png.startswith("data:image/") else ""
        capacity = labels["capacity"].get(consent.signer_capacity or "patient", "")
        patient_above = f"{image}<div>{escape(consent.signed_by_name or '')} ({capacity})</div>"

    rows = [
        _signature_row(
            f"{labels['patient_signature']}<br>{labels['accepts']}",
            above=patient_above,
            on_date=date_text,
            date_label=labels["date"],
        )
    ]
    if informed:
        professional = escape(consent.explained_by_name or "")
        if consent.explained_by_license:
            professional += f" · {labels['license']} {escape(consent.explained_by_license)}"
        rows.append(
            _signature_row(
                f"{labels['professional_signature']}<br>{professional}",
                on_date=date_text,
                date_label=labels["date"],
            )
        )
        witness = f"<td class='half'><div class='hand'></div><div class='cap'>{labels['witness']}</div></td>"
        rows.append(f"<table class='sign'><tr>{witness}<td class='gap'></td>{witness}</tr></table>")

    # --- What became of it, when that is not "signed".
    outcome = ""
    for status, moment in (("revoked", consent.revoked_at), ("declined", consent.declined_at)):
        if consent.status == status and moment is not None:
            when = _local_date(moment, clinic)
            outcome = f"<div class='outcome'>{labels[status]} {when:%d/%m/%Y}</div>"

    version = (
        f" · {labels['version']}{consent.template_version}" if consent.template_version else ""
    )

    # --- The regulation the record is kept under. A signed letter keeps the
    #     one it named that day; a sheet still to sign names today's.
    if consent.signed_at is not None:
        regulation = consent.regulation
    else:
        regulation = record_regulation(clinic) if clinic is not None else None
    regulation_line = (
        f"<p class='regulation'>{labels['regulation']}: {escape(regulation)}</p>"
        if regulation
        else ""
    )

    return f"""<!DOCTYPE html>
<html lang="{escape(locale)}">
<head>
<meta charset="utf-8">
<title>{escape(consent.title)}</title>
<style>
  @page {{ size: letter; margin: 18mm 22mm 16mm;
           @bottom-left {{ content: "{labels["folio"]} {consent.id.hex[:8].upper()}{version}";
                           font-size: 8pt; color: #555; }}
           @bottom-right {{ content: counter(page); font-size: 9pt; }} }}
  body {{ font-family: "Helvetica Neue", Arial, sans-serif; font-size: 10.5pt; color: #000; }}
{LETTERHEAD_CSS}
  .informs {{ font-weight: 700; font-style: italic; font-size: 9.5pt; margin: 0 0 10px; }}
  table {{ width: 100%; border-collapse: collapse; }}
  .fields {{ margin-bottom: 9px; }}
  .fields td {{ vertical-align: bottom; padding: 0; }}
  .k {{ white-space: nowrap; padding-right: 4px !important; width: 1%; }}
  .line {{ border-bottom: 0.8pt solid #000; padding: 0 4px 1px !important; }}
  .rule {{ border-top: 1.5pt solid #000; margin: 12px 0 14px; }}
  .lead {{ font-weight: 700; font-style: italic; }}
  .dx {{ margin-bottom: 0; }}
  .ruled {{ border-bottom: 0.8pt solid #000; height: 6.8mm; line-height: 6.8mm;
            padding: 0 4px; overflow: hidden; }}
  h1, h2 {{ text-align: center; font-size: 10.5pt; font-weight: 700; font-style: italic;
            text-transform: uppercase; }}
  h2 {{ margin: 14px 0 0; }}
  h1 {{ margin: 16px 0 8px; }}
  .body {{ white-space: pre-wrap; text-align: justify; font-style: italic; line-height: 1.45; }}
  .place {{ margin-top: 12px; }}
  .sign {{ margin-top: 6mm; break-inside: avoid; }}
  .sign td {{ vertical-align: bottom; padding: 0; }}
  .who {{ width: 56%; }} .gap {{ width: 10%; }} .when {{ width: 34%; }}
  .half {{ width: 45%; }}
  .hand {{ min-height: 9mm; text-align: center; border-bottom: 0.8pt solid #000;
           padding-bottom: 1px; }}
  .hand img {{ height: 16mm; display: block; margin: 0 auto; }}
  .cap {{ text-align: center; font-weight: 700; font-style: italic; font-size: 9.5pt;
          padding-top: 2px; }}
  .outcome {{ margin-top: 10px; font-weight: 700; text-align: right; }}
  .regulation {{ margin: 10px 0 0; font-size: 8.5pt; color: #333; }}
</style>
</head>
<body>
  {letterhead}
  <div class="informs">{informs}</div>
  {patient_block}
  <div class="rule"></div>
  {clinical_block}
  <h1>{escape(consent.title)}</h1>
  <div class="body">{escape(consent.body)}</div>
  <table class="fields place"><tr>
    {_field(labels["place_date"], f"{place}{', ' + date_text if date_text else ''}", 60)}
    <td style="width:25%"></td>
  </tr></table>
  {regulation_line}
  {"".join(rows)}
  {outcome}
</body>
</html>"""
