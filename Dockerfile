FROM python:3.12-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DB_PATH=/app/data/subs.sqlite

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt \
    && mkdir -p /app/data \
    && useradd --create-home --uid 1000 bot \
    && chown -R bot:bot /app

COPY bot.py xui.py db.py payments.py webapp.py pay_return.py admin_panel.py ./

USER bot

CMD ["python", "bot.py"]
