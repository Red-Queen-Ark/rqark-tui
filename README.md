# rqark-tui

基於 [Textual](https://textual.textualize.io/) 的終端聊天客戶端，用於與 LLM 驅動的 coding agent 對話。

`rqark-tui` 只是介面層，實際的聊天引擎（provider 管理、session 儲存、串流、重試）由 [`rqark-app`](https://gitea.carhyme.top/RedQueenArk) 提供。

## 功能特色

- 串流式聊天：reasoning、Markdown 內容、tool call 與 tool result 即時顯示
- agent 由 `~/.rqark/agents/*.yml` 定義（人格、prompt、工具），首次執行會用內建三個預設（Angel Holiday、Diana、Wednesday）填入該目錄；可在執行中用 `/agents` 切換
- 每個專案目錄獨立 session：`~/.rqark/dir_caches.json` 記錄專案目錄 → session 對應，在同一專案重開即恢復上次對話
- 多 provider 設定（依 `priority` 排序），API 連續失敗 3 次自動 failover；`app.chat` 無限重試為設計行為，context 超長時自動摘要壓縮後續跑
- Thinking 區塊與 tool result 預設收合，可按 `▶` / `▼` 展開
- `/stop` 中斷時保留已收到的部分內容
- 滑鼠拖曳選取跨行文字；`Ctrl+C` 複製選取、`Ctrl+A` 全選、每則訊息右上 `[copy]` 按鈕整則複製（同時寫入 app 內部與系統剪貼簿）
- 多個 session 同時運行：每條 session 有自己的訊息窗、worker 同 transcript，切 tab 即可望返另一條嘅即時進度，互不阻塞
- Agent plan 以浮動 popup 顯示進度（` ` 待辦 / `>` 進行中 / `x` 完成 / `-` 取消），只顯示目前 session 嘅 plan
- Subagent 輸出留在所屬 session 內，以 `Agent - <id>` 分塊顯示
- 新 session 首則訊息送出後背景自動產生標題（標題會顯示在 tab 上）

## 安裝

需要 Python ≥ 3.14。`rqark-tui` 及其依賴 `rqark-app`、`rqark-core` 只發布在私有 Gitea PyPI registry，安裝時需指定該 index：

```bash
uv tool install rqark-tui --index https://gitea.carhyme.top/api/packages/RedQueenArk/pypi/simple
```

或加入專案：

```bash
uv add rqark-tui --index https://gitea.carhyme.top/api/packages/RedQueenArk/pypi/simple
```

pip 亦可（`--extra-index-url`）：

```bash
pip install rqark-tui --extra-index-url https://gitea.carhyme.top/api/packages/RedQueenArk/pypi/simple
```

## 設定

設定集中在使用者家目錄的 `~/.rqark/`（跨專案共用，不會污染各專案目錄）：

```text
~/.rqark/
├── providers.yml      # provider 清單（不存在時自動建立空白範本）
├── agents/            # 每個 agent 一個 .yml（不存在時用內建預設填入）
├── dir_caches.json    # 專案目錄（cwd hash）→ session 對應
└── sessions/tui/      # 每 session 一個 .jsonl
```

`dir_caches.json` 以啟動時的所在目錄（cwd hash）為 key，故每個專案各自保留 session。

`agents/*.yml` 範例（`name` 用大駝峰類名，tool 名稱見 `rqark-core` 的 `TOOLS` 表；`params` 視 tool 而定）：

```yaml
name: Diana
description: ''
prompts:
- name: RolePrompt
  params:
    agent_name: Diana
    user_name: Sir
tools:
- name: Gitea
  params:
    username: diana
    token: '...'
    base_url: https://gitea.example
- name: WebSearch
```

改完 `agents/*.yml` 要重開程式才生效；`/agents` 只會在已載入的 agent 之間切換。因為 YAML 直接存到本機，內含 token 的 agent 檔建議 `chmod 600`（`~/.rqark` 本身不在任何 repo 內）。

`providers.yml` 範例：

```yaml
- name: inhouse
  model_name: gemma4:e4b-mlx
  api_key: '-'
  api_base: http://127.0.0.1:11434/v1
  priority: 1

- model_name: deepseek-v4-flash
  api_key: sk-xxxx
  api_base: https://api.deepseek.com
  priority: 3
```

可用欄位：`name`、`model_name`、`api_key`、`api_base`、`priority`（小者優先），以及選擇性的 `reasoning_effort`、`thinking`、`temperature`、`top_p`、`seed`、`frequency_penalty`、`presence_penalty`、`combine`。provider 依 `priority` 升序使用，失敗自動輪替。

## 使用

```bash
rqark-tui
```

在相同專案目錄再次執行，會接返該目錄記住嘅所有對話（每條開一個 tab，最近用過嘅排最前，畫面顯示第一條）。

畫面由上至下：header（agent / model / 標題）、session tab、訊息窗、popup（plan 或選單，需要時才出現）、輸入框。

```text
<header>
<session tab>   [Session 1] [Session 2] [+]
<main>
<popup>
<footer>
```

### 多個 session

- 點 `+`（或輸入 `/new`）開一條新 session；每條 session 各自有訊息紀錄、進行中的回應同輸入草稿
- 切 tab 只換上面嘅訊息窗，背景 session 照樣繼續串流，切返去就見到完整內容
- 正在回應嘅 session，tab 會變黃色；該 session 未完成前唔可以再送訊息（其他 session 不受影響）
- `/stop`、`/clear`、`/close` 只作用於目前 session
- 移除 session 有兩種方法，效果一樣：點 tab 上面嘅 `×`、或輸入 `/close`；兩者都會先彈確認 dialog（`Enter`/`Esc` 取消、`Ctrl+E` 確認、或直接點按鈕）
- 確認後會終止該 session 進行中嘅回應，再刪除它嘅對話紀錄（之後無法復原）；最後一條 session 唔可以關（要清空就用 `/clear`），因為畫面永遠要有一條 session
- 關掉程式再喺同一目錄開返，之前嘅 session 會逐條還原成 tab；已經刪咗嘅則唔會再還原

### 快捷鍵

| 按鍵 | 功能 |
| --- | --- |
| `Enter` | 送出訊息 |
| `Shift+Enter`（或 `Ctrl+Enter`、`Ctrl+J`） | 換行 |
| `Ctrl+C` | 複製選取範圍（未選取時）／複製訊息面板選取 |
| `Ctrl+A` | 於訊息面板全選 |
| `Ctrl+E` | 離開（再次按或 `Enter` 於 Quit 確認） |
| `Esc` × 3 | 離開（同上，會先跳出確認） |
| `Tab` / `↑` / `↓` | popup 中移動選項 |
| `Esc` | 關閉 popup / 取消 |

滑鼠操作：拖曳選取跨行文字、點 `[copy]` 複製整則訊息、點 `▶` / `▼` 展開或收合 thinking／tool result、點 session tab 切換 session、點 `+` 開新 session、點 tab 上嘅 `×` 關閉該 session。

> macOS 終端（如 Terminal.app）若吞掉修飾鍵，程式會直接讀取實體鍵盤狀態，確保 `Shift/Ctrl+Enter` 仍可換行。

### 斜線指令

輸入 `/` 會帶出完成清單，`Enter` 立即執行。

| 指令 | 功能 |
| --- | --- |
| `/clear` | 清除目前對話（刪除 session 檔，保留 tab） |
| `/close` | 關閉目前 session（確認後刪除 session 檔並收起 tab） |
| `/compact` | 將目前對話壓縮成一段 summary（壓縮期間顯示 `Compacting…`，之後只帶 summary 同新訊息續聊） |
| `/new` | 開一條新 session（同點 `+` 一樣） |
| `/stop` | 停止目前回應（已收到的部分內容會存下） |
| `/models` | 切換 model（picker 顯示目前可用 provider） |
| `/agents` | 切換 agent |

回應進行中會擋下一般訊息（顯示 "Still processing — please wait"），但斜線指令不受限制，`/stop` 即逃生門。

## 開發

```bash
uv sync
uv run rqark-tui        # 直接執行
uv run ruff check --fix
uv run ty check --fix
uv run pyright          # 輔助確認 type safety
uv run mypy
```

規格：Python ≥ 3.14、ruff line-length 240、單引號風格、型別檢查以 `ruff` + `ty` 為主。