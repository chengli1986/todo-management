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

BJT = timezone(timedelta(hours=8))
DB_PATH = os.path.expanduser("~/.openclaw/workspace/todo.db")
ENV_FILE = os.path.expanduser("~/.stock-monitor.env")
LOG_FILE = os.path.expanduser("~/logs/todo-digest.log")


def log(msg: str) -> None:
    ts = datetime.now(BJT).strftime("%Y-%m-%d %H:%M:%S BJT")
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


def format_age(created_at: str) -> str:
    """Format task age as human-readable string (e.g., '2d', '3h', 'just now')."""
    try:
        # SQLite CURRENT_TIMESTAMP is UTC
        created = datetime.strptime(created_at, "%Y-%m-%d %H:%M:%S").replace(
            tzinfo=timezone.utc
        )
        delta = datetime.now(timezone.utc) - created
        days = delta.days
        hours = delta.seconds // 3600
        if days > 0:
            return f"{days}d"
        elif hours > 0:
            return f"{hours}h"
        else:
            return "just now"
    except Exception:
        return ""


def build_html(data: dict) -> str:
    """Generate professional table-based HTML email from task data."""
    now_bjt = datetime.now(BJT)
    date_str = now_bjt.strftime("%A, %B %d")
    time_str = now_bjt.strftime("%H:%M BJT")
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

    # Status config: (dot_color, label, text_color)
    status_cfg = {
        "in_progress": ("#0066cc", "IN PROGRESS", "#1a1a2e"),
        "pending": ("#94a3b8", "PENDING", "#1a1a2e"),
        "done": ("#22863a", "DONE", "#8b949e"),
        "skipped": ("#cf6820", "SKIPPED", "#8b949e"),
    }

    def render_task_row(task: dict, is_last: bool = False) -> str:
        cfg = status_cfg.get(task["status"], ("#999", "?", "#333"))
        dot_color, status_label, text_color = cfg
        text = html.escape(task["text"])
        age = format_age(task["created_at"])
        is_done = task["status"] in ("done", "skipped")
        text_decoration = "text-decoration:line-through;" if is_done else ""
        border = "" if is_last else "border-bottom:1px solid #eef0f4;"

        # Reminder badge
        reminder_cell = ""
        if task.get("reminder_at"):
            try:
                r_utc = datetime.strptime(
                    task["reminder_at"], "%Y-%m-%dT%H:%M:%S.%fZ"
                ).replace(tzinfo=timezone.utc)
                r_bjt = r_utc.astimezone(BJT).strftime("%m/%d %H:%M")
                reminder_cell = (
                    f'<br><span style="font-size:11px;color:#d97706;'
                    f'font-family:Trebuchet MS,Verdana,sans-serif">'
                    f'&#9200; {r_bjt}</span>'
                )
            except Exception:
                pass

        return f"""<tr>
  <td style="padding:12px 0 12px 16px;{border}vertical-align:top;width:10px">
    <div style="width:10px;height:10px;border-radius:50%;background:{dot_color};margin-top:4px"></div>
  </td>
  <td style="padding:12px 8px;{border}vertical-align:top">
    <span style="font-size:10px;font-family:Trebuchet MS,Verdana,sans-serif;letter-spacing:0.6px;color:{dot_color};font-weight:700">{status_label}</span>
  </td>
  <td style="padding:12px 16px 12px 0;{border}vertical-align:top;font-family:Georgia,'Times New Roman',serif;font-size:15px;color:{text_color};line-height:1.5;{text_decoration}">
    {text}{reminder_cell}
  </td>
  <td style="padding:12px 16px 12px 0;{border}vertical-align:top;text-align:right;white-space:nowrap;font-size:12px;font-family:Trebuchet MS,Verdana,sans-serif;color:#94a3b8">
    {age}
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
<table width="100%" cellpadding="0" cellspacing="0" border="0" style="margin-bottom:24px">
  <tr>
    <td style="padding:0 0 10px 16px">
      <span style="font-size:11px;font-family:Trebuchet MS,Verdana,sans-serif;letter-spacing:1.5px;color:#64748b;font-weight:700;text-transform:uppercase">{html.escape(group_name)}</span>
    </td>
  </tr>
  <tr>
    <td>
      <table width="100%" cellpadding="0" cellspacing="0" border="0" style="background:#ffffff;border:1px solid #e2e6ed;border-radius:6px">
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
    <td style="padding:16px 0 10px 16px;border-top:2px solid #eef0f4">
      <span style="font-size:11px;font-family:Trebuchet MS,Verdana,sans-serif;letter-spacing:1.5px;color:#94a3b8;font-weight:700;text-transform:uppercase">Completed &middot; Last 24h</span>
    </td>
  </tr>
  <tr>
    <td>
      <table width="100%" cellpadding="0" cellspacing="0" border="0" style="background:#fafbfc;border:1px solid #e2e6ed;border-radius:6px">
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
      <p style="font-family:Georgia,'Times New Roman',serif;font-size:18px;color:#94a3b8;font-style:italic;margin:0">Nothing on the board. Enjoy the calm.</p>
    </td>
  </tr>
</table>"""

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>Task Brief</title>
</head>
<body style="margin:0;padding:0;background:#f0f2f5;-webkit-text-size-adjust:100%">

<!-- Outer wrapper table for centering -->
<table width="100%" cellpadding="0" cellspacing="0" border="0" style="background:#f0f2f5">
  <tr>
    <td align="center" style="padding:24px 16px">

      <!-- Main container -->
      <table width="580" cellpadding="0" cellspacing="0" border="0" style="max-width:580px;width:100%">

        <!-- Header -->
        <tr>
          <td style="background:#1a1f36;padding:28px 32px 24px;border-radius:8px 8px 0 0">
            <table width="100%" cellpadding="0" cellspacing="0" border="0">
              <tr>
                <td>
                  <span style="font-size:11px;font-family:Trebuchet MS,Verdana,sans-serif;letter-spacing:3px;color:#7c85a6;text-transform:uppercase;font-weight:700">Task Brief</span>
                </td>
                <td align="right">
                  <span style="font-size:11px;font-family:Trebuchet MS,Verdana,sans-serif;letter-spacing:0.5px;color:#7c85a6">{time_str}</span>
                </td>
              </tr>
              <tr>
                <td colspan="2" style="padding-top:8px">
                  <span style="font-family:Georgia,'Times New Roman',serif;font-size:22px;color:#e8eaf0;font-weight:400">{date_str}</span>
                </td>
              </tr>
            </table>
          </td>
        </tr>

        <!-- Metrics row -->
        <tr>
          <td style="background:#252b48;padding:0 0 2px">
            <table width="100%" cellpadding="0" cellspacing="0" border="0">
              <tr>
                <td width="33%" align="center" style="padding:18px 8px;border-right:1px solid #333a58">
                  <span style="font-family:Georgia,'Times New Roman',serif;font-size:28px;color:#6db3f2;font-weight:400;line-height:1">{in_progress}</span>
                  <br>
                  <span style="font-size:10px;font-family:Trebuchet MS,Verdana,sans-serif;letter-spacing:1px;color:#7c85a6;text-transform:uppercase">Active</span>
                </td>
                <td width="34%" align="center" style="padding:18px 8px;border-right:1px solid #333a58">
                  <span style="font-family:Georgia,'Times New Roman',serif;font-size:28px;color:#94a3b8;font-weight:400;line-height:1">{pending}</span>
                  <br>
                  <span style="font-size:10px;font-family:Trebuchet MS,Verdana,sans-serif;letter-spacing:1px;color:#7c85a6;text-transform:uppercase">Queued</span>
                </td>
                <td width="33%" align="center" style="padding:18px 8px">
                  <span style="font-family:Georgia,'Times New Roman',serif;font-size:28px;color:#56d4a0;font-weight:400;line-height:1">{done_today}</span>
                  <br>
                  <span style="font-size:10px;font-family:Trebuchet MS,Verdana,sans-serif;letter-spacing:1px;color:#7c85a6;text-transform:uppercase">Done Today</span>
                </td>
              </tr>
            </table>
          </td>
        </tr>

        <!-- Progress bar -->
        <tr>
          <td style="background:#ffffff;padding:0;border-left:1px solid #e2e6ed;border-right:1px solid #e2e6ed">
            <table width="100%" cellpadding="0" cellspacing="0" border="0">
              <tr>
                <td style="padding:20px 32px 4px">
                  <table width="100%" cellpadding="0" cellspacing="0" border="0">
                    <tr>
                      <td style="font-size:10px;font-family:Trebuchet MS,Verdana,sans-serif;letter-spacing:1px;color:#94a3b8;text-transform:uppercase;padding-bottom:8px">
                        Progress &middot; {done_total} of {done_total + total_active} total
                      </td>
                    </tr>
                    <tr>
                      <td>
                        <table width="100%" cellpadding="0" cellspacing="0" border="0" style="background:#eef0f4;border-radius:3px;height:6px">
                          <tr>
                            <td style="background:linear-gradient(90deg,#0066cc,#56d4a0);border-radius:3px;height:6px;width:{int(done_total / max(done_total + total_active, 1) * 100)}%"></td>
                            <td></td>
                          </tr>
                        </table>
                      </td>
                    </tr>
                  </table>
                </td>
              </tr>
            </table>
          </td>
        </tr>

        <!-- Content area -->
        <tr>
          <td style="background:#ffffff;padding:20px 32px 32px;border-left:1px solid #e2e6ed;border-right:1px solid #e2e6ed;border-radius:0 0 8px 8px;border-bottom:1px solid #e2e6ed">

            {groups_html}

            {recent_html}

            {empty_html}

          </td>
        </tr>

        <!-- Footer -->
        <tr>
          <td style="padding:20px 32px;text-align:center">
            <span style="font-size:11px;font-family:Trebuchet MS,Verdana,sans-serif;color:#94a3b8;letter-spacing:0.3px">
              Delivered every 4 hours &middot; {done_total} done, {skipped_total} skipped all time
            </span>
          </td>
        </tr>

      </table>
      <!-- /Main container -->

    </td>
  </tr>
</table>
<!-- /Outer wrapper -->

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

    now_bjt = datetime.now(BJT).strftime("%b %d %H:%M BJT")
    subject = f"\U0001f4cb Todo Digest - {now_bjt}"

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
