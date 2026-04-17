# 技术实现说明

本文档记录项目的内部技术细节，供开发者参考。

---

## 目录结构

```text
README.md                  # 说明
src/
  ccgp_collect.py          # 一次执行两个入口（地方+中央）并清理过期附件
  ccgp/
    main.py                # 核心采集流程与 CLI 入口
    parse_index.py         # 列表页解析
    parse_detail.py        # 详情页解析 + 附件链接提取
    tools.py               # HTTP/时间/关键词/CSV/附件处理等工具
    config.py              # 采集参数、关键词、字段别名、路径等配置
    model.py               # TenderItem 数据结构
    llm_requirements.py    # LLM 需求摘要生成
    data/
      tender_items.csv     # 输出文件
      logs/                # 运行日志
      attachments/         # 附件下载目录
  utils/
    mylogger.py            # 日志初始化
docs/
  index.html               # GitHub Pages 静态页面
  assets/                  # 前端脚本与样式
```

---

## 运行环境

- Python 3.10+
- Windows / Linux / macOS 均可

安装依赖：

```bash
pip install -r requirements.txt
```

（`requirements.txt` 已包含 `openai`、`PyPDF2`、`python-docx`、`openpyxl` 等全部所需依赖。）

---

## 配置项（`src/ccgp/config.py`）

核心配置：

- `DAYS` / `PAGES`：默认采集范围
- `FILTER_KEYWORDS`：命中关键词
- `FILTER_EXCLUDE_KEYWORDS`：排除干扰词
- `FIELD_ALIASES`：详情页字段别名映射（适配不同公告模板）
- `ENABLE_READ_ATTACHMENTS`：是否下载并解析附件
- `ENABLE_LLM_REQUIREMENTS`：是否调用 LLM 生成需求摘要
- `ATTACHMENTS_DIR`：附件目录
- `CSV_OUTPUT_DIR`：CSV 输出路径
- `LOGGING_DIR` / `LOGGING_LEVEL`：日志路径与级别

关键词配置示例：

```python
# 关键词（待增删）
FILTER_KEYWORDS = [
    "工业互联网", "智能制造", "智能", "智慧",
    "人工智能", "AI", "大模型",
    "大数据", "数据治理", "数据中台",
    "机器人", "机器视觉", "自动化",
    "云计算", "算力", "边缘计算",
    "物联网", "5G",
]

# 干扰词汇(待补充)
FILTER_EXCLUDE_KEYWORDS = [
    "智能开标", "智能评标", "智能客服", "采小蜜", "深圳政府采购智慧平台", "智能电子采购系统", "智能服务管家", "自动化学院", "智能产业大厦", "项目编号",
    "依托政采云", "具有电子与智能化工程专业承包二级（含）及以上资质",
]
```

采集范围与开关配置示例：

```python
# 收集日期和最大页数（按需修改）
DAYS = 1
PAGES = 20

# 开关
ENABLE_READ_ATTACHMENTS = _env_bool("CCGP_ENABLE_ATTACHMENTS", True)
ENABLE_LLM_REQUIREMENTS = _env_bool("CCGP_ENABLE_LLM", True)
```

---

## LLM 配置说明

`src/ccgp/llm_requirements.py` 支持多 Provider 自动故障转移，按以下优先级依次尝试：

| 优先级 | Provider | 环境变量 |
|--------|----------|----------|
| 1 | Moonshot AI (Kimi) | `MOONSHOT_API_KEY` |
| 2 | Volcengine (Doubao/Ark) | `VOLC_API_KEY` |
| 3 | DeepSeek | `DEEPSEEK_API_KEY` |

配置方式：在环境变量（或 `.env` 文件）中设置对应的 API Key，程序将自动使用已配置的 Provider。至少配置一个即可运行；同时配置多个时，前一个失败后会自动切换到下一个。

```bash
# 示例 .env
MOONSHOT_API_KEY=your_moonshot_key
VOLC_API_KEY=your_volcengine_key
DEEPSEEK_API_KEY=your_deepseek_key
```

若所有 Provider 均未配置，LLM 相关功能（需求摘要生成、二轮语义筛选）将不可用，程序会记录错误日志并跳过相关步骤。

---

## 日志与附件清理

- 日志文件默认写入 `src/ccgp/data/logs/`，文件名格式：`app_YYYYMMDD_HHMMSS.log`
- `src/ccgp_collect.py` 在采集完成后会清理超过 `CLEAN_THRESHOLD` 天的附件子目录（目录名需符合 `前缀_YYYYMMDD`）
- 筛选追踪文件（每次运行新建）：
  - 路径：`src/ccgp/data/filter_trace/filter_trace_YYYYMMDD_HHMMSS.csv`
  - 字段：`title`、`url`、`is_selected`、`not_selected_reason`

---

## 常见问题

- 查询报 403/超时：可适当增大 `sleep_range`，或降低并发/频率
- 字段提取为空：公告模板差异导致，优先补充 `FIELD_ALIASES`；若市字段为空，可能是该市为少数民族自治区，格式不是"xx市"的形式出现
- 提取附件文本失败：下载了不支持的格式或文件过大
- LLM 失败：检查 API Key、网络可达性、模型名与配额
- search.ccgp.gov.cn 不可达（如 GitHub Actions 环境）：程序会自动检测到所有关键词搜索均失败，并自动回退至 `--no-search` 列表页模式（访问 `www.ccgp.gov.cn`），无需人工干预

---

## 性能优化与 CI 配置

### Runtime Env Variables

项目支持通过环境变量覆盖部分运行参数（主要用于 GitHub Actions）：

- `CCGP_ENABLE_ATTACHMENTS`：是否下载并解析附件（`true/false`，默认 `true`）
- `CCGP_ENABLE_LLM`：是否调用 LLM 生成需求摘要（`true/false`，默认 `true`）
- `CCGP_HTTP_TIMEOUT`：列表页/详情页请求超时秒数（默认 `15`）
- `CCGP_DOWNLOAD_TIMEOUT`：附件下载超时秒数（默认 `30`）
- `CCGP_MAX_ATTACHMENTS`：每条公告最多处理附件数（默认 `3`）
- `CCGP_SLEEP_MIN`：查询详情页前最小 sleep 秒数（默认 `2.0`）
- `CCGP_SLEEP_MAX`：查询详情页前最大 sleep 秒数（默认 `4.0`）
- `CCGP_SKIP_REPEAT_FAILED_ATTACHMENTS`：是否跳过已失败过的附件 URL（默认 `true`）

说明：

- 当 `CCGP_ENABLE_ATTACHMENTS=false` 时，将不下载附件，也不会做附件文本提取。
- 当 `CCGP_ENABLE_LLM=false` 时，`requirement_brief/requirement_desc` 为空字符串。

### Attachment Optimization

为降低 CI 运行时长，附件处理增加了以下优化：

- 附件黑名单跳过（例如 `zfcg.szggzy.com` 与 `TPBidder/DownLoad`）
- 失败附件 URL 去重（同一次运行中失败后不再重复下载）
- 限制每条公告最大附件处理数量（由 `CCGP_MAX_ATTACHMENTS` 控制）
- Search 预筛选会放慢请求节奏（页间隔、周期性长休眠、关键词间休眠）
- Search 预筛选会将高频词后置（如 `智能/智慧/自动化`）
- Search 触发频控后会冷却重试 1 次，仍被拦截则提前结束本轮预筛选

### Fast Mode Example

工作流可配置为"快速模式"，示例：

```yaml
env:
  CCGP_ENABLE_LLM: "false"
  CCGP_HTTP_TIMEOUT: "15"
  CCGP_DOWNLOAD_TIMEOUT: "25"
  CCGP_MAX_ATTACHMENTS: "2"
  CCGP_SLEEP_MIN: "0.2"
  CCGP_SLEEP_MAX: "0.8"
  CCGP_SKIP_REPEAT_FAILED_ATTACHMENTS: "true"
```

建议：

- 若主要目标是稳定出数，可先关闭 LLM（`CCGP_ENABLE_LLM=false`）。
- 若仍耗时偏长，可进一步设置 `CCGP_ENABLE_ATTACHMENTS=false` 进入极限快跑模式。

---

## GitHub Pages 部署说明

- 已新增工作流：`.github/workflows/pages.yml`
- 当 `docs/**` 或 `src/ccgp/data/tender_items.csv` 变化并推送到 `main` 时，会自动部署
- 工作流会将 `src/ccgp/data/tender_items.csv` 复制到 `site/data/tender_items.csv` 后发布（`docs/data/` 无需纳入版本控制）

本地预览说明：

`docs/data/` 已被 `.gitignore` 排除，本地直接打开 `docs/index.html` 时需手动准备数据：

```bash
mkdir -p docs/data
cp src/ccgp/data/tender_items.csv docs/data/tender_items.csv
# 然后用静态服务器预览（如 python3 -m http.server 8080 --directory docs）
```
