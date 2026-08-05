.DEFAULT_GOAL := help
COMPOSE := docker compose
PY := python3

.PHONY: help build up down restart logs logs-bot logs-sched ps shell \
        dry-run next done status bot-local sched-local stop-local \
        stop-legacy clean env-check

help: ## Tampilkan daftar perintah
	@grep -hE '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) \
		| awk 'BEGIN{FS=":.*?## "}{printf "  \033[36m%-14s\033[0m %s\n", $$1, $$2}'

## --- Docker ---

build: ## Build image
	$(COMPOSE) build

up: ## Jalankan bot + scheduler di background
	$(COMPOSE) up -d --build
	@$(MAKE) --no-print-directory ps

down: ## Stop dan hapus container
	$(COMPOSE) down

restart: ## Restart kedua service
	$(COMPOSE) restart

ps: ## Status container
	$(COMPOSE) ps

logs: ## Ikuti log semua service
	$(COMPOSE) logs -f --tail=50

logs-bot: ## Ikuti log bot Telegram saja
	$(COMPOSE) logs -f --tail=50 bot

logs-sched: ## Ikuti log scheduler saja
	$(COMPOSE) logs -f --tail=50 scheduler

shell: ## Masuk shell di container bot
	$(COMPOSE) exec bot /bin/bash

## --- Operasi Jira (jalan di host, tanpa Docker) ---

dry-run: ## Lihat kandidat berikutnya, tanpa mengubah apa pun
	$(PY) jira_daily_done.py --dry-run

next: dry-run ## Alias dari dry-run

done: ## Done satu issue: make done ISSUE=ATIDIS26-1387
	@test -n "$(ISSUE)" || { echo "Pakai: make done ISSUE=ATIDIS26-1387"; exit 1; }
	$(PY) jira_daily_done.py --issue $(ISSUE)

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

## --- Mode lokal (tanpa Docker) ---

bot-local: ## Jalankan bot Telegram di foreground
	$(PY) telegram_bot.py

sched-local: ## Jalankan scheduler di foreground
	$(PY) scheduler_loop.py

stop-local: ## Matikan bot/scheduler yang jalan di luar Docker
	-pkill -f "$(PY) telegram_bot.py"
	-pkill -f "$(PY) scheduler_loop.py"
	@echo "Proses lokal dihentikan."

stop-legacy: stop-local ## Matikan proses lokal DAN hapus cron lama (sebelum pindah ke Docker)
	-crontab -r
	@echo "Cron dihapus. Sekarang aman jalanin: make up"

clean: ## Hapus cache Python dan file sementara
	rm -rf __pycache__ bot.out
	@echo "Bersih. State & log di data/ tidak disentuh."
