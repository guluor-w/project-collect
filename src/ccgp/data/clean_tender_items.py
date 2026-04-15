"""
数据清洗脚本：针对 tender_items.csv 文件进行清洗，生成 cleaned_requirements.csv。

功能：
1. 筛选 requirement_brief 不为"无相关要求"的数据。
2. 新建数据表格，包含指定字段。
3. 字段名称变更及默认值设置。
4. 字段内容处理（日期格式标准化、预算金额转换、需求内容清洗/截断/追加来源说明/富文本格式转换）。
5. 地址标准化：
   a. 若清洗后的省份/市区已在 province_city_codes.csv 编码表中，直接保留，跳过高德 API 调用。
      否则通过高德地址编码接口获取 province、city、adcode（需设置 AMAP_GEOCODING_KEY），
      请求失败时填写"待人工处理"。
   b. 严格标准化"省份名称"和"市区名称"，依据 province_city_codes.csv 的省市编码表：
      1) 若清洗后的省份/市区已在编码表中则保留。
      2) 否则用高德省份/城市替换，若匹配则保留。
      3) 否则通过高德adcode反查编码表，若找到则替换；仍找不到则填写"待人工处理"。
6. 将标准化成功（非"待人工处理"）的省市回填到 tender_items.csv 的 province/city 字段。
"""

import os
import re
import csv
import html
import tempfile
from datetime import datetime
from typing import Dict, Set, Tuple

import requests
from dotenv import load_dotenv

load_dotenv()

INPUT_FILE = os.path.join(os.path.dirname(__file__), "tender_items.csv")
OUTPUT_FILE = os.path.join(os.path.dirname(__file__), "cleaned_requirements.csv")
PROVINCE_CITY_CODES_FILE = os.path.join(os.path.dirname(__file__), "province_city_codes.csv")

OUTPUT_COLUMNS = [
    "所有分类名称",
    "需求分类名称",
    "需求子类名称",
    "活动主题",
    "需求主题",
    "需求简介",
    "需求内容",
    "发布时间",
    "截止时间",
    "发布单位名称",
    "发布单位概述",
    "发布人姓名",
    "发布人电话",
    "发布人邮箱",
    "省份名称",
    "市区名称",
    "预算金额",
    "参考地址",
    "来源链接",
    "高德省份",
    "高德城市",
    "高德adcode",
]

AMAP_GEO_URL = "https://restapi.amap.com/v3/geocode/geo"
FALLBACK_VALUE = "待人工处理"

# 共享的 HTTP Session，复用底层 TCP 连接，降低每次请求的开销
_SESSION = requests.Session()

# 省级行政区和地级市常见后缀，用于将简称补全为编码表规范全称（长后缀在前以避免部分匹配）
_PROV_SUFFIXES = ("壮族自治区", "维吾尔自治区", "回族自治区", "自治区", "省", "市")
_CITY_SUFFIXES = ("自治州", "地区", "市", "区", "县", "盟", "旗")


def _canonicalize(raw: str, known: frozenset, suffixes: tuple) -> str:
    """尝试将简称补全为编码表中的规范全称。

    如 "北京" → "北京市"，"河北" → "河北省"。
    若 raw 已在 known 中则直接返回；否则逐一追加后缀后查找；均不命中时原样返回。
    """
    if not raw or raw in known:
        return raw
    for suf in suffixes:
        candidate = raw + suf
        if candidate in known:
            return candidate
    return raw


# --------------- 省市编码表加载 ---------------

def load_province_city_codes(
    codes_file: str = PROVINCE_CITY_CODES_FILE,
) -> Tuple[Set[Tuple[str, str]], Dict[str, Tuple[str, str]]]:
    """加载省市编码 CSV，返回两个查询结构。

    Returns:
        valid_pairs: set of (省, 市) tuples that are valid in the reference.
        adcode_map: dict mapping 编码 -> (省, 市).
    """
    valid_pairs: Set[Tuple[str, str]] = set()
    adcode_map: Dict[str, Tuple[str, str]] = {}

    try:
        with open(codes_file, newline="", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            for row in reader:
                province = (row.get("省") or "").strip()
                city = (row.get("市") or "").strip()
                code = (row.get("编码") or "").strip()
                if province and city:
                    valid_pairs.add((province, city))
                if code and province and city:
                    if code in adcode_map:
                        print(f"警告：省市编码表中存在重复编码 {code!r}，保留首次出现的记录。")
                    else:
                        adcode_map[code] = (province, city)
    except Exception as e:
        print(f"警告：加载省市编码表失败: {e}")

    return valid_pairs, adcode_map


def normalize_location(
    province: str,
    city: str,
    amap_province: str,
    amap_city: str,
    amap_adcode: str,
    valid_pairs: Set[Tuple[str, str]],
    adcode_map: Dict[str, Tuple[str, str]],
) -> Tuple[str, str]:
    """根据三步规则严格标准化省份名称和市区名称。

    步骤：
    1. 若 (province, city) 在编码表中，直接保留。
    2. 若 (amap_province, amap_city) 在编码表中，用它们替换。
    3. 用 amap_adcode 在编码表中反查；找到则使用对应省市，否则返回"待人工处理"。
    """
    # 步骤 1：原始省市已在编码表中
    if province and city and (province, city) in valid_pairs:
        return province, city

    # 步骤 2：高德省市在编码表中
    if amap_province and amap_city and (amap_province, amap_city) in valid_pairs:
        return amap_province, amap_city

    # 步骤 3：通过高德 adcode 反查编码表
    if amap_adcode and amap_adcode != FALLBACK_VALUE:
        result = adcode_map.get(amap_adcode)
        if result:
            return result

    return FALLBACK_VALUE, FALLBACK_VALUE


def geocode_address(address: str, api_key: str) -> tuple:
    """使用高德地图地理编码接口获取省份、城市和adcode。

    Args:
        address: 待编码的地址字符串（对应"参考地址"字段）。
        api_key: 高德地图 Web 服务 API Key（环境变量 AMAP_GEOCODING_KEY）。

    Returns:
        (province, city, adcode) 三元组。
        当地址或 key 为空、请求失败或返回结果为空时，三个字段均返回"待人工处理"。
    """
    if not address or not api_key:
        return FALLBACK_VALUE, FALLBACK_VALUE, FALLBACK_VALUE

    try:
        resp = _SESSION.get(
            AMAP_GEO_URL,
            params={"address": address, "key": api_key, "output": "json"},
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()

        if data.get("status") != "1" or not data.get("geocodes"):
            return FALLBACK_VALUE, FALLBACK_VALUE, FALLBACK_VALUE

        geo = data["geocodes"][0]

        def _str_field(value) -> str:
            """Convert a field that may be a list or string to a plain string."""
            if isinstance(value, list):
                value = value[0] if value else ""
            return str(value).strip() if value else ""

        province = _str_field(geo.get("province")) or FALLBACK_VALUE
        city_raw = _str_field(geo.get("city"))
        # 直辖市等场景下 Amap 返回 city 为空；按接口语义以省份值回填，避免误标为失败
        city = city_raw if city_raw else (_str_field(geo.get("province")) or FALLBACK_VALUE)
        adcode = _str_field(geo.get("adcode")) or FALLBACK_VALUE
        return province, city, adcode
    except (requests.RequestException, ValueError, KeyError):
        return FALLBACK_VALUE, FALLBACK_VALUE, FALLBACK_VALUE


def parse_datetime(value: str) -> str:
    """将各种日期/时间字符串标准化为 'YYYY-MM-DD HH:MM:SS' 格式。
    
    支持的输入格式：
    - ISO 8601：'2026-04-05T09:10+08:00'
    - 日期字符串：'2026-04-24'
    - 中文日期：'2026年03月27日'
    - 空字符串或无法解析的值返回原值。
    """
    value = value.strip()
    if not value:
        return value

    formats_to_try = [
        "%Y-%m-%dT%H:%M%z",       # 2026-04-05T09:10+08:00
        "%Y-%m-%dT%H:%M:%S%z",    # 2026-04-05T09:10:00+08:00
        "%Y-%m-%dT%H:%M",         # 2026-04-05T09:10
        "%Y-%m-%d %H:%M:%S",      # 2026-04-05 09:10:00
        "%Y-%m-%d %H:%M",         # 2026-04-05 09:10
        "%Y-%m-%d",               # 2026-04-24
    ]

    # 处理中文日期格式，如 '2026年03月27日'
    chinese_date_pattern = re.compile(r"(\d{4})年(\d{2})月(\d{2})日")
    m = chinese_date_pattern.fullmatch(value)
    if m:
        return f"{m.group(1)}-{m.group(2)}-{m.group(3)} 00:00:00"

    for fmt in formats_to_try:
        try:
            dt = datetime.strptime(value, fmt)
            return dt.strftime("%Y-%m-%d %H:%M:%S")
        except ValueError:
            continue

    # 无法解析时返回原值
    return value


def parse_budget(value: str) -> str:
    """将预算金额转换为以万元为单位、保留两位小数的纯数字字符串。
    
    输入示例：'380.28万元' -> '380.28'
    若无法解析则返回原值。
    """
    value = value.strip()
    if not value:
        return value

    # 提取数字部分（支持整数和小数）
    num_match = re.search(r"[\d,.]+", value)
    if not num_match:
        return value

    num_str = num_match.group().replace(",", "")
    try:
        amount = float(num_str)
    except ValueError:
        return value

    # 如果单位是元（非万元），则转换为万元
    if "万元" not in value and "万" not in value:
        amount = amount / 10000

    return f"{amount:.2f}"


def clean_contact_phone(value: str) -> str:
    """清洗发布人电话：仅保留第一组电话。"""
    text = (value or "").strip()
    if not text:
        return ""

    # 先匹配手机号，再匹配带区号/分机的固话，最后兜底匹配连续数字。
    phone_patterns = [
        re.compile(r"(?<!\d)(?:\+?86[-\s]?)?1[3-9]\d{9}(?!\d)"),
        re.compile(
            r"(?<!\d)(?:0\d{2,3}[-\s]?)?\d{7,8}(?:[-\s]\d{1,6})?(?:（\d+(?:[、,，]\d+)*）|\(\d+(?:[、,，]\d+)*\))?(?!\d)"
        ),
        re.compile(r"(?<!\d)\d{6,}(?!\d)"),
    ]

    best_match = None
    for pattern in phone_patterns:
        m = pattern.search(text)
        if not m:
            continue
        if best_match is None or m.start() < best_match.start():
            best_match = m

    if best_match:
        first = best_match.group(0).strip()
        # 去除结尾可能残留的分隔符号
        return first.rstrip("；;，,。、. ")

    # 如果没有提取到电话，按常见分隔符裁剪第一段，避免污染下游字段。
    # 覆盖：中英文句号/逗号、分号、顿号。
    fallback_parts = re.split(r"[；;，,。、.]", text, maxsplit=1)
    return fallback_parts[0].strip() if fallback_parts else text


def plaintext_to_richtext(plaintext: str) -> str:
    """将纯文本转换为富文本（HTML）格式。

    支持的格式：
    - 【内容】 -> 带样式的加粗 Span
    - **内容** -> <strong>内容</strong>
    - 以 - 或 * 开头的行 -> 无序列表 <ul><li>...</li></ul>
    - 以数字. 开头的行 -> 有序列表 <ol><li>...</li></ol>
    - 其余行 -> 段落 <p>...</p>
    """
    if not plaintext:
        return ""

    text = str(plaintext).strip()
    # 统一换行符
    text = text.replace('\r\n', '\n')
    # 转义 HTML 特殊字符，防止原始文本破坏 HTML 结构
    text = html.escape(text)

    # 1. 优先处理原有自定义格式：【内容】 -> 带样式的 Span
    def replace_custom_style(match):
        content = match.group(1)
        return f'<span style="color: rgb(0, 0, 0); font-size: 15px;"><strong>{content}</strong></span>'

    text = re.sub(r'\【(.*?)\】', replace_custom_style, text)

    # 2. 增加 Markdown 风格加粗支持：**内容** -> <strong>内容</strong>
    text = re.sub(r'\*\*(.*?)\*\*', r'<strong>\1</strong>', text)

    # 3. 分段处理（按双换行符分割段落）
    paragraphs = text.split('\n\n')
    new_paragraphs = []

    for p in paragraphs:
        lines = [line.strip() for line in p.split('\n') if line.strip()]
        if not lines:
            continue

        first_line = lines[0]

        # 检测是否为无序列表 (以 - 或 * 开头)
        if first_line.startswith('- ') or first_line.startswith('* '):
            list_items = []
            for line in lines:
                # 移除列表标记
                item_content = re.sub(r'^[-*]\s+', '', line)
                list_items.append(f'<li>{item_content}</li>')
            new_paragraphs.append(f'<ul>{"".join(list_items)}</ul>')

        # 检测是否为有序列表 (以数字. 开头，允许数字后紧接内容)
        elif re.match(r'^\d+\.', first_line):
            list_items = []
            for line in lines:
                # 移除数字标记（允许数字后无空格）
                item_content = re.sub(r'^\d+\.\s*', '', line)
                list_items.append(f'<li>{item_content}</li>')
            new_paragraphs.append(f'<ol>{"".join(list_items)}</ol>')

        else:
            # 普通段落：每一行都作为独立段落处理
            for line in lines:
                new_paragraphs.append(f'<p>{line}</p>')

    return ''.join(new_paragraphs)


def clean_requirement_desc(desc: str) -> str:
    """清洗需求内容字段：删除AI生成的章节标签和无关词语。

    - 删除形如 【xxx】、【xxx】：、【xxx】: 的章节标签（含可选冒号和尾随空白）。
    - 删除"本项目"、"本项目的"、"该项目"、"该项目的"、"旨在"等无关词语。
    """
    if not desc:
        return desc
    # 删除【xxx】类章节标签（含可选中文或英文冒号及尾随空白）
    desc = re.sub(r'【.*?】[：:]?\s*', '', desc)
    # 删除特定无关词语（顺序：先删带"的"的形式，再删不带"的"的形式，避免部分匹配遗漏）
    desc = re.sub(r'本项目的|本项目|该项目的|该项目|旨在', '', desc)
    return desc.strip()


def truncate_desc_for_limit(desc: str, max_len: int) -> str:
    """将字符串截断到不超过 max_len 个字符，在中文句号或换行符处截断。

    若字符串本身不超过限制则原样返回；否则在 max_len 范围内找最后一个
    中文句号（。）或换行符（\n）作为截断点；若找不到则直接截断。
    """
    if max_len <= 0:
        return ""
    if len(desc) <= max_len:
        return desc
    truncated = desc[:max_len]
    for i in range(len(truncated) - 1, -1, -1):
        if truncated[i] in ('。', '\n'):
            return truncated[:i + 1]
    return truncated


def build_requirement_content(desc: str, announcement_url: str) -> str:
    """清洗需求内容、截断至1000字符限制、追加来源说明并转换为富文本格式。

    处理步骤：
    1. 删除AI生成的章节标签和无关词语。
    2. 确保拼合后的总长度不超过1000字符（在中文句号或换行符处截断）。
    3. 在需求内容末尾追加来源说明段落。
    4. 将拼合结果转换为富文本（HTML）格式。
    """
    source_note = f"本需求来源于中国政府采购网，详情请见招标信息： {announcement_url}"
    # 1. 清洗
    cleaned_desc = clean_requirement_desc(desc)
    if cleaned_desc:
        # 2. 计算留给 desc 的最大字符数，确保拼合后不超过1000字符
        suffix = f"\n\n{source_note}"
        max_desc_len = 1000 - len(suffix)
        if max_desc_len <= 0:
            # source_note 本身已超出限制，截断 source_note 至1000字符后使用
            combined = truncate_desc_for_limit(source_note, 1000)
        else:
            cleaned_desc = truncate_desc_for_limit(cleaned_desc, max_desc_len)
            # 3. 拼合
            combined = f"{cleaned_desc}{suffix}"
    else:
        combined = truncate_desc_for_limit(source_note, 1000)
    # 4. 富文本格式转换
    return plaintext_to_richtext(combined)


def writeback_to_input(
    input_file: str,
    writeback_map: Dict[str, Tuple[str, str]],
) -> None:
    """将标准化后的省市回填到 tender_items.csv 的 province/city 字段。

    只回填标准化成功（非"待人工处理"）的记录，以 announcement_url 作为匹配键。

    Args:
        input_file: tender_items.csv 文件路径。
        writeback_map: announcement_url -> (province, city) 的映射，
                       仅包含已成功标准化的条目。
    """
    if not writeback_map:
        return

    with open(input_file, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        fieldnames = reader.fieldnames or []
        rows = list(reader)

    updated_count = 0
    for row in rows:
        url = row.get("announcement_url", "")
        if url in writeback_map:
            prov, city = writeback_map[url]
            row["province"] = prov
            row["city"] = city
            updated_count += 1

    # 先写入同目录下的临时文件，写入成功后原子替换原文件，避免中途异常导致源文件损坏
    dir_name = os.path.dirname(os.path.abspath(input_file))
    tmp_fd, tmp_path = tempfile.mkstemp(dir=dir_name, suffix=".tmp")
    try:
        with os.fdopen(tmp_fd, "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)
        os.replace(tmp_path, input_file)
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise

    print(f"已将 {updated_count} 条标准化省市回填至: {input_file}")


def clean_tender_items(input_file: str = INPUT_FILE, output_file: str = OUTPUT_FILE) -> None:
    """读取 tender_items.csv，清洗数据后写入 cleaned_requirements.csv，并将标准化省市回填到输入文件。"""
    amap_key = os.getenv("AMAP_GEOCODING_KEY", "")
    if not amap_key:
        print("警告：未设置环境变量 AMAP_GEOCODING_KEY，地址标准化字段将全部填写'待人工处理'。")

    # 加载省市编码表
    valid_pairs, adcode_map = load_province_city_codes()
    print(f"已加载省市编码表：{len(valid_pairs)} 个有效省市对，{len(adcode_map)} 个 adcode 映射。")

    # 构建省份/城市规范化查找集合，用于将简称补全为编码表全称（如 "北京" → "北京市"）
    known_provinces = frozenset(p for p, _ in valid_pairs)
    known_cities = frozenset(c for _, c in valid_pairs)

    # 地址编码结果内存缓存，避免对相同地址重复发起 HTTP 请求
    _geocode_cache: Dict[str, Tuple[str, str, str]] = {}

    with open(input_file, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        rows = list(reader)

    # 1. 筛选 requirement_brief 不为"无相关要求"的数据
    filtered_rows = [r for r in rows if r.get("requirement_brief", "") != "无相关要求"]
    print(f"原始数据行数: {len(rows)}，筛选后行数: {len(filtered_rows)}")

    output_rows = []
    # announcement_url -> (province, city) 回填映射，仅记录标准化成功的条目
    writeback_map: Dict[str, Tuple[str, str]] = {}

    for row in filtered_rows:
        new_row = {col: "" for col in OUTPUT_COLUMNS}

        # 固定默认值
        new_row["活动主题"] = "供需对接活动"
        new_row["所有分类名称"] = "行业应用"
        new_row["需求分类名称"] = "其它行业"
        new_row["需求子类名称"] = "其它环节"

        # 字段映射
        new_row["需求主题"] = row.get("ai_project_title", "")
        new_row["需求简介"] = truncate_desc_for_limit(row.get("requirement_brief", ""), 200)
        new_row["发布单位名称"] = row.get("company_name", "")
        new_row["发布人姓名"] = row.get("contact_name", "")
        new_row["发布人电话"] = clean_contact_phone(row.get("contact_phone", ""))
        new_row["参考地址"] = row.get("location_text", "")
        new_row["来源链接"] = row.get("announcement_url", "")

        # 日期格式标准化
        new_row["发布时间"] = parse_datetime(row.get("pub_time", ""))
        new_row["截止时间"] = parse_datetime(row.get("deadline", ""))

        # 预算金额转换
        new_row["预算金额"] = parse_budget(row.get("budget", ""))

        # 需求内容（追加来源说明）
        new_row["需求内容"] = build_requirement_content(
            row.get("requirement_desc", ""),
            row.get("announcement_url", ""),
        )

        # 提前获取原始省市，将简称规范化为编码表全称后用于判断是否需要调用高德 API
        raw_province = row.get("province", "")
        raw_city = row.get("city", "")
        # 将简称规范化为编码表全称（如 "北京" → "北京市"，"河北" → "河北省"），
        # 确保跳过 API 调用的优化在实际数据上能够命中
        canon_province = _canonicalize(raw_province, known_provinces, _PROV_SUFFIXES)
        canon_city = _canonicalize(raw_city, known_cities, _CITY_SUFFIXES)

        # 地址标准化：若规范化后的省市已符合编码表，跳过高德 API 调用
        if canon_province and canon_city and (canon_province, canon_city) in valid_pairs:
            amap_province, amap_city, amap_adcode = "", "", ""
        else:
            reference_address = row.get("location_text", "")
            if reference_address not in _geocode_cache:
                _geocode_cache[reference_address] = geocode_address(reference_address, amap_key)
            amap_province, amap_city, amap_adcode = _geocode_cache[reference_address]

        new_row["高德省份"] = amap_province
        new_row["高德城市"] = amap_city
        new_row["高德adcode"] = amap_adcode

        # 严格标准化省份名称和市区名称（用规范化后的省市做步骤1匹配）
        norm_province, norm_city = normalize_location(
            canon_province,
            canon_city,
            amap_province,
            amap_city,
            amap_adcode,
            valid_pairs,
            adcode_map,
        )
        new_row["省份名称"] = norm_province
        new_row["市区名称"] = norm_city

        # 记录标准化成功的省市，用于回填输入文件
        if norm_province != FALLBACK_VALUE and norm_city != FALLBACK_VALUE:
            url = row.get("announcement_url", "")
            if url:
                writeback_map[url] = (norm_province, norm_city)

        output_rows.append(new_row)

    with open(output_file, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=OUTPUT_COLUMNS)
        writer.writeheader()
        writer.writerows(output_rows)

    print(f"清洗完成，结果已保存至: {output_file}")

    # 将标准化省市回填到输入文件
    writeback_to_input(input_file, writeback_map)


if __name__ == "__main__":
    clean_tender_items()
