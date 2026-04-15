# 招标公告采集项目

本项目用于查询公开招标公告，提取结构化字段，并可选下载附件、抽取附件文本、调用 LLM 生成需求摘要，最终落盘到 CSV。

## 功能概览

- 采集来源：公开招标公告

- 支持按最近 N 天、最多翻页数控制采集范围，在文件src/ccgp/config.py中进行设置
```python
# 收集日期和最大页数
DAYS = 1
PAGES = 30
```
- 关键词过滤（含排除词）,在文件src/ccgp/config.py中进行增删
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
    "智能开标", "智能评标", "智能客服", "采小蜜","深圳政府采购智慧平台","智能电子采购系统", "智能服务管家", "自动化学院","智能产业大厦", "项目编号",
    "依托政采云","具有电子与智能化工程专业承包二级（含）及以上资质",
]

```
- 详情页结构化解析（项目名、预算、截止时间、采购单位、联系方式、地址等）

- 可选附件下载与文本抽取（支持`pdf/docx/xlsx/txt/zip`）
- 可选 LLM 生成:
  - `ai_project_title`（AI相关标题）
  - `requirement_brief`（简要需求）
  - `requirement_desc`（详细需求）

开关在文件src/ccgp/config.py中进行设置
```python
# 开关
ENABLE_READ_ATTACHMENTS = _env_bool("CCGP_ENABLE_ATTACHMENTS", True)
ENABLE_LLM_REQUIREMENTS = _env_bool("CCGP_ENABLE_LLM", True)
```
- 输出 CSV 追加写入，日志按时间滚动保存

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

## 运行环境

- Python 3.10+
- Windows / Linux / macOS 均可

安装依赖：

```bash
pip install -r requirements.txt
pip install openai PyPDF2 python-docx openpyxl
```

说明：第二行是附件解析与 LLM 功能需要的额外依赖，未安装时对应功能会报错或不可用。

## 快速开始

- 使用默认模式（推荐，基于 search.ccgp 全文检索预筛选）：

    ```bash
    python src/ccgp_collect.py 
    ```

- 使用旧列表页模式（仅在需要时）：

    ```bash
    python src/ccgp_collect.py --no-search 
    ```

- 其他参数说明：

    - `--days`：搜索近 N 天（默认 `3`）
    - `--pages`：每个关键词最多搜索页数（search 模式）或最大翻页数（旧模式）
    - `--start`：指定起始网址，仅在 `--no-search` 模式下生效，目前支持：  
      - 地方公告：`https://www.ccgp.gov.cn/cggg/dfgg/gkzb/index.htm`
      - 中央公告：`https://www.ccgp.gov.cn/cggg/zygg/gkzb/index.htm`


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

## 输出说明

输出 CSV 默认路径：`src/ccgp/data/tender_items.csv`

字段如下：

- `announcement_title` 需求标题
- `announcement_url`  需求来源
- `pub_time`  发布时间
- `province`  省
- `city`  市
- `project_name`  项目名称
- `ai_project_title` AI相关标题
- `requirement_brief`  项目简介
- `requirement_desc`  项目描述
- `deadline`  截止时间
- `company_name`  单位名称
- `purchasing_unit_contact_number`  单位联系方式
- `contact_name`  负责人名称
- `contact_phone`  负责人联系方式
- `location_text`  详细地址
- `budget`  预算

## GitHub Pages 可视化看板

仓库已新增 GitHub Pages 静态页面，默认读取 `tender_items.csv` 并展示为可交互表格。

- 页面源文件：`docs/index.html`
- 前端脚本：`docs/assets/app.js`
- 样式文件：`docs/assets/style.css`
- 页面数据文件（部署时由工作流从 `src/ccgp/data/tender_items.csv` 自动生成）：`site/data/tender_items.csv`

功能说明：

- 解析 `tender_items.csv` 作为主要内容
- 搜索功能（项目名、地区、单位、摘要等）
- 列头点击排序（日期、预算、文本列）
- 分页功能（默认每页 `50` 条，数字页码导航）
- 筛选功能：默认不显示 `requirement_desc == "无相关要求"` 的条目
- 省份筛选
- 城市筛选（随省份联动）
- 预算区间筛选（单位：万元）
- 表格仅保留适合展示的核心列，并将公告链接合并到“项目标题”字段
- 时间列展示精度为“年月日”（`YYYY-MM-DD`）

部署说明：

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

## LLM 配置说明

当前 `src/ccgp/llm_requirements.py` 中使用 Moonshot 兼容接口。
```
client = OpenAI(
    api_key=MOONSHOT_API_KEY,
    base_url=BASE_URL
)
```


## 日志与附件清理

- 日志文件默认写入 `src/ccgp/data/logs/`，文件名格式：`app_YYYYMMDD_HHMMSS.log`
- `src/ccgp_collect.py` 在采集完成后会清理超过 `CLEAN_THRESHOLD` 天的附件子目录（目录名需符合 `前缀_YYYYMMDD`）
- 筛选追踪文件（每次运行新建）：
  - 路径：`src/ccgp/data/filter_trace/filter_trace_YYYYMMDD_HHMMSS.csv`
  - 字段：`title`、`url`、`is_selected`、`not_selected_reason`

## 常见问题

- 查询报 403/超时：可适当增大 `sleep_range`，或降低并发/频率
- 字段提取为空：公告模板差异导致，优先补充 `FIELD_ALIASES`；若市字段为空，可能是该市为少数名族自治区，格式不是“xx市”的形式出现
- 提取附件文本失败：下载了不支持的格式或文件过大
- LLM 失败：检查 API Key、网络可达性、模型名与配额
- search.ccgp.gov.cn 不可达（如 GitHub Actions 环境）：程序会自动检测到所有关键词搜索均失败，并自动回退至 `--no-search` 列表页模式（访问 `www.ccgp.gov.cn`），无需人工干预

## 以下为优化速度相关配置（主要用于GitHub Actions）
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

工作流可配置为“快速模式”，示例：

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

