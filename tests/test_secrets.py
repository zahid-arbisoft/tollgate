from __future__ import annotations

from pathlib import Path

import pytest

from tollgate.security.secrets import EncryptedFileBackend, Secrets


def test_file_backend_roundtrip(tmp_path: Path):
    backend = EncryptedFileBackend(tmp_path, keyring=None)
    backend.set("provider:1", "sk-very-secret")
    assert backend.get("provider:1") == "sk-very-secret"
    backend.delete("provider:1")
    assert backend.get("provider:1") is None


def test_file_backend_persists_and_is_encrypted(tmp_path: Path):
    backend = EncryptedFileBackend(tmp_path, keyring=None)
    backend.set("k", "sk-another-secret")
    blob = (tmp_path / "secrets.enc").read_bytes()
    assert b"sk-another-secret" not in blob

    reloaded = EncryptedFileBackend(tmp_path, keyring=None)
    # New backend re-derives the same key from master.key file
    assert reloaded.get("k") == "sk-another-secret"


def test_secrets_create_forces_file(tmp_path: Path):
    s = Secrets.create(tmp_path, preference="file")
    s.set("admin-token", "tok")
    assert s.get("admin-token") == "tok"


def test_secrets_keyring_preference(tmp_path: Path):
    import logging

    logging.disable(logging.CRITICAL)
    try:
        try:
            s = Secrets.create(tmp_path, preference="keyring")
        except RuntimeError:
            pytest.skip("keyring unavailable on this machine")
        s.set("x", "y")
        assert s.get("x") == "y"
    finally:
        logging.disable(logging.NOTSET)
