# Author: WangLei
# Email: WangLei1578@outlook.com
# Date: 2026-09-28

import hashlib
import hmac
import secrets
import time

from fastapi import Depends, Header, HTTPException

from backend.storage import connect


def login(username, password):
    with connect() as db:
        user = db.execute("SELECT * FROM users WHERE username=?", (str(username)[:80],)).fetchone()
        if not user:
            raise HTTPException(401, "用户名或密码错误")
        digest = hashlib.pbkdf2_hmac("sha256", str(password).encode(), bytes.fromhex(user["salt"]), 160000).hex()
        if not hmac.compare_digest(digest, user["password_hash"]):
            raise HTTPException(401, "用户名或密码错误")
        token = secrets.token_urlsafe(32)
        db.execute("INSERT INTO sessions(token,user_id,expires) VALUES(?,?,?)", (token, user["id"], time.time() + 12 * 60 * 60))
        return {"token": token, "user": {"id": user["id"], "username": user["username"], "display_name": user["display_name"], "role": user["role"]}}


def current_user(authorization: str | None = Header(default=None)):
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(401, "请先登录")
    token = authorization[7:].strip()
    with connect() as db:
        row = db.execute("SELECT u.id,u.username,u.display_name,u.role FROM sessions s JOIN users u ON u.id=s.user_id WHERE s.token=? AND s.expires>?", (token, time.time())).fetchone()
        if not row:
            raise HTTPException(401, "登录已过期，请重新登录")
        return dict(row)


def allow_roles(*roles):
    def check(user=Depends(current_user)):
        if user["role"] not in roles:
            raise HTTPException(403, "当前角色无权执行此操作")
        return user
    return check
