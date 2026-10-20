# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Overview

A small Python tool that moves Jira sub-tasks to DONE, driven either by a Telegram bot (the main deployed service) or a CLI script. **Stdlib only** — no `requirements.txt`, no pip install; HTTP goes through `urllib`. Keep it that way unless there's a strong reason.

Code comments, log lines, and all user-facing text (Telegram messages, Makefile help) are in casual Indonesian. Match that style when editing.

## Commands

Run `make` (or `make help`) to list targets.

- `make up` / `make down` / `make logs` / `make restart` — run the bot via Docker Compose (service `bot`, container `jira-bot`)
- `make bot-local` / `make stop-local` — run the Telegram bot on the host without Docker
- `make env-check` — verify `.env` loads and Jira credentials work (calls `/myself`)
- `make dry-run` — show the next candidate sub-task without changing anything
- `make done ISSUE=KEY` — complete one specific issue
- `make import CSV=file.csv [DRY=1] [DUE=YYYY-MM-DD]` — bulk-create sub-tasks from a CSV (`Issue Type,Summary,Parent,Description`) via [import_subtasks.py](import_subtasks.py); assigns to the API user, due date defaults to end of month, skips summaries that already exist under the same parent
- `make status` — count open sub-tasks by status

There is no test suite or linter configured. Note that `make done` / the CLI hit the real Jira instance.

## Architecture

- [jira_client.py](jira_client.py) — shared core used by both entry points: `.env` loading (`load_env`, uses `setdefault` so real env vars win), `get_config`, the `api()` wrapper for Jira REST v3 (Basic auth with email + API token), `list_open_subtasks` (POST `/search/jql` using `JIRA_JQL`), and `complete_issue`.
- [telegram_bot.py](telegram_bot.py) — long-polling bot (`getUpdates`, no webhook). Commands `/l`, `/next`, `/done KEY`, `/status`, `/help`. Inline-keyboard callbacks use `callback_data` strings (Telegram caps these at 64 bytes): `page:<n>` (page from cache), `ref:<n>` (re-fetch from Jira), `tog:<KEY>:<page>` / `all:<page>` / `clr:<page>` (checkbox selection), `bulk:<page>` (bulk confirm), `bdo:<page>` (run bulk done, capped at `MAX_BULK`), `ask:<KEY>:<page>` / `do:<KEY>:<page>` (single-issue confirm/complete, used by `/next` and `/done`). The fetched list and the selection live in the module-level `cache` / `selected` dicts keyed by chat_id, so they are lost on restart. Bulk done runs synchronously, so the bot doesn't respond to other updates until it finishes. Every update is gated by `TELEGRAM_ALLOWED_CHAT_ID` (comma-separated whitelist; empty = reject everything). Per-update exceptions are caught so one bad update can't kill the loop.
- [jira_daily_done.py](jira_daily_done.py) — CLI originally meant for a daily cron: completes the oldest open sub-task, at most once per day, tracked via `.last_run_state.json`. `--dry-run` and `--issue KEY` bypass the once-per-day limit. The scheduler/cron container was removed, so this is now only invoked manually (via Makefile).

### Completion flow (`complete_issue`)

1. If `JIRA_DUE_DATE` is set (default `today`) and the issue has no due date, PUT it first — the ATIDIS26 workflow has a "Due date is required" validator that otherwise rejects transitions with HTTP 400.
2. Walk `JIRA_STATUS_PATH` (comma-separated, e.g. `in progress, DONE`) hop by hop, since the workflow can't jump straight to DONE. Statuses already reached are skipped; transitions are matched by target status name (case-insensitive).
3. Optionally post `JIRA_COMMENT` as an ADF comment.

`JiraError` is the "user-displayable" exception type — `api()` converts HTTP/URL errors into it, and both entry points catch it and show/log its message.

### Data & config

- Config lives in `.env` (see [.env.example](.env.example)); required: `JIRA_BASE_URL`, `JIRA_EMAIL`, `JIRA_API_TOKEN`, `JIRA_JQL`, plus `TELEGRAM_BOT_TOKEN` and `TELEGRAM_ALLOWED_CHAT_ID` for the bot.
- `DATA_DIR` (defaults to the repo dir; `/data` in Docker, bind-mounted from `./data`) holds `jira_daily_done.log` and `.last_run_state.json`. Log-file write failures are swallowed on purpose (container runs as UID 1000, bind mount may be root-owned) — stdout is still captured by `docker logs`.
- When adding a new Python module, also add it to the `COPY` line in the [Dockerfile](Dockerfile), which lists files explicitly.
