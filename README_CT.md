# 指令控制器 (Command Manager)

一個為 AstrBot 設計的 WebUI 指令管理插件，允許管理員動態啟用或禁用機器人中的任何指令。

---

Powered by Gemini 2.5 Pro, All.

在 AI 時代，每一個人都擁有了編寫簡易程式的能力。

魔法，令人難以置信。 : )


## ⚠️ 維護與相容性說明

- **官方支援**: AstrBot 未來版本計畫提供官方的指令管理功能，屆時本插件將被淘汰。
- **相容性警告**: 本插件的核心功能與 AstrBot 框架的內部實現緊密耦合。若未來 AstrBot 更新其指令註冊機制，可能導致本插件失效。
- **靈感來源**: WebUI 的安全驗證設計靈感來自 [Meme Manager](https://github.com/anka-afk/astrbot_plugin_meme_manager)。

## ✨ 功能特性

- **WebUI 面板**: 透過網頁介面，集中查看所有已註冊的插件指令。
- **即時控制**: 一鍵啟用或禁用任何指令，變更立即生效。
- **狀態持久化**: 禁用狀態會被自動儲存，即使 AstrBot 重啟，設定也不會遺失。
- **安全存取**: WebUI 設有安全驗證，只有管理員才能存取和操作。
- **輕量高效**: 採用 FastAPI 和獨立執行緒運行，對主程式效能影響極小。

## 🚀 安裝與設定

1.  將 `astrbot_plugin_command_manager` 資料夾放入 AstrBot 的 `plugins` 目錄下。
2.  安裝所需的依賴套件：
    ```bash
    pip install -r requirements.txt
    ```

## 🛠️ 使用說明

### 指令列表

- `/cmdmgr on` (別名: `/指令管理 on`)
  - **權限**: 管理員
  - **功能**: 啟動 WebUI 管理主控台。成功後，Bot 將透過私訊傳送**一次性**的登入權杖 (Token)。

- `/cmdmgr off` (別名: `/指令管理 off`)
  - **權限**: 管理員
  - **功能**: 關閉正在運行的 WebUI 管理主控台，釋放網路連接埠。

### WebUI 操作流程

1.  對機器人發送 `/cmdmgr on` 指令。
2.  從機器人的私訊中，取得一次性的存取權杖。
3.  在瀏覽器中開啟 `http://[主機]:[5000]/`，輸入權杖進行登入。
4.  登入成功後，您將看到包含所有指令的列表，上面清晰地標明了指令名稱、所屬插件以及目前的啟用狀態。
5.  點擊每個指令旁的開關，即可即時啟用或禁用該指令。

## ⚙️ 配置選項

本插件的 WebUI 伺服器預設使用 `5000` 連接埠。如需修改，請直接編輯 `main.py` 檔案中的 `_start_webui` 方法。

## 🔬 技術實現

本插件採用職責分離的架構設計：

- `main.py`: 總控制器，負責回應管理員指令，並管理 WebUI 後台的生命週期。
- `logic.py`: 插件的核心，透過非侵入式的猴子補丁技術，實現指令的動態禁用與啟用。
- `webui.py`: 基於 FastAPI 的 Web 後端，提供安全的 API 介面供前端頁面呼叫。

<details>
<summary><strong>點此展開：核心設計演進歷程</strong></summary>

### 背景：從侵入式修改到非侵入式補丁

本插件的核心功能（禁用/啟用指令）經過了一次重要的技術重構，從一個有狀態、具侵入性的設計，演進為一個無狀態、非侵入式且生命週期安全的設計。這確保了插件在被卸載後，不會對 AstrBot 的核心狀態造成任何永久性的污染。

#### 1. 舊有設計（已廢棄）

最初的實現方式是直接修改 AstrBot 的全域指令註冊表 `star_handlers_registry`：
- **禁用**: 從 `star_handlers_registry._handlers` 列表中移除指定的指令處理器，並將其備份到一個本地快取。
- **啟用**: 從本地快取中取回指令處理器，並將其重新添加回 `star_handlers_registry._handlers` 列表。

**缺陷**: 這種方法存在一個致命的生命週期問題。如果插件在禁用某些指令後被停用或卸載，由於清理邏輯未能正確執行，那些被移除的指令將**永久失效**，除非重啟整個 AstrBot 服務。這是一種對核心狀態的直接且危險的修改。

#### 2. 當前設計：非侵入式猴子補丁

為了解決上述問題，我們借鑒了 `gemini_patcher` 插件的成功經驗，採用了**猴子補丁 (Monkey Patching)** 技術，在不修改任何核心資料結構的前提下，動態地改變系統行為。

**核心思路**: 我們不再修改 `star_handlers_registry` 的內容，而是去「攔截」AstrBot 獲取指令列表的行為。我們選擇的攔截點是 `astrbot.core.star.star_handler.StarHandlerRegistry` 類別中的 `get_handlers_by_event_type` 方法，這是 AstrBot 指令分發流程的關鍵。

**補丁邏輯 (`logic.py`)**

1.  **狀態管理**: 維護一個全域 `set` (`disabled_handlers_set`)，僅用於儲存被禁用指令的唯一名稱 (`handler_full_name`)。

2.  **補丁函式 `_patched_get_handlers_on_class`**:
    a. 呼叫原始的 `get_handlers_by_event_type` 方法，獲取一份**完整的、未經修改的**指令列表。
    b. 根據 `disabled_handlers_set` 過濾掉所有被禁用的指令。
    c. 返回一個臨時的、過濾後的新列表給呼叫方。

3.  **生命週期管理**:
    - **應用補丁 (`apply_patch`)**: 在插件初始化時，將 `StarHandlerRegistry.get_handlers_by_event_type` 替換為我們的補丁函式，並備份原始方法。
    - **移除補丁 (`remove_patch`)**: 在插件終止時，將備份的原始方法恢復到 `StarHandlerRegistry` 類別上，使系統完美恢復到原始狀態。

#### 3. 技術挑戰：實例補丁 vs. 類別補丁

- **失敗的嘗試**: 最初嘗試在 `star_handlers_registry` 這個**實例 (instance)** 上應用補丁，導致 `TypeError` (遺失 `self` 參數)，因為 AstrBot 內部的呼叫方式繞過了標準的實例方法綁定機制。

- **最終方案**: 採用更穩健的**類別級別補丁**。直接修改 `StarHandlerRegistry` 這個**類別 (class)** 的方法定義，確保**所有**該類別的實例在呼叫此方法時，都能正確地接收到 `self` 參數，從而根本上解決了問題。

```python
# logic.py - 最終的補丁應用邏輯
def apply_patch():
    global _original_get_handlers_on_class
    if _original_get_handlers_on_class is None:
        # 從類別本身備份原始函式
        _original_get_handlers_on_class = StarHandlerRegistry.get_handlers_by_event_type
        # 在類別本身上替換為我們的補丁函式
        StarHandlerRegistry.get_handlers_by_event_type = _patched_get_handlers_on_class
```

### 結論

目前的實現是健壯、安全且可維護的。它完美地實現了動態指令管理的功能，同時遵循了非侵入式設計的最佳實踐，確保了插件的獨立性和系統的整體穩定性。

</details>