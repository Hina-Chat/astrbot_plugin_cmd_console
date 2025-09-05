import threading
from typing import List, Dict, Optional, Callable

from pydantic import BaseModel

from astrbot.core.star.star_handler import (
    StarHandlerMetadata as StarHandler,
    star_handlers_registry,
)
from astrbot.core.star.star_handler import (
    StarHandlerRegistry,
    EventType,
)
from astrbot.core import sp, logger
from astrbot.core.star.star import star_map

# 1. 线程锁，确保全局状态修改的原子性
shared_data_lock = threading.Lock()


# 2. Pydantic 数据模型
class CommandInfo(BaseModel):
    handler_full_name: str
    plugin_name: str
    command: str
    description: Optional[str] = "无描述"
    activated: bool


class ToggleItem(BaseModel):
    handler_full_name: str


class TogglePluginItem(BaseModel):
    plugin_name: str
    activate: bool


# 3. 全局状态变量
_original_get_handlers_on_class: Optional[Callable] = None
disabled_handlers_set: set[str] = set()
INACTIVATED_COMMANDS_KEY = "inactivated_command_handlers"


# 4. 猴子补丁核心逻辑
def _patched_get_handlers_on_class(
    self,
    event_type: EventType,
    only_activated=True,
    plugins_name: list[str] | None = None,
) -> list[StarHandler]:
    """我们注入的补丁函数，在类级别上替换原始方法"""
    # 首先，调用原始的、未绑定的函数，并手动传入 self
    original_handlers = _original_get_handlers_on_class(
        self,
        event_type,
        only_activated=only_activated,
        plugins_name=plugins_name,
    )

    # 如果没有禁用的指令，直接返回原始列表，提高性能
    if not disabled_handlers_set:
        return original_handlers

    # 过滤掉被禁用的指令
    with shared_data_lock:
        active_handlers = [
            handler
            for handler in original_handlers
            if handler.handler_full_name not in disabled_handlers_set
        ]

    return active_handlers


def apply_patch():
    """在类级别应用猴子补丁，并备份原始方法"""
    global _original_get_handlers_on_class
    if _original_get_handlers_on_class is None:
        # 从类本身备份原始函数
        _original_get_handlers_on_class = StarHandlerRegistry.get_handlers_by_event_type
        # 在类本身上替换为我们的补丁函数
        StarHandlerRegistry.get_handlers_by_event_type = _patched_get_handlers_on_class
        logger.info("指令管理器：已成功应用猴子补丁到 StarHandlerRegistry CLASS。")


def remove_patch():
    """移除类级别的猴子补丁，恢复原始方法"""
    global _original_get_handlers_on_class
    if _original_get_handlers_on_class is not None:
        # 在类本身上恢复原始函数
        StarHandlerRegistry.get_handlers_by_event_type = _original_get_handlers_on_class
        _original_get_handlers_on_class = None
        logger.info("指令管理器：已成功移除类级猴子补丁，系统已恢复。")


# 5. 插件业务逻辑
def initialize_disabled_commands():
    """从持久化存储中加载已禁用的指令列表，并应用补丁"""
    with shared_data_lock:
        inactivated_list = sp.get(INACTIVATED_COMMANDS_KEY, [])
        global disabled_handlers_set
        disabled_handlers_set = set(inactivated_list)

    apply_patch()
    if disabled_handlers_set:
        logger.info(f"成功恢复 {len(disabled_handlers_set)} 个已禁用的指令状态。")


def get_all_commands() -> List[CommandInfo]:
    """获取所有已注册的指令信息，包括已禁用的"""
    from astrbot.core.star.filter.command import CommandFilter
    from astrbot.core.star.filter.command_group import CommandGroupFilter

    all_commands_map: Dict[str, CommandInfo] = {}

    # 我们不再需要合并两个列表，直接从全局注册表中获取所有指令
    all_handlers = list(star_handlers_registry)

    with shared_data_lock:
        for handler in all_handlers:
            is_activated = handler.handler_full_name not in disabled_handlers_set

            command_filters = [
                f
                for f in handler.event_filters
                if isinstance(f, (CommandFilter, CommandGroupFilter))
            ]
            if not command_filters:
                continue

            command_parts = []
            for f in command_filters:
                if isinstance(f, CommandGroupFilter):
                    all_names = f.get_complete_command_names()
                    command_parts.extend(all_names)
                elif isinstance(f, CommandFilter):
                    all_names = []
                    base_names = [f.command_name] + list(f.alias)
                    for parent in f.parent_command_names:
                        for base in base_names:
                            if parent:
                                all_names.append(f"{parent.strip()} {base.strip()}")
                            else:
                                all_names.append(base.strip())
                    command_parts.extend(all_names)

            command_str = ", ".join(sorted(list(set(command_parts))))
            if not command_str:
                continue

            plugin_metadata = star_map.get(handler.handler_module_path)
            plugin_name = plugin_metadata.name if plugin_metadata else "未知插件"

            all_commands_map[handler.handler_full_name] = CommandInfo(
                handler_full_name=handler.handler_full_name,
                plugin_name=plugin_name,
                command=command_str,
                description=handler.desc.strip() or "无描述",
                activated=is_activated,
            )

    final_list = list(all_commands_map.values())
    final_list.sort(key=lambda x: (x.plugin_name, x.command))
    return final_list


def toggle_command(item: ToggleItem):
    """切换指令的启用/禁用状态"""
    with shared_data_lock:
        handler_full_name = item.handler_full_name

        if handler_full_name in disabled_handlers_set:
            disabled_handlers_set.remove(handler_full_name)
            logger.info(f"指令 '{handler_full_name}' 已被重新启用。")
        else:
            disabled_handlers_set.add(handler_full_name)
            logger.info(f"指令 '{handler_full_name}' 已被禁用。")

        # 持久化变更
        sp.put(INACTIVATED_COMMANDS_KEY, list(disabled_handlers_set))

    return {"status": "ok"}


def toggle_plugin_commands(item: TogglePluginItem):
    """启用或禁用某个插件下的所有指令"""
    with shared_data_lock:
        all_handlers = list(star_handlers_registry)
        handlers_to_modify = {
            handler.handler_full_name
            for handler in all_handlers
            if star_map.get(handler.handler_module_path)
            and star_map.get(handler.handler_module_path).name == item.plugin_name
        }

        if not handlers_to_modify:
            logger.warning(
                f"尝试切换不存在的插件 '{item.plugin_name}' 的指令，或该插件下无指令。"
            )
            return {
                "status": "not_found",
                "message": f"Plugin '{item.plugin_name}' not found or has no commands.",
            }

        if item.activate:
            disabled_handlers_set.difference_update(handlers_to_modify)
            logger.info(f"插件 '{item.plugin_name}' 的所有指令已被启用。")
        else:
            disabled_handlers_set.update(handlers_to_modify)
            logger.info(f"插件 '{item.plugin_name}' 的所有指令已被禁用。")

        sp.put(INACTIVATED_COMMANDS_KEY, list(disabled_handlers_set))

    return {"status": "ok"}
