import json
import re
from openai import OpenAI
from utils.mylogger import get_logger

#暂时这么写（后续再添加环境变量）
MOONSHOT_API_KEY = "sk-APeYe0xM3akzvtvc88JHTu5gWfJ8DFNHR5B2tm2oR3ILoeov"

BASE_URL = "https://api.moonshot.cn/v1" 
client = OpenAI(
    api_key=MOONSHOT_API_KEY,
    base_url=BASE_URL
)

def build_prompt(meta: dict, page_text: str, attachment_texts: list[str]) -> str:
    def clip(s: str, n: int) -> str:
        s = s or ""
        return s[:n]

    att_block = "\n\n".join(
        [f"[附件{i+1}]\n{clip(t, 8000)}" for i, t in enumerate(attachment_texts) if (t or "").strip()]
    )
    page_block = clip(page_text, 12000)

    return f"""
你是政府采购/招投标领域的需求分析专家。请基于“网页正文 + 附件内容”，输出该项目的【需求详细描述】。

【项目信息】
- 公告标题：{meta.get("title","")}
- 公告URL：{meta.get("url","")}
- 项目名称：{meta.get("project_name","")}
- 预算：{meta.get("budget","")}
- 截止/开标时间：{meta.get("deadline","")}
- 采购人：{meta.get("company_name","")}
- 联系方式：{meta.get("contact_phone","")}

【网页正文（可能包含公告概要/投标人资格/技术参数等）】
{page_block}

【附件内容（如果为空说明附件无法提取文字或无附件）】
{att_block if att_block.strip() else "（无可用附件文本）"}

输出要求：
1) 用中文输出，内容必须来自提供内容，不要编造不存在的条款；若信息缺失请标注“未明确/以招标文件为准”。
2) 输出必须严格为 JSON（不要有任何多余解释和文本），字段如下：
{{
  "requirement_brief": "100字概述",
  "requirement_desc": "尽量详细(300字左右)，内容重点包括采购范围/现状与目标/功能需求/非功能需求(安全/性能/兼容)/交付物/实施与培训/验收与测评等，不用分点，用一段话的形式输出"
}}
""".strip()

def _safe_json_loads(text: str) -> dict:
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", text, flags=re.S)
        if not m:
            raise
        return json.loads(m.group(0))

def generate_requirements(meta: dict, page_text: str, attachment_texts: list[str]) -> dict:
    prompt = build_prompt(meta, page_text, attachment_texts)

    resp = client.chat.completions.create(
        model="moonshot-v1-32k",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.2,
    )
    txt = (resp.choices[0].message.content or "").strip()

    get_logger().debug(f"LLM response:\n{txt}\n---")

    return _safe_json_loads(txt)


# 测试用
if __name__ == "__main__":
    meta = {
        "title": "示例：教学仪器购置公开招标",
        "url": "https://www.ccgp.gov.cn/xxgg/dfgg/gkzb/202601/t20260128_XXXXX.htm",
        "project_name": "泉州市实验小学大兴校区教学仪器购置(三次)",
        "budget": "106.2万元",
        "deadline": "2026-02-27 10:00",
        "company_name": "泉州市实验小学",
        "contact_phone": "18120608656",
    }
    page_text = "这里放公告正文..."
    attachment_texts = ["这里放附件提取的文本..."]
    generate_requirements(meta, page_text, attachment_texts)