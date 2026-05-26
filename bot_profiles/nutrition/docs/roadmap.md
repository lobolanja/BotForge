# Nutrition Bot Roadmap

This roadmap is tracked under epic #79. Issue #92 owns these design documents.

## Working Rule

Before implementing any nutrition bot issue, read the relevant design docs in
this directory.

If implementation changes product behavior, data shape, journeys, stories, or
MVP order, update these docs in the same PR.

For behavior that touches health, compensation, supplements, weekly planning, or
recipe recommendations, also check [Open considerations](open-considerations.md).

## MVP 1: Base Bot And Plan Capture

Goal: create an active plan from pasted JSON or a `.json/.txt` upload and store
the compact plan as JSONB.

Issues:

- #92: Nutrition bot design docs.
- #80: Nutrition bot profile and guardrails.
- #81: JSONB persistence for nutrition plans.
- #82: `comidas` contract and validation.
- #83: `/set_plan` command for pasted JSON and `.json/.txt` files.
- #84: V1 JSON text ingestion.
- #85: LLM normalizer for `situaciones` and `comidas`.
- #86: Save active plan and summarize generated plan.

Definition of done:

- User can start `/set_plan`.
- Bot accepts compact plan JSON pasted as text or attached as `.json/.txt`.
- Valid JSON can fall back to local validation if LLM normalization is
  unavailable.
- Bot generates or normalizes only the active plan documents needed for V1:
  `situaciones` and `comidas`.
- JSON preserves original food strings, notes, and conditions.
- JSON preserves nested `and`/`or` grouping recursively.
- JSON contains warnings for ambiguity.
- Active plan and document are saved in PostgreSQL.
- Previous active plan is archived only after the new plan validates.
- Bot replies with a clear summary.

## MVP 2: Use Active Plan Well

Goal: use the active plan to answer practical meal questions.

Issues:

- #95: LangChain orchestration, message understanding, and model/tool routing.
- #94: Local situations router and plan chunk selection.
- #87: Activate nutrition plan.
- #88: First responses with active plan.
- #89: Basic adaptation of concrete foods.

Definition of done:

- Only one plan is active per user.
- Without active plan, bot suggests `/set_plan`.
- With active plan, bot answers from the relevant `comidas` slice.
- If the user provides today's activity, the bot resolves it through
  `situaciones` when available.
- The runtime should detect situation and meal moment locally when possible,
  then send only the resolved meal block to the LLM.
- For the basic happy path, the answer should recommend one concrete valid
  option from the resolved block, with plan quantities, instead of listing the
  whole block.
- If situation or moment is missing, bot asks one concise clarification instead
  of sending the full plan.
- Bot does not invent quantities or foods.

## MVP 2A: Active Plan Router

Goal: get useful responses from the active PostgreSQL plan for each user.

Issue:

- #94: Local situations router and plan chunk selection.
- #95: LangChain orchestration, message understanding, and future MCP/model
  routing.

Definition of done:

- The nutrition profile can load the active user plan from PostgreSQL.
- The router detects day situations from `situaciones.*.aliases`.
- The router detects common meal moments from natural language.
- Complete queries such as `Hoy tengo crossfit, que como al mediodia?` resolve
  to one comida block before the LLM call.
- Informal messages are classified locally before the final LLM call, so the
  prompt can include intent, deviations, foods, and only the relevant plan
  context.
- An optional normalization model can map free text to the active user's own
  `situaciones` and `momentos` before routing. This step must receive only
  compact routing options, not the whole meal plan.
- Weekly planning requests can pass the mentioned situations and referenced
  meal blocks instead of failing as ambiguous single-meal requests.
- Today's current day type, skipped meals, and logged meals are stored in
  PostgreSQL as one editable daily state per user/profile/date.
- Same-day corrections such as "al final no he ido al crossfit" update the
  current day type and use that situation for the next meal recommendation.
- Same-day replacements such as "cambio crossfit por natacion" update the
  current day type to the replacement activity.
- Ambiguous or incomplete queries ask for the missing context.
- The prompt receives only the resolved block, not the full plan.

The router contract stays the same regardless of how the user's plan was
uploaded or normalized.

## MVP 3: Daily Tracking

Goal: record meals and answer daily progress questions.

Issue:

- #90: Daily tracking MVP.

Definition of done:

- User can register a meal in natural language.
- Bot preserves the original meal text.
- Bot compares simple records with the active plan.
- Bot answers "como voy hoy" with a practical next step.
- Bot can handle skipped meal context without automatic overcompensation.

## MVP 4: Advanced Documents

Goal: add richer plan interpretation without breaking V1.

Issue:

- #91: Advanced documents and future management.

Implementation note: #91 is a phased backlog, not a single all-in-one build.
Ship the smallest useful slice first, usually `situaciones`, before recipes,
RAG, review queues, or weekly planning.

Definition of done:

- `situaciones` maps day context and meal moment to comida keys.
- `situaciones` references are validated against the active `comidas` document.
- `recetas` suggests approved real dishes without overriding quantities.
- `recetas` is accessed through retrieval/RAG so prompts receive only relevant
  approved candidates, not the full catalog.
- User-submitted recipes are saved as `pending_review` until admin/professional
  review.
- Weekly planning can map a user-provided activity schedule to comidas and
  produce meals/dinners with plan quantities.
- `adaptation_rules` provides generic interpretation rules.
- Explicit plan conditions remain higher priority than generic rules.

## Out Of Scope Until Scheduled

- OCR for images.
- Batch cooking.
- Comparing multiple plans.
- Full recipe review UI beyond the JSONB/admin workflow.
- Manual JSON editing UI.
- Full nutrient database integration.

## Data Principle

The active source of truth for quantities is always the compact `comidas`
document. Future documents may select, explain, or adapt blocks, but they must
not silently override block quantities.
