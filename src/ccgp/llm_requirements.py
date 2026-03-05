import json
import os
import re

from openai import OpenAI

from utils.mylogger import get_logger

MOONSHOT_API_KEY = os.getenv("MOONSHOT_API_KEY", "").strip()
BASE_URL = os.getenv("MOONSHOT_BASE_URL", "https://api.moonshot.cn/v1").strip()

client = OpenAI(api_key=MOONSHOT_API_KEY, base_url=BASE_URL) if MOONSHOT_API_KEY else None


def _build_desc_prompt(meta: dict, page_text: str, attachment_texts: list[str]) -> str:
    def clip(s: str, n: int) -> str:
        return (s or "")[:n]

    att_block = "\n\n".join(
        [f"[附件{i + 1}]\n{clip(t, 8000)}" for i, t in enumerate(attachment_texts) if (t or "").strip()]
    )
    page_block = clip(page_text, 12000)

    return f"""
你是政府采购/招投标领域的AI与信息化需求分析专家。请基于网页正文和附件内容，深入提取总结该项目中【与人工智能应用相关的核心信息】，包括涉及的技术要求、功能要求、性能要求等。

[项目信息]
- 项目名称: {meta.get("project_name", "")}
- 采购人: {meta.get("company_name", "")}

[网页正文]
{page_block}

[附件内容]
{att_block if att_block.strip() else "(无可用附件文本)"}

输出内容要求:
1) 输出内容尽可能详细。严格按照输入信息生成，不得捏造信息。
2) 重点关注人工智能能力建设以及落地应用场景等行业应用内容。
3) 需要输出包括AI相关技术、功能、具体业务场景、性能指标等方面。如不存在相应方面内容，直接跳过不输出，不要输出“无相关要求”或者类似表述。
4) 不要输出预算、资质、供应商资格等与AI技术要求无关的内容。
5) 如果输入内容不涉及任何人工智能相关的实质性需求，可以直接输出“无相关要求”。

输出格式要求：
1) 严格输出 JSON 格式，不要输出额外解释、不要带有 markdown 标记。
2) 1000字以内。
3) JSON 字段格式如下:
{{
  "requirement_desc": "AI项目详情"
}}
""".strip()

def _build_summary_prompt(project_name: str, requirement_desc: str) -> str:
    return f"""
你是政府采购/招投标领域的AI与信息化需求分析专家。请根据以下项目名称和项目详情（requirement_desc），生成项目标题和简要概述。

[项目名称]
{project_name}

[项目详情 (requirement_desc)]
{requirement_desc}

输出内容要求:
1) ai_project_title: AI项目标题，高度概括AI需求相关内容，不需要出现项目期数等信息，28字以内。
2) requirement_brief: AI项目建设目标及总体概述，150字以内。

输出格式要求：
1) 严格输出 JSON 格式，不要输出额外解释、不要带有 markdown 标记。
2) JSON 字段格式如下:
{{
  "ai_project_title": "AI项目标题",
  "requirement_brief": "AI项目建设目标及总体概述"
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
    if client is None:
        raise RuntimeError("MOONSHOT_API_KEY is not set. Configure it via environment variable or GitHub Secret.")

    # 1. Generate Requirement Description
    desc_prompt = _build_desc_prompt(meta, page_text, attachment_texts)
    resp_desc = client.chat.completions.create(
        model="moonshot-v1-32k",
        messages=[{"role": "user", "content": desc_prompt}],
        temperature=0.2,
    )
    txt_desc = (resp_desc.choices[0].message.content or "").strip()
    get_logger().debug(f"LLM desc response:\n{txt_desc}\n---")
    
    try:
        desc_data = _safe_json_loads(txt_desc)
        requirement_desc = desc_data.get("requirement_desc", "无相关要求")
    except Exception as e:
        get_logger().error(f"Failed to parse desc JSON: {e}")
        requirement_desc = "无相关要求"

    if "无相关要求" in requirement_desc:
        return {
            "ai_project_title": "无相关要求",
            "requirement_brief": "无相关要求",
            "requirement_desc": "无相关要求"
        }

    # 2. Generate Title and Brief
    project_name = meta.get("project_name", "") or meta.get("title", "")
    summary_prompt = _build_summary_prompt(project_name, requirement_desc)
    
    resp_summary = client.chat.completions.create(
        model="moonshot-v1-8k",
        messages=[{"role": "user", "content": summary_prompt}],
        temperature=0.2,
    )
    txt_summary = (resp_summary.choices[0].message.content or "").strip()
    get_logger().debug(f"LLM summary response:\n{txt_summary}\n---")
    
    try:
        summary_data = _safe_json_loads(txt_summary)
    except Exception as e:
        get_logger().error(f"Failed to parse summary JSON: {e}")
        summary_data = {}

    return {
        "ai_project_title": summary_data.get("ai_project_title", ""),
        "requirement_brief": summary_data.get("requirement_brief", ""),
        "requirement_desc": requirement_desc
    }


def llm_second_filter_by_combined(combined_text: str, title: str = "") -> dict:
    """
    LLM second-pass filter.
    Return shape:
    {
      "keep": bool,
      "reason": str
    }
    """
    if client is None:
        return {"keep": True, "reason": "skip second filter: MOONSHOT_API_KEY not set"}

    text = (combined_text or "")[:18000]
    prompt = f"""
你是政府采购需求筛选员。请判断下面公告是否为“人工智能业务/产品”或者“智能化业务/产品”相关需求。

判断规则：
1) 若“智能/智慧/AI”等只是宣传词、平台口号、局部修饰（如仅修饰开标系统、客服、楼宇名称、物业/平台名称），应判定为不保留。
2) 只有当智能化内容构成采购主体目标、核心建设内容或主要交付物时，才判定保留。
3) 不要因为出现关键词就保留，要判断“人工智能业务/产品”或者“智能化业务/产品”是否为项目主体。

标题：{title}
文本：
{text}

仅输出JSON，不要输出其它内容：
{{
  "keep": true,
  "reason": "一句话说明判断依据(25字以内)"
}}
""".strip()

    resp = client.chat.completions.create(
        model="moonshot-v1-32k",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.0,
    )
    txt = (resp.choices[0].message.content or "").strip()
    data = _safe_json_loads(txt)

    keep = bool(data.get("keep", True))
    reason = str(data.get("reason", "")).strip()
    return {"keep": keep, "reason": reason}


if __name__ == "__main__":
    meta = {
        "title": "示例：教学仪器采购公开招标",
        "url": "https://www.ccgp.gov.cn/xxgg/dfgg/gkzb/202601/t20260128_xxxxx.htm",
        "project_name": "某实验小学教学仪器采购",
        "budget": "106.2万元",
        "deadline": "2026-02-27",
        "company_name": "某采购单位",
        "contact_phone": "18120608656",
    }
    page_text = "这里放公告正文"
    attachment_texts = ["这里放附件提取文本"]
    print(generate_requirements(meta, page_text, attachment_texts))
