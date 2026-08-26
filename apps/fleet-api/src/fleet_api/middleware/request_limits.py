"""
ASGI Request Limits Middleware for FortifiedReg Fleet (v0.4.0).
Provides byte-accurate streaming request body limits.
Checks Content-Length header for rapid rejection and incrementally meters ASGI receive() chunks,
raising clean HTTP 413 Payload Too Large responses without buffering excessive payloads into memory.
"""
import json
from typing import Callable
from starlette.types import ASGIApp, Message, Receive, Scope, Send

DEFAULT_MAX_BODY_BYTES = 12 * 1024 * 1024  # 12 MiB hard limit


class PayloadTooLargeError(Exception):
    """Raised when an incoming HTTP request body exceeds configured byte ceiling."""
    def __init__(self, max_bytes: int, received_bytes: int):
        self.max_bytes = max_bytes
        self.received_bytes = received_bytes
        super().__init__(f"Payload size {received_bytes} bytes exceeds maximum allowed limit of {max_bytes} bytes.")


class ContentLengthLimitMiddleware:
    """
    ASGI middleware enforcing strict byte ceilings on HTTP request bodies.
    Guards both known Content-Length headers and chunked/streaming payloads.
    """
    def __init__(self, app: ASGIApp, max_body_bytes: int = DEFAULT_MAX_BODY_BYTES):
        self.app = app
        self.max_body_bytes = max_body_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        headers = dict(scope.get("headers", []))
        content_length_header = headers.get(b"content-length")

        if content_length_header:
            try:
                content_length = int(content_length_header.decode("latin-1"))
                if content_length > self.max_body_bytes:
                    await self._send_413_response(send, self.max_body_bytes, content_length)
                    return
            except (ValueError, UnicodeDecodeError):
                pass

        total_received = 0
        response_started = False

        async def send_wrapper(message: Message) -> None:
            nonlocal response_started
            if message["type"] == "http.response.start":
                response_started = True
            await send(message)

        async def receive_wrapper() -> Message:
            nonlocal total_received
            message = await receive()
            if message["type"] == "http.request":
                body_chunk = message.get("body", b"")
                total_received += len(body_chunk)
                if total_received > self.max_body_bytes:
                    raise PayloadTooLargeError(self.max_body_bytes, total_received)
            return message

        try:
            await self.app(scope, receive_wrapper, send_wrapper)
        except PayloadTooLargeError as exc:
            if not response_started:
                await self._send_413_response(send, exc.max_bytes, exc.received_bytes)
            else:
                raise

    async def _send_413_response(self, send: Send, max_bytes: int, received_bytes: int) -> None:
        body = json.dumps({
            "detail": f"Payload Too Large: Request body size ({received_bytes} bytes) exceeds the hard limit of {max_bytes} bytes ({max_bytes // (1024 * 1024)} MiB)."
        }).encode("utf-8")

        await send({
            "type": "http.response.start",
            "status": 413,
            "headers": [
                (b"content-type", b"application/json"),
                (b"content-length", str(len(body)).encode("latin-1")),
                (b"connection", b"close"),
            ],
        })
        await send({
            "type": "http.response.body",
            "body": body,
            "more_body": False,
        })
