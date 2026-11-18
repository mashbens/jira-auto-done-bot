.DEFAULT_GOAL := help
COMPOSE := docker compose
# Pakai venv kalau ada (butuh gspread buat /s), kalau gak ya python3 sistem
PY := $(if $(wildcard .venv/bin/python),.venv/bin/python,python3)

.PHONY: help build up down restart logs ps shell \
        dry-run next done import status bot-local stop-local clean env-check \
        install sheet-check

help: ## Tampilkan daftar perintah
	@grep -hE '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) \
		| awk 'BEGIN{FS=":.*?## "}{printf "  \033[36m%-14s\033[0m %s\n", $$1, $$2}'

## --- Docker ---

build: ## Build image
	$(COMPOSE) build

up: ## Jalankan bot di background
	$(COMPOSE) up -d --build
	@$(MAKE) --no-print-directory ps

down: ## Stop dan hapus container
	$(COMPOSE) down

restart: ## Restart bot
	$(COMPOSE) restart

ps: ## Status container
	$(COMPOSE) ps

logs: ## Ikuti log bot
	$(COMPOSE) logs -f --tail=50

shell: ## Masuk shell di container bot
	$(COMPOSE) exec bot /bin/bash

## --- Operasi Jira (jalan di host, tanpa Docker) ---

dry-run: ## Lihat kandidat berikutnya, tanpa mengubah apa pun
	$(PY) jira_daily_done.py --dry-run

next: dry-run ## Alias dari dry-run

done: ## Done satu issue: make done ISSUE=ATIDIS26-1387
	@test -n "$(ISSUE)" || { echo "Pakai: make done ISSUE=ATIDIS26-1387"; exit 1; }
	$(PY) jira_daily_done.py --issue $(ISSUE)

import: ## Bikin sub-task dari CSV: make import CSV=file.csv [DRY=1] [DUE=YYYY-MM-DD]
	@test -n "$(CSV)" || { echo "Pakai: make import CSV=file.csv [DRY=1] [DUE=2026-11-30]"; exit 1; }
	$(PY) import_subtasks.py $(CSV) $(if $(DRY),--dry-run) $(if $(DUE),--due $(DUE))

status: ## Ringkasan antrian sub-task open
	@$(PY) -c "from jira_client import get_config, list_open_subtasks; \
	from collections import Counter; \
	cfg = get_config(); i = list_open_subtasks(cfg, 50); \
	c = Counter(x['fields']['status']['name'] for x in i); \
	print(f'{len(i)} sub-task open'); \
	[print(f'  - {k}: {v}') for k, v in c.items()]"

env-check: ## Cek konfigurasi .env terbaca dan kredensial Jira valid
	@$(PY) -c "from jira_client import get_config, api; \
	cfg = get_config(); me = api(cfg, '/myself'); \
	print('Jira OK  ->', me['displayName'], '<'+me['emailAddress']+'>'); \
	print('JQL      ->', cfg['jql'][:70] + '...'); \
	print('Alur     ->', ' -> '.join(cfg['status_path']))"

sheet-check: ## Cek koneksi Google Sheet dan tampilkan baris yang belum DONE
	@$(PY) -c "from jira_client import load_env; load_env(); import sheet_tasks as s; \
	rows = s.pending_rows(); print(f'Sheet OK -> {len(rows)} baris belum DONE'); \
	[print(f\"  #{r['row']} {r['Parent']} {r['Summary'][:60]} {r['Status']}\") for r in rows]"

## --- Mode lokal (tanpa Docker) ---

install: ## Bikin .venv dan install dependency (gspread)
	python3 -m venv .venv
	.venv/bin/pip install -r requirements.txt

bot-local: ## Jalankan bot Telegram di foreground
	$(PY) telegram_bot.py

stop-local: ## Matikan bot yang jalan di luar Docker
	@# Kurung siku bikin pola tidak cocok dengan command line make/shell ini sendiri,
	@# kalau tidak pkill bakal bunuh diri sebelum target berikutnya jalan.
	-@pkill -f "[t]elegram_bot.py" || true
	@echo "Bot lokal dihentikan."

clean: ## Hapus cache Python dan file sementara
	rm -rf __pycache__ bot.out
	@# .venv sengaja gak dihapus, bikin ulang pakai: make install
	@echo "Bersih. State & log di data/ tidak disentuh."
