# todo-management (OpenClaw Skill)

A **per-workspace** todo manager for OpenClaw that stores everything in a local **SQLite** DB (`./todo.db`) and is controlled via a single script (`todo.sh`). Includes **time-based reminders** delivered through WhatsApp (or any connected channel) via `openclaw cron`.

* Groups (default: `Inbox`)
* Task statuses: `pending`, `in_progress`, `done`, `skipped`
* Time-based reminders (relative or absolute, Beijing time)
* Deterministic CLI (no "creative" file writing)
* Designed to keep agent replies short (no auto-pasting the full list)

---

## Requirements

* `sqlite3` must be available in your `PATH`
  (Most macOS/Linux systems already have it; otherwise install via your package manager.)
* `openclaw cron` for reminder scheduling (bundled with OpenClaw)

---

## After installation: make the script executable

Depending on how you installed skills, your path may differ. The common one is:

```bash
chmod +x skills/todo-management/scripts/todo.sh
```

Quick check (should print help text):

```bash
bash skills/todo-management/scripts/todo.sh --help
```

---

## How it works

* The skill ships with a CLI script inside the skill folder:

  * `.../skills/todo-management/scripts/todo.sh`
* The **data** lives in your current working directory (workspace):

  * default DB file: `./todo.db`
  * override location: `TODO_DB=/path/to/todo.db`

So: the script is global (skill asset), but the tasks are local to the project you're working in.

---

## Examples (CLI)

### Add tasks

```bash
todo.sh entry create "Buy milk"
todo.sh entry create "Ship feature X" --group="Work" --status=in_progress
```

### List tasks (active by default)

```bash
todo.sh entry list
todo.sh entry list --all              # include done/skipped
todo.sh entry list --group="Work"
todo.sh entry list --status=done
```

### Edit / move / change status

```bash
todo.sh entry edit 1 "Buy oat milk"
todo.sh entry move 1 --group="Inbox"
todo.sh entry status 1 --status=done
```

### Groups

```bash
todo.sh group create "Work"
todo.sh group rename "Work" "Work (Project A)"
todo.sh group remove "Work"                    # moves entries to Inbox
todo.sh group remove "Work" --delete-entries   # deletes entries too
```

### Reminders

Set a reminder to get notified via WhatsApp (or your connected channel) at a specific time.

```bash
# Relative — in N minutes/hours/days
todo.sh entry remind 1 --in=5m
todo.sh entry remind 1 --in=1h
todo.sh entry remind 1 --in=2d

# Absolute — Beijing time (auto-converted to UTC)
todo.sh entry remind 1 --at="20:00"
todo.sh entry remind 1 --at="2026-02-23 08:00"

# Clear a reminder
todo.sh entry remind 1 --clear
```

Reminders are powered by `openclaw cron`. When the time arrives, a message like `"⏰ 待办提醒: Buy milk (ID: 1)"` is delivered to your last active channel.

Active reminders are shown with a ⏰ prefix in `entry list`. Reminders are automatically cancelled when an entry is removed.

---

## Example (how the agent should respond)

The skill is configured to be **concise** by default:

```
User: I need to buy milk, add it to my todo list
Agent: Done.

User: Show my todos
Agent: (prints the list)

User: 5分钟后提醒我喝水
Agent: 已设置提醒。

User: remind me to call mom at 8pm
Agent: Reminder set.

User: 取消那个提醒
Agent: 已取消。
```

---

## Notes

* This skill intentionally **does not** write `todos.md` or any other files.
* The todo list is only printed when you explicitly ask to show/list it (or when the agent needs IDs to disambiguate a destructive action).
* `--at` times are interpreted as **Beijing time (CST/BJT)** and auto-converted to UTC for scheduling.
* If a `--at` time has already passed today, it automatically rolls to tomorrow.
