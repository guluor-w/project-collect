import json
import os
import re
from typing import List, Dict, Optional, Tuple, Any

from openai import OpenAI
from utils.mylogger import get_logger

# -----------------------------------------------------------------------------
# 配置与模型管理
# -----------------------------------------------------------------------------

class LLMProvider:
    """定义 LLM 服务商配置"""
    def __init__(self, name: str, api_key: str, base_url: str, models: Dict[str, str]):
        self.name = name
        self.api_key = api_key
        self.base_url = base_url
        self.models = models

    def get_model(self, task_type: str) -> str:
        """根据任务类型获取模型名称，如果未找到，则尝试获取 default，最后返回空"""
        return self.models.get(task_type, self.models.get("default", ""))

    def create_client(self) -> Optional[OpenAI]:
        if not self.api_key:
            return None
        return OpenAI(api_key=self.api_key, base_url=self.base_url)


def _load_llm_providers() -> List[LLMProvider]:
    """
    加载所有可用的 LLM 服务配置。
    优先级顺序即为列表顺序。
    """
    providers = []

    # 1. Moonshot AI (Kimi) - 优先使用
    mk = os.getenv("MOONSHOT_API_KEY", "").strip()
    if mk:
        providers.append(LLMProvider(
            name="Moonshot",
            api_key=mk,
            base_url="https://api.moonshot.cn/v1",
            models={
                "desc": "kimi-k2-thinking",
                "summary": "moonshot-v1-8k",
                "filter": "moonshot-v1-32k",
                "default": "moonshot-v1-32k"
            }
        ))

    # 2. Volcengine (Doubao/Ark) - 火山引擎
    vk = os.getenv("VOLC_API_KEY", "").strip()
    
    if vk:
        providers.append(LLMProvider(
            name="Volcengine",
            api_key=vk,
            base_url="https://ark.cn-beijing.volces.com/api/v3", 
            models={
                "desc": "doubao-seed-2-0-pro-260215",
                "summary": "doubao-seed-2-0-lite-260215",
                "filter": "doubao-seed-2-0-pro-260215",
                "default": "doubao-seed-2-0-pro-260215"
            }
        ))

    # 3. DeepSeek
    dk = os.getenv("DEEPSEEK_API_KEY", "").strip()
    if dk:
        providers.append(LLMProvider(
            name="DeepSeek",
            api_key=dk,
            base_url="https://api.deepseek.com",
            models={
                "desc": "deepseek-reasoner",
                "summary": "deepseek-chat",
                "filter": "deepseek-reasoner",
                "default": "deepseek-reasoner"
            }
        ))

    return providers


class LLMService:
    """LLM 服务统一封装，支持故障转移"""
    
    def __init__(self):
        self.providers = _load_llm_providers()

    def chat_completion(self, 
                       messages: List[Dict[str, str]], 
                       task_type: str = "default") -> str:
        """
        执行 Chat Completion，支持自动重试不同的 Provider。
        返回生成的文本内容，如果全都失败则通过 get_logger 记录并返回空字符串。
        """
        if not self.providers:
            get_logger().error("No LLM providers configured. Please check environment variables (MOONSHOT_API_KEY, VOLC_API_KEY, etc).")
            return ""

        last_error = None

        for provider in self.providers:
            model = provider.get_model(task_type)
            if not model:
                # 该 provider 不支持此任务类型，跳过
                continue
            
            try:
                client = provider.create_client()
                if not client:
                    continue

                get_logger().debug(f"Calling LLM: Provider={provider.name}, Model={model}, Task={task_type}")
                
                resp = client.chat.completions.create(
                    model=model,
                    messages=messages
                    # 使用供应商的默认 temperature 参数
                )
                content = (resp.choices[0].message.content or "").strip()
                if content:
                    return content
                else:
                    get_logger().warning(f"LLM returned empty content. Provider={provider.name}")

            except Exception as e:
                get_logger().warning(f"LLM call failed with {provider.name}: {e}")
                last_error = e
                # 尝试下一个 provider
                continue
        
        get_logger().error(f"All LLM providers failed. Last error: {last_error}")
        return ""


# 全局单例
_llm_service = None

def get_llm_service() -> LLMService:
    global _llm_service
    if _llm_service is None:
        _llm_service = LLMService()
    return _llm_service


# -----------------------------------------------------------------------------
# Prompt 构建辅助函数
# -----------------------------------------------------------------------------

def _build_desc_prompt(meta: dict, page_text: str, attachment_texts: list[str]) -> str:
    def clip(s: str, n: int) -> str:
        return (s or "")[:n]

    # 附件截取策略：总长度控制 + 单个附件控制
    # 扩大容量以适配长上下文模型 (128k)，总容量控制在 60k-80k 字符也是安全的
    att_block = "\n\n".join(
        [f"[附件{i + 1}]\n{clip(t, 25000)}" for i, t in enumerate(attachment_texts) if (t or "").strip()]
    )
    # 网页正文截取
    page_block = clip(page_text, 40000)

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
    if not text:
        return {}
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", text, flags=re.S)
        if not m:
            return {}
        try:
            return json.loads(m.group(0))
        except:
            return {}


# -----------------------------------------------------------------------------
# 核心业务逻辑
# -----------------------------------------------------------------------------

def generate_requirements(meta: dict, page_text: str, attachment_texts: list[str]) -> dict:
    """
    第一阶段：生成需求描述 (desc)
    第二阶段：生成标题和摘要 (summary)
    """
    service = get_llm_service()

    # 1. Generate Requirement Description
    desc_prompt = _build_desc_prompt(meta, page_text, attachment_texts)
    
    # 任务类型 "desc" 通常通过长文本模型处理 (如 moonshot-v1-128k, volc-endpoint-long)
    txt_desc = service.chat_completion(
        messages=[{"role": "user", "content": desc_prompt}],
        task_type="desc"
    )

    if not txt_desc:
        # 失败时返回空结构，避免上层逻辑报错
        return {
            "ai_project_title": "",
            "requirement_brief": "",
            "requirement_desc": "无法调用LLM生成需求，请检查API Key配置。"
        }

    # get_logger().debug(f"LLM desc response:\n{txt_desc}\n---") # 可按需开启详细日志
    
    requirement_desc = txt_desc

    if "无相关要求" in requirement_desc:
        return {
            "ai_project_title": "无相关要求",
            "requirement_brief": "无相关要求",
            "requirement_desc": requirement_desc
        }

    # 2. Generate Title and Brief
    project_name = meta.get("project_name", "") or meta.get("title", "")
    summary_prompt = _build_summary_prompt(project_name, requirement_desc)
    
    # 任务类型 "summary" 可用短文本模型 (如 moonshot-v1-8k, volc-endpoint-short)
    txt_summary = service.chat_completion(
        messages=[{"role": "user", "content": summary_prompt}],
        task_type="summary"
    )

    # get_logger().debug(f"LLM summary response:\n{txt_summary}\n---")
    
    summary_data = _safe_json_loads(txt_summary)

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
    service = get_llm_service()
    # 如果完全没有配置任何 provider，则默认通过，不阻拦
    if not service.providers:
        return {"keep": True, "reason": "skip: 没有配置大模型KEY"}

    text = (combined_text or "")[:18000] # 截断，防止过长
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

    # 任务类型 "filter"
    txt = service.chat_completion(
        messages=[{"role": "user", "content": prompt}],
        task_type="filter"
    )
    
    data = _safe_json_loads(txt)
    
    # 只要没明确说不 keep，就默认 keep (Fail-Open)
    keep = bool(data.get("keep", True))
    reason = str(data.get("reason", "API解析失败或未返回reason")).strip()
    
    return {"keep": keep, "reason": reason}


if __name__ == "__main__":
    meta = {
        "title": "示例：教学仪器采购公开招标",
        "url": "https://www.ccgp.gov.cn/test",
        "project_name": "某实验小学AI教学实验室",
        "company_name": "某采购单位",
        "contact_phone": "181...",
    }
    page_text = "本项目采购AI教学相关设备，包括大模型推理服务器..."
    attachment_texts = ["附件内容：服务器参数要求..."]
    
    print("Testing generate_requirements...")
    res = generate_requirements(meta, page_text, attachment_texts)
    print(res)
