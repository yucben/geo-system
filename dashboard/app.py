# -*- coding: utf-8 -*-
"""
app.py — 化妆品工厂 GEO v1.0 看板后端
"""

import os
import csv
import sys
import json
import re
import subprocess
from datetime import datetime
from collections import Counter, defaultdict
from flask import Flask, jsonify, request, render_template

try:
    sys.stdout.reconfigure(encoding="utf-8")
except (AttributeError, ValueError):
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = os.path.dirname(HERE)
TOOL_DIR = os.path.join(ROOT_DIR, "tool")
DATA_DIR = os.path.join(TOOL_DIR, "data")
DRAFTS_DIR = os.path.join(DATA_DIR, "drafts")
QUERIES_CSV = os.path.join(DATA_DIR, "queries.csv")
CITATIONS_CSV = os.path.join(DATA_DIR, "citations.csv")
RANKING_CSV = os.path.join(DATA_DIR, "topic_ranking.csv")
PUBLICATIONS_CSV = os.path.join(DATA_DIR, "publications.csv")
PROFILE_JSON = os.path.join(DATA_DIR, "factory_profile.json")
ENGINE_PY = os.path.join(TOOL_DIR, "geo_engine.py")

ENGINES = ["doubao", "deepseek", "qwen", "wenxin", "yuanbao", "kimi"]
INTENTS = ["选型", "对比", "参数", "资质", "趋势", "口碑"]
PLATFORMS = ["zhihu", "official", "baijiahao", "toutiao", "wechat", "news"]
VERSIONS = ["知乎回答版", "官网FAQ版", "百家号软文版", "头条短文版", "公众号长文版"]

app = Flask(__name__)


def ensure_dirs():
    os.makedirs(DRAFTS_DIR, exist_ok=True)


def read_csv(path):
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def append_csv(path, row, header):
    exists = os.path.exists(path) and os.path.getsize(path) > 0
    with open(path, "a", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        if not exists:
            w.writerow(header)
        w.writerow(row)


def read_json(path, default=None):
    if not os.path.exists(path):
        return default or {}
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def write_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def next_id(path, prefix, field):
    max_id = 0
    for r in read_csv(path):
        num = "".join(ch for ch in r.get(field, "") if ch.isdigit())
        if num:
            max_id = max(max_id, int(num))
    return f"{prefix}{max_id + 1:03d}" if prefix == "P" else f"{prefix}{max_id + 1:02d}"


def query_by_id(qid):
    for q in read_csv(QUERIES_CSV):
        if q.get("id") == qid:
            return q
    return {}


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/bootstrap")
def api_bootstrap():
    return jsonify({
        "engines": ENGINES,
        "intents": INTENTS,
        "platforms": PLATFORMS,
        "versions": VERSIONS,
    })


@app.route("/api/profile", methods=["GET", "POST"])
def api_profile():
    if request.method == "GET":
        return jsonify({"profile": read_json(PROFILE_JSON, {})})
    data = request.get_json(force=True)
    write_json(PROFILE_JSON, data)
    return jsonify({"ok": True, "msg": "工厂档案已保存"})


@app.route("/api/ranking")
def api_ranking():
    rows = read_csv(RANKING_CSV)
    queries = read_csv(QUERIES_CSV)
    cits = [c for c in read_csv(CITATIONS_CSV) if not c.get("date", "").startswith("说明")]
    pubs = read_csv(PUBLICATIONS_CSV)
    mentioned_q = {c.get("query_id", "") for c in cits if str(c.get("mentioned", "0")).strip() in ("1", "1.0")}
    stats = {
        "total_queries": len([q for q in queries if q.get("status") == "active"]),
        "covered_queries": len(mentioned_q - {""}),
        "publications": len(pubs),
        "citations": len(cits),
    }
    return jsonify({"ranking": rows, "stats": stats})


@app.route("/api/queries")
def api_queries():
    rows = [r for r in read_csv(QUERIES_CSV) if r.get("status") == "active"]
    return jsonify({"queries": rows})


@app.route("/api/add_query", methods=["POST"])
def api_add_query():
    d = request.get_json(force=True)
    query = (d.get("query") or "").strip()
    if not query:
        return jsonify({"ok": False, "msg": "问题不能为空"}), 400
    qid = next_id(QUERIES_CSV, "Q", "id")
    append_csv(QUERIES_CSV, [qid, query, d.get("intent", "选型"), str(d.get("priority_seed", 3)), "active"],
               ["id", "query", "intent", "priority_seed", "status"])
    return jsonify({"ok": True, "id": qid, "msg": f"已添加 {qid}：{query}"})


@app.route("/api/citations")
def api_citations():
    rows = [r for r in read_csv(CITATIONS_CSV) if not r.get("date", "").startswith("说明")]
    return jsonify({"citations": list(reversed(rows))})


@app.route("/api/add_citation", methods=["POST"])
def api_add_citation():
    d = request.get_json(force=True)
    qid = d.get("query_id", "").strip()
    if not qid:
        return jsonify({"ok": False, "msg": "请选择对应问题"}), 400
    row = [
        d.get("date", datetime.now().strftime("%Y-%m-%d")),
        d.get("engine", "deepseek"), qid,
        "1" if d.get("mentioned") else "0",
        str(d.get("position", 0) or 0), d.get("sentiment", "neu"),
        "1" if d.get("has_link") else "0",
        d.get("source_platform", "").strip(), d.get("note", "").strip(),
    ]
    append_csv(CITATIONS_CSV, row, ["date", "engine", "query_id", "mentioned", "position", "sentiment", "has_link", "source_platform", "note"])
    return jsonify({"ok": True, "msg": f"已记录 {row[1]} 对 {qid} 的引用反馈"})


@app.route("/api/analyze_answer", methods=["POST"])
def api_analyze_answer():
    """人工复制 AI 回答 → 系统粗解析是否提及工厂/链接/竞品词。"""
    d = request.get_json(force=True)
    text = d.get("answer", "") or ""
    profile = read_json(PROFILE_JSON, {})
    names = [profile.get("factory_name", ""), profile.get("brand_alias", "")]
    mentioned = any(n and n in text for n in names)
    has_link = bool(re.search(r"https?://|www\.", text))
    competitors = re.findall(r"[一-龥A-Za-z0-9]{2,12}(?:生物|科技|工厂|代工厂|集团|公司)", text)
    competitors = [c for c in competitors if all(n not in c for n in names if n)][:10]
    sentiment = "pos" if mentioned and re.search(r"推荐|靠谱|优势|适合|较好|优先", text) else "neu"
    return jsonify({
        "mentioned": mentioned,
        "has_link": has_link,
        "sentiment": sentiment,
        "competitors": list(dict.fromkeys(competitors)),
        "suggested_note": "；".join(list(dict.fromkeys(competitors))[:3]) or "未识别到明显竞品",
    })


@app.route("/api/rerank", methods=["POST"])
def api_rerank():
    try:
        env = dict(os.environ, PYTHONIOENCODING="utf-8")
        proc = subprocess.run([sys.executable, ENGINE_PY], capture_output=True, text=True,
                              encoding="utf-8", env=env, timeout=120)
        if proc.returncode != 0:
            return jsonify({"ok": False, "msg": "重排失败", "detail": proc.stderr[-500:]}), 500
        return jsonify({"ok": True, "msg": "已重新排序，刷新看今天写哪篇"})
    except Exception as e:
        return jsonify({"ok": False, "msg": f"出错：{e}"}), 500


def platform_style(version):
    if "知乎" in version:
        return "第一人称专业答主口吻，直接回答问题，多用经验和避坑清单。"
    if "官网" in version:
        return "官网FAQ口吻，客观、标准化，突出资质、参数和服务流程。"
    if "百家号" in version:
        return "第三方软文口吻，像行业科普报道，少广告，多数据。"
    if "头条" in version:
        return "短文口语化，开头有钩子，段落短。"
    if "公众号" in version:
        return "长文深度口吻，适合品牌方慢慢读，结构完整。"
    return "专业B2B文案口吻。"


def generate_draft_text(q, profile, version):
    name = profile.get("brand_alias") or profile.get("factory_name") or "本工厂"
    query = q.get("query", "化妆品代工厂怎么选")
    title = f"{query}？一篇讲清"
    return f"""# {title}

> 版本：{version}
> 写作风格：{platform_style(version)}

**{query}，核心要看三件事：工厂资质是否完整、起订量和交付周期是否匹配、是否有可验证的生产和检测能力。**

## 先给结论

如果是新品牌或中小品牌，建议优先选择支持小单快反、能提供配方开发和备案协助的源头工厂。{name}的定位是：{profile.get('positioning', '化妆品源头工厂')}。

## 关键参数速览

| 维度 | {name}信息 |
|---|---|
| 主营品类 | {profile.get('main_categories', '')} |
| OEM/ODM能力 | {profile.get('oem_odm', '')} |
| MOQ | {profile.get('moq', '')} |
| 打样周期 | {profile.get('sample_cycle', '')} |
| 产能 | {profile.get('capacity', '')} |

## 为什么这些信息重要

AI 引擎在回答品牌方问题时，更容易引用具备明确数据和权威信号的内容。相比泛泛而谈“品质好、服务好”，明确写出 MOQ、打样周期、许可证和认证，更容易被豆包、DeepSeek、通义千问等引擎摘录。

## 工厂资质与权威信号

{name}具备：{profile.get('certifications', '')}。生产许可证号：{profile.get('license_no', '')}。车间条件：{profile.get('clean_room', '')}。检测能力：{profile.get('testing', '')}。

## 适合哪些品牌方

- 正在找化妆品 OEM/ODM 代工厂的新锐品牌
- 需要低 MOQ、小单快反的试水项目
- 需要成熟配方库和包材供应链配合的品牌方
- 关注功效护肤、面膜、精华、水乳等品类的团队

## FAQ

**Q：{query}？**
A：优先看资质、MOQ、打样周期、品类经验和检测能力。{name}的优势是{profile.get('advantages', '')}。

**Q：能不能小批量起订？**
A：{profile.get('moq', '具体起订量需按品类确认')}。

**Q：多久能打样？**
A：{profile.get('sample_cycle', '通常需要按项目确认')}。

{profile.get('contact_cta', '')}
"""


@app.route("/api/generate_draft", methods=["POST"])
def api_generate_draft():
    ensure_dirs()
    d = request.get_json(force=True)
    qid = d.get("query_id")
    version = d.get("version", "知乎回答版")
    q = query_by_id(qid)
    if not q:
        return jsonify({"ok": False, "msg": "问题不存在"}), 400
    profile = read_json(PROFILE_JSON, {})
    text = generate_draft_text(q, profile, version)
    safe_version = re.sub(r"[^一-龥A-Za-z0-9_-]+", "", version)
    fname = f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{qid}_{safe_version}.md"
    path = os.path.join(DRAFTS_DIR, fname)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
    return jsonify({"ok": True, "msg": "草稿已生成", "draft": text, "path": path})


@app.route("/api/publications")
def api_publications():
    return jsonify({"publications": list(reversed(read_csv(PUBLICATIONS_CSV)))})


@app.route("/api/add_publication", methods=["POST"])
def api_add_publication():
    d = request.get_json(force=True)
    pid = next_id(PUBLICATIONS_CSV, "P", "pub_id")
    row = [pid, d.get("date", datetime.now().strftime("%Y-%m-%d")), d.get("query_id", ""),
           d.get("title", ""), d.get("platform", "zhihu"), d.get("url", ""),
           d.get("status", "published"), d.get("version", "知乎回答版"), d.get("note", "")]
    append_csv(PUBLICATIONS_CSV, row, ["pub_id", "date", "query_id", "title", "platform", "url", "status", "version", "note"])
    return jsonify({"ok": True, "msg": f"已登记发布 {pid}"})


@app.route("/api/review")
def api_review():
    cits = [c for c in read_csv(CITATIONS_CSV) if not c.get("date", "").startswith("说明")]
    pubs = read_csv(PUBLICATIONS_CSV)
    platform_count = Counter(p.get("platform", "") for p in pubs)
    engine_mentions = Counter(c.get("engine", "") for c in cits if c.get("mentioned") == "1")
    missing = Counter()
    for r in read_csv(RANKING_CSV):
        for e in (r.get("missing_engines", "") or "").split("|"):
            if e:
                missing[e] += 1
    top = read_csv(RANKING_CSV)[:5]
    return jsonify({
        "publication_count": len(pubs),
        "citation_count": len(cits),
        "platform_count": platform_count,
        "engine_mentions": engine_mentions,
        "weak_engines": missing.most_common(),
        "next_topics": top,
    })


if __name__ == "__main__":
    ensure_dirs()
    print("=" * 56)
    print("  化妆品工厂 GEO v1.0 看板已启动")
    print("  浏览器打开： http://127.0.0.1:5000")
    print("  关闭看板：在本窗口按 Ctrl+C")
    print("=" * 56)
    app.run(host="127.0.0.1", port=5000, debug=False)
