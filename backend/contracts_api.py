# Author: WangLei
# Email: WangLei1578@outlook.com
# Date: 2026-09-28

import json
import os
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, UploadFile

from backend.auth import allow_roles, current_user
from backend.document_service import extract, metadata
from backend.review_service import review
from backend.storage import UPLOADS, connect, log, task_data

router = APIRouter()
MAX_UPLOAD = 20 * 1024 * 1024
FORMATS = {".docx", ".pdf", ".png", ".jpg", ".jpeg", ".tif", ".tiff"}


def save_risks(db, task_id, text, risks):
    for risk in risks:
        page = text[:risk["start"]].count("\f") + 1
        db.execute("INSERT INTO risks(id,task_id,level,title,clause_type,original_text,start,end,page,reason,legal_basis,suggestion,suggested_text) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)", (str(uuid.uuid4()), task_id, risk["level"], risk["title"], risk["clause_type"], risk["original_text"], risk["start"], risk["end"], page, risk["reason"], risk["legal_basis"], risk["suggestion"], risk["suggested_text"]))


def process_upload(task_id, path, suffix):
    started = time.monotonic()
    try:
        with connect() as db:
            db.execute("UPDATE tasks SET status='parsing' WHERE id=?", (task_id,))
            log(db, task_id, "文档解析开始")
        text, pages = extract(path, suffix)
        if not text.strip():
            raise ValueError("文档正文为空")
        with connect() as db:
            db.execute("UPDATE tasks SET status='reviewing',text=?,metadata=? WHERE id=?", (text, json.dumps({**metadata(text), "pages": pages}, ensure_ascii=False), task_id))
            log(db, task_id, "文档解析完成，开始风险审查")
        risks = review(text)
        # ponytail: configurable floor keeps the asynchronous state visible in a local demo; production can set 0.
        floor = max(0.0, float(os.getenv("MIN_REVIEW_SECONDS", "1.2")))
        time.sleep(max(0.0, floor - (time.monotonic() - started)))
        with connect() as db:
            db.execute("DELETE FROM risks WHERE task_id=?", (task_id,))
            save_risks(db, task_id, text, risks)
            db.execute("UPDATE tasks SET status='completed',blocked_reason=NULL WHERE id=?", (task_id,))
            log(db, task_id, "AI审查完成")
    except Exception as exc:
        with connect() as db:
            db.execute("UPDATE tasks SET status='blocked',blocked_reason=? WHERE id=?", (str(exc)[:1000], task_id))
            log(db, task_id, f"任务阻塞：{exc}")


@router.get("/api/review/tasks")
def list_tasks(user=Depends(current_user)):
    with connect() as db:
        sql = """
            SELECT t.id,t.name,t.filename,t.status,t.blocked_reason,t.writeback_status,t.created_at,
            (SELECT r.level FROM risks r WHERE r.task_id=t.id ORDER BY CASE r.level WHEN 'HIGH' THEN 0 WHEN 'MEDIUM' THEN 1 ELSE 2 END LIMIT 1) top_level,
            (SELECT count(*) FROM risks r WHERE r.task_id=t.id AND r.level='HIGH') high_count,
            (SELECT group_concat(DISTINCT r.level) FROM risks r WHERE r.task_id=t.id) risk_levels
            FROM tasks t
        """
        rows = db.execute(sql + (" WHERE t.owner_id=?" if user["role"] == "business" else "") + " ORDER BY t.created_at DESC", (user["id"],) if user["role"] == "business" else ()).fetchall()
        return [dict(row) for row in rows]


@router.post("/api/contracts/upload")
async def upload_contract(background_tasks: BackgroundTasks, file: UploadFile = File(...), name: str = Form(""), user=Depends(allow_roles("business", "legal", "admin"))):
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in FORMATS:
        raise HTTPException(400, "仅支持 DOCX、PDF 和图片")
    content = await file.read(MAX_UPLOAD + 1)
    if not content or len(content) > MAX_UPLOAD:
        raise HTTPException(400, "文件为空或超过20MB")
    task_id = str(uuid.uuid4())
    path = UPLOADS / f"{task_id}{suffix}"
    path.write_bytes(content)
    created = datetime.now(timezone.utc).isoformat()
    with connect() as db:
        db.execute("INSERT INTO tasks(id,name,filename,text,status,blocked_reason,metadata,created_at,owner_id) VALUES(?,?,?,?,?,?,?,?,?)", (task_id, name.strip() or Path(file.filename).stem, file.filename or path.name, "", "pending", None, "{}", created, user["id"]))
        log(db, task_id, "任务创建，等待解析")
    background_tasks.add_task(process_upload, task_id, path, suffix)
    task, risk_items = task_data(task_id)
    return {"task": task, "risks": risk_items}


@router.post("/api/demo")
def create_demo(kind: str = "risk", user=Depends(current_user)):
    task_id = str(uuid.uuid4())
    if kind not in {"risk", "normal"}:
        raise HTTPException(400, "示例类型无效")
    risky_text = """软件采购合同
合同编号：CG-2026-018
甲方：示例科技有限公司
乙方：云端软件供应商
合同金额：人民币 480,000 元
履行期限：2026年10月1日至2027年9月30日

一、交付与付款
乙方完成软件交付后，甲方应支付全部合同价款。

二、知识产权
本项目开发成果及相关知识产权均归乙方所有。

三、违约责任
乙方逾期交付的，每日按合同金额万分之一支付违约金；甲方承担的赔偿责任不设上限。

四、保密
双方对合作中获知的保密信息承担保密义务。
"""
    normal_text = """软件采购合同
合同编号：CG-2026-019
甲方：示例科技有限公司
乙方：可信软件服务商
合同金额：人民币 120,000 元
履行期限：2026年10月1日至2027年9月30日

一、交付与付款
乙方完成软件交付后，甲方验收合格并收到合法发票后十五个工作日内支付合同价款。

二、知识产权
双方背景知识产权归各自所有；本项目定制成果的知识产权归甲方所有。

三、违约责任
双方因违反本合同约定造成损失的，应依法承担相应赔偿责任。

四、保密
双方对保密信息承担保密义务，该义务在合同终止后继续有效五年。
"""
    text = normal_text if kind == "normal" else risky_text
    name = "软件采购合同正常示例" if kind == "normal" else "软件采购合同风险示例"
    filename = name + ".docx"
    risks = review(text)
    with connect() as db:
        db.execute("INSERT INTO tasks(id,name,filename,text,status,metadata,created_at,owner_id) VALUES(?,?,?,?,?,?,?,?)", (task_id, name, filename, text, "completed", json.dumps({**metadata(text), "pages": 1}, ensure_ascii=False), datetime.now(timezone.utc).isoformat(), user["id"]))
        save_risks(db, task_id, text, risks)
        log(db, task_id, "加载示例合同并完成审查")
    task, risk_items = task_data(task_id)
    return {"task": task, "risks": risk_items}


@router.get("/api/review/tasks/{task_id}")
def get_task(task_id: str, user=Depends(current_user)):
    task, risks = task_data(task_id, user)
    task["metadata"] = json.loads(task["metadata"])
    return {"task": task, "risks": risks}


@router.get("/api/review/tasks/{task_id}/risks")
def get_task_risks(task_id: str, user=Depends(current_user)):
    _, risks = task_data(task_id, user)
    return risks


@router.post("/api/review/tasks/{task_id}/retry")
def retry_task(task_id: str, user=Depends(allow_roles("admin"))):
    task, _ = task_data(task_id, user)
    path = UPLOADS / f"{task_id}{Path(task['filename']).suffix.lower()}"
    text, pages, risks = "", 0, []
    try:
        text, pages = extract(path, path.suffix)
        if not text.strip():
            raise ValueError("文档正文为空")
        risks = review(text)
        status, error = "completed", None
    except Exception as exc:
        status, error = "blocked", str(exc)[:1000]
    with connect() as db:
        db.execute("DELETE FROM risks WHERE task_id=?", (task_id,))
        db.execute("UPDATE tasks SET text=?,status=?,blocked_reason=?,metadata=? WHERE id=?", (text, status, error, json.dumps({**metadata(text), "pages": pages}, ensure_ascii=False), task_id))
        save_risks(db, task_id, text, risks)
        log(db, task_id, "任务重试")
    return get_task(task_id, user)


@router.get("/api/risks/{risk_id}")
def get_risk(risk_id: str, user=Depends(current_user)):
    with connect() as db:
        risk = db.execute("SELECT * FROM risks WHERE id=?", (risk_id,)).fetchone()
        if not risk:
            raise HTTPException(404, "风险项不存在")
        task_data(risk["task_id"], user)
        return dict(risk)


@router.put("/api/risks/{risk_id}")
def update_risk(risk_id: str, payload: dict, user=Depends(allow_roles("legal", "admin"))):
    with connect() as db:
        row = db.execute("SELECT * FROM risks WHERE id=?", (risk_id,)).fetchone()
        if not row:
            raise HTTPException(404, "风险项不存在")
        task_data(row["task_id"], user)
        fields = {"suggested_text": 2000, "suggestion": 1000}
        updates = {key: str(payload[key])[:limit] for key, limit in fields.items() if key in payload}
        if "accepted" in payload:
            updates["accepted"] = int(bool(payload["accepted"]))
        if not updates:
            raise HTTPException(400, "没有可更新字段")
        db.execute(f"UPDATE risks SET {','.join(f'{key}=?' for key in updates)} WHERE id=?", (*updates.values(), risk_id))
        log(db, row["task_id"], "人工修改风险建议")
        return dict(db.execute("SELECT * FROM risks WHERE id=?", (risk_id,)).fetchone())


@router.post("/api/review/tasks/{task_id}/comments")
def add_comment(task_id: str, payload: dict, user=Depends(allow_roles("legal", "admin"))):
    note = str(payload.get("comment", ""))[:5000].strip()
    if not note:
        raise HTTPException(400, "法务意见不能为空")
    task_data(task_id, user)
    with connect() as db:
        db.execute("UPDATE tasks SET comments=? WHERE id=?", (note, task_id))
        log(db, task_id, "添加法务意见")
    return {"comment": note}
