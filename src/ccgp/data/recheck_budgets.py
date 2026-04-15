"""
预算金额重新抓取脚本：针对 tender_items.csv 中的每一条记录，
通过 announcement_url 重新抓取详情页并用最新的金额解析规则提取 budget，
更新后写回 tender_items.csv（以及同步更新 docs/data/tender_items.csv）。

用法：
    cd <项目根目录>
    python -m ccgp.data.recheck_budgets

可选环境变量：
    CCGP_SLEEP_MIN   两次请求之间的最小等待时间（秒），默认 2.0
    CCGP_SLEEP_MAX   两次请求之间的最大等待时间（秒），默认 4.0
    CCGP_HTTP_TIMEOUT 单次 HTTP 请求超时（秒），默认 15
"""

import csv
import os
import random
import sys
import tempfile
import time
from typing import Optional

import requests
from dotenv import load_dotenv

load_dotenv()

# ---------------------------------------------------------------------------
# 路径配置
# ---------------------------------------------------------------------------
_HERE = os.path.dirname(__file__)
_REPO_ROOT = os.path.abspath(os.path.join(_HERE, "..", "..", ".."))

# 确保项目 src 目录在 Python 路径中（方便直接以脚本方式运行）
_SRC_DIR = os.path.join(_REPO_ROOT, "src")
if _SRC_DIR not in sys.path:
    sys.path.insert(0, _SRC_DIR)

from ccgp.parse_detail import parse_detail_page  # noqa: E402 - path set above

SRC_CSV = os.path.join(_HERE, "tender_items.csv")
DOCS_CSV = os.path.join(_REPO_ROOT, "docs", "data", "tender_items.csv")

# ---------------------------------------------------------------------------
# 访问间隔（可通过环境变量覆盖）
# ---------------------------------------------------------------------------
_SLEEP_MIN = float(os.getenv("CCGP_SLEEP_MIN", "2.0"))
_SLEEP_MAX = float(os.getenv("CCGP_SLEEP_MAX", "4.0"))
_TIMEOUT = int(os.getenv("CCGP_HTTP_TIMEOUT", "15"))

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    )
}


# ---------------------------------------------------------------------------
# 辅助函数
# ---------------------------------------------------------------------------

def _fetch_html(session: requests.Session, url: str) -> Optional[str]:
    """抓取页面 HTML，失败时返回 None。"""
    try:
        resp = session.get(url, headers=_HEADERS, timeout=_TIMEOUT)
        resp.raise_for_status()
        resp.encoding = resp.apparent_encoding or "utf-8"
        return resp.text
    except Exception as exc:
        print(f"  [WARN] 抓取失败: {url} -> {exc}")
        return None


def _write_csv_atomic(path: str, fieldnames: list, rows: list) -> None:
    """原子写入 CSV（先写临时文件再替换），避免中途异常损坏源文件。"""
    dir_name = os.path.dirname(os.path.abspath(path))
    os.makedirs(dir_name, exist_ok=True)
    tmp_fd, tmp_path = tempfile.mkstemp(dir=dir_name, suffix=".tmp")
    try:
        with os.fdopen(tmp_fd, "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)
        os.replace(tmp_path, path)
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------

def recheck_budgets(src_csv: str = SRC_CSV, docs_csv: str = DOCS_CSV) -> None:
    """重新抓取所有条目的预算金额并写回 CSV。"""

    with open(src_csv, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        fieldnames = list(reader.fieldnames or [])
        rows = list(reader)

    total = len(rows)
    print(f"共 {total} 条记录，开始重新提取预算金额…")

    session = requests.Session()
    updated = 0
    failed = 0

    for idx, row in enumerate(rows, start=1):
        url = (row.get("announcement_url") or "").strip()
        old_budget = (row.get("budget") or "").strip()

        if not url:
            print(f"[{idx}/{total}] 跳过（无 URL）: {row.get('project_name', '')[:40]}")
            continue

        print(f"[{idx}/{total}] 抓取: {url}")
        html = _fetch_html(session, url)

        if html is None:
            failed += 1
            print(f"  [SKIP] 保留原值: {old_budget!r}")
        else:
            detail = parse_detail_page(html, url)
            new_budget = (detail.get("budget") or "").strip()

            if new_budget and new_budget != old_budget:
                print(f"  [UPDATE] {old_budget!r} -> {new_budget!r}")
                row["budget"] = new_budget
                updated += 1
            elif not new_budget:
                print(f"  [SKIP] 未能从页面提取金额，保留原值: {old_budget!r}")
            else:
                print(f"  [OK] 无变化: {old_budget!r}")

        # 合理的访问间隔
        if idx < total:
            sleep_sec = random.uniform(_SLEEP_MIN, _SLEEP_MAX)
            time.sleep(sleep_sec)

    print(f"\n完成：共更新 {updated} 条，抓取失败 {failed} 条，共 {total} 条。")

    # 写回源文件
    _write_csv_atomic(src_csv, fieldnames, rows)
    print(f"已写入: {src_csv}")

    # 同步到 docs/data/tender_items.csv（若路径非空且父目录存在）
    docs_parent = os.path.dirname(os.path.abspath(docs_csv)) if docs_csv else ""
    if docs_csv and docs_parent and os.path.isdir(docs_parent):
        _write_csv_atomic(docs_csv, fieldnames, rows)
        print(f"已同步: {docs_csv}")


if __name__ == "__main__":
    recheck_budgets()
