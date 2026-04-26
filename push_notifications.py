from __future__ import annotations

import base64
import json
import os
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import requests
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature

_ROOT_DIR = Path(__file__).resolve().parent
_VAPID_KEYS_PATH = Path(
    os.getenv("PUSH_VAPID_KEYS_PATH", str(_ROOT_DIR / "push_vapid_keys.json"))
)
_VAPID_SUBJECT = os.getenv("PUSH_VAPID_SUBJECT", "mailto:push@rftuning.id")
_VAPID_TTL_SECONDS = int(os.getenv("PUSH_VAPID_TTL_SECONDS", "3600"))


def _b64url_encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _b64url_decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(value + padding)


def _load_or_create_private_key() -> ec.EllipticCurvePrivateKey:
    if _VAPID_KEYS_PATH.exists():
        stored = json.loads(_VAPID_KEYS_PATH.read_text(encoding="utf-8"))
        private_key_pem = stored.get("private_key_pem")
        if private_key_pem:
            return serialization.load_pem_private_key(
                private_key_pem.encode("utf-8"), password=None
            )

    private_key = ec.generate_private_key(ec.SECP256R1())
    private_key_pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode("utf-8")

    _VAPID_KEYS_PATH.write_text(
        json.dumps({"private_key_pem": private_key_pem}, indent=2), encoding="utf-8"
    )
    return private_key


def get_vapid_public_key() -> str:
    private_key = _load_or_create_private_key()
    public_key = private_key.public_key()
    public_key_bytes = public_key.public_bytes(
        encoding=serialization.Encoding.X962,
        format=serialization.PublicFormat.UncompressedPoint,
    )
    return _b64url_encode(public_key_bytes)


def _make_vapid_jwt(push_endpoint: str) -> str:
    private_key = _load_or_create_private_key()
    public_key_b64 = get_vapid_public_key()
    audience = f"{urlparse(push_endpoint).scheme}://{urlparse(push_endpoint).netloc}"
    now = int(time.time())
    header = {"typ": "JWT", "alg": "ES256"}
    payload = {"aud": audience, "exp": now + _VAPID_TTL_SECONDS, "sub": _VAPID_SUBJECT}

    signing_input = "{}.{}".format(
        _b64url_encode(json.dumps(header, separators=(",", ":")).encode("utf-8")),
        _b64url_encode(json.dumps(payload, separators=(",", ":")).encode("utf-8")),
    ).encode("ascii")

    der_signature = private_key.sign(signing_input, ec.ECDSA(hashes.SHA256()))
    r, s = decode_dss_signature(der_signature)
    raw_signature = r.to_bytes(32, "big") + s.to_bytes(32, "big")
    jwt = "{}.{}".format(signing_input.decode("ascii"), _b64url_encode(raw_signature))

    return f"vapid t={jwt}, k={public_key_b64}"


def build_webpush_headers(push_endpoint: str, *, ttl_seconds: int | None = None) -> dict[str, str]:
    headers = {
        "Authorization": _make_vapid_jwt(push_endpoint),
        "TTL": str(ttl_seconds or _VAPID_TTL_SECONDS),
        "Urgency": "high",
    }
    return headers


def send_web_push(subscription: dict[str, Any], *, ttl_seconds: int | None = None) -> requests.Response:
    endpoint = subscription.get("endpoint")
    if not endpoint:
        raise ValueError("Push subscription is missing an endpoint")

    headers = build_webpush_headers(endpoint, ttl_seconds=ttl_seconds)
    return requests.post(endpoint, data=b"", headers=headers, timeout=10)
