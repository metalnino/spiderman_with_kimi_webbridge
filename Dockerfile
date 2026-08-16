# 群晖直连 docker.io 常 401；用 DaoCloud 代理 library 官方镜像
FROM docker.m.daocloud.io/library/python:3.10-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    TZ=Asia/Shanghai \
    LEDGER_HOST=0.0.0.0 \
    LEDGER_PORT=8765 \
    CRAWL_CRON_HOURS=8,12,18,22

COPY requirements.txt .
# 群晖直连 PyPI 易超时；用清华镜像 + 超时重试
RUN pip install --no-cache-dir -r requirements.txt \
    -i https://pypi.tuna.tsinghua.edu.cn/simple --default-timeout=120 --retries 5

COPY . .

RUN mkdir -p data/web data/sessions \
    && chmod +x scripts/docker_entrypoint.sh

EXPOSE 8765

ENTRYPOINT ["/bin/sh", "scripts/docker_entrypoint.sh"]
