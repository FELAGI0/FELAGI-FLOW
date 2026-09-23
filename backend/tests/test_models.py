import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.shared.models import User, Workspace, WorkspaceMember


async def _make_user(session: AsyncSession, email: str = "a@b.c") -> User:
    user = User(email=email, password_hash="hash", name="A")
    session.add(user)
    await session.commit()
    return user


async def test_create_user_workspace_member(session: AsyncSession) -> None:
    user = await _make_user(session)
    ws = Workspace(name="Team", slug="team", created_by=user.id)
    session.add(ws)
    await session.flush()
    session.add(WorkspaceMember(workspace_id=ws.id, user_id=user.id, role="owner"))
    await session.commit()

    assert isinstance(user.id, uuid.UUID)
    assert ws.plan == "free"

    member = await session.get(WorkspaceMember, (ws.id, user.id))
    assert member is not None
    assert member.role == "owner"
    assert member.joined_at is not None


async def test_user_email_unique(session: AsyncSession) -> None:
    await _make_user(session, "dup@example.com")
    with pytest.raises(IntegrityError):
        await _make_user(session, "dup@example.com")


async def test_workspace_slug_unique(session: AsyncSession) -> None:
    user = await _make_user(session, "s@example.com")
    session.add(Workspace(name="One", slug="same", created_by=user.id))
    await session.flush()
    with pytest.raises(IntegrityError):
        session.add(Workspace(name="Two", slug="same", created_by=user.id))
        await session.flush()


async def test_timestamps_set_by_server(session: AsyncSession) -> None:
    user = await _make_user(session, "t@example.com")
    assert user.created_at is not None
    assert user.updated_at is not None


async def test_member_cascade_on_workspace_delete(session: AsyncSession) -> None:
    user = await _make_user(session, "c@example.com")
    ws = Workspace(name="C", slug="c-ws", created_by=user.id)
    session.add(ws)
    await session.flush()
    session.add(WorkspaceMember(workspace_id=ws.id, user_id=user.id))
    await session.commit()

    await session.delete(ws)
    await session.commit()

    left = await session.execute(select(WorkspaceMember))
    assert left.scalars().all() == []


@pytest.mark.postgres
async def test_delete_user_owning_workspace_is_restricted(session: AsyncSession) -> None:
    user = await _make_user(session, "owner@example.com")
    session.add(Workspace(name="Owned", slug="owned", created_by=user.id))
    await session.commit()

    with pytest.raises(IntegrityError):
        await session.delete(user)
        await session.commit()
