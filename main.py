"""允许使用 `uv run python main.py` 启动本地开发服务器。"""

import uvicorn


if __name__ == "__main__":
    uvicorn.run("app.main:app", host="127.0.0.1", port=8001, reload=True)
