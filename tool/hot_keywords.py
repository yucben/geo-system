# -*- coding: utf-8 -*-
"""
hot_keywords.py  —  化妆品行业热点 → 问题库（映射 CSDN 文章模块④「热点关键词抓取」）
======================================================================
原文章：接百度指数/微博热搜，自动更新高流量关键词。
本实现：
  - 默认走【本地种子模式】：读 data/hot_seeds.csv（人工/运营维护的行业热词），
    转成 AI 提问句式，去重后并入 queries.csv。立刻可用、无需联网。
  - 预留【真实接口模式】：百度指数 / 巨量算数 / 微博热搜 的接入位置已写好骨架，
    但需要你自备 API key 或 cookie —— 这些平台均无免费公开接口，
    诚实标注为占位，不假装能跑。

用法：
  python hot_keywords.py            # 本地种子模式，并入问题库
  python hot_keywords.py --dry-run  # 只预览要新增的问题，不写入
"""

import os
import csv
import sys
from collections import OrderedDict

try:
    sys.stdout.reconfigure(encoding="utf-8")
except (AttributeError, ValueError):
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(HERE, "data")
SEEDS_CSV = os.path.join(DATA_DIR, "hot_seeds.csv")
QUERIES_CSV = os.path.join(DATA_DIR, "queries.csv")

# 热词 → AI 提问句式的模板。一个热词可派生多条不同意图的问题。
QUESTION_TEMPLATES = {
    "选型": "{kw}代工厂哪家好",
    "推荐": "{kw}代工厂推荐",
    "趋势": "{kw}代工趋势",
    "参数": "{kw}代工起订量多少",
}


def read_seeds(path):
    """读本地热词种子。字段：keyword, heat, intent, source"""
    if not os.path.exists(path):
        sys.exit(f"[错误] 找不到热词种子文件：{path}\n     请先创建 data/hot_seeds.csv")
    seeds = []
    with open(path, encoding="utf-8-sig") as f:
        for r in csv.DictReader(f):
            kw = r.get("keyword", "").strip()
            if kw:
                seeds.append({
                    "keyword": kw,
                    "heat": int(float(r.get("heat", 50) or 50)),
                    "intent": r.get("intent", "趋势").strip() or "趋势",
                    "source": r.get("source", "manual").strip(),
                })
    return seeds


def existing_queries(path):
    """读现有问题库，返回 (现有问题文本集合, 最大ID序号)。"""
    texts, max_id = set(), 0
    if os.path.exists(path):
        with open(path, encoding="utf-8-sig") as f:
            for r in csv.DictReader(f):
                texts.add(r["query"].strip())
                num = "".join(ch for ch in r.get("id", "") if ch.isdigit())
                if num:
                    max_id = max(max_id, int(num))
    return texts, max_id


def seeds_to_questions(seeds):
    """把热词按意图模板派生成 AI 提问句。热度→优先级种子(1~5)。"""
    out = []
    for s in seeds:
        tmpl = QUESTION_TEMPLATES.get(s["intent"], QUESTION_TEMPLATES["趋势"])
        q = tmpl.format(kw=s["keyword"])
        # 热度 0~100 映射到优先级 1~5
        prio = max(1, min(5, round(s["heat"] / 20)))
        out.append({"query": q, "intent": s["intent"],
                    "priority_seed": prio, "source": s["source"]})
    return out


def main():
    dry = "--dry-run" in sys.argv
    seeds = read_seeds(SEEDS_CSV)
    derived = seeds_to_questions(seeds)
    existing, max_id = existing_queries(QUERIES_CSV)

    # 去重：句子已存在则跳过
    fresh = OrderedDict()
    for d in derived:
        if d["query"] not in existing and d["query"] not in fresh:
            fresh[d["query"]] = d

    print("=" * 60)
    print("  热点关键词 → 问题库  (hot_keywords.py / 本地种子模式)")
    print("=" * 60)
    print(f"读入热词 {len(seeds)} 个，派生问题 {len(derived)} 条，"
          f"去重后新增 {len(fresh)} 条。\n")

    if not fresh:
        print("没有新问题可加入（都已存在）。")
        return

    new_rows = []
    for i, (q, d) in enumerate(fresh.items(), 1):
        new_id = f"Q{max_id + i:02d}"
        print(f"  + {new_id} [{d['intent']}|热度种子{d['priority_seed']}] {q}")
        new_rows.append([new_id, q, d["intent"], d["priority_seed"], "active"])

    if dry:
        print("\n[--dry-run] 仅预览，未写入 queries.csv。")
        return

    # 追加写入问题库
    with open(QUERIES_CSV, "a", encoding="utf-8-sig", newline="") as f:
        csv.writer(f).writerows(new_rows)
    print(f"\n[完成] 已追加 {len(new_rows)} 条到 {QUERIES_CSV}")
    print("       下一步：跑 python geo_engine.py 重新排选题优先级。")


# ============================================================
# 以下为【真实接口模式】骨架 —— 需自备凭证，当前为占位，不会被默认调用。
# ============================================================
def fetch_baidu_index(keywords, cookie=None):
    """
    百度指数：无官方免费 API。真实接入需登录 cookie + 解密其加密的指数值。
    占位：返回空。接入指南见 workflow/03 文档或自行搜索「百度指数 爬虫」。
    """
    raise NotImplementedError(
        "百度指数需自备登录 cookie 与解密逻辑，未实现。请用本地种子模式。")


def fetch_juliang_suanshu(keywords, token=None):
    """
    巨量算数（抖音热词）：需巨量引擎开放平台账号 + token。
    占位：返回空。
    """
    raise NotImplementedError(
        "巨量算数需开放平台 token，未实现。请用本地种子模式。")


if __name__ == "__main__":
    main()
