# Nutrition Bot Data Contracts

These contracts describe JSONB documents stored per user in PostgreSQL. They
are not repository files per user.

The V1 contract should stay compact. The bot needs a faithful structured plan,
not a fully normalized food database. Expensive enrichment such as food tags,
parsed quantities, recipe matching, or substitutions can be computed later and
only for the relevant meal/query.

## Storage Model

V1 storage:

- `nutrition_plans`: one row per uploaded/generated plan.
- `nutrition_plan_documents`: JSONB documents belonging to a plan.
- `nutrition_plan_upload_sessions`: state for `/new_plan` uploads.

`nutrition_plans.user_id` references `users(id)` as `INTEGER`.

Plan states:

- `draft`
- `active`
- `failed`
- `archived`

Upload session states:

- `waiting_for_plan_upload`
- `processing`
- `completed`
- `cancelled`
- `failed`
- `expired`

Document types live in the database row, not necessarily inside the JSONB
content. For V1:

- `nutrition_plan_documents.document_type = meal_blocks`
- `nutrition_plan_documents.content = compact comidas document`

Input priority for `/new_plan`:

1. Valid compact JSON with root `comidas`: validate and store directly.
2. Pasted text: extract/generate compact `comidas`.
3. PDF: extract text, then generate compact `comidas`.

Direct JSON is the most reliable and lowest-cost path. It should bypass LLM
generation.

## V1 Compact Meal Blocks Document

V1 stores the same functional shape as the extracted `comidas.json` example:

```json
{
  "comidas": {
    "comida_0": {
      "descripcion": "Merienda simple",
      "macros_plan": {
        "codigos": {
          "actual": "0.2.0"
        },
        "interpretacion": {
          "actual": {
            "hidratos_g": 0,
            "proteina_g": 20,
            "grasa_g": 0
          }
        }
      },
      "and": [
        {
          "nombre": "proteina",
          "or": ["25g de proteina Whey"]
        }
      ]
    }
  }
}
```

Rules:

- Top-level `comidas` is required.
- `comidas` is an object keyed by stable ids such as `comida_0`.
- Each comida must have `descripcion`.
- Each comida should have exactly one root operator: `and` or `or`.
- `and` and `or` may be nested at any depth.
- Food leaves remain plain strings.
- The original food text must never be discarded.
- `condiciones` and `notas` remain arrays of strings.
- `warnings` may be added at document, comida, or node level when extraction is
  ambiguous.

This shape is intentionally cheaper in tokens than object-per-food structures.

## Situations Router Document

`situaciones` is the operational router between natural day context and meal
blocks. It does not contain food quantities. It only answers:

```text
tipo de dia + momento -> comida_key
```

Current compact shape:

```json
{
  "momentos": {
    "desayuno": {
      "label": "Desayuno",
      "aliases": ["desayuno", "desayunar"]
    },
    "media_manana": {
      "label": "Media mañana",
      "aliases": ["media mañana", "media manana"]
    },
    "almuerzo": {
      "label": "Almuerzo",
      "aliases": ["almuerzo", "comida", "mediodia", "medio dia"]
    },
    "pre_entreno": {
      "label": "Pre entreno",
      "aliases": ["pre entreno", "antes de entrenar"]
    },
    "post_entreno": {
      "label": "Post entreno",
      "aliases": ["post entreno", "despues de entrenar"]
    },
    "cena": {
      "label": "Cena",
      "aliases": ["cena", "cenar", "ceno", "noche"]
    }
  },
  "situaciones": {
    "crossfit": {
      "label": "CrossFit o entrenamiento de fuerza alta intensidad",
      "aliases": ["crossfit", "fuerza", "gym", "gimnasio", "hiit"],
      "tipo_dia": "entrenamiento_fuerza_por_la_tarde",
      "suplementacion": ["10g de creatina monohidrato creapure"],
      "momentos": {
        "desayuno": "comida_1",
        "almuerzo": "comida_2",
        "merienda": "comida_0",
        "cena": "comida_3"
      }
    }
  }
}
```

Rules:

- Top-level `situaciones` is required when day routing is enabled.
- Each situation key is stable and internal, for example `crossfit`,
  `futbol`, `ciclismo`, `atletismo`, or `no_entreno`.
- `aliases` is part of the practical contract. It lets the local router map
  natural language such as `bici`, `gym`, `partido`, or `correr` to stable
  situation keys without a model call.
- Root `momentos` defines the meal moments supported by that plan and their
  natural-language aliases.
- `situaciones.*.momentos` maps plan-specific meal moments to existing
  `comidas` keys.
- Every `momentos.*` value must reference an existing key in `comidas`.
- `suplementacion` must be an array of strings. Preserve it, but do not mention
  it in every meal response unless the user asks about supplements or daily
  planning.
- Situation names are configurable. The code must not hardcode only crossfit,
  football, or rest days.
- Moment names are configurable. Some users may have `media_manana`,
  `pre_entreno`, `post_entreno`, or no `merienda`; that must be plan data, not
  hardcoded runtime behavior.
- Training timing is also plan data. If morning and afternoon training change
  the routing, model them as distinct situation keys such as
  `crossfit_manana` and `crossfit_tarde`, with aliases that capture natural
  language. If the user says only `crossfit`, ask which situation applies.

## Runtime Chunking Contract

The full plan should not be sent to the LLM when the runtime can resolve a
smaller slice locally.

Preferred V1 flow:

```text
mensaje del usuario
-> normalizar texto
-> detectar situation_key desde situaciones.*.aliases
-> detectar si el usuario pide un dia completo
-> detectar moment_key desde momentos.*.aliases
-> resolver situaciones[situation_key].momentos[moment_key]
-> obtener comidas[comida_key]
-> llamar al LLM solo con ese chunk
```

Chunk sent to the LLM when resolution is complete:

```json
{
  "nutrition_context": {
    "mode": "single_meal",
    "situation_key": "crossfit",
    "moment_key": "almuerzo",
    "meal_block_key": "comida_2",
    "supplementation": ["10g de creatina monohidrato creapure"],
    "meal_block": {
      "descripcion": "Elige y combina. E.F",
      "and": []
    }
  }
}
```

Chunk sent to the LLM when the user asks for the whole day:

```json
{
  "nutrition_context": {
    "mode": "full_day",
    "situation_key": "ciclismo",
    "supplementation": ["10g de creatina monohidrato creapure"],
    "meal_blocks": [
      {
        "moment_key": "desayuno",
        "moment_label": "Desayuno",
        "meal_block_key": "comida_1",
        "meal_block": {}
      },
      {
        "moment_key": "almuerzo",
        "moment_label": "Almuerzo",
        "meal_block_key": "comida_2",
        "meal_block": {}
      }
    ]
  }
}
```

Rules:

- The chunk is read-only context.
- The LLM may explain and format the block, but must not invent quantities.
- If `situation_key` or `moment_key` is missing, ask one short clarification
  instead of sending the full plan.
- If the user clearly asks for the whole day, resolve all canonical moments
  configured for that situation and send only those meal blocks. Do not include
  alias-only moment keys such as `comida` or `mediodia` when they point to the
  same canonical `almuerzo` block.
- If multiple situations match with similar confidence, ask the user to choose.
- If the resolved `meal_block_key` is missing from `comidas`, treat it as
  configuration error.
- The full `comidas` document may be used for validation or local lookup, not
  as routine prompt payload.

## Node Contract

Nodes represent a recursive logical tree. Nutrition plans often nest choices,
for example: choose one breakfast option, then inside that option combine pan,
protein, and fat, then choose one item from each of those groups.

Group node:

```json
{
  "nombre": "proteinas",
  "or": [
    "240g de pechuga de pollo",
    {
      "nombre": "opcion_pescado",
      "or": ["330g de salmon fresco"],
      "condiciones": ["si eliges pescado azul, eliminar el aceite"]
    }
  ],
  "notas": ["Texto original importante"],
  "condiciones": ["Texto original de condicion"]
}
```

Nested `or -> and -> or` example:

```json
{
  "descripcion": "Elige una de las siguientes opciones",
  "or": [
    {
      "nombre": "pan_proteina_grasa",
      "and": [
        {
          "nombre": "pan",
          "or": ["80g de pan integral"]
        },
        {
          "nombre": "proteina",
          "or": ["120g de pavo", "2 latas de atun al natural"]
        },
        {
          "nombre": "grasa",
          "or": ["20g de aceite de oliva", "160g de aguacate"]
        }
      ]
    }
  ]
}
```

Nested `and -> or -> and -> or` example:

```json
{
  "descripcion": "Elige y combina",
  "and": [
    {
      "nombre": "grasas",
      "or": ["20g de aceite de oliva", "160g de aguacate"]
    },
    {
      "nombre": "proteinas",
      "or": [
        "240g de pechuga de pollo",
        {
          "nombre": "huevos_con_acompanamiento",
          "and": [
            {
              "nombre": "huevos",
              "or": ["2 huevos"]
            },
            {
              "nombre": "acompanamiento",
              "or": ["160g de carne fresca", "220g de pescado"]
            }
          ],
          "condiciones": ["eliminar 1 cucharada de aceite de oliva"]
        }
      ]
    }
  ]
}
```

Allowed fields:

- `nombre`: short semantic group name.
- `and`: all children are combined.
- `or`: choose one compatible child.
- `condiciones`: raw condition text.
- `notas`: raw notes from the plan.
- `warnings`: extraction or interpretation warnings.

Child values may be:

- strings for food/options;
- nested nodes for grouped choices.

Validation rules:

- A node must have exactly one of `and` or `or`.
- `and` and `or` must be non-empty arrays.
- Children may be strings or nested objects at any depth.
- A string child is already valid raw food text.
- Empty groups are invalid for activation.
- A parent `or` can contain nested `and` groups.
- A parent `and` can contain nested `or` groups.
- The validator must recurse until it reaches string leaves.

Semantic rules:

- `and` means all children in that array belong to the same valid selection.
- `or` means choose one compatible child from that array.
- The meaning is local to the node. Do not flatten the full tree.
- Preserve the nutritionist's grouping when possible, because nesting carries
  meal logic.

## Macros

Keep both compact codes and interpreted grams when available.

```json
{
  "macros_plan": {
    "codigos": {
      "anterior": "4.2.1,5",
      "actual": "4.2.2"
    },
    "interpretacion": {
      "anterior": {
        "hidratos_g": 40,
        "proteina_g": 20,
        "grasa_g": 15
      },
      "actual": {
        "hidratos_g": 40,
        "proteina_g": 20,
        "grasa_g": 20
      }
    }
  }
}
```

Compact format:

```text
hidratos.proteina.grasa
```

Each number represents tens of grams:

- `0.2.0`: 0 g carbs, 20 g protein, 0 g fat
- `1.7.2`: 10 g carbs, 70 g protein, 20 g fat
- `2.7.1,5`: 20 g carbs, 70 g protein, 15 g fat

Kcal can be calculated on demand when all macro grams are known:

- carbs: 4 kcal/g
- protein: 4 kcal/g
- fat: 9 kcal/g

The bot must not show macros by default.

## Conditions And Notes

V1 keeps conditions as raw strings.

```json
{
  "nombre": "opcion_pescado",
  "or": [
    "330g de merluza",
    "330g de salmon fresco",
    "330g de cualquier pescado azul"
  ],
  "condiciones": [
    "si eliges pescado azul, eliminar el aceite"
  ]
}
```

Do not force conditions into structured trigger/effect objects in V1. That
inflates JSON and prompt tokens. Convert a condition into a structured action
only at response time if it is needed for the current query.

## Warnings

Warnings should be compact and local.

Recommended shape:

```json
{
  "type": "ambiguous_group_operator",
  "message": "No queda claro si estas opciones son AND u OR.",
  "path": "comidas.comida_1.or[2]"
}
```

Recommended warning types:

- `unparsed_quantity`
- `unknown_unit`
- `ambiguous_group_operator`
- `missing_macro_plan`
- `unstructured_condition`
- `possible_duplicate_block`
- `empty_group`
- `low_confidence_extraction`

Warnings are for extraction review. They should not be sent to the model on
every normal user query unless the warning affects the selected comida.

## Token Budget Rules

When answering a user query, do not send the whole plan if a small slice is
enough.

Preferred context order:

1. Situation keys and moment mapping only when resolving context.
2. Selected comida only after context is resolved.
3. Relevant sibling choices inside that comida.
4. Relevant `condiciones` and `notas`.
5. Retrieved approved recipe candidates only when the user asks for a real dish
   or recipe-like recommendation.
6. Macros only if the user asks about macros, calories, quantities, or progress.
7. Document-level warnings only if they affect the selected comida.

Avoid passing:

- all comidas for a single meal question;
- the full situaciones document after the comida key is resolved;
- the full recetas catalog;
- future documents not needed by the query;
- parsed food objects when raw strings are enough;
- full extraction warnings for normal recommendations.

## Situations Document Notes

The canonical `situaciones` shape is defined above in
[Situations Router Document](#situations-router-document). Keep only one
operational contract:

- root `momentos` defines canonical meal moments and aliases;
- root `situaciones` defines configurable day contexts and maps each moment to a
  `comida_*` key;
- activity keys and moment keys are plan data, not hardcoded sports or fixed
  meals;
- after routing, the bot reads quantities only from the selected `comidas`
  block.

Future persistence may split `situaciones` into a separate JSONB document, but
the runtime contract stays the same.

## recetas Document

`recetas` is a catalog of real dishes that can make plan-based answers more
natural. The catalog may become large, so normal user answers should retrieve
candidate recipes through search/RAG instead of passing the full catalog to the
LLM.

It never replaces `comidas`. Recipes do not define final quantities. They only
describe dish shapes that may be adapted to the selected comida.

Functional order:

```text
situaciones -> chooses comida key
comidas -> defines quantities, macros, groups, and conditions
recetas -> proposes real dishes compatible with that comida
adaptation_rules -> helps adapt the recipe to the comida
```

Correct use:

1. Resolve situation and moment.
2. Load the selected comida from `comidas`.
3. Retrieve a small set of approved candidate recipes through search/RAG.
4. Filter candidates compatible with the moment and comida.
5. Adapt the selected recipe using quantities and conditions from the comida.
6. Answer with the adapted dish.

Wrong use:

```text
User: Que como?
Bot: Pasta bolonesa.
```

That skips context resolution and plan quantities.

### Recipe Lifecycle

Recipes have review status.

Allowed statuses:

- `draft`: created by admin/professional but incomplete.
- `pending_review`: submitted by user or imported automatically.
- `approved`: reviewed and usable by the bot.
- `rejected`: reviewed and not usable.
- `archived`: preserved for history but not usable.

The bot may use only:

- `status = approved`

The bot must not use `draft`, `pending_review`, `rejected`, or `archived`
recipes for normal user recommendations. Exceptions are admin/professional
review flows.

### Approved Recipe Shape

```json
{
  "nombre": "salmon_con_ensalada",
  "nombre_visible": "Salmon con ensalada",
  "tipo_comida": ["cena", "almuerzo"],
  "proteina_principal": ["salmon"],
  "tipo_proteina": "pescado_azul",
  "hidratos": [],
  "nivel_hidratos": "ninguno",
  "verduras": ["lechuga", "tomate", "ensalada"],
  "grasas": ["grasa_intrinseca_pescado_azul"],
  "nivel_grasa": "intrinseca_alta",
  "tags": ["pescado_azul", "ligero", "cena", "sin_hidrato_directo"],
  "compatibilidad": {
    "almuerzo": "media",
    "cena": "alta"
  },
  "notas_adaptacion": [
    "Eliminar el aceite si se usa como pescado azul del bloque.",
    "Anadir hidrato solo si el bloque lo pide."
  ],
  "status": "approved",
  "created_by_role": "professional"
}
```

Required fields for approval:

- `nombre`
- `nombre_visible`
- `tipo_comida`
- `proteina_principal`
- `tipo_proteina`
- `hidratos`
- `nivel_hidratos`
- `grasas`
- `nivel_grasa`
- `compatibilidad`
- `tags`
- `notas_adaptacion`
- `status = approved`

### Main Fields

`nombre` is the stable internal key. It should use snake_case and must be
unique.

`nombre_visible` is the human-readable name shown to users.

`tipo_comida` lists compatible moments, such as `desayuno`, `almuerzo`,
`merienda`, or `cena`. Future generic aliases may include `breakfast`, `lunch`,
`snack`, `dinner`, `pre_workout`, or `post_workout`.

`proteina_principal` lists main protein ingredients.

`tipo_proteina` classifies the protein for adaptation. Recommended values:

- `carne_magra`
- `carne_grasa`
- `pescado_blanco`
- `pescado_azul`
- `pescado_blanco_o_marisco`
- `huevo`
- `claras`
- `mixta`
- `variable`

`hidratos` lists carb sources present in the dish.

`nivel_hidratos` classifies carb level. Recommended values:

- `ninguno`
- `bajo`
- `medio`
- `medio_alto`
- `alto`

`verduras` lists usual vegetables in the recipe.

`grasas` lists fat sources present in the recipe.

`nivel_grasa` classifies fat level. Recommended values:

- `baja`
- `controlable`
- `media`
- `alta`
- `intrinseca_alta`
- `alta_o_dificil_controlar`
- `media_o_dificil_controlar`

`compatibilidad` maps moment keys to compatibility level. Recommended values:

- `muy_baja`
- `baja`
- `media`
- `alta`
- `muy_alta`

`notas_adaptacion` are hints for adapting the dish, but they do not override
`comidas` or explicit conditions in the selected comida.

### User Submitted Recipes

Users may propose recipes, but those recipes must not become approved
automatically.

Flow:

```text
user submits recipe
-> bot detects proposal
-> bot stores recipe as pending_review
-> bot informs user
-> admin/professional reviews
-> admin/professional edits, approves, rejects, or archives
-> approved recipes become usable by the bot
```

User-facing response:

```text
He guardado la receta como propuesta.
Un profesional tendra que revisarla antes de que el bot pueda usarla dentro del plan.
```

Pending recipe shape:

```json
{
  "nombre": "user_submitted_2026_05_22_001",
  "nombre_visible": "Arroz con atun y huevo",
  "tipo_comida": [],
  "proteina_principal": [],
  "tipo_proteina": null,
  "hidratos": [],
  "nivel_hidratos": null,
  "verduras": [],
  "grasas": [],
  "nivel_grasa": null,
  "tags": [],
  "compatibilidad": {},
  "notas_adaptacion": [],
  "status": "pending_review",
  "created_by_role": "user",
  "submitted_by_user_id": 123456,
  "raw_submission": {
    "text": "Arroz con atun, huevo cocido, pimientos y un poco de aceite.",
    "attachments": []
  },
  "review": {
    "reviewed_by": null,
    "reviewed_at": null,
    "decision": null,
    "notes": []
  }
}
```

Review decisions:

- `approve`
- `reject`
- `edit`
- `archive`

Rejected recipe review shape:

```json
{
  "review": {
    "reviewed_by": "admin_001",
    "reviewed_at": "2026-05-22T18:00:00Z",
    "decision": "rejected",
    "notes": [
      "Receta demasiado ambigua. Faltan cantidades y metodo de preparacion."
    ]
  }
}
```

### Recipe Storage

Simple starting point:

- `nutrition_plan_documents.document_type = recipes`
- `nutrition_plan_documents.content = recetas JSONB catalog`

Likely future shape when recipes grow one by one:

- `nutrition_recipes.id`
- `nutrition_recipes.plan_id`
- `nutrition_recipes.recipe_key`
- `nutrition_recipes.visible_name`
- `nutrition_recipes.status`
- `nutrition_recipes.created_by_role`
- `nutrition_recipes.submitted_by_user_id`
- `nutrition_recipes.content JSONB`
- `nutrition_recipes.created_at`
- `nutrition_recipes.updated_at`
- `nutrition_recipes.reviewed_by`
- `nutrition_recipes.reviewed_at`

For MVP planning, JSONB catalog is acceptable. Row-per-recipe becomes useful
when user submissions, review queues, and admin/professional editing exist.

### Recipe Retrieval And RAG

The recipe catalog should be treated as retrievable knowledge, not prompt
context.

Source of truth:

- approved recipe JSONB records or catalog entries;
- review metadata and status;
- raw submission for pending recipes.

Retrieval index:

- built only from `status = approved` recipes for normal user queries;
- includes searchable text from `nombre_visible`, ingredients, tags,
  `tipo_comida`, `tipo_proteina`, `nivel_hidratos`, `nivel_grasa`,
  `compatibilidad`, and `notas_adaptacion`;
- excludes `pending_review`, `draft`, `rejected`, and `archived` recipes unless
  the caller is in admin/professional review mode.

Prompt rule:

- do not pass the full recipe catalog to the LLM;
- retrieve a small candidate set first;
- pass only the selected comida, relevant conditions, and top recipe
  candidates;
- keep recipe candidates compact, preferably `nombre_visible`, key fields, and
  adaptation notes.

Example retrieval query:

```json
{
  "moment": "cena",
  "selected_comida": "comida_3",
  "desired_food": "salmon",
  "constraints": ["sin_hidrato_directo"],
  "prefer": ["compatibilidad.cena alta", "nivel_hidratos ninguno"]
}
```

Example compact candidate sent to the LLM:

```json
{
  "nombre": "salmon_con_ensalada",
  "nombre_visible": "Salmon con ensalada",
  "tipo_proteina": "pescado_azul",
  "nivel_hidratos": "ninguno",
  "nivel_grasa": "intrinseca_alta",
  "compatibilidad": {
    "cena": "alta"
  },
  "notas_adaptacion": [
    "Eliminar el aceite si se usa como pescado azul del bloque."
  ]
}
```

### Recipe Matching

When proposing a recipe, filter by:

1. `status = approved`.
2. Retrieval/search relevance.
3. Compatible meal moment.
4. Carb level compatible with the selected comida.
5. Protein type compatible with the selected comida.
6. User restrictions.
7. User preferences.

Dinner defaults:

- Prioritize `nivel_hidratos = ninguno` or `bajo`.
- Prioritize `compatibilidad.cena = alta` or `muy_alta`.
- Avoid `nivel_hidratos = alto` unless the selected comida requires it.

Lunch defaults:

- Allow carb-based recipes when the selected comida has a carb source.
- Adjust carb source to the selected comida quantity.

Do not:

- use pending recipes in normal recommendations;
- invent final quantities from recipes;
- approve user recipes automatically;
- modify approved recipes without admin/professional role;
- mix recipes with incompatible comidas;
- use high-carb dinner recipes without warning and plan support.

## Future Documents

Future document types may be added as separate JSONB rows:

- `adaptation_rules`: defines generic interpretation rules.

The active source of truth for quantities remains the compact `comidas`
document. Future documents may select or explain plan blocks, but they must not
silently override quantities.
