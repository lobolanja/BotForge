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

Goal: create a draft plan from text or PDF and store compact `meal_blocks` as
JSONB.

Issues:

- #92: Nutrition bot design docs.
- #80: Nutrition bot profile and guardrails.
- #81: JSONB persistence for nutrition plans.
- #82: `meal_blocks` contract and validation.
- #83: `/new_plan` command and upload session.
- #84: V1 text and PDF extraction.
- #85: LLM generator for `meal_blocks`.
- #86: Save draft and summarize generated plan.

Definition of done:

- User can start `/new_plan`.
- Bot accepts compact `comidas` JSON, text, or PDF.
- Valid JSON `comidas` bypasses LLM extraction.
- Bot generates only `meal_blocks`.
- JSON preserves original food strings, notes, and conditions.
- JSON preserves nested `and`/`or` grouping recursively.
- JSON contains warnings for ambiguity.
- Draft plan and document are saved in PostgreSQL.
- Bot replies with a clear summary.

## MVP 2: Activate And Use Active Plan

Goal: use the active plan to answer practical meal questions.

Issues:

- #94: Local situations router and plan chunk selection.
- #87: Activate nutrition plan.
- #88: First responses with active plan.
- #89: Basic adaptation of concrete foods.

Definition of done:

- User can activate a valid draft.
- Only one plan is active per user.
- Without active plan, bot suggests `/new_plan`.
- With active plan, bot answers from the relevant `meal_blocks` slice.
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

## MVP 2A: Demo Plan Router Before Persistence

Goal: get useful responses from the repository demo plan before full user plan
persistence is implemented.

Issue:

- #94: Local situations router and plan chunk selection.

Definition of done:

- The nutrition profile can load the repository demo plan.
- The router detects day situations from `situaciones.*.aliases`.
- The router detects common meal moments from natural language.
- Complete queries such as `Hoy tengo crossfit, que como al mediodia?` resolve
  to one comida block before the LLM call.
- Ambiguous or incomplete queries ask for the missing context.
- The prompt receives only the resolved block, not the full demo plan.

This is a temporary but useful step. Later persistence should reuse the same
router contract against each user's active plan.

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

The active source of truth for quantities is always the compact `meal_blocks`
document. Future documents may select, explain, or adapt blocks, but they must
not silently override block quantities.
