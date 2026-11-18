#!/usr/bin/env python3
"""
Antrian sub-task dari Google Sheet: create di Jira lalu langsung di-done.

Tab sheet (default "Jira Subtask") kolomnya:
  Parent | Summary | Description | Key | Status | Done At
Parent/Summary/Description diisi manusia, Key/Status/Done At diisi bot.

Satu-satunya modul yang butuh dependency luar (gspread), soalnya login
service account Google perlu tanda tangan RSA yang gak ada di stdlib.
gspread di-import pas dipakai aja, jadi CLI lain tetap jalan tanpa itu.
"""

import os
import time
from datetime import date, datetime

from jira_client import (
    BASE_DIR,
    JiraError,
    api,
    complete_issue,
    create_subtask,
    existing_children,
    get_issue,
    log,
    subtask_type_id,
)

HEADERS = ["Parent", "Summary", "Description", "Key", "Status", "Done At"]
FINAL = "DONE"

_ws = None  # worksheet, dibuka sekali per proses


def configured():
    return bool(os.environ.get("SHEET_ID", "").strip())


def worksheet():
    global _ws
    if _ws is None:
        try:
            import gspread
        except ImportError as e:
            raise JiraError("gspread belum ke-install. Jalankan: make install") from e
        cred = os.environ.get("GOOGLE_CREDENTIALS") or str(BASE_DIR / "credentials.json")
        tab = os.environ.get("SHEET_TAB", "Jira Subtask")
        try:
            gc = gspread.service_account(filename=cred)
            _ws = gc.open_by_key(os.environ["SHEET_ID"].strip()).worksheet(tab)
        except FileNotFoundError as e:
            raise JiraError(f"File credentials Google gak ada: {cred}") from e
        except gspread.WorksheetNotFound as e:
            raise JiraError(f"Tab '{tab}' gak ada di spreadsheet") from e
        except gspread.exceptions.APIError as e:
            raise JiraError(f"Google Sheets nolak: {e}") from e
    return _ws


def pending_rows():
    """Baris yang Parent+Summary-nya keisi tapi Status belum DONE."""
    values = worksheet().get_all_values()
    if not values:
        return []
    header = [h.strip() for h in values[0]]
    missing = [h for h in HEADERS if h not in header]
    if missing:
        raise JiraError(f"Header sheet kurang: {missing}")
    col = {h: header.index(h) for h in HEADERS}

    rows = []
    for n, raw in enumerate(values[1:], start=2):
        raw = raw + [""] * (len(header) - len(raw))
        r = {h: raw[col[h]].strip() for h in HEADERS}
        if not r["Parent"] or not r["Summary"]:
            continue
        if r["Status"].upper() == FINAL:
            continue
        r["row"] = n
        r["Parent"] = r["Parent"].upper()
        rows.append(r)
    return rows


def write_back(row, key, status):
    """Isi Key/Status/Done At di baris itu. Done At cuma diisi kalau DONE.

    Gagal nulis ke sheet gak boleh ngebatalin proses: Jira-nya sudah berubah,
    jadi cukup di-log dan dilaporin. Return False kalau gagal.
    """
    try:
        import gspread.utils

        ws = worksheet()
        header = [h.strip() for h in ws.row_values(1)]
        done_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S") if status == FINAL else ""
        ws.batch_update(
            [
                {
                    "range": gspread.utils.rowcol_to_a1(row, header.index(name) + 1),
                    "values": [[value]],
                }
                for name, value in (("Key", key), ("Status", status), ("Done At", done_at))
            ]
        )
        return True
    except Exception as e:  # noqa: BLE001 — apa pun error-nya, Jira jangan ikut gagal
        log(f"SHEET gagal nulis baris {row} ({key} {status}): {type(e).__name__}: {e}")
        return False


class Runner:
    """Proses beberapa baris sekaligus; cache lookup Jira yang sama antar baris."""

    def __init__(self, cfg):
        self.cfg = cfg
        self.me = api(cfg, "/myself")["accountId"]
        self.type_ids = {}
        self.children = {}
        self.parent_ok = {}
        self.delay = float(os.environ.get("SHEET_DELAY", "1.5"))

    def check_parent(self, parent):
        if parent not in self.parent_ok:
            f = api(self.cfg, f"/issue/{parent}?fields=issuetype,summary")["fields"]
            t = f["issuetype"]
            if t.get("subtask"):
                self.parent_ok[parent] = "parent-nya sub-task, harus Story"
            elif t["name"].lower() == "epic":
                self.parent_ok[parent] = "parent-nya Epic, harus Story"
            else:
                self.parent_ok[parent] = ""
        if self.parent_ok[parent]:
            raise JiraError(self.parent_ok[parent])

    def process(self, r):
        """Create (kalau belum ada) -> jeda -> done. Return (key, status, catatan)."""
        parent, summary = r["Parent"], r["Summary"]
        key = r["Key"]
        try:
            if not key:
                self.check_parent(parent)
                if parent not in self.children:
                    self.children[parent] = existing_children(self.cfg, parent)
                key = self.children[parent].get(summary, "")
            if key:
                note = "sudah ada di Jira, tinggal di-done"
            else:
                project = parent.rsplit("-", 1)[0]
                if project not in self.type_ids:
                    self.type_ids[project] = subtask_type_id(self.cfg, project)
                key = create_subtask(
                    self.cfg, parent, summary, r["Description"],
                    date.today().isoformat(), self.me, self.type_ids[project],
                )
                self.children[parent][summary] = key
                log(f"SHEET DIBUAT {key} di {parent} — {summary}")
                note = "dibuat"
                time.sleep(self.delay)
        except JiraError as e:
            status = f"GAGAL create: {e}"
            ok = write_back(r["row"], key, status)
            return key, status, "" if ok else "gagal nulis ke sheet"

        # Create sukses tapi done gagal = sub-task gantung. Coba sekali lagi,
        # complete_issue aman diulang karena status yang sudah lewat di-skip.
        err = None
        for attempt in range(2):
            try:
                complete_issue(self.cfg, get_issue(self.cfg, key))
                err = None
                break
            except JiraError as e:
                err = e
                log(f"SHEET done {key} gagal (percobaan {attempt + 1}): {e}")
                time.sleep(2)
        status = FINAL if err is None else f"GAGAL done: {err}"
        if not write_back(r["row"], key, status):
            note += ", ⚠️ gagal nulis ke sheet"
        return key, status, note
