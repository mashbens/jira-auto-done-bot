FROM python:3.12-slim

# Semua stdlib, kecuali gspread buat antrian Google Sheet (sheet_tasks.py).
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    DATA_DIR=/data

WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY jira_client.py jira_daily_done.py telegram_bot.py sheet_tasks.py import_subtasks.py ./

# credentials.json (service account Google) TIDAK masuk image,
# di-mount read-only lewat docker-compose.yml.

# State & log ditulis ke volume, bukan ke layer image
RUN mkdir -p /data && useradd -m -u 1000 app && chown -R app:app /app /data
USER app

VOLUME ["/data"]

# Dioverride per service di docker-compose.yml
CMD ["python3", "telegram_bot.py"]
