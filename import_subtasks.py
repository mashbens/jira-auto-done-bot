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

from jira_client import JiraError, api, get_config, log


def end_of_month():
    today = date.today()
    last = calendar.monthrange(today.year, today.month)[1]
    return today.replace(day=last).isoformat()


def adf(text):
    """Teks polos -> Atlassian Document Format (wajib di REST API v3)."""
    return {
        "type": "doc",
        "version": 1,
        "content": [
            {"type": "paragraph", "content": [{"type": "text", "text": line}]}
            for line in text.splitlines()
            if line.strip()
        ],
    }


def existing_summaries(cfg, parent):
    result = api(
        cfg,
        "/search/jql",
        "POST",
        {"jql": f"parent = {parent}", "maxResults": 200, "fields": ["summary"]},
    )
    return {i["fields"]["summary"].strip() for i in result.get("issues", [])}


def subtask_type_id(cfg, project):
    """Cari id issue type sub-task, nama 'Sub-task' beda-beda tiap instance."""
    r = api(cfg, f"/issue/createmeta/{project}/issuetypes")
    types = r.get("issueTypes", r.get("values", []))
    for t in types:
        if t.get("subtask") and t["name"].lower() in ("sub-task", "subtask"):
            return t["id"]
    raise JiraError(f"Issue type Sub-task gak ketemu di project {project}")


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
            seen[parent] = existing_summaries(cfg, parent)
        if summary in seen[parent]:
            print(f"  SKIP (sudah ada) {parent} · {summary}")
            skipped += 1
            continue

        if dry_run:
            print(f"  [DRY-RUN] {parent} · {summary} · due {due} · {me['displayName']}")
            continue

        if project not in type_ids:
            type_ids[project] = subtask_type_id(cfg, project)
        fields = {
            "project": {"key": project},
            "parent": {"key": parent},
            "issuetype": {"id": type_ids[project]},
            "summary": summary,
            "assignee": {"accountId": me["accountId"]},
            "duedate": due,
        }
        if (r.get("Description") or "").strip():
            fields["description"] = adf(r["Description"])

        res = api(cfg, "/issue", "POST", {"fields": fields})
        seen[parent].add(summary)
        created += 1
        log(f"DIBUAT {res['key']} di {parent} — {summary}")

    if not dry_run:
        print(f"Selesai: {created} dibuat, {skipped} di-skip.")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except JiraError as e:
        log(f"GAGAL: {e}")
        sys.exit(1)
