# Nutrition Bot Orchestration

This document describes the first orchestration layer for the nutrition bot.
It exists to keep the user experience practical while avoiding token-heavy
prompts and hardcoded logic inside the generic bot engine.

## Current Pipeline

Runtime flow:

```text
Telegram message
-> profile-selected memory backend
-> local message understanding
-> context-aware LLM message normalization
-> daily nutrition log read plus deferred update preview
-> plan context selection
-> final LLM answer
-> persist daily nutrition log update after successful delivery
```

The current implementation uses LangChain Core as a lightweight pipeline:

```text
RunnableLambda(classify message locally)
-> RunnableLambda(normalize message with a configured model, optional)
-> RunnableLambda(route plan context)
```

This is intentionally small. The first step does not call an LLM. It classifies
common nutrition intents and extracts cheap signals such as mentioned weekdays,
foods, deviations, shopping-list requests, and macro requests.

The normalization step receives compact routing options from the active user's
plan plus bounded memory context. It exists to make short follow-ups natural,
for example `fútbol`, `y para cenar?`, `lo de antes`, or a correction to a food
already being discussed.

```json
{
  "situations": ["crossfit", "futbol", "pilates", "no_entreno"],
  "moments": ["desayuno", "media_manana", "almuerzo", "cena"],
  "allowed_intents": ["recommend_meal", "weekly_planning"]
}
```

It returns validated JSON such as:

```json
{
  "intent": "recommend_meal",
  "situation_key": "pilates",
  "target_moment_key": "media_manana",
  "logged_meals": [],
  "goal": "resolver snack personalizado",
  "confidence": "high"
}
```

The router validates every returned key against the active plan. Invalid
situations or moments are ignored and the deterministic router remains the
fallback.

The plan context step decides what context to send to the final model:

- single meal: one resolved `comida` block;
- full day: all resolved blocks for one situation;
- weekly planning: the situations mentioned by the user and their referenced
  meal blocks;
- shopping list: plan blocks plus conversation memory, because the useful
  weekly choices may live in recent chat.
- unresolved follow-up: candidate plan context plus memory, letting the final
  model infer naturally or ask one specific clarification.

The daily log step stores one editable state per user, profile, and real date in
PostgreSQL. It is not a replacement for conversation memory. During prompt
preparation the bot reads the current log and builds an in-memory preview of
any update implied by the message. The database write is deferred until after
the answer has been sent successfully, so failed model calls do not mutate the
user's day state. The log tracks:

- one current day type, for example `crossfit` or `natacion`;
- logged or skipped meal moments, preserving the user's raw text;
- `completed=true/false` per meal moment;
- compact notes about corrections.

When the user says "esta manana era crossfit" and later "al final no he ido,
que ceno?", the day type is updated to `no_entreno`. The same applies to
replacements such as "cambio crossfit por natacion": the current day type
becomes `natacion` if it exists in the active plan. The bot should use the daily
log to avoid asking again for context that the user already gave, while still
letting explicit new user input override stale state.

The generic `engine.py` should not know how nutrition routing works. It only
receives:

- the prompt profile to use;
- runtime instructions;
- whether recent memory should be included;
- an optional direct clarification answer;
- optional post-success actions, such as committing a daily log update.

The nutrition profile currently sets `memory_backend = langchain_postgres`.
Recent raw turns are stored through LangChain's maintained
`PostgresChatMessageHistory` implementation. BotForge keeps only the
user/profile session mapping, privacy deletion hook, and compact summary. The
backend reads bounded recent and compaction windows instead of loading the full
chat history for every prompt. The selection is profile-level configuration so
other bots can keep the plain PostgreSQL adapter or use a different memory
backend later.

## Model Routing Direction

The desired architecture is:

```text
cheap local step
-> tool/context retrieval
-> high-quality remote response model
```

Examples:

- local model, NVIDIA, or deterministic rules for cleaning and intent
  classification;
- local plan router for `situaciones + momento -> comida`;
- RAG retrieval for approved recipes;
- remote NVIDIA model for the final user-facing answer.

The current default uses NVIDIA for the optional normalization step when
configured, because no local model is available yet. The provider and model are
separate from the final answer model:

```text
NUTRITION_NORMALIZER_PROVIDER=nvidia
NUTRITION_NORMALIZER_MODEL=nvidia/llama-3.3-nemotron-super-49b-v1.5
```

When a cheaper local model is available, only this configuration should need to
change.

## Future MCP Boundaries

Likely MCP/tool boundaries:

- `nutrition_plan_context`: fetch active user plan documents from PostgreSQL;
- `nutrition_message_normalizer`: map free text to plan-specific keys;
- `nutrition_router`: resolve situation, moment, and meal block;
- `nutrition_recipes`: retrieve approved recipes from RAG;
- `nutrition_memory`: retrieve daily logs and adherence state;
- `nutrition_week_planner`: build week-level candidate plans;
- `nutrition_admin_review`: manage pending recipes and plan documents.

These should stay behind orchestration functions. The final answer model should
receive only the compact context needed for the current reply.

## UX Rules

The orchestration layer exists to protect the Telegram experience:

- prefer one useful recommendation over dumping the full plan;
- ask one short clarification when situation or meal moment is missing;
- avoid deterministic clarification loops; if the user is clearly continuing a
  previous topic, use memory before asking again;
- treat macro or "all meals/day" requests as full-day context, not as a missing
  meal moment;
- support user-specific plan vocabularies such as one user having `pilates` and
  `media_manana` while another has `futbol` and no mid-morning meal;
- use recent conversation for follow-up answers;
- use today's daily nutrition log for same-day situation changes, skipped
  meals, and meal records;
- keep memory available for non-plan questions;
- keep memory backend selection outside nutrition business logic;
- do not use stale failure messages as permanent context;
- never invent quantities outside `comidas`.

## Test Expectations

Tests should cover:

- intent classification from real informal messages;
- single-meal context selection;
- full-day and weekly-planning context selection;
- follow-up resolution using recent conversation;
- direct clarification without calling the LLM;
- memory inclusion for non-plan messages and shopping-list planning.
- daily log routing when the user asks a short follow-up such as `que ceno?`;
- training cancellation such as `al final no he ido al crossfit`.
