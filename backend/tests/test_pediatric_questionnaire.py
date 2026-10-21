"""The pediatric health questionnaire (odontología pediátrica).

What these pin: it is the same dated declaration as the adult one, under its
own form — its questions, its checklist and the data it asks to write; a
parent, guardian or representative signs it, never the child; on paper it
is printed blank with the guardian's consent at the foot; and it reaches the
clinical record saying which form it was.
"""

import pytest
from httpx import AsyncClient

from app.modules.patients.models import Patient
from app.modules.patients_clinical.questionnaire import (
    FORMS,
    PEDIATRIC_CONDITION_GROUPS,
    PEDIATRIC_FIELD_GROUPS,
    PEDIATRIC_QUESTION_GROUPS,
    PEDIATRIC_QUESTIONS,
)

PNG = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR4nGNgYGBgAAAABQABh6FO1AAAAABJRU5ErkJggg=="

ANSWERED = {
    "form_kind": "pediatric",
    "signature": {"png": PNG, "signed_by_name": "María López", "signer_capacity": "guardian"},
    "chief_complaint": "Revisión y dolor en una muela",
    "form_data": {
        "school": "Primaria Benito Juárez",
        "weight": "28 kg",
        "guardian_name": " María López ",
    },
    "answers": {
        "thumb_sucking": {"answer": True},
        "allergic": {"answer": True, "detail": "Penicilina"},
        "prior_dental_visit": {"answer": False},
    },
    "conditions": ["frequent_throat_infections", "hemophilia"],
}


def _url(patient: Patient) -> str:
    return f"/api/v1/patients_clinical/patients/{patient.id}/questionnaires"


def test_the_pediatric_form_asks_what_the_paper_form_asks() -> None:
    pediatric = FORMS["pediatric"]
    assert pediatric.questions == PEDIATRIC_QUESTIONS
    assert (
        len(PEDIATRIC_QUESTIONS)
        == len(set(PEDIATRIC_QUESTIONS))
        == sum(len(group) for group in PEDIATRIC_QUESTION_GROUPS.values())
    )
    assert pediatric.conditions == frozenset(PEDIATRIC_CONDITION_GROUPS["pediatric"])
    assert set(pediatric.fields) == {k for g in PEDIATRIC_FIELD_GROUPS.values() for k in g}
    # The adult form asks to write nothing beyond its own columns.
    assert FORMS["adult"].fields == ()


@pytest.mark.asyncio
async def test_a_guardian_answers_and_signs_it_for_the_child(
    client: AsyncClient, auth_headers: dict, test_patient: Patient
) -> None:
    made = await client.post(_url(test_patient), headers=auth_headers, json=ANSWERED)
    assert made.status_code == 201, made.text
    saved = made.json()["data"]
    assert saved["form_kind"] == "pediatric"
    assert saved["form_data"]["guardian_name"] == "María López"  # trimmed
    assert saved["conditions"] == ["hemophilia", "frequent_throat_infections"]  # the form's order
    assert saved["signer_capacity"] == "guardian"

    listed = await client.get(_url(test_patient), headers=auth_headers)
    assert listed.json()["data"][0]["form_kind"] == "pediatric"

    record = await client.get(f"/api/v1/record/patients/{test_patient.id}", headers=auth_headers)
    sections = {(s["module"], s["name"]): s for s in record.json()["data"]["sections"]}
    [entry] = sections[("patients_clinical", "health_questionnaires")]["entries"]
    assert entry["detail"]["form_kind"] == "pediatric"
    assert {"field": "school", "value": "Primaria Benito Juárez"} in entry["detail"]["form_data"]
    assert {"question": "allergic", "detail": "Penicilina"} in entry["detail"][
        "affirmative_answers"
    ]


@pytest.mark.asyncio
async def test_the_child_does_not_sign_it(
    client: AsyncClient, auth_headers: dict, test_patient: Patient
) -> None:
    body = {**ANSWERED, "signature": {**ANSWERED["signature"], "signer_capacity": "patient"}}
    refused = await client.post(_url(test_patient), headers=auth_headers, json=body)
    assert refused.status_code in (400, 422)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "change",
    [
        # An adult question on the pediatric form.
        {"answers": {"pregnant": {"answer": False}}},
        # A pediatric question on the adult form.
        {"form_kind": "adult", "form_data": {}, "answers": {"thumb_sucking": {"answer": True}}},
        # A field the form does not ask for, and the adult form asks for none.
        {"form_data": {"favourite_toy": "pelota"}},
        {"form_kind": "adult", "answers": {}, "conditions": [], "form_data": {"school": "X"}},
        # A form nobody defined.
        {"form_kind": "geriatric"},
    ],
)
async def test_each_form_takes_only_what_it_asks(
    client: AsyncClient, auth_headers: dict, test_patient: Patient, change: dict
) -> None:
    refused = await client.post(
        _url(test_patient), headers=auth_headers, json={**ANSWERED, **change}
    )
    assert refused.status_code in (400, 422), refused.text


@pytest.mark.asyncio
async def test_the_blank_pediatric_form_prints(
    client: AsyncClient, auth_headers: dict, test_patient: Patient
) -> None:
    for locale in ("es", "en"):
        form = await client.get(
            f"/api/v1/patients_clinical/patients/{test_patient.id}/questionnaire-form",
            params={"locale": locale, "kind": "pediatric"},
            headers=auth_headers,
        )
        assert form.status_code == 200, form.text
        assert form.content.startswith(b"%PDF")
        assert "cuestionario_pediatrico.pdf" in form.headers["content-disposition"]


def test_the_pediatric_sheet_closes_with_the_guardians_consent() -> None:
    from app.modules.patients_clinical.questionnaire_pdf import render_pediatric_html

    patient = Patient(first_name="Leo", last_name="Gil", gender="male", address={"city": "Puebla"})
    html = render_pediatric_html(patient, "es", "", "NOM-004-SSA3-2012")
    assert "Odontología pediátrica" in html
    assert "autorizo la exploración" in html
    assert "Nombre y firma del padre, madre o tutor" in html
    assert "Masculino" in html and "Puebla" in html
    assert "Succión del dedo" in html and "Hemofilia" in html
