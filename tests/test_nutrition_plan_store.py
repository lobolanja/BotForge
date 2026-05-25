from typing import Any

from forge_bot.nutrition.plan_store import (
    load_active_nutrition_plan,
    save_active_nutrition_plan,
    save_nutrition_plan_part,
)


def sample_plan_data() -> dict[str, Any]:
    return {
        "plan_id": "sample_plan",
        "momentos": {"cena": {"label": "Cena", "aliases": ["cena"]}},
        "situaciones": {
            "no_entreno": {
                "label": "No entreno",
                "aliases": ["no entreno"],
                "suplementacion": [],
                "momentos": {"cena": "comida_1"},
            }
        },
        "comidas": {
            "comida_1": {
                "descripcion": "Cena",
                "and": ["200g merluza", "verdura"],
            }
        },
        "reglas_adaptacion": {
            "principios": ["comidas.json manda sobre cualquier receta."]
        },
        "recetas": [
            {
                "nombre": "merluza_con_ensalada",
                "nombre_visible": "Merluza con ensalada",
            }
        ],
    }


class FakeCursor:
    def __init__(self) -> None:
        self.statements: list[str] = []
        self.params: list[tuple[Any, ...]] = []
        self.fetchone_queue: list[dict[str, Any] | None] = []
        self.fetchall_queue: list[list[dict[str, Any]]] = []

    def __enter__(self) -> "FakeCursor":
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def execute(self, statement: str, params: tuple[Any, ...]) -> None:
        self.statements.append(" ".join(statement.split()))
        self.params.append(params)

    def fetchone(self) -> dict[str, Any] | None:
        return self.fetchone_queue.pop(0)

    def fetchall(self) -> list[dict[str, Any]]:
        return self.fetchall_queue.pop(0)


class FakeConnection:
    def __init__(self) -> None:
        self.cursor_obj = FakeCursor()
        self.committed = False
        self.rolled_back = False
        self.closed = False

    def cursor(self) -> FakeCursor:
        return self.cursor_obj

    def commit(self) -> None:
        self.committed = True

    def rollback(self) -> None:
        self.rolled_back = True

    def close(self) -> None:
        self.closed = True


def test_save_active_nutrition_plan_archives_previous_and_inserts_document(
    monkeypatch,
) -> None:
    connection = FakeConnection()
    connection.cursor_obj.fetchone_queue.append({"id": "plan-uuid"})
    monkeypatch.setattr("forge_bot.nutrition.plan_store.conect_db", lambda: connection)

    saved = save_active_nutrition_plan(
        user_id=7,
        plan_data=sample_plan_data(),
        source_filename="plan.json",
    )

    assert saved.plan_uuid == "plan-uuid"
    assert saved.plan.plan_id == "sample_plan"
    assert connection.committed is True
    statements = connection.cursor_obj.statements
    assert any(
        "UPDATE nutrition_plans SET status = 'archived'" in statement
        for statement in statements
    )
    assert any("INSERT INTO nutrition_plans" in statement for statement in statements)
    document_insert_count = sum(
        1
        for statement in statements
        if "INSERT INTO nutrition_plan_documents" in statement
    )
    document_types = [
        params[1]
        for params in connection.cursor_obj.params
        if len(params) == 3
    ]
    assert document_insert_count == 4
    assert "situaciones" in document_types
    assert "comidas" in document_types
    assert "reglas_adaptacion" in document_types
    assert "recetas" in document_types


def test_load_active_nutrition_plan_parses_stored_json(monkeypatch) -> None:
    connection = FakeConnection()
    connection.cursor_obj.fetchall_queue.append(
        [
            {
                "plan_uuid": "plan-uuid",
                "document_type": "situaciones",
                "content": {
                    "plan_id": "sample_plan",
                    "situaciones": sample_plan_data()["situaciones"],
                },
            },
            {
                "plan_uuid": "plan-uuid",
                "document_type": "comidas",
                "content": {
                    "plan_id": "sample_plan",
                    "comidas": sample_plan_data()["comidas"],
                },
            },
        ]
    )
    monkeypatch.setattr("forge_bot.nutrition.plan_store.conect_db", lambda: connection)

    plan = load_active_nutrition_plan(user_id=7)

    assert plan is not None
    assert plan.plan_id == "sample_plan"
    assert plan.situations.keys() == {"no_entreno"}
    assert connection.closed is True


def test_save_nutrition_plan_part_waits_for_missing_document(monkeypatch) -> None:
    connection = FakeConnection()
    connection.cursor_obj.fetchone_queue.extend([None, {"id": "draft-uuid"}])
    connection.cursor_obj.fetchall_queue.append(
        [
            {
                "document_type": "situaciones",
                "content": {
                    "plan_id": "sample_plan",
                    "situaciones": sample_plan_data()["situaciones"],
                },
            }
        ]
    )
    monkeypatch.setattr("forge_bot.nutrition.plan_store.conect_db", lambda: connection)

    result = save_nutrition_plan_part(
        user_id=7,
        document_type="situaciones",
        content={
            "plan_id": "sample_plan",
            "situaciones": sample_plan_data()["situaciones"],
        },
        source_filename="situaciones.json",
    )

    assert result.activated is False
    assert result.missing_document_types == ("comidas",)
    assert connection.committed is True


def test_save_nutrition_plan_part_activates_when_both_documents_exist(
    monkeypatch,
) -> None:
    connection = FakeConnection()
    connection.cursor_obj.fetchone_queue.extend([None, {"id": "draft-uuid"}])
    connection.cursor_obj.fetchall_queue.append(
        [
            {
                "document_type": "situaciones",
                "content": {
                    "plan_id": "sample_plan",
                    "situaciones": sample_plan_data()["situaciones"],
                },
            },
            {
                "document_type": "comidas",
                "content": {
                    "plan_id": "sample_plan",
                    "comidas": sample_plan_data()["comidas"],
                },
            },
        ]
    )
    monkeypatch.setattr("forge_bot.nutrition.plan_store.conect_db", lambda: connection)

    result = save_nutrition_plan_part(
        user_id=7,
        document_type="comidas",
        content={
            "plan_id": "sample_plan",
            "comidas": sample_plan_data()["comidas"],
        },
        source_filename="comidas.json",
    )

    assert result.activated is True
    assert result.activated_plan is not None
    assert result.activated_plan.plan_id == "sample_plan"
    statements = connection.cursor_obj.statements
    assert any("SET status = 'active'" in statement for statement in statements)
