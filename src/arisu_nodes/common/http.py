"""Shared HTTP boundaries: same-origin bounded JSON bodies, worker admission and sanitized error responses."""

from __future__ import annotations

import asyncio
import json
import logging
import threading
from typing import Any, Awaitable, Callable, Dict
from urllib.parse import urlsplit

from aiohttp import web

from .media import StaleResource, UnsupportedMedia

HEADERS = {"X-Content-Type-Options": "nosniff"}
MAX_BODY = 1024 * 1024
_POLL_INTERVAL = 0.05

Handler = Callable[[web.Request], Awaitable[web.StreamResponse]]


class Busy(ValueError):
    """A bounded worker cannot accept more work now."""


async def body(request: web.Request) -> Dict[str, Any]:
    """Require same-origin JSON and count streamed request bytes."""
    origin = request.headers.get("Origin")
    if origin and urlsplit(origin).netloc != request.host:
        raise web.HTTPForbidden(text="Cross-origin requests are refused")
    if request.headers.get("Sec-Fetch-Site") not in (None, "same-origin", "none"):
        raise web.HTTPForbidden(text="Cross-origin requests are refused")
    if request.content_type != "application/json":
        raise web.HTTPUnsupportedMediaType(text="JSON required")
    content = bytearray()
    async for chunk in request.content.iter_chunked(65536):
        content.extend(chunk)
        if len(content) > MAX_BODY:
            raise web.HTTPRequestEntityTooLarge(max_size=MAX_BODY, actual_size=len(content))
    value = json.loads(content)
    if not isinstance(value, dict):
        raise TypeError("expected a JSON object")
    return value


class Admission:
    """Admit blocking work to a few threads and keep each slot until its work really ends."""

    def __init__(self, slots: int, waiters: int = 32, deadline: float = 30.0):
        self._guard = threading.BoundedSemaphore(slots)
        self._waiters, self._deadline, self._waiting = waiters, deadline, 0

    async def _admit(self):
        if self._guard.acquire(blocking=False):
            return
        if self._waiting >= self._waiters:
            raise Busy("workers are busy")
        loop = asyncio.get_running_loop()
        deadline = loop.time() + self._deadline
        self._waiting += 1
        try:
            while not self._guard.acquire(blocking=False):
                if loop.time() >= deadline:
                    raise Busy("workers are busy")
                await asyncio.sleep(_POLL_INTERVAL)
        finally:
            self._waiting -= 1

    async def run(self, function: Callable[..., Any], *args: Any) -> Any:
        """Run ``function`` in a thread; a cancelled request does not release the slot early."""
        await self._admit()

        def work() -> Any:
            try:
                return function(*args)
            finally:
                self._guard.release()

        task = asyncio.create_task(asyncio.to_thread(work))

        def observed(done: asyncio.Task[Any]):
            if not done.cancelled():
                done.exception()

        task.add_done_callback(observed)
        return await asyncio.shield(task)


def guarded(handler: Handler, logger: logging.Logger, subject: str) -> Handler:
    """Map failures to generic JSON errors; physical paths and decoder details stay in the server log."""

    async def guard(request: web.Request) -> web.StreamResponse:
        try:
            return await handler(request)
        except web.HTTPException:
            raise
        except (KeyError, FileNotFoundError, NotADirectoryError):
            status, error = 404, f"{subject} not found"
        except StaleResource:
            status, error = 409, "source changed; rerun or reselect it"
        except UnsupportedMedia:
            status, error = 415, "unsupported, external, or incomplete media"
        except Busy:
            status, error = 429, f"{subject} work is busy; retry shortly"
        except PermissionError:
            status, error = 403, f"{subject} cannot be read"
        except (ValueError, TypeError, UnicodeError):
            logger.warning("invalid %s request", subject, exc_info=True)
            status, error = 400, f"invalid {subject} request"
        except Exception:
            logger.exception("%s request failed", subject)
            status, error = 500, f"{subject} request failed; see the server log"
        return web.json_response({"error": error}, status=status, headers=HEADERS)

    return guard
