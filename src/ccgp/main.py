import random
import time
import os
from datetime import datetime, timedelta
from typing import List, Optional, Tuple
import requests
from hashlib import sha1

from ccgp.config import FILTER_KEYWORDS, USER_AGENT, SG_TZ, ENABLE_LLM_REQUIREMENTS, ENABLE_READ_ATTACHMENTS, ATTACHMENTS_DIR, CSV_OUTPUT_DIR, DAYS, PAGES
from ccgp.model import TenderItem
from ccgp.parse_index import parse_list_page
from ccgp.parse_detail import parse_detail_page
from ccgp.tools import http_get, norm_list_page_urls, parse_pub_datetime, keyword_hit, write_csv, guess_location
from ccgp.tools import download_file, extract_text_from_file
from ccgp.llm_requirements import generate_requirements
from utils.mylogger import setup_logging, get_logger

def scrape_ccgp(
    start_list_url: str,
    days: int = 3,
    max_pages: int = 30,
    keywords: Optional[List[str]] = FILTER_KEYWORDS,
    sleep_range: Tuple[float, float] = (2,4), # 每次抓取随机休眠5-8秒
) -> List[TenderItem]:
    session = requests.Session()
    session.headers.update({
        "User-Agent": USER_AGENT,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        "Connection": "keep-alive",
    })

    now = datetime.now(tz=SG_TZ)
    cutoff = now - timedelta(days=days)

    list_urls = norm_list_page_urls(start_list_url, max_pages=max_pages)

    results: List[TenderItem] = []
    seen_urls = set()

    count = 0
    for list_url in list_urls:
        try:
            list_html = http_get(list_url, session)
        except Exception as e:
            # 某些页可能不存在（比如只有 25 页），遇到 404 之类就停止
            get_logger().warning(f"list page failed: {list_url} -> {e}")
            break

        base_url = list_url.rsplit("/", 1)[0] + "/"
        entries = parse_list_page(list_html, base_url=base_url)

        if not entries:
            # 没有条目：停止
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
                detail_html = http_get(ann_url, session)
            except Exception as e:
                get_logger().warning(f"detail failed: {ann_url} -> {e}")
                continue

            detail = parse_detail_page(detail_html, page_url=ann_url)
            # 关键词过滤：标题 + 详情全文 + 采购需求章节
            combined = " ".join([
                ent.get("title", ""),
                detail.get("project_name", ""),
                detail.get("full_text", ""),
            ])

            get_logger().debug(f"filtering the announcement: ent.title={ent.get('title','')} url={ann_url}")
            if not keyword_hit(combined, keywords):
                continue

            province = ent.get("region", "") or ""
            prov, city = guess_location(detail.get("location_text", ""))
            if not province:
                province = prov

            #------------------------------- 抓附件文本---------------------------------#
            if(ENABLE_READ_ATTACHMENTS):
                attachments = detail.get("attachments", []) or []
                att_texts = []
                att_dir = f"{ATTACHMENTS_DIR}{sha1(ann_url.encode('utf-8')).hexdigest()[:12]}_{datetime.now().strftime('%Y%m%d')}"

                for a in attachments[:3]:  # 限制附件个数
                    try:
                        local_path = download_file(session, a["url"], out_dir=att_dir, filename=a.get("name"))
                        get_logger().warning(f"downloaded attachment: {a.get('url')} -> {local_path}")
                        try:    
                            t = extract_text_from_file(local_path)
                            if t and t.strip():
                                att_texts.append(t)
                                get_logger().warning(f"extracted text from attachment: {a.get('name')} ({len(t)} chars)")
                                count += 1
                            else:
                                    try:
                                        size = os.path.getsize(local_path)
                                    except Exception:
                                        size = -1
                                    ext = (os.path.splitext(local_path)[1] or "").lower()
                                    get_logger().warning(
                                        f"no text extracted: name={a.get('name')} ext={ext} size={size}B path={local_path} url={a.get('url')}"
                                    )
                        except Exception as e:
                            get_logger().warning(f"extract_text_from_file failed: {a.get('name')} -> {e}")
                    except Exception as e:
                        get_logger().warning(f"download attachment failed: {a.get('name')} -> {e}")

                if(ENABLE_LLM_REQUIREMENTS):
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
                        requirement_brief = ""
                        requirement_desc = ""
                else:
                    requirement_brief = ""
                    requirement_desc = ""
            else:
                requirement_brief = ""
                requirement_desc = ""        
            #------------------------------- 结束抓附件文本---------------------------------#    
            results.append(TenderItem(
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
            ))

        # 如果整页都没有“最近 days 天”的内容，且页面时间有解析到，说明已经翻到更早了，可停止
        if not page_has_recent:
            break

    get_logger().debug(f"successfully read {count} attachments.")  
    return results

def main():
    setup_logging()
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default="https://www.ccgp.gov.cn/cggg/dfgg/gkzb/index.htm", help="公开招标公告列表页")
    ap.add_argument("--days", type=int, default=DAYS, help="只抓最近 N 天")
    ap.add_argument("--pages", type=int, default=PAGES, help="最多翻页数")
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
