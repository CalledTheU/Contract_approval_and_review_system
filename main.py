# Author: WangLei
# Email: WangLei1578@outlook.com
# Date: 2026-09-28

from app import app

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app:app", host="127.0.0.1", port=8000, reload=True)
