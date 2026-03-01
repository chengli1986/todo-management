# todo-management (OpenClaw Skill)

A **per-workspace** todo manager for OpenClaw that stores everything in a local **SQLite** DB (`./todo.db`) and is controlled via a single script (`todo.sh`). Includes **time-based reminders** delivered through WhatsApp via `openclaw cron`, and a **scheduled email digest** ("Task Brief") sent every 4 hours.

## Features

- **Groups** (default: `Inbox`) — organize tasks by project or category
- **Task statuses**: `pending`, `in_progress`, `done`, `skipped`
- **Time-based reminders** — relative (`--in=5m`) or absolute (`--at="20:00"`, Beijing time)
- **Email digest** — professional "Task Brief" email every 4 hours with metrics, progress bar, and grouped task tables
- **Smart skip** — no email when the task board is empty
- **Manual trigger** — say "发一封任务摘要" or "send me a digest" via WhatsApp
- **Concise agent replies** — no auto-pasting the full list; short confirmations only

---

## Requirements

- `sqlite3` in your `PATH` (most Linux/macOS systems have it)
- `openclaw cron` for reminder scheduling (bundled with OpenClaw)
- SMTP credentials in `~/.stock-monitor.env` (for email digest)

---

## Quick Start

```bash
# Make scripts executable
chmod +x skills/todo-management/scripts/todo.sh
chmod +x skills/todo-management/scripts/todo-digest.py

# Verify
bash skills/todo-management/scripts/todo.sh --help
python3 skills/todo-management/scripts/todo-digest.py  # sends a test email
```

---

## How It Works

```
WhatsApp (OpenClaw /todo)
  │
  ├── todo.sh ──writes──► todo.db (SQLite)
  │                            │
  │                        reads (every 4h)
  │                            │
  │                            ▼
  │                      todo-digest.py
  │                        │ generates HTML
  │                        │ sends via SMTP
  │                        ▼
  │                   email inbox
  │
  └── openclaw cron ──► WhatsApp reminders
```

- **Script** (`todo.sh`): CLI for all CRUD operations, lives in the skill folder
- **Digest** (`todo-digest.py`): reads DB (read-only), generates HTML, sends email
- **Data** (`todo.db`): per-workspace SQLite DB in your working directory
- Override DB location: `TODO_DB=/path/to/todo.db`

---

## CLI Examples

### Tasks

```bash
# Add
todo.sh entry create "Buy milk"
todo.sh entry create "Ship feature X" --group="Work" --status=in_progress

# List (active by default)
todo.sh entry list
todo.sh entry list --all              # include done/skipped
todo.sh entry list --group="Work"
todo.sh entry list --status=done

# Edit / move / change status
todo.sh entry edit 1 "Buy oat milk"
todo.sh entry move 1 --group="Inbox"
todo.sh entry status 1 --status=done

# Remove
todo.sh entry remove 1
```

### Groups

```bash
todo.sh group create "Work"
todo.sh group list
todo.sh group rename "Work" "Work (Project A)"
todo.sh group remove "Work"                    # moves entries to Inbox
todo.sh group remove "Work" --delete-entries   # deletes entries too
```

### Reminders

```bash
# Relative — in N minutes/hours/days
todo.sh entry remind 1 --in=5m
todo.sh entry remind 1 --in=1h
todo.sh entry remind 1 --in=2d

# Absolute — Beijing time (auto-converted to UTC)
todo.sh entry remind 1 --at="20:00"
todo.sh entry remind 1 --at="2026-02-23 08:00"

# Clear
todo.sh entry remind 1 --clear
```

Reminders are powered by `openclaw cron`. When the time arrives, a message like `"⏰ 待办提醒: Buy milk (ID: 1)"` is delivered to your last active channel.

---

## Email Digest ("Task Brief")

A professional HTML email sent every 4 hours via cron:

| Feature | Detail |
|---------|--------|
| **Schedule** | Every 4h (BJT 00, 04, 08, 12, 16, 20) |
| **Header** | Dark slate masthead with date and time |
| **Metrics** | Three cards: Active / Queued / Done Today |
| **Progress bar** | Visual completion ratio |
| **Task tables** | Grouped by category, status dots, task age |
| **Completed section** | Tasks done/skipped in last 24h |
| **Smart skip** | No email if board is empty |
| **Manual trigger** | WhatsApp: "发一封任务摘要" / "send me a digest" |

### Cron Setup

```bash
# Add to crontab (UTC times = BJT 08,12,16,20,00,04)
0 0,4,8,12,16,20 * * * /usr/bin/python3 /path/to/scripts/todo-digest.py >> ~/logs/todo-digest.log 2>&1
```

---

## WhatsApp Conversation Examples

```
User: 加个任务：部署航班中继服务
Agent: 已添加。

User: 看看我的待办
Agent: (prints the list)

User: 第8个任务完成了
Agent: 已更新。

User: 5分钟后提醒我喝水
Agent: 已设置提醒。

User: remind me to call mom at 8pm
Agent: Reminder set.

User: 发一封任务摘要
Agent: 已发送。

User: 取消那个提醒
Agent: 已取消。
```

---

## File Structure

```
todo-management/
├── SKILL.md              # OpenClaw skill definition
├── README.md             # This file
├── _meta.json            # Skill metadata
└── scripts/
    ├── todo.sh           # Task CRUD + reminders (Bash/SQLite)
    └── todo-digest.py    # Email digest generator (Python)
```

---

## Development

The `.claude/CLAUDE.md` file provides repository context for [Claude Code](https://claude.com/claude-code).

---

## License

MIT
