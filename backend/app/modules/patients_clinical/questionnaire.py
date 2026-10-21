"""The health questionnaire a patient answers at a visit: what is asked.

Two forms: the **adult** one, and the **pediatric** one (odontología
pediátrica) a parent or guardian answers and signs for a child. The
questions, the checklist of conditions and — on the pediatric form — the
data fields, by key. The wording lives
with the screen (``healthQuestionnaire`` in the frontend locales) and is
copied for the printed form by ``scripts/generate_record_labels.py``.

A fixed form, not a per-clinic one: changing a question changes what
earlier answers meant, so a new question is a new key and
``FORM_VERSION`` moves. Stored answers keep the version they were given
under.
"""

from __future__ import annotations

FORM_VERSION = "1"

#: Yes/no questions, in the order they are asked. Any may carry a detail
#: ("cause", "which one").
QUESTIONS: tuple[str, ...] = (
    "medical_care_2y",
    "hospitalized_5y",
    "taking_medication",
    "drug_food_allergy",
    "prior_surgery",
    "anesthesia_reaction",
    "major_bleeding",
    "problem_after_dental_treatment",
    "weight_change_10kg",
    "pregnant",
    "breastfeeding",
    "contraceptive",
)

#: Conditions the patient has or has had, in the blocks the paper form
#: prints them in.
CONDITION_GROUPS: dict[str, tuple[str, ...]] = {
    "cardiovascular": (
        "hypotension",
        "hypertension",
        "heart_failure",
        "angina",
        "myocardial_infarction",
        "rheumatic_fever",
        "tachycardia",
        "bradycardia",
        "pacemaker",
        "arteriosclerosis",
        "atherosclerosis",
        "headache",
        "tinnitus",
        "phosphenes",
        "dizziness",
        "fainting",
        "obesity",
        "overweight",
        "exertional_chest_pain",
        "resting_chest_pain",
        "heart_murmur",
        "evening_leg_edema",
        "cyanosis",
        "bruising",
        "anemia",
        "epistaxis",
        "thrombosis",
        "transfusion",
        "blood_donor",
        "organ_donor",
        "stroke",
        "epigastric_pain",
    ),
    "systemic": (
        "gastric_ulcer",
        "reflux",
        "gastritis",
        "colitis",
        "diabetes",
        "sinusitis",
        "bronchitis",
        "glaucoma",
        "emphysema",
        "tuberculosis",
        "pharyngotonsillitis",
        "digestive_problems",
        "hepatitis",
        "gallbladder",
        "cirrhosis",
        "epilepsy",
        "hyperthyroidism",
        "seizures",
        "alcoholism",
        "smoking",
        "drugs",
        "hypothyroidism",
        "goiter",
        "asthma",
        "gout",
    ),
    "renal_other": (
        "kidney_infection",
        "kidney_stone",
        "dialysis",
        "prostate_problems",
        "cancer",
        "chemotherapy",
        "radiotherapy",
        "bisphosphonates",
        "std",
        "hiv_aids",
    ),
}

CONDITIONS: frozenset[str] = frozenset(key for group in CONDITION_GROUPS.values() for key in group)


# --- The pediatric form (odontología pediátrica) ------------------------
#
# Answered and signed by a parent or guardian. Its own version: it moves
# on its own, and stored answers keep the version they were given under.

PEDIATRIC_FORM_VERSION = "1"

#: Data written on the form rather than answered yes or no, by block.
PEDIATRIC_FIELD_GROUPS: dict[str, tuple[str, ...]] = {
    "child": ("school", "school_grade", "siblings"),
    "family": ("guardian_name", "guardian_occupation", "guardian_phone", "physician_name"),
    "exam": ("weight", "height", "blood_pressure", "temperature", "behavior"),
    "health": ("current_health", "last_physical_exam"),
}

#: Yes/no questions, by block, in the order the form asks them. Any may
#: carry a detail ("which one", "when").
PEDIATRIC_QUESTION_GROUPS: dict[str, tuple[str, ...]] = {
    "dental": ("prior_dental_visit", "bad_dental_experience", "plays_sport"),
    "habits": (
        "thumb_sucking",
        "nail_biting",
        "lip_biting",
        "mouth_breathing",
        "teeth_grinding",
        "frequent_headache",
    ),
    "medical": (
        "current_illness",
        "taking_medication",
        "head_face_accident",
        "allergic",
        "tonsillectomy",
        "adenoidectomy",
    ),
    "history": (
        "prolonged_illness",
        "receives_medical_care",
        "prior_surgery",
        "prior_dental_treatment",
        "anesthetized",
        "anesthesia_reaction",
    ),
}

PEDIATRIC_QUESTIONS: tuple[str, ...] = tuple(
    key for group in PEDIATRIC_QUESTION_GROUPS.values() for key in group
)

#: Infections and conditions the child has or has had.
PEDIATRIC_CONDITION_GROUPS: dict[str, tuple[str, ...]] = {
    "pediatric": (
        "emotional_disorders",
        "persistent_bleeding",
        "hemophilia",
        "seizures",
        "hepatitis",
        "rheumatic_fever",
        "chronic_nasal_obstruction",
        "frequent_throat_infections",
    ),
}


class Form:
    """What one form asks: its version, questions, conditions and fields."""

    def __init__(
        self,
        version: str,
        questions: tuple[str, ...],
        condition_groups: dict[str, tuple[str, ...]],
        fields: tuple[str, ...] = (),
    ) -> None:
        self.version = version
        self.questions = questions
        self.condition_groups = condition_groups
        self.conditions = frozenset(k for group in condition_groups.values() for k in group)
        self.fields = fields


FORMS: dict[str, Form] = {
    "adult": Form(FORM_VERSION, QUESTIONS, CONDITION_GROUPS),
    "pediatric": Form(
        PEDIATRIC_FORM_VERSION,
        PEDIATRIC_QUESTIONS,
        PEDIATRIC_CONDITION_GROUPS,
        tuple(key for group in PEDIATRIC_FIELD_GROUPS.values() for key in group),
    ),
}

FORM_KINDS: tuple[str, ...] = tuple(FORMS)
