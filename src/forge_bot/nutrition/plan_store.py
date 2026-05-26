from __future__ import annotations

import logging
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

import psycopg
from psycopg.types.json import Jsonb

from ..database import conect_db
from .plan import NutritionPlan, parse_nutrition_plan

logger = logging.getLogger(__name__)

LEGACY_NUTRITION_PLAN_DOCUMENT_TYPE = "meal_plan"
NUTRITION_PLAN_SITUATIONS_DOCUMENT_TYPE = "situaciones"
NUTRITION_PLAN_MEALS_DOCUMENT_TYPE = "comidas"
NUTRITION_PLAN_ADAPTATION_RULES_DOCUMENT_TYPE = "reglas_adaptacion"
NUTRITION_PLAN_RECIPES_DOCUMENT_TYPE = "recetas"


class NutritionPlanStoreError(RuntimeError):
    """Raised when nutrition plan persistence cannot complete."""


@dataclass(frozen=True)
class SavedNutritionPlan:
    """Stored active nutrition plan metadata."""

    plan_uuid: str
    user_id: int
    plan: NutritionPlan


@dataclass(frozen=True)
class SavedNutritionPlanPart:
    """Result of storing one partial plan document."""

    plan_uuid: str
    user_id: int
    document_type: str
    missing_document_types: tuple[str, ...]
    activated_plan: NutritionPlan | None = None

    @property
    def activated(self) -> bool:
        return self.activated_plan is not None


@dataclass(frozen=True)
class ActiveNutritionPlanDocuments:
    """Raw JSONB documents stored for the active nutrition plan."""

    plan_uuid: str
    documents: Mapping[str, Mapping[str, Any]]
    combined: Mapping[str, Any]


def load_active_nutrition_plan(*, user_id: int) -> NutritionPlan | None:
    """Load the active normalized nutrition plan for one internal user."""
    connection = conect_db()
    if connection is None:
        return None
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT p.id AS plan_uuid, d.document_type, d.content
                FROM nutrition_plans p
                JOIN nutrition_plan_documents d ON d.plan_id = p.id
                WHERE p.id = (
                    SELECT id
                    FROM nutrition_plans
                    WHERE user_id = %s
                      AND status = 'active'
                    ORDER BY updated_at DESC, created_at DESC
                    LIMIT 1
                )
                """,
                (user_id,),
            )
            rows = list(cursor.fetchall())
    except psycopg.Error:
        logger.exception("nutrition_active_plan_load_failed user_id=%s", user_id)
        return None
    finally:
        connection.close()

    if not rows:
        return None
    content = _combine_plan_documents(rows)
    if content is None:
        logger.warning("nutrition_active_plan_invalid_content user_id=%s", user_id)
        return None
    try:
        return parse_nutrition_plan(content)
    except Exception:
        logger.exception("nutrition_active_plan_parse_failed user_id=%s", user_id)
        return None


def load_active_nutrition_plan_documents(
    *,
    user_id: int,
) -> ActiveNutritionPlanDocuments | None:
    """Load raw active plan documents for user-facing review/export."""
    connection = conect_db()
    if connection is None:
        return None
    try:
        with connection.cursor() as cursor:
            rows = _fetch_active_plan_document_rows(cursor=cursor, user_id=user_id)
    except psycopg.Error:
        logger.exception(
            "nutrition_active_plan_documents_load_failed user_id=%s",
            user_id,
        )
        return None
    finally:
        connection.close()

    if not rows:
        return None
    combined = _combine_plan_documents(rows)
    if combined is None:
        return None

    documents: dict[str, Mapping[str, Any]] = {}
    plan_uuid = ""
    for row in rows:
        if not plan_uuid and row.get("plan_uuid") is not None:
            plan_uuid = str(row["plan_uuid"])
        document_type = row.get("document_type")
        content = row.get("content")
        if isinstance(document_type, str) and isinstance(content, dict):
            documents[document_type] = content
    return ActiveNutritionPlanDocuments(
        plan_uuid=plan_uuid,
        documents=documents,
        combined=combined,
    )


def save_active_nutrition_plan(
    *,
    user_id: int,
    plan_data: Mapping[str, Any],
    source_filename: str | None = None,
) -> SavedNutritionPlan:
    """Archive the current active plan and store a new active normalized plan."""
    plan = parse_nutrition_plan(plan_data)
    connection = conect_db()
    if connection is None:
        raise NutritionPlanStoreError("La base de datos no esta disponible.")

    try:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                UPDATE nutrition_plans
                SET status = 'archived',
                    updated_at = NOW()
                WHERE user_id = %s
                  AND status = 'active'
                """,
                (user_id,),
            )
            cursor.execute(
                """
                INSERT INTO nutrition_plans (user_id, status, source_filename)
                VALUES (%s, 'active', %s)
                RETURNING id
                """,
                (user_id, source_filename),
            )
            row = cursor.fetchone()
            if row is None:
                raise NutritionPlanStoreError("No se pudo crear el plan.")
            plan_uuid = str(row["id"])
            situations_document: dict[str, Any] = {
                "plan_id": plan.plan_id,
                "situaciones": dict(plan_data["situaciones"]),
            }
            moments = plan_data.get("momentos")
            if isinstance(moments, dict):
                situations_document["momentos"] = dict(moments)

            cursor.execute(
                """
                INSERT INTO nutrition_plan_documents (
                    plan_id, document_type, content
                )
                VALUES (%s, %s, %s)
                """,
                (
                    plan_uuid,
                    NUTRITION_PLAN_SITUATIONS_DOCUMENT_TYPE,
                    Jsonb(situations_document),
                ),
            )
            cursor.execute(
                """
                INSERT INTO nutrition_plan_documents (
                    plan_id, document_type, content
                )
                VALUES (%s, %s, %s)
                """,
                (
                    plan_uuid,
                    NUTRITION_PLAN_MEALS_DOCUMENT_TYPE,
                    Jsonb(
                        {
                            "plan_id": plan.plan_id,
                            "comidas": dict(plan_data["comidas"]),
                        }
                    ),
                ),
            )
            _insert_optional_document(
                cursor=cursor,
                plan_uuid=plan_uuid,
                plan_data=plan_data,
                source_key="reglas_adaptacion",
                document_type=NUTRITION_PLAN_ADAPTATION_RULES_DOCUMENT_TYPE,
            )
            _insert_optional_document(
                cursor=cursor,
                plan_uuid=plan_uuid,
                plan_data=plan_data,
                source_key="recetas",
                document_type=NUTRITION_PLAN_RECIPES_DOCUMENT_TYPE,
            )
        connection.commit()
        return SavedNutritionPlan(plan_uuid=plan_uuid, user_id=user_id, plan=plan)
    except NutritionPlanStoreError:
        connection.rollback()
        raise
    except Exception as exc:
        connection.rollback()
        raise NutritionPlanStoreError(
            "No se pudo guardar el plan nutricional."
        ) from exc
    finally:
        connection.close()


def save_nutrition_plan_part(
    *,
    user_id: int,
    document_type: str,
    content: Mapping[str, Any],
    source_filename: str | None = None,
) -> SavedNutritionPlanPart:
    """Store one uploaded plan part and activate the draft once complete."""
    if document_type not in {
        NUTRITION_PLAN_SITUATIONS_DOCUMENT_TYPE,
        NUTRITION_PLAN_MEALS_DOCUMENT_TYPE,
    }:
        raise NutritionPlanStoreError("Tipo de documento de plan no soportado.")
    _validate_plan_part(document_type=document_type, content=content)

    connection = conect_db()
    if connection is None:
        raise NutritionPlanStoreError("La base de datos no esta disponible.")

    try:
        with connection.cursor() as cursor:
            plan_uuid = _get_or_create_draft_plan(
                cursor=cursor,
                user_id=user_id,
                source_filename=source_filename,
            )
            _upsert_plan_document(
                cursor=cursor,
                plan_uuid=plan_uuid,
                document_type=document_type,
                content=content,
            )
            draft_documents = _fetch_plan_documents(cursor=cursor, plan_uuid=plan_uuid)
            combined = _combine_plan_documents(draft_documents)
            if combined is None:
                connection.commit()
                return SavedNutritionPlanPart(
                    plan_uuid=plan_uuid,
                    user_id=user_id,
                    document_type=document_type,
                    missing_document_types=_missing_required_documents(draft_documents),
                )

            plan = parse_nutrition_plan(combined)
            cursor.execute(
                """
                UPDATE nutrition_plans
                SET status = 'archived',
                    updated_at = NOW()
                WHERE user_id = %s
                  AND status = 'active'
                """,
                (user_id,),
            )
            cursor.execute(
                """
                UPDATE nutrition_plans
                SET status = 'active',
                    updated_at = NOW()
                WHERE id = %s
                """,
                (plan_uuid,),
            )
            connection.commit()
            return SavedNutritionPlanPart(
                plan_uuid=plan_uuid,
                user_id=user_id,
                document_type=document_type,
                missing_document_types=(),
                activated_plan=plan,
            )
    except NutritionPlanStoreError:
        connection.rollback()
        raise
    except Exception as exc:
        connection.rollback()
        raise NutritionPlanStoreError(
            "No se pudo guardar esa parte del plan nutricional."
        ) from exc
    finally:
        connection.close()


def _get_or_create_draft_plan(
    *,
    cursor: Any,
    user_id: int,
    source_filename: str | None,
) -> str:
    cursor.execute(
        """
        SELECT id
        FROM nutrition_plans
        WHERE user_id = %s
          AND status = 'draft'
        ORDER BY updated_at DESC, created_at DESC
        LIMIT 1
        """,
        (user_id,),
    )
    row = cursor.fetchone()
    if row is not None:
        plan_uuid = str(row["id"])
        cursor.execute(
            """
            UPDATE nutrition_plans
            SET source_filename = COALESCE(%s, source_filename),
                updated_at = NOW()
            WHERE id = %s
            """,
            (source_filename, plan_uuid),
        )
        return plan_uuid

    cursor.execute(
        """
        INSERT INTO nutrition_plans (user_id, status, source_filename)
        VALUES (%s, 'draft', %s)
        RETURNING id
        """,
        (user_id, source_filename),
    )
    created = cursor.fetchone()
    if created is None:
        raise NutritionPlanStoreError("No se pudo crear el borrador del plan.")
    return str(created["id"])


def _upsert_plan_document(
    *,
    cursor: Any,
    plan_uuid: str,
    document_type: str,
    content: Mapping[str, Any],
) -> None:
    cursor.execute(
        """
        INSERT INTO nutrition_plan_documents (
            plan_id, document_type, content
        )
        VALUES (%s, %s, %s)
        ON CONFLICT (plan_id, document_type)
        DO UPDATE SET content = EXCLUDED.content,
                      updated_at = NOW()
        """,
        (plan_uuid, document_type, Jsonb(dict(content))),
    )


def _fetch_plan_documents(
    *,
    cursor: Any,
    plan_uuid: str,
) -> list[Mapping[str, Any]]:
    cursor.execute(
        """
        SELECT document_type, content
        FROM nutrition_plan_documents
        WHERE plan_id = %s
        """,
        (plan_uuid,),
    )
    return list(cursor.fetchall())


def _fetch_active_plan_document_rows(
    *,
    cursor: Any,
    user_id: int,
) -> list[Mapping[str, Any]]:
    cursor.execute(
        """
        SELECT p.id AS plan_uuid, d.document_type, d.content
        FROM nutrition_plans p
        JOIN nutrition_plan_documents d ON d.plan_id = p.id
        WHERE p.id = (
            SELECT id
            FROM nutrition_plans
            WHERE user_id = %s
              AND status = 'active'
            ORDER BY updated_at DESC, created_at DESC
            LIMIT 1
        )
        ORDER BY d.document_type
        """,
        (user_id,),
    )
    return list(cursor.fetchall())


def _insert_optional_document(
    *,
    cursor: Any,
    plan_uuid: str,
    plan_data: Mapping[str, Any],
    source_key: str,
    document_type: str,
) -> None:
    content = plan_data.get(source_key)
    if not isinstance(content, (dict, list)):
        return
    cursor.execute(
        """
        INSERT INTO nutrition_plan_documents (
            plan_id, document_type, content
        )
        VALUES (%s, %s, %s)
        """,
        (plan_uuid, document_type, Jsonb({source_key: content})),
    )


def _combine_plan_documents(
    rows: list[Mapping[str, Any]],
) -> dict[str, Any] | None:
    combined: dict[str, Any] = {"plan_id": "nutrition_plan"}
    for row in rows:
        document_type = row.get("document_type")
        content = row.get("content")
        if not isinstance(content, dict):
            continue
        plan_id = content.get("plan_id")
        if isinstance(plan_id, str) and plan_id.strip():
            combined["plan_id"] = plan_id.strip()
        if document_type == LEGACY_NUTRITION_PLAN_DOCUMENT_TYPE:
            return dict(content)
        if document_type == NUTRITION_PLAN_SITUATIONS_DOCUMENT_TYPE:
            situations = content.get("situaciones")
            if isinstance(situations, dict):
                combined["situaciones"] = situations
            moments = content.get("momentos")
            if isinstance(moments, dict):
                combined["momentos"] = moments
        elif document_type == NUTRITION_PLAN_MEALS_DOCUMENT_TYPE:
            meals = content.get("comidas")
            if isinstance(meals, dict):
                combined["comidas"] = meals
        elif document_type == NUTRITION_PLAN_ADAPTATION_RULES_DOCUMENT_TYPE:
            rules = content.get("reglas_adaptacion")
            if isinstance(rules, dict):
                combined["reglas_adaptacion"] = rules
        elif document_type == NUTRITION_PLAN_RECIPES_DOCUMENT_TYPE:
            recipes = content.get("recetas")
            if isinstance(recipes, (dict, list)):
                combined["recetas"] = recipes

    if "situaciones" not in combined or "comidas" not in combined:
        return None
    return combined


def _missing_required_documents(
    rows: list[Mapping[str, Any]],
) -> tuple[str, ...]:
    document_types = {
        row.get("document_type")
        for row in rows
        if isinstance(row.get("document_type"), str)
    }
    missing: list[str] = []
    if NUTRITION_PLAN_SITUATIONS_DOCUMENT_TYPE not in document_types:
        missing.append(NUTRITION_PLAN_SITUATIONS_DOCUMENT_TYPE)
    if NUTRITION_PLAN_MEALS_DOCUMENT_TYPE not in document_types:
        missing.append(NUTRITION_PLAN_MEALS_DOCUMENT_TYPE)
    return tuple(missing)


def _validate_plan_part(
    *,
    document_type: str,
    content: Mapping[str, Any],
) -> None:
    root_key = document_type
    value = content.get(root_key)
    if not isinstance(value, dict) or not value:
        raise NutritionPlanStoreError(
            f"El fichero debe contener un objeto raiz '{root_key}'."
        )
