"""Constants for the odontogram module."""

from datetime import date
from enum import StrEnum
from typing import Final

# FDI Notation - Permanent teeth (adults): 11-48
# Quadrant 1 (upper right): 18-17-16-15-14-13-12-11
# Quadrant 2 (upper left): 21-22-23-24-25-26-27-28
# Quadrant 3 (lower left): 38-37-36-35-34-33-32-31
# Quadrant 4 (lower right): 41-42-43-44-45-46-47-48
PERMANENT_TEETH: Final[list[int]] = [
    # Upper right (quadrant 1)
    18,
    17,
    16,
    15,
    14,
    13,
    12,
    11,
    # Upper left (quadrant 2)
    21,
    22,
    23,
    24,
    25,
    26,
    27,
    28,
    # Lower left (quadrant 3)
    38,
    37,
    36,
    35,
    34,
    33,
    32,
    31,
    # Lower right (quadrant 4)
    41,
    42,
    43,
    44,
    45,
    46,
    47,
    48,
]

# FDI Notation - Deciduous teeth (children): 51-85
# Quadrant 5 (upper right): 55-54-53-52-51
# Quadrant 6 (upper left): 61-62-63-64-65
# Quadrant 7 (lower left): 75-74-73-72-71
# Quadrant 8 (lower right): 81-82-83-84-85
DECIDUOUS_TEETH: Final[list[int]] = [
    # Upper right (quadrant 5)
    55,
    54,
    53,
    52,
    51,
    # Upper left (quadrant 6)
    61,
    62,
    63,
    64,
    65,
    # Lower left (quadrant 7)
    75,
    74,
    73,
    72,
    71,
    # Lower right (quadrant 8)
    81,
    82,
    83,
    84,
    85,
]

ALL_TEETH: Final[list[int]] = PERMANENT_TEETH + DECIDUOUS_TEETH


class ToothType(StrEnum):
    """Type of tooth dentition."""

    PERMANENT = "permanent"
    DECIDUOUS = "deciduous"


class Dentition(StrEnum):
    """Which teeth a patient's chart shows.

    ``AUTO`` follows the patient's age (:func:`dentition_for_age`); the
    others are a clinician's choice for that patient, kept until changed.
    """

    AUTO = "auto"
    DECIDUOUS = "deciduous"
    MIXED = "mixed"
    PERMANENT = "permanent"


#: Ages (completed years) where the chart's dentition changes: below the
#: first, deciduous; below the second, mixed; from it on, permanent. Third
#: molars are shown dimmed below the third.
MIXED_FROM_AGE: Final[int] = 6
PERMANENT_FROM_AGE: Final[int] = 13
THIRD_MOLARS_FROM_AGE: Final[int] = 18


class EruptionStatus(StrEnum):
    """Where a tooth is in its life, charted by the clinician.

    ``None`` on a tooth record means "not said": the chart then goes by the
    eruption chronology.
    """

    UNERUPTED = "unerupted"  # not in the mouth yet
    ERUPTING = "erupting"  # coming through
    ERUPTED = "erupted"  # in the mouth
    EXFOLIATED = "exfoliated"  # a primary tooth that fell out
    CONGENITALLY_MISSING = "congenitally_missing"  # agenesis: it will not come
    IMPACTED = "impacted"  # retained in the bone


ERUPTION_STATUSES: Final[tuple[str, ...]] = tuple(status.value for status in EruptionStatus)

#: Usual age (completed years, lower bound) a permanent tooth erupts, by arch
#: and position 1–8. A clinic may set its own (``OdontogramClinicSettings``).
DEFAULT_ERUPTION_AGES: Final[dict[str, dict[str, int]]] = {
    "upper": {"1": 7, "2": 8, "3": 11, "4": 10, "5": 10, "6": 6, "7": 12, "8": 17},
    "lower": {"1": 6, "2": 7, "3": 9, "4": 10, "5": 11, "6": 6, "7": 11, "8": 17},
}

#: Years past the usual age before the chart warns of a late eruption or a
#: primary tooth kept too long.
ERUPTION_TOLERANCE_YEARS: Final[int] = 2


def successor_of(primary: int) -> int | None:
    """The permanent tooth that replaces a primary one (54 → 14)."""
    if primary not in DECIDUOUS_TEETH:
        return None
    return (primary // 10 - 4) * 10 + primary % 10


def age_in_years(birth_date: date | None, on: date) -> int | None:
    """Completed years on ``on``; ``None`` when the birth date is unknown."""
    if birth_date is None:
        return None
    before_birthday = (on.month, on.day) < (birth_date.month, birth_date.day)
    return on.year - birth_date.year - before_birthday


def dentition_for_age(age: int | None) -> Dentition:
    """The dentition a patient of ``age`` is expected to have.

    A suggestion — what is charted tooth by tooth is what counts. With no
    known age, permanent: the chart every adult needs.
    """
    if age is None or age >= PERMANENT_FROM_AGE:
        return Dentition.PERMANENT
    if age >= MIXED_FROM_AGE:
        return Dentition.MIXED
    return Dentition.DECIDUOUS


class Surface(StrEnum):
    """Tooth surfaces using standard dental notation."""

    MESIAL = "M"  # Side toward midline
    DISTAL = "D"  # Side away from midline
    OCCLUSAL = "O"  # Chewing surface (molars/premolars) or Incisal (incisors/canines)
    VESTIBULAR = "V"  # Outer surface (toward lips/cheeks)
    LINGUAL = "L"  # Inner surface (toward tongue)


SURFACES: Final[list[str]] = [s.value for s in Surface]


class ToothCondition(StrEnum):
    """Possible conditions stored on ToothRecord.surfaces / general_condition.

    These describe the observed state of a tooth/surface — independent of the
    Treatment log. Whole-tooth states like `crown` or `missing` are acceptable as
    general_condition even though they usually imply an underlying Treatment.
    """

    HEALTHY = "healthy"
    CARIES = "caries"
    FILLING = "filling"
    CROWN = "crown"
    MISSING = "missing"
    ROOT_CANAL = "root_canal"
    IMPLANT = "implant"
    EXTRACTION_INDICATED = "extraction_indicated"
    SEALANT = "sealant"
    FRACTURE = "fracture"


class TreatmentStatus(StrEnum):
    """Status of a Treatment.

    planned: decided but not yet done.
    performed: executed (applies to treatments done in this clinic or pre-existing
    findings discovered during diagnosis).
    """

    PLANNED = "planned"
    PERFORMED = "performed"


class TreatmentScope(StrEnum):
    """How a Treatment relates to teeth.

    tooth         → 1 TreatmentTooth, surfaces optional (inside the row)
    multi_tooth   → N TreatmentTooth with optional role (pillar/pontic/cantilever)
    global_mouth  → 0 TreatmentTooth (e.g. cleaning, whitening, fluorization)
    global_arch   → 0 TreatmentTooth; `arch` required (e.g. splint upper/lower)
    """

    TOOTH = "tooth"
    MULTI_TOOTH = "multi_tooth"
    GLOBAL_MOUTH = "global_mouth"
    GLOBAL_ARCH = "global_arch"


class Arch(StrEnum):
    """Dental arch (for global_arch treatments)."""

    UPPER = "upper"
    LOWER = "lower"


class TreatmentCategory(StrEnum):
    """Category of treatment based on what it affects."""

    SURFACE = "surface"  # Affects specific surfaces
    WHOLE_TOOTH = "whole_tooth"  # Affects entire tooth


class TreatmentType(StrEnum):
    """Clinical types of dental treatments.

    These drive visualization rules on the odontogram. Pricing, duration, human labels
    and variants live in the catalog module. A `bridge` is a single clinical type
    regardless of how many teeth it covers; pillar/pontic distinction is a per-tooth
    role on TreatmentTooth, not a type.
    """

    # Diagnóstico (Diagnostic) — pre-existing findings, usually not billable.
    PULPITIS = "pulpitis"
    CARIES = "caries"
    INCIPIENT_CARIES = "incipient_caries"
    PIGMENTATION = "pigmentation"
    FRACTURE = "fracture"
    MISSING = "missing"
    PERIAPICAL_SMALL = "periapical_small"
    PERIAPICAL_MEDIUM = "periapical_medium"
    PERIAPICAL_LARGE = "periapical_large"
    ROTATED = "rotated"
    DISPLACED = "displaced"
    UNERUPTED = "unerupted"

    # Restauradora (Restorative)
    FILLING_COMPOSITE = "filling_composite"
    FILLING_AMALGAM = "filling_amalgam"
    FILLING_TEMPORARY = "filling_temporary"
    SEALANT = "sealant"
    VENEER = "veneer"
    INLAY = "inlay"
    OVERLAY = "overlay"
    CROWN = "crown"
    CROWN_ON_IMPLANT = "crown_on_implant"  # Definitive crown supported by an implant.
    PROVISIONAL_CROWN_ON_IMPLANT = "provisional_crown_on_implant"  # Temporary crown on an implant.
    BRIDGE = "bridge"  # Atomic multi-tooth. Roles (pillar/pontic) live on TreatmentTooth.
    SPLINT = "splint"  # Atomic multi-tooth.

    # Cirugía (Surgery)
    EXTRACTION = "extraction"
    IMPLANT = "implant"
    APICOECTOMY = "apicoectomy"
    # A biopsy is a surgical act that serves a diagnosis: tissue taken from
    # beside a tooth for the pathologist. Soft: gingiva / mucosa. Hard: bone
    # or an intraosseous lesion. Charted on the tooth it is nearest to.
    BIOPSY_SOFT_TISSUE = "biopsy_soft_tissue"
    BIOPSY_HARD_TISSUE = "biopsy_hard_tissue"

    # Endodoncia (Endodontics)
    ROOT_CANAL_FULL = "root_canal_full"
    ROOT_CANAL_TWO_THIRDS = "root_canal_two_thirds"
    ROOT_CANAL_HALF = "root_canal_half"
    POST = "post"
    ROOT_CANAL_OVERFILL = "root_canal_overfill"

    # Ortodoncia (Orthodontics)
    BRACKET = "bracket"
    TUBE = "tube"
    BAND = "band"
    ATTACHMENT = "attachment"
    RETAINER = "retainer"

    # Esquelético (Skeletal / orthognathic) — acts on the facial skeleton, not
    # on a tooth. Deliberately absent from TREATMENTS_BY_CATEGORY and from
    # TREATMENT_VISUALIZATION_RULES below: those drive the per-tooth palette
    # (whose fallback hard-codes ``treatment_scope: 'tooth'``) and the drawing
    # of a tooth, and neither applies here. A skeletal treatment reaches the UI
    # as a ``global_mouth`` / ``global_arch`` catalog item, so it renders as a
    # named chip in the "Boca completa" tab and draws nothing on the chart.
    OSTEOTOMY_LEFORT1 = "osteotomy_lefort1"  # Le Fort I maxillary osteotomy.
    OSTEOTOMY_SAGITTAL_RAMUS = "osteotomy_sagittal_ramus"  # Bilateral sagittal split (BSSO).
    GENIOPLASTY = "genioplasty"  # Sliding genioplasty of the mandibular symphysis.
    OSTEOSYNTHESIS = "osteosynthesis"  # Plate/screw fixation of the osteotomised segments.
    OSTEOSYNTHESIS_REMOVAL = "osteosynthesis_removal"  # Deferred hardware removal.

    # Proceso (Process) — the visit itself rather than work on a structure:
    # examination, imaging, hygiene. Billable, plannable, and not attached to
    # any tooth. Same treatment as the skeletal block above: absent from the
    # per-tooth palette and from the drawing rules, reached as a
    # ``global_mouth`` catalog item. Without these a first visit had to borrow
    # ``extraction`` to satisfy the mapping.
    CONSULTATION = "consultation"  # First visit, second opinion, urgent visit.
    CHECKUP = "checkup"  # Periodic review of a known patient.
    IMAGING = "imaging"  # Panoramic, periapical, CBCT, cephalometric, photos.
    HYGIENE = "hygiene"  # Scaling, prophylaxis, fluoride, hygiene instruction.
    # Catch-all for a billable act the chart does not draw: a removable
    # denture, an occlusal adjustment, an orthodontic appliance, a graft.
    # Roughly half a dental catalog is like this, and refusing to plan those
    # treatments was never the intent of requiring a chart mapping.
    PROCEDURE = "procedure"


class VisualizationRule(StrEnum):
    """Visualization rules for rendering treatments."""

    PULP_FILL = "pulp_fill"  # Rule 1: Fill pulp chamber in lateral view
    OCCLUSAL_SURFACE = "occlusal_surface"  # Rule 2: Surface fill/dot in cenital view
    LATERAL_ICON = "lateral_icon"  # Rule 3: SVG icon on lateral view
    PATTERN_FILL = "pattern_fill"  # Rule 4: Pattern fill on cenital view


class TreatmentClinicalCategory(StrEnum):
    """Clinical categories for treatments (used in TreatmentBar).

    Mirrors the catalog's category keys: a mapping's ``clinical_category``
    decides which tab of the bar an item lands in, and the tab takes its
    label from the catalog category of the same key.

    Only the first five carry a built-in findings palette in
    ``TREATMENTS_BY_CATEGORY`` below; the rest reach the bar through the
    catalog, which is where a clinic's own treatments live anyway.
    """

    DIAGNOSTICO = "diagnostico"
    RESTAURADORA = "restauradora"
    CIRUGIA = "cirugia"
    ENDODONCIA = "endodoncia"
    ORTODONCIA = "ortodoncia"
    PREVENTIVO = "preventivo"
    PERIODONCIA = "periodoncia"
    PROTESIS = "protesis"
    ESTETICA = "estetica"
    PEDIATRICA = "pediatrica"


# Treatments by clinical category
TREATMENTS_BY_CATEGORY: Final[dict[str, list[str]]] = {
    TreatmentClinicalCategory.DIAGNOSTICO.value: [
        TreatmentType.PULPITIS.value,
        TreatmentType.CARIES.value,
        TreatmentType.INCIPIENT_CARIES.value,
        TreatmentType.PIGMENTATION.value,
        TreatmentType.FRACTURE.value,
        TreatmentType.MISSING.value,
        TreatmentType.PERIAPICAL_SMALL.value,
        TreatmentType.PERIAPICAL_MEDIUM.value,
        TreatmentType.PERIAPICAL_LARGE.value,
        TreatmentType.ROTATED.value,
        TreatmentType.DISPLACED.value,
        TreatmentType.UNERUPTED.value,
    ],
    TreatmentClinicalCategory.RESTAURADORA.value: [
        TreatmentType.FILLING_COMPOSITE.value,
        TreatmentType.FILLING_AMALGAM.value,
        TreatmentType.FILLING_TEMPORARY.value,
        TreatmentType.SEALANT.value,
        TreatmentType.VENEER.value,
        TreatmentType.INLAY.value,
        TreatmentType.OVERLAY.value,
        TreatmentType.CROWN.value,
        TreatmentType.BRIDGE.value,  # atomic multi-tooth
        TreatmentType.SPLINT.value,  # atomic multi-tooth
    ],
    TreatmentClinicalCategory.CIRUGIA.value: [
        TreatmentType.EXTRACTION.value,
        TreatmentType.IMPLANT.value,
        TreatmentType.APICOECTOMY.value,
        TreatmentType.BIOPSY_SOFT_TISSUE.value,
        TreatmentType.BIOPSY_HARD_TISSUE.value,
    ],
    TreatmentClinicalCategory.ENDODONCIA.value: [
        TreatmentType.ROOT_CANAL_FULL.value,
        TreatmentType.ROOT_CANAL_TWO_THIRDS.value,
        TreatmentType.ROOT_CANAL_HALF.value,
        TreatmentType.POST.value,
        TreatmentType.ROOT_CANAL_OVERFILL.value,
    ],
    TreatmentClinicalCategory.ORTODONCIA.value: [
        TreatmentType.BRACKET.value,
        TreatmentType.TUBE.value,
        TreatmentType.BAND.value,
        TreatmentType.ATTACHMENT.value,
        TreatmentType.RETAINER.value,
    ],
}


# Visualization rules mapping
TREATMENT_VISUALIZATION_RULES: Final[dict[str, list[str]]] = {
    # Rule 1: Pulp fill (lateral view)
    VisualizationRule.PULP_FILL.value: [
        TreatmentType.PULPITIS.value,
        TreatmentType.ROOT_CANAL_FULL.value,
        TreatmentType.ROOT_CANAL_TWO_THIRDS.value,
        TreatmentType.ROOT_CANAL_HALF.value,
        TreatmentType.ROOT_CANAL_OVERFILL.value,  # Also uses LATERAL_ICON
    ],
    # Rule 2: Occlusal surface (cenital view)
    VisualizationRule.OCCLUSAL_SURFACE.value: [
        TreatmentType.CARIES.value,
        TreatmentType.INCIPIENT_CARIES.value,
        TreatmentType.PIGMENTATION.value,
        TreatmentType.FILLING_COMPOSITE.value,
        TreatmentType.FILLING_AMALGAM.value,
        TreatmentType.FILLING_TEMPORARY.value,
        TreatmentType.SEALANT.value,
        TreatmentType.VENEER.value,
    ],
    # Rule 3: Lateral icon (lateral view)
    VisualizationRule.LATERAL_ICON.value: [
        TreatmentType.FRACTURE.value,
        TreatmentType.MISSING.value,
        TreatmentType.PERIAPICAL_SMALL.value,
        TreatmentType.PERIAPICAL_MEDIUM.value,
        TreatmentType.PERIAPICAL_LARGE.value,
        TreatmentType.ROTATED.value,
        TreatmentType.DISPLACED.value,
        TreatmentType.IMPLANT.value,
        TreatmentType.APICOECTOMY.value,
        TreatmentType.BIOPSY_SOFT_TISSUE.value,
        TreatmentType.BIOPSY_HARD_TISSUE.value,
        TreatmentType.EXTRACTION.value,
        TreatmentType.POST.value,
        TreatmentType.ROOT_CANAL_OVERFILL.value,  # Also uses PULP_FILL
        TreatmentType.BRACKET.value,
        TreatmentType.TUBE.value,
        TreatmentType.BAND.value,
        TreatmentType.ATTACHMENT.value,
        TreatmentType.RETAINER.value,
        TreatmentType.SPLINT.value,
    ],
    # Rule 4: Pattern fill (cenital view)
    VisualizationRule.PATTERN_FILL.value: [
        TreatmentType.UNERUPTED.value,
        TreatmentType.INLAY.value,
        TreatmentType.OVERLAY.value,
        TreatmentType.CROWN.value,
        TreatmentType.BRIDGE.value,
    ],
}


# Treatment type categorization (surface vs whole tooth)
SURFACE_TREATMENTS: Final[set[str]] = {
    TreatmentType.CARIES.value,
    TreatmentType.INCIPIENT_CARIES.value,
    TreatmentType.PIGMENTATION.value,
    TreatmentType.FILLING_COMPOSITE.value,
    TreatmentType.FILLING_AMALGAM.value,
    TreatmentType.FILLING_TEMPORARY.value,
    TreatmentType.SEALANT.value,
    TreatmentType.VENEER.value,
    TreatmentType.INLAY.value,
}

WHOLE_TOOTH_TREATMENTS: Final[set[str]] = {
    TreatmentType.PULPITIS.value,
    TreatmentType.FRACTURE.value,
    TreatmentType.MISSING.value,
    TreatmentType.PERIAPICAL_SMALL.value,
    TreatmentType.PERIAPICAL_MEDIUM.value,
    TreatmentType.PERIAPICAL_LARGE.value,
    TreatmentType.ROTATED.value,
    TreatmentType.DISPLACED.value,
    TreatmentType.UNERUPTED.value,
    TreatmentType.OVERLAY.value,
    TreatmentType.CROWN.value,
    TreatmentType.CROWN_ON_IMPLANT.value,
    TreatmentType.PROVISIONAL_CROWN_ON_IMPLANT.value,
    TreatmentType.BRIDGE.value,
    TreatmentType.SPLINT.value,
    TreatmentType.EXTRACTION.value,
    TreatmentType.IMPLANT.value,
    TreatmentType.APICOECTOMY.value,
    TreatmentType.BIOPSY_SOFT_TISSUE.value,
    TreatmentType.BIOPSY_HARD_TISSUE.value,
    TreatmentType.ROOT_CANAL_FULL.value,
    TreatmentType.ROOT_CANAL_TWO_THIRDS.value,
    TreatmentType.ROOT_CANAL_HALF.value,
    TreatmentType.POST.value,
    TreatmentType.ROOT_CANAL_OVERFILL.value,
    TreatmentType.BRACKET.value,
    TreatmentType.TUBE.value,
    TreatmentType.BAND.value,
    TreatmentType.ATTACHMENT.value,
    TreatmentType.RETAINER.value,
}


# Treatments that are clinically atomic multi-tooth units. A Treatment with any of
# these clinical types must have more than one TreatmentTooth and may carry per-tooth
# roles (pillar/pontic on bridges).
ATOMIC_MULTI_TOOTH_TYPES: Final[set[str]] = {
    TreatmentType.BRIDGE.value,
    TreatmentType.SPLINT.value,
}


def get_visualization_rules(treatment_type: str) -> list[str]:
    """Get the default visualization rules for a clinical type.

    Fallback for treatments without a catalog_item_id (e.g. diagnostic findings).
    """
    return [
        rule
        for rule, treatments in TREATMENT_VISUALIZATION_RULES.items()
        if treatment_type in treatments
    ]


def get_treatment_category(treatment_type: str) -> TreatmentCategory:
    """Determine if a treatment affects surfaces or whole tooth."""
    if treatment_type in SURFACE_TREATMENTS:
        return TreatmentCategory.SURFACE
    return TreatmentCategory.WHOLE_TOOTH


def is_valid_treatment_type(treatment_type: str) -> bool:
    """Check if a treatment type is valid."""
    return treatment_type in SURFACE_TREATMENTS or treatment_type in WHOLE_TOOTH_TREATMENTS


# Color mapping for each condition (frontend reference).
CONDITION_COLORS: Final[dict[str, str]] = {
    ToothCondition.HEALTHY.value: "#FFFFFF",
    ToothCondition.CARIES.value: "#EF4444",
    ToothCondition.FILLING.value: "#3B82F6",
    ToothCondition.CROWN.value: "#F59E0B",
    ToothCondition.MISSING.value: "#9CA3AF",
    ToothCondition.ROOT_CANAL.value: "#8B5CF6",
    ToothCondition.IMPLANT.value: "#10B981",
    ToothCondition.EXTRACTION_INDICATED.value: "#DC2626",
    ToothCondition.SEALANT.value: "#06B6D4",
    ToothCondition.FRACTURE.value: "#BE185D",
}


def get_tooth_type(tooth_number: int) -> ToothType:
    """Determine if a tooth is permanent or deciduous based on FDI number."""
    if tooth_number in PERMANENT_TEETH:
        return ToothType.PERMANENT
    elif tooth_number in DECIDUOUS_TEETH:
        return ToothType.DECIDUOUS
    else:
        raise ValueError(f"Invalid tooth number: {tooth_number}")


def is_valid_tooth_number(tooth_number: int) -> bool:
    """Check if a tooth number is valid according to FDI notation."""
    return tooth_number in ALL_TEETH
