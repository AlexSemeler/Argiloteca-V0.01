from enum import Enum


class ScientificStatus(str, Enum):
    CALCULATED = "calculated"
    INFERRED = "inferred"
    REVIEWED = "reviewed"
    CONFIRMED = "confirmed"
    INCONCLUSIVE = "inconclusive"


class Preparation(str, Enum):
    NATURAL = "natural"
    GLYCOLATED = "glicolada"
    CALCINED = "calcinada"
    UNDETERMINED = "indeterminada"
