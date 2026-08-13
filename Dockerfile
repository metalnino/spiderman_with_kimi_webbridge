# 群晖直连 docker.io 常 401；用 DaoCloud 代理 library 官方镜像
FROM docker.m.daocloud.io/library/python:3.10-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    LEDGER_HOST=0.0.0.0 \
    LEDGER_PORT=8765 \
    CRAWL_INTERVAL_HOURS=2

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN mkdir -p data/web data/sessions \
    && chmod +x scripts/docker_entrypoint.sh

EXPOSE 8765

ENTRYPOINT ["/bin/sh", "scripts/docker_entrypoint.sh"]
