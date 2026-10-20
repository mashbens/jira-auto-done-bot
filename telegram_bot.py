#!/usr/bin/env python3
"""
Bot Telegram buat nge-done sub-task Jira secara manual.

  /l           daftar sub-task open, centang lalu bulk done
  /next        sub-task yang paling lama nganggur
  /done KEY    langsung done issue tertentu
  /status      ringkasan antrian

Long polling, stdlib doang. Jalankan: python3 telegram_bot.py
"""

import html
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request

from jira_client import (
    JiraError,
    complete_issue,
    get_config,
    get_issue,
    list_open_subtasks,
    load_env,
    log,
)

PAGE_SIZE = 8
LIST_LIMIT = 300
MAX_BULK = 50  # rem darurat biar salah tap gak nge-done ratusan issue

# State per chat, cukup di memori: kalau bot restart, centangan hilang.
# callback_data Telegram maks 64 byte, jadi pilihan gak bisa dititip di tombol.
cache = {}  # chat_id -> list issue dari fetch terakhir
selected = {}  # chat_id -> set key yang dicentang


def tg(method, payload=None):
    url = f"https://api.telegram.org/bot{os.environ['TELEGRAM_BOT_TOKEN']}/{method}"
    data = json.dumps(payload or {}).encode()
    req = urllib.request.Request(url, data=data, method="POST")
    req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=90) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        log(f"Telegram ERROR {method}: {e.read().decode()[:300]}")
        return {}
    except urllib.error.URLError as e:
        log(f"Telegram gagal konek: {e.reason}")
        return {}


def send(chat_id, text, keyboard=None):
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }
    if keyboard:
        payload["reply_markup"] = {"inline_keyboard": keyboard}
    return tg("sendMessage", payload)


def edit(chat_id, message_id, text, keyboard=None):
    payload = {
        "chat_id": chat_id,
        "message_id": message_id,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }
    if keyboard:
        payload["reply_markup"] = {"inline_keyboard": keyboard}
    return tg("editMessageText", payload)


def is_allowed(chat_id):
    """Whitelist chat id. Tanpa ini siapa pun yang nemu bot bisa ngubah Jira kamu."""
    allowed = os.environ.get("TELEGRAM_ALLOWED_CHAT_ID", "").strip()
    if not allowed:
        return False
    return str(chat_id) in [c.strip() for c in allowed.split(",")]


def page_chunk(issues, page):
    pages = max(1, (len(issues) + PAGE_SIZE - 1) // PAGE_SIZE)
    page = max(0, min(page, pages - 1))
    return issues[page * PAGE_SIZE : (page + 1) * PAGE_SIZE], page, pages


def build_list(cfg, chat_id, page=0, refresh=False):
    # Toggle centang pakai cache, biar tiap tap gak nembak Jira lagi
    if refresh or chat_id not in cache:
        cache[chat_id] = list_open_subtasks(cfg, limit=LIST_LIMIT)
    issues = cache[chat_id]
    sel = selected.setdefault(chat_id, set())
    sel &= {i["key"] for i in issues}  # buang yang sudah gak open
    if not issues:
        return "Gak ada sub-task open. Bersih. 🎉", None

    chunk, page, pages = page_chunk(issues, page)

    lines = [
        f"<b>{len(issues)} sub-task open</b> — halaman {page + 1}/{pages}"
        f" · {len(sel)} dipilih",
        "",
    ]
    buttons = []
    for i in chunk:
        f = i["fields"]
        mark = "☑️" if i["key"] in sel else "⬜"
        lines.append(
            f"{mark} <code>{i['key']}</code> · {f['status']['name']}\n"
            f"{html.escape(f['summary'])}"
        )
        lines.append("")
        buttons.append(
            {"text": f"{mark} {i['key']}", "callback_data": f"tog:{i['key']}:{page}"}
        )
    keyboard = [buttons[n : n + 2] for n in range(0, len(buttons), 2)]
    keyboard.append(
        [
            {"text": "☑️ Pilih hal. ini", "callback_data": f"all:{page}"},
            {"text": "⬜ Kosongkan", "callback_data": f"clr:{page}"},
        ]
    )

    nav = []
    if page > 0:
        nav.append({"text": "⬅️ Prev", "callback_data": f"page:{page - 1}"})
    if page < pages - 1:
        nav.append({"text": "Next ➡️", "callback_data": f"page:{page + 1}"})
    if nav:
        keyboard.append(nav)
    if sel:
        keyboard.append(
            [{"text": f"✅ Done terpilih ({len(sel)})", "callback_data": f"bulk:{page}"}]
        )
    keyboard.append([{"text": "🔄 Refresh", "callback_data": f"ref:{page}"}])

    return "\n".join(lines), keyboard


def back_button(page):
    return [[{"text": "📋 Kembali ke list", "callback_data": f"ref:{page}"}]]


def confirm_bulk(chat_id, message_id, page):
    keys = sorted(selected.get(chat_id, ()))
    if not keys:
        edit(chat_id, message_id, "Belum ada yang dicentang.", back_button(page))
        return
    if len(keys) > MAX_BULK:
        edit(
            chat_id,
            message_id,
            f"Kebanyakan: {len(keys)} dipilih, maksimal {MAX_BULK} sekali jalan.",
            [[{"text": "📋 Kembali ke list", "callback_data": f"page:{page}"}]],
        )
        return
    listing = "\n".join(f"• <code>{k}</code>" for k in keys)
    edit(
        chat_id,
        message_id,
        f"Yakin mau done <b>{len(keys)} issue</b> ini?\n\n{listing}",
        [
            [
                {"text": f"✅ Ya, done {len(keys)}", "callback_data": f"bdo:{page}"},
                {"text": "❌ Batal", "callback_data": f"page:{page}"},
            ]
        ],
    )


def run_bulk(cfg, chat_id, message_id, page):
    keys = sorted(selected.get(chat_id, ()))
    # Kosongkan duluan: tap dobel di tombol konfirmasi jadi gak jalan dua kali
    selected[chat_id] = set()
    if not keys:
        edit(chat_id, message_id, "Gak ada yang dipilih.", back_button(page))
        return

    ok, fail = [], []
    for n, key in enumerate(keys, 1):
        edit(chat_id, message_id, f"⏳ Proses {n}/{len(keys)}: <code>{key}</code>...")
        try:
            complete_issue(cfg, get_issue(cfg, key))
            ok.append(key)
        except JiraError as e:
            fail.append((key, str(e)))
    cache.pop(chat_id, None)
    log(f"BULK done: {len(ok)} berhasil, {len(fail)} gagal")

    text = f"✅ <b>{len(ok)} berhasil</b>"
    if fail:
        text += f", ⚠️ <b>{len(fail)} gagal</b>\n\n" + "\n".join(
            f"<code>{k}</code>: {html.escape(e)}" for k, e in fail
        )
    edit(chat_id, message_id, text, back_button(page))


def handle_command(cfg, chat_id, text):
    cmd, _, arg = text.partition(" ")
    cmd = cmd.split("@")[0].lower()
    arg = arg.strip()

    if cmd in ("/start", "/help"):
        send(
            chat_id,
            "<b>Jira sub-task bot</b>\n\n"
            "/l — daftar sub-task open, centang lalu done sekaligus\n"
            "/next — sub-task yang paling lama nganggur\n"
            "/done KEY — langsung done issue tertentu\n"
            "/status — ringkasan antrian",
        )
    elif cmd == "/l":
        text, keyboard = build_list(cfg, chat_id, 0, refresh=True)
        send(chat_id, text, keyboard)
    elif cmd == "/next":
        issues = list_open_subtasks(cfg, limit=1)
        if not issues:
            send(chat_id, "Antrian kosong.")
        else:
            f = issues[0]["fields"]
            send(
                chat_id,
                f"Berikutnya: <code>{issues[0]['key']}</code> ({f['status']['name']})\n"
                f"{f['summary']}",
                [[{"text": "✅ Done sekarang", "callback_data": f"ask:{issues[0]['key']}:0"}]],
            )
    elif cmd == "/status":
        issues = list_open_subtasks(cfg, limit=LIST_LIMIT)
        by_status = {}
        for i in issues:
            s = i["fields"]["status"]["name"]
            by_status[s] = by_status.get(s, 0) + 1
        detail = "\n".join(f"  • {k}: {v}" for k, v in by_status.items())
        send(chat_id, f"<b>{len(issues)} sub-task open</b>\n{detail}")
    elif cmd == "/done":
        if not arg:
            send(chat_id, "Formatnya: <code>/done ATIDIS26-1387</code>")
            return
        ask_confirm(chat_id, arg.upper(), 0)
    else:
        send(chat_id, "Perintah gak dikenal. Coba /help")


def ask_confirm(chat_id, key, page, message_id=None):
    text = f"Yakin mau done <code>{key}</code>?"
    keyboard = [
        [
            {"text": "✅ Ya, done", "callback_data": f"do:{key}:{page}"},
            {"text": "❌ Batal", "callback_data": f"page:{page}"},
        ]
    ]
    if message_id:
        edit(chat_id, message_id, text, keyboard)
    else:
        send(chat_id, text, keyboard)


def handle_callback(cfg, cb):
    chat_id = cb["message"]["chat"]["id"]
    message_id = cb["message"]["message_id"]
    data = cb["data"]
    tg("answerCallbackQuery", {"callback_query_id": cb["id"]})

    action, _, rest = data.partition(":")

    if action in ("page", "ref"):
        text, keyboard = build_list(cfg, chat_id, int(rest), refresh=action == "ref")
        edit(chat_id, message_id, text, keyboard)
    elif action in ("tog", "all", "clr"):
        if action == "tog":
            key, _, rest = rest.partition(":")
            selected.setdefault(chat_id, set()).symmetric_difference_update({key})
        elif action == "all" and chat_id in cache:
            chunk, _, _ = page_chunk(cache[chat_id], int(rest))
            selected.setdefault(chat_id, set()).update(i["key"] for i in chunk)
        elif action == "clr":
            selected[chat_id] = set()
        text, keyboard = build_list(cfg, chat_id, int(rest))
        edit(chat_id, message_id, text, keyboard)
    elif action == "bulk":
        confirm_bulk(chat_id, message_id, int(rest))
    elif action == "bdo":
        run_bulk(cfg, chat_id, message_id, int(rest))
    elif action == "ask":
        key, _, page = rest.partition(":")
        ask_confirm(chat_id, key, int(page or 0), message_id)
    elif action == "do":
        key, _, page = rest.partition(":")
        try:
            issue = get_issue(cfg, key)
            steps = complete_issue(cfg, issue)
            base = cfg["base_url"].rstrip("/")
            edit(
                chat_id,
                message_id,
                f"✅ <b>{key}</b> selesai\n"
                f"{issue['fields']['summary']}\n\n"
                f"<i>{'; '.join(steps)}</i>\n"
                f'<a href="{base}/browse/{key}">Buka di Jira</a>',
                [[{"text": "📋 Kembali ke list", "callback_data": f"ref:{page or 0}"}]],
            )
        except JiraError as e:
            edit(
                chat_id,
                message_id,
                f"⚠️ Gagal nge-done <code>{key}</code>\n\n{e}",
                [[{"text": "📋 Kembali ke list", "callback_data": f"ref:{page or 0}"}]],
            )


def main():
    load_env()
    if not os.environ.get("TELEGRAM_BOT_TOKEN"):
        print("TELEGRAM_BOT_TOKEN belum diisi di .env")
        return 1

    try:
        cfg = get_config()
    except JiraError as e:
        log(f"Config Jira bermasalah: {e}")
        log("Perbaiki .env lalu: docker compose up -d --force-recreate")
        return 1

    me = tg("getMe").get("result", {})
    if not me:
        log("Token Telegram ditolak. Cek TELEGRAM_BOT_TOKEN di .env")
        return 1
    log(f"Bot jalan sebagai @{me.get('username')}. Ctrl-C buat berhenti.")

    if not os.environ.get("TELEGRAM_ALLOWED_CHAT_ID", "").strip():
        log("PERINGATAN: TELEGRAM_ALLOWED_CHAT_ID kosong — semua pesan bakal ditolak.")

    offset = None
    while True:
        payload = {"timeout": 60}
        if offset:
            payload["offset"] = offset
        updates = tg("getUpdates", payload).get("result", [])
        for u in updates:
            offset = u["update_id"] + 1
            try:
                if "message" in u and "text" in u["message"]:
                    chat_id = u["message"]["chat"]["id"]
                    if not is_allowed(chat_id):
                        log(f"DITOLAK chat_id={chat_id}: {u['message']['text'][:40]}")
                        send(chat_id, f"Akses ditolak. Chat ID kamu: <code>{chat_id}</code>")
                        continue
                    handle_command(cfg, chat_id, u["message"]["text"])
                elif "callback_query" in u:
                    cb = u["callback_query"]
                    if not is_allowed(cb["message"]["chat"]["id"]):
                        tg("answerCallbackQuery", {"callback_query_id": cb["id"]})
                        continue
                    handle_callback(cfg, cb)
            except JiraError as e:
                log(f"JiraError: {e}")
            except Exception as e:  # bot jangan mati gara-gara 1 update aneh
                log(f"Error tak terduga: {type(e).__name__}: {e}")


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\nBot dihentikan.")
