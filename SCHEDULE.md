# 自動排程設定指南

台股新聞 AI 情緒追蹤器支援透過系統排程自動執行 `run_pipeline.py`。
本文件提供 **cron**（簡單快速）與 **launchd**（macOS 原生，開機自動啟動）兩種方案。

---

## 快速開始：確認手動執行正常

在設定排程前，請先確認手動執行沒有問題：

```bash
cd ~/Desktop/stock_sentiment

# Mock 模式（不消耗 API）
python3 run_pipeline.py --mock

# Claude 模式（需要 ANTHROPIC_API_KEY）
export ANTHROPIC_API_KEY="sk-ant-..."
python3 run_pipeline.py --claude
```

---

## 方案一：cron（推薦初學者）

### 設定步驟

```bash
# 開啟 crontab 編輯器
crontab -e
```

加入以下任一排程（選一個適合你的）：

```cron
# ── 每天早上 8:00 執行（Mock 模式）──────────────────────────────
0 8 * * * cd ~/Desktop/stock_sentiment && /usr/bin/python3 run_pipeline.py --mock >> ~/Desktop/stock_sentiment/logs/pipeline.log 2>&1

# ── 每天早上 8:00 執行（Claude 模式）────────────────────────────
0 8 * * * cd ~/Desktop/stock_sentiment && ANTHROPIC_API_KEY="sk-ant-你的金鑰" /usr/bin/python3 run_pipeline.py --claude >> ~/Desktop/stock_sentiment/logs/pipeline.log 2>&1

# ── 每 4 小時執行一次（Mock 模式）───────────────────────────────
0 */4 * * * cd ~/Desktop/stock_sentiment && /usr/bin/python3 run_pipeline.py --mock >> ~/Desktop/stock_sentiment/logs/pipeline.log 2>&1

# ── 台股交易日（週一到週五）早上 8:30 執行 ─────────────────────
30 8 * * 1-5 cd ~/Desktop/stock_sentiment && /usr/bin/python3 run_pipeline.py --mock >> ~/Desktop/stock_sentiment/logs/pipeline.log 2>&1
```

### 建立 logs 資料夾

```bash
mkdir -p ~/Desktop/stock_sentiment/logs
```

### cron 語法說明

```
分  時  日  月  星期  指令
0   8   *   *   *     ...

*   = 每個
*/4 = 每 4 個
1-5 = 星期一到星期五
```

### 確認排程已生效

```bash
crontab -l          # 列出所有排程
tail -f ~/Desktop/stock_sentiment/logs/pipeline.log   # 即時查看 log
```

### 移除排程

```bash
crontab -e          # 刪除對應那行，存檔即可
```

---

## 方案二：launchd（macOS 原生，開機自啟）

launchd 是 macOS 的系統級排程工具，比 cron 更可靠，支援開機自動啟動且不依賴終端機保持開啟。

### 步驟 1：建立設定檔

```bash
mkdir -p ~/Library/LaunchAgents
```

建立 `~/Library/LaunchAgents/com.stock_sentiment.pipeline.plist`：

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <!-- 唯一識別名稱，不要與其他 agent 重複 -->
    <key>Label</key>
    <string>com.stock_sentiment.pipeline</string>

    <!-- 執行指令與參數 -->
    <key>ProgramArguments</key>
    <array>
        <string>/usr/bin/python3</string>
        <string>/Users/你的使用者名稱/Desktop/stock_sentiment/run_pipeline.py</string>
        <string>--mock</string>
        <!-- 若要 Claude 模式，把 --mock 改成 --claude -->
    </array>

    <!-- 工作目錄 -->
    <key>WorkingDirectory</key>
    <string>/Users/你的使用者名稱/Desktop/stock_sentiment</string>

    <!-- 環境變數（Claude 模式需要） -->
    <key>EnvironmentVariables</key>
    <dict>
        <key>ANTHROPIC_API_KEY</key>
        <string>sk-ant-你的金鑰（Mock 模式可省略這段）</string>
    </dict>

    <!-- 排程：每天 08:00 執行 -->
    <key>StartCalendarInterval</key>
    <dict>
        <key>Hour</key>
        <integer>8</integer>
        <key>Minute</key>
        <integer>0</integer>
    </dict>

    <!-- Log 輸出 -->
    <key>StandardOutPath</key>
    <string>/Users/你的使用者名稱/Desktop/stock_sentiment/logs/pipeline.log</string>
    <key>StandardErrorPath</key>
    <string>/Users/你的使用者名稱/Desktop/stock_sentiment/logs/pipeline_err.log</string>

    <!-- 失敗時不要重試（避免無限循環） -->
    <key>ThrottleInterval</key>
    <integer>300</integer>
</dict>
</plist>
```

> ⚠️ 請把所有 `你的使用者名稱` 替換為你的 macOS 帳號名稱（執行 `whoami` 查看）

### 步驟 2：載入 agent

```bash
# 建立 logs 資料夾
mkdir -p ~/Desktop/stock_sentiment/logs

# 載入（啟用）排程
launchctl load ~/Library/LaunchAgents/com.stock_sentiment.pipeline.plist

# 確認已載入
launchctl list | grep stock_sentiment
```

### 步驟 3：手動觸發測試

```bash
launchctl start com.stock_sentiment.pipeline

# 查看輸出
tail -f ~/Desktop/stock_sentiment/logs/pipeline.log
```

### 管理指令

```bash
# 停用排程
launchctl unload ~/Library/LaunchAgents/com.stock_sentiment.pipeline.plist

# 重新載入（修改 plist 後執行）
launchctl unload ~/Library/LaunchAgents/com.stock_sentiment.pipeline.plist
launchctl load   ~/Library/LaunchAgents/com.stock_sentiment.pipeline.plist

# 查看執行狀態（0 = 正常，非 0 = 上次有錯）
launchctl list com.stock_sentiment.pipeline
```

### 每 4 小時執行（launchd 版本）

把 `StartCalendarInterval` 改為陣列：

```xml
<key>StartCalendarInterval</key>
<array>
    <dict><key>Hour</key><integer>8</integer><key>Minute</key><integer>0</integer></dict>
    <dict><key>Hour</key><integer>12</integer><key>Minute</key><integer>0</integer></dict>
    <dict><key>Hour</key><integer>16</integer><key>Minute</key><integer>0</integer></dict>
    <dict><key>Hour</key><integer>20</integer><key>Minute</key><integer>0</integer></dict>
</array>
```

---

## 查看執行紀錄

每次 pipeline 執行後，結果會同時寫入：

1. **Log 檔案**（文字）
   ```bash
   tail -50 ~/Desktop/stock_sentiment/logs/pipeline.log
   ```

2. **SQLite `pipeline_runs` 表**（可在 Dashboard 查看）
   ```bash
   sqlite3 ~/Desktop/stock_sentiment/data/news.db \
     "SELECT ran_at, mode, inserted, analyzed, duration_sec FROM pipeline_runs ORDER BY ran_at DESC LIMIT 5;"
   ```

3. **Streamlit Dashboard** sidebar 的「Pipeline 狀態」區塊（自動更新）

---

## 執行指令速查

```bash
# 統一入口（推薦）
python3 run_pipeline.py --mock              # 不呼叫 API，適合測試與排程
python3 run_pipeline.py --claude            # 呼叫 Claude API
python3 run_pipeline.py --mock --crawl-only # 只爬蟲不分析
python3 run_pipeline.py --mock --analysis-limit 50  # 指定分析上限

# 查看 Dashboard
streamlit run web/app.py

# 舊版獨立腳本（仍可使用）
python3 pipeline/save_cnyes_to_db.py
python3 pipeline/save_yahoo_tw_to_db.py
python3 pipeline/analyze_sentiment.py --mock
```

---

## 新增爬蟲來源（擴充說明）

只需兩步，不需修改任何既有程式碼：

1. **建立新爬蟲**，繼承 `BaseCrawler`，設定 `source = "新來源名稱"`

2. **在 `run_pipeline.py` 頂端的 `CRAWLERS` 清單加一行**：
   ```python
   CRAWLERS: list[tuple[type, dict]] = [
       (CnyesCrawler,   {"limit": 30}),
       (YahooTwCrawler, {}),
       (你的新爬蟲,      {"param": "value"}),  # ← 加這行
   ]
   ```

主流程 `run_crawlers()` 完全不需要修改。
