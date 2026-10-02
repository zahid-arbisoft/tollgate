"""Secret storage: OS keyring first, encrypted-file fallback.

Handles are stable string ids ("provider:3", "key:abc", "admin-token"). Values are
API keys / tokens — never written to the DB. The encrypted-file fallback keeps one
Fernet-encrypted JSON blob in the data dir; its master key lives in the keychain
when possible, otherwise in a 0600 file next to it (documented degraded mode: the
DB dir alone is then no longer useless to an attacker — acceptable for dev/CI).
"""

from __future__ import annotations

import json
import logging
import secrets as pysecrets
from pathlib import Path
from typing import Protocol

from cryptography.fernet import Fernet

log = logging.getLogger(__name__)

KEYRING_SERVICE = "tollgate"


class SecretBackend(Protocol):
    def get(self, handle: str) -> str | None: ...
    def set(self, handle: str, value: str) -> None: ...
    def delete(self, handle: str) -> None: ...


class KeyringBackend:
    def __init__(self) -> None:
        import keyring

        self._kr = keyring

    def get(self, handle: str) -> str | None:
        return self._kr.get_password(KEYRING_SERVICE, handle)

    def set(self, handle: str, value: str) -> None:
        self._kr.set_password(KEYRING_SERVICE, handle, value)

    def delete(self, handle: str) -> None:
        try:
            self._kr.delete_password(KEYRING_SERVICE, handle)
        except Exception:  # noqa: BLE001 - best-effort cleanup
            log.warning("keyring delete failed for %s", handle)


class EncryptedFileBackend:
    """Fernet-encrypted JSON blob at <data_dir>/secrets.enc."""

    FILE_NAME = "secrets.enc"
    MASTER_HANDLE = "master-key"

    def __init__(self, data_dir: Path, keyring: KeyringBackend | None) -> None:
        self._path = data_dir / self.FILE_NAME
        master = keyring.get(self.MASTER_HANDLE) if keyring else None
        key_path = data_dir / "master.key"
        if master is None and keyring is None and key_path.exists():
            # Degraded mode from a previous run: reuse the 0600 master-key file.
            master = key_path.read_text().strip()
        if master is None:
            master = Fernet.generate_key().decode()
            if keyring:
                keyring.set(self.MASTER_HANDLE, master)
            else:
                key_path.write_text(master)
                key_path.chmod(0o600)
                log.warning("keyring unavailable; master key stored in %s", key_path)
        self._fernet = Fernet(master.encode())
        self._data: dict[str, str] = self._load()

    def _load(self) -> dict[str, str]:
        if not self._path.exists():
            return {}
        try:
            return json.loads(self._fernet.decrypt(self._path.read_bytes()))
        except Exception:  # noqa: BLE001 - corrupt file must not brick the app
            log.error("secrets file unreadable; starting empty (%s)", self._path)
            return {}

    def _flush(self) -> None:
        self._path.write_bytes(self._fernet.encrypt(json.dumps(self._data).encode()))
        self._path.chmod(0o600)

    def get(self, handle: str) -> str | None:
        return self._data.get(handle)

    def set(self, handle: str, value: str) -> None:
        self._data[handle] = value
        self._flush()

    def delete(self, handle: str) -> None:
        self._data.pop(handle, None)
        self._flush()


class Secrets:
    """Front door: keyring if usable, else encrypted file."""

    def __init__(self, backend: SecretBackend) -> None:
        self._backend = backend

    @classmethod
    def create(cls, data_dir: Path, preference: str = "auto") -> Secrets:
        keyring = None
        if preference in ("auto", "keyring"):
            try:
                probe = KeyringBackend()
                probe.set("__probe__", "ok")
                if probe.get("__probe__") == "ok":
                    probe.delete("__probe__")
                    keyring = probe
            except Exception:  # noqa: BLE001 - any keyring failure → fallback
                log.info("keyring unavailable; using encrypted-file secrets")
        if preference == "keyring" and keyring is None:
            raise RuntimeError("secrets backend 'keyring' requested but unavailable")
        if keyring is not None:
            return cls(keyring)
        return cls(EncryptedFileBackend(data_dir, keyring=None))

    def get(self, handle: str) -> str | None:
        return self._backend.get(handle)

    def set(self, handle: str, value: str) -> None:
        self._backend.set(handle, value)

    def delete(self, handle: str) -> None:
        self._backend.delete(handle)


def generate_secret(nbytes: int = 30) -> str:
    return pysecrets.token_urlsafe(nbytes)
