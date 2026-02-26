import argparse
import os
import random
import time
from datetime import datetime, timedelta
from hashlib import sha1
from typing import List, Optional, Tuple
from urllib.parse import urlparse

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
from ccgp.llm_requirements import generate_requirements
from ccgp.model import TenderItem
from ccgp.parse_detail import parse_detail_page
from ccgp.parse_index import parse_list_page
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


def _should_skip_attachment(url: str, name: str) -> bool:
    host = (urlparse(url).hostname or "").lower()
    if host in ATTACHMENT_BLOCKLIST_HOSTS:
        return True

    for kw in ATTACHMENT_BLOCKLIST_KEYWORDS:
        if kw and (kw in url or kw in name):
            return True
    return False


def scrape_ccgp(
    start_list_url: str,
    days: int = 3,
    max_pages: int = 30,
    keywords: Optional[List[str]] = FILTER_KEYWORDS,
    sleep_range: Tuple[float, float] = (DETAIL_SLEEP_MIN_SEC, DETAIL_SLEEP_MAX_SEC),
) -> List[TenderItem]:
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

    list_urls = norm_list_page_urls(start_list_url, max_pages=max_pages)

    results: List[TenderItem] = []
    seen_urls = set()
    failed_attachment_urls = set()
    count = 0

    for list_url in list_urls:
        try:
            list_html = http_get(list_url, session, timeout=REQUEST_TIMEOUT_SEC)
        except Exception as e:
            get_logger().warning(f"list page failed: {list_url} -> {e}")
            break

        base_url = list_url.rsplit("/", 1)[0] + "/"
        entries = parse_list_page(list_html, base_url=base_url)

        if not entries:
            break

        page_has_recent = False

        for ent in entries:
            ann_url = ent["url"]
            if ann_url in seen_urls:
                continue

            pub_dt = parse_pub_datetime(ent.get("pub_raw", ""))
            if pub_dt and pub_dt < cutoff:
                continue

            page_has_recent = True
            seen_urls.add(ann_url)

            try:
                time.sleep(random.uniform(*sleep_range))
                detail_html = http_get(ann_url, session, timeout=REQUEST_TIMEOUT_SEC)
            except Exception as e:
                get_logger().warning(f"detail failed: {ann_url} -> {e}")
                continue

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
            if not keyword_hit(combined, keywords):
                continue

            province = ent.get("region", "") or ""
            prov, city = guess_location(detail.get("location_text", ""))
            if not province:
                province = prov

            requirement_brief = ""
            requirement_desc = ""

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

                    if _should_skip_attachment(a_url, a_name):
                        get_logger().warning(
                            f"skip attachment by blocklist: name={a_name} url={a_url}"
                        )
                        continue

                    if (
                        SKIP_REPEATED_FAILED_ATTACHMENTS
                        and a_url in failed_attachment_urls
                    ):
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
                        get_logger().warning(
                            f"downloaded attachment: {a_url} -> {local_path}"
                        )

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
                            get_logger().warning(
                                f"extract_text_from_file failed: {a_name} -> {e}"
                            )
                    except Exception as e:
                        failed_attachment_urls.add(a_url)
                        get_logger().warning(f"download attachment failed: {a_name} -> {e}")

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
                        get_logger().warning(
                            f"LLM generate requirements failed: {ann_url} -> {e}"
                        )

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
                    purchasing_unit_contact_number=detail.get(
                        "purchasing_unit_contact_number", ""
                    ),
                    contact_name=detail.get("contact_name", ""),
                    contact_phone=detail.get("contact_phone", ""),
                    location_text=detail.get("location_text", ""),
                    budget=detail.get("budget", ""),
                )
            )

        if not page_has_recent:
            break

    get_logger().debug(f"successfully read {count} attachments.")
    return results


def main() -> None:
    setup_logging()

    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--start",
        default="https://www.ccgp.gov.cn/cggg/dfgg/gkzb/index.htm",
        help="公开招标公告列表页",
    )
    ap.add_argument("--days", type=int, default=DAYS, help="仅抓最近 N 天")
    ap.add_argument("--pages", type=int, default=PAGES, help="最大翻页数")
    args = ap.parse_args()

    items = scrape_ccgp(
        start_list_url=args.start,
        days=args.days,
        max_pages=args.pages,
        keywords=FILTER_KEYWORDS,
    )

    write_csv(items, CSV_OUTPUT_DIR)
    get_logger().debug(f"[OK] saved: {CSV_OUTPUT_DIR}, items={len(items)}")


if __name__ == "__main__":
    main()
