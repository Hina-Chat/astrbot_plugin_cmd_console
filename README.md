# 指令控制器 (Command Manager)

一个为 AstrBot 设计的 WebUI 指令管理插件，允许管理员动态启用或禁用机器人中的任何指令。

---

Powered by Claude 4s & Gemini 2.5 Pro, All.

在 AI 時代，每一個人都擁有了編寫簡易程式的能力。

魔法，令人難以置信。 : )


## ⚠️ 维护与兼容性说明

- **官方支持**: AstrBot 未来版本计划提供官方的指令管理功能，届时本插件将被淘汰。
- **兼容性警告**: 本插件的核心功能与 AstrBot 框架的内部实现紧密耦合。若未来 AstrBot 更新其指令注册机制，可能导致本插件失效。
- **灵感来源**: WebUI 的安全验证设计灵感来自 [Meme Manager](https://github.com/anka-afk/astrbot_plugin_meme_manager)。

## ✨ 功能特性

- **WebUI 面板**: 通过网页界面，集中查看所有已注册的插件指令。
- **即时控制**: 一键启用或禁用任何指令，变更立即生效。
- **状态持久化**: 禁用状态会被自动保存，即使 AstrBot 重启，设置也不会丢失。
- **安全访问**: WebUI 设有安全验证，只有管理员才能访问和操作。
- **轻量高效**: 采用 FastAPI 和独立线程运行，对主程序性能影响极小。

## 🚀 安装与设置

1.  下載 Code 為 ZIP；
2.  插件管理 - 安裝插件，選擇下載的 ZIP

## 🛠️ 使用说明

### 指令列表

- `/cmdmgr on` (别名: `/指令管理 on`)
  - **权限**: 管理员
  - **功能**: 启动 WebUI 管理控制台。成功后，Bot 将通过私信发送**一次性**的登录令牌 (Token)。

- `/cmdmgr off` (别名: `/指令管理 off`)
  - **权限**: 管理员
  - **功能**: 关闭正在运行的 WebUI 管理控制台，释放网络端口。

### WebUI 操作流程

1.  对机器人发送 `/cmdmgr on` 指令。
2.  从机器人的私信中，获取一次性的访问令牌。
3.  在浏览器中打开 `http://[主机]:[5000]/`，输入令牌进行登录。
4.  登录成功后，您将看到包含所有指令的列表，上面清晰地标明了指令名称、所属插件以及当前的启用状态。
5.  点击每个指令旁的开关，即可实时启用或禁用该指令。

## ⚙️ 配置选项

本插件的 WebUI 服务器默认使用 `5000` 端口。如需修改，请直接编辑 `main.py` 文件中的 `_start_webui` 方法。

## 🔬 技术实现

本插件采用职责分离的架构设计：

- `main.py`: 总控制器，负责响应管理员指令，并管理 WebUI 后台的生命周期。
- `logic.py`: 插件的核心，通过非侵入式的猴子补丁技术，实现指令的动态禁用与启用。
- `webui.py`: 基于 FastAPI 的 Web 后端，提供安全的 API 接口供前端页面调用。

<details>
<summary><strong>点此展开：核心设计演进历程</strong></summary>

### 背景：从侵入式修改到非侵入式补丁

本插件的核心功能（禁用/启用指令）经过了一次重要的技术重构，从一个有状态、具侵入性的设计，演进为一个无状态、非侵入式且生命周期安全的设计。这确保了插件在被卸载后，不会对 AstrBot 的核心状态造成任何永久性的污染。

#### 1. 旧有设计（已废弃）

最初的实现方式是直接修改 AstrBot 的全局指令注册表 `star_handlers_registry`：
- **禁用**: 从 `star_handlers_registry._handlers` 列表中移除指定的指令处理器，并将其备份到一个本地缓存。
- **启用**: 从本地缓存中取回指令处理器，并将其重新添加回 `star_handlers_registry._handlers` 列表。

**缺陷**: 这种方法存在一个致命的生命周期问题。如果插件在禁用某些指令后被停用或卸载，由于清理逻辑未能正确执行，那些被移除的指令将**永久失效**，除非重启整个 AstrBot 服务。这是一种对核心状态的直接且危险的修改。

#### 2. 当前设计：非侵入式猴子补丁

为了解决上述问题，我们借鉴了 `gemini_patcher` 插件的成功经验，采用了**猴子补丁 (Monkey Patching)** 技术，在不修改任何核心数据结构的前提下，动态地改变系统行为。

**核心思路**: 我们不再修改 `star_handlers_registry` 的内容，而是去“拦截”AstrBot 获取指令列表的行为。我们选择的拦截点是 `astrbot.core.star.star_handler.StarHandlerRegistry` 类中的 `get_handlers_by_event_type` 方法，这是 AstrBot 指令分发流程的关键。

**补丁逻辑 (`logic.py`)**

1.  **状态管理**: 维护一个全局 `set` (`disabled_handlers_set`)，仅用于存储被禁用指令的唯一名称 (`handler_full_name`)。

2.  **补丁函数 `_patched_get_handlers_on_class`**:
    a. 调用原始的 `get_handlers_by_event_type` 方法，获取一份**完整的、未经修改的**指令列表。
    b. 根据 `disabled_handlers_set` 过滤掉所有被禁用的指令。
    c. 返回一个临时的、过滤后的新列表给调用方。

3.  **生命周期管理**:
    - **应用补丁 (`apply_patch`)**: 在插件初始化时，将 `StarHandlerRegistry.get_handlers_by_event_type` 替换为我们的补丁函数，并备份原始方法。
    - **移除补丁 (`remove_patch`)**: 在插件终止时，将备份的原始方法恢复到 `StarHandlerRegistry` 类上，使系统完美恢复到原始状态。

#### 3. 技术挑战：实例补丁 vs. 类补丁

- **失败的尝试**: 最初尝试在 `star_handlers_registry` 这个**实例 (instance)** 上应用补丁，导致 `TypeError` (丢失 `self` 参数)，因为 AstrBot 内部的调用方式绕过了标准的实例方法绑定机制。

- **最终方案**: 采用更稳健的**类级别补丁**。直接修改 `StarHandlerRegistry` 这个**类 (class)** 的方法定义，确保**所有**该类的实例在调用此方法时，都能正确地接收到 `self` 参数，从而根本上解决了问题。

```python
# logic.py - 最终的补丁应用逻辑
def apply_patch():
    global _original_get_handlers_on_class
    if _original_get_handlers_on_class is None:
        # 从类本身备份原始函数
        _original_get_handlers_on_class = StarHandlerRegistry.get_handlers_by_event_type
        # 在类本身上替换为我们的补丁函数
        StarHandlerRegistry.get_handlers_by_event_type = _patched_get_handlers_on_class
```

### 结论

目前的实现是健壮、安全且可维护的。它完美地实现了动态指令管理的功能，同时遵循了非侵入式设计的最佳实践，确保了插件的独立性和系统的整体稳定性。

</details>
