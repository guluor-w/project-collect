from typing import Dict, List
from urllib.parse import urljoin
from bs4 import BeautifulSoup

from ccgp.tools import clean_text, parse_pub_datetime

#-------------------------------分析列表页----------------------------------#
def parse_list_page(list_html: str, base_url: str) -> List[Dict[str, str]]:
    soup = BeautifulSoup(list_html, "lxml")
    out = []

    for li in soup.select("ul.c_list_bid > li"):
        a = li.find("a", href=True)
        if not a:
            continue

        title = clean_text(a.get_text(" ", strip=True))
        href = a["href"].strip()
        url = urljoin(base_url, href)

        ems = li.find_all("em")

        # 发布时间：<em>2026-01-26 15:31</em>
        pub_em = ""
        if ems:
            pub_em = ems[0].get_text(" ", strip=True)
        pub_dt = parse_pub_datetime(pub_em or "")

        # 地域：<em>江苏</em>（列表页一般到“省/地区”）
        region = ""
        if len(ems) >= 2:
            region = clean_text(ems[1].get_text(" ", strip=True))

        out.append({
            "title": title,
            "url": url,
            "pub_raw": pub_em or "",
            "pub_iso": pub_dt.isoformat(timespec="minutes") if pub_dt else "",
            "region": region,
        })
    return out
