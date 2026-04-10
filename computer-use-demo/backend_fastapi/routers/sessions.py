from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session as OrmSession

from ..database import get_db
from ..docker_manager import (
    DockerOrchestrationError,
    is_orchestration_enabled,
    start_session_environment,
    stop_session_environment,
)
from ..models import Message, Session
from ..novnc_urls import build_session_vnc_info
from ..schemas import MessageRead, SessionCreate, SessionRead, SessionVncInfo

router = APIRouter(prefix="/sessions", tags=["sessions"])

DbDep = Annotated[OrmSession, Depends(get_db)]


@router.post("", response_model=SessionRead, status_code=status.HTTP_201_CREATED)
def create_session(
    body: SessionCreate,
    db: DbDep,
) -> SessionRead:
    orchestrate = is_orchestration_enabled()
    row = Session(
        status="provisioning" if orchestrate else body.status,
        vnc_port=None if orchestrate else body.vnc_port,
        agent_api_port=None if orchestrate else body.agent_api_port,
        docker_container_id=None,
    )
    db.add(row)
    db.commit()
    db.refresh(row)

    if not orchestrate:
        return SessionRead.model_validate(row)

    try:
        rt = start_session_environment(row.id)
    except DockerOrchestrationError as e:
        row.status = "failed"
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(e),
        ) from e

    row.vnc_port = rt.novnc_host_port
    row.agent_api_port = rt.agent_api_host_port
    row.docker_container_id = rt.container_id
    row.status = body.status
    db.commit()
    db.refresh(row)
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


@router.get("/{session_id}/vnc", response_model=SessionVncInfo)
def get_session_vnc(
    session_id: int,
    db: DbDep,
) -> SessionVncInfo:
    row = db.get(Session, session_id)
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Session not found",
        )
    if row.vnc_port is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Session has no active VNC endpoint",
        )
    return build_session_vnc_info(session_id=row.id, vnc_port=row.vnc_port)


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


@router.delete("/{session_id}", response_model=SessionRead)
def delete_session(
    session_id: int,
    db: DbDep,
) -> SessionRead:
    row = db.get(Session, session_id)
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Session not found"
        )
    cid = row.docker_container_id
    if cid:
        try:
            stop_session_environment(cid)
        except DockerOrchestrationError as e:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=str(e),
            ) from e

    row.status = "stopped"
    row.docker_container_id = None
    row.vnc_port = None
    row.agent_api_port = None
    db.commit()
    db.refresh(row)
    return SessionRead.model_validate(row)
