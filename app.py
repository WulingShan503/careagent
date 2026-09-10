"""澄初个人护理 - AI 金牌导购

运行：streamlit run app.py
"""

import streamlit as st

import agent
import guard
import kb

st.set_page_config(page_title="澄初个人护理 · AI 导购", page_icon="🧴", layout="wide")


# ---------------------------------------------------------------- 状态初始化

def init():
    if "history" not in st.session_state:
        st.session_state.history = []
    if "profile" not in st.session_state:
        st.session_state.profile = {}
    if "trace" not in st.session_state:
        st.session_state.trace = []


init()


# ---------------------------------------------------------------- 侧边栏

with st.sidebar:
    st.subheader("产品目录")
    st.caption("Agent 的唯一事实来源，共 6 个 SKU")

    for p in kb.PRODUCTS.values():
        badge = ""
        if p.get("requires_screening"):
            badge = " ⚠️"
        if p.get("travel_only"):
            badge = " ✈️"
        with st.expander(f"{p['sku']} {p['name']}　{p['price']} 元{badge}"):
            st.write(f"**规格**　{p['spec']}")
            st.write(f"**特点**　{p['features']}")
            st.write(f"**适用**　{p['fit']}")
            st.write(f"**限制**　{p['limits']}")

    st.divider()
    st.subheader("可讨论组合")
    for c in kb.COMBOS:
        detail = " + ".join(str(kb.PRODUCTS[s]["price"]) for s in c["members"])
        st.write(f"**{' + '.join(c['members'])}**　{c['price']} 元")
        st.caption(f"{detail} = {c['price']}，无折扣　|　{c['scenario']}")

    st.divider()
    st.subheader("手册未覆盖")
    st.caption("命中即转交门店/系统确认，不由模型作答")
    st.write("　".join(kb.UNCOVERED_TOPICS))

    st.divider()
    if st.session_state.profile:
        st.subheader("已识别需求")
        st.json(st.session_state.profile)

    if st.button("清空对话", use_container_width=True):
        st.session_state.history = []
        st.session_state.profile = {}
        st.session_state.trace = []
        st.rerun()


# ---------------------------------------------------------------- 主区

st.title("澄初个人护理 · AI 金牌导购")
st.caption(
    "产品事实与价格来自品牌手册确定性查表；安全与政策边界由规则层前置拦截，不交给大模型自由判断。"
)

if not st.session_state.history:
    st.info(
        "试试这些问法：　“想买洗面奶，皮肤有点干”　·　"
        "“我想改善皮肤粗糙”　·　“有赠品吗？”　·　“用了之后有点刺痛”"
    )

# 渲染历史
for i, m in enumerate(st.session_state.history):
    with st.chat_message(m["role"], avatar="🧴" if m["role"] == "assistant" else None):
        st.markdown(m["content"])
        # 命中规则的回复附判定依据
        hit = next(
            (t for t in st.session_state.trace if t["turn"] == i), None
        )
        if hit:
            with st.expander(f"判定依据　·　{hit['label']}"):
                st.write(f"**触发词**　{'、'.join(hit['matched'])}")
                st.write(f"**依据规则**　{hit['rule']}")


TYPE_LABEL = {
    "discomfort": "安全边界拦截",
    "uncovered": "手册未覆盖 · 转交确认",
    "acid_screening": "果酸产品前置筛查",
}


def push(role, content):
    st.session_state.history.append({"role": role, "content": content})


if user_input := st.chat_input("请输入您的需求…"):
    push("user", user_input)
    with st.chat_message("user"):
        st.markdown(user_input)

    # 先从原话确认旅行需求，P301 是否可提及依赖它
    st.session_state.profile = guard.note_travel_need(
        user_input, st.session_state.profile
    )

    # --- 第一层：确定性护栏 ---
    blocked = guard.check_all(user_input, st.session_state.profile)

    if blocked:
        if blocked["type"] == "acid_screening":
            st.session_state.profile["acid_screened"] = True
        if blocked.get("blocked_products"):
            st.session_state.profile["blocked"] = blocked["blocked_products"]

        push("assistant", blocked["reply"])
        st.session_state.trace.append(
            {
                "turn": len(st.session_state.history) - 1,
                "label": TYPE_LABEL[blocked["type"]],
                "matched": blocked["matched"],
                "rule": blocked["rule"],
            }
        )
        with st.chat_message("assistant", avatar="🧴"):
            st.markdown(blocked["reply"])
            with st.expander(f"判定依据　·　{TYPE_LABEL[blocked['type']]}"):
                st.write(f"**触发词**　{'、'.join(blocked['matched'])}")
                st.write(f"**依据规则**　{blocked['rule']}")
        st.stop()

    # --- 第二层：抽取需求 + 模型生成 ---
    try:
        client = agent.get_client()
    except RuntimeError as e:
        st.error(str(e))
        st.stop()

    with st.chat_message("assistant", avatar="🧴"):
        with st.spinner("正在为您整理建议…"):
            info = agent.extract_info(client, user_input)
            st.session_state.profile = agent.merge_state(
                st.session_state.profile, info
            )
            try:
                answer = agent.reply(
                    client, st.session_state.history, st.session_state.profile
                )
            except Exception as e:
                st.error(f"调用模型失败：{e}")
                st.stop()

        # --- 第三层：输出校验 ---
        notes = []

        # P301 非护肤功效产品，旅行需求未明确时不得连带推荐
        if guard.audit_p301(answer, st.session_state.profile):
            answer = guard.strip_p301(answer)
            notes.append("已移除 P301 连带推荐：顾客未明确旅行携带需求（手册限制）")

        violations = guard.audit_reply(answer)
        if violations:
            notes.append(f"命中禁用表达：{'、'.join(violations)}，建议人工复核")

        st.markdown(answer)
        for n in notes:
            st.caption(f"⚙️ 输出校验　{n}")

    push("assistant", answer)
