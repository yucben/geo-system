# -*- coding: utf-8 -*-
"""
geo_engine.py  —  化妆品工厂 GEO 选题优先级引擎
====================================================
映射 CSDN 文章 (ximenjianxue/159200646) 的三大核心模块，但反馈信号
从「站内搜索的点击/停留」改造为「AI 引擎的引用反馈」，使其真正服务于
生成式引擎优化（GEO）。

原文章模块            →   本引擎对应实现
--------------------------------------------------------------
① 关键词语义分析       →   jieba 分词 + TF-IDF + 余弦相似度，把问题库语义聚类
② 检索权重动态调整     →   权重 = AI 引用反馈（提及/排位/链接/情感）算出的「覆盖度」
③ 用户行为反馈闭环     →   读 citations.csv（监测看板回流），算「引用缺口」
输出：GEO 排序         →   topic_ranking.csv（下一篇该写什么的优先级）

核心公式（改造自原文 score = similarity × weight）：
    选题优先级 priority_score = 业务价值 biz × 引用缺口 gap
    其中 gap = 1 - 当前AI引用覆盖度，覆盖度由 citations.csv 算出。
    含义：高业务价值 + 当前AI引用少 = 最该优先写的选题。

依赖：jieba, scikit-learn, numpy （均已安装，无需联网、无需模型下载）
用法：python geo_engine.py
"""

import os
import csv
import sys
from collections import defaultdict

# Windows 终端默认 GBK，强制 UTF-8 输出，避免控制台中文乱码
try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except (AttributeError, ValueError):
    pass

import numpy as np
import jieba
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

# ============================ 配置区 ============================
HERE = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(HERE, "data")
QUERIES_CSV = os.path.join(DATA_DIR, "queries.csv")
CITATIONS_CSV = os.path.join(DATA_DIR, "citations.csv")
OUT_RANKING = os.path.join(DATA_DIR, "topic_ranking.csv")
OUT_CLUSTERS = os.path.join(DATA_DIR, "cluster_summary.csv")

# 你关注的目标 AI 引擎（缺口计算的分母基准）
TARGET_ENGINES = ["doubao", "deepseek", "qwen", "wenxin", "yuanbao", "kimi"]

# 语义聚类阈值：余弦相似度 ≥ 该值的两个问题归为一簇（0~1，越大越严格）
CLUSTER_SIM_THRESHOLD = 0.18

# 中文停用词（高频但无区分度，避免干扰聚类）
STOPWORDS = {"的", "了", "吗", "和", "是", "有", "找", "大概", "要", "做",
             "怎么样", "哪", "多少", "个", "啊", "呢", "吧"}

# 引用强度子项权重（可调）
W_LINK_BONUS = 0.3      # 给了链接的加分
W_SENT_POS = 0.2        # 正面描述加分
W_SENT_NEG = -0.2       # 负面描述减分
PER_ENGINE_GOOD = 1.0   # 单引擎「表现良好」的基准分，用于归一化覆盖度
# ===============================================================


def jieba_tokenizer(text):
    """jieba 分词 + 去停用词，供 TF-IDF 使用。"""
    return [w for w in jieba.cut(text) if w.strip() and w not in STOPWORDS]


def read_queries(path):
    """读问题库，仅保留 status=active 的问题。"""
    if not os.path.exists(path):
        sys.exit(f"[错误] 找不到问题库：{path}")
    rows = []
    with open(path, encoding="utf-8-sig") as f:
        for r in csv.DictReader(f):
            if r.get("status", "active").strip() == "active":
                r["priority_seed"] = float(r.get("priority_seed", 3) or 3)
                rows.append(r)
    if not rows:
        sys.exit("[错误] 问题库里没有 active 的问题。")
    return rows


def read_citations(path):
    """读 AI 引用反馈，按 query_id 聚合。文件不存在则返回空（冷启动）。"""
    by_q = defaultdict(list)
    if not os.path.exists(path):
        return by_q, False
    with open(path, encoding="utf-8-sig") as f:
        for r in csv.DictReader(f):
            by_q[r["query_id"].strip()].append(r)
    return by_q, True


def citation_strength(row):
    """单条引用记录的强度：未提及=0；提及则按排位+链接+情感加权。"""
    if str(row.get("mentioned", "0")).strip() not in ("1", "1.0"):
        return 0.0
    try:
        pos = int(float(row.get("position", 0) or 0))
    except ValueError:
        pos = 0
    # 排位分：第1位=1.0，第5位=0.2，未知位置给中性 0.5
    pos_score = (6 - pos) / 5 if 1 <= pos <= 5 else 0.5
    link_bonus = W_LINK_BONUS if str(row.get("has_link", "0")).strip() in ("1", "1.0") else 0.0
    sent = row.get("sentiment", "neu").strip().lower()
    sent_bonus = W_SENT_POS if sent == "pos" else (W_SENT_NEG if sent == "neg" else 0.0)
    return max(0.0, pos_score + link_bonus + sent_bonus)


def compute_coverage(cit_rows):
    """聚合某问题的引用覆盖度，返回 (覆盖度0~1, 已引用引擎集合)。"""
    cited_engines = set()
    raw = 0.0
    for r in cit_rows:
        s = citation_strength(r)
        if s > 0:
            cited_engines.add(r.get("engine", "").strip().lower())
            raw += s
    coverage = min(1.0, raw / (len(TARGET_ENGINES) * PER_ENGINE_GOOD))
    return coverage, cited_engines


def cluster_queries(queries):
    """TF-IDF + 余弦相似度 + 并查集，把语义相近的问题归簇。"""
    texts = [q["query"] for q in queries]
    vec = TfidfVectorizer(tokenizer=jieba_tokenizer, token_pattern=None)
    tfidf = vec.fit_transform(texts)
    sim = cosine_similarity(tfidf)

    n = len(queries)
    parent = list(range(n))

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[max(ra, rb)] = min(ra, rb)

    for i in range(n):
        for j in range(i + 1, n):
            if sim[i, j] >= CLUSTER_SIM_THRESHOLD:
                union(i, j)

    # 归一化簇 id：按首次出现顺序编号
    root_to_cid, cids = {}, []
    for i in range(n):
        root = find(i)
        if root not in root_to_cid:
            root_to_cid[root] = len(root_to_cid) + 1
        cids.append(root_to_cid[root])
    return cids


def main():
    print("=" * 64)
    print("  化妆品工厂 GEO 选题优先级引擎  (geo_engine.py)")
    print("=" * 64)

    queries = read_queries(QUERIES_CSV)
    cit_by_q, has_cit = read_citations(CITATIONS_CSV)
    if not has_cit or not cit_by_q:
        print("\n[提示] 未读到引用反馈数据 → 冷启动模式：")
        print("       覆盖度全部记为 0，优先级 = 纯业务价值。")
        print("       先按此排序去各引擎跑基线，回填 citations.csv 后再跑一次。\n")

    cids = cluster_queries(queries)

    # 逐题打分
    results = []
    for q, cid in zip(queries, cids):
        biz = q["priority_seed"] / 5.0  # 业务价值归一化 0.2~1.0
        cov, cited = compute_coverage(cit_by_q.get(q["id"], []))
        gap = 1.0 - cov
        priority = round(biz * gap, 4)
        missing = [e for e in TARGET_ENGINES if e not in cited]
        results.append({
            "cluster_id": cid,
            "query_id": q["id"],
            "query": q["query"],
            "intent": q["intent"],
            "priority_seed": int(q["priority_seed"]),
            "biz": round(biz, 3),
            "coverage": round(cov, 3),
            "gap": round(gap, 3),
            "priority_score": priority,
            "cited_engines": "|".join(sorted(cited)) if cited else "-",
            "missing_engines": "|".join(missing),
            "recommendation": recommend(biz, cov, gap),
        })

    results.sort(key=lambda x: x["priority_score"], reverse=True)

    # 写 topic_ranking.csv
    fields = ["cluster_id", "query_id", "query", "intent", "priority_seed",
              "biz", "coverage", "gap", "priority_score",
              "cited_engines", "missing_engines", "recommendation"]
    with open(OUT_RANKING, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(results)

    # 簇级汇总
    write_cluster_summary(results)

    # 控制台报告
    print_report(results)
    print(f"\n[输出] 选题优先级 → {OUT_RANKING}")
    print(f"[输出] 簇级汇总   → {OUT_CLUSTERS}")


def recommend(biz, cov, gap):
    """给文案手的一句话行动建议。"""
    if biz >= 0.8 and gap >= 0.7:
        return "高价值且几乎没被引用 → 立刻优先写"
    if biz >= 0.8 and gap < 0.4:
        return "已有不错引用 → 优化冲第1位/补缺口引擎"
    if gap >= 0.8:
        return "几乎空白 → 适合铺新内容试探"
    if cov >= 0.6:
        return "覆盖较好 → 维护即可，勿过度投入"
    return "中等机会 → 排期常规产出"


def write_cluster_summary(results):
    clusters = defaultdict(list)
    for r in results:
        clusters[r["cluster_id"]].append(r)
    rows = []
    for cid, items in clusters.items():
        rep = max(items, key=lambda x: x["priority_seed"])  # 业务价值最高者作代表
        rows.append({
            "cluster_id": cid,
            "size": len(items),
            "representative_query": rep["query"],
            "queries": " / ".join(i["query"] for i in items),
            "cluster_priority": round(sum(i["priority_score"] for i in items), 4),
            "avg_coverage": round(sum(i["coverage"] for i in items) / len(items), 3),
        })
    rows.sort(key=lambda x: x["cluster_priority"], reverse=True)
    with open(OUT_CLUSTERS, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["cluster_id", "size",
                          "representative_query", "queries",
                          "cluster_priority", "avg_coverage"])
        w.writeheader()
        w.writerows(rows)


def print_report(results):
    print("\n【选题优先级 TOP 10】（priority = 业务价值 × 引用缺口）")
    print("-" * 64)
    for i, r in enumerate(results[:10], 1):
        print(f"{i:>2}. [{r['priority_score']:.3f}] {r['query']}")
        print(f"     簇{r['cluster_id']} | {r['intent']} | 覆盖度{r['coverage']} "
              f"缺口{r['gap']} | 缺失引擎:{r['missing_engines']}")
        print(f"     → {r['recommendation']}")


if __name__ == "__main__":
    main()
