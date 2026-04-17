# 招标公告采集项目

本项目用于查询公开招标公告，提取结构化字段，并可选下载附件、抽取附件文本、调用 LLM 生成需求摘要，最终落盘到 CSV。

> 内部技术实现细节（目录结构、配置项、LLM配置、日志与附件清理、性能优化、常见问题等）请参阅 [docs/technical.md](docs/technical.md)。

## 功能概览

- 采集来源：公开招标公告
- 支持按最近 N 天、最多翻页数控制采集范围
- 关键词过滤（含排除词）
- 详情页结构化解析（项目名、预算、截止时间、采购单位、联系方式、地址等）
- 可选附件下载与文本抽取（支持 `pdf/docx/xlsx/txt/zip`）
- 可选 LLM 生成需求摘要：
  - `ai_project_title`（AI相关标题）
  - `requirement_brief`（简要需求）
  - `requirement_desc`（详细需求）
- 输出 CSV 追加写入，日志按时间滚动保存

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
- 筛选功能：默认不显示 `requirement_desc` 或 `requirement_brief` 为"无相关要求"的条目，勾选"包含未提取需求的项目"后显示
- 省份筛选
- 城市筛选（随省份联动）
- 预算区间筛选（单位：万元）
- 表格仅保留适合展示的核心列，并将公告链接合并到"项目标题"字段
- 时间列展示精度为"年月日"（`YYYY-MM-DD`）

> 部署说明、本地预览及更多技术细节，请参阅 [docs/technical.md](docs/technical.md)。
