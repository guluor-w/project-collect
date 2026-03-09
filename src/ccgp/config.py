import re
import os
from datetime import timedelta, timezone
from dotenv import load_dotenv

load_dotenv()


def _env_bool(name: str, default: bool) -> bool:
    v = os.getenv(name)
    if v is None:
        return default
    return v.strip().lower() in {"1", "true", "yes", "on"}


def _env_int(name: str, default: int) -> int:
    v = os.getenv(name)
    if not v:
        return default
    try:
        return int(v)
    except Exception:
        return default


def _env_float(name: str, default: float) -> float:
    v = os.getenv(name)
    if not v:
        return default
    try:
        return float(v)
    except Exception:
        return default

# 收集日期和最大页数
DAYS = 1
PAGES = 20
CLEAN_THRESHOLD = 1

# 时区
SG_TZ = timezone(timedelta(hours=8))

# HTTP 请求头
USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

# 关键词（待增删）
FILTER_KEYWORDS = [
    "智能制造","机器学习","深度学习", "大模型",
    "大数据", "数据治理", "机器人", "机器视觉",
    "云计算", "算力", "边缘计算","知识库","自然语言处理","计算机视觉","知识图谱",
    "智能化","数智化","智能","智慧","AI",
]

# 干扰词汇(待补充)
FILTER_EXCLUDE_KEYWORDS = [
    "开标","评标","投标","智能客服","采小蜜","智能电子采购系统","智能服务管家","大厦", "项目编号",
    "政采云","电子与智能化工程专业","现场获取","采购智慧",
    "联系人","联系方式","项目联系人","项目联系电话","采购人联系方式",
    "采购单位联系方式","楼","电子与智能化工程专业","栋",
    "智能交易系统适配版","智慧云平台"
]

# 查询时依赖的标志字段（以第一个为主，后面的用于兜底）
FIELD_ALIASES = {
    "project_name": ["项目名称", "采购项目名称"],
    "budget": ["预算金额", "预算金额（元）", "采购预算", "项目预算", "最高限价"],
    "deadline": ["截止时间", "投标截止时间", "响应文件提交截止时间", "获取招标文件截止时间", "至", "开标时间"],
    "purchaser_name": ["采购单位", "采购人信息-名称", "采购人名称", "采购人", "采购人信息"],
    "purchasing_unit_contact_number": ["采购单位联系方式", "采购人联系方式", "采购单位电话"],
    "contact_name": ["项目联系人", "联系人", "采购人项目联系人", "项目负责人"],
    "contact_phone": ["项目联系电话", "联系方式", "联系电话", "移动电话","电话"],
    "location": ["采购单位地址", "采购单位地点", "项目实施地点", "项目实施地址", "项目地点", "项目地址", "地点", "地址"],
}

PROVINCES = [
    "北京", "天津", "上海", "重庆",
    "河北", "山西", "内蒙古",
    "辽宁", "吉林", "黑龙江",
    "江苏", "浙江", "安徽", "福建", "江西", "山东",
    "河南", "湖北", "湖南",
    "广东", "广西", "海南",
    "四川", "贵州", "云南", "西藏",
    "陕西", "甘肃", "青海", "宁夏", "新疆",
    "香港", "澳门", "台湾",
]

# 解析日期
RE_DATE_YMD_HM = re.compile(
    r"(?P<y>\d{4})[年\-/\.](?P<m>\d{1,2})[月\-/\.](?P<d>\d{1,2})日?"
    r"(?:\s*(?P<h>\d{1,2})[:：](?P<mi>\d{1,2}))?"
)

# 解析金额
RE_MONEY = re.compile(
    r"(?P<num>\d{1,3}(?:,\d{3})*(?:\.\d+)?|\d+(?:\.\d+)?)\s*(?P<unit>万元|万|元)?"
)

# 开关
ENABLE_READ_ATTACHMENTS = _env_bool("CCGP_ENABLE_ATTACHMENTS", True)
ENABLE_LLM_REQUIREMENTS = _env_bool("CCGP_ENABLE_LLM", True)

# Runtime tuning knobs for CI / GitHub Actions
REQUEST_TIMEOUT_SEC = _env_int("CCGP_HTTP_TIMEOUT", 15)
DOWNLOAD_TIMEOUT_SEC = _env_int("CCGP_DOWNLOAD_TIMEOUT", 30)
MAX_ATTACHMENTS_PER_NOTICE = _env_int("CCGP_MAX_ATTACHMENTS", 3)
DETAIL_SLEEP_MIN_SEC = _env_float("CCGP_SLEEP_MIN", 2.0)
DETAIL_SLEEP_MAX_SEC = _env_float("CCGP_SLEEP_MAX", 4.0)
SKIP_REPEATED_FAILED_ATTACHMENTS = _env_bool("CCGP_SKIP_REPEAT_FAILED_ATTACHMENTS", True)

# Skip known low-value or problematic attachment links to reduce long waits.
ATTACHMENT_BLOCKLIST_HOSTS = {
    "zfcg.szggzy.com",
}
ATTACHMENT_BLOCKLIST_KEYWORDS = [
    "TPBidder/DownLoad",
    "投标文件制作专用软件",
]

# 路径保存
ATTACHMENTS_DIR = "src/ccgp/data/attachments/"
CSV_OUTPUT_DIR = "src/ccgp/data/tender_items.csv"

LOGGING_DIR = "src/ccgp/data/logs/"
LOGGING_LEVEL = "DEBUG"
