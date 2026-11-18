#!/usr/bin/env python3
"""
Bikin sub-task Jira massal dari CSV.

Kolom CSV: Issue Type,Summary,Parent,Description
Sub-task otomatis di-assign ke current user, due date default akhir bulan ini.
Summary yang sudah ada di parent yang sama di-skip, jadi aman dijalankan ulang.

  python3 import_subtasks.py file.csv --dry-run         # cek dulu, tanpa ngubah apa-apa
  python3 import_subtasks.py file.csv                   # beneran bikin
  python3 import_subtasks.py file.csv --due 2026-11-15  # due date eksplisit
"""

import calendar
import csv
import sys
from datetime import date

from jira_client import (
    JiraError,
    api,
    create_subtask,
    existing_children,
    get_config,
    log,
    subtask_type_id,
)


def end_of_month():
    today = date.today()
    last = calendar.monthrange(today.year, today.month)[1]
    return today.replace(day=last).isoformat()


def main():
    args = sys.argv[1:]
    if not args or args[0].startswith("-"):
        print(__doc__)
        return 1
    csv_path = args[0]
    dry_run = "--dry-run" in args
    due = args[args.index("--due") + 1] if "--due" in args else end_of_month()

    cfg = get_config()
    me = api(cfg, "/myself")

    with open(csv_path, newline="", encoding="utf-8-sig") as f:
        rows = [r for r in csv.DictReader(f) if (r.get("Summary") or "").strip()]

    type_ids, seen = {}, {}
    created = skipped = 0
    for r in rows:
        parent = r["Parent"].strip()
        summary = r["Summary"].strip()
        project = parent.rsplit("-", 1)[0]

        if parent not in seen:
            seen[parent] = set(existing_children(cfg, parent))
        if summary in seen[parent]:
            print(f"  SKIP (sudah ada) {parent} · {summary}")
            skipped += 1
            continue

        if dry_run:
            print(f"  [DRY-RUN] {parent} · {summary} · due {due} · {me['displayName']}")
            continue

        if project not in type_ids:
            type_ids[project] = subtask_type_id(cfg, project)
        key = create_subtask(
            cfg, parent, summary, r.get("Description"), due, me["accountId"],
            type_ids[project],
        )
        seen[parent].add(summary)
        created += 1
        log(f"DIBUAT {key} di {parent} — {summary}")

    if not dry_run:
        print(f"Selesai: {created} dibuat, {skipped} di-skip.")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except JiraError as e:
        log(f"GAGAL: {e}")
        sys.exit(1)
