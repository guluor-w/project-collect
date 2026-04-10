"""
数据清洗脚本：针对 tender_items.csv 文件进行清洗，生成 cleaned_requirements.csv。

功能：
1. 筛选 requirement_brief 不为"无相关要求"的数据。
2. 新建数据表格，包含指定字段。
3. 字段名称变更及默认值设置。
4. 字段内容处理（日期格式标准化、预算金额转换、需求内容追加来源说明）。
5. 地址标准化：通过高德地址编码接口获取 province、city、adcode，拼合到末尾字段。
   - 需要设置环境变量 AMAP_GEOCODING_KEY。
   - 请求失败时填写"待人工处理"。
"""

import os
import re
import csv
from datetime import datetime

import requests
from dotenv import load_dotenv

load_dotenv()

INPUT_FILE = os.path.join(os.path.dirname(__file__), "tender_items.csv")
OUTPUT_FILE = os.path.join(os.path.dirname(__file__), "cleaned_requirements.csv")

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
        resp = requests.get(
            AMAP_GEO_URL,
            params={"address": address, "key": api_key, "output": "json"},
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()

        if data.get("status") != "1" or not data.get("geocodes"):
            return FALLBACK_VALUE, FALLBACK_VALUE, FALLBACK_VALUE

        geo = data["geocodes"][0]
        province = geo.get("province") or FALLBACK_VALUE
        city = geo.get("city") or FALLBACK_VALUE
        adcode = geo.get("adcode") or FALLBACK_VALUE
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


def build_requirement_content(desc: str, announcement_url: str) -> str:
    """在需求内容末尾追加来源说明段落。"""
    source_note = f"本需求来源于中国政府采购网，详情请见招标信息 {announcement_url}"
    if desc:
        return f"{desc}\n\n{source_note}"
    return source_note


def clean_tender_items(input_file: str = INPUT_FILE, output_file: str = OUTPUT_FILE) -> None:
    """读取 tender_items.csv，清洗数据后写入 cleaned_requirements.csv。"""
    amap_key = os.getenv("AMAP_GEOCODING_KEY", "")
    if not amap_key:
        print("警告：未设置环境变量 AMAP_GEOCODING_KEY，地址标准化字段将全部填写'待人工处理'。")

    with open(input_file, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        rows = list(reader)

    # 1. 筛选 requirement_brief 不为"无相关要求"的数据
    filtered_rows = [r for r in rows if r.get("requirement_brief", "") != "无相关要求"]
    print(f"原始数据行数: {len(rows)}，筛选后行数: {len(filtered_rows)}")

    output_rows = []
    for row in filtered_rows:
        new_row = {col: "" for col in OUTPUT_COLUMNS}

        # 固定默认值
        new_row["活动主题"] = "供需对接活动"

        # 字段映射
        new_row["需求主题"] = row.get("ai_project_title", "")
        new_row["需求简介"] = row.get("requirement_brief", "")
        new_row["发布单位名称"] = row.get("company_name", "")
        new_row["发布人姓名"] = row.get("contact_name", "")
        new_row["发布人电话"] = row.get("contact_phone", "")
        new_row["省份名称"] = row.get("province", "")
        new_row["市区名称"] = row.get("city", "")
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

        # 地址标准化（高德地理编码）
        reference_address = row.get("location_text", "")
        province, city, adcode = geocode_address(reference_address, amap_key)
        new_row["高德省份"] = province
        new_row["高德城市"] = city
        new_row["高德adcode"] = adcode

        output_rows.append(new_row)

    with open(output_file, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=OUTPUT_COLUMNS)
        writer.writeheader()
        writer.writerows(output_rows)

    print(f"清洗完成，结果已保存至: {output_file}")


if __name__ == "__main__":
    clean_tender_items()
