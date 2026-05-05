# Product Vision And User Stories

## Vision

BotForge should become a generic infrastructure for deploying Telegram bots with
memory, authentication, roles, and configurable behavior.

The goal is not to build only one chatbot. The goal is to build a reusable base
that can power different assistants:

- Nutritionist assistant
- Agronomic advisor
- Financial advisor
- Internal company assistant
- Educational tutor
- Any other domain-specific bot

Each bot can have a different system prompt, tone, domain rules, and future
tools. The underlying infrastructure should stay the same.

## Core Product Idea

There are two clearly separated layers:

## 1. Generic Bot Infrastructure

This is reusable across every bot.

It includes:

- Telegram integration
- User onboarding
- Invite-based authentication
- Usage policy and consent onboarding
- Roles and permissions
- Bot profile configuration
- Conversation memory
- Memory compaction
- Prompt assembly
- Ollama model integration
- Optional remote LLM fallback
- Database storage
- Data retention and deletion controls
- Abuse prevention and rate limits
- Backup and restore process
- Docker deployment
- Logs and runtime safety

This layer should not know whether the bot is a nutritionist, agronomic advisor,
or financial advisor.

## 2. Bot-Specific Functionality

This changes depending on the bot we want to deploy.

It includes:

- System prompt
- Bot personality
- Domain restrictions
- Domain vocabulary
- Future domain tools
- Future knowledge bases
- Safety disclaimers
- Business-specific commands

Example:

- A nutrition bot may talk about food, calories, allergies, and diet planning.
- An agronomic bot may talk about crops, soil, irrigation, and pests.
- A financial bot may talk about budgeting, risk, and financial education.

The infrastructure should allow us to deploy each of those bots without
rewriting authentication, memory, database, or Telegram handling.

## Product Principles

- The user experience should be simple and friendly.
- Users should feel that the bot understands their context.
- The bot should remember useful context without becoming slow.
- The bot should not mix memory between users.
- Domain-specific behavior should be configured, not hardcoded into the core.
- Users should understand and accept the usage policy before protected use.
- User data should have clear retention, deletion, and privacy boundaries.
- The system should have basic abuse prevention before wider beta access.
- The system should be safe enough for beta before adding advanced features.


## Main Actors

## End User

The person who talks to the bot through Telegram.

They want:

- Simple onboarding.
- Clear messages.
- A bot that remembers recent context.
- Privacy.
- Useful responses.

## Admin

The person who manages access to the bot.

They want:

- Generate invite links.
- Control who can access the bot.
- Assign roles.
- See basic operational state.

## Bot Owner

The person or team deploying a specific bot for a specific use case.

They want:

- Configure the bot's purpose.
- Configure the system prompt.
- Reuse the same infrastructure for different bots.
- Avoid duplicating auth and memory logic.

## Developer

The engineer implementing and maintaining the system.

They want:

- Clear boundaries between generic and domain-specific code.
- Testable modules.
- Predictable database schema.
- Docker-based local development.

## Epics And User Stories

## Implementation Issue Map

The detailed implementation work is tracked in GitHub:

- Foundation: [#6 PostgreSQL migration](https://github.com/lobolanja/BotForge/issues/6), [#7 configuration and migrations](https://github.com/lobolanja/BotForge/issues/7), [#8 command modules](https://github.com/lobolanja/BotForge/issues/8), [#9 bot profiles and prompt configuration](https://github.com/lobolanja/BotForge/issues/9)
- Access and onboarding: [#10 user roles](https://github.com/lobolanja/BotForge/issues/10), [#11 invite-token auth](https://github.com/lobolanja/BotForge/issues/11), [#12 usage policy consent](https://github.com/lobolanja/BotForge/issues/12), [#13 admin invites](https://github.com/lobolanja/BotForge/issues/13), [#14 campaign invites](https://github.com/lobolanja/BotForge/issues/14)
- Reliable runtime: [#15 Telegram update recovery](https://github.com/lobolanja/BotForge/issues/15), [#16 runtime safety](https://github.com/lobolanja/BotForge/issues/16), [#17 async request lifecycle](https://github.com/lobolanja/BotForge/issues/17), [#18 rate limits](https://github.com/lobolanja/BotForge/issues/18), [#19 NVIDIA fallback](https://github.com/lobolanja/BotForge/issues/19)
- Privacy and operations: [#20 data retention and deletion](https://github.com/lobolanja/BotForge/issues/20), [#21 backup and hardening](https://github.com/lobolanja/BotForge/issues/21), [#22 beta validation](https://github.com/lobolanja/BotForge/issues/22)
- Memory and data improvement: [#23 memory investigation](https://github.com/lobolanja/BotForge/issues/23), [#24 memory MVP](https://github.com/lobolanja/BotForge/issues/24), [#25 analytics dataset](https://github.com/lobolanja/BotForge/issues/25)
- Optional document handling: [#26 file upload and Google Drive storage](https://github.com/lobolanja/BotForge/issues/26)

## Epic 1: Generic Bot Deployment

### Story 1.1: Deploy A Generic Bot Stack

As a developer, I want to run the bot, database, and LLM service with Docker
Compose, so that I can start development without manually installing every
service.

Acceptance criteria:

- `docker compose up -d --build` starts all required services.
- The bot starts without manual database setup.
- The LLM model can be configured through environment variables.
- The README explains the first-run flow.

### Story 1.2: Configure Bot Identity Separately From Infrastructure

As a bot owner, I want to configure the bot's system prompt separately from the
generic infrastructure, so that I can deploy different bots using the same code
base.

Acceptance criteria:

- The core Telegram/database/memory logic does not contain domain-specific
  instructions.
- A bot-specific system prompt can be configured.
- Changing the system prompt does not require changing auth or memory code.

## Epic 2: Invite-Based Authentication

### Story 2.1: Admin Generates User Invite

As an admin, I want to generate an invite link for a new user, so that I can
control who is allowed to access the bot.

Acceptance criteria:

- Only admins can generate invite links.
- Generated links use Telegram's `/start <token>` flow.
- Invite tokens are single-use.
- Invite tokens expire.
- Raw tokens are not stored in the database.

### Story 2.2: User Joins With A Telegram Invite Link

As a user, I want to open a Telegram invite link and be registered
automatically, so that onboarding is simple and does not require copying
technical tokens manually.

Acceptance criteria:

- Opening the link sends `/start <token>` to the bot.
- The bot validates the token.
- The user receives a clear success message.
- The user's Telegram ID is linked to an internal user record.

### Story 2.3: Invalid Invite Gives A Clear Message

As a user, I want a clear explanation when my invite link fails, so that I know
whether the link is invalid, expired, already used, or if there is a temporary
system problem.

Acceptance criteria:

- Invalid token shows a friendly error.
- Expired token shows a friendly error.
- Used token shows a friendly error.
- System errors do not expose technical internals.

## Epic 3: Roles And Permissions

### Story 3.1: Separate Admin And User Permissions

As an admin, I want admin-only commands to be protected, so that normal users
cannot manage access or create invites.

Acceptance criteria:

- The system supports at least `admin` and `user`.
- The system reserves `professional` for later.
- Admin-only commands reject non-admin users.
- Permission checks are implemented in reusable helpers.

### Story 3.2: Reserve Professional Role

As a product owner, I want the `professional` role reserved in the schema, so
that future professional workflows can be added without redesigning users later.

Acceptance criteria:

- `professional` exists as a valid role.
- It has no special behavior for now.
- The code does not assume only two roles exist.

## Epic 4: User Memory

### Story 4.1: Remember Recent Conversation Context

As a user, I want the bot to remember recent messages, so that I do not need to
repeat context in every message.

Example:

```text
User: Estoy preparando una dieta vegetariana.
Bot: Perfecto, puedo ayudarte con eso.
User: Dame una cena para manana.
```

The bot should understand that the dinner should be vegetarian.

Acceptance criteria:

- The bot stores recent conversation turns per authenticated user.
- The bot sends recent context to the model.
- Memory is scoped to the user.
- Memory survives container restarts.

### Story 4.2: Compact Memory Every X Queries

As a system operator, I want the bot to compact memory every X user queries, so
that the context stays useful without sending too many old messages to the LLM.

Acceptance criteria:

- The number of queries before compaction is configurable.
- The bot summarizes older context into compact memory.
- The bot keeps the latest messages plus the compacted memory.
- The prompt does not grow indefinitely.
- The compaction process is generic and independent of the bot's system prompt.

### Story 4.3: Use Latest Messages Plus Compacted Memory

As a user, I want the bot to remember both recent details and older important
context, so that it feels continuous and personalized without becoming slow.

Acceptance criteria:

- The model receives:
  - Bot-specific system prompt.
  - Compacted user memory.
  - Last N conversation messages.
  - Current user message.
- The order of prompt assembly is deterministic.
- The memory layer does not contain domain-specific assumptions.

### Story 4.4: Clear User Memory

As a user, I want to clear what the bot remembers about me, so that I control my
privacy.

Acceptance criteria:

- User can run `/memory_clear`.
- Only that user's memory is deleted.
- The bot confirms memory was cleared.
- Other users' memory is unaffected.

### Story 4.5: Prevent Memory Leaks Between Users

As a user, I want my memory to be private, so that the bot never uses another
person's context when answering me.

Acceptance criteria:

- Memory is stored by internal authenticated user ID.
- User A cannot retrieve User B memory.
- Tests cover memory isolation.

## Epic 5: Prompt Composition

### Story 5.1: Compose Prompt From Generic And Specific Parts

As a developer, I want prompt assembly to be explicit, so that generic memory
logic and bot-specific instructions are not mixed together.

Acceptance criteria:

- Prompt assembly has clear inputs:
  - system prompt
  - compacted memory
  - recent messages
  - current message
- The system prompt is bot-specific.
- Memory and recent messages are generic.
- The code makes this separation obvious.

### Story 5.2: Deploy A New Bot By Changing Configuration

As a bot owner, I want to deploy a new domain-specific bot by changing
configuration, so that I can reuse BotForge for multiple assistants.

Acceptance criteria:

- The infrastructure can run with a different system prompt.
- The database/auth/memory logic does not need to change.
- README explains where bot-specific configuration belongs.

## Epic 6: Friendly User Experience

### Story 6.1: Friendly First Contact

As a new user, I want the bot to greet me clearly when I open it, so that I know
what to do next.

Acceptance criteria:

- `/start` without token explains that an invite is required.
- `/start <valid_token>` registers the user.
- `/help` explains available commands.

### Story 6.2: Friendly Slow Response Handling

As a user, I want the bot to acknowledge slow responses, so that I know it is
working and has not ignored me.

Acceptance criteria:

- Bot sends Telegram typing action.
- Long model calls have timeout handling.
- If the model fails, the user receives a friendly message.

## Epic 7: Runtime Safety

### Story 7.1: Safe Failure When LLM Is Unavailable

As a user, I want a clear response when the LLM service is unavailable, so that
I understand the bot is temporarily unable to answer.

Acceptance criteria:

- Ollama connection errors are caught.
- User receives a friendly fallback message.
- Logs contain technical details.
- Secrets are not logged.

### Story 7.2: Safe Failure When Database Is Unavailable

As a user, I want the bot to fail gracefully if the database is unavailable, so
that I do not see raw technical errors.

Acceptance criteria:

- Database errors are caught.
- User receives a friendly fallback message.
- Logs contain technical details.
- Auth checks do not crash the bot process.

## Epic 8: Privacy, Consent, And Data Control

### Story 8.1: User Accepts Usage Policy Before Protected Use

As a user, I want to understand the bot's usage policy before using it, so that
I know how my messages, memory, files, and analytics data may be handled.

Acceptance criteria:

- The user sees a short policy summary during onboarding.
- The user can read the full policy or a policy link.
- The user must accept the current policy version before protected chat.
- Acceptance stores timestamp and policy version.
- Optional analytics/training consent is not silently enabled.

### Story 8.2: User Controls Stored Data

As a user, I want to clear memory or request deletion of my data, so that I can
control what the bot keeps about me.

Acceptance criteria:

- `/privacy` explains what is stored.
- `/memory_clear` deletes only personalization memory for the current user.
- Broader deletion is supported through `/delete_my_data` or a documented beta
  request flow.
- Deleted user data is not used in future prompts or analytics exports.

## Epic 9: Abuse Prevention And Operational Readiness

### Story 9.1: System Limits Abuse And Accidental Overload

As a system operator, I want configurable limits on user messages and AI
requests, so that one user or campaign link cannot overload the bot.

Acceptance criteria:

- Per-user message limits exist.
- Maximum message length exists.
- Global active AI request limits exist.
- Users receive friendly limit messages.
- Limit logs do not store full private message text.

### Story 9.2: Operator Can Backup And Restore The System

As a system operator, I want a tested backup and restore process, so that user
accounts, policy acceptance, invites, messages, and memory are not lost after a
deployment or machine failure.

Acceptance criteria:

- Database backup command/process is documented.
- Restore into a clean environment is tested.
- Required persistent Docker volumes are documented.
- Production deployments do not use development passwords.

### Story 9.3: Team Validates Beta End To End

As a project owner, I want a release checklist and smoke test, so that beta
readiness is based on evidence instead of assumptions.

Acceptance criteria:

- The team can run the full invite, policy, chat, restart, and recovery flow.
- Automated tests run with one documented command.
- Security/privacy gates are checked before inviting real users.

## Epic 10: Optional Document Handling

### Story 10.1: User Uploads A PDF For Future Analysis

As a user, I want to upload a PDF to the bot, so that future bot features can
analyze it.

Acceptance criteria:

- Only authenticated users with accepted policy can upload files.
- Only allowed file types and sizes are accepted.
- File metadata is stored.
- Files are stored privately in configured external storage.
- Deletion controls also cover uploaded files.

## Definition Of Done For The Future Product Shape

The project is moving in the right direction when:

- A new user can join through an invite link.
- A new user accepts the usage policy before protected use.
- Admins can control access.
- The bot remembers each user separately.
- Memory is compacted and does not grow forever.
- Bot-specific behavior lives outside the generic infrastructure.
- A new domain bot can be created mostly through configuration.
- The system is easy to run locally with Docker.
- User data retention and deletion are documented.
- Backups and restore have been tested.
- Basic rate limits protect the beta.
- The code is clear enough for a junior engineer to extend safely.
