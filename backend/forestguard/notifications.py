"""Optional Telegram delivery and a bounded background outbox worker."""

from __future__ import annotations

import json
import logging
import sqlite3
import threading
import time
from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from forestguard import notification_repository
from forestguard.config import Settings
from forestguard.database import connect

logger = logging.getLogger("forestguard.notifications")


class TelegramDeliveryError(RuntimeError):
    """Delivery failed; the description is sanitized and never contains credentials."""


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _utc_stale_cutoff() -> str:
    return (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat(
        timespec="milliseconds"
    ).replace("+00:00", "Z")


def notification_availability(settings: Settings) -> str:
    if not settings.telegram_enabled:
        return "disabled"
    if not settings.telegram_bot_token or not settings.telegram_chat_id:
        return "unavailable: Telegram credentials are incomplete"
    return "available"


def send_telegram_message(
    *,
    token: str,
    chat_id: str,
    message: str,
    timeout: float,
    retries: int,
    opener: Callable[..., Any] | None = None,
    sleep: Callable[[float], None] = time.sleep,
) -> None:
    """Deliver with short timeouts and a finite retry budget; never expose the token."""
    request_opener = opener or urlopen
    endpoint = f"https://api.telegram.org/bot{token}/sendMessage"
    request = Request(
        endpoint,
        data=json.dumps(
            {"chat_id": chat_id, "text": message, "parse_mode": "HTML", "disable_web_page_preview": True}
        ).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    for attempt in range(retries + 1):
        try:
            with request_opener(request, timeout=timeout) as response:
                body = json.loads(response.read())
            if not body.get("ok"):
                raise TelegramDeliveryError("Telegram rejected the notification.")
            return
        except HTTPError as error:
            retryable = error.code == 429 or error.code >= 500
            safe_error = f"Telegram returned HTTP {error.code}."
            if not retryable or attempt == retries:
                raise TelegramDeliveryError(safe_error) from None
        except (TimeoutError, URLError, OSError, json.JSONDecodeError) as error:
            safe_error = f"Telegram delivery failed ({type(error).__name__})."
            if attempt == retries:
                raise TelegramDeliveryError(safe_error) from None
        except TelegramDeliveryError:
            raise
        sleep(min(0.25 * (2**attempt), 2.0))


def dispatch_one(
    database_path: Path,
    settings: Settings,
    *,
    sender: Callable[..., None] = send_telegram_message,
) -> bool:
    """Claim and deliver one queued notification outside all database transactions."""
    if not settings.telegram_available:
        return False
    with connect(database_path) as connection:
        event = notification_repository.claim_next(connection, _utc_now(), _utc_stale_cutoff())
    if event is None:
        return False
    try:
        sender(
            token=settings.telegram_bot_token,
            chat_id=settings.telegram_chat_id,
            message=event["message_text"],
            timeout=settings.telegram_timeout_seconds,
            retries=settings.telegram_retries,
        )
        sent, error = True, None
    except Exception as exception:  # noqa: BLE001 - delivery failures must not escape ingestion.
        sent = False
        error = (
            str(exception)
            if isinstance(exception, TelegramDeliveryError)
            else f"Telegram delivery failed ({type(exception).__name__})."
        )
    with connect(database_path) as connection:
        notification_repository.finish_attempt(
            connection,
            event["notification_id"],
            sent=sent,
            now=_utc_now(),
            error=error,
        )
    if sent:
        logger.info("Telegram notification sent for alert %s", event["alert_id"])
    else:
        logger.warning("Telegram notification failed for alert %s: %s", event["alert_id"], error)
    return True


class NotificationWorker:
    """One daemon worker per application process, polling durable queued events."""

    def __init__(self, database_path: Path, settings: Settings) -> None:
        self.database_path = database_path
        self.settings = settings
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if not self.settings.telegram_enabled:
            with connect(self.database_path) as connection:
                notification_repository.skip_pending(
                    connection, _utc_now(), "Telegram notifications are disabled."
                )
            logger.info("Telegram notifications disabled")
            return
        if not self.settings.telegram_available:
            with connect(self.database_path) as connection:
                notification_repository.skip_pending(
                    connection,
                    _utc_now(),
                    "Telegram is enabled but credentials are incomplete.",
                )
            logger.warning("Telegram notifications unavailable: credentials are incomplete")
            return
        self._thread = threading.Thread(target=self._run, name="forestguard-telegram", daemon=True)
        self._thread.start()

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                delivered_or_attempted = dispatch_one(self.database_path, self.settings)
            except (sqlite3.Error, OSError):
                logger.exception("Telegram outbox worker could not access its database")
                delivered_or_attempted = False
            if not delivered_or_attempted:
                self._stop.wait(0.5)

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2.0)
