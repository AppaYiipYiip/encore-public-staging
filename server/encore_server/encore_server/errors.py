"""One error shape everywhere (docs/17 sections 1 and 2): `{"error": {"code", "message", "retryable", "retryAfterMs", "details"}}`.

`message` is a plain sentence a client may show as it is; `code` is for logic. The list of codes is closed: a new one needs a doc change.
"""

from __future__ import annotations

from typing import Any

#: code -> (HTTP status, the sentence, whether trying again can help)
CODES: dict[str, tuple[int, str, bool]] = {
    "unauthorized": (401, "Sign in again.", False),
    "forbidden": (403, "You are not allowed to do that.", False),
    "not_found": (404, "That does not exist (any more).", False),
    "conflict": (409, "That changed on another device. Here is how it is now.", False),
    "validation": (400, "That request was not understood.", False),
    "rate_limited": (429, "That is a lot at once. Try again in a moment.", True),
    "song_unavailable": (404, "This song is not available.", False),
    "source_busy": (503, "YouTube is not letting this server fetch songs right now. Try again in a little while.", True),
    "source_unreachable": (502, "This server cannot reach YouTube right now.", True),
    "storage_full": (507, "The server is out of disk space.", False),
    "server_busy": (503, "The server is busy. Try again in a moment.", True),
    "upstream_timeout": (504, "The song could not be started in time. Try again.", True),
    "federation_disabled": (403, "This server does not connect to other servers.", False),
    "peer_unreachable": (502, "The other server did not answer.", True),
    "internal": (500, "Something went wrong on the server.", True),
}


class ApiError(Exception):
    """Raised anywhere in the server; one handler turns it into the shape above."""

    def __init__(
        self,
        code: str,
        message: str | None = None,
        *,
        status: int | None = None,
        retry_after_ms: int | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        if code not in CODES:
            raise ValueError(f"unknown error code {code!r}")
        default_status, default_message, retryable = CODES[code]
        super().__init__(message or default_message)
        self.code = code
        self.status = status or default_status
        self.message = message or default_message
        self.retryable = retryable
        self.retry_after_ms = retry_after_ms
        self.details = details or {}

    def body(self) -> dict[str, Any]:
        return {
            "error": {
                "code": self.code,
                "message": self.message,
                "retryable": self.retryable,
                "retryAfterMs": self.retry_after_ms,
                "details": self.details,
            }
        }
