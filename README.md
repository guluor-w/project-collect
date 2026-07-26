# 招标公告结构化索引工具

一个针对已公开发布的招标公告的结构化整理与浏览辅助工具：从公开信息源读取公告 → 解析详情 → 提取结构化字段 → 可选附件文本摘录与 LLM 需求摘要 → 生成便于检索的 CSV 索引。

> 内部实现细节（目录结构、配置项、字段清单、LLM 配置、日志与附件清理、性能优化、部署等）请参阅 [docs/technical.md](docs/technical.md)。

## 功能概览

- 按最近 N 天、最多翻页数控制读取范围
- 关键词过滤（含排除词）
- 详情页结构化解析（项目、预算、截止时间、单位、联系方式、地址等）
- 可选附件文本摘录（`pdf/docx/xlsx/txt/zip`）
- 可选 LLM 生成需求摘要
- CSV 追加写入，日志按时间滚动保存

## 快速开始

```bash
# 默认模式（推荐）
python src/ccgp_collect.py

# 旧列表页模式（仅在需要时）
python src/ccgp_collect.py --no-search
```

常用参数：

- `--days`：读取近 N 天的公开公告（默认 `3`）
- `--pages`：每个关键词最多检索页数 / 最大翻页数
- `--start`：指定起始网址（仅在 `--no-search` 下生效，具体入口见 [docs/technical.md](docs/technical.md)）

## GitHub Pages 可视化看板

仓库附带一份静态页面，用于对生成的 CSV 索引进行本地浏览，支持搜索、排序、筛选与分页。部署与本地预览请参阅 [docs/technical.md](docs/technical.md)。
