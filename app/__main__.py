from __future__ import annotations

import asyncio
import json

import click
import uvicorn

from app.bot_runner import run_bot
from app.settings import settings
from app.web import app


@click.group()
def cli() -> None:
    """CLI entrypoint."""


@cli.command()
@click.option("--host", default=settings.API_HOST, help="Host to run the server on")
@click.option("--port", default=settings.API_PORT, type=int, help="Port to run the server on")
def server(host: str, port: int) -> None:
    uvicorn.run(
        app,
        host=host,
        port=port,
        access_log=False,
        proxy_headers=True,
        forwarded_allow_ips="*",
        log_config={
            "version": 1,
            "disable_existing_loggers": False,
            "formatters": {},
            "handlers": {},
            "loggers": {
                "uvicorn": {"handlers": [], "propagate": True},
                "uvicorn.access": {"handlers": [], "propagate": True},
                "uvicorn.error": {"handlers": [], "propagate": True},
            },
        },
    )


@cli.command()
def bot() -> None:
    asyncio.run(run_bot(settings))


@cli.command()
def openapi() -> None:
    print(json.dumps(app.openapi()))


if __name__ == "__main__":
    cli()
