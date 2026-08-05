#!/usr/bin/env python3
"""Helper Jira yang dipakai bareng oleh bot Telegram dan CLI jira_daily_done."""

import base64
import json
import os
import urllib.error
import urllib.request
from datetime import date, datetime
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
# Di Docker diarahkan ke volume (/data) supaya state & log gak ilang saat recreate.
DATA_DIR = Path(os.environ.get("DATA_DIR") or BASE_DIR)
LOG_FILE = DATA_DIR / "jira_daily_done.log"


class JiraError(Exception):
    """Error dari Jira yang pesannya sudah layak ditampilkan ke user."""


def load_env():
    """Baca .env sederhana (KEY=VALUE) di folder yang sama."""
    env_file = BASE_DIR / ".env"
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def log(msg):
    stamp = f"[{datetime.now().strftime('%Y-%m-%d %H:%M')}] {msg}"
    print(stamp, flush=True)
    try:
        with LOG_FILE.open("a") as f:
            f.write(stamp + "\n")
    except OSError as e:
        # Volume read-only atau salah owner (bind mount dibuat root, container UID 1000).
        # stdout sudah kepegang docker logs, jadi jangan bikin proses mati gara-gara ini.
        print(f"  (log ke {LOG_FILE} gagal: {e})", flush=True)


def get_config():
    load_env()
    cfg = {
        "base_url": os.environ.get("JIRA_BASE_URL", ""),
        "email": os.environ.get("JIRA_EMAIL", ""),
        "token": os.environ.get("JIRA_API_TOKEN", ""),
    }
    cfg["jql"] = os.environ.get("JIRA_JQL", "")
    # Multi-hop, dipisah koma. Workflow ATIDIS26: Start -> in progress -> DONE
    cfg["status_path"] = [
        s.strip()
        for s in os.environ.get("JIRA_STATUS_PATH", "DONE").split(",")
        if s.strip()
    ]
    cfg["comment"] = os.environ.get("JIRA_COMMENT", "")
    # "today" | "" (jangan diisi) | tanggal eksplisit YYYY-MM-DD
    due_cfg = os.environ.get("JIRA_DUE_DATE", "today").strip()
    cfg["set_due"] = date.today().isoformat() if due_cfg == "today" else due_cfg

    missing = [k for k in ("base_url", "email", "token", "jql") if not cfg[k]]
    if missing:
        raise JiraError(f"Config belum lengkap di .env: {missing}")
    return cfg


def api(cfg, path, method="GET", body=None):
    url = f"{cfg['base_url'].rstrip('/')}/rest/api/3{path}"
    data = json.dumps(body).encode() if body is not None else None
    token = base64.b64encode(f"{cfg['email']}:{cfg['token']}".encode()).decode()
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Authorization", f"Basic {token}")
    req.add_header("Accept", "application/json")
    if data:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            raw = resp.read()
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as e:
        detail = e.read().decode()[:400]
        log(f"ERROR {method} {path} -> HTTP {e.code}: {detail}")
        try:
            msgs = json.loads(detail).get("errorMessages") or []
            if msgs:
                raise JiraError(msgs[0]) from e
        except (ValueError, AttributeError):
            pass
        raise JiraError(f"HTTP {e.code} dari Jira") from e
    except urllib.error.URLError as e:
        raise JiraError(f"Gagal konek ke Jira: {e.reason}") from e


FIELDS = ["summary", "status", "duedate", "parent"]


def list_open_subtasks(cfg, limit=50):
    """Sub-task open sesuai JQL di .env, urut dari yang paling lama."""
    result = api(
        cfg,
        "/search/jql",
        "POST",
        {"jql": cfg["jql"], "maxResults": limit, "fields": FIELDS},
    )
    return result.get("issues", [])


def get_issue(cfg, key):
    return api(cfg, f"/issue/{key}?fields={','.join(FIELDS)}")


def complete_issue(cfg, issue):
    """Jalankan status_path pada satu issue. Return list langkah yang dilakukan."""
    key = issue["key"]
    current = issue["fields"]["status"]["name"]
    steps = []

    # Workflow ATIDIS26 punya validator "Due date is required" saat transisi.
    # Isi dulu kalau masih kosong, kalau tidak POST transisi bakal ditolak 400.
    if cfg["set_due"] and not issue["fields"].get("duedate"):
        api(cfg, f"/issue/{key}", "PUT", {"fields": {"duedate": cfg["set_due"]}})
        steps.append(f"due date diisi {cfg['set_due']}")

    for step in cfg["status_path"]:
        if current.lower() == step.lower():
            continue  # sudah di status ini, lanjut hop berikutnya
        transitions = api(cfg, f"/issue/{key}/transitions")["transitions"]
        match = next(
            (t for t in transitions if t["to"]["name"].lower() == step.lower()), None
        )
        if not match:
            available = [f"{t['name']} -> {t['to']['name']}" for t in transitions]
            raise JiraError(
                f"dari '{current}' gak ada transisi ke '{step}'. Yang ada: {available}"
            )
        api(cfg, f"/issue/{key}/transitions", "POST", {"transition": {"id": match["id"]}})
        steps.append(f"{current} -> {step}")
        current = step

    if cfg["comment"]:
        api(
            cfg,
            f"/issue/{key}/comment",
            "POST",
            {
                "body": {
                    "type": "doc",
                    "version": 1,
                    "content": [
                        {
                            "type": "paragraph",
                            "content": [{"type": "text", "text": cfg["comment"]}],
                        }
                    ],
                }
            },
        )

    log(f"SELESAI {key} — {'; '.join(steps)}")
    return steps
