FROM python:3.12-slim

# Tanpa dependency eksternal — semua pakai stdlib, jadi gak ada pip install.
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    DATA_DIR=/data

WORKDIR /app

COPY jira_client.py jira_daily_done.py telegram_bot.py scheduler_loop.py ./

# State & log ditulis ke volume, bukan ke layer image
RUN mkdir -p /data && useradd -m -u 1000 app && chown -R app:app /app /data
USER app

VOLUME ["/data"]

# Dioverride per service di docker-compose.yml
CMD ["python3", "telegram_bot.py"]
