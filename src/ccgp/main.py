import argparse
import csv
import os
import random
import time
from datetime import datetime, timedelta
from hashlib import sha1
from typing import List, Optional, Tuple
from urllib.parse import urlencode, urlparse

import requests

from ccgp.config import (
    ATTACHMENT_BLOCKLIST_HOSTS,
    ATTACHMENT_BLOCKLIST_KEYWORDS,
    ATTACHMENTS_DIR,
    CSV_OUTPUT_DIR,
    DAYS,
    DETAIL_SLEEP_MAX_SEC,
    DETAIL_SLEEP_MIN_SEC,
    DOWNLOAD_TIMEOUT_SEC,
    ENABLE_LLM_REQUIREMENTS,
    ENABLE_READ_ATTACHMENTS,
    FILTER_KEYWORDS,
    MAX_ATTACHMENTS_PER_NOTICE,
    PAGES,
    REQUEST_TIMEOUT_SEC,
    SG_TZ,
    SKIP_REPEATED_FAILED_ATTACHMENTS,
    USER_AGENT,
)
from ccgp.llm_requirements import generate_requirements, llm_second_filter_by_combined
from ccgp.model import TenderItem
from ccgp.parse_detail import parse_detail_page
from ccgp.parse_index import parse_list_page, parse_search_page
from ccgp.tools import (
    download_file,
    extract_text_from_file,
    guess_location,
    http_get,
    keyword_hit,
    norm_list_page_urls,
    parse_pub_datetime,
    write_csv,
)
from utils.mylogger import get_logger, setup_logging


SEARCH_BASE_URL = "https://search.ccgp.gov.cn/bxsearch"


def _get_filter_trace_file() -> str:
    out_dir = "src/ccgp/data/filter_trace"
    os.makedirs(out_dir, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    return os.path.join(out_dir, f"filter_trace_{ts}.csv")


def _flush_filter_trace_csv(path: str, records: dict) -> None:
    cols = ["title", "url", "is_selected", "not_selected_reason"]
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        for rec in records.values():
            row = {k: rec.get(k, "") for k in cols}
            w.writerow(row)


def _set_trace_result(records: dict, ann_url: str, is_selected: bool, reason: str) -> None:
    rec = records.get(ann_url)
    if not rec:
        return
    rec["is_selected"] = is_selected
    rec["not_selected_reason"] = reason if (not is_selected) else ""


def _should_skip_attachment(url: str, name: str) -> bool:
    host = (urlparse(url).hostname or "").lower()
    if host in ATTACHMENT_BLOCKLIST_HOSTS:
        return True
    for kw in ATTACHMENT_BLOCKLIST_KEYWORDS:
        if kw and (kw in url or kw in name):
            return True
    return False


def _build_search_url(keyword: str, page_index: int, start_date: str, end_date: str) -> str:
    params = {
        "searchtype": "2",
        "page_index": str(page_index),
        "bidSort": "0",
        "buyerName": "",
        "projectId": "",
        "pinMu": "0",
        "bidType": "1",
        "dbselect": "bidx",
        "kw": keyword,
        "start_time": start_date,
        "end_time": end_date,
        "timeType": "1",
        "displayZone": "",
        "zoneId": "",
        "pppStatus": "0",
        "agentName": "",
    }
    return f"{SEARCH_BASE_URL}?{urlencode(params)}"


def _collect_entries_from_search(
    session: requests.Session,
    keywords: List[str],
    start_date: str,
    end_date: str,
    max_pages: int,
) -> List[dict]:

    dedup = {}
    norm_keywords = [k.strip() for k in (keywords or []) if (k or "").strip()]
    get_logger().debug(
        f"search prefilter start: keywords={len(norm_keywords)} date_range={start_date}..{end_date} max_pages={max_pages}"
    )

    stop_all_search = False
    for kw in norm_keywords:
        # 已经被封禁了，就不再继续后续关键词的查找。 
        if stop_all_search: 
            break

        keyword_count = 0
        blocked_once_for_kw = False
        for page_index in range(1, max_pages + 1):
            url = _build_search_url(kw, page_index, start_date, end_date)
            try:
                html = http_get(url, session, timeout=REQUEST_TIMEOUT_SEC)
            except Exception as e:
                get_logger().warning(f"search page failed: kw={kw} page={page_index} -> {e}")
                break

            if ("访问过于频繁" in html) or ("频繁访问" in html) or ("事件ID" in html):
                cooldown = random.uniform(150, 380)
                get_logger().warning(
                    f"search blocked by frequency control: kw={kw} page={page_index}, cooldown={cooldown:.1f}s"
                )
                time.sleep(cooldown)

                if blocked_once_for_kw:
                    get_logger().warning(
                        f"search blocked twice, stop all search prefilter: kw={kw} page={page_index}"
                    )
                    stop_all_search = True
                    break
                blocked_once_for_kw = True
                
                # 如果是第一次被封禁，休眠后重试一次，看看是否恢复了；如果仍然被封禁，则停止整个预筛选过程，不再继续后续关键词的搜索。
                try:
                    html = http_get(url, session, timeout=REQUEST_TIMEOUT_SEC)
                except Exception as e:
                    get_logger().warning(
                        f"search retry failed after cooldown: kw={kw} page={page_index} -> {e}"
                    )
                    stop_all_search = True
                    break

                if ("访问过于频繁" in html) or ("频繁访问" in html) or ("事件ID" in html):
                    get_logger().warning(
                        f"search still blocked after cooldown retry, stop all search prefilter: kw={kw} page={page_index}"
                    )
                    stop_all_search = True
                    break

            entries = parse_search_page(html, base_url="https://search.ccgp.gov.cn/")
            if not entries:
                if page_index == 1:
                    get_logger().debug(f"search empty: kw={kw}")
                break

            for ent in entries:
                ann_url = (ent.get("url") or "").strip()
                if not ann_url:
                    continue
                if ann_url not in dedup:
                    ent["search_keyword"] = kw
                    dedup[ann_url] = ent
                    keyword_count += 1

            # 每页查找之间随机短暂休眠，避免过快访问引发封禁；每10页长休眠一次。
            time.sleep(random.uniform(5, 8))
            if page_index % 5 == 0:
                long_pause = random.uniform(10, 15)
                get_logger().debug(
                    f"search periodic cooldown: kw={kw} page={page_index} sleep={long_pause:.1f}s"
                )
                time.sleep(long_pause)

        get_logger().debug(f"search keyword done: kw={kw}, new_entries={keyword_count}")
        # 每个关键词查找之间随机长休眠，避免过快访问引发封禁；
        # 如果已经被封禁了，就不再继续后续关键词的查找。
        if not stop_all_search:
            kw_pause = random.uniform(5, 8)
            get_logger().debug(f"search keyword cooldown: kw={kw} sleep={kw_pause:.1f}s")
            time.sleep(kw_pause)

    out = list(dedup.values())
    get_logger().debug(f"search prefilter done: unique_entries={len(out)}, stopped_early={stop_all_search}")
    return out


def scrape_ccgp(
    start_list_url: str,
    days: int = 3,
    max_pages: int = 30,
    keywords: Optional[List[str]] = FILTER_KEYWORDS,
    sleep_range: Tuple[float, float] = (DETAIL_SLEEP_MIN_SEC, DETAIL_SLEEP_MAX_SEC),
    use_search_prefilter: bool = True,
) -> List[TenderItem]:
    """
    抓取中国政府采购网公告的核心业务流程。
    主要步骤：
    1. 根据配置，先从搜索接口(或列表页)收集指定时间范围内的公告条目初步信息。
    2. 遍历收集到的条目，依次请求公告详情页。
    3. 基于关键词和LLM进行双重过滤，筛选出符合要求的招标公告。
    4. 提取详情和附件文本，利用大模型归纳出采购需求。
    """
    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            "Connection": "keep-alive",
        }
    )

    now = datetime.now(tz=SG_TZ)
    cutoff = now - timedelta(days=days)

    # 第一步：收集公告列表
    # 如果启用 use_search_prefilter，通过站内搜索接口获取近期公告以缩小范围
    # 否则，退化为传统方式，从指定列表页逐页爬取
    if use_search_prefilter:
        entries = _collect_entries_from_search(
            session=session,
            keywords=keywords,
            start_date=(cutoff.date().strftime("%Y:%m:%d")),
            end_date=(now.date().strftime("%Y:%m:%d")),
            max_pages=max_pages,
        )
    else:
        list_urls = norm_list_page_urls(start_list_url, max_pages=max_pages)
        entries = []
        for list_url in list_urls:
            try:
                list_html = http_get(list_url, session, timeout=REQUEST_TIMEOUT_SEC)
            except Exception as e:
                get_logger().warning(f"list page failed: {list_url} -> {e}")
                break
            base_url = list_url.rsplit("/", 1)[0] + "/"
            page_entries = parse_list_page(list_html, base_url=base_url)
            if not page_entries:
                break
            entries.extend(page_entries)

    results: List[TenderItem] = []
    seen_urls = set()
    failed_attachment_urls = set()
    count = 0

    filter_trace_file = _get_filter_trace_file()
    filter_trace_records: dict = {}
    get_logger().debug(f"filter trace file: {filter_trace_file}")

    # 第二步：逐个详情页抓取与处理流程
    for ent in entries:
        ann_url = (ent.get("url") or "").strip()
        if not ann_url:
            continue

        if ann_url in seen_urls:
            continue

        # 初始化本条过滤追踪记录
        filter_trace_records[ann_url] = {
            "title": ent.get("title", ""),
            "url": ann_url,
            "is_selected": None,
            "not_selected_reason": "pending",
        }

        # 时间过滤：对于列表页模式，剔除超过时间窗口的数据
        pub_dt = parse_pub_datetime(ent.get("pub_raw", ""))
        if pub_dt and pub_dt < cutoff and not use_search_prefilter:
            _set_trace_result(filter_trace_records, ann_url, False, "older than DAYS window")
            _flush_filter_trace_csv(filter_trace_file, filter_trace_records)
            continue

        seen_urls.add(ann_url)

        # 抓取详情网页，休眠控制防BAN
        try:
            time.sleep(random.uniform(*sleep_range))
            detail_html = http_get(ann_url, session, timeout=REQUEST_TIMEOUT_SEC)
        except Exception as e:
            _set_trace_result(filter_trace_records, ann_url, False, f"detail fetch failed: {e}")
            get_logger().warning(f"detail failed: {ann_url} -> {e}")
            _flush_filter_trace_csv(filter_trace_file, filter_trace_records)
            continue

        # 解析详情正文、项目名称等字段
        detail = parse_detail_page(detail_html, page_url=ann_url)
        combined = " ".join(
            [
                ent.get("title", ""),
                detail.get("project_name", ""),
                detail.get("full_text", ""),
            ]
        )

        get_logger().debug(
            f"filtering the announcement: ent.title={ent.get('title', '')} url={ann_url}"
        )
        
        # 第三步：关键过滤 （1）关键字精确过滤
        if not keyword_hit(combined, keywords):
            _set_trace_result(filter_trace_records, ann_url, False, "round1 keyword filter not matched")
            _flush_filter_trace_csv(filter_trace_file, filter_trace_records)
            continue

        # 第三步：关键过滤 （2）大模型进行深度语义过滤
        try:
            second_filter = llm_second_filter_by_combined(
                combined_text=combined,
                title=ent.get("title", ""),
            )
            if not second_filter.get("keep", True):
                reason = str(second_filter.get("reason", "")).strip()
                _set_trace_result(
                    filter_trace_records,
                    ann_url,
                    False,
                    f"round2 llm rejected: {reason}",
                )
                get_logger().warning(f"llm second filter rejected: {ann_url} -> {reason}")
                _flush_filter_trace_csv(filter_trace_file, filter_trace_records)
                continue
            get_logger().debug(
                f"llm second filter passed: {ann_url} -> {second_filter.get('reason', '')}"
            )
        except Exception as e:
            get_logger().warning(f"llm second filter failed, fallback keep: {ann_url} -> {e}")

        # 通过所有验证，标记选定
        _set_trace_result(filter_trace_records, ann_url, True, "")

        # 完善从列表中获取不到的省市信息
        province = ent.get("region", "") or ""
        prov, city = guess_location(detail.get("location_text", ""))
        if not province:
            province = prov

        requirement_brief = ""
        requirement_desc = ""

        # 第四步：若开启，下载附件并提取文本以供需求信息生成
        if ENABLE_READ_ATTACHMENTS:
            attachments = detail.get("attachments", []) or []
            att_texts = []
            att_dir = (
                f"{ATTACHMENTS_DIR}{sha1(ann_url.encode('utf-8')).hexdigest()[:12]}_"
                f"{datetime.now().strftime('%Y%m%d')}"
            )

            for a in attachments[:MAX_ATTACHMENTS_PER_NOTICE]:
                a_url = (a.get("url") or "").strip()
                a_name = (a.get("name") or "").strip()
                if not a_url:
                    continue

                # 通过黑名单判断是否跳过该附件（如非招投标文件）
                if _should_skip_attachment(a_url, a_name):
                    get_logger().warning(
                        f"skip attachment by blocklist: name={a_name} url={a_url}"
                    )
                    continue

                if SKIP_REPEATED_FAILED_ATTACHMENTS and a_url in failed_attachment_urls:
                    get_logger().debug(f"skip repeated failed attachment: {a_url}")
                    continue

                try:
                    local_path = download_file(
                        session,
                        a_url,
                        out_dir=att_dir,
                        filename=a_name,
                        timeout=DOWNLOAD_TIMEOUT_SEC,
                    )
                    get_logger().warning(f"downloaded attachment: {a_url} -> {local_path}")

                    try:
                        text = extract_text_from_file(local_path)
                        if text and text.strip():
                            att_texts.append(text)
                            get_logger().warning(
                                f"extracted text from attachment: {a_name} ({len(text)} chars)"
                            )
                            count += 1
                        else:
                            try:
                                size = os.path.getsize(local_path)
                            except Exception:
                                size = -1
                            ext = (os.path.splitext(local_path)[1] or "").lower()
                            get_logger().warning(
                                "no text extracted: "
                                f"name={a_name} ext={ext} size={size}B path={local_path} url={a_url}"
                            )
                    except Exception as e:
                        get_logger().warning(f"extract_text_from_file failed: {a_name} -> {e}")
                except Exception as e:
                    failed_attachment_urls.add(a_url)
                    get_logger().warning(f"download attachment failed: {a_name} -> {e}")

            # 第五步：利用大语言模型提取关键业务需求
            if ENABLE_LLM_REQUIREMENTS:
                meta = {
                    "title": ent.get("title", ""),
                    "url": ann_url,
                    "project_name": detail.get("project_name", ""),
                    "budget": detail.get("budget", ""),
                    "deadline": detail.get("deadline", ""),
                    "company_name": detail.get("company_name", ""),
                    "contact_phone": detail.get("contact_phone", ""),
                }
                try:
                    req = generate_requirements(meta, detail.get("full_text", ""), att_texts)
                    requirement_brief = req.get("requirement_brief", "")
                    requirement_desc = req.get("requirement_desc", "")
                except Exception as e:
                    get_logger().warning(f"LLM generate requirements failed: {ann_url} -> {e}")

        # 第六步：保存结构化信息到 results 列表中
        results.append(
            TenderItem(
                announcement_title=ent.get("title", ""),
                announcement_url=ann_url,
                pub_time=ent.get("pub_iso", "") or "",
                province=province,
                city=city,
                project_name=detail.get("project_name", "") or ent.get("title", ""),
                requirement_brief=requirement_brief,
                requirement_desc=requirement_desc,
                deadline=detail.get("deadline", ""),
                company_name=detail.get("company_name", ""),
                purchasing_unit_contact_number=detail.get("purchasing_unit_contact_number", ""),
                contact_name=detail.get("contact_name", ""),
                contact_phone=detail.get("contact_phone", ""),
                location_text=detail.get("location_text", ""),
                budget=detail.get("budget", ""),
            )
        )
        _flush_filter_trace_csv(filter_trace_file, filter_trace_records)

    _flush_filter_trace_csv(filter_trace_file, filter_trace_records)
    get_logger().debug(f"successfully read {count} attachments.")
    get_logger().debug(f"saved filter trace: {filter_trace_file}, items={len(filter_trace_records)}")
    return results


def main() -> None:
    setup_logging()

    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--start",
        default="https://www.ccgp.gov.cn/cggg/dfgg/gkzb/index.htm",
        help="列表页起始 URL（仅在 --no-search 时生效）",
    )
    ap.add_argument("--days", type=int, default=DAYS, help="搜索近 N 天")
    ap.add_argument("--pages", type=int, default=PAGES, help="每个关键词最多搜索页数")
    ap.add_argument("--no-search", action="store_true", help="关闭 search.ccgp 预筛选，回退到旧列表页模式")
    args = ap.parse_args()

    items = scrape_ccgp(
        start_list_url=args.start,
        days=args.days,
        max_pages=args.pages,
        keywords=FILTER_KEYWORDS,
        use_search_prefilter=(not args.no_search),
    )

    write_csv(items, CSV_OUTPUT_DIR)
    get_logger().debug(f"[OK] saved: {CSV_OUTPUT_DIR}, items={len(items)}")


if __name__ == "__main__":
    main()
