FROM python:3.13-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 HOME=/tmp
WORKDIR /app
COPY requirements.lock ./
RUN pip install --no-cache-dir -r requirements.lock && useradd --uid 10001 --create-home clay
COPY argiloclay_intelligence ./argiloclay_intelligence
COPY data ./data
USER clay
CMD ["gunicorn", "--bind", "0.0.0.0:7861", "--workers", "1", "--threads", "2", "--timeout", "15", "argiloclay_intelligence.api:app"]
