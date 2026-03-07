import os
import re
from typing import Dict, List
from bs4 import BeautifulSoup
from urllib.parse import urljoin,urlsplit

from ccgp.config import FIELD_ALIASES, RE_DATE_YMD_HM, RE_MONEY
from ccgp.tools import clean_text, parse_pub_datetime, extract_money
from utils.mylogger import get_logger

#------------------------------解析匹配detail页面内容----------------------------------#
def parse_ccgp_table(soup: BeautifulSoup) -> Dict[str, str]:
    """
    解析 ccgp 详情页面常见的 “公告概要” 表格：
    通常结构为: <td class='title'>字段名</td><td>字段值</td>
    返回一个字典: {字段名: 字段值}
    """
    kv = {}

    # 找所有 title 单元格
    for td in soup.select("td.title"):
        key = clean_text(td.get_text(" ", strip=True))
        # 值通常在下一个 td
        vtd = td.find_next_sibling("td")
        if not vtd:
            continue
        val = clean_text(vtd.get_text(" ", strip=True))
        if key and val:
            kv[key] = val
    return kv

def pick_by_alias(kv: Dict[str, str], aliases: List[str]) -> str:
    """
    从字典 kv 中，尝试按 aliases 列表顺序查找值，返回找到的第一个非空值。
    """
    for a in aliases:
        a = a.strip()
        if not a:
            continue
        if a in kv:
            return kv[a]
    return ""

#---------------------------------分析需求详细描述相关-------------------------------------#
def extract_ccgp_attachments(soup, page_url: str):
    """
    从详情页 soup 中提取可能的附件链接：
    1. 查找 'a[ignore="1"][href]'
    2. 查找 'a.bizDownload'（特殊类名）
    3. 查找任意符合后缀 (.pdf, .docx, .xlsx 等) 的 'a[href]'
    返回去重后的附件列表 [{"name":..., "url":..., "kind":...}, ...]
    """ 
    out = []

    # 允许的文件后缀（保持你的逻辑）
    ALLOWED_EXTENSIONS = {'.pdf', '.docx', '.xlsx', '.txt', '.zip'}

    def strip_qs(url: str) -> str:
        try:
            p = urlsplit(url)
            return f"{p.scheme}://{p.netloc}{p.path}" if p.scheme and p.netloc else p.path
        except Exception:
            return (url or "").split("?", 1)[0].split("#", 1)[0]

    # 筛选后缀，不要下载一些无关配置文件
    def is_allowed_file(url: str) -> bool:
        url_lower = strip_qs(url or "").lower()
        return any(url_lower.endswith(ext) for ext in ALLOWED_EXTENSIONS)

    def normalize_href(href: str) -> str:
        href = (href or "").strip()
        if not href:
            return ""
        if href.startswith("//"):
            return "https:" + href
        return href

    def guess_name_from_a(a, fallback_url: str = "") -> str:
        # 1) 文本
        t = (a.get_text(" ", strip=True) or "").strip()
        if t:
            return t
        # 2) 常见属性
        for k in ("download", "title", "data-filename", "data-file", "filename"):
            v = (a.get(k) or "").strip()
            if v:
                return v
        # 3) url basename
        if fallback_url:
            try:
                base = os.path.basename(strip_qs(fallback_url))
                if base:
                    return base
            except Exception:
                pass
        return ""

    def name_has_allowed_ext(name: str) -> bool:
        n = (name or "").strip().lower()
        return any(n.endswith(ext) for ext in ALLOWED_EXTENSIONS)

    # 1) 正文“相关附件” a[ignore="1"]（这里经常是外站直链，且带 accessCode）
    for a in soup.select('a[ignore="1"][href]'):
        href = normalize_href(a.get("href") or "")
        if not href:
            continue
        url = href if href.startswith("http") else urljoin(page_url, href)

        # 关键：用 strip_qs 后判断后缀
        if is_allowed_file(url):
            out.append({
                "name": guess_name_from_a(a, fallback_url=url) or os.path.basename(strip_qs(url)),
                "url": url,
                "kind": "direct"
            })

    # 2) 表格“附件：bizDownload”（href 为空，id 是 uuid；文本含真实文件名）
    for a in soup.select("a.bizDownload"):
        href = normalize_href(a.get("href") or "")
        uuid = (a.get("id") or "").strip()
        name = guess_name_from_a(a)  # 通常就是“xxx.zip/pdf”

        if href:
            url = href if href.startswith("http") else urljoin(page_url, href)
            if is_allowed_file(url):
                out.append({"name": guess_name_from_a(a, fallback_url=url) or os.path.basename(strip_qs(url)),
                            "url": url, "kind": "bizDownload_href"})
            else:
                # href 可能是无后缀的下载入口（带 uuid=...），仍按“名字后缀”原则收录
                if name and name_has_allowed_ext(name):
                    out.append({"name": name, "url": url, "kind": "bizDownload_href_name_guard"})
        elif uuid:
            # 典型：CCGP 统一下载接口
            url = f"https://download.ccgp.gov.cn/oss/download?uuid={uuid}"
            # 注意：url 没后缀，必须靠 name 判断后缀（保持你的筛选原则）
            if name and name_has_allowed_ext(name):
                out.append({"name": name, "url": url, "kind": "bizDownload_uuid"})
            else:
                # 若文本被替换/为空，尝试从 onclick/title 里抓文件名再判断（仍不突破后缀守门）
                blob = " ".join([(a.get("onclick") or "").strip(), (a.get("title") or "").strip()])
                m = re.search(r"([^\"'\s<>]+?\.(?:pdf|docx|xlsx|txt|zip))", blob, flags=re.I)
                if m:
                    fname = m.group(1).strip()
                    if name_has_allowed_ext(fname):
                        out.append({"name": fname, "url": url, "kind": "bizDownload_uuid_attr_fname"})

    # 3) 兜底：页面上任何 href 直链（只收“看起来是附件”的，且后缀命中）
    #    防止漏掉 ignore!=1 的附件链接
    for a in soup.select("a[href]"):
        href = normalize_href(a.get("href") or "")
        if not href:
            continue
        hl = href.lower()
        if hl.startswith(("javascript:", "mailto:", "#")):
            continue

        url = href if href.startswith("http") else urljoin(page_url, href)

        # 只要后缀命中才收（保持严格）
        if is_allowed_file(url):
            out.append({
                "name": guess_name_from_a(a, fallback_url=url) or os.path.basename(strip_qs(url)),
                "url": url,
                "kind": "direct_any_a"
            })

    # 去重（按 url）
    seen = set()
    uniq = []
    for x in out:
        u = (x.get("url") or "").strip()
        if not u or u in seen:
            continue
        seen.add(u)
        uniq.append(x)

    return uniq

#---------------------------------分析详情页主流程-------------------------------------#
def parse_detail_page(detail_html: str, page_url: str) -> Dict[str, str]:
    """
    解析详情页 HTML，提取关键字段信息：
    - full_text: 页面纯文本
    - project_name: 项目名称
    - budget: 预算金额
    - deadline: 截止时间
    - company_name: 采购单位名称
    - contact_name/phone: 联系人及电话
    - locations: 地址信息
    - attachments: 附件列表
    """
    soup = BeautifulSoup(detail_html, "lxml")
    full_text = clean_text(soup.get_text(" ", strip=True))

    kv = parse_ccgp_table(soup)

    # 1) 项目名称
    project_name = pick_by_alias(kv, FIELD_ALIASES["project_name"])

    # 2) 预算
    budget_text = pick_by_alias(kv, FIELD_ALIASES["budget"])
    budget = extract_money(budget_text) if budget_text else ""

    # 3) 截止时间（没找到严格的，就用全文找第一个带时分的日期兜底）
    deadline = pick_by_alias(kv, FIELD_ALIASES["deadline"])
    if deadline:
        # 规范化成 “YYYY年MM月DD日” 优先
        dt = parse_pub_datetime(deadline)
        if dt:
            deadline = f"{dt.year}年{dt.month:02d}月{dt.day:02d}日"
        else:
            # 尝试从文本里抽日期时间
            m = RE_DATE_YMD_HM.search(deadline)
            if m:
                y = int(m.group("y")); mo = int(m.group("m")); d = int(m.group("d"))
                deadline = f"{y:04d}年{mo:02d}月{d:02d}日"

    else:
        # 兜底：全文找一个可能的截止/开标时间（不保证准确）
        m = RE_DATE_YMD_HM.search(full_text)
        if m:
            y = int(m.group("y")); mo = int(m.group("m")); d = int(m.group("d"))
            deadline = f"{y:04d}年{mo:02d}月{d:02d}日"
        else:
            deadline = ""

    # 4) 采购人/企业名称（按“采购人”输出）
    company_name = pick_by_alias(kv, FIELD_ALIASES["purchaser_name"])
    purchasing_unit_contact_number = pick_by_alias(kv, FIELD_ALIASES["purchasing_unit_contact_number"])

    # 5) 联系人、电话
    contact_name = pick_by_alias(kv, FIELD_ALIASES["contact_name"])
    contact_phone = pick_by_alias(kv, FIELD_ALIASES["contact_phone"])
    # 兜底：全文找电话号码
    if not contact_phone:
        m = re.search(r"(1\d{10})", full_text) # 手机号
        if m:
            contact_phone = m.group(1)
        else:
            m = re.search(r"(\d{3,4}-\d{7,8})", full_text) # 固话
            if m:
                contact_phone = m.group(1)

    # 6) 地点（尽量抽地址段）
    location_text = pick_by_alias(kv, FIELD_ALIASES["location"])
    # 兜底：如果全文包含“地址”，取附近
    if not location_text:
        m = re.search(r"地址[:：]?\s*([^。；;]{5,80})", full_text)
        location_text = clean_text(m.group(1)) if m else ""

    # 7) 需求附件
    attachments = extract_ccgp_attachments(soup, page_url)
    return {
        "full_text": full_text,
        "project_name": project_name,
        "budget": budget,
        "deadline": deadline,
        "company_name": company_name,
        "purchasing_unit_contact_number": purchasing_unit_contact_number,
        "contact_name": contact_name,
        "contact_phone": contact_phone,
        "location_text": location_text,
        "attachments": attachments,
    }