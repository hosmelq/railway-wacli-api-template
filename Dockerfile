ARG WACLI_IMAGE=ghcr.io/hosmelq/railway-wacli-template:latest@sha256:3397d18cb7991da17093243f6aa4f1841d6065bb27d9a42d93408ca7682a8112
FROM ${WACLI_IMAGE}

LABEL org.opencontainers.image.description="wacli with a FastAPI HTTP API and persistent WhatsApp sessions for Railway" \
      org.opencontainers.image.source="https://github.com/hosmelq/railway-wacli-api-template"

RUN apt-get update \
    && apt-get install -y --no-install-recommends python3 python3-venv \
    && apt-get clean \
    && python3 -m venv /opt/venv

COPY requirements.txt /opt/railway/requirements.txt
RUN /opt/venv/bin/pip install --no-cache-dir -r /opt/railway/requirements.txt

ENV PORT=8080 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPATH=/opt/railway \
    PYTHONUNBUFFERED=1

COPY api.py /opt/railway/api.py
COPY --chmod=755 start.sh sync.sh /opt/railway/

EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
  CMD /opt/venv/bin/python -c "import os,urllib.request;urllib.request.urlopen('http://127.0.0.1:'+os.environ['PORT']+'/healthz',timeout=3)"
