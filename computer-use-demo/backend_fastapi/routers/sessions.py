from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session as OrmSession

from ..database import get_db
from ..models import Message, Session
from ..schemas import MessageRead, SessionCreate, SessionRead

router = APIRouter(prefix="/sessions", tags=["sessions"])

DbDep = Annotated[OrmSession, Depends(get_db)]


@router.post("", response_model=SessionRead, status_code=status.HTTP_201_CREATED)
def create_session(
    body: SessionCreate,
    db: DbDep,
) -> SessionRead:
    row = Session(status=body.status, vnc_port=body.vnc_port)
    db.add(row)
    db.commit()
    db.refresh(row)
    return SessionRead.model_validate(row)


@router.get("/{session_id}", response_model=SessionRead)
def get_session(
    session_id: int,
    db: DbDep,
) -> SessionRead:
    row = db.get(Session, session_id)
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Session not found"
        )
    return SessionRead.model_validate(row)


@router.get("/{session_id}/history", response_model=list[MessageRead])
def get_session_history(
    session_id: int,
    db: DbDep,
) -> list[MessageRead]:
    if db.get(Session, session_id) is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Session not found"
        )
    stmt = (
        select(Message)
        .where(Message.session_id == session_id)
        .order_by(Message.timestamp.asc(), Message.id.asc())
    )
    rows = db.scalars(stmt).all()
    return [MessageRead.model_validate(m) for m in rows]
