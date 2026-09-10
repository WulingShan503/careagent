"""确定性护栏层

在调用大模型之前先做规则判定。命中的场景走固定话术，不交给模型自由发挥，
以满足「判断依据来自题目给定规则，不允许只依赖大模型常识自由判断」。

三类拦截：
  1. 皮肤不适 / 医疗诉求  -> 安全话术 + 建议咨询专业人士
  2. 手册未覆盖的政策话题 -> 明确说明需向门店或系统确认
  3. 果酸产品前置筛查     -> 提示必须先确认敏感与使用经验
"""

import re

from kb import UNCOVERED_REPLY, hits_uncovered

# ---------------------------------------------------------------- 场景词表

# 皮肤不适 / 受损 / 医疗诉求
DISCOMFORT_PATTERNS = [
    "不舒服", "刺痛", "刺痒", "发红", "红肿", "过敏", "脱皮", "爆皮",
    "灼热", "烧得", "刺激", "泛红", "痒", "肿", "破皮", "受损", "屏障受损",
    "湿疹", "皮炎", "激素脸", "痘痘发炎", "脓", "伤口",
]

MEDICAL_PATTERNS = ["能治", "治好", "治疗", "治愈", "药", "医生说", "确诊", "皮肤病"]

# 果酸敏感度筛查触发（用户主动询问 P201 或果酸相关）
ACID_PATTERNS = ["果酸", "刷酸", "焕肤", "p201", "P201", "去角质", "粗糙"]

# 绝对化 / 承诺类表达 —— 用于回复后置校验
FORBIDDEN_OUTPUT = [
    "治愈", "治疗", "保证有效", "绝对不过敏", "马上见效", "立刻见效",
    "一定有效", "包好", "根治", "永久", "100%", "最好的", "第一",
]


def _hit(text, patterns):
    lowered = text.lower()
    return [p for p in patterns if p.lower() in lowered]


# ---------------------------------------------------------------- 拦截判定


def check_discomfort(text):
    """检测皮肤不适或医疗诉求。命中返回固定安全话术。"""
    d = _hit(text, DISCOMFORT_PATTERNS)
    m = _hit(text, MEDICAL_PATTERNS)
    if not d and not m:
        return None

    reply = (
        "听起来您的皮肤现在状态不太稳定，这种情况我不方便替您判断原因。\n\n"
        "建议先暂停正在使用的功效类产品，尤其是含酸类等有刺激性的产品，"
        "让皮肤先安静一段时间；如果不适持续或加重，请咨询皮肤科医生或专业人士。\n\n"
        "等状态恢复稳定之后，我再帮您看看日常清洁和保湿可以怎么安排。"
    )
    return {
        "type": "discomfort",
        "reply": reply,
        "matched": d + m,
        "rule": "手册「安全边界」：不作医疗诊断；提到明显不适、受损或持续问题时，"
                "建议停止刺激性尝试并咨询专业人士。",
        "blocked_products": ["P201"],
    }


def check_uncovered(text):
    """检测手册未覆盖的政策话题。命中返回转交确认话术。"""
    topics = hits_uncovered(text)
    if not topics:
        return None

    joined = "、".join(topics)
    reply = (
        f"关于{joined}这部分，我手上的品牌资料里没有相关政策说明，"
        f"所以不能给您一个确定的答复 —— {UNCOVERED_REPLY}。\n\n"
        "如果您方便的话，可以到门店由店员帮您查一下系统，"
        "那边的信息会比我这里准确。产品本身的成分、适用情况和价格我可以直接告诉您。"
    )
    return {
        "type": "uncovered",
        "reply": reply,
        "matched": topics,
        "rule": "手册末注：未提供促销、赠品、线上同价、退换货或渠道授权政策，"
                "遇到此类问题应说明「需要向门店或系统确认」。",
    }


def needs_acid_screening(text, state):
    """判断是否触及果酸产品且尚未完成前置筛查。"""
    if not _hit(text, ACID_PATTERNS):
        return False
    return not state.get("acid_screened", False)


ACID_SCREENING_PROMPT = (
    "在聊这类产品之前，有两件事想先确认一下：\n\n"
    "1. 您的皮肤目前有没有敏感、刺痛或者正在不适的情况？\n"
    "2. 之前有用过果酸或类似的焕肤产品吗？\n\n"
    "这两点会直接影响它适不适合您，所以我想先问清楚，而不是直接推荐。"
)


# ---------------------------------------------------------------- 输出校验


def audit_reply(text):
    """检查模型回复是否出现禁用表达。返回命中列表（空表示通过）。"""
    return _hit(text, FORBIDDEN_OUTPUT)


TRAVEL_PATTERNS = ["出差", "旅行", "旅游", "外出", "带着", "携带", "分装", "小瓶", "便携", "过夜", "住酒店"]


def audit_p301(text, state):
    """P301 是旅行分装瓶，非护肤功效产品。

    手册规定「仅在旅行携带需求明确时连带推荐」。模型有时会拿它 49 元的低价
    去凑顾客预算，这属于强推连带购买，必须拦。

    返回 True 表示这次提及不合规。
    """
    if "P301" not in text:
        return False
    return not state.get("travel_need")


def note_travel_need(text, state):
    """从顾客原话中确认旅行携带需求，写入会话状态。"""
    if _hit(text, TRAVEL_PATTERNS):
        state["travel_need"] = True
    return state


def strip_p301(text):
    """移除回复中提及 P301 的段落，避免不合规连带推荐流到用户面前。"""
    blocks = re.split(r"\n{2,}", text)
    kept = [b for b in blocks if "P301" not in b]
    if not kept:
        return text
    return "\n\n".join(kept).strip()


def check_all(text, state):
    """统一入口。按优先级返回第一个命中的拦截结果，无命中返回 None。

    优先级：不适 > 未覆盖政策 > 果酸筛查
    不适优先于一切，因为它涉及安全。
    """
    for fn in (check_discomfort, check_uncovered):
        r = fn(text)
        if r:
            return r

    if needs_acid_screening(text, state):
        return {
            "type": "acid_screening",
            "reply": ACID_SCREENING_PROMPT,
            "matched": _hit(text, ACID_PATTERNS),
            "rule": "手册 P201 限制：敏感、受损或正在不适的皮肤不推荐；"
                    "先问敏感/不适和使用经验；说明注意防晒，不强推。",
        }

    return None
