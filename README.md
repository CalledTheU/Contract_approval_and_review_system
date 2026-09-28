# 合同审批审查系统

本地运行的合同解析与风险审查 MVP，包含 DOCX/PDF/图片接入、元数据提取、规则审查、法务复核、模拟审批回写以及 Markdown/PDF 报告。

代码按职责拆分：`backend/storage.py`（SQLite 与审计日志）、`backend/document_service.py`（DOCX/PDF/OCR）、`backend/review_service.py`（规则与可选 LLM）、`backend/contracts_api.py`（上传/任务/风险）、`backend/reporting.py`（报告/回写）、`backend/auth.py`（演示 RBAC）；`app.py` 仅负责组装路由。

## 启动

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python main.py
```

打开 <http://127.0.0.1:8000>。首页提供正常与风险合同示例。Swagger 接口文档在 <http://127.0.0.1:8000/docs>。

首页可载入软件采购示例，或上传不超过 20 MB 的 DOCX、可搜索 PDF、PNG/JPEG/TIFF。扫描图片 OCR 需要本机安装 Tesseract 和中文语言包；可用 `TESSERACT_CMD`、`OCR_LANG` 指定命令及语言。扫描版 PDF 当前会进入阻塞状态，请先 OCR 成可搜索 PDF 后上传。

演示账号：`legal / Demo123!`（复核与回写）、`business / Demo123!`（提交并查看本人任务）、`admin / Demo123!`（查看全部任务及重试）。

设置 `LLM_REVIEW_ENABLED=1` 和 `DEEPSEEK_API_KEY` 可启用 DeepSeek 兼容的 JSON 风险审查；默认使用内置规则完成离线演示。扫描版 PDF 和图片 OCR 需要本机安装 Tesseract 及中文语言包。PDF 报告需要中文字体，Windows 默认使用微软雅黑；其他环境可通过 `PDF_FONT` 指定 TTF 字体文件。

## 检查

```powershell
python -m unittest discover -s tests -v
```

数据保存在 `data/contracts.db` 和 `data/uploads/`。审批回写目前为本地模拟记录，不会连接企业审批系统。
