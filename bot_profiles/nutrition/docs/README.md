# Nutrition Bot Design Docs

These documents are the versioned functional design for the nutrition bot.
They are not user data.

User-specific nutrition plans, extracted documents, recipes, situations, and
adaptation rules must be stored in PostgreSQL as JSONB documents linked to each
user. The filenames used in these docs describe document shapes, not repository
files to create per user.

V1 should keep the plan compact: the active plan stores separate `situaciones`
and `comidas` JSONB documents. `situaciones` routes day context and meal moment
to a comida key; `comidas` keeps the `and`/`or` tree, raw food strings, raw
conditions, macros from the plan, and notes. It should not normalize every food
into a large object unless a later feature proves that cost is worth it.

## Product Goal

The nutrition bot helps a Telegram user follow a nutrition plan delivered by a
nutrition professional. The bot should not invent diets from scratch. Its job is
to interpret structured plan data, preserve the plan's quantities, and answer in
a simple, practical way.

Primary priorities:

1. Respect the user's active nutrition plan.
2. Use the blocks and quantities defined by the plan.
3. Adapt real meals without breaking the plan logic.
4. Keep responses short unless the user asks for detail.
5. Avoid moralizing, guilt, or medical diagnosis.

## Plain Mental Model

For a non-technical user, the product should feel like this:

```text
My nutritionist gave me a plan.
I tell the bot what kind of day I have.
The bot knows which meal block applies.
The bot turns that block into a practical meal.
```

Internally, that maps to:

```text
situaciones -> chooses the right comida for a day/moment
comidas -> defines allowed foods, quantities, macros, and conditions
recetas -> suggests approved real dishes through RAG
adaptation_rules -> helps adjust dishes without breaking the plan
```

Example capabilities this design must support:

- "Que ceno hoy dia de no entreno?" -> one concrete dinner option with plan
  quantities.
- "Hoy tengo crossfit, que puedo comer?"
- "Que ceno hoy si me he saltado la media manana?"
- "Esta manana era dia de crossfit, pero al final no he ido. Ajustame la cena."
- "Cambio crossfit por natacion, que ceno?"
- "Hazme un plan de comidas y cenas para la semana: lunes ciclismo,
  miercoles fuerza, viernes atletismo y el resto no entreno."

In all cases, `comidas` remains the source of truth for quantities.

Runtime principle:

```text
detect situation + detect moment -> resolve comida -> choose valid option path
-> answer with plan quantities
```

The bot should not send the full plan to the LLM when it can select the
relevant block locally. `situaciones.*.aliases` exists so natural language such
as "bici", "gym", "partido", or "correr" can be mapped to configured situations
before the model is called.

## Document Map

- [User journeys](user-journeys.md): complete user flows and expected outcomes.
- [User stories](user-stories.md): implementable stories grouped by MVP.
- [Data contracts](data-contracts.md): JSONB document shapes and validation rules.
- [Response behavior](response-behavior.md): tone, guardrails, and answer examples.
- [Orchestration](orchestration.md): LangChain pipeline, model routing, and
  future MCP tool boundaries.
- [Roadmap](roadmap.md): issue order, MVP boundaries, and maintenance rules.
- [Open considerations](open-considerations.md): nutrition safety gaps and
  product risks to keep visible.

## Maintenance Rule

Every implementation issue in epic #79 must check these docs before changing
behavior. If a PR changes a journey, story, JSONB contract, response rule, or
roadmap assumption, it must update the relevant document in the same PR.

## Current Scope

V1 now focuses on setting one active user plan through `/set_plan`:

- user sends `/set_plan`, then attaches `situaciones.json` and `comidas.json`
  as `.json`/`.txt` files without needing captions, in either order;
- if only one file has arrived, bot keeps a draft and tells the user which part
  is missing;
- a combined JSON with both roots is also accepted;
- bot asks the configured normalization model only when a combined payload needs
  cleanup; already-valid split files use local validation;
- bot stores `situaciones` and `comidas` as PostgreSQL JSONB documents under
  the user's active plan;
- any previous active plan for that user is archived;
- bot replies with a short summary.
- user can run `/get_plan` for a summary or `/get_plan situaciones`,
  `/get_plan comidas`, `/get_plan all` to export review files.

Out of V1:

- OCR for images;
- PDF support;
- full recipe generation;
- full situation mapping;
- recipe RAG;
- daily tracking;
- advanced plan comparison;
- batch cooking workflows.

The current implementation loads the active plan from PostgreSQL. Issue #95
adds the first LangChain orchestration layer around the router. It separates
local understanding, optional LLM normalization, plan-context selection, and
final-answer generation so each step can use a different model or future MCP
tool. It also introduces the first daily nutrition log in PostgreSQL: one
editable state per user/profile/date so the bot can remember today's current
day type, skipped meals, and logged meals without depending only on free-form
chat memory.
