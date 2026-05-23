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
6. Bot suggests `/new_plan`.

Expected response:

```text
Para ayudarte bien necesito tu plan nutricional.

Puedes subirlo con /new_plan en texto o PDF.
```

Edge cases:

- If the user asks for generic advice, the bot can give general, safe guidance
  but must not pretend it has a plan.
- If the user mentions a medical condition, the bot should recommend checking
  with a qualified professional.

## Journey 2: Create A Draft Plan With /new_plan

Actor: authenticated Telegram user.

Goal: upload or paste a nutrition plan and convert it into `meal_blocks`.

Flow:

1. User sends `/new_plan`.
2. Bot creates or refreshes a `waiting_for_plan_upload` session.
3. Bot asks the user to send compact `comidas` JSON, paste plan text, or upload
   a PDF.
4. User sends JSON, text, or a PDF document.
5. If the input is valid `comidas` JSON, bot skips LLM extraction.
6. If the input is text/PDF, bot extracts readable text.
7. For text/PDF only, bot asks the LLM to generate compact `meal_blocks`,
   preserving nested `and`/`or` groups from the source plan.
8. Bot validates the JSON.
9. Bot stores a new `nutrition_plan` in `draft` status.
10. Bot stores `nutrition_plan_documents.document_type = meal_blocks`.
11. Bot replies with a summary.

Expected response:

```text
Plan creado en borrador.

He detectado:
- 6 bloques de comida
- 58 opciones alimentarias
- 8 condiciones
- 4 avisos de revision

Estado: draft
```

Edge cases:

- Unsupported file: explain that V1 accepts `comidas` JSON, text, or PDF.
- Unreadable PDF: ask the user to paste text or upload a clearer PDF.
- Partial extraction: save draft if valid blocks exist and include warnings.
- No blocks detected: mark the session failed and ask for a better source.
- Existing active plan: create a new draft without overwriting the active plan.

## Journey 3: Review Generated Plan Summary

Actor: authenticated Telegram user.

Goal: inspect whether extraction looks reasonable.

Flow:

1. Bot finishes `/new_plan`.
2. Bot shows a summary of extracted blocks.
3. User reviews block names, macro hints, warnings, and option counts.
4. User decides whether to activate later, upload a new version, or wait.

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

- No draft exists: suggest `/new_plan`.
- Critical warnings: recommend uploading a clearer document before activation.
- Non-critical warnings: allow later activation with warning.

## Journey 4: Activate A Draft Plan

Actor: authenticated Telegram user.

Goal: select a draft plan as the active source of truth.

Flow:

1. User asks to activate the generated plan.
2. Bot finds the latest draft owned by the user.
3. Bot validates that it contains valid `meal_blocks`.
4. Bot deactivates or archives previous active plans for the same user.
5. Bot marks the selected plan as `active`.
6. Bot confirms the change.

Expected response:

```text
Plan activado.

A partir de ahora usare este plan para interpretar tus comidas.
```

Edge cases:

- No draft: suggest `/new_plan`.
- Draft has no valid blocks: do not activate.
- Existing active plan: replace it only for the same user.

## Journey 5: Ask What To Eat

Actor: authenticated Telegram user with an active plan.

Goal: get a practical meal recommendation from the plan.

Flow:

1. User asks "Que ceno?" or "Que como hoy?".
2. Bot detects recommendation intent.
3. Bot detects or asks for day situation when `situaciones` is available.
4. Bot detects or asks for the meal moment.
5. Bot resolves `situacion + momento` to a `comida_*` key.
6. Bot chooses compatible options from that comida.
7. Bot replies briefly with the meal structure.

Expected response:

```text
Cena:
Pescado blanco con ensalada.

Usa la grasa del bloque si corresponde.
```

Edge cases:

- Missing meal moment: ask a short clarification.
- Missing day situation: ask using the configured options for that user's plan,
  such as cycling, athletics, football, strength, rest, or any other defined
  activity.
- No active plan: suggest `/new_plan`.
- Missing mapping: do not invent a comida.

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
