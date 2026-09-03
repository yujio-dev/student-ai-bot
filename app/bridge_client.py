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
import base64
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

    def post(self, operation: str, payload: dict, *, timeout: float | None = None) -> dict:
        body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode()
        limit = 9 * 1024 * 1024 if operation in {"study/photo/quote", "study/photo/confirm"} else 64 * 1024
        if len(body) > limit:
            raise BridgeError(413)
        timestamp, nonce = str(int(time.time())), secrets.token_urlsafe(24)
        path = "/api/internal/v1/" + operation
        signature = hmac.new(self._secret.encode(), b"v2.POST." + path.encode() + b"." + timestamp.encode() + b"."
                             + nonce.encode() + b"." + body, hashlib.sha256).hexdigest()
        request = Request(self.base_url + path, data=body,
                          headers={"Content-Type": "application/json",
                                   "X-Bridge-Timestamp": timestamp,
                                   "X-Bridge-Nonce": nonce,
                                   "X-Bridge-Signature": signature}, method="POST")
        try:
            with self._opener.open(request, timeout=timeout or self.timeout) as response:
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
        return self.post("products", {}, timeout=5)

    def health(self) -> dict:
        return self.post("health", {}, timeout=5)

    def submit_text_task(self, telegram: dict, assignment: str, request_id: str) -> dict:
        return self.post("study/text", {"telegram": telegram, "assignment": assignment,
                                        "request_id": request_id})

    def record_payment(self, payload: dict) -> dict:
        return self.post("payments/telegram-stars", payload, timeout=10)

    def feedback(self, telegram, rating, request_id):
        return self.post("feedback", {"telegram": telegram, "rating": rating, "request_id": request_id}, timeout=5)

    def quote_photo(self, telegram, data, mime):
        return self.post("study/photo/quote", {"telegram": telegram,
            "image_b64": base64.b64encode(data).decode(), "mime": mime})

    def latest_photo(self, telegram):
        return self.post("study/photo/session", {"telegram": telegram})

    def confirm_photo(self, telegram, data, mime, quote_id):
        return self.post("study/photo/confirm", {"telegram": telegram,
            "image_b64": base64.b64encode(data).decode(), "mime": mime, "quote_id": quote_id})

    def answer_photo(self, telegram, session_id, selection, request_id):
        return self.post("study/photo/answer", {"telegram": telegram,
            "session_id": session_id, "selection": selection, "request_id": request_id})
