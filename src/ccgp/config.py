import re
from datetime import timedelta, timezone

# 收集日期和最大页数
DAYS = 1
PAGES = 30
CLEAN_THRESHOLD = 3

# 时区
SG_TZ = timezone(timedelta(hours=8))

# HTTP 请求头
USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

# 关键词（待增删）
FILTER_KEYWORDS = [
    "工业互联网", "智能制造", "智能", "智慧",
    "人工智能", "AI", "大模型", 
    "大数据", "数据治理", "数据中台",
    "机器人", "机器视觉", "自动化",
    "云计算", "算力", "边缘计算",
    "物联网", "5G",
]

# 干扰词汇(待补充)
FILTER_EXCLUDE_KEYWORDS = [
    "智能开标", "智能评标", "智能客服", "采小蜜","政府采购智慧云平台","智能电子采购系统", "智能服务管家", "自动化学院","智能产业大厦", "项目编号",
    "依托政采云","具有电子与智能化工程专业承包二级（含）及以上资质","现场获取",
]

# 爬取时依赖的标志字段（以第一个为主，后面的用于兜底）
FIELD_ALIASES = {
    "project_name": ["项目名称", "采购项目名称"],
    "budget": ["预算金额", "预算金额（元）", "采购预算", "项目预算", "最高限价"],
    "deadline": ["截止时间", "投标截止时间", "响应文件提交截止时间", "获取招标文件截止时间", "至", "开标时间"],
    "purchaser_name": ["采购单位", "采购人信息-名称", "采购人名称", "采购人", "采购人信息"],
    "purchasing_unit_contact_number": ["采购单位联系方式", "采购人联系方式", "采购单位电话"],
    "contact_name": ["项目联系人", "联系人", "采购人项目联系人", "项目负责人"],
    "contact_phone": ["项目联系电话", "联系方式", "联系电话", "移动电话"],
    "location": ["采购单位地址", "项目实施地点", "项目地点", "地点"],
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
ENABLE_READ_ATTACHMENTS = True
ENABLE_LLM_REQUIREMENTS = True

# 路径保存
ATTACHMENTS_DIR = "src/ccgp/data/attachments/"
CSV_OUTPUT_DIR = "src/ccgp/data/tender_items.csv"

LOGGING_DIR = "src/ccgp/data/logs/"
LOGGING_LEVEL = "DEBUG"