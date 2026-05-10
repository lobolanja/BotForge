# Beta Readiness Tasks

This folder contains product context for the first beta-readiness milestone.
The implementation tasks live in GitHub issues. The order below is the
recommended implementation sequence.

## Product Context

- [Product Vision And User Stories](product-vision-user-stories.md)
- [Customer Journeys](customer-journeys.md)

## GitHub Issue Board

The implementation tasks have been published as GitHub issues:

- [BotForge GitHub issues](https://github.com/lobolanja/BotForge/issues)

## Recommended Execution Order

If the project is going to use PostgreSQL instead of MariaDB, complete
[Issue #6: Migrate Database Runtime From MariaDB To PostgreSQL](https://github.com/lobolanja/BotForge/issues/6)
before starting task 1.

The file numbers are historical issue numbers. The execution order below is the
recommended implementation sequence.

## Phase 0: Product Context

Read these before implementing anything:

1. [Product Vision And User Stories](product-vision-user-stories.md)
2. [Customer Journeys](customer-journeys.md)

## Phase 1: Foundation

1. [Issue #6: Migrate Database Runtime From MariaDB To PostgreSQL](https://github.com/lobolanja/BotForge/issues/6)
2. [Issue #7: Configuration, Startup Validation, And DB Migrations](https://github.com/lobolanja/BotForge/issues/7)
3. [Issue #8: Split Telegram Commands Into Separate Command Modules](https://github.com/lobolanja/BotForge/issues/8)
4. [Issue #9: Bot Profile And Prompt Configuration](https://github.com/lobolanja/BotForge/issues/9)

Why this order:

- Database choice should be final before adding schema-heavy features.
- Migrations and startup validation are needed before roles, invites, policy,
  memory, or analytics.
- Command modularization is easier before adding `/start`, `/invite`,
  `/policy`, `/campaign_invite`, and future bot-specific commands.
- Bot profile configuration covers the "deploy different bots without changing
  generic infrastructure" journey before memory/prompt assembly gets complex.

## Phase 2: Access And Onboarding

5. [Issue #10: User Model And Roles](https://github.com/lobolanja/BotForge/issues/10)
6. [Issue #11: Telegram Invite Token Authentication](https://github.com/lobolanja/BotForge/issues/11)
7. [Issue #12: Usage Policy And Consent Onboarding](https://github.com/lobolanja/BotForge/issues/12)
8. [Issue #13: Admin Invite Management](https://github.com/lobolanja/BotForge/issues/13)
9. [Issue #14: Add Campaign Invite Tokens](https://github.com/lobolanja/BotForge/issues/14)

Why this order:

- Roles are the base for admin-only behavior.
- Invite authentication replaces password login. Treat a redeemed invite as a
  Telegram identity binding, not as a short-lived login/logout session.
- Users should accept the current usage policy before using protected bot
  functionality.
- Admin invite commands come after the invite model exists.
- Campaign invites build on normal invite handling and admin permissions.

## Phase 3: Reliable Runtime

10. [Issue #15: Persist Telegram Updates And Recover Safely After Downtime](https://github.com/lobolanja/BotForge/issues/15)
11. [Issue #16: Runtime Safety For Beta](https://github.com/lobolanja/BotForge/issues/16)
12. [Issue #17: Manage Async User Request Lifecycle And Waiting State](https://github.com/lobolanja/BotForge/issues/17)
13. [Issue #18: Abuse Prevention And Rate Limits](https://github.com/lobolanja/BotForge/issues/18)
14. [Issue #19: Add NVIDIA NIM Fallback Provider](https://github.com/lobolanja/BotForge/issues/19)

Why this order:

- Telegram updates should be persisted before expensive work starts.
- Runtime safety should make slow or failed providers visible to users.
- Request lifecycle tracking measures queue wait time and prevents confusing
  concurrent conversations.
- Rate limits protect the system before public campaign links or remote
  providers amplify load/cost.
- NVIDIA fallback depends on reliable wait-time measurement.

## Phase 4: Privacy, Operations, And Beta Readiness

15. [Issue #20: User Data Retention And Deletion Controls](https://github.com/lobolanja/BotForge/issues/20)
16. [Issue #21: Backup, Restore, And Operational Hardening](https://github.com/lobolanja/BotForge/issues/21)
17. [Issue #22: Beta Validation, CI, And Release Checklist](https://github.com/lobolanja/BotForge/issues/22)

Why this order:

- Retention and deletion controls should exist before storing more long-lived
  user data.
- Backups and restore are required before real users depend on the database.
- The beta checklist proves the whole system works as one product, not just as
  separate tasks.

## Phase 5: Memory And Data Improvement

18. [Issue #23: Agent Memory Investigation](https://github.com/lobolanja/BotForge/issues/23)
19. [Issue #24: MVP Agent Memory](https://github.com/lobolanja/BotForge/issues/24)
20. [Issue #25: Build A Privacy-Safe Conversation Analytics And Training Dataset](https://github.com/lobolanja/BotForge/issues/25)

Why this order:

- Memory design should be investigated before schema and prompt changes.
- The MVP memory implementation should use the reliable message foundation,
  policy acceptance, and deletion controls from earlier phases.
- Analytics and future training datasets should only happen after policy,
  consent, message persistence, redaction rules, and deletion rules are clear.

## Phase 6: Optional Document Handling

21. [Issue #26: User File Upload And Google Drive Storage](https://github.com/lobolanja/BotForge/issues/26)

Why this order:

- File upload introduces higher privacy and security risk than normal text.
- It should wait until policy, retention/deletion, message persistence, and
  operational hardening are already in place.

## Suggested Beta Cut

For a first private beta, complete Phases 1, 2, 3, and 4.

Phase 5 is required before promising persistent memory or using conversations
for product analytics/training. Phase 6 should only be included in beta if file
upload is a required product promise.

## Notes For Engineers

- Keep changes small and scoped to the issue you are working on.
- Do not store or log Telegram tokens, invite tokens, or user passwords.
- Do not add user-facing login/logout concepts unless there is a concrete
  session-management requirement. Privacy and account-control work should use
  explicit data-removal commands or documented deletion request flows.
- Run the Docker stack before and after auth/database changes.
- Add tests whenever an issue changes auth, roles, database access, or message
  routing behavior.
- Update `README.md` when commands, environment variables, or deployment steps
  change.
