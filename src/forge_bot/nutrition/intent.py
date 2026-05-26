from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Literal

from .router import normalize_text

ALL_NUTRITION_INTENTS = (
    "weekly_planning",
    "recommend_meal",
    "adjust_existing_meal",
    "log_meal",
    "evaluate_day",
    "calculate_macros",
    "recover_from_high_fat_meal",
    "recover_from_high_carb_meal",
    "alcohol_recovery_or_guidance",
    "recovery_guidance",
    "body_composition_analysis",
    "supplement_guidance",
    "batch_cooking_or_recipe_preparation",
    "multi_person_meal_planning",
    "motivation_or_adherence_support",
    "shopping_list",
    "recipe_submission",
    "plan_generation",
    "hunger_management",
    "unknown",
)

NutritionIntent = Literal[
    "weekly_planning",
    "recommend_meal",
    "adjust_existing_meal",
    "log_meal",
    "evaluate_day",
    "calculate_macros",
    "recover_from_high_fat_meal",
    "recover_from_high_carb_meal",
    "alcohol_recovery_or_guidance",
    "recovery_guidance",
    "body_composition_analysis",
    "supplement_guidance",
    "batch_cooking_or_recipe_preparation",
    "multi_person_meal_planning",
    "motivation_or_adherence_support",
    "shopping_list",
    "recipe_submission",
    "plan_generation",
    "hunger_management",
    "unknown",
]


@dataclass(frozen=True)
class NutritionMessageUnderstanding:
    """Cheap, local understanding used before selecting plan context."""

    intent: NutritionIntent
    normalized_message: str
    mentioned_days: tuple[str, ...] = ()
    foods: tuple[str, ...] = ()
    deviations: tuple[str, ...] = ()
    people: tuple[str, ...] = ()
    needs_shopping_list: bool = False
    asks_for_macros: bool = False
    asks_for_full_day: bool = False

    def to_prompt_payload(self) -> dict[str, object]:
        return {
            "intent": self.intent,
            "mentioned_days": list(self.mentioned_days),
            "foods": list(self.foods),
            "deviations": list(self.deviations),
            "people": list(self.people),
            "needs_shopping_list": self.needs_shopping_list,
            "asks_for_macros": self.asks_for_macros,
            "asks_for_full_day": self.asks_for_full_day,
        }


INTENTS_THAT_NEED_PLAN_CONTEXT: frozenset[NutritionIntent] = frozenset(
    {
        "weekly_planning",
        "multi_person_meal_planning",
        "recommend_meal",
        "adjust_existing_meal",
        "log_meal",
        "evaluate_day",
        "recover_from_high_fat_meal",
        "recover_from_high_carb_meal",
        "alcohol_recovery_or_guidance",
        "recovery_guidance",
        "hunger_management",
        "shopping_list",
        "calculate_macros",
    }
)

DAY_ALIASES: dict[str, tuple[str, ...]] = {
    "lunes": ("lunes",),
    "martes": ("martes",),
    "miercoles": ("miercoles",),
    "jueves": ("jueves",),
    "viernes": ("viernes",),
    "sabado": ("sabado",),
    "domingo": ("domingo",),
}

FOOD_ALIASES: dict[str, tuple[str, ...]] = {
    "aguacate": ("aguacate",),
    "arroz": ("arroz",),
    "atun": ("atun",),
    "bacalao": ("bacalao",),
    "cerveza": ("cerveza", "cervezas"),
    "chuletas": ("chuleta", "chuletas"),
    "dulces": ("dulce", "dulces"),
    "ensalada": ("ensalada",),
    "gofre": ("gofre", "gofres"),
    "huevo": ("huevo", "huevos"),
    "merluza": ("merluza",),
    "palmera": ("palmera", "palmeras"),
    "pasta": ("pasta",),
    "patata": ("patata", "patatas"),
    "pollo": ("pollo",),
    "pavo": ("pavo",),
    "rebujito": ("rebujito", "rebujitos"),
    "salmon": ("salmon",),
    "secreto": ("secreto",),
    "verduras": ("verdura", "verduras"),
}

HIGH_FAT_TERMS = (
    "secreto",
    "chuleta",
    "chuletas",
    "cachopo",
    "croqueta",
    "croquetas",
    "frito",
    "fritos",
    "grasa",
    "grasienta",
    "grasiento",
)
HIGH_CARB_TERMS = (
    "atracon",
    "dulce",
    "dulces",
    "dorayaki",
    "dorayakis",
    "gofre",
    "gofres",
    "palmera",
    "palmeras",
    "azucar",
)
ALCOHOL_TERMS = ("alcohol", "cerveza", "cervezas", "rebujito", "rebujitos", "vino")


def classify_nutrition_message(message: str) -> NutritionMessageUnderstanding:
    """Classify an informal nutrition message without calling an LLM."""
    normalized = normalize_text(message)
    foods = _detect_foods(normalized)
    deviations = _detect_deviations(normalized)
    mentioned_days = _detect_days(normalized)
    people = _detect_people(normalized)
    asks_for_macros = _contains_any(
        normalized,
        (
            "macro",
            "macros",
            "caloria",
            "calorias",
            "proteina llevo",
            "cuanta proteina",
            "hidratos llevo",
            "grasa llevo",
        ),
    )
    needs_shopping_list = _contains_any(
        normalized,
        ("lista de la compra", "compra", "supermercado"),
    )
    asks_for_full_day = _contains_any(
        normalized,
        (
            "todo el dia",
            "dia completo",
            "plan del dia",
            "que puedo comer hoy",
            "todo lo que puedo comer",
            "todas las comidas",
            "entre todas las comidas",
            "comidas que tengo que hacer",
        ),
    ) or (
        asks_for_macros
        and _contains_any(normalized, ("dia", "todas las comidas", "comidas"))
    )
    intent = _detect_intent(
        normalized,
        foods=foods,
        deviations=deviations,
        mentioned_days=mentioned_days,
        people=people,
        asks_for_macros=asks_for_macros,
        needs_shopping_list=needs_shopping_list,
    )
    return NutritionMessageUnderstanding(
        intent=intent,
        normalized_message=normalized,
        mentioned_days=mentioned_days,
        foods=foods,
        deviations=deviations,
        people=people,
        needs_shopping_list=needs_shopping_list,
        asks_for_macros=asks_for_macros,
        asks_for_full_day=asks_for_full_day,
    )


def _detect_intent(
    normalized: str,
    *,
    foods: tuple[str, ...],
    deviations: tuple[str, ...],
    mentioned_days: tuple[str, ...],
    people: tuple[str, ...],
    asks_for_macros: bool,
    needs_shopping_list: bool,
) -> NutritionIntent:
    if _contains_any(
        normalized,
        ("/set_plan", "subir plan", "plan nuevo", "nuevo plan", "json"),
    ):
        return "plan_generation"
    if _contains_any(
        normalized,
        ("te paso una receta", "guardar receta", "anadir receta", "nueva receta"),
    ):
        return "recipe_submission"
    if needs_shopping_list:
        return "shopping_list"
    if mentioned_days and _contains_any(
        normalized,
        ("planificacion", "planificar", "semana", "plan de comidas"),
    ):
        return "multi_person_meal_planning" if people else "weekly_planning"
    if _contains_any(normalized, ("planificacion de la semana", "plan de la semana")):
        return "multi_person_meal_planning" if people else "weekly_planning"
    if asks_for_macros:
        return "calculate_macros"
    if _contains_any(normalized, ("como vamos", "como queda el dia", "voy pasado")):
        return "evaluate_day"
    if _contains_any(normalized, ("porcentaje de grasa", "peso", "composicion")):
        return "body_composition_analysis"
    if _contains_any(
        normalized,
        ("suplemento", "suplementacion", "creatina", "magnesio", "whey"),
    ):
        return "supplement_guidance"
    if _contains_any(
        normalized,
        ("batch", "congelado", "dejar preparado", "varios dias", "meal prep"),
    ):
        return "batch_cooking_or_recipe_preparation"
    if _contains_any(
        normalized,
        ("estancado", "motivacion", "constancia", "me estoy rayando"),
    ):
        return "motivation_or_adherence_support"
    if _contains_any(normalized, ("tengo hambre", "mucha hambre", "sin liarla")):
        return "hunger_management"
    if _contains_any(normalized, ALCOHOL_TERMS):
        return "alcohol_recovery_or_guidance"
    if _contains_any(normalized, HIGH_FAT_TERMS):
        return "recover_from_high_fat_meal"
    if _contains_any(normalized, HIGH_CARB_TERMS):
        return "recover_from_high_carb_meal"
    if _contains_any(
        normalized,
        ("reventado", "sobrecarga", "agujetas", "sin fuerza", "vacio"),
    ):
        return "recovery_guidance"
    if _contains_any(
        normalized,
        (
            "he comido",
            "he cenado",
            "me he comido",
            "acabo de comer",
            "me he saltado",
        ),
    ):
        return "log_meal"
    if _contains_any(
        normalized,
        (
            "voy a cenar",
            "voy a comer",
            "le meto",
            "le pongo",
            "puedo meter",
            "puedo anadir",
            "cuanto le pongo",
        ),
    ):
        return "adjust_existing_meal"
    if _contains_any(
        normalized,
        (
            "que como",
            "que comer",
            "que puedo comer",
            "que puedo tomar",
            "que ceno",
            "que desayuno",
            "que meriendo",
            "que me hago",
            "comida toca",
            "cena toca",
            "hoy tengo",
            "hoy es dia",
            "dia de no entreno",
            "no entreno",
        ),
    ):
        return "recommend_meal"
    if foods and _contains_any(normalized, ("puedo", "encaja", "vale")):
        return "adjust_existing_meal"
    return "unknown"


def _detect_days(normalized: str) -> tuple[str, ...]:
    days: list[str] = []
    for day, aliases in DAY_ALIASES.items():
        if _contains_any(normalized, aliases):
            days.append(day)
    return tuple(days)


def _detect_foods(normalized: str) -> tuple[str, ...]:
    foods: list[str] = []
    for food, aliases in FOOD_ALIASES.items():
        if _contains_any(normalized, aliases):
            foods.append(food)
    return tuple(foods)


def _detect_deviations(normalized: str) -> tuple[str, ...]:
    deviations: list[str] = []
    if _contains_any(normalized, HIGH_FAT_TERMS):
        deviations.append("high_fat_meal")
    if _contains_any(normalized, HIGH_CARB_TERMS):
        deviations.append("high_carb_meal")
    if _contains_any(normalized, ALCOHOL_TERMS):
        deviations.append("alcohol")
    if _contains_any(normalized, ("me he saltado", "saltado", "no he hecho")):
        deviations.append("skipped_meal")
    return tuple(deviations)


def _detect_people(normalized: str) -> tuple[str, ...]:
    people: list[str] = []
    if _contains_any(normalized, ("pareja", "mi mujer", "mi marido", "los dos")):
        people.append("pareja")
    return tuple(people)


def _contains_any(normalized: str, aliases: Iterable[str]) -> bool:
    return any(_contains_phrase(normalized, normalize_text(alias)) for alias in aliases)


def _contains_phrase(normalized: str, phrase: str) -> bool:
    if not phrase:
        return False
    return f" {phrase} " in f" {normalized} "
