#!/usr/bin/env python3
"""
Pengganti cron di dalam container.

Tiap menit dia cek jam. Kalau sudah masuk jadwal (default Senin-Jumat 17:00),
jalankan jira_daily_done sekali. Pengaman 1-per-hari tetap dipegang state file,
jadi kalau container restart di jam yang sama, dia gak double-done.

Config di .env:
  SCHEDULE_TIME=17:00
  SCHEDULE_DAYS=1-5     (1=Senin ... 7=Minggu)
  TZ=Asia/Jakarta
"""

import os
import time
from datetime import datetime

import jira_daily_done
from jira_client import JiraError, load_env, log


def parse_days(spec):
    """'1-5' atau '1,3,5' -> set isoweekday."""
    days = set()
    for part in spec.split(","):
        part = part.strip()
        if "-" in part:
            a, b = part.split("-")
            days.update(range(int(a), int(b) + 1))
        elif part:
            days.add(int(part))
    return days or {1, 2, 3, 4, 5}


def main():
    load_env()
    target = os.environ.get("SCHEDULE_TIME", "17:00").strip()
    days = parse_days(os.environ.get("SCHEDULE_DAYS", "1-5"))
    hh, mm = (int(x) for x in target.split(":"))

    log(
        f"Scheduler jalan. Target {target} pada hari {sorted(days)} "
        f"(TZ={os.environ.get('TZ', 'system')})"
    )

    last_fired = None
    while True:
        now = datetime.now()
        today = now.date().isoformat()
        due = now.isoweekday() in days and now.hour == hh and now.minute == mm

        if due and last_fired != today:
            last_fired = today
            log(f"Jadwal {target} tercapai, menjalankan tugas harian.")
            try:
                jira_daily_done.main()
            except JiraError as e:
                log(f"GAGAL: {e}")
            except Exception as e:  # scheduler jangan mati gara-gara 1 run gagal
                log(f"Error tak terduga: {type(e).__name__}: {e}")

        time.sleep(30)


if __name__ == "__main__":
    main()
