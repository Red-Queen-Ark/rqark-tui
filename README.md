# rqark-tui

基於 [Textual](https://textual.textualize.io/) 的終端聊天客戶端，用於與 LLM 驅動的 coding agent 對話。

`rqark-tui` 只是介面層，實際的聊天引擎（provider 管理、session 儲存、串流、重試）由 [`rqark-app`](https://gitea.carhyme.top/RedQueenArk) 提供。

## 功能特色

- 串流式聊天：reasoning、Markdown 內容、tool call 與 tool result 即時顯示
- 內建三個 agent：Angel Holiday（含完整工具集）、Diana、Wednesday，可在執行中切換
- 每個專案目錄獨立 session：`~/.rqark/dir_cache.json` 記錄專案目錄 → session 對應，在同一專案重開即恢復上次對話
- 多 provider 設定（依 `priority` 排序），API 連續失敗 3 次自動 failover；`app.chat` 無限重試為設計行為，context 超長時自動摘要壓縮後續跑
- Thinking 區塊與 tool result 預設收合，可按 `▶` / `▼` 展開
- `/stop` 中斷時保留已收到的部分內容
- 滑鼠拖曳選取跨行文字；`Ctrl+C` 複製選取、`Ctrl+A` 全選、每則訊息右上 `[copy]` 按鈕整則複製（同時寫入 app 內部與系統剪貼簿）
- Agent plan 以浮動 popup 顯示進度（` ` 待辦 / `>` 進行中 / `x` 完成 / `-` 取消）
- 新 session 首則訊息送出後背景自動產生標題

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
├── dir_cache.json    # 專案目錄（cwd hash）→ session 對應
└── sessions/tui/     # 每 session 一個 .jsonl
```

`dir_cache.json` 以啟動時的所在目錄（cwd hash）為 key，故每個專案各自保留 session。

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

在相同專案目錄再次執行，會接續上次對話。

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

滑鼠操作：拖曳選取跨行文字、點 `[copy]` 複製整則訊息、點 `▶` / `▼` 展開或收合 thinking／tool result。

> macOS 終端（如 Terminal.app）若吞掉修飾鍵，程式會直接讀取實體鍵盤狀態，確保 `Shift/Ctrl+Enter` 仍可換行。

### 斜線指令

輸入 `/` 會帶出完成清單，`Enter` 立即執行。

| 指令 | 功能 |
| --- | --- |
| `/clear` | 清除目前對話（刪除 session 檔） |
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