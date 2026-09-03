"""Small synchronous transport; handlers call it through asyncio.to_thread.

No automatic HTTP retries: payments retry through the durable outbox, and AI
requests must never be silently submitted with a new idempotency key.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener


class BridgeError(RuntimeError):
    def __init__(self, status: int = 503) -> None:
        self.status = status
        super().__init__(f"Core request failed ({status})")


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class StudentOSBridgeClient:
    def __init__(self, base_url: str, secret: str, *, timeout: float = 45) -> None:
        url = urlsplit(base_url)
        if (url.scheme not in {"http", "https"} or not url.hostname
                or url.username or url.password or url.query or url.fragment
                or url.path not in {"", "/"} or not secret
                or (url.scheme == "http" and url.hostname not in {"localhost", "127.0.0.1", "::1"})):
            raise ValueError("Core requires an HTTPS origin (HTTP only on loopback) and a secret")
        self.base_url = base_url.rstrip("/")
        self._secret = secret
        self.timeout = timeout
        self._opener = build_opener(_NoRedirect())

    def post(self, operation: str, payload: dict) -> dict:
        body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode()
        if len(body) > 64 * 1024:
            raise BridgeError(413)
        timestamp, nonce = str(int(time.time())), secrets.token_urlsafe(24)
        signature = hmac.new(self._secret.encode(), timestamp.encode() + b"."
                             + nonce.encode() + b"." + body, hashlib.sha256).hexdigest()
        request = Request(self.base_url + "/api/internal/v1/" + operation, data=body,
                          headers={"Content-Type": "application/json",
                                   "X-Bridge-Timestamp": timestamp,
                                   "X-Bridge-Nonce": nonce,
                                   "X-Bridge-Signature": signature}, method="POST")
        try:
            with self._opener.open(request, timeout=self.timeout) as response:
                raw = response.read(256 * 1024 + 1)
            if len(raw) > 256 * 1024:
                raise BridgeError(502)
            result = json.loads(raw)
            if not isinstance(result, dict):
                raise BridgeError(502)
            return result
        except HTTPError as exc:
            # Never retain response bodies, URLs or credentials in errors/logs.
            raise BridgeError(exc.code) from None
        except (URLError, OSError, ValueError):
            raise BridgeError(503) from None

    def resolve_user(self, telegram: dict) -> dict:
        return self.post("identity/resolve", {"telegram": telegram})

    def get_entitlement(self, telegram: dict) -> dict:
        return self.post("entitlement", {"telegram": telegram})

    def get_products(self) -> dict:
        return self.post("products", {})

    def submit_text_task(self, telegram: dict, assignment: str, request_id: str) -> dict:
        return self.post("study/text", {"telegram": telegram, "assignment": assignment,
                                        "request_id": request_id})

    def record_payment(self, payload: dict) -> dict:
        return self.post("payments/telegram-stars", payload)
