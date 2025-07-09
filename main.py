import asyncio
import secrets
from threading import Thread
from typing import Optional
import uvicorn

from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.star import Context, Star
from astrbot.core.star.filter.permission import PermissionType

class CommandManagerPlugin(Star):
    def __init__(self, context: Context):
        super().__init__(context)
        self.webui_thread: Optional[Thread] = None
        self.webui_server: Optional[uvicorn.Server] = None
        self.secret_key = None

    async def initialize(self):
        """插件初始化时，安排一个延迟任务来恢复禁用指令配置"""
        delay = self.context.get_config().get("init_delay", 15)
        asyncio.create_task(self.deferred_initialize(delay))
        logger.info(
            f"指令管理器插件已加载。将在 {delay} 秒后恢复指令状态。使用 /cmdmgr on 启动管理后台。"
        )

    async def deferred_initialize(self, delay: int):
        """延迟执行初始化，以确保所有插件都已加载完毕"""
        from . import logic

        logger.info(f"Command Manager: 延迟 {delay} 秒后，开始异步恢复指令禁用状态...")
        await asyncio.sleep(delay)
        # 在异步函数中安全地调用同步阻塞函数
        await asyncio.to_thread(logic.initialize_disabled_commands)
        logger.info("指令状态恢复完成。")

    async def terminate(self):
        """插件终止时，移除补丁并关闭 WebUI"""
        from . import logic

        # 移除猴子补丁，恢复核心功能
        await asyncio.to_thread(logic.remove_patch)

        # 关闭 WebUI
        await asyncio.to_thread(self._shutdown_webui)
        logger.info("指令管理器插件已完全卸载，资源已清理。")

    @filter.command_group("cmdmgr", alias={"指令管理"})
    @filter.permission_type(PermissionType.ADMIN)
    def command_manager_group(self):
        """指令管理后台命令组"""
        pass

    @command_manager_group.command("on")
    async def start_webui_command(self, event: AstrMessageEvent):
        """启动指令管理后台"""
        if self.webui_thread and self.webui_thread.is_alive():
            yield event.plain_result("管理后台已经在运行中。")
            return

        yield event.plain_result("正在启动管理后台，请稍候...")

        try:
            config_obj = self.context.get_config()
            host = config_obj.get("host", "0.0.0.0")
            port = int(config_obj.get("port", 5000))

            if await self._is_port_in_use(host, port):
                yield event.plain_result(f"启动失败：端口 {port} 已被占用。")
                return

            self.secret_key = self._start_webui(config_obj)

            # 等待服务器就绪
            for _ in range(10):
                if await self._is_port_in_use(host, port):
                    break
                await asyncio.sleep(1)
            else:
                # 关键修复：使用 to_thread 调用阻塞的 shutdown
                await asyncio.to_thread(self._shutdown_webui)
                raise RuntimeError("后台服务启动超时，已自动关闭。")

            if not self.webui_thread.is_alive():
                raise RuntimeError("后台进程未能成功启动，请检查日志。")


            yield event.plain_result(f"{self.secret_key}")

        except Exception as e:
            logger.error(f"启动管理后台时发生意外错误: {e}", exc_info=True)
            # 关键修复：使用 to_thread 调用阻塞的 shutdown
            await asyncio.to_thread(self._shutdown_webui)
            yield event.plain_result(f"启动失败: {e}")

    @command_manager_group.command("off")
    async def stop_webui_command(self, event: AstrMessageEvent):
        """关闭指令管理后台"""
        if not self.webui_thread or not self.webui_thread.is_alive():
            yield event.plain_result("管理后台尚未启动。")
            return

        yield event.plain_result("正在关闭管理后台...")
        await asyncio.to_thread(self._shutdown_webui)
        yield event.plain_result("管理后台已成功关闭。")

    def _start_webui(self, config_obj) -> str:
        """启动 WebUI 子线程并返回临时密钥"""
        from . import webui

        host = config_obj.get("host", "0.0.0.0")
        port = int(config_obj.get("port", 5000))
        self.secret_key = secrets.token_hex(16)

        # 通过 uvicorn.Server 实现可控的服务器实例
        config = uvicorn.Config(
            app=webui.app, host=host, port=port, log_level="warning"
        )
        # 关键：在服务器运行前设置好 state
        webui.app.state.secret_key = self.secret_key

        self.webui_server = uvicorn.Server(config=config)

        # uvicorn.Server.run() 是一个同步阻塞方法，适合在线程中运行
        self.webui_thread = Thread(target=self.webui_server.run)
        self.webui_thread.start()

        return self.secret_key

    def _shutdown_webui(self):
        """优雅地关闭 WebUI 线程并释放端口"""
        if self.webui_server and self.webui_thread and self.webui_thread.is_alive():
            logger.info("正在发送关闭信号到 WebUI 服务器...")
            self.webui_server.should_exit = True
            # 等待线程执行完毕，即服务器完全关闭
            self.webui_thread.join(timeout=5)
            if self.webui_thread.is_alive():
                logger.warning("WebUI 线程未能优雅地在5秒内关闭。")
            else:
                logger.info("指令管理后台 WebUI 已成功关闭，端口已释放。")

        self.webui_thread = None
        self.webui_server = None

    async def _is_port_in_use(self, host: str, port: int) -> bool:
        """检查指定端口是否已被占用"""
        try:
            check_host = "127.0.0.1" if host == "0.0.0.0" else host
            reader, writer = await asyncio.wait_for(
                asyncio.open_connection(check_host, port), timeout=1.0
            )
            writer.close()
            await writer.wait_closed()
            return True
        except (ConnectionRefusedError, asyncio.TimeoutError):
            return False
        except Exception as e:
            logger.debug(f"检查端口占用时发生未知错误: {e}")
            return True
