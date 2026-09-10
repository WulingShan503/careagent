"""澄初个人护理 - 产品知识库

所有数据逐字取自《澄初个人护理 智能导购品牌手册》，不做任何推测补全。
Agent 的一切产品事实、价格、组合与限制均以本文件为唯一来源。
"""

# ---------------------------------------------------------------- 产品目录

PRODUCTS = {
    "P101": {
        "sku": "P101",
        "name": "云感氨基酸舒润洁面乳",
        "spec": "150ml",
        "price": 169,
        "category": "洁面",
        "features": "无香型、低泡、洗后易冲净",
        "fit": "偏干或敏感倾向用户可考虑",
        "limits": "个体差异，首次使用建议局部测试",
        "fragrance": False,
    },
    "P102": {
        "sku": "P102",
        "name": "净澈控油洁面凝胶",
        "spec": "150ml",
        "price": 149,
        "category": "洁面",
        "features": "清洁感较强、带香味",
        "fit": "偏油且偏好清爽肤感者",
        "limits": "对香味敏感者不优先",
        "fragrance": True,
    },
    "P201": {
        "sku": "P201",
        "name": "焕亮果酸细致精华液",
        "spec": "30ml",
        "price": 229,
        "category": "精华",
        "features": "含 8% 果酸复合成分",
        "fit": "有相关使用经验、希望改善粗糙者",
        "limits": "敏感、受损或正在不适的皮肤不推荐；需注意防晒",
        "fragrance": None,
        # 果酸类产品，推荐前必须完成前置确认
        "requires_screening": True,
    },
    "P202": {
        "sku": "P202",
        "name": "屏护神经酰胺保湿乳",
        "spec": "50ml",
        "price": 259,
        "category": "保湿",
        "features": "无香型、含神经酰胺类保湿成分",
        "fit": "干燥、屏障脆弱倾向用户可考虑",
        "limits": "不承诺治疗；明显不适建议咨询专业人士",
        "fragrance": False,
    },
    "P203": {
        "sku": "P203",
        "name": "水漾轻盈保湿凝露",
        "spec": "50ml",
        "price": 219,
        "category": "保湿",
        "features": "清爽质地、带淡香",
        "fit": "偏油、喜欢轻薄肤感者",
        "limits": "对香味敏感者不优先",
        "fragrance": True,
    },
    "P301": {
        "sku": "P301",
        "name": "随行旅行分装瓶礼盒",
        "spec": "4 个可重复使用小瓶",
        "price": 49,
        "category": "配件",
        "features": "4 个可重复使用小瓶",
        "fit": "出差、旅行携带",
        "limits": "不属于护肤功效产品",
        "fragrance": None,
        # 仅在旅行携带需求明确时才可连带推荐
        "travel_only": True,
    },
}

# ---------------------------------------------------------------- 组合方案
# 手册「三、组合与边界」。组合价等于成员单价之和，无折扣。

COMBOS = [
    {
        "id": "C1",
        "members": ["P101", "P202"],
        "price": 428,
        "scenario": "偏干、敏感倾向、希望简单护理",
        "note": "先确认预算；不以“修复/治疗”承诺效果。",
    },
    {
        "id": "C2",
        "members": ["P102", "P203"],
        "price": 368,
        "scenario": "偏油、可接受香味、喜欢清爽感",
        "note": "先确认预算与香味偏好。",
    },
]

# ---------------------------------------------------------------- 手册未覆盖
# 遇到这些话题必须转交门店/系统确认，不得自行回答。

UNCOVERED_TOPICS = ["促销", "赠品", "线上同价", "退换货", "渠道授权"]

# 顾客的实际说法与手册术语不一致，做同义扩展用于命中检测。
# 例如手册写「线上同价」，顾客会说「网上更便宜」。
UNCOVERED_ALIASES = {
    "促销": ["促销", "活动", "打折", "折扣", "优惠", "满减", "特价", "降价", "便宜点"],
    "赠品": ["赠品", "赠送", "送什么", "送不送", "小样", "试用装", "礼品", "买一送"],
    "线上同价": ["线上同价", "网上", "线上", "旗舰店", "直播间", "电商", "同价", "比价", "拼多多", "淘宝", "京东", "抖音"],
    "退换货": ["退换货", "退货", "换货", "退款", "七天无理由", "不满意能退"],
    "渠道授权": ["渠道授权", "正品", "授权", "专柜", "代购", "水货", "假货"],
}

UNCOVERED_REPLY = "需要向门店或系统确认"

# ---------------------------------------------------------------- 品牌约束

BRAND = {
    "claim": "用清晰、克制的产品信息，帮助顾客做适合自己的日常护理选择。",
    "principle": "先了解需求，再提出选择；不制造焦虑，不夸大效果，不强推连带购买。",
    "tone": "温和、具体、尊重顾客决定。使用“可以考虑”“如果您在意……”等表达。",
    "forbidden": "不说“治愈、治疗、保证有效、绝对不过敏、马上见效”；不对价格、赠品、退换或授权作无依据承诺。",
    "safety": "不作医疗诊断。顾客提到明显不适、受损或持续问题时，建议停止刺激性尝试并咨询专业人士。",
}


# ---------------------------------------------------------------- 查询函数


def get_product(sku):
    """按 SKU 取产品，不存在返回 None。"""
    return PRODUCTS.get(sku.strip().upper())


def combo_total(skus):
    """计算给定 SKU 列表的合计金额。

    返回 (合计, 明细列表)。未知 SKU 被忽略并记入 unknown。
    """
    items, unknown, total = [], [], 0
    for sku in skus:
        p = get_product(sku)
        if p is None:
            unknown.append(sku)
            continue
        items.append({"sku": p["sku"], "name": p["name"], "price": p["price"]})
        total += p["price"]
    return total, items, unknown


def find_combo(skus):
    """判断一组 SKU 是否命中手册中的官方组合。"""
    target = set(s.strip().upper() for s in skus)
    for c in COMBOS:
        if set(c["members"]) == target:
            return c
    return None


def hits_uncovered(text):
    """检测用户输入是否触及手册未覆盖的政策话题。

    返回命中的手册话题名列表（去重、保持手册顺序）。匹配走同义词扩展，
    因为顾客的说法通常和手册术语不一致（「网上更便宜」对应「线上同价」）。
    """
    hits = []
    for topic in UNCOVERED_TOPICS:
        for alias in UNCOVERED_ALIASES.get(topic, [topic]):
            if alias in text:
                hits.append(topic)
                break
    return hits
