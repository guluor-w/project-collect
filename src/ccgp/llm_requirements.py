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
你是政府采购/招投标领域的AI与信息化需求分析专家。请基于网页正文和附件内容，深入提取总结该项目中与人工智能应用相关的需求信息。

[项目信息]
- 项目名称: {meta.get("project_name", "")}
- 采购人: {meta.get("company_name", "")}

[网页正文]
{page_block}

[附件内容]
{att_block if att_block.strip() else "(无可用附件文本)"}

一、强制规则（必须遵守）
1) 输出分两部分：先写“背景概述”（可选），再写“AI需求点”。两部分都必须来自原文明确表述，不得推测、补全、联想行业惯例。
   - 禁止出现或变体：可能、通常、一般、惯例、推断、暗示、隐含、倾向、可从…维度、需要说明的是、总体而言、技术实现路径推断、根据行业实践。
2) 不输出分析过程与评价性/总结性套话；只输出“背景概述+需求清单式”的结果。
3) 不得输出与AI无关内容：预算、工期、评分办法、资质证书、人员证书、投标要求、售后通用条款等。
4) 当全文（网页+附件）都没有出现任何“可被视为AI相关需求”的明确描述时，仅输出：“无相关要求”
   - 注意：仅出现“智能”“智慧”等字样但没有对应功能/技术/指标/场景描述，不算AI需求；仍输出：无相关要求
5) 1000字以内；输出为纯文本；禁止Markdown（不要用#、*、表格、代码块）。

二、什么算“AI相关的明确需求”（满足其一即可收录）
A. 明确技术/模型/算法：如大模型、LLM、RAG、向量检索、OCR、ASR、TTS、NLP、文本分类、实体识别、知识图谱、推荐、预测、异常检测、图像识别、智能问答等。
B. 明确智能功能且具备可验证描述：如“自动识别/自动分类/自动抽取/自动生成报告/智能问答/智能预警”，并伴随至少一种细节：输入数据、处理对象、输出结果、适用业务环节、触发条件、准确率/召回率/时延等指标。
C. 明确提出模型训练/微调/评测/数据标注/模型管理/推理部署/算力资源。

三、输出格式（严格按此结构；没有内容的章节直接跳过，不要写‘无’）
先输出【背景概述】（可选）：
- 仅摘取与项目背景/现状/建设目标/项目意义相关的原文表述进行压缩改写，<=150字；不得引入新信息。
- 若原文未提供可用信息，跳过该段。

再按“需求点”逐条输出：
- 用编号分条（1、2、3…）输出，每条为一个“AI相关需求点”的纯文本段落。
- 不需要强制保留字段名；但每条尽量覆盖（原文若有则写）：业务场景/使用对象、目标产出、输入数据、涉及的AI能力或智能功能、关键功能点、指标与约束、集成对接与交付物。
- 只写原文明确写到的内容；原文没写到的要素直接不写，禁止补全。
四、去重与合并要求
- 原文多处描述同一需求点时，合并为一条；避免重复表述。
- 除开头的【背景概述】外，需求条目中仅保留“需求”，不复述背景介绍、现状描述、项目意义；也不要写结论性总结。
""".strip()

def _build_summary_prompt(project_name: str, requirement_desc: str) -> str:
    return f"""
你是采购/招投标领域的AI与信息化需求分析专家。请根据以下项目名称和项目详情，生成项目标题和简要概述。

[项目名称]
{project_name}

[项目详情]
{requirement_desc}

输出内容要求:
1) ai_project_title: AI项目标题，高度概括AI需求相关内容，不需要出现项目期数等信息，28字以内。
2) requirement_brief: AI项目需求的建设目标及总体概述，150字以内。

输出格式要求：
1) 严格输出 JSON 格式，不要输出额外解释、不要带有 markdown 标记。
2) JSON 字段格式如下:
{{
  "ai_project_title": "AI项目标题",
  "requirement_brief": "AI项目需求的建设目标及总体概述"
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
        model="kimi-k2-thinking",
        messages=[{"role": "user", "content": desc_prompt}]
    )
    txt_desc = (resp_desc.choices[0].message.content or "").strip()
    get_logger().debug(f"LLM desc response:\n{txt_desc}\n---")
    
    requirement_desc = txt_desc

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
