import os
import asyncio
import secrets
from fastapi import FastAPI, Depends, Request, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
import uvicorn

from . import logic

# --- FastAPI 应用定义 ---

app = FastAPI()

# 配置 CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- 认证依赖 ---


async def verify_token(request: Request):
    """FastAPI 依赖项，用于验证 'Authorization: Bearer <token>' 请求头。"""
    token = request.headers.get("Authorization")
    secret_key = getattr(request.app.state, "secret_key", None)

    if not token or not token.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="无效的认证格式，需要 'Bearer <token>'",
            headers={"WWW-Authenticate": "Bearer"},
        )

    token_value = token.split(" ", 1)[1]

    if not secret_key or not secrets.compare_digest(token_value, secret_key):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="无效或缺失的认证Token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return True


# --- API 路由 ---


@app.get("/api/verify", dependencies=[Depends(verify_token)])
async def verify_token_endpoint():
    """用于前端验证 Token 的有效性"""
    return {"status": "ok"}


@app.get(
    "/api/commands",
    response_model=list[logic.CommandInfo],
    dependencies=[Depends(verify_token)],
)
async def get_commands_endpoint():
    """获取所有指令及其状态"""
    return await asyncio.to_thread(logic.get_all_commands)


@app.post("/api/commands/toggle", dependencies=[Depends(verify_token)])
async def toggle_command_endpoint(item: logic.ToggleItem):
    """切换指令的启用/禁用状态"""
    return await asyncio.to_thread(logic.toggle_command, item)


@app.post("/api/plugins/toggle", dependencies=[Depends(verify_token)])
async def toggle_plugin_endpoint(item: logic.TogglePluginItem):
    """切换某个插件下所有指令的启用/禁用状态"""
    return await asyncio.to_thread(logic.toggle_plugin_commands, item)


def run(secret_key_to_pass: str, host: str = "0.0.0.0", port: int = 5000):
    """
    启动 WebUI 的 uvicorn 服务器。
    此函数设计为在独立的线程中运行。
    """
    # 正确的做法是将密钥设置在 app.state 上，而不是全局变量
    app.state.secret_key = secret_key_to_pass

    uvicorn.run(app, host=host, port=port, log_level="warning")


# 挂载静态文件目录
# 确保在插件的任何地方调用 os.path.dirname(__file__) 都能正确解析路径
frontend_dist_path = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "frontend", "dist"
)
app.mount("/", StaticFiles(directory=frontend_dist_path, html=True), name="static")
