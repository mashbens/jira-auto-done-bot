.DEFAULT_GOAL := help
COMPOSE := docker compose
PY := python3

.PHONY: help build up down restart logs ps shell \
        dry-run next done status bot-local stop-local clean env-check

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

stop-local: ## Matikan bot yang jalan di luar Docker
	@# Kurung siku bikin pola tidak cocok dengan command line make/shell ini sendiri,
	@# kalau tidak pkill bakal bunuh diri sebelum target berikutnya jalan.
	-@pkill -f "[t]elegram_bot.py" || true
	@echo "Bot lokal dihentikan."

clean: ## Hapus cache Python dan file sementara
	rm -rf __pycache__ bot.out
	@echo "Bersih. State & log di data/ tidak disentuh."
