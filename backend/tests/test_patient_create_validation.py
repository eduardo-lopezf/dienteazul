"""Field validation on ``PatientCreate`` (the body of ``POST /patients``)."""

from datetime import date, timedelta

import pytest
from pydantic import ValidationError

from app.modules.patients.schemas import PatientCreate


def _create(**overrides) -> PatientCreate:
    data = {"first_name": "Ana", "last_name": "García"} | overrides
    return PatientCreate(**data)


def test_minimal_patient_is_valid() -> None:
    patient = _create()
    assert patient.phone is None
    assert patient.email is None


@pytest.mark.parametrize("name", ["María José", "O'Connor", "Pérez-Núñez", "Jr."])
def test_names_accept_letters_and_common_punctuation(name: str) -> None:
    assert _create(first_name=name).first_name == name


def test_names_are_trimmed() -> None:
    assert _create(last_name="  García ").last_name == "García"


@pytest.mark.parametrize("name", ["", "   ", "Ana2", "Ana@", "<b>"])
@pytest.mark.parametrize("field", ["first_name", "last_name"])
def test_names_reject_blank_or_invalid(field: str, name: str) -> None:
    with pytest.raises(ValidationError):
        _create(**{field: name})


@pytest.mark.parametrize("field", ["phone", "email", "notes"])
@pytest.mark.parametrize("value", ["", "   ", None])
def test_empty_optional_fields_skip_validation(field: str, value: str | None) -> None:
    assert getattr(_create(**{field: value}), field) is None


@pytest.mark.parametrize(
    "phone", ["612345678", "+34 612 345 678", "(55) 1234-5678", "612.34.56.78"]
)
def test_phone_accepts_common_formats(phone: str) -> None:
    assert _create(phone=phone).phone == phone


@pytest.mark.parametrize("phone", ["12345", "abc1234567", "+34 612 abc 678", "++34612345678"])
def test_phone_rejects_invalid(phone: str) -> None:
    with pytest.raises(ValidationError):
        _create(phone=phone)


def test_email_rejects_invalid() -> None:
    with pytest.raises(ValidationError):
        _create(email="not-an-email")


def test_email_accepts_valid() -> None:
    assert _create(email="ana@example.com").email == "ana@example.com"


def test_date_of_birth_rejects_future() -> None:
    with pytest.raises(ValidationError):
        _create(date_of_birth=date.today() + timedelta(days=1))


def test_date_of_birth_rejects_implausibly_old() -> None:
    with pytest.raises(ValidationError):
        _create(date_of_birth=date(1800, 1, 1))


def test_date_of_birth_accepts_today_and_past() -> None:
    assert _create(date_of_birth=date.today()).date_of_birth == date.today()
    assert _create(date_of_birth=date(1980, 5, 17)).date_of_birth == date(1980, 5, 17)


def test_notes_have_a_maximum_length() -> None:
    with pytest.raises(ValidationError):
        _create(notes="x" * 5001)
