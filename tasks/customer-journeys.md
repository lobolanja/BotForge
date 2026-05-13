# Customer Journeys

## Purpose

This document describes the desired user journeys for the finished shape of
BotForge. It should help engineers understand why the technical tasks matter.

The product should feel simple to users, even if the infrastructure behind it
has authentication, roles, memory, compaction, and model orchestration.

## Journey To Issue Map

- Journey 1, admin creates access: [#10 user roles](https://github.com/lobolanja/BotForge/issues/10), [#11 invite-token auth](https://github.com/lobolanja/BotForge/issues/11), [#13 admin invites](https://github.com/lobolanja/BotForge/issues/13), [#14 campaign invites](https://github.com/lobolanja/BotForge/issues/14)
- Journey 2, user joins through invite: [#11 invite-token auth](https://github.com/lobolanja/BotForge/issues/11), [#12 usage policy consent](https://github.com/lobolanja/BotForge/issues/12)
- Journey 3, first domain message: [#9 bot profiles](https://github.com/lobolanja/BotForge/issues/9), [#15 Telegram update recovery](https://github.com/lobolanja/BotForge/issues/15), [#16 runtime safety](https://github.com/lobolanja/BotForge/issues/16)
- Journeys 4-6, memory and memory clearing: [#20 data retention and deletion](https://github.com/lobolanja/BotForge/issues/20), [#23 memory investigation](https://github.com/lobolanja/BotForge/issues/23), [#24 memory MVP](https://github.com/lobolanja/BotForge/issues/24)
- Journey 7, deploy a different domain bot: [#8 command modules](https://github.com/lobolanja/BotForge/issues/8), [#9 bot profiles](https://github.com/lobolanja/BotForge/issues/9)
- Journey 8, slow or failed LLM response: [#16 runtime safety](https://github.com/lobolanja/BotForge/issues/16), [#17 async request lifecycle](https://github.com/lobolanja/BotForge/issues/17), [#18 rate limits](https://github.com/lobolanja/BotForge/issues/18), [#19 NVIDIA fallback](https://github.com/lobolanja/BotForge/issues/19)
- Journey 9, user controls data: [#12 usage policy consent](https://github.com/lobolanja/BotForge/issues/12), [#20 data retention and deletion](https://github.com/lobolanja/BotForge/issues/20), [#25 analytics dataset](https://github.com/lobolanja/BotForge/issues/25)
- Journey 10, operator validates beta: [#7 configuration and migrations](https://github.com/lobolanja/BotForge/issues/7), [#21 backup and hardening](https://github.com/lobolanja/BotForge/issues/21), [#22 beta validation](https://github.com/lobolanja/BotForge/issues/22)
- Journey 11, user uploads a file: [#15 Telegram update recovery](https://github.com/lobolanja/BotForge/issues/15), [#20 data retention and deletion](https://github.com/lobolanja/BotForge/issues/20), [#26 file upload and Google Drive storage](https://github.com/lobolanja/BotForge/issues/26)

## Journey 1: Admin Creates Access For A New User

## Actor

Admin.

## Goal

Invite a new person to use the bot without sharing passwords through Telegram.

## Desired Flow

1. Admin opens Telegram.
2. Admin sends:

   ```text
   /invite user user@example.com
   ```

3. Bot checks that the sender is an admin.
4. Bot generates a secure, single-use, expiring token.
5. Bot stores the hashed token, the intended user's email, the target role, and
   audit metadata. The raw token is not stored.
6. Bot replies with a Telegram invite link:

   ```text
   https://t.me/<bot_username>?start=<token>
   ```

7. Admin sends that link to the intended user.
8. Admin can trust that the link cannot be reused indefinitely.

For the first beta, invites are tied to both a target role and an email address.
The email gives the product a stable user attribute for future admin views, web
UI, support workflows, and audit trails. The admin still sends the generated
Telegram link to the intended user out of band.

## User Experience Goal

The admin should feel that access is controlled and simple.

## Product Requirements Behind This Journey

- Roles.
- Admin-only commands.
- Invite token generation.
- Token expiration.
- Token audit fields.
- Token redemption flow.
- Role and email captured when the invite is created.
- User email available for future web UI and admin/support workflows.

## Journey 2: New User Joins Through Invite Link

## Actor

End user.

## Goal

Start using the bot without understanding technical authentication.

## Desired Flow

1. User receives a Telegram link from an admin.
2. User taps the link.
3. Telegram opens the bot.
4. Telegram sends:

   ```text
   /start <token>
   ```

5. Bot validates the token.
6. Bot links the Telegram account to the invited internal user identity.
   6.1 The invite email is stored on the internal user.
   6.2 The Telegram ID identifies the Telegram account that redeemed the invite.
   6.3 The user does not need a separate `/login` or `/logout` session.
7. Bot shows a short usage policy summary.
8. User accepts the current policy version.
9. Bot replies with a friendly success message:

   ```text
   Ya tienes acceso. Puedes escribirme cuando quieras.
   ```

10. User sends their first normal message.
11. Bot replies normally.

If the user declines the policy, the Telegram ID remains identified but protected
bot functionality stays blocked. The user can accept the policy later or use the
documented privacy/deletion flow when that later-phase feature exists.

## User Experience Goal

The user should feel that onboarding is effortless.

## Product Requirements Behind This Journey

- `/start <token>` handler.
- Token validation.
- User creation or linking.
- Policy summary.
- Policy acceptance storage.
- Clear success/failure messages.
- Authenticated chat access.
- Internal user record stores email and Telegram ID after invite redemption.
- No password-style login/logout flow for invite-authenticated users.

## Journey 3: User Sends First Message To A Domain Bot

## Actor

End user.

## Goal

Ask the bot something in natural language and receive a useful response.

## Example For Nutrition Bot

```text
User: Hola, estoy intentando comer mejor pero no se por donde empezar.
Bot: Puedo ayudarte. Para empezar, dime si tienes algun objetivo concreto, como perder peso, ganar energia o planificar comidas mas saludables.
```

## Example For Agronomic Bot

```text
User: Tengo tomates con hojas amarillas, que puede ser?
Bot: Puede deberse a riego, falta de nutrientes o alguna enfermedad. Para orientarte mejor, dime cada cuanto riegas y si las manchas empiezan en hojas nuevas o viejas.
```

## User Experience Goal

The user should feel understood and guided, not interrogated by a technical
system.

## Product Requirements Behind This Journey

- Bot-specific system prompt.
- Generic message routing.
- Generic Ollama integration.
- Friendly wording.
- Runtime safety if model is slow.

## Journey 4: Bot Remembers Recent Context

## Actor

End user.

## Goal

Continue a conversation naturally without repeating context.

## Desired Flow

1. User gives context:

   ```text
   Estoy preparando una dieta vegetariana.
   ```

2. Bot responds.
3. User later says:

   ```text
   Dame una cena para manana.
   ```

4. Bot understands that the dinner should be vegetarian.

## User Experience Goal

The user should feel that the bot is paying attention.

## Product Requirements Behind This Journey

- Store recent messages.
- Retrieve last N turns.
- Send recent context to the model.
- Keep memory scoped to authenticated user.

## Journey 5: Bot Compacts Older Memory

## Actor

End user and system operator.

## Goal

Keep the bot context useful without making every response slower over time.

## Desired Flow

1. User has several interactions with the bot.
2. After X user queries, the system compacts older conversation history.
3. The compacted memory stores stable useful facts, preferences, and context.
4. The latest messages remain available as raw recent context.
5. Future prompts include:
   - System prompt.
   - Compacted memory.
   - Recent messages.
   - Current user message.

## Example Compacted Memory

```text
The user is interested in vegetarian meal planning, prefers simple dinners, and has asked for practical weekly suggestions.
```

## User Experience Goal

The user should feel remembered, while the system remains fast enough to use.

## Product Requirements Behind This Journey

- Query counter per user or conversation.
- Configurable compaction interval.
- Compaction prompt.
- Storage for compacted memory.
- Prompt assembly rules.
- Limits on recent message history.

## Journey 6: User Clears Their Memory

## Actor

End user.

## Goal

Delete the memory associated with their account.

## Desired Flow

1. User sends:

   ```text
   /memory_clear
   ```

2. Bot deletes compacted memory and stored conversation history for that user.
3. Bot replies:

   ```text
   He borrado tu memoria. A partir de ahora empezamos de nuevo.
   ```

4. Other users' memory is not affected.

## User Experience Goal

The user should feel in control of their privacy.

## Product Requirements Behind This Journey

- Memory table scoped by internal user ID.
- Delete memory command.
- Confirmation message.
- Tests for user isolation.

## Journey 7: Deploy A Different Domain Bot

## Actor

Bot owner or developer.

## Goal

Reuse the same infrastructure to deploy a different assistant.

## Desired Flow

1. Bot owner chooses a new domain.
2. Developer creates or changes bot-specific configuration:
   - System prompt.
   - Bot display name if needed.
   - Domain rules.
   - Future tools or knowledge sources.
3. Generic infrastructure remains unchanged:
   - Telegram auth.
   - Roles.
   - Memory.
   - Compaction.
   - Database.
   - Ollama integration.
4. New bot is deployed with the same Docker-based workflow.

## Example

The same platform can run:

- Nutrition assistant.
- Agronomic advisor.
- Financial education assistant.

Each one has different behavior, but the same auth and memory infrastructure.

## User Experience Goal

The product should feel specialized to each domain, while engineering effort is
reused.

## Product Requirements Behind This Journey

- Clear separation between generic and bot-specific code.
- Configurable system prompt.
- Generic memory layer.
- Generic auth layer.
- Deployment documentation.

## Journey 8: System Handles Slow Or Failed LLM Response

## Actor

End user.

## Goal

Understand what is happening when the bot is slow or temporarily unavailable.

## Desired Flow

1. User sends a message.
2. Bot shows Telegram typing state.
3. If the model responds, bot sends the answer.
4. If the model takes too long, bot sends a friendly timeout message.
5. Logs contain enough technical detail for developers.

## User Experience Goal

The user should not feel ignored.

## Product Requirements Behind This Journey

- Typing indicator.
- AI timeout.
- Friendly fallback messages.
- Logs without secrets.

## Journey 9: User Controls Their Data

## Actor

End user.

## Goal

Understand and control what the bot stores about them.

## Desired Flow

1. User sends:

   ```text
   /privacy
   ```

2. Bot explains what data is stored and which controls exist.
3. User sends:

   ```text
   /memory_clear
   ```

4. Bot clears that user's personalization memory.
5. If broader deletion is needed, user sends:

   ```text
   /delete_my_data
   ```

6. Bot follows the configured deletion or beta request flow.

This is the user-facing control surface for removing stored information. In the
invite-based model, `/logout` is not a core user journey because the user is not
holding a password session; the bot identifies the Telegram account that accepted
an invite.

## User Experience Goal

The user should feel in control of their privacy and stored context.

## Product Requirements Behind This Journey

- Usage policy.
- Data inventory.
- Memory deletion.
- Broader user-data deletion or deletion request flow.
- Tests for user isolation.
- Clear removal path for the Telegram identity link when the user stops using
  the bot.

## Journey 10: Operator Validates Beta Readiness

## Actor

Developer or project owner.

## Goal

Confirm the system is functional and safe before inviting real users.

## Desired Flow

1. Developer starts from a clean checkout.
2. Developer configures `.env`.
3. Docker stack starts successfully.
4. Database migrations run.
5. First admin is created.
6. Admin generates an invite.
7. User joins, accepts policy, and chats.
8. Bot is restarted.
9. Message recovery and stored user state behave as expected.
10. Backup and restore commands are tested.
11. Logs are checked for secrets.

## User Experience Goal

The team should know beta is ready from evidence, not assumptions.

## Product Requirements Behind This Journey

- Docker-first deployment.
- Migrations.
- Invite onboarding.
- Policy acceptance.
- Runtime recovery.
- Backup and restore.
- Security/privacy release checklist.

## Journey 11: User Uploads A File For Future Analysis

## Actor

End user.

## Goal

Send a PDF that the bot can store privately for future analysis.

## Desired Flow

1. Authenticated user sends a PDF to the bot.
2. Bot validates file type and size.
3. Bot stores file metadata.
4. Bot uploads the file to private external storage.
5. Bot confirms receipt or explains why the file was rejected.

## User Experience Goal

The user should understand whether the file was accepted and trust that it is
handled privately.

## Product Requirements Behind This Journey

- File message handling.
- Telegram file metadata storage.
- External private storage.
- File retention and deletion rules.
- Clear user feedback.

## Overall Desired Experience

The finished product should feel like this:

- Admins can control who enters.
- Users can join easily.
- Users accept the policy before protected use.
- Users can speak naturally.
- The bot remembers useful context.
- Memory remains private.
- Users can control stored data.
- The bot does not get slower forever.
- Different domain bots can be deployed from the same foundation.
- Operators can backup, restore, and validate beta readiness.
- Engineers can extend the system without mixing generic platform code with
  domain-specific behavior.
