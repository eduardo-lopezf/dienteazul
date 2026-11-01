"""The operator's notices to clinics: written through ``/api/v1/ops``,
read by each clinic's members at ``GET /api/v1/announcements`` — only the
ones in force, and only those meant for that clinic."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from httpx import AsyncClient

from app.config import settings
from app.core.auth.models import Clinic

from .test_ops_endpoint import SECRET, _token


@pytest.fixture
def ops_enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "CONTROL_PLANE_SECRET", SECRET)


async def _publish(client: AsyncClient, **notice) -> dict:
    body = {"kind": "maintenance", "message": "Mantenimiento el domingo"} | notice
    response = await client.post("/api/v1/ops/announcements", json=body, headers=_token())
    assert response.status_code == 201, response.text
    return response.json()["data"]


async def _seen(client: AsyncClient, headers: dict[str, str]) -> list[str]:
    response = await client.get("/api/v1/announcements", headers=headers)
    assert response.status_code == 200, response.text
    return [a["message"] for a in response.json()["data"]]


def _at(**delta: float) -> str:
    return (datetime.now(UTC) + timedelta(**delta)).isoformat()


async def test_only_the_control_plane_publishes(
    client: AsyncClient, ops_enabled: None, test_clinic: Clinic, auth_headers: dict[str, str]
) -> None:
    body = {"kind": "feature", "message": "Nuevo"}
    response = await client.post("/api/v1/ops/announcements", json=body, headers=auth_headers)
    assert response.status_code == 401


async def test_a_clinic_sees_the_notices_in_force_for_it(
    client: AsyncClient, ops_enabled: None, test_clinic: Clinic, auth_headers: dict[str, str]
) -> None:
    await _publish(client, message="Para todas")
    await _publish(
        client, kind="feature", message="Solo para esta", clinic_ids=[str(test_clinic.id)]
    )
    await _publish(client, message="Para otra", clinic_ids=[str(uuid4())])
    scheduled = await _publish(client, message="Todavía no", starts_at=_at(hours=1))
    await _publish(client, message="Ya pasó", starts_at=_at(hours=-2), ends_at=_at(hours=-1))

    assert set(await _seen(client, auth_headers)) == {"Para todas", "Solo para esta"}

    listed = await client.get("/api/v1/ops/announcements", headers=_token())
    statuses = {a["message"]: a["status"] for a in listed.json()["data"]}
    assert statuses == {
        "Para todas": "active",
        "Solo para esta": "active",
        "Para otra": "active",
        "Todavía no": "scheduled",
        "Ya pasó": "ended",
    }
    assert scheduled["status"] == "scheduled"


async def test_a_notice_is_changed_and_taken_down(
    client: AsyncClient, ops_enabled: None, test_clinic: Clinic, auth_headers: dict[str, str]
) -> None:
    notice = await _publish(client)
    url = f"/api/v1/ops/announcements/{notice['id']}"

    changed = await client.put(
        url, json={"kind": "feature", "message": "  Ahora hay recordatorios  "}, headers=_token()
    )
    assert changed.status_code == 200, changed.text
    assert await _seen(client, auth_headers) == ["Ahora hay recordatorios"]

    assert (await client.delete(url, headers=_token())).status_code == 204
    assert await _seen(client, auth_headers) == []
    assert (await client.delete(url, headers=_token())).status_code == 404


@pytest.mark.parametrize(
    "body",
    [
        {"kind": "maintenance", "message": "   "},
        {"kind": "outage", "message": "Caída"},
        {"kind": "feature", "message": "x" * 281},
    ],
    ids=["empty", "unknown kind", "too long"],
)
async def test_a_notice_that_cannot_be_shown_is_refused(
    client: AsyncClient, ops_enabled: None, body: dict
) -> None:
    response = await client.post("/api/v1/ops/announcements", json=body, headers=_token())
    assert response.status_code == 422


async def test_a_notice_cannot_end_before_it_starts(client: AsyncClient, ops_enabled: None) -> None:
    body = {
        "kind": "feature",
        "message": "Al revés",
        "starts_at": _at(hours=2),
        "ends_at": _at(hours=1),
    }
    response = await client.post("/api/v1/ops/announcements", json=body, headers=_token())
    assert response.status_code == 422


# --- Surveys ---------------------------------------------------------------
#
# A notice can be a questionnaire: a title for the banner and up to ten
# questions, each a yes/no the member may explain or a question answered
# in prose. The operator reads the counts and what people wrote; never
# who wrote what.


QUALITY = {
    "kind": "survey",
    "title": "Encuesta de Calidad",
    "message": "Cuéntanos cómo te va con el programa.",
    "questions": [
        {"kind": "yes_no", "text": "¿El programa te resulta fácil de usar en tu día a día?"},
        {"kind": "yes_no", "text": "¿El programa va suficientemente rápido?"},
        {"kind": "open", "text": "¿Qué nueva característica o mejora propondrías?"},
    ],
}


async def _survey(client: AsyncClient, **over) -> dict:
    return await _publish(client, **(QUALITY | over))


async def _answer(client: AsyncClient, survey: dict, answers: list[dict], headers: dict) -> int:
    response = await client.put(
        f"/api/v1/announcements/{survey['id']}/answers",
        json={"answers": answers},
        headers=headers,
    )
    return response.status_code


async def _result(client: AsyncClient, survey: dict) -> dict:
    response = await client.get(
        f"/api/v1/ops/announcements/{survey['id']}/responses", headers=_token()
    )
    assert response.status_code == 200, response.text
    return response.json()["data"]


async def _seen_survey(client: AsyncClient, headers: dict) -> dict:
    listed = (await client.get("/api/v1/announcements", headers=headers)).json()["data"]
    return next(a for a in listed if a["kind"] == "survey")


async def test_the_clinic_reads_the_questionnaire_and_answers_it(
    client: AsyncClient, ops_enabled: None, test_clinic: Clinic, auth_headers: dict[str, str]
) -> None:
    survey = await _survey(client)
    assert [q["kind"] for q in survey["questions"]] == ["yes_no", "yes_no", "open"]
    # Every question carries an id of its own, minted here.
    assert len({q["id"] for q in survey["questions"]}) == 3

    seen = await _seen_survey(client, auth_headers)
    assert seen["title"] == "Encuesta de Calidad"
    assert seen["answers"] == []
    easy, fast, idea = (q["id"] for q in seen["questions"])

    assert (
        await _answer(
            client,
            survey,
            [
                {"question_id": easy, "yes": True},
                {"question_id": fast, "yes": False, "comment": "El odontograma tarda"},
                {"question_id": idea, "comment": "Avisos por WhatsApp"},
            ],
            auth_headers,
        )
        == 204
    )

    # The questionnaire reopens on what they said.
    answers = {a["question_id"]: a for a in (await _seen_survey(client, auth_headers))["answers"]}
    assert answers[easy]["yes"] is True
    assert answers[fast]["comment"] == "El odontograma tarda"

    result = await _result(client, survey)
    assert result["title"] == "Encuesta de Calidad"
    assert result["respondents"] == 1
    by_id = {q["id"]: q for q in result["questions"]}
    assert (by_id[easy]["yes"], by_id[easy]["no"]) == (1, 0)
    assert (by_id[fast]["yes"], by_id[fast]["no"]) == (0, 1)
    assert [c["text"] for c in by_id[fast]["comments"]] == ["El odontograma tarda"]
    assert [c["text"] for c in by_id[idea]["comments"]] == ["Avisos por WhatsApp"]
    assert [c["clinic_name"] for c in by_id[idea]["comments"]] == ["Test Clinic"]
    assert result["clinics"] == [
        {
            "clinic_id": str(test_clinic.id),
            "clinic_name": "Test Clinic",
            "respondents": 1,
        }
    ]


async def test_a_half_filled_survey_is_half_answered(
    client: AsyncClient, ops_enabled: None, test_clinic: Clinic, auth_headers: dict[str, str]
) -> None:
    """Every question is optional: a questionnaire that refuses to be sent
    until all ten are filled in is one busy people abandon."""
    survey = await _survey(client)
    easy = survey["questions"][0]["id"]

    assert await _answer(client, survey, [{"question_id": easy, "yes": True}], auth_headers) == 204

    result = await _result(client, survey)
    assert result["respondents"] == 1
    by_id = {q["id"]: q for q in result["questions"]}
    assert by_id[easy]["yes"] == 1
    # The ones left alone stayed unanswered rather than counting as a no.
    assert [(q["yes"], q["no"]) for q in result["questions"][1:]] == [(0, 0), (0, 0)]


async def test_sending_it_again_corrects_instead_of_counting_twice(
    client: AsyncClient, ops_enabled: None, test_clinic: Clinic, auth_headers: dict[str, str]
) -> None:
    survey = await _survey(client)
    easy = survey["questions"][0]["id"]

    await _answer(client, survey, [{"question_id": easy, "yes": True}], auth_headers)
    await _answer(
        client,
        survey,
        [{"question_id": easy, "yes": False, "comment": "Me retracto"}],
        auth_headers,
    )

    result = await _result(client, survey)
    assert result["respondents"] == 1
    by_id = {q["id"]: q for q in result["questions"]}
    assert (by_id[easy]["yes"], by_id[easy]["no"]) == (0, 1)
    assert [c["text"] for c in by_id[easy]["comments"]] == ["Me retracto"]


async def test_clearing_an_answer_removes_it(
    client: AsyncClient, ops_enabled: None, test_clinic: Clinic, auth_headers: dict[str, str]
) -> None:
    """An answer with neither a yes nor words is one nobody gave."""
    survey = await _survey(client)
    easy = survey["questions"][0]["id"]

    await _answer(client, survey, [{"question_id": easy, "yes": True}], auth_headers)
    await _answer(client, survey, [{"question_id": easy}], auth_headers)

    result = await _result(client, survey)
    assert result["respondents"] == 0
    assert (result["questions"][0]["yes"], result["questions"][0]["no"]) == (0, 0)


async def test_editing_a_survey_keeps_the_answers_on_their_question(
    client: AsyncClient, ops_enabled: None, test_clinic: Clinic, auth_headers: dict[str, str]
) -> None:
    """The reason question ids exist.

    Recording positions, as the first version did, meant that reordering
    a published survey moved every answer to its neighbour.
    """
    survey = await _survey(client)
    easy, fast, idea = (q["id"] for q in survey["questions"])
    await _answer(client, survey, [{"question_id": fast, "yes": False}], auth_headers)

    # The operator reorders and corrects a typo, echoing the ids back.
    reordered = await client.put(
        f"/api/v1/ops/announcements/{survey['id']}",
        json=QUALITY
        | {
            "questions": [
                {"id": idea, "kind": "open", "text": "¿Qué nueva característica propondrías?"},
                {"id": fast, "kind": "yes_no", "text": "¿El programa va bastante rápido?"},
                {"id": easy, "kind": "yes_no", "text": "¿Es fácil de usar?"},
            ]
        },
        headers=_token(),
    )
    assert reordered.status_code == 200, reordered.text
    assert [q["id"] for q in reordered.json()["data"]["questions"]] == [idea, fast, easy]

    by_id = {q["id"]: q for q in (await _result(client, survey))["questions"]}
    assert (by_id[fast]["yes"], by_id[fast]["no"]) == (0, 1)
    assert (by_id[easy]["yes"], by_id[easy]["no"]) == (0, 0)


async def test_an_open_question_takes_no_yes_or_no(
    client: AsyncClient, ops_enabled: None, test_clinic: Clinic, auth_headers: dict[str, str]
) -> None:
    survey = await _survey(client)
    idea = survey["questions"][2]["id"]
    assert await _answer(client, survey, [{"question_id": idea, "yes": True}], auth_headers) == 422


async def test_a_question_the_survey_does_not_ask_is_refused(
    client: AsyncClient, ops_enabled: None, test_clinic: Clinic, auth_headers: dict[str, str]
) -> None:
    survey = await _survey(client)
    assert (
        await _answer(client, survey, [{"question_id": "nope", "yes": True}], auth_headers) == 422
    )


async def test_only_a_survey_in_force_for_the_clinic_is_answered(
    client: AsyncClient, ops_enabled: None, test_clinic: Clinic, auth_headers: dict[str, str]
) -> None:
    elsewhere = await _survey(client, message="Para otra", clinic_ids=[str(uuid4())])
    over = await _survey(client, message="Ya pasó", starts_at=_at(hours=-2), ends_at=_at(hours=-1))
    notice = await _publish(client, message="No es una encuesta")

    for target in (elsewhere, over):
        answer = [{"question_id": target["questions"][0]["id"], "yes": True}]
        assert await _answer(client, target, answer, auth_headers) == 404
    assert await _answer(client, notice, [{"question_id": "x", "yes": True}], auth_headers) == 404


async def test_the_operator_empties_the_result_and_keeps_the_survey(
    client: AsyncClient, ops_enabled: None, test_clinic: Clinic, auth_headers: dict[str, str]
) -> None:
    survey = await _survey(client)
    easy = survey["questions"][0]["id"]
    await _answer(client, survey, [{"question_id": easy, "yes": True}], auth_headers)
    assert (await _result(client, survey))["respondents"] == 1

    cleared = await client.delete(
        f"/api/v1/ops/announcements/{survey['id']}/responses", headers=_token()
    )
    assert cleared.status_code == 204

    emptied = await _result(client, survey)
    assert emptied["respondents"] == 0
    assert emptied["clinics"] == []
    # The survey itself is untouched, and may be answered again.
    assert [q["id"] for q in emptied["questions"]] == [q["id"] for q in survey["questions"]]
    assert await _answer(client, survey, [{"question_id": easy, "yes": False}], auth_headers) == 204
    assert (await _result(client, survey))["respondents"] == 1


async def test_the_list_counts_people_not_answers(
    client: AsyncClient, ops_enabled: None, test_clinic: Clinic, auth_headers: dict[str, str]
) -> None:
    survey = await _survey(client)
    await _answer(
        client,
        survey,
        [{"question_id": q["id"], "yes": True} for q in survey["questions"][:2]],
        auth_headers,
    )

    listed = (await client.get("/api/v1/ops/announcements", headers=_token())).json()["data"]
    assert [a["responses"] for a in listed] == [1]


@pytest.mark.parametrize(
    "body",
    [
        QUALITY | {"questions": []},
        QUALITY | {"title": "   "},
        {k: v for k, v in QUALITY.items() if k != "title"},
        QUALITY | {"questions": [{"kind": "yes_no", "text": "  "}]},
        QUALITY | {"questions": [{"kind": "maybe", "text": "¿?"}]},
        QUALITY | {"questions": [{"kind": "yes_no", "text": "x" * 201}]},
        QUALITY | {"questions": [{"kind": "yes_no", "text": f"¿Pregunta {i}?"} for i in range(11)]},
        QUALITY | {"questions": [{"kind": "yes_no", "text": "¿Igual?"}] * 2},
        {"kind": "feature", "message": "Novedad", "questions": [{"kind": "open", "text": "¿?"}]},
        {"kind": "feature", "message": "Novedad", "title": "No le toca"},
    ],
    ids=[
        "no questions",
        "blank title",
        "no title",
        "empty question",
        "unknown question kind",
        "question too long",
        "eleven questions",
        "two questions the same",
        "questions on something that is not a survey",
        "title on something that is not a survey",
    ],
)
async def test_a_survey_that_cannot_be_answered_is_refused(
    client: AsyncClient, ops_enabled: None, body: dict
) -> None:
    response = await client.post("/api/v1/ops/announcements", json=body, headers=_token())
    assert response.status_code == 422, response.text


async def test_the_result_of_a_notice_that_asks_nothing_is_refused(
    client: AsyncClient, ops_enabled: None
) -> None:
    notice = await _publish(client)
    response = await client.get(
        f"/api/v1/ops/announcements/{notice['id']}/responses", headers=_token()
    )
    assert response.status_code == 409


async def test_taking_a_survey_down_takes_its_answers_with_it(
    client: AsyncClient, ops_enabled: None, test_clinic: Clinic, auth_headers: dict[str, str]
) -> None:
    survey = await _survey(client)
    await _answer(
        client, survey, [{"question_id": survey["questions"][0]["id"], "yes": True}], auth_headers
    )

    url = f"/api/v1/ops/announcements/{survey['id']}"
    assert (await client.delete(url, headers=_token())).status_code == 204
    assert (await client.get(f"{url}/responses", headers=_token())).status_code == 404
