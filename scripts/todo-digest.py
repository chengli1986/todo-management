#!/usr/bin/env python3
"""
Todo digest email - sends task board status every 4 hours.
Reads todo.db (SQLite), generates card-based HTML, sends via SMTP.

Cron: 0 0,4,8,12,16,20 * * *
"""

import html
import os
import sqlite3
import smtplib
import sys
from datetime import datetime, timezone, timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from zoneinfo import ZoneInfo

DB_PATH = os.path.expanduser("~/.openclaw/workspace/todo.db")
ENV_FILE = os.path.expanduser("~/.stock-monitor.env")
LOG_FILE = os.path.expanduser("~/logs/todo-digest.log")

# Timezone: reads TODO_TZ from env var or ~/.stock-monitor.env
# Switch when traveling: TODO_TZ=America/Vancouver
_TZ_LABELS = {
    "Asia/Shanghai": "BJT",
    "America/Vancouver": "PDT",
    "America/Toronto": "EDT",
    "America/New_York": "EDT",
    "Europe/London": "BST",
    "Asia/Tokyo": "JST",
    "Asia/Hong_Kong": "HKT",
}


def _resolve_tz() -> tuple[ZoneInfo, str]:
    """Read TODO_TZ from env var or .stock-monitor.env, default Asia/Shanghai."""
    tz_name = os.environ.get("TODO_TZ", "")
    if not tz_name:
        try:
            with open(ENV_FILE) as f:
                for line in f:
                    line = line.strip()
                    if line.startswith("TODO_TZ="):
                        tz_name = line.split("=", 1)[1].strip().strip('"').strip("'")
                        break
        except IOError:
            pass
    tz_name = tz_name or "Asia/Shanghai"
    return ZoneInfo(tz_name), _TZ_LABELS.get(tz_name, tz_name)


LOCAL_TZ, LOCAL_TZ_LABEL = _resolve_tz()


def log(msg: str) -> None:
    ts = datetime.now(LOCAL_TZ).strftime(f"%Y-%m-%d %H:%M:%S {LOCAL_TZ_LABEL}")
    line = f"[{ts}] {msg}"
    print(line, flush=True)


def load_env() -> dict[str, str]:
    """Load SMTP credentials from .stock-monitor.env."""
    env = {}
    try:
        with open(ENV_FILE) as f:
            for line in f:
                line = line.strip()
                if "=" in line and not line.startswith("#"):
                    key, _, val = line.partition("=")
                    env[key.strip()] = val.strip().strip('"').strip("'")
    except IOError:
        pass
    return env


def query_tasks(db_path: str) -> dict:
    """Query todo.db for active tasks and recent completions.

    Returns dict with keys:
      - active: list of (id, text, status, group_name, created_at, reminder_at)
      - recent_done: same shape, tasks done/skipped in last 24h
      - stats: dict with counts
    """
    if not os.path.isfile(db_path):
        return {"active": [], "recent_done": [], "stats": {}}

    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        # Active tasks (pending + in_progress)
        active = conn.execute("""
            SELECT e.id, e.text, e.status, g.name AS group_name,
                   e.created_at, e.reminder_at
            FROM entries e
            JOIN groups g ON g.id = e.group_id
            WHERE e.status IN ('pending', 'in_progress')
            ORDER BY
                CASE e.status WHEN 'in_progress' THEN 0 ELSE 1 END,
                e.id
        """).fetchall()

        # Recently completed (done/skipped in last 24h)
        recent_done = conn.execute("""
            SELECT e.id, e.text, e.status, g.name AS group_name,
                   e.created_at, e.updated_at AS reminder_at
            FROM entries e
            JOIN groups g ON g.id = e.group_id
            WHERE e.status IN ('done', 'skipped')
              AND e.updated_at >= datetime('now', '-1 day')
            ORDER BY e.updated_at DESC
        """).fetchall()

        # Stats
        stats_rows = conn.execute("""
            SELECT status, COUNT(*) as cnt FROM entries GROUP BY status
        """).fetchall()
        stats = {r["status"]: r["cnt"] for r in stats_rows}

    finally:
        conn.close()

    return {
        "active": [dict(r) for r in active],
        "recent_done": [dict(r) for r in recent_done],
        "stats": stats,
    }


def parse_created(created_at: str) -> datetime | None:
    """Parse SQLite CURRENT_TIMESTAMP (UTC) into aware datetime."""
    try:
        return datetime.strptime(created_at, "%Y-%m-%d %H:%M:%S").replace(
            tzinfo=timezone.utc
        )
    except Exception:
        return None


def format_age_detailed(created_at: str) -> tuple[str, int]:
    """Return (human-readable age, total_days) from a UTC timestamp.

    Examples: 'just now', '3 hours', '2 days', '1 week 4 days', '3 weeks'.
    """
    created = parse_created(created_at)
    if not created:
        return ("", 0)
    delta = datetime.now(timezone.utc) - created
    days = delta.days
    hours = delta.seconds // 3600
    if days >= 14:
        weeks = days // 7
        rem = days % 7
        age = f"{weeks}w {rem}d" if rem else f"{weeks} weeks"
    elif days >= 1:
        age = f"{days} day{'s' if days != 1 else ''}"
    elif hours >= 1:
        age = f"{hours} hour{'s' if hours != 1 else ''}"
    else:
        minutes = delta.seconds // 60
        age = f"{minutes}m" if minutes > 0 else "just now"
    return (age, days)


def created_local_str(created_at: str) -> str:
    """Convert UTC timestamp to local TZ display string like 'Mar 01, 14:30'."""
    created = parse_created(created_at)
    if not created:
        return ""
    return created.astimezone(LOCAL_TZ).strftime("%b %d, %H:%M")


def health_emoji(status: str, age_days: int) -> str:
    """Return an emoji indicating task health based on status and age.

    In-progress tasks:
      <1d  🔥 (hot — just started)
      1-3d ⚡ (on track)
      3-7d ⚠️ (getting stale)
      >7d  🚨 (overdue)

    Pending tasks:
      <1d  💤 (fresh — just added)
      1-3d 📋 (queued)
      3-7d ⏳ (waiting too long)
      >7d  🔴 (stale)

    Done/skipped:
      ✅ / ⏭️
    """
    if status == "done":
        return "&#x2705;"    # ✅
    if status == "skipped":
        return "&#x23ED;&#xFE0F;"  # ⏭️

    if status == "in_progress":
        if age_days < 1:
            return "&#x1F525;"   # 🔥
        elif age_days <= 3:
            return "&#x26A1;"    # ⚡
        elif age_days <= 7:
            return "&#x26A0;&#xFE0F;"  # ⚠️
        else:
            return "&#x1F6A8;"   # 🚨
    else:  # pending
        if age_days < 1:
            return "&#x1F4A4;"   # 💤
        elif age_days <= 3:
            return "&#x1F4CB;"   # 📋
        elif age_days <= 7:
            return "&#x231B;"    # ⏳
        else:
            return "&#x1F534;"   # 🔴


def build_html(data: dict) -> str:
    """Generate professional table-based HTML email from task data."""
    now_local = datetime.now(LOCAL_TZ)
    date_str = now_local.strftime("%A, %B %d")
    time_str = now_local.strftime(f"%H:%M {LOCAL_TZ_LABEL}")
    stats = data["stats"]
    in_progress = stats.get("in_progress", 0)
    pending = stats.get("pending", 0)
    done_total = stats.get("done", 0)
    skipped_total = stats.get("skipped", 0)
    done_today = len(data["recent_done"])
    total_active = in_progress + pending

    # Group active tasks by group_name
    groups: dict[str, list[dict]] = {}
    for task in data["active"]:
        g = task["group_name"]
        groups.setdefault(g, []).append(task)

    # Status config: (accent_color, label, text_color)
    status_cfg = {
        "in_progress": ("#0969da", "IN PROGRESS", "#24292f"),
        "pending": ("#656d76", "PENDING", "#24292f"),
        "done": ("#1a7f37", "DONE", "#656d76"),
        "skipped": ("#bc4c00", "SKIPPED", "#656d76"),
    }

    def render_task_row(task: dict, is_last: bool = False) -> str:
        cfg = status_cfg.get(task["status"], ("#999", "?", "#333"))
        accent, status_label, text_color = cfg
        text = html.escape(task["text"])
        age_str, age_days = format_age_detailed(task["created_at"])
        emoji = health_emoji(task["status"], age_days)
        created_ts = created_local_str(task["created_at"])
        is_done = task["status"] in ("done", "skipped")
        text_decoration = "text-decoration:line-through;" if is_done else ""
        border = "" if is_last else "border-bottom:1px solid #d8dee4;"

        # Age color: escalates as task lingers
        if age_days > 7:
            age_color = "#cf222e"
        elif age_days > 3:
            age_color = "#bc4c00"
        else:
            age_color = "#656d76"

        # Reminder
        reminder_html = ""
        if task.get("reminder_at"):
            try:
                r_utc = datetime.strptime(
                    task["reminder_at"], "%Y-%m-%dT%H:%M:%S.%fZ"
                ).replace(tzinfo=timezone.utc)
                r_local = r_utc.astimezone(LOCAL_TZ).strftime("%m/%d %H:%M")
                reminder_html = (
                    f'&nbsp;&nbsp;<span style="font-size:11px;color:#bc4c00;'
                    f'font-family:Trebuchet MS,Verdana,sans-serif">'
                    f'&#9200; {r_local}</span>'
                )
            except Exception:
                pass

        # Meta line
        meta_line = (
            f'<div style="margin-top:4px;font-size:11px;font-family:Trebuchet MS,Verdana,sans-serif;color:#656d76;line-height:1.4">'
            f'Created {created_ts}'
            f' &middot; <span style="color:{age_color};font-weight:600">{age_str}</span>'
            f'{reminder_html}'
            f'</div>'
        )

        return f"""<tr>
  <td style="padding:14px 0 14px 16px;{border}vertical-align:top;width:28px;text-align:center">
    <span style="font-size:18px;line-height:1">{emoji}</span>
  </td>
  <td style="padding:14px 8px;{border}vertical-align:top;width:90px">
    <span style="font-size:10px;font-family:Trebuchet MS,Verdana,sans-serif;letter-spacing:0.6px;color:{accent};font-weight:700">{status_label}</span>
  </td>
  <td style="padding:14px 16px 14px 0;{border}vertical-align:top;font-family:Georgia,'Times New Roman',serif;font-size:15px;color:{text_color};line-height:1.5;{text_decoration}">
    {text}
    {meta_line}
  </td>
</tr>"""

    # Build group sections
    groups_html = ""
    for group_name, tasks in sorted(groups.items()):
        rows = ""
        for i, t in enumerate(tasks):
            rows += render_task_row(t, is_last=(i == len(tasks) - 1))

        groups_html += f"""
<!-- Group: {html.escape(group_name)} -->
<table width="100%" cellpadding="0" cellspacing="0" border="0" style="margin-bottom:20px">
  <tr>
    <td style="padding:0 0 8px 4px">
      <span style="font-size:11px;font-family:Trebuchet MS,Verdana,sans-serif;letter-spacing:1.5px;color:#24292f;font-weight:700;text-transform:uppercase">{html.escape(group_name)}</span>
    </td>
  </tr>
  <tr>
    <td>
      <table width="100%" cellpadding="0" cellspacing="0" border="0" style="background:#ffffff;border:1px solid #d0d7de;border-radius:6px">
        {rows}
      </table>
    </td>
  </tr>
</table>"""

    # Recently completed section
    recent_html = ""
    if data["recent_done"]:
        recent_rows = ""
        for i, t in enumerate(data["recent_done"]):
            recent_rows += render_task_row(t, is_last=(i == len(data["recent_done"]) - 1))

        recent_html = f"""
<table width="100%" cellpadding="0" cellspacing="0" border="0" style="margin-top:8px">
  <tr>
    <td style="padding:16px 0 8px 4px;border-top:1px solid #d0d7de">
      <span style="font-size:11px;font-family:Trebuchet MS,Verdana,sans-serif;letter-spacing:1.5px;color:#656d76;font-weight:700;text-transform:uppercase">Completed &middot; Last 24h</span>
    </td>
  </tr>
  <tr>
    <td>
      <table width="100%" cellpadding="0" cellspacing="0" border="0" style="background:#f6f8fa;border:1px solid #d0d7de;border-radius:6px">
        {recent_rows}
      </table>
    </td>
  </tr>
</table>"""

    # Empty state
    empty_html = ""
    if not data["active"] and not data["recent_done"]:
        empty_html = """
<table width="100%" cellpadding="0" cellspacing="0" border="0">
  <tr>
    <td style="padding:48px 24px;text-align:center">
      <p style="font-family:Georgia,'Times New Roman',serif;font-size:18px;color:#656d76;font-style:italic;margin:0">Nothing on the board. Enjoy the calm.</p>
    </td>
  </tr>
</table>"""

    # Progress percentage
    pct = int(done_total / max(done_total + total_active, 1) * 100)

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <meta name="color-scheme" content="light">
  <meta name="supported-color-schemes" content="light">
  <title>Task Brief</title>
</head>
<body style="margin:0;padding:0;background:#ffffff;-webkit-text-size-adjust:100%">

<!-- Outer wrapper -->
<table width="100%" cellpadding="0" cellspacing="0" border="0" style="background:#ffffff">
  <tr>
    <td align="center" style="padding:20px 16px">

      <!-- Main container -->
      <table width="580" cellpadding="0" cellspacing="0" border="0" style="max-width:580px;width:100%">

        <!-- Header -->
        <tr>
          <td style="padding:24px 28px 20px;border-bottom:2px solid #24292f">
            <table width="100%" cellpadding="0" cellspacing="0" border="0">
              <tr>
                <td>
                  <span style="font-size:11px;font-family:Trebuchet MS,Verdana,sans-serif;letter-spacing:3px;color:#0969da;text-transform:uppercase;font-weight:700">Task Brief</span>
                </td>
                <td align="right">
                  <span style="font-size:12px;font-family:Trebuchet MS,Verdana,sans-serif;color:#656d76">{time_str}</span>
                </td>
              </tr>
              <tr>
                <td colspan="2" style="padding-top:6px">
                  <span style="font-family:Georgia,'Times New Roman',serif;font-size:24px;color:#24292f;font-weight:400">{date_str}</span>
                </td>
              </tr>
            </table>
          </td>
        </tr>

        <!-- Metrics row -->
        <tr>
          <td style="padding:20px 28px;border-bottom:1px solid #d0d7de">
            <table width="100%" cellpadding="0" cellspacing="0" border="0">
              <tr>
                <td width="33%" align="center" style="padding:12px 4px;background:#f6f8fa;border:1px solid #d0d7de;border-radius:6px 0 0 6px;border-right:none">
                  <span style="font-family:Georgia,'Times New Roman',serif;font-size:30px;color:#0969da;font-weight:400;line-height:1">{in_progress}</span>
                  <br>
                  <span style="font-size:10px;font-family:Trebuchet MS,Verdana,sans-serif;letter-spacing:1px;color:#656d76;text-transform:uppercase;font-weight:600">Active</span>
                </td>
                <td width="34%" align="center" style="padding:12px 4px;background:#f6f8fa;border:1px solid #d0d7de;border-radius:0;border-right:none">
                  <span style="font-family:Georgia,'Times New Roman',serif;font-size:30px;color:#24292f;font-weight:400;line-height:1">{pending}</span>
                  <br>
                  <span style="font-size:10px;font-family:Trebuchet MS,Verdana,sans-serif;letter-spacing:1px;color:#656d76;text-transform:uppercase;font-weight:600">Queued</span>
                </td>
                <td width="33%" align="center" style="padding:12px 4px;background:#f6f8fa;border:1px solid #d0d7de;border-radius:0 6px 6px 0">
                  <span style="font-family:Georgia,'Times New Roman',serif;font-size:30px;color:#1a7f37;font-weight:400;line-height:1">{done_today}</span>
                  <br>
                  <span style="font-size:10px;font-family:Trebuchet MS,Verdana,sans-serif;letter-spacing:1px;color:#656d76;text-transform:uppercase;font-weight:600">Done Today</span>
                </td>
              </tr>
            </table>
          </td>
        </tr>

        <!-- Progress bar -->
        <tr>
          <td style="padding:16px 28px 4px">
            <table width="100%" cellpadding="0" cellspacing="0" border="0">
              <tr>
                <td style="font-size:11px;font-family:Trebuchet MS,Verdana,sans-serif;color:#656d76;padding-bottom:6px">
                  Progress &middot; {done_total} of {done_total + total_active} total &middot; {pct}%
                </td>
              </tr>
              <tr>
                <td>
                  <table width="100%" cellpadding="0" cellspacing="0" border="0" style="background:#d0d7de;border-radius:4px;height:6px">
                    <tr>
                      <td style="background:#0969da;border-radius:4px;height:6px;width:{pct}%"></td>
                      <td></td>
                    </tr>
                  </table>
                </td>
              </tr>
            </table>
          </td>
        </tr>

        <!-- Content area -->
        <tr>
          <td style="padding:20px 28px 28px">

            {groups_html}

            {recent_html}

            {empty_html}

          </td>
        </tr>

        <!-- Footer -->
        <tr>
          <td style="padding:16px 28px;border-top:1px solid #d0d7de;text-align:center">
            <span style="font-size:11px;font-family:Trebuchet MS,Verdana,sans-serif;color:#656d76">
              Delivered every 4 hours &middot; {done_total} done, {skipped_total} skipped all time
            </span>
          </td>
        </tr>

      </table>

    </td>
  </tr>
</table>

</body>
</html>"""


def send_email(subject: str, html_body: str, env: dict) -> None:
    """Send HTML email via SMTP."""
    smtp_user = env.get("SMTP_USER", "")
    smtp_pass = env.get("SMTP_PASS", "")
    mail_to = env.get("MAIL_TO", "")

    if not all([smtp_user, smtp_pass, mail_to]):
        log("ERROR: Missing SMTP_USER, SMTP_PASS, or MAIL_TO in env")
        sys.exit(1)

    msg = MIMEMultipart("alternative")
    msg["From"] = smtp_user
    msg["To"] = mail_to
    msg["Subject"] = subject
    msg["MIME-Version"] = "1.0"

    msg.attach(MIMEText(html_body, "html", "utf-8"))

    with smtplib.SMTP_SSL("smtp.163.com", 465) as server:
        server.login(smtp_user, smtp_pass)
        server.sendmail(smtp_user, mail_to, msg.as_string())

    log(f"Email sent to {mail_to}")


def main() -> None:
    log("Starting todo digest")

    data = query_tasks(DB_PATH)

    # Smart skip: no email if nothing to report
    if not data["active"] and not data["recent_done"]:
        log("No active tasks and no recent completions — skipping email")
        return

    now_local = datetime.now(LOCAL_TZ).strftime(f"%b %d %H:%M {LOCAL_TZ_LABEL}")
    subject = f"\U0001f4cb Todo Digest - {now_local}"

    html_body = build_html(data)
    env = load_env()
    send_email(subject, html_body, env)

    stats = data["stats"]
    log(
        f"Done: {stats.get('in_progress', 0)} in-progress, "
        f"{stats.get('pending', 0)} pending, "
        f"{len(data['recent_done'])} done today"
    )


if __name__ == "__main__":
    main()
