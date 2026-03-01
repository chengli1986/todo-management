---
name: todo-management
description: Per-workspace SQLite todo manager (./todo.db) with groups, task statuses (pending/in_progress/done/skipped), and time-based reminders via openclaw cron, operated via {baseDir}/scripts/todo.sh.
metadata: {"openclaw":{"emoji":"📝","requires":{"bins":["sqlite3"]}}}
user-invocable: true
---

# Todo Management

## What this skill controls
A per-workspace SQLite database:
- Default: `./todo.db`
- Override: `TODO_DB=/path/to/todo.db`

All changes MUST happen through the CLI:
`bash {baseDir}/scripts/todo.sh ...`

## Statuses
`pending` (default), `in_progress`, `done`, `skipped`

Default list hides `done` and `skipped` unless `--all` or `--status=...`.

---

# Non-negotiable rules

## 1) No file writing (ever)
- Do NOT create or edit any files (e.g., `todos.md`, notes, markdown, exports).
- Do NOT output “filename blocks” like `todos.md (...)`.
- The only persistent state is in `todo.db`, mutated by `todo.sh`.

## 2) Never print the todo list unless explicitly asked
- If the user does NOT ask to “show/list/print my todos”, do NOT paste the list.
- Default behavior after mutations: one short confirmation line only.

## 3) Keep replies extremely short
- After success: respond with ONE line, max ~5 words (translate to user’s language yourself).
- Do not include bullets, tables, code blocks, or tool output unless the user explicitly asked for the list/details.

Allowed confirmations (English examples; translate as needed):
- “Done.”
- “Added.”
- “Updated.”
- “Removed.”
- “Moved.”
- “Renamed.”
- “Cleared.”
- “Added to the list.”

## 4) Ambiguity handling (the ONLY exception to rule #2)
If the user requests a destructive action but does not specify an ID (e.g., “remove the milk task”):
1) run `entry list` (optionally with `--group=...`)  
2) show the results (minimal table)  
3) ask which ID to act on

This is the only case where you may show the list without the user explicitly requesting it.

## 5) Group deletion safety
- `group remove “X”` moves entries to Inbox (default).
- Only delete entries if the user explicitly chooses that:
  - ask: “Move entries to Inbox (default) or delete entries too?”
  - only then use `--delete-entries`.

## 6) Reminder handling
- When the user asks to be reminded about something at a specific time (e.g., “5分钟后提醒我喝水”, “remind me at 8pm”):
  1. Create the entry first (if it doesn't already exist)
  2. Set a reminder with `entry remind ID --in=...` or `--at=...`
- If the user says “提醒我...” without specifying a time, ask when they want to be reminded.
- `--at` times are always interpreted as **Beijing time (BJT/CST)**.
- Reminders are auto-cancelled when an entry is removed — no manual cleanup needed.
- After setting a reminder, reply with ONE short confirmation (e.g., “已设置提醒。” / “Reminder set.”).

---

# Commands (use exactly these)

### Entries
- Add:
  - `bash {baseDir}/scripts/todo.sh entry create "Buy milk"`
  - `bash {baseDir}/scripts/todo.sh entry create "Ship feature X" --group="Work" --status=in_progress`
- List (ONLY when user asks, or for ambiguity resolution):
  - `bash {baseDir}/scripts/todo.sh entry list`
  - `bash {baseDir}/scripts/todo.sh entry list --group="Work"`
  - `bash {baseDir}/scripts/todo.sh entry list --all`
  - `bash {baseDir}/scripts/todo.sh entry list --status=done`
- Show one entry:
  - `bash {baseDir}/scripts/todo.sh entry show 12`
- Edit text:
  - `bash {baseDir}/scripts/todo.sh entry edit 12 "Buy oat milk instead"`
- Move:
  - `bash {baseDir}/scripts/todo.sh entry move 12 --group="Inbox"`
- Change status:
  - `bash {baseDir}/scripts/todo.sh entry status 12 --status=done`
  - `bash {baseDir}/scripts/todo.sh entry status 12 --status=skipped`
- Remove:
  - `bash {baseDir}/scripts/todo.sh entry remove 12`
- Remind (set/clear time-based reminders):
  - Relative (in N minutes/hours/days):
    - `bash {baseDir}/scripts/todo.sh entry remind 12 --in=5m`
    - `bash {baseDir}/scripts/todo.sh entry remind 12 --in=1h`
    - `bash {baseDir}/scripts/todo.sh entry remind 12 --in=2d`
  - Absolute (Beijing time, auto-converts to UTC):
    - `bash {baseDir}/scripts/todo.sh entry remind 12 --at="20:00"`
    - `bash {baseDir}/scripts/todo.sh entry remind 12 --at="2026-02-23 08:00"`
  - Clear a reminder:
    - `bash {baseDir}/scripts/todo.sh entry remind 12 --clear`

### Groups
- Create / list:
  - `bash {baseDir}/scripts/todo.sh group create "Work"`
  - `bash {baseDir}/scripts/todo.sh group list`
- Rename (alias: edit):
  - `bash {baseDir}/scripts/todo.sh group rename "Work" "Work (Project A)"`
  - `bash {baseDir}/scripts/todo.sh group edit "Work" "Work (Project A)"`
- Remove:
  - Default (move entries to Inbox):
    - `bash {baseDir}/scripts/todo.sh group remove "Work"`
  - Delete entries too (ONLY if user explicitly wants it):
    - `bash {baseDir}/scripts/todo.sh group remove "Work" --delete-entries`

## 7) Email digest
- A cron job sends a “Task Brief” email every 4 hours with the full task board + stats.
- The user can also manually trigger it by saying “发一封任务摘要” / “send me a digest” / “send task brief”:
  - Run: `python3 {baseDir}/scripts/todo-digest.py`
  - Reply with ONE short confirmation: “已发送。” / “Sent.”
- The digest reads `todo.db` (read-only) and sends to the configured email.
- Do NOT modify `todo-digest.py` or its cron schedule — that is managed separately.

---

# “Clear the list” behavior (no list printing)
To clear the todo list:
1) run `entry list --all` to get IDs (do NOT paste the results)
2) remove each ID with `entry remove ID`
3) reply with ONE line: “Cleared.”

If the user then asks to see the list, run `entry list` and show it.

---

# Dialogue example (expected behavior)

User: "I need to buy milk, add it to my todo list"
Agent: "Done."

User: "Oh, and I also need to clean the room"
Agent: "Added to the list."

User: "Show my todos"
Agent: (prints the list)

User: "Remove the milk one"
Agent: (lists matching tasks + asks for ID, then removes when ID is provided)

User: "5分钟后提醒我喝水"
Agent: (creates entry "喝水", sets reminder --in=5m) "已设置提醒。"

User: "remind me to call mom at 8pm"
Agent: (creates entry "call mom", sets reminder --at="20:00") "Reminder set."

User: "取消那个提醒"
Agent: (resolves which entry, runs remind ID --clear) "已取消。"
