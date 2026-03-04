import json
import os
import re

from openai import OpenAI

from utils.mylogger import get_logger

MOONSHOT_API_KEY = os.getenv("MOONSHOT_API_KEY", "").strip()
BASE_URL = os.getenv("MOONSHOT_BASE_URL", "https://api.moonshot.cn/v1").strip()

client = OpenAI(api_key=MOONSHOT_API_KEY, base_url=BASE_URL) if MOONSHOT_API_KEY else None


def build_prompt(meta: dict, page_text: str, attachment_texts: list[str]) -> str:
    def clip(s: str, n: int) -> str:
        return (s or "")[:n]

    att_block = "\n\n".join(
        [f"[附件{i + 1}]\n{clip(t, 8000)}" for i, t in enumerate(attachment_texts) if (t or "").strip()]
    )
    page_block = clip(page_text, 12000)

    return f"""
你是政府采购/招投标领域的AI与信息化需求分析专家。请基于网页正文和附件内容，深入提取总结该项目中【与人工智能应用相关的核心信息】，包括涉及的技术要求、功能要求、性能要求等。

[项目信息]
- 公告标题: {meta.get("title", "")}
- 项目名称: {meta.get("project_name", "")}
- 采购人: {meta.get("company_name", "")}

[网页正文]
{page_block}

[附件内容]
{att_block if att_block.strip() else "(无可用附件文本)"}

输出要求:
1) 仅根据输入信息生成，不得杜撰。重点关注人工智能能力建设以及落地应用场景等行业应用内容。
2) 如果整个文档不涉及任何人工智能相关的实质性需求，可以在各个字段中填写“无相关要求”。
3) 严格输出 JSON 格式，不要输出额外解释、不要带有 markdown 标记。
4) JSON 字段格式如下:
{{
  "requirement_brief": "AI建设目标及总体概述，150字以内",
  "requirement_desc": "AI项目详情，包括AI相关技术要求、具体业务场景和功能要求、性能指标要求。1000字以内",
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

    prompt = build_prompt(meta, page_text, attachment_texts)

    resp = client.chat.completions.create(
        model="moonshot-v1-32k",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.2,
    )
    txt = (resp.choices[0].message.content or "").strip()
    get_logger().debug(f"LLM response:\n{txt}\n---")
    return _safe_json_loads(txt)


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
你是政府采购需求筛选员。请判断下面公告是否“应保留为智能化业务相关需求”。

规则：
1) 若“智能/智慧/AI”等只是宣传词、平台口号、局部修饰（如仅修饰开标系统、客服、楼宇名称、物业/平台名称），应判定为不保留。
2) 只有当智能化内容构成采购主体目标、核心建设内容或主要交付物时，才判定保留。
3) 不要因为出现关键词就保留，要看是否是项目主体。

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
        "deadline": "2026-02-27 10:00",
        "company_name": "某采购单位",
        "contact_phone": "18120608656",
    }
    page_text = "这里放公告正文"
    attachment_texts = ["这里放附件提取文本"]
    print(generate_requirements(meta, page_text, attachment_texts))
