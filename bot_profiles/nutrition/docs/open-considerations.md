# Nutrition Bot Open Considerations

This document lists important gaps and design decisions that must stay visible
before the bot gives more advanced nutrition guidance.

The bot is not a clinician. It helps apply a nutrition plan already provided by
a professional. It should stay inside that scope unless a qualified
professional reviews and approves broader behavior.

## Product Scope Risks

The bot must not drift from plan interpreter to diet prescriber.

Allowed:

- explain the user's active plan;
- choose the correct comida for a situation and moment;
- adapt a real dish to the selected comida;
- build weekly menus from configured situaciones and comidas;
- track meals and help the user return to the plan calmly.

Not allowed without professional review:

- create a new diet from scratch;
- prescribe calories or macros not present in the plan;
- diagnose or treat medical conditions;
- recommend aggressive compensation after missed meals or deviations;
- approve user-submitted recipes automatically.

## User Data We Probably Need

Future planning will be weak unless the bot knows or can ask for:

- active nutrition plan;
- configured situaciones for that user;
- allergies and intolerances;
- foods the user refuses or cannot access;
- dietary pattern such as vegetarian, vegan, halal, kosher, gluten-free, or
  lactose-free;
- cooking constraints, such as no kitchen, meal prep, restaurant meals, or
  travel;
- training schedule, including sport, day, rough time, intensity, and duration;
- meal schedule, including skipped or shifted meals;
- professional restrictions from the plan;
- user preferences and budget.

This data should be explicit and user-controlled. Do not infer sensitive health
details from casual text unless the user states them clearly.

## Safety Flags

The bot should stop normal plan optimization and recommend professional help
when the user mentions:

- pregnancy or breastfeeding;
- diabetes, kidney disease, cardiovascular disease, cancer, gastrointestinal
  disease, or any condition where diet is part of treatment;
- medication interactions or supplements used as treatment;
- eating disorder history or signs of disordered eating;
- repeated binge episodes, purging, fasting as punishment, or extreme
  restriction;
- minors or guardians asking for restrictive dieting;
- fainting, chest pain, persistent vomiting, severe dehydration, or similar
  acute symptoms.

In those cases the bot can help organize information, but should not adjust the
plan independently.

## Eating Disorder And Compensation Guardrails

The bot must avoid language that reinforces guilt or punishment.

Do:

- acknowledge the event neutrally;
- recommend returning to the next planned meal;
- suggest simple, plan-compatible choices;
- mention professional support when distress or repeated loss of control is
  present.

Do not:

- tell the user to fast as punishment;
- double or remove full meal blocks without an explicit plan rule;
- encourage weighing, checking, or restriction loops;
- frame foods as moral failure.

Skipped meals need special handling. If the user says they skipped `media
manana`, the default should be to keep the next meal anchored to its comida. Do
not move all skipped quantities into dinner unless the plan explicitly says so.

## Weekly Planning Gaps

Weekly planning needs more than a single meal lookup.

Required inputs:

- days requested;
- situation per day, or explicit defaults like "el resto no entreno";
- moments requested, such as comidas and cenas;
- active situaciones document;
- active comidas document;
- optional approved recipe retrieval.

Open decisions:

- how to store a generated weekly plan;
- whether the weekly plan is temporary chat output or persisted;
- how users edit a day after generation;
- how to handle activities not configured in situaciones;
- how to avoid repeating the same recipe too often;
- how to handle batch cooking later without turning it into a new diet.

Recommended first behavior:

- generate the plan as chat output only;
- use configured situaciones only;
- ask when an activity is unknown;
- use quantities from comidas;
- use RAG only for approved recipe candidates;
- keep the table compact.

## Activity And Training Context

Situation keys are plan data, not hardcoded sports.

The same user may have:

- crossfit;
- futbol;
- ciclismo;
- atletismo;
- natacion;
- fuerza;
- senderismo;
- competicion;
- viaje;
- descanso_activo;
- no_entreno.

The bot should not assume all training days are nutritionally identical. If the
plan distinguishes activities, use that. If it does not, ask or use the closest
configured option only with user confirmation.

## Recipes And RAG Risks

Recipe RAG is useful, but the source of truth is still the plan.

Important rules:

- index only `approved` recipes for normal users;
- keep pending recipes out of normal retrieval;
- pass only a few compact candidates to the LLM;
- never let recipe quantities override comidas;
- keep review metadata outside normal prompts;
- log enough metadata to understand which recipe candidate was used.

Open decisions:

- vector store or database search;
- embedding model and language handling;
- per-user recipe catalogs vs global approved catalog;
- how to include allergies/restrictions in retrieval;
- how admins/professionals review user-submitted recipes.

## Supplementation

`situaciones.suplementacion` should be preserved, but not repeated in every meal
answer.

The bot should mention supplements only when:

- the user asks about supplementation;
- the user asks for a full day plan;
- the supplement timing affects the requested plan;
- the professional plan explicitly includes it.

The bot should not add new supplements or change supplement dosage without
professional review.

## Allergies, Intolerances, And Food Safety

Before recommending recipes broadly, the bot needs a reliable place for
allergies and intolerances.

If a recipe contains a user-declared allergen, it must not be recommended even
if it matches the comida.

Food safety should stay simple:

- do not recommend unsafe handling or storage;
- avoid risky raw foods for vulnerable groups;
- do not override professional or medical advice.

## Validation Gaps

Current contracts need validators for:

- `comidas` recursive and/or trees;
- missing or empty groups;
- references from situaciones to existing comida keys;
- recipe statuses;
- recipe required fields before approval;
- pending recipe review metadata;
- unknown or ambiguous activity mapping;
- weekly planning defaults.

Important: validation should catch configuration errors before the bot gives a
recommendation.

## Explainability

For normal users, explain simply:

```text
Uso el bloque de crossfit para la comida.
Por eso te propongo arroz con pollo y verduras, usando la cantidad del bloque.
```

For admins/professionals, provide enough traceability:

- situation key;
- moment key;
- comida key;
- recipe candidate key if used;
- relevant condition applied;
- warnings that affected the answer.

Do not expose raw JSON in normal user replies unless asked.

## References

These are high-level safety references, not implementation requirements:

- [WHO healthy diet guidance](https://www.who.int/news-room/fact-sheets/detail/healthy-diet)
  emphasizes adequacy, balance, moderation, diversity, and food safety.
- [USDA Dietary Health overview](https://www.usda.gov/about-food/nutrition-research-and-programs/dietary-health)
  describes healthy eating guidance as adaptable to personal preferences,
  cultural traditions, and budget.
- [NIMH eating disorder information](https://www.nimh.nih.gov/health/publications/eating-disorders)
  reinforces that eating disorder symptoms need appropriate treatment and
  support.
