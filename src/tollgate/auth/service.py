"""Virtual-key lifecycle: create / lookup / rotate / status transitions.

Keys are `tg-` + 40 urlsafe chars, stored as SHA-256 hash + display prefix.
The plaintext is returned exactly once at creation (unless the caller opts into
encrypted re-display storage — off by default).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from ..ids import new_ulid
from ..security.hashing import sha256_hex
from ..security.secrets import Secrets, generate_secret
from ..store.models import VirtualKey

KEY_PREFIX = "tg-"
PREFIX_LEN = 8  # e.g. "tg-7f3a"


class KeyService:
    def __init__(self, session_factory, secrets: Secrets, rotation_grace_s: int = 3600):
        self._sessions = session_factory
        self._secrets = secrets
        self._grace = rotation_grace_s
        # Set by app bootstrap; key mutations emit config events when present.
        self.instance_id: str | None = None

    async def _emit(self, session, key: VirtualKey, op: str = "upsert") -> None:
        """Append a config event for peer sync (no-op for unsynced installs)."""
        if not self.instance_id:
            return
        import json as _json

        from ..ids import new_ulid
        from ..store.models import ConfigEvent
        from ..sync.serialize import key_payload

        session.add(
            ConfigEvent(
                id=new_ulid(),
                entity="key",
                row_pk=key.id,
                op=op,
                payload_json=_json.dumps(key_payload(key), default=str) if op == "upsert" else None,
                origin_instance=self.instance_id,
                applied=True,
            )
        )

    async def create(
        self,
        *,
        name: str = "",
        project: str | None = None,
        notes: str | None = None,
        expires_at: datetime | None = None,
        expires_in_days: int | None = None,
        allowed_providers: list[str] | None = None,
        allowed_models_aliases: list[str] | None = None,
        store_plaintext: bool = False,
    ) -> tuple[VirtualKey, str]:
        if expires_at is None and expires_in_days is not None:
            expires_at = datetime.now(UTC) + timedelta(days=expires_in_days)
        plaintext = KEY_PREFIX + generate_secret(30)  # 40 urlsafe chars
        key = VirtualKey(
            id=new_ulid(),
            prefix=plaintext[:PREFIX_LEN],  # UI renders the trailing ellipsis
            key_hash=sha256_hex(plaintext),
            name=name,
            project=project,
            notes=notes,
            expires_at=expires_at,
            allowed_providers=allowed_providers,
            allowed_models_aliases=allowed_models_aliases,
        )
        if store_plaintext:
            key.secret_handle = f"key:{key.id}"
            self._secrets.set(key.secret_handle, plaintext)
        async with self._sessions() as session:
            session.add(key)
            await self._emit(session, key)
            await session.commit()
            await session.refresh(key)
        return key, plaintext

    async def find_by_hash(self, key_hash: str) -> VirtualKey | None:
        async with self._sessions() as session:
            row = (
                await session.execute(select(VirtualKey).where(VirtualKey.key_hash == key_hash))
            ).scalar_one_or_none()
            if row is not None:
                # Detach a plain snapshot copy for request-scoped use.
                session.expunge(row)
            return row

    async def find_by_plaintext(self, plaintext: str) -> VirtualKey | None:
        return await self.find_by_hash(sha256_hex(plaintext))

    async def lookup_active(self, plaintext: str) -> VirtualKey | None:
        """Find and enforce status/expiry; flips expired keys on the fly."""
        key = await self.find_by_plaintext(plaintext)
        if key is None:
            return None
        if key.expires_at is not None and key.expires_at <= datetime.now(UTC):
            await self.set_status(key.id, "expired")
            key.status = "expired"
            return None
        if key.status != "active":
            return None
        return key

    async def set_status(
        self, key_id: str, status: str, reason: str | None = None
    ) -> VirtualKey | None:
        async with self._sessions() as session:
            row = await session.get(VirtualKey, key_id)
            if row is not None:
                row.status = status
                row.blocked_reason = reason if status == "blocked" else None
                await self._emit(session, row)
            await session.commit()
        return await self.get(key_id)

    async def get(self, key_id: str) -> VirtualKey | None:
        async with self._sessions() as session:
            row = await session.get(VirtualKey, key_id)
            if row is not None:
                session.expunge(row)
            return row

    async def rotate(self, key_id: str, grace_s: int | None = None) -> tuple[VirtualKey, str]:
        """Issue a replacement; the old key keeps working for the grace window."""
        old = await self.get(key_id)
        if old is None:
            raise KeyError(f"no such key: {key_id}")
        grace = self._grace if grace_s is None else grace_s
        new, plaintext = await self.create(
            name=old.name,
            project=old.project,
            notes=old.notes,
            expires_at=old.expires_at,
            allowed_providers=old.allowed_providers,
            allowed_models_aliases=old.allowed_models_aliases,
        )
        async with self._sessions() as session:
            new_row = await session.get(VirtualKey, new.id)
            old_row = await session.get(VirtualKey, old.id)
            if new_row is not None:
                new_row.rotated_from = old.id
                await self._emit(session, new_row)
            if old_row is not None:
                old_row.expires_at = datetime.now(UTC) + timedelta(seconds=grace)
                await self._emit(session, old_row)
            await session.commit()
        return await self.get(new.id), plaintext  # type: ignore[return-value]

    async def extend(self, key_id: str, days: int) -> VirtualKey | None:
        async with self._sessions() as session:
            row = await session.get(VirtualKey, key_id)
            if row is not None:
                row.expires_at = datetime.now(UTC) + timedelta(days=days)
                row.status = "active"
                await self._emit(session, row)
            await session.commit()
        return await self.get(key_id)

    async def stored_plaintext(self, key: VirtualKey) -> str | None:
        if not key.secret_handle:
            return None
        return self._secrets.get(key.secret_handle)
