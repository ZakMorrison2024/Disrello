# syntax=docker/dockerfile:1
FROM python:3.11-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

COPY disrello /app/disrello
COPY README.md /app/README.md

ENV PYTHONUNBUFFERED=1

CMD ["python", "-m", "disrello.main"]
