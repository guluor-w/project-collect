from typing import Dict, List
from urllib.parse import urljoin
import re

from bs4 import BeautifulSoup

from ccgp.tools import clean_text, parse_pub_datetime
from ccgp.config import PROVINCES


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
        pub_em = ems[0].get_text(" ", strip=True) if ems else ""
        pub_dt = parse_pub_datetime(pub_em or "")

        region = clean_text(ems[1].get_text(" ", strip=True)) if len(ems) >= 2 else ""

        out.append(
            {
                "title": title,
                "url": url,
                "pub_raw": pub_em or "",
                "pub_iso": pub_dt.isoformat(timespec="minutes") if pub_dt else "",
                "region": region,
            }
        )
    return out


def parse_search_page(search_html: str, base_url: str = "https://search.ccgp.gov.cn/") -> List[Dict[str, str]]:
    soup = BeautifulSoup(search_html, "lxml")
    out: List[Dict[str, str]] = []
    seen = set()

    def extract_ohtmlurls(html: str) -> List[str]:
        m = re.search(r'ohtmlurls\s*=\s*"([^"]+)"', html, flags=re.I | re.S)
        if not m:
            return []
        return [u.strip() for u in m.group(1).split(",") if u.strip()]

    def parse_span_meta(span_text: str) -> Dict[str, str]:
        txt = clean_text(span_text or "")
        parts = [clean_text(p) for p in txt.split("|")]
        pub_raw = parts[0] if parts else ""
        pub_dt = parse_pub_datetime(pub_raw)

        region = ""
        for p in parts:
            p2 = clean_text(p)
            if not p2:
                continue
            if p2 in PROVINCES:
                region = p2
        return {
            "pub_raw": pub_raw,
            "pub_iso": pub_dt.isoformat(timespec="minutes") if pub_dt else "",
            "region": region,
        }

    lis = soup.select("ul.vT-srch-result-list-bid > li")
    ohtmlurls = extract_ohtmlurls(search_html)

    for idx, li in enumerate(lis):
        a = li.find("a")
        if not a:
            continue
        title = clean_text(a.get_text("", strip=True))
        if not title:
            continue

        href = clean_text(a.get("href", ""))
        if (not href) or ("ccgp.gov.cn/cggg/" not in href.lower()):
            if idx < len(ohtmlurls):
                href = ohtmlurls[idx]
        if not href:
            continue

        url = urljoin(base_url, href)
        if url in seen:
            continue
        seen.add(url)

        span = li.find("span")
        meta = parse_span_meta(span.get_text(" ", strip=True) if span else "")
        out.append(
            {
                "title": title,
                "url": url,
                "pub_raw": meta.get("pub_raw", ""),
                "pub_iso": meta.get("pub_iso", ""),
                "region": meta.get("region", ""),
            }
        )

    if out:
        return out

    # fallback: 旧列表页结构
    by_regular = parse_list_page(search_html, base_url=base_url)
    if by_regular:
        return by_regular

