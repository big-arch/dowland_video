FROM node:22-bookworm-slim AS node

FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Node нужен yt-dlp для YouTube (JS-челленджи)
COPY --from=node /usr/local/bin/node /usr/local/bin/node

WORKDIR /app

COPY requirements.txt ./
RUN pip install -r requirements.txt

COPY mediagrab ./mediagrab

RUN mkdir -p /app/downloads /app/data /app/cookies

VOLUME ["/app/data", "/app/cookies"]
EXPOSE 8080

CMD ["python", "-m", "mediagrab"]
