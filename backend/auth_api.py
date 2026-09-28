# Author: WangLei
# Email: WangLei1578@outlook.com
# Date: 2026-09-28

from fastapi import APIRouter, Depends, Header

from backend.auth import current_user, login
from backend.storage import connect

router = APIRouter()


@router.post("/api/auth/login")
def login_route(payload: dict):
    return login(payload.get("username", ""), payload.get("password", ""))


@router.get("/api/auth/me")
def me(user=Depends(current_user)):
    return user


@router.post("/api/auth/logout")
def logout(authorization: str | None = Header(default=None)):
    if authorization and authorization.lower().startswith("bearer "):
        with connect() as db:
            db.execute("DELETE FROM sessions WHERE token=?", (authorization[7:].strip(),))
    return {"ok": True}
