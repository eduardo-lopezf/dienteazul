"""Every failure says what class it is and which request it was.

The defect this closes was a report, not a crash: a clinic hit "Error del
servidor" while adding a patient and there was nothing to go on — the
message is deliberately vague outside development because it can quote
patient data, and nothing else reached the screen. The log line and the
``ServerError`` row existed all along; what was missing was the string
that leads to them.

So the envelope carries three things (``app/core/errors.py``):
``category`` for the interface to branch on, ``code`` for whoever debugs,
and ``reference`` — this request's id — for the person to quote.
"""

from __future__ import annotations

import pytest
from fastapi import status
from httpx import AsyncClient

from app.core.errors import ErrorCategory, category_for_status
from app.modules.agenda.errors import ERROR_CATALOG as AGENDA_ERROR_CATALOG
from app.modules.patients.errors import ERROR_CATALOG
from app.modules.patients_clinical.errors import ERROR_CATALOG as PATIENTS_CLINICAL_ERROR_CATALOG


@pytest.mark.asyncio
async def test_a_claimed_failure_names_its_case(
    client: AsyncClient, auth_headers: dict[str, str], test_clinic
) -> None:
    """A patient that is not there is one case, and it says so."""
    response = await client.get(
        "/api/v1/patients/01a16023-0000-0000-0000-000000000000", headers=auth_headers
    )

    assert response.status_code == status.HTTP_404_NOT_FOUND
    body = response.json()
    definition = ERROR_CATALOG["patients.patient.not_found"]
    assert body["code"] == definition.code
    assert body["category"] == definition.category.value
    assert body["message"] == definition.message
    assert response.status_code == definition.status_code


@pytest.mark.asyncio
@pytest.mark.parametrize("sort", ["last_visit:sideways", "unknown_field:asc"])
async def test_invalid_patient_sort_uses_the_error_catalog(
    client: AsyncClient, auth_headers: dict[str, str], test_clinic, sort: str
) -> None:
    response = await client.get("/api/v1/patients", headers=auth_headers, params={"sort": sort})

    definition = ERROR_CATALOG["patients.patient.invalid_sort"]
    body = response.json()
    assert response.status_code == definition.status_code
    assert body["code"] == definition.code
    assert body["category"] == definition.category.value
    assert body["message"] == definition.message
    assert body["reference"] == response.headers["x-request-id"]


@pytest.mark.asyncio
async def test_missing_appointment_uses_the_agenda_error_catalog(
    client: AsyncClient, auth_headers: dict[str, str], test_clinic
) -> None:
    response = await client.get(
        "/api/v1/agenda/appointments/00000000-0000-0000-0000-000000000000",
        headers=auth_headers,
    )

    definition = AGENDA_ERROR_CATALOG["agenda.appointment.not_found"]
    body = response.json()
    assert response.status_code == definition.status_code
    assert body["code"] == definition.code
    assert body["category"] == definition.category.value
    assert body["message"] == definition.message
    assert body["reference"] == response.headers["x-request-id"]


@pytest.mark.asyncio
async def test_missing_clinical_patient_uses_its_error_catalog(
    client: AsyncClient, auth_headers: dict[str, str], test_clinic
) -> None:
    response = await client.get(
        "/api/v1/patients_clinical/patients/00000000-0000-0000-0000-000000000000/medical-context",
        headers=auth_headers,
    )

    definition = PATIENTS_CLINICAL_ERROR_CATALOG["patients_clinical.patient.not_found"]
    body = response.json()
    assert response.status_code == definition.status_code
    assert body["code"] == definition.code
    assert body["category"] == definition.category.value
    assert body["message"] == definition.message
    assert body["reference"] == response.headers["x-request-id"]


@pytest.mark.asyncio
async def test_the_reference_is_the_request_id(
    client: AsyncClient, auth_headers: dict[str, str], test_clinic
) -> None:
    """The reference has to be the *same* string the logs carry, or it
    leads nowhere. The header is what the browser reads when the body is
    not ours — a gateway's error page — so the two must agree."""
    response = await client.get(
        "/api/v1/patients/01a16023-0000-0000-0000-000000000000", headers=auth_headers
    )

    assert response.json()["reference"] == response.headers["x-request-id"]


@pytest.mark.asyncio
async def test_a_rejected_payload_points_at_the_field(
    client: AsyncClient, auth_headers: dict[str, str], test_clinic
) -> None:
    """422 used to answer in FastAPI's own shape — no reference, and a
    list a form could not match to its inputs."""
    response = await client.post(
        "/api/v1/patients",
        json={"first_name": "A", "last_name": "B", "email": "not-an-email"},
        headers=auth_headers,
    )

    assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY
    body = response.json()
    assert body["category"] == ErrorCategory.VALIDATION.value
    assert body["code"] == "validation.invalid_payload"
    assert "email" in body["fields"]
    assert body["reference"]


@pytest.mark.asyncio
async def test_an_unknown_route_answers_in_the_same_envelope(client: AsyncClient) -> None:
    """The router's own 404 used to be a bare ``{"detail": "Not Found"}``:
    a different shape from everything else and the only failure with no
    reference at all."""
    response = await client.get("/api/v1/there-is-no-such-route")

    assert response.status_code == status.HTTP_404_NOT_FOUND
    body = response.json()
    assert body["category"] == ErrorCategory.NOT_FOUND.value
    assert body["reference"] == response.headers["x-request-id"]
    # Nothing claimed it, so it carries no code — which is how an operator
    # tells "a case we named" from "a URL nobody serves".
    assert body["code"] is None


def test_a_status_without_a_mapping_is_the_callers_to_fix() -> None:
    """The safer half to be wrong about: "look at what you sent" rather
    than "a defect, wait"."""
    assert category_for_status(418) is ErrorCategory.VALIDATION
    assert category_for_status(503) is ErrorCategory.DEPENDENCY
    assert category_for_status(500) is ErrorCategory.INTERNAL
    assert category_for_status(502) is ErrorCategory.INTERNAL
