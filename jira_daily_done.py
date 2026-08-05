#!/usr/bin/env python3
"""
Auto-done 1 sub-task Jira per hari (dipanggil cron).

Ambil sub-task open paling lama sesuai JQL di .env, lalu transisi ke DONE.
Idempotent: kalau hari ini sudah pernah nge-done, dia skip.

  python3 jira_daily_done.py              # mode normal (dipakai cron)
  python3 jira_daily_done.py --dry-run    # lihat kandidat, tanpa ngubah apa-apa
  python3 jira_daily_done.py --issue KEY  # target manual, abaikan batas 1-per-hari
"""

import json
import sys
from datetime import date

from jira_client import (
    DATA_DIR,
    JiraError,
    complete_issue,
    get_config,
    get_issue,
    list_open_subtasks,
    log,
)

STATE_FILE = DATA_DIR / ".last_run_state.json"


def already_done_today():
    if not STATE_FILE.exists():
        return False
    state = json.loads(STATE_FILE.read_text())
    return state.get("last_done_date") == date.today().isoformat()


def save_state(issue_key):
    STATE_FILE.write_text(
        json.dumps({"last_done_date": date.today().isoformat(), "issue": issue_key})
    )


def main():
    cfg = get_config()

    target_key = None
    if "--issue" in sys.argv:
        target_key = sys.argv[sys.argv.index("--issue") + 1]

    # --dry-run gak ngubah apa-apa, jadi gak perlu kena batas 1-per-hari
    if not target_key and "--dry-run" not in sys.argv and already_done_today():
        log("Sudah ada sub-task yang di-done hari ini, skip.")
        return 0

    if target_key:
        issue = get_issue(cfg, target_key)
    else:
        issues = list_open_subtasks(cfg, limit=1)
        if not issues:
            log("Gak ada sub-task open yang cocok dengan JQL. Selesai.")
            return 0
        issue = issues[0]

    key, fields = issue["key"], issue["fields"]
    if "--dry-run" in sys.argv:
        log(
            f"[DRY-RUN] kandidat: {key} ({fields['status']['name']}) — "
            f"{fields['summary']}; rencana: {cfg['status_path']}"
        )
        return 0

    complete_issue(cfg, issue)
    save_state(key)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except JiraError as e:
        log(f"GAGAL: {e}")
        sys.exit(1)
