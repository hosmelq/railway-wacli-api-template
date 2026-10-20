# Railway wacli API template

Self-host [wacli](https://wacli.sh) with FastAPI, token authentication, and persistent WhatsApp sessions.

[![Deploy on Railway](https://railway.com/button.svg)](https://railway.com/deploy/wacli-api-self-hosted)

## Setup

Run `wacli-pair` in the service's Railway Console and scan the QR code from WhatsApp's **Linked devices**. Keep one replica with a persistent volume at `/data`.

Open `/docs` on your service's public domain for the API documentation. Use `API_TOKEN` from Railway to authorize requests.

## Variables

| Variable    | Default   | Purpose                   |
| ----------- | --------- | ------------------------- |
| `API_TOKEN` | Generated | Bearer token for the API. |
| `PORT`      | `8080`    | HTTP port.                |
| `TZ`        | `UTC`     | Time zone.                |
