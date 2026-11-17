import argparse
import csv
import json
import os
import random
import time
import requests
from datetime import datetime, timedelta
from hashlib import sha1
from typing import Callable, List, Optional, Tuple
from tqdm import tqdm
from urllib.parse import urlencode, urlparse


from ccgp.config import (
    ATTACHMENT_BLOCKLIST_HOSTS,
    ATTACHMENT_BLOCKLIST_KEYWORDS,
    ATTACHMENTS_DIR,
    COLLECTION_CHECKPOINT_PATH,
    COLLECTION_TIME_BUDGET_SEC,
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
    SEARCH_COOLDOWN_SCHEDULE_SEC,
    SEARCH_KEYWORD_SLEEP_MAX_SEC,
    SEARCH_KEYWORD_SLEEP_MIN_SEC,
    SEARCH_PAGE_SLEEP_MAX_SEC,
    SEARCH_PAGE_SLEEP_MIN_SEC,
    SG_TZ,
    SKIP_REPEATED_FAILED_ATTACHMENTS,
    USER_AGENT,
)


class SearchNetworkError(RuntimeError):
    """搜索预筛选因网络请求失败或持续频率限制而不可用。"""
    pass


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
COLLECTION_STARTED_AT = time.monotonic()


def _load_processed_urls(csv_file: str) -> set[str]:
    """帮助加载已经处理过的公告 URL，避免重复处理和保存。"""
    if not os.path.exists(csv_file):
        return set()

    seen = set()
    try:
        with open(csv_file, "r", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            for row in reader:
                url = (row.get("announcement_url") or "").strip()
                if url:
                    seen.add(url)
    except Exception as e:
        get_logger().error(f"Failed to load processed URLs from {csv_file}: {e}")
        
    return seen


def _load_pending_entries() -> List[dict]:
    if not os.path.exists(COLLECTION_CHECKPOINT_PATH):
        return []
    try:
        with open(COLLECTION_CHECKPOINT_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        entries = data.get("entries", [])
        return [
            entry for entry in entries
            if isinstance(entry, dict) and (entry.get("url") or "").strip()
        ]
    except Exception as e:
        get_logger().error(f"读取采集断点失败: {COLLECTION_CHECKPOINT_PATH} -> {e}")
        return []


def _write_pending_entries(entries: List[dict]) -> None:
    dedup = {}
    for entry in entries:
        ann_url = (entry.get("url") or "").strip()
        if ann_url:
            dedup[ann_url] = entry
    directory = os.path.dirname(COLLECTION_CHECKPOINT_PATH)
    if directory:
        os.makedirs(directory, exist_ok=True)
    tmp_path = COLLECTION_CHECKPOINT_PATH + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump({"entries": list(dedup.values())}, f, ensure_ascii=False, indent=2)
    os.replace(tmp_path, COLLECTION_CHECKPOINT_PATH)


def _check_deadline(deadline: Optional[float]) -> None:
    if deadline is not None and time.monotonic() >= deadline:
        raise TimeoutError("已达到采集时间预算，保留当前断点")


def _sleep_with_deadline(seconds: float, deadline: Optional[float]) -> None:
    if deadline is not None and time.monotonic() + seconds >= deadline:
        raise TimeoutError("采集时间预算不足以完成本次等待，保留当前断点")
    time.sleep(seconds)


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


def _log_keyword_stats(stats: dict) -> None:
    if not stats:
        return

    logger = get_logger()
    logger.info("=" * 105)
    logger.info(f"{'关键词':<20} | {'发现':<6} | {'详情OK':<6} | {'关键词通过':<10} | {'LLM通过':<8} | {'需求明确':<6} | {'入库':<6}")
    logger.info("-" * 105)

    for kw, counts in stats.items():
        found = counts.get("found", 0)
        detail = counts.get("detail_ok", 0)
        kw_pass = counts.get("kw_filter_pass", 0)
        llm_pass = counts.get("llm_filter_pass", 0)
        req_found = counts.get("req_found", 0)
        saved = counts.get("saved", 0)

        logger.info(
            f"{kw:<20} | {found:<8} | {detail:<8} | {kw_pass:<15} | {llm_pass:<10} | {req_found:<8} | {saved:<6}"
        )
    logger.info("=" * 105)


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
    keywords: Optional[List[str]],
    start_date: str,
    end_date: str,
    max_pages: int,
    on_update: Optional[Callable[[List[dict]], None]] = None,
    deadline: Optional[float] = None,
) -> Tuple[List[dict], bool]:
    """搜索预筛选：按关键词遍历 search.ccgp.gov.cn 获取候选公告列表。

    Returns:
        entries (List[dict]): 去重后的公告条目列表。
        search_unavailable (bool): 所有关键词均因网络/连接错误失败，或搜索因持续
            频率限制、冷却后重试失败而提前终止时为 True。
    """
    dedup = {}

    def notify_update() -> None:
        if on_update:
            on_update(list(dedup.values()))

    norm_keywords = [k.strip() for k in (keywords or []) if (k or "").strip()]
    get_logger().debug(
        f"搜索预筛选开始: 关键词数={len(norm_keywords)} 日期={start_date}..{end_date} 最大页数={max_pages}"
    )

    stop_all_search = False
    keywords_attempted = 0
    network_failed_kws = 0
    # 使用 tqdm 显示关键词搜索进度
    for kw in tqdm(norm_keywords, desc="关键词搜索进度", unit="kw"):
        _check_deadline(deadline)
        # 已经被封禁了，就不再继续后续关键词的查找。 
        if stop_all_search: 
            break

        keywords_attempted += 1
        had_connection_success = False  # True if at least one request reached the server (even 4xx/5xx)
        keyword_count = 0
        blocked_attempts = 0
        for page_index in range(1, max_pages + 1):
            url = _build_search_url(kw, page_index, start_date, end_date)
            try:
                html = http_get(url, session, timeout=REQUEST_TIMEOUT_SEC)
                had_connection_success = True
            except requests.ConnectionError as e:
                get_logger().warning(f"搜索页网络连接失败: 关键词={kw} 页码={page_index} -> {e}")
                break
            except requests.Timeout as e:
                get_logger().warning(f"搜索页请求超时: 关键词={kw} 页码={page_index} -> {e}")
                break
            except Exception as e:
                had_connection_success = True
                get_logger().warning(f"搜索页请求失败: 关键词={kw} 页码={page_index} -> {e}")
                break

            while any(marker in html for marker in ("访问过于频繁", "频繁访问", "事件ID")):
                if blocked_attempts >= len(SEARCH_COOLDOWN_SCHEDULE_SEC):
                    get_logger().warning(
                        f"长等待重试后仍被限制，停止搜索并保留候选: 关键词={kw} 页码={page_index}"
                    )
                    stop_all_search = True
                    break
                base_cooldown = SEARCH_COOLDOWN_SCHEDULE_SEC[blocked_attempts]
                blocked_attempts += 1
                cooldown = base_cooldown * random.uniform(0.8, 1.2)
                notify_update()
                get_logger().warning(
                    f"搜索限流，第 {blocked_attempts}/{len(SEARCH_COOLDOWN_SCHEDULE_SEC)} 次长等待: "
                    f"关键词={kw} 页码={page_index} 等待={cooldown / 60:.1f}分钟"
                )
                _sleep_with_deadline(cooldown, deadline)
                try:
                    html = http_get(url, session, timeout=REQUEST_TIMEOUT_SEC)
                except Exception as e:
                    get_logger().warning(f"长等待后重试搜索失败: 关键词={kw} 页码={page_index} -> {e}")
                    stop_all_search = True
                    break
            if stop_all_search:
                break

            entries = parse_search_page(html, base_url="https://search.ccgp.gov.cn/")
            have_find_new = False

            if not entries:
                if page_index == 1:
                    get_logger().debug(f"搜索结果为空: 关键词={kw}")
                break

            for ent in entries:
                ann_url = (ent.get("url") or "").strip()
                if not ann_url:
                    continue
                if ann_url not in dedup:
                    ent["search_keyword"] = kw
                    dedup[ann_url] = ent
                    keyword_count += 1
                    have_find_new = True

            if not have_find_new:
                if page_index == 1:
                    get_logger().debug(f"搜索结果为空: 关键词={kw}")
                else:
                    get_logger().debug(f"搜索无新条目: 关键词={kw} 页码={page_index}")
                break

            _sleep_with_deadline(
                random.uniform(SEARCH_PAGE_SLEEP_MIN_SEC, SEARCH_PAGE_SLEEP_MAX_SEC), deadline
            )
            if page_index % 5 == 0:
                long_pause = random.uniform(10, 15)
                get_logger().debug(
                    f"搜索周期性冷却: 关键词={kw} 页码={page_index} 休眠={long_pause:.1f}秒"
                )
                _sleep_with_deadline(long_pause, deadline)

        get_logger().debug(f"关键词搜索完成: 关键词={kw}, 新增条目={keyword_count}")
        notify_update()
        if not had_connection_success:
            network_failed_kws += 1
        if not stop_all_search:
            kw_pause = random.uniform(SEARCH_KEYWORD_SLEEP_MIN_SEC, SEARCH_KEYWORD_SLEEP_MAX_SEC)
            get_logger().debug(f"关键词冷却: 关键词={kw} 休眠={kw_pause:.1f}秒")
            _sleep_with_deadline(kw_pause, deadline)

    out = list(dedup.values())
    notify_update()
    search_unavailable = stop_all_search or (
        keywords_attempted > 0 and network_failed_kws == keywords_attempted
    )
    get_logger().debug(
        f"搜索预筛选完成: 唯一条目数={len(out)}, 是否提前终止={stop_all_search}, "
        f"尝试关键词数={keywords_attempted}, 网络失败数={network_failed_kws}"
    )
    return out, search_unavailable


def scrape_ccgp(
    start_list_url: str,
    days: int = 3,
    max_pages: int = 30,
    keywords: Optional[List[str]] = FILTER_KEYWORDS,
    sleep_range: Tuple[float, float] = (DETAIL_SLEEP_MIN_SEC, DETAIL_SLEEP_MAX_SEC),
    use_search_prefilter: bool = True,
) -> List[TenderItem]:
    """
    查询公开公告的核心业务流程。
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
    deadline = (
        COLLECTION_STARTED_AT + COLLECTION_TIME_BUDGET_SEC
        if COLLECTION_TIME_BUDGET_SEC > 0 else None
    )

    # 加载之前处理过的 URL，避免重复处理和保存
    processed_urls = _load_processed_urls(CSV_OUTPUT_DIR)
    get_logger().info(f"Loaded {len(processed_urls)} processed URLs from {CSV_OUTPUT_DIR}")

    # 第一步：收集公告列表，优先处理上次未完成的候选
    pending_entries = _load_pending_entries()
    resume_from_checkpoint = bool(pending_entries)
    if resume_from_checkpoint:
        entries = pending_entries
        get_logger().info(f"从断点继续处理 {len(entries)} 条候选")
    elif use_search_prefilter:
        entries, search_unavailable = _collect_entries_from_search(
            session=session,
            keywords=keywords,
            start_date=(cutoff.date().strftime("%Y:%m:%d")),
            end_date=(now.date().strftime("%Y:%m:%d")),
            max_pages=max_pages,
            on_update=_write_pending_entries,
            deadline=deadline,
        )
        if search_unavailable:
            get_logger().warning(
                "搜索预筛选因网络请求失败或持续频率限制而不可用，"
                "已保存候选断点，抛出 SearchNetworkError 以便调用方回退至列表页模式"
            )
            raise SearchNetworkError(
                "search.ccgp.gov.cn 不可达或长等待重试后仍受频率限制"
            )
    else:
        list_urls = norm_list_page_urls(start_list_url, max_pages=max_pages)
        entries = []
        for list_url in list_urls:
            try:
                list_html = http_get(list_url, session, timeout=REQUEST_TIMEOUT_SEC)
            except Exception as e:
                _write_pending_entries(entries)
                get_logger().warning(f"列表页请求失败: {list_url} -> {e}")
                raise RuntimeError(f"列表页请求失败: {list_url}") from e
            if any(
                marker in list_html
                for marker in ("访问过于频繁", "频繁访问", "事件ID", "请求被阻断")
            ):
                _write_pending_entries(entries)
                get_logger().warning(f"列表页访问被限制: {list_url}")
                raise RuntimeError(f"列表页访问被限制: {list_url}")
            base_url = list_url.rsplit("/", 1)[0] + "/"
            page_entries = parse_list_page(list_html, base_url=base_url)
            if not page_entries:
                if not entries:
                    raise RuntimeError(f"列表页首页未解析到公告: {list_url}")
                break
            entries.extend(page_entries)
            page_pub_times = [
                parse_pub_datetime(ent.get("pub_raw", "")) for ent in page_entries
            ]
            page_pub_times = [pub_dt for pub_dt in page_pub_times if pub_dt]
            if len(page_pub_times) == len(page_entries) and max(page_pub_times) < cutoff:
                break

    _write_pending_entries(entries)
    pending_urls = {
        (entry.get("url") or "").strip() for entry in entries if entry.get("url")
    }

    def mark_entry_done(ann_url: str) -> None:
        if ann_url not in pending_urls:
            return
        pending_urls.remove(ann_url)
        remaining = [
            entry for entry in entries
            if (entry.get("url") or "").strip() in pending_urls
        ]
        _write_pending_entries(remaining)

    # 初始化关键词统计
    keyword_stats = {}
    for ent in entries:
        # 如果是列表页查询，可能没有 search_keyword，给一个默认值
        kw = ent.get("search_keyword", "list_page_scan")
        if kw not in keyword_stats:
            keyword_stats[kw] = {
                "found": 0,
                "detail_ok": 0,
                "kw_filter_pass": 0,
                "llm_filter_pass": 0,
                "req_found": 0,
                "saved": 0,
            }
        keyword_stats[kw]["found"] += 1

    results: List[TenderItem] = []
    seen_urls = set()
    failed_attachment_urls = set()
    count = 0

    filter_trace_file = _get_filter_trace_file()
    filter_trace_records: dict = {}
    get_logger().debug(f"过滤追踪文件: {filter_trace_file}")

    # 使用 tqdm 显示详情页处理进度
    for ent in tqdm(entries, desc="详情页处理进度", unit="条"):
        ann_url = (ent.get("url") or "").strip()
        kw = ent.get("search_keyword", "list_page_scan")
        if not ann_url:
            continue

        if ann_url in seen_urls:
            mark_entry_done(ann_url)
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
        if pub_dt and pub_dt < cutoff and (not use_search_prefilter or resume_from_checkpoint):
            _set_trace_result(filter_trace_records, ann_url, False, "older than DAYS window")
            _flush_filter_trace_csv(filter_trace_file, filter_trace_records)
            mark_entry_done(ann_url)
            continue

        if ann_url in processed_urls:
            _set_trace_result(filter_trace_records, ann_url, False, "processed in prev run")
            _flush_filter_trace_csv(filter_trace_file, filter_trace_records)
            mark_entry_done(ann_url)
            continue

        seen_urls.add(ann_url)

        # 查询详情网页，休眠控制防BAN
        _check_deadline(deadline)
        _sleep_with_deadline(random.uniform(*sleep_range), deadline)
        try:
            detail_html = http_get(ann_url, session, timeout=REQUEST_TIMEOUT_SEC)
        except Exception as e:
            _set_trace_result(filter_trace_records, ann_url, False, f"detail fetch failed: {e}")
            get_logger().warning(f"详情页请求失败: {ann_url} -> {e}")
            _flush_filter_trace_csv(filter_trace_file, filter_trace_records)
            continue

        # 详情页获取成功计数
        if kw in keyword_stats:
            keyword_stats[kw]["detail_ok"] += 1

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
            f"正在过滤公告: title={ent.get('title', '')} url={ann_url}"
        )
        
        # 第三步：关键过滤 （1）关键字精确过滤
        if not keyword_hit(combined, keywords):
            _set_trace_result(filter_trace_records, ann_url, False, "基于关键词的过滤发现不匹配")
            _flush_filter_trace_csv(filter_trace_file, filter_trace_records)
            mark_entry_done(ann_url)
            continue
        
        # 关键词过滤通过计数
        if kw in keyword_stats:
            keyword_stats[kw]["kw_filter_pass"] += 1

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
                    f"通过语义分析，该项目被过滤不保留的原因: {reason}",
                )
                get_logger().warning(f"通过语义分析，该项目被过滤不保留: {ann_url} -> {reason}")
                _flush_filter_trace_csv(filter_trace_file, filter_trace_records)
                mark_entry_done(ann_url)
                continue
            
            # LLM 过滤通过计数
            if kw in keyword_stats:
                keyword_stats[kw]["llm_filter_pass"] += 1
            get_logger().debug(
                f"通过基于语义的过滤: {ann_url} -> {second_filter.get('reason', '')}"
            )
        except Exception as e:
            get_logger().warning(f"基于语义分析的第二轮过滤失败，回退保留: {ann_url} -> {e}")

        # 通过所有验证，标记选定
        _set_trace_result(filter_trace_records, ann_url, True, "")

        # 完善从列表中获取不到的省市信息
        province = ent.get("region", "") or ""
        prov, city = guess_location(detail.get("location_text", ""))
        if not province:
            province = prov
        ai_project_title = ""
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
                        f"因黑名单跳过附件: name={a_name} url={a_url}"
                    )
                    continue

                if SKIP_REPEATED_FAILED_ATTACHMENTS and a_url in failed_attachment_urls:
                    get_logger().debug(f"跳过重复失败的附件: {a_url}")
                    continue

                try:
                    local_path = download_file(
                        session,
                        a_url,
                        out_dir=att_dir,
                        filename=a_name,
                        timeout=DOWNLOAD_TIMEOUT_SEC,
                    )
                    get_logger().warning(f"已下载附件: {a_url} -> {local_path}")

                    try:
                        text = extract_text_from_file(local_path)
                        if text and text.strip():
                            att_texts.append(text)
                            get_logger().warning(
                                f"从附件提取文本: {a_name} ({len(text)} 字符)"
                            )
                            count += 1
                        else:
                            try:
                                size = os.path.getsize(local_path)
                            except Exception:
                                size = -1
                            ext = (os.path.splitext(local_path)[1] or "").lower()
                            get_logger().warning(
                                "未提取到文本: "
                                f"name={a_name} ext={ext} size={size}B path={local_path} url={a_url}"
                            )
                    except Exception as e:
                        get_logger().warning(f"从文件提取文本失败: {a_name} -> {e}")
                except Exception as e:
                    failed_attachment_urls.add(a_url)
                    get_logger().warning(f"下载附件失败: {a_name} -> {e}")

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
                    ai_project_title = req.get("ai_project_title", "")
                    requirement_brief = req.get("requirement_brief", "")
                    requirement_desc = req.get("requirement_desc", "")
                    
                    if kw in keyword_stats and "无相关要求" not in requirement_desc:
                        keyword_stats[kw]["req_found"] += 1

                except Exception as e:
                    get_logger().warning(f"LLM 生成需求失败: {ann_url} -> {e}")

        # 第六步：保存结构化信息到 results 列表中
        results.append(
            TenderItem(
                announcement_title=ent.get("title", ""),
                announcement_url=ann_url,
                pub_time=ent.get("pub_iso", "") or "",
                province=province,
                city=city,
                project_name=detail.get("project_name", "") or ent.get("title", ""),
                ai_project_title=ai_project_title,
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
        write_csv(results, CSV_OUTPUT_DIR)
        mark_entry_done(ann_url)
        # 保存计数
        if kw in keyword_stats:
            keyword_stats[kw]["saved"] += 1

        _flush_filter_trace_csv(filter_trace_file, filter_trace_records)

    _flush_filter_trace_csv(filter_trace_file, filter_trace_records)
    _log_keyword_stats(keyword_stats)
    get_logger().debug(f"成功读取 {count} 个附件。")
    get_logger().debug(f"保存过滤追踪: {filter_trace_file}, 条目数={len(filter_trace_records)}")
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
    get_logger().debug(f"[OK] 保存成功: {CSV_OUTPUT_DIR}, 条目数={len(items)}")


if __name__ == "__main__":
    main()
