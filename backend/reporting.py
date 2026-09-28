# Author: WangLei
# Email: WangLei1578@outlook.com
# Date: 2026-09-28

import io
import json
import os
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import PlainTextResponse, Response

from backend.auth import allow_roles, current_user
from backend.storage import connect, log, task_data

router = APIRouter()


def build_report(task, risks):
    meta = json.loads(task["metadata"])
    lines = [f"# 合同审查报告：{task['name']}", "", f"- 原文件：{task['filename']}", f"- 状态：{task['status']}", f"- 合同编号：{meta.get('contract_number', '未识别')}", f"- 合同金额：{meta.get('amount', '未识别')}", f"- 创建时间：{task['created_at']}", "", f"## 综合结论：{'需重点整改' if any(r['level']=='HIGH' for r in risks) else '建议法务复核' if risks else '未发现内置规则命中'}", "", "## 风险清单"]
    for risk in risks:
        lines.extend([f"### [{risk['level']}] {risk['title']}", f"- 页码：{risk['page']}", f"- 原文：{risk['original_text']}", f"- 原因：{risk['reason']}", f"- 依据：{risk['legal_basis']}", f"- 建议：{risk['suggestion']}", f"- 建议条款：{risk['suggested_text']}", f"- 法务采纳：{'是' if risk['accepted'] else '待确认'}", ""])
    lines.extend(["## 法务意见", task["comments"] or "暂无", "", f"## 回写状态：{task['writeback_status']}"])
    return "\n".join(lines)


@router.get("/api/review/tasks/{task_id}/report/markdown")
def markdown_report(task_id: str, user=Depends(current_user)):
    task, risks = task_data(task_id, user)
    return PlainTextResponse(build_report(task, risks), media_type="text/markdown; charset=utf-8", headers={"Content-Disposition": f'attachment; filename="report-{task_id}.md"'})


@router.get("/api/review/tasks/{task_id}/report/pdf")
def pdf_report(task_id: str, user=Depends(current_user)):
    task, risks = task_data(task_id, user)
    try:
        from reportlab.lib.pagesizes import A4
        from reportlab.pdfbase import pdfmetrics
        from reportlab.pdfbase.ttfonts import TTFont
        from reportlab.pdfgen import canvas
        font = next((path for path in [Path(os.getenv("PDF_FONT", "")), Path("C:/Windows/Fonts/msyh.ttc"), Path("/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc")] if str(path) and path.is_file()), None)
        if not font:
            raise RuntimeError("未找到中文字体；设置 PDF_FONT 指向中文 TTF 字体")
        pdfmetrics.registerFont(TTFont("CJK", str(font), subfontIndex=0))
        output = io.BytesIO()
        pdf = canvas.Canvas(output, pagesize=A4)
        _, height = A4
        y = height - 48
        pdf.setFont("CJK", 10)
        for raw_line in build_report(task, risks).splitlines():
            for line in [raw_line[i:i + 48] for i in range(0, max(1, len(raw_line)), 48)]:
                if y < 48:
                    pdf.showPage()
                    pdf.setFont("CJK", 10)
                    y = height - 48
                pdf.drawString(40, y, line)
                y -= 16
        pdf.save()
        return Response(output.getvalue(), media_type="application/pdf", headers={"Content-Disposition": f'attachment; filename="report-{task_id}.pdf"'})
    except (ImportError, RuntimeError) as exc:
        raise HTTPException(503, str(exc)) from exc


@router.post("/api/review/tasks/{task_id}/writeback")
def writeback(task_id: str, user=Depends(allow_roles("legal", "admin"))):
    task, risks = task_data(task_id, user)
    if task["status"] != "completed":
        raise HTTPException(409, "阻塞任务不能回写")
    body = build_report(task, risks)
    with connect() as db:
        db.execute("UPDATE tasks SET writeback_status='success',writeback=? WHERE id=?", (body, task_id))
        log(db, task_id, "模拟审批系统回写成功")
    return {"status": "success", "content": body}


@router.get("/api/review/tasks/{task_id}/writeback")
def get_writeback(task_id: str, user=Depends(current_user)):
    task, _ = task_data(task_id, user)
    return {"status": task["writeback_status"], "content": task["writeback"]}
