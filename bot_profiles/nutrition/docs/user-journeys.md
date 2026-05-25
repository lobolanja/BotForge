# Nutrition Bot User Journeys

These journeys describe the intended user experience for the nutrition bot.
They should drive implementation decisions and test scenarios.

## Journey 1: First Use Without A Plan

Actor: authenticated Telegram user.

Goal: understand that the bot needs a nutrition plan before giving useful
nutrition guidance.

Flow:

1. User opens the bot after invite-based onboarding.
2. User sends a nutrition question such as "Que como hoy?".
3. Bot checks whether the user has an active nutrition plan.
4. No active plan exists.
5. Bot explains briefly that it needs the user's plan from their nutritionist.
6. Bot suggests `/set_plan`.

Expected response:

```text
Para ayudarte bien necesito tu plan nutricional.

Envia /set_plan y despues sube situaciones.json y comidas.json como documentos.
```

Edge cases:

- If the user asks for generic advice, the bot can give general, safe guidance
  but must not pretend it has a plan.
- If the user mentions a medical condition, the bot should recommend checking
  with a qualified professional.

## Journey 2: Set An Active Plan With /set_plan

Actor: authenticated Telegram user.

Goal: upload `situaciones.json` and `comidas.json` and store them as the active
user plan.

Flow:

1. User sends `/set_plan`.
2. Bot explains that the user can upload `situaciones.json` and `comidas.json`
   without captions.
3. User attaches `situaciones.json`.
4. Bot stores that part in a draft and replies that `comidas` is missing.
5. User attaches `comidas.json`.
6. Bot combines both parts and validates situations, meal references, meal
   blocks, and nested `and`/`or` groups.
7. Bot archives any previous active plan for that user.
8. Bot stores the new `nutrition_plan` in `active` status.
9. Bot stores `nutrition_plan_documents.document_type = situaciones` and
   `document_type = comidas`.
10. Bot replies with a short summary.

Expected response:

```text
Plan nutricional activo actualizado.

He detectado:
- 6 bloques de comida
- 3 situaciones
- normalizacion: LLM
```

Edge cases:

- Unsupported file: explain that V1 accepts `.json` or `.txt`.
- Only one part uploaded: keep the draft and ask for the missing file.
- Invalid JSON and no LLM normalization: ask the user to send valid JSON.
- Invalid references: reject the plan and explain that a situation points to a
  missing meal block.
- Existing active plan: archive it only after the new plan validates.

## Journey 3: Review Generated Plan Summary

Actor: authenticated Telegram user.

Goal: inspect whether extraction looks reasonable.

Flow:

1. Bot finishes `/set_plan`.
2. Bot shows a summary of extracted blocks.
3. User reviews block names, macro hints, warnings, and option counts.
4. User decides whether to keep it active or upload a corrected version.

Expected response:

```text
Resumen del plan:

1. Desayuno
   Macros detectados: 40 HC / 20 P / 20 G
   Opciones detectadas: 12

2. Cena
   Macros detectados: 10 HC / 70 P / 20 G
   Opciones detectadas: 18

Avisos:
- 1 cantidad no se pudo interpretar.
- 2 condiciones se guardaron como texto.
```

Edge cases:

- No active plan exists: suggest `/set_plan`.
- Critical validation errors: do not store the plan.
- Non-critical warnings: store the plan if the core routing is valid.

## Journey 4: Replace The Active Plan

Actor: authenticated Telegram user.

Goal: replace an active plan without leaving the user with a broken plan.

Flow:

1. User already has an active plan.
2. User sends a new JSON plan with `/set_plan`.
3. Bot validates and normalizes the new plan.
4. Bot archives the previous active plan.
5. Bot marks the new plan as `active`.
6. Bot confirms the change.

Expected response:

```text
Plan nutricional activo actualizado.

A partir de ahora usare este plan para interpretar tus comidas.
```

Edge cases:

- No active plan: suggest `/set_plan`.
- New upload has no valid blocks: keep the previous active plan.
- Existing active plan: replace it only for the same user.

## Journey 5: Ask What To Eat

Actor: authenticated Telegram user with an active plan.

Goal: get one practical meal recommendation from the user's active plan.

This is the most basic successful use case for the bot after the user already
has a nutrition plan loaded. The user should not need to understand `comidas`,
macros, `situaciones`, or internal block keys.

Flow:

1. User asks "Que ceno?", "Que como hoy dia de no entreno?", or "Hoy tengo
   crossfit, que como al mediodia?".
2. Bot detects recommendation intent.
3. Bot detects or asks for day situation when `situaciones` is available.
4. Bot detects or asks for the meal moment.
5. Bot resolves `situacion + momento` to a `comida_*` key locally.
6. Bot loads only that comida chunk.
7. Bot selects one valid option path through the block:
   - for `and`, include each required group;
   - for `or`, choose one reasonable option;
   - preserve explicit conditions such as removing oil for fatty fish.
8. Bot answers as a normal meal recommendation with quantities from the plan.
9. Bot does not show macros unless the user asks for macros, calories, or
   detailed targets.

Expected response:

```text
Cena:
330g de merluza con ensalada.

Añade 20g de aceite de oliva o cambia esa grasa por 160g de aguacate.
```

Edge cases:

- Missing meal moment: ask a short clarification.
- Missing day situation: ask using the configured options for that user's plan,
  such as cycling, athletics, football, strength, rest, or any other defined
  activity.
- Multiple day situations detected: ask the user which one should drive the
  plan for this meal.
- No active plan: suggest `/set_plan`.
- Missing mapping: do not invent a comida.
- Complete mapping: do not send the full plan to the LLM; send only the
  resolved chunk.
- If the user asks "quiero otra opcion", choose a different valid option path
  from the same resolved block when possible.
- If the user asks "por que?", explain the selected groups and conditions
  without exposing raw JSON.
- If no reasonable concrete option can be selected automatically, show two or
  three valid choices from the block and ask which one prefers.

## Journey 6: Adapt A Concrete Food Or Dish

Actor: authenticated Telegram user with an active plan.

Goal: know how to fit a desired food into the plan.

Flow:

1. User says "Voy a cenar salmon" or "Puedo meter pasta?".
2. Bot detects the food and meal moment.
3. Bot loads the relevant block.
4. Bot checks raw food strings, group names, notes, and conditions
   conservatively.
5. Bot applies explicit conditions when present.
6. Bot gives a short adjustment.

Expected response:

```text
Cena:
Salmon con ensalada.

Sin aceite, porque el salmon ya aporta grasa.
```

Edge cases:

- Food appears in block: use the block quantity.
- Food is a clear equivalent: adapt cautiously and say it is an approximation.
- Food is not compatible: offer a close option from the block.
- Fatty protein: apply oil removal or reduction if the plan says so.

## Journey 7: Register A Meal

Actor: authenticated Telegram user with an active plan.

Goal: record what they ate.

Flow:

1. User says "He comido pollo con arroz y ensalada".
2. Bot detects this is a meal log.
3. Bot detects or asks for meal moment.
4. Bot stores the event.
5. Bot compares it against the expected block when possible.
6. Bot replies with a simple assessment.

Expected response:

```text
Registrado.

Encaja bastante bien. Vigila no anadir otro hidrato fuerte en la siguiente comida.
```

Edge cases:

- No quantities: register approximate text.
- Missing moment: infer from time only when confidence is acceptable.
- User corrects later: update the event instead of duplicating it.

## Journey 8: Ask Daily Progress

Actor: authenticated Telegram user with an active plan and meal records.

Goal: understand how the day is going.

Flow:

1. User asks "Como voy hoy?".
2. Bot loads today's recorded meals.
3. Bot compares records against expected blocks.
4. Bot summarizes the day.
5. Bot recommends the next practical decision.

Expected response:

```text
Vas bastante bien.

La comida ha sido algo alta en grasa, asi que para la cena haria:
proteina magra + verdura, sin grasa extra.
```

Edge cases:

- No records: say there is not enough data yet.
- Excess carbs: suggest a lighter next meal if compatible with plan.
- Excess fat: suggest lean protein and vegetables.
- Missing protein: prioritize protein next.

## Journey 9: Recover From A Deviation

Actor: authenticated Telegram user with an active plan.

Goal: return to the plan without guilt or extreme compensation.

Flow:

1. User says "Me he pasado con los dulces".
2. Bot classifies the deviation conservatively.
3. Bot records the event when tracking exists.
4. Bot suggests the next meal adjustment.
5. Bot avoids punishment, shame, or extreme restriction.

Expected response:

```text
No lo compensaria con castigo.

Siguiente comida:
proteina magra + verdura.

Sin pan, arroz, pasta ni grasa extra.
```

Edge cases:

- Possible binge or distress: recommend professional support.
- Alcohol: suggest hydration, normal eating, and rest.
- Repeated deviations: focus on patterns and next simple step.

## Journey 10: Submit A Recipe Proposal

Actor: authenticated Telegram user.

Goal: propose a real recipe for future review.

Flow:

1. User says "Quiero anadir una receta de arroz con atun y huevo".
2. Bot detects that this is a recipe proposal, not a meal log.
3. Bot stores the proposal as `pending_review`.
4. Bot preserves the raw user text and attachments when available.
5. Bot confirms that the recipe needs admin/professional review before use.

Expected response:

```text
He guardado la receta como propuesta.

Un profesional tendra que revisarla antes de que el bot pueda usarla dentro del plan.
```

Edge cases:

- If the user only mentions a meal they ate, do not treat it as a recipe
  proposal unless intent is clear.
- If required fields are unknown, keep them empty and preserve raw submission.
- The bot must not recommend pending recipes to normal users.

## Journey 11: Review A Recipe Proposal

Actor: admin or nutrition professional.

Goal: turn a pending recipe into an approved, rejected, edited, or archived
catalog entry.

Flow:

1. Admin/professional lists pending recipes.
2. Admin/professional reviews raw submission.
3. Admin/professional normalizes fields such as protein, carbs, fat level,
   compatibility, tags, and adaptation notes.
4. Admin/professional approves, rejects, edits, or archives.
5. Approved recipes become available for normal bot recommendations.

Edge cases:

- Rejected recipes keep review notes.
- Approved recipes must have all required structured fields.
- Only approved recipes are used by the bot outside review mode.

## Journey 12: Build A Weekly Meal Plan

Actor: authenticated Telegram user with active `comidas` and `situaciones`.

Goal: receive a practical weekly plan for meals and dinners based on planned
activities.

Example request:

```text
Hazme un plan de comidas y cenas para la semana.
Lunes ciclismo, miercoles fuerza, viernes atletismo y el resto no entreno.
```

Flow:

1. Bot detects a weekly planning intent.
2. Bot extracts day-by-day situations from the message.
3. Bot maps user words to configured situation keys when confidence is high.
4. Bot asks a clarification if an activity is not configured or ambiguous.
5. For each day and requested moment, bot resolves `situacion + momento` to a
   `comida_*` key.
6. Bot loads only the selected comidas.
7. If `recetas` RAG is available, bot retrieves approved recipe candidates per
   day/moment.
8. Bot returns a compact weekly table with comida/cena, quantities from
   `comidas`, and recipe-style names when available.

Expected response shape:

```text
Plan semanal

Lunes - ciclismo
Comida: arroz tipo paella con pollo o pavo.
Usa el arroz y la proteina del bloque comida_2. No anadas pan.
Cena: pescado blanco con ensalada y la grasa del bloque.

Martes - no entreno
Comida: carne magra con verdura y la fuente de hidrato de comida_5.
Cena: tortilla con ensalada, ajustando el aceite del bloque.
```

Edge cases:

- If the user says "algo" or an unknown activity, ask which configured situation
  it corresponds to.
- If a day is omitted, use the user's stated default only when explicit, such as
  "el resto no entreno".
- If a moment mapping is missing, show that day/moment as unresolved instead of
  inventing a comida.
- Do not pass all recipes or all comidas to the LLM. Resolve keys first, then
  retrieve only needed slices/candidates.

## Journey 13: Adjust After Skipping A Meal

Actor: authenticated Telegram user with an active plan.

Goal: decide what to eat after missing a planned meal without overcompensating.

Example request:

```text
Que ceno hoy? Me he saltado la media manana.
```

Flow:

1. Bot detects target moment: `cena`.
2. Bot detects skipped moment: `media_manana` or nearest configured equivalent.
3. Bot loads today's situation if known, or asks for it if needed.
4. Bot resolves dinner with `situaciones`.
5. Bot checks whether the skipped meal affects dinner instructions.
6. Bot recommends dinner from the dinner comida and avoids inventing extra
   compensation.

Expected response:

```text
Cena:
Pescado blanco con ensalada.

Mantendria la cena del bloque. No hace falta compensar metiendo el doble.
Si tienes hambre, prioriza la proteina y la verdura del plan.
```

Edge cases:

- If the skipped meal was a snack and there is no explicit compensation rule,
  do not move its full quantities into dinner.
- If the user skipped several meals or reports distress, respond conservatively
  and recommend professional guidance when appropriate.
- If daily tracking exists, record the skipped meal as an event.
