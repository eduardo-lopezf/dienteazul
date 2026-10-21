"""Copy the record's wording from the screen to the printed document.

The *Expediente* tab and the PDF a disclosure produces say the same thing
in the same words. The words live in the frontend locales; the PDF is
rendered by the backend, which cannot read them at run time. This writes
the copies it uses:

- ``backend/app/modules/record/labels.json`` — the record's PDF.
- ``backend/app/modules/patients_clinical/questionnaire_labels.json`` —
  the blank health questionnaire.

Run it **from the host**, after touching the ``record`` block of
``frontend/i18n/locales/*.json`` or any translation a coded value borrows:

    python backend/scripts/generate_record_labels.py
"""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TARGET = ROOT / "backend/app/modules/record/labels.json"
QUESTIONNAIRE_TARGET = ROOT / "backend/app/modules/patients_clinical/questionnaire_labels.json"

#: Where a coded value is already translated — the same table as
#: ``recordFormat.ts``. The first prefix wins, as on the screen.
VALUE_KEYS: dict[str, list[str]] = {
    "type": ["patients.medicalHistory.allergyTypes", "patients.medicalHistory.diseaseTypes"],
    "severity": ["patients.medicalHistory.severity"],
    "alcohol_consumption": ["patients.medicalHistory.alcohol"],
    "gender": ["patients.gender"],
    "clinical_type": ["odontogram.treatments.types"],
    "status": ["treatmentPlans.status", "consents.status"],
    "closure_reason": ["treatmentPlans.closureReason"],
    "kind": ["consents.kinds"],
    "signer_capacity": ["consents.capacity"],
    "relative": ["patients.medicalHistory.relatives"],
    "prognosis": ["treatmentPlans.prognosis"],
}


def _labels(locale: dict) -> dict:
    def at(path: str) -> dict:
        node = locale
        for part in path.split("."):
            node = node[part]
        return node

    record = locale["record"]
    values: dict[str, dict[str, str]] = {
        # The questionnaire's own keys, so the record can name what was ticked.
        "declared_conditions": locale["healthQuestionnaire"]["conditions"],
        "question": locale["healthQuestionnaire"]["questions"],
        "form_kind": locale["healthQuestionnaire"]["forms"],
        "form_field": locale["healthQuestionnaire"]["pediatric"]["fields"],
    }
    for key, prefixes in VALUE_KEYS.items():
        merged: dict[str, str] = {}
        for prefix in reversed(prefixes):
            merged.update({k: v for k, v in at(prefix).items() if isinstance(v, str)})
        values[key] = merged
    for key, own in record["value"].items():
        values.setdefault(key, {}).update(own)
    return {
        "section": {f"record.section.{name}": title for name, title in record["section"].items()},
        "field": record["field"],
        "value": values,
        "status": record["status"],
        "yes": locale["common"]["yes"],
        "no": locale["common"]["no"],
    }


def _write(target: Path, content: dict) -> None:
    target.write_text(json.dumps(content, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    print(f"Wrote {target.relative_to(ROOT)}")


def main() -> None:
    locales = {
        lang: json.loads((ROOT / f"frontend/i18n/locales/{lang}.json").read_text())
        for lang in ("es", "en")
    }
    _write(TARGET, {lang: _labels(locale) for lang, locale in locales.items()})
    _write(
        QUESTIONNAIRE_TARGET,
        {lang: locale["healthQuestionnaire"] for lang, locale in locales.items()},
    )


if __name__ == "__main__":
    main()
