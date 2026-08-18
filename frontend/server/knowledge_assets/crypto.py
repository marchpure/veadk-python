# Copyright (c) 2025 Beijing Volcano Engine Technology Co., Ltd. and/or its affiliates.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.

"""AES-GCM credential sealing for the Studio knowledge asset store."""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, TypedDict

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

_ALGORITHM = "AES-256-GCM"
_VERSION = "knowledge_asset.credential.v1"
_NONCE_BYTES = 12
_KEY_BYTES = 32


class CredentialEnvelope(TypedDict):
    version: Literal["knowledge_asset.credential.v1"]
    algorithm: Literal["AES-256-GCM"]
    key_id: str
    nonce: str
    ciphertext: str


class CredentialCryptoError(RuntimeError):
    """Raised when a credential envelope cannot be encrypted or decrypted safely."""


@dataclass(frozen=True)
class AssetStoreKey:
    material: bytes
    key_id: str


def default_key_path() -> Path:
    return Path.home() / ".veadk" / "studio" / "asset-store.key"


class CredentialCipher:
    def __init__(self, key: AssetStoreKey | None = None) -> None:
        self._key = key

    def encrypt(self, payload: dict[str, Any]) -> CredentialEnvelope:
        key = self._resolve_key()
        nonce = os.urandom(_NONCE_BYTES)
        plaintext = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode(
            "utf-8"
        )
        ciphertext = AESGCM(key.material).encrypt(nonce, plaintext, None)
        return {
            "version": _VERSION,
            "algorithm": _ALGORITHM,
            "key_id": key.key_id,
            "nonce": _b64(nonce),
            "ciphertext": _b64(ciphertext),
        }

    def decrypt(self, envelope: str | CredentialEnvelope) -> dict[str, Any]:
        parsed = _parse_envelope(envelope)
        if parsed["version"] != _VERSION:
            raise CredentialCryptoError("Unsupported credential envelope version.")
        if parsed["algorithm"] != _ALGORITHM:
            raise CredentialCryptoError("Unsupported credential envelope algorithm.")
        key = self._resolve_key()
        if parsed["key_id"] != key.key_id:
            raise CredentialCryptoError("Credential envelope key id does not match.")
        try:
            plaintext = AESGCM(key.material).decrypt(
                _unb64(parsed["nonce"], "nonce"),
                _unb64(parsed["ciphertext"], "ciphertext"),
                None,
            )
            payload = json.loads(plaintext.decode("utf-8"))
        except (InvalidTag, UnicodeDecodeError, json.JSONDecodeError) as error:
            raise CredentialCryptoError(
                "Credential envelope could not be decrypted."
            ) from error
        if not isinstance(payload, dict):
            raise CredentialCryptoError("Credential payload is invalid.")
        return payload

    def envelope_json(self, payload: dict[str, Any]) -> str:
        return json.dumps(self.encrypt(payload), sort_keys=True, separators=(",", ":"))

    def _resolve_key(self) -> AssetStoreKey:
        if self._key is None:
            self._key = resolve_asset_store_key()
        return self._key


def resolve_asset_store_key() -> AssetStoreKey:
    explicit = os.getenv("VEADK_STUDIO_ASSET_SECRET", "")
    if explicit:
        material = _secret_to_key(explicit)
        return AssetStoreKey(material=material, key_id=_key_id(material, "env"))
    path = default_key_path()
    material = _read_or_create_local_key(path)
    return AssetStoreKey(material=material, key_id=_key_id(material, "file"))


def _read_or_create_local_key(path: Path) -> bytes:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    try:
        path.parent.chmod(0o700)
    except OSError:
        pass
    if path.exists():
        material = _decode_key_file(path.read_text(encoding="utf-8"))
        try:
            path.chmod(0o600)
        except OSError:
            pass
        return material
    material = os.urandom(_KEY_BYTES)
    try:
        fd = os.open(str(path), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError:
        return _decode_key_file(path.read_text(encoding="utf-8"))
    with os.fdopen(fd, "w", encoding="utf-8") as file:
        file.write(_b64(material))
        file.write("\n")
    return material


def _decode_key_file(value: str) -> bytes:
    try:
        material = base64.b64decode(value.strip(), validate=True)
    except binascii.Error as error:
        raise CredentialCryptoError("Asset store key file is not valid base64.") from error
    if len(material) != _KEY_BYTES:
        raise CredentialCryptoError("Asset store key file must contain a 32-byte key.")
    return material


def _secret_to_key(value: str) -> bytes:
    raw = value.strip()
    if not raw:
        raise CredentialCryptoError("Asset store secret must not be empty.")
    try:
        decoded = base64.b64decode(raw, validate=True)
    except binascii.Error:
        decoded = b""
    if len(decoded) == _KEY_BYTES:
        return decoded
    return hashlib.sha256(raw.encode("utf-8")).digest()


def _parse_envelope(envelope: str | CredentialEnvelope) -> CredentialEnvelope:
    if isinstance(envelope, str):
        try:
            parsed = json.loads(envelope)
        except json.JSONDecodeError as error:
            raise CredentialCryptoError("Credential envelope is not valid JSON.") from error
    else:
        parsed = envelope
    if not isinstance(parsed, dict):
        raise CredentialCryptoError("Credential envelope is invalid.")
    required = {"version", "algorithm", "key_id", "nonce", "ciphertext"}
    if not required.issubset(parsed):
        raise CredentialCryptoError("Credential envelope is missing required fields.")
    return {
        "version": parsed["version"],
        "algorithm": parsed["algorithm"],
        "key_id": str(parsed["key_id"]),
        "nonce": str(parsed["nonce"]),
        "ciphertext": str(parsed["ciphertext"]),
    }


def _key_id(material: bytes, source: str) -> str:
    digest = hashlib.sha256(material).hexdigest()[:16]
    return f"{source}:{digest}"


def _b64(value: bytes) -> str:
    return base64.b64encode(value).decode("ascii")


def _unb64(value: str, field: str) -> bytes:
    try:
        return base64.b64decode(value, validate=True)
    except binascii.Error as error:
        raise CredentialCryptoError(
            f"Credential envelope {field} is not valid base64."
        ) from error


__all__ = [
    "AssetStoreKey",
    "CredentialCipher",
    "CredentialCryptoError",
    "CredentialEnvelope",
    "default_key_path",
    "resolve_asset_store_key",
]
