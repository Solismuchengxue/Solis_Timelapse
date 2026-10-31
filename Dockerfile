FROM python:3.12-slim

LABEL org.opencontainers.image.source="https://github.com/Solismuchengxue/Solis_Timelapse"

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    SOLIS_CONTAINER=1 \
    IMAGEIO_FFMPEG_EXE=/usr/bin/ffmpeg

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends libgomp1 ffmpeg \
    && ffmpeg -hide_banner -encoders 2>/dev/null | grep -q h264_nvenc \
    && ffmpeg -hide_banner -encoders 2>/dev/null | grep -q hevc_nvenc \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY config/config.yaml config/config.yaml
COPY assets/watchcow-icon-512.png assets/watchcow-icon-512.png
COPY src src
COPY webui webui
COPY docker docker

EXPOSE 9501

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:9501/api/health', timeout=3).read()"]

ENTRYPOINT ["python", "docker/entrypoint.py"]
