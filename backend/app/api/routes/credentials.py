"""Credentials: секреты воркспейса (Telegram bot-токен), зашифрованные Fernet.

DESIGN.md §«credentials» + ПРАВКА 12. Наружу отдаются только метаданные —
`encrypted_payload` никогда не сериализуется. Удаление — soft-delete.
"""

import json
import uuid
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import DbSession, require_role
from app.shared.config import settings
from app.shared.crypto import CryptoError, encrypt
from app.shared.models import Credential, WorkspaceMember
from app.shared.schemas.credential import (
    CredentialCreate,
    CredentialListResponse,
    CredentialResponse,
)

router = APIRouter(prefix="/api/workspaces", tags=["credentials"])

# чтение — любому участнику; создание/удаление — owner или admin
Viewer = Annotated[WorkspaceMember, Depends(require_role("owner", "admin", "member"))]
AdminMember = Annotated[WorkspaceMember, Depends(require_role("owner", "admin"))]

# какой auth_type соответствует сервису (ПРАВКА 12: пока только Telegram)
_SERVICE_AUTH_TYPE = {"telegram": "bot_token"}


def _to_response(credential: Credential) -> CredentialResponse:
    return CredentialResponse(
        id=credential.id,
        service=credential.service,
        auth_type=credential.auth_type,
        name=credential.name,
        created_at=credential.created_at,
    )


async def _get_active_credential(
    session: AsyncSession, ws_id: uuid.UUID, credential_id: uuid.UUID
) -> Credential:
    """Credential воркспейса, не удалённый (soft-delete). 404 иначе."""
    credential: Credential | None = await session.get(Credential, credential_id)
    if credential is None or credential.workspace_id != ws_id or credential.deleted_at is not None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Credential not found")
    return credential


@router.get("/{ws_id}/credentials", response_model=CredentialListResponse)
async def list_credentials(
    ws_id: uuid.UUID, member: Viewer, session: DbSession
) -> CredentialListResponse:
    rows = await session.scalars(
        select(Credential)
        .where(Credential.workspace_id == ws_id, Credential.deleted_at.is_(None))
        .order_by(Credential.created_at.desc())
    )
    return CredentialListResponse(items=[_to_response(c) for c in rows])


@router.post(
    "/{ws_id}/credentials",
    status_code=status.HTTP_201_CREATED,
    response_model=CredentialResponse,
)
async def create_credential(
    ws_id: uuid.UUID,
    body: CredentialCreate,
    member: AdminMember,
    session: DbSession,
) -> CredentialResponse:
    if not settings.fernet_key:
        # секрет нельзя сохранить, если нечем шифровать — явная 500 с подсказкой
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="FERNET_KEY is not configured",
        )
    if not body.payload:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="payload must not be empty",
        )

    try:
        encrypted = encrypt(json.dumps(body.payload))
    except CryptoError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc)
        ) from exc

    credential = Credential(
        workspace_id=ws_id,
        service=body.service,
        name=body.name,
        auth_type=_SERVICE_AUTH_TYPE.get(body.service, "api_key"),
        encrypted_payload=encrypted,
        encryption_key_id=settings.fernet_key_id,
        created_by=member.user_id,
    )
    session.add(credential)
    await session.commit()
    await session.refresh(credential)
    return _to_response(credential)


@router.delete("/{ws_id}/credentials/{credential_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_credential(
    ws_id: uuid.UUID,
    credential_id: uuid.UUID,
    member: AdminMember,
    session: DbSession,
) -> None:
    credential = await _get_active_credential(session, ws_id, credential_id)
    # soft-delete: физически строка и payload остаются (аудит, восстановление)
    credential.deleted_at = datetime.now(UTC)
    await session.commit()
    return None
