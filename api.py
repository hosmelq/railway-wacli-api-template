"""Authenticated text messaging over the local wacli session."""

import asyncio
import json
import os
import secrets
import signal
from contextlib import asynccontextmanager, suppress
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, ConfigDict, Field, field_validator


async def stop_process(process):
    if process.returncode is None:
        with suppress(ProcessLookupError):
            process.terminate()
        try:
            await asyncio.wait_for(process.communicate(), timeout=5)
        except asyncio.TimeoutError:
            with suppress(ProcessLookupError):
                process.kill()
            await process.communicate()


async def run_wacli(*arguments, sending=False, timeout=100):
    process = await asyncio.create_subprocess_exec(
        "/usr/local/bin/wacli",
        "--json",
        "--timeout",
        "90s",
        *arguments,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, _ = await asyncio.wait_for(process.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        await stop_process(process)
        detail = "WhatsApp request timed out."
        if sending:
            detail += " Delivery is unknown; check WhatsApp before retrying."
        raise HTTPException(status_code=504, detail=detail) from None
    except asyncio.CancelledError:
        await stop_process(process)
        raise
    try:
        result = json.loads(stdout)
        if (
            not isinstance(result, dict)
            or process.returncode != 0
            or result.get("success") is not True
        ):
            raise ValueError
        data = result["data"]
        if not isinstance(data, dict):
            raise ValueError
        return data
    except (KeyError, TypeError, ValueError):
        raise HTTPException(
            status_code=502,
            detail="WhatsApp could not complete the request. Check the session before retrying.",
        ) from None


async def monitor_sync(process):
    await process.wait()
    # Stop the API too: Railway restarts both processes as one service.
    os.kill(os.getpid(), signal.SIGTERM)


@asynccontextmanager
async def lifespan(app):
    token = os.environ.get("API_TOKEN", "")
    if len(token) < 32 or token != token.strip():
        raise RuntimeError(
            "API_TOKEN must contain at least 32 characters without surrounding whitespace."
        )
    app.state.api_token = token.encode()
    await run_wacli("auth", "status")
    app.state.sync = await asyncio.create_subprocess_exec(
        "/bin/sh", "/opt/railway/sync.sh"
    )
    monitor = asyncio.create_task(monitor_sync(app.state.sync))
    try:
        yield
    finally:
        monitor.cancel()
        with suppress(asyncio.CancelledError):
            await monitor
        await stop_process(app.state.sync)


app = FastAPI(
    description="Send WhatsApp text messages through your linked wacli session.",
    lifespan=lifespan,
    redoc_url=None,
    title="wacli API",
    version="1.0.0",
)
bearer = HTTPBearer(auto_error=False)


async def authenticate(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
):
    if credentials is None or not secrets.compare_digest(
        credentials.credentials.encode(),
        request.app.state.api_token,
    ):
        raise HTTPException(
            status_code=401,
            detail="Invalid or missing API token.",
            headers={"WWW-Authenticate": "Bearer"},
        )


class Message(BaseModel):
    model_config = ConfigDict(extra="forbid")

    message: str = Field(min_length=1, max_length=65536)
    to: str = Field(pattern=r"^\+[1-9][0-9]{6,14}$")

    @field_validator("message")
    @classmethod
    def nonblank_message(cls, value):
        if not value.strip():
            raise ValueError("Message must not be blank.")
        return value


class SentMessage(BaseModel):
    id: str
    sent: bool
    store_warning: str | None = None
    to: str


@app.get("/healthz", include_in_schema=False)
async def health(request: Request):
    if request.app.state.sync.returncode is not None:
        raise HTTPException(status_code=503, detail="Sync worker stopped.")
    return {"status": "ok"}


@app.get("/session", dependencies=[Depends(authenticate)])
async def session():
    return await run_wacli("--read-only", "auth", "status")


@app.post(
    "/messages",
    dependencies=[Depends(authenticate)],
    response_model=SentMessage,
    response_model_exclude_none=True,
    status_code=202,
)
async def send_message(message: Message):
    status = await run_wacli("--read-only", "auth", "status")
    if status.get("authenticated") is not True:
        raise HTTPException(
            status_code=409,
            detail="Link your phone with wacli-pair before sending messages.",
        )
    result = await run_wacli(
        "send",
        "text",
        f"--to={message.to}",
        f"--message={message.message}",
        sending=True,
    )
    if result.get("sent") is not True:
        raise HTTPException(
            status_code=502, detail="WhatsApp did not accept the message."
        )
    return result
