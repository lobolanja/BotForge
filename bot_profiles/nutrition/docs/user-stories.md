# Nutrition Bot User Stories

Stories are grouped by MVP and aligned with epic #79.

## MVP 1: Plan Capture And Draft Creation

### Story 1.1: Understand The Nutrition Bot Scope

As a bot owner, I want a nutrition-specific profile and design docs, so that
future changes inherit a clear product direction.

Acceptance criteria:

- The `nutrition` bot has versioned design docs.
- The docs say the bot interprets user plans instead of inventing diets.
- The docs distinguish design docs from user JSONB data.
- Response guardrails are documented.

Related issues: #80, #92.

### Story 1.2: Store Nutrition Plans Per User

As a user, I want my nutrition plan stored under my account, so that the bot can
use my plan without mixing it with other users.

Acceptance criteria:

- Plans reference `users(id)`.
- Plan documents are stored as JSONB.
- V1 supports `document_type = meal_blocks`.
- Plan states are constrained to `draft`, `active`, `failed`, and `archived`.

Related issue: #81.

### Story 1.3: Start A New Plan Upload

As a user, I want to send `/new_plan`, so that the bot waits for my plan text or
PDF.

Acceptance criteria:

- Only authenticated users can start the flow.
- The bot creates a `waiting_for_plan_upload` session.
- The bot tells the user to send text or PDF.
- Re-running `/new_plan` handles an existing pending session predictably.

Related issue: #83.

### Story 1.4: Upload Plan Text Or PDF

As a user, I want to provide compact JSON, paste text, or upload a PDF, so that
the bot can capture my nutrition plan.

Acceptance criteria:

- Valid compact JSON with root `comidas` is accepted directly and does not call
  the LLM extractor.
- Pasted text is accepted directly.
- PDF files are downloaded from Telegram and extracted.
- Images and unsupported documents receive a clear V1 limitation message.
- Extraction failures do not crash the bot.

Related issue: #84.

### Story 1.5: Generate Meal Blocks

As a user, I want the bot to convert my plan into structured meal blocks, so
that future answers can use the plan reliably.

Acceptance criteria:

- The final document is `document_type = meal_blocks`.
- Direct `comidas` JSON bypasses LLM generation.
- The generator does not create `situations`, `recipes`, or `adaptation_rules`
  in V1.
- Original food strings are preserved as leaves in the `comidas` tree.
- Nested `and`/`or` groups from the nutritionist's plan are preserved
  recursively.
- Ambiguities are represented as warnings.

Related issues: #82, #85.

### Story 1.6: Save Draft And Show Summary

As a user, I want to see what the bot extracted, so that I can decide whether
the plan looks usable.

Acceptance criteria:

- A valid extraction creates a draft plan.
- The bot stores the `meal_blocks` JSONB document.
- The bot summarizes blocks, food options, conditions, and warnings.
- If no blocks are detected, the flow fails clearly.

Related issue: #86.

## MVP 2: Active Plan Usage

### Story 2.0: Route Natural Language To A Plan Chunk

As a user, I want to describe my day naturally, so that the bot can select the
right comida without sending the full plan to the LLM.

Acceptance criteria:

- The bot detects situation keys from configured `situaciones.*.aliases`.
- The bot detects common meal moments such as desayuno, almuerzo, merienda, and
  cena.
- The bot resolves `situacion + momento` to a `comida_*` key before the LLM
  call.
- If either value is missing, the bot asks one concise clarification.
- If multiple situations match, the bot asks the user to choose.
- When resolution succeeds, the LLM receives only the resolved comida chunk and
  not the full plan.

Related issue: #94.

### Story 2.1: Activate A Draft Plan

As a user, I want to activate a draft plan, so that the bot uses it as the
source of truth.

Acceptance criteria:

- The bot activates only a draft owned by the user.
- The selected plan has valid `meal_blocks`.
- Only one plan is active per user.
- Previous active plans are no longer active after replacement.

Related issue: #87.

### Story 2.2: Ask What To Eat

As a user, I want to ask what to eat, so that I receive a practical answer from
my active plan.

Acceptance criteria:

- Without an active plan, the bot suggests `/new_plan`.
- With an active plan, the bot uses `meal_blocks`.
- The bot asks for meal moment when needed.
- When `situaciones` are available, the bot routes to the relevant comida chunk
  before calling the LLM.
- The answer recommends one valid option path from the resolved block rather
  than dumping all possible options.
- The recommended option follows local `and`/`or` semantics: include all
  required `and` groups and choose one child from each relevant `or` group.
- The answer includes quantities from the selected block.
- Explicit block conditions are applied or shown when they affect the selected
  option.
- Macros are hidden by default even when the plan contains macro codes.
- The user can ask for another option from the same block.
- Responses do not expose technical JSON details unless requested.

Related issues: #88, #94.

### Story 2.3: Adapt A Concrete Food

As a user, I want to ask whether I can eat a concrete food, so that the bot
adapts it to my plan.

Acceptance criteria:

- Matching uses raw food strings, group names, notes, and conditions
  conservatively.
- If the food appears in the block, the bot uses the block quantity.
- If a condition applies, the bot explains the key adjustment.
- If compatibility is unclear, the bot asks or offers a plan option.

Related issue: #89.

### Story 2.4: Ask What To Eat For A Specific Activity Day

As a user, I want to say what activity I have today, so that the bot can select
the correct comida before suggesting food.

Acceptance criteria:

- The bot maps user activity words to configured `situaciones` keys.
- The bot resolves `situacion + momento` to a `comida_*` key.
- The bot uses `aliases` from the plan instead of hardcoding only one set of
  sports.
- If the activity or moment is ambiguous, the bot asks using configured options.
- The bot answers with quantities from the resolved comida.

Related issues: #88, #91, #94.

## MVP 3: Daily Tracking

### Story 3.1: Register A Meal

As a user, I want to tell the bot what I ate, so that it can track my day.

Acceptance criteria:

- The bot stores meal records by user and day.
- The original user text is preserved.
- The bot detects or asks for meal moment.
- The bot can compare the record against the active plan at a basic level.

Related issue: #90.

### Story 3.2: Ask How The Day Is Going

As a user, I want to ask how I am doing today, so that I can decide what to eat
next.

Acceptance criteria:

- The bot loads today's meal records.
- The bot summarizes alignment with the active plan.
- The bot gives one practical next-step recommendation.
- The bot avoids shame, punishment, and extreme compensation.

Related issue: #90.

### Story 3.3: Adjust After A Skipped Meal

As a user, I want to tell the bot that I skipped a meal, so that the next meal
recommendation stays practical and does not overcompensate.

Acceptance criteria:

- The bot detects skipped meal context such as "me he saltado la media manana".
- The bot records the skipped meal when daily tracking exists.
- The bot keeps the next recommendation anchored to the selected comida.
- The bot does not automatically move all skipped quantities into the next meal.
- If the plan has explicit compensation notes, those notes take priority.

Related issues: #88, #90.

## MVP 4: Advanced Documents

### Story 4.1: Use Situations

As a user, I want the bot to know whether today is a training or rest day, so
that it can choose the right block.

Acceptance criteria:

- `situaciones` exists as a JSONB document type or supported content shape.
- Situations map day context and meal moment to `comida_*` keys.
- Situation keys are plan data, not hardcoded sports.
- Every referenced comida key exists in the active `comidas` document.
- Supplementation is preserved but not repeated in every meal answer.
- Missing situation context triggers a short clarification.
- Missing meal moment triggers a short clarification or a later time-based
  suggestion with user correction.
- Missing mappings do not invent comidas.

Related issue: #91.

### Story 4.2: Use Recipes

As a user, I want real meal suggestions, so that the plan feels practical.

Acceptance criteria:

- `recetas` exists as a JSONB document type or future row-per-recipe storage.
- Recipes suggest dishes but do not override `meal_blocks` quantities.
- Recipe compatibility is scoped by meal moment and compact plan context.
- The bot uses only recipes with `status = approved`.
- The bot retrieves recipes through search/RAG and does not pass the full
  catalog to the LLM.
- Only a small set of approved candidates is added to prompt context.
- Recipes can be filtered by moment, carb level, protein type, restrictions,
  and preferences.

Related issue: #91.

### Story 4.3: Submit Recipe For Review

As a user, I want to propose a recipe I usually eat, so that a professional can
review whether it should be added to the catalog.

Acceptance criteria:

- User-submitted recipes are stored as `pending_review`.
- The bot confirms that a professional must review the recipe before use.
- The bot never uses pending recipes for normal recommendations.
- Admin/professional users can approve, reject, edit, or archive recipes.
- Approved recipes include required structured fields and `status = approved`.

Related issue: #91.

### Story 4.4: Build A Weekly Meal Plan

As a user, I want to give the bot my weekly activity schedule, so that it can
generate a practical plan for meals and dinners.

Acceptance criteria:

- The bot accepts day-by-day activity input in natural language.
- The bot maps each day to configured `situaciones` keys.
- Explicit defaults such as "el resto no entreno" are applied to omitted days.
- For each requested moment, the bot resolves a `comida_*` key before answering.
- The weekly plan uses quantities from `comidas`.
- If recipe RAG is available, only approved candidates are retrieved per
  day/moment.
- Missing mappings or unknown activities trigger clarification instead of
  invented meals.

Related issue: #91.

### Story 4.5: Use Adaptation Rules

As a user, I want the bot to adjust meals consistently, so that equivalent
foods do not break the plan.

Acceptance criteria:

- `adaptation_rules` exists as a JSONB document type.
- Rules document macro interpretation and conservative substitutions.
- Explicit plan conditions still take priority.

Related issue: #91.
