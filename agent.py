"""导购 Agent 核心

职责划分：
  - 产品事实、价格、组合、限制 -> 全部来自 kb.py，确定性查表
  - 安全与政策边界             -> 全部由 guard.py 前置拦截
  - 大模型                     -> 只负责在给定事实内组织语言

模型不参与任何价格计算，也不允许自行补充手册以外的产品信息。
"""

import json
import os

from openai import OpenAI

import kb

QWEN_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"
MODEL = "qwen-plus"


def _api_key():
    """按优先级读取密钥：Streamlit secrets -> 环境变量。"""
    try:
        import streamlit as st

        if "DASHSCOPE_API_KEY" in st.secrets:
            return st.secrets["DASHSCOPE_API_KEY"]
    except Exception:
        pass
    return os.environ.get("DASHSCOPE_API_KEY", "")


def get_client():
    key = _api_key()
    if not key:
        raise RuntimeError(
            "未找到 DASHSCOPE_API_KEY。请在 .streamlit/secrets.toml 中配置，"
            "或设置同名环境变量。"
        )
    return OpenAI(api_key=key, base_url=QWEN_BASE_URL)


# ---------------------------------------------------------------- 知识注入


def _render_catalog():
    """把产品目录渲染成 prompt 可用的文本。"""
    lines = []
    for p in kb.PRODUCTS.values():
        tags = []
        if p.get("requires_screening"):
            tags.append("【需前置筛查】")
        if p.get("travel_only"):
            tags.append("【仅旅行需求明确时才可提及】")
        tag = "".join(tags)
        lines.append(
            f"- {p['sku']} {p['name']} {p['spec']}｜{p['price']} 元{tag}\n"
            f"  客观特点：{p['features']}\n"
            f"  适用提示：{p['fit']}\n"
            f"  重要限制：{p['limits']}"
        )
    return "\n".join(lines)


def _render_combos():
    lines = []
    for c in kb.COMBOS:
        names = " + ".join(f"{s} {kb.PRODUCTS[s]['name']}" for s in c["members"])
        detail = " + ".join(str(kb.PRODUCTS[s]["price"]) for s in c["members"])
        lines.append(
            f"- {c['scenario']}：{names}，合计 {c['price']} 元（{detail}）\n"
            f"  说明：{c['note']}"
        )
    return "\n".join(lines)


SYSTEM_PROMPT = """你是「澄初个人护理」的门店导购。你的全部产品知识只能来自下面这份品牌手册，手册之外的信息一律不得编造。

# 品牌约束
品牌主张：{claim}
服务原则：{principle}
沟通语气：{tone}
禁止表达：{forbidden}
安全边界：{safety}

# 产品目录（唯一事实来源）
{catalog}

# 可讨论的组合
{combos}

# 硬性规则
1. 只能提及上面 6 个 SKU。不得虚构任何产品、成分、功效、规格或价格。
2. 报价必须与目录完全一致。组合总价按成员单价相加，两个组合均无折扣，
   因此绝对不要说「优惠」「省钱」「划算」「打折」之类的话。
3. 手册没有会员价、促销、赠品、线上同价、退换货、渠道授权政策。
   顾客问到这些，只说需要向门店或系统确认，不要给任何具体数字或承诺。
4. P201 含 8% 果酸：敏感、受损或正在不适的皮肤不推荐。推荐前必须先确认
   敏感情况和过往使用经验，并提示注意防晒。不强推。
5. P301 是旅行分装瓶，不属于护肤功效产品。只有顾客明确提到出差或旅行
   携带需求时才可提及，其他情况一律不要连带推荐。
6. 香味：P102、P203 带香味；P101、P202 无香型。顾客表示对香味敏感时，
   不优先推荐带香味的产品。
7. 不作医疗诊断。顾客提到明显不适、受损或持续问题，建议停止刺激性尝试
   并咨询专业人士。
8. 信息不足时最多追问 1-2 个最关键的问题，不要一次抛出一堆问题，
   也不要在信息不足时硬猜着推荐。

# 回复要求
- 语气自然、克制、有温度，不施压，不制造焦虑。
- 提到产品时必须带上 SKU 编号和准确价格。
- 给出推荐时要说明理由，理由要对应顾客说过的需求。
- 篇幅简短，像真人说话，不要写成产品说明书或长篇列表。
"""


def build_system_prompt():
    return SYSTEM_PROMPT.format(
        claim=kb.BRAND["claim"],
        principle=kb.BRAND["principle"],
        tone=kb.BRAND["tone"],
        forbidden=kb.BRAND["forbidden"],
        safety=kb.BRAND["safety"],
        catalog=_render_catalog(),
        combos=_render_combos(),
    )


# ---------------------------------------------------------------- 结构化抽取

EXTRACT_PROMPT = """从顾客这句话中抽取信息，只输出 JSON，不要其他文字。
没有明确提到的字段填 null，不要推测。

顾客说：{msg}

字段：
{{"skin_type": "偏干/偏油/敏感倾向/混合/null",
  "concerns": ["顾客提到的诉求，如 清洁/保湿/粗糙/控油"],
  "budget": 数字或null,
  "fragrance_averse": true/false/null,
  "travel_need": true/false/null,
  "acid_experience": true/false/null,
  "recommend_skus": ["你认为最匹配的 SKU，最多 2 个，不确定就空数组"]}}"""


def extract_info(client, message):
    """抽取结构化需求。失败时返回空 dict，不影响主流程。"""
    try:
        r = client.chat.completions.create(
            model=MODEL,
            messages=[{"role": "user", "content": EXTRACT_PROMPT.format(msg=message)}],
            temperature=0,
            response_format={"type": "json_object"},
        )
        return json.loads(r.choices[0].message.content)
    except Exception:
        return {}


def merge_state(state, info):
    """把抽取结果合并进会话状态，已知信息不被 null 覆盖。"""
    if not info:
        return state
    for k in ("skin_type", "budget", "fragrance_averse", "travel_need"):
        if info.get(k) is not None:
            state[k] = info[k]
    if info.get("concerns"):
        state["concerns"] = sorted(set(state.get("concerns", []) + info["concerns"]))
    if info.get("acid_experience") is not None:
        state["acid_experience"] = info["acid_experience"]
        state["acid_screened"] = True
    return state


# ---------------------------------------------------------------- 主回复


def reply(client, history, state):
    """生成导购回复。history 为 [{role, content}] 列表。"""
    msgs = [{"role": "system", "content": build_system_prompt()}]

    # 把已确认的顾客信息作为事实注入，减少重复追问
    known = {k: v for k, v in state.items() if k not in ("acid_screened",) and v}
    if known:
        msgs.append(
            {
                "role": "system",
                "content": "已确认的顾客信息（不要重复追问）："
                + json.dumps(known, ensure_ascii=False),
            }
        )

    msgs.extend(history)

    r = client.chat.completions.create(
        model=MODEL, messages=msgs, temperature=0.6, max_tokens=800
    )
    return r.choices[0].message.content
