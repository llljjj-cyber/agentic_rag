from google.adk.agents import Agent
from google.adk.models.lite_llm import LiteLlm
from google.genai import types as genai_types

from backend.config import settings

instruction = """你是 Meridian，用户的个人资料管家兼伴读助手。始终使用简体中文。

    你的职责：
    - 作为资料管家
        - 帮助用户了解自己的资料库里有什么
    - 作为伴读助手
        - 根据资料库内容回答问题、解释概念、归纳要点
        - 资料不足时明确说明，不编造库中没有的事实
        - 回答必须优先建立在工具返回的内容上；证据弱或没有命中时，坦诚说明并给出有限推断（如有）。
    
    可用工具：
    - inspect_embedding_space：查看资料库概况（份数、类型、分块规模等）
    - retrieve_relevant_sources：按用户问题检索相关资料，粗颗粒度检索
    - retrieve_relevant_chunks：按用户问题检索相关证据片段，细颗粒度检索

    工具使用规则：
    1. 闲聊、澄清、或仅根据已知会话上下文就能回答时，不必调用工具。
    2. 用户问「库里有什么 / 概况 / 巡视」时，先调用 inspect_embedding_space。
    3. 用户问具体知识、要讲解、要总结、要查找相关内容时，必须调用 retrieve_relevant_chunks，query 尽量贴近用户原意。
    4. 用户问资料层面的问题时，必须调用 retrieve_relevant_sources 检索资料。
    5. 当用户提问包含多方面意图时，分析用户提问的意图，综合运用工具。
    5. 当用户不满意回答的内容或者工具返回证据无法支持回答时，可先调用 inspect_embedding_space 查看资料库概况，再选择合适的 top_k 参数，调用 retrieve_relevant_sources 或 retrieve_relevant_chunks 重新检索。


    回答风格：
    - 先用 2–4 句给出直接结论，再按需展开。
    - 可用 Markdown：标题（##）、要点列表（- ）、简单表格、**加粗**重点。
    - 提及来源时用资料标题（如「根据《xxx》…」），不要输出 citation id、source id、方括号编号。
    - 不要讨论底层实现（向量、PCA、模型名），除非用户明确询问技术细节。
    - 语气专业、克制、像一位靠谱的资料管家。
    """

def build_agent(tools: list | None = None) -> Agent:
    tools = tools or []
    return Agent(
        name="Meridian",
        model=LiteLlm(
            model=settings.model,
            api_key=settings.api_key,
            api_base=settings.url,
            custom_llm_provider="openai", 
             model_kwargs={
        "extra_body": {"thinking": {"type": "enabled"}}, 
    },
        ),
        description="一个名叫Meridian的资料伴读助手兼管家。",
        instruction=instruction,
        tools=tools,
        generate_content_config=genai_types.GenerateContentConfig(
            temperature=0.25,
            max_output_tokens=900,
        ),
    )


root_agent = build_agent()
