# Author: WangLei
# Email: WangLei1578@outlook.com
# Date: 2026-09-28

from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from backend.contracts_api import router as contracts_router
from backend.auth_api import router as auth_router
from backend.reporting import router as reporting_router
from backend.storage import ROOT

try:
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env")
except ImportError:
    pass

app = FastAPI(title="合同审批审查系统", version="1.0.0")
app.include_router(auth_router)
app.include_router(contracts_router)
app.include_router(reporting_router)
app.mount("/static", StaticFiles(directory=ROOT / "static"), name="static")


@app.get("/", include_in_schema=False)
def home():
    from fastapi.responses import FileResponse
    return FileResponse(Path(ROOT / "static" / "index.html"))


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app:app", host="127.0.0.1", port=8000, reload=True)
