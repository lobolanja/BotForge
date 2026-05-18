# Privacy And Retention

This document is the beta data inventory for BotForge. It describes what the
bot stores, why it is stored, how long it is expected to live, and what happens
when a user uses `/memory_clear` or `/delete_my_data`.

This is product documentation, not final legal wording.

## User Commands

- `/privacy` explains the stored data categories and the available data-control
  commands.
- `/memory_clear` clears personalization memory for the linked user. The
  current schema has no memory tables yet, so the command is wired as a stable
  hook for issue #24.
- `/delete_my_data` creates a durable beta deletion request and explains the
  consequences.
- `/delete_my_data CONFIRM` performs self-service beta deletion for non-admin
  users. Admin accounts are queued for manual owner review to avoid removing the
  only operator accidentally.

## Data Inventory

| Category | Example Fields | Why Stored | Retention Decision | Deletion Behavior |
| --- | --- | --- | --- | --- |
| User account | internal user id, role, email, Telegram id | identity and access | while account is active | anonymize and soft delete on confirmed deletion |
| Invite records | token hash, role, email, created_by, used_by | access audit | retained as operational audit | keep token audit, avoid exposing raw tokens, user deletion removes direct account link where possible |
| Policy acceptances | user id, policy version, privacy version, timestamp | compliance and access gate | while account is active or needed for audit | retained as minimal operational audit after account deletion |
| Inbound messages | update id, message id, chat id, text, file metadata, status | recovery and operations | short operational window, controlled by operational retention work | confirmed deletion clears Telegram user id, text, raw update, and file metadata for that Telegram user |
| Conversation memory | recent user and assistant turns | useful context | configurable after issue #24 | hard delete on `/memory_clear` after memory tables exist |
| Compacted memory | summary facts and preferences | long-term personalization | configurable after issue #24 | hard delete on `/memory_clear` after memory tables exist |
| Analytics records | redacted text, intent, quality labels | product improvement | configurable after issue #25 | exclude or delete on user deletion after analytics tables exist |
| Uploaded documents | file id, external storage id, metadata | future analysis | configurable after issue #26 | delete external object and metadata after file storage exists |
| Logs | timestamps, ids, error classes | debugging and security | short local or deployment-specific retention | logs must not include raw private text, invite tokens, provider keys, or unsafe filenames |
| Backups | database snapshots | disaster recovery | operational policy | deletion applies to live data; older backups may retain data until backup expiry |

## Beta Deletion Behavior

For a non-admin linked user, `/delete_my_data CONFIRM`:

1. Creates a completed `user_deletion_requests` row.
2. Clears personalization memory through the shared memory deletion hook.
3. Anonymizes existing inbound message records tied to the Telegram account.
4. Removes the Telegram identity link from `users`.
5. Clears email and password fields.
6. Replaces the username with a non-identifying deleted-user marker.
7. Sets `users.deleted_at`, `users.deletion_requested_at`, and
   `users.deletion_reason`.

After deletion, normal identity checks exclude the user and protected bot
features require a new invite.

For an admin linked user, confirmation creates a confirmed request for manual
owner review instead of self-service deletion.

## Implementation Notes

- User-facing commands do not expose internal database ids, invite token hashes,
  raw Telegram update JSON, or implementation details.
- Data-control commands do not require current policy acceptance. A user must be
  able to remove data even if they have not accepted the current policy.
- New memory, analytics, and file-storage tables must update this inventory and
  add their table-specific deletion behavior before they are enabled.
