"""Bound actual request bytes before multipart parsing, even without Content-Length."""

from fastapi.responses import JSONResponse

from quartermaster.ingestion import MAX_UPLOAD

MAX_REQUEST = MAX_UPLOAD + 64 * 1024


class BodyLimitMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope["method"] not in {"POST", "PUT", "PATCH"}:
            return await self.app(scope, receive, send)
        parts = []
        size = 0
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            body = message.get("body", b"")
            size += len(body)
            if size > MAX_REQUEST:
                response = JSONResponse(
                    {"detail": "UPLOAD_SIZE: Upload one file at a time, no larger than 8 MiB."},
                    status_code=413,
                )
                return await response(scope, receive, send)
            parts.append(body)
            if not message.get("more_body", False):
                break
        # A bounded buffer avoids partially created multipart temporary files on
        # overflow. The parser gets at most MAX_REQUEST bytes, regardless of headers.
        buffered = b"".join(parts)
        delivered = False

        async def bounded_receive():
            nonlocal delivered
            if not delivered:
                delivered = True
                return {"type": "http.request", "body": buffered, "more_body": False}
            return await receive()

        await self.app(scope, bounded_receive, send)
