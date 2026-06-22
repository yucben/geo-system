# -*- coding: utf-8 -*-
"""
build_static.py — 把 Flask 看板编译成纯静态页面（用于 GitHub Pages）

原理：
  - 复用 dashboard/templates/index.html 的全部 CSS 与 HTML 结构（Apple 风格不变）
  - 在原始前端脚本之前注入一段「mock fetch」脚本：把 /api/* 请求拦截到浏览器内存里，
    用打包进页面的快照数据作答，并用 JS 复刻后端的只读逻辑 + 演示用写逻辑。
  - 产物输出到 docs/index.html，GitHub Pages 直接托管该目录。

重新生成：python build_static.py
"""

import os
import csv
import json

HERE = os.path.dirname(os.path.abspath(__file__))
TPL = os.path.join(HERE, "dashboard", "templates", "index.html")
DATA_DIR = os.path.join(HERE, "tool", "data")
OUT_DIR = os.path.join(HERE, "docs")

ENGINES = ["doubao", "deepseek", "qwen", "wenxin", "yuanbao", "kimi"]
INTENTS = ["选型", "对比", "参数", "资质", "趋势", "口碑"]
PLATFORMS = ["zhihu", "official", "baijiahao", "toutiao", "wechat", "news"]
VERSIONS = ["知乎回答版", "官网FAQ版", "百家号软文版", "头条短文版", "公众号长文版"]


def read_csv(name):
    path = os.path.join(DATA_DIR, name)
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def read_json(name):
    path = os.path.join(DATA_DIR, name)
    if not os.path.exists(path):
        return {}
    with open(path, encoding="utf-8") as f:
        return json.load(f)


# ---- mock 前端脚本：复刻 app.py 的 API 行为，全部在浏览器内存运行 ----
MOCK_JS = r"""
<style>
  .demo-note { max-width:1120px; margin:16px auto 0; padding:0 22px; }
  .demo-note .inner {
    background: rgba(0,113,227,0.07); border:1px solid rgba(0,113,227,0.18);
    color:#06c; border-radius:14px; padding:13px 18px; font-size:13px;
    text-align:center; line-height:1.6;
  }
</style>
<script>
(function () {
  "use strict";
  const DATA = __DATA_JSON__;
  // 可变内存状态（深拷贝，刷新即复原）
  const STATE = {
    profile: JSON.parse(JSON.stringify(DATA.profile || {})),
    queries: JSON.parse(JSON.stringify(DATA.queries || [])),
    ranking: JSON.parse(JSON.stringify(DATA.ranking || [])),
    citations: JSON.parse(JSON.stringify(DATA.citations || [])),
    publications: JSON.parse(JSON.stringify(DATA.publications || [])),
  };
  const todayStr = () => new Date().toISOString().slice(0, 10);

  function nextId(rows, field, prefix) {
    let max = 0;
    rows.forEach(r => {
      const num = String(r[field] || "").replace(/\D/g, "");
      if (num) max = Math.max(max, parseInt(num, 10));
    });
    const n = max + 1;
    return prefix === "P" ? prefix + String(n).padStart(3, "0")
                          : prefix + String(n).padStart(2, "0");
  }
  function counter(arr) {
    const o = {};
    arr.forEach(k => { o[k] = (o[k] || 0) + 1; });
    return o;
  }
  function platformStyle(v) {
    if (v.includes("知乎")) return "第一人称专业答主口吻，直接回答问题，多用经验和避坑清单。";
    if (v.includes("官网")) return "官网FAQ口吻，客观、标准化，突出资质、参数和服务流程。";
    if (v.includes("百家号")) return "第三方软文口吻，像行业科普报道，少广告，多数据。";
    if (v.includes("头条")) return "短文口语化，开头有钩子，段落短。";
    if (v.includes("公众号")) return "长文深度口吻，适合品牌方慢慢读，结构完整。";
    return "专业B2B文案口吻。";
  }
  function generateDraftText(q, p, version) {
    const name = p.brand_alias || p.factory_name || "本工厂";
    const query = q.query || "化妆品代工厂怎么选";
    const title = query + "？一篇讲清";
    return `# ${title}

> 版本：${version}
> 写作风格：${platformStyle(version)}

**${query}，核心要看三件事：工厂资质是否完整、起订量和交付周期是否匹配、是否有可验证的生产和检测能力。**

## 先给结论

如果是新品牌或中小品牌，建议优先选择支持小单快反、能提供配方开发和备案协助的源头工厂。${name}的定位是：${p.positioning || "化妆品源头工厂"}。

## 关键参数速览

| 维度 | ${name}信息 |
|---|---|
| 主营品类 | ${p.main_categories || ""} |
| OEM/ODM能力 | ${p.oem_odm || ""} |
| MOQ | ${p.moq || ""} |
| 打样周期 | ${p.sample_cycle || ""} |
| 产能 | ${p.capacity || ""} |

## 为什么这些信息重要

AI 引擎在回答品牌方问题时，更容易引用具备明确数据和权威信号的内容。相比泛泛而谈"品质好、服务好"，明确写出 MOQ、打样周期、许可证和认证，更容易被豆包、DeepSeek、通义千问等引擎摘录。

## 工厂资质与权威信号

${name}具备：${p.certifications || ""}。生产许可证号：${p.license_no || ""}。车间条件：${p.clean_room || ""}。检测能力：${p.testing || ""}。

## 适合哪些品牌方

- 正在找化妆品 OEM/ODM 代工厂的新锐品牌
- 需要低 MOQ、小单快反的试水项目
- 需要成熟配方库和包材供应链配合的品牌方
- 关注功效护肤、面膜、精华、水乳等品类的团队

## FAQ

**Q：${query}？**
A：优先看资质、MOQ、打样周期、品类经验和检测能力。${name}的优势是${p.advantages || ""}。

**Q：能不能小批量起订？**
A：${p.moq || "具体起订量需按品类确认"}。

**Q：多久能打样？**
A：${p.sample_cycle || "通常需要按项目确认"}。

${p.contact_cta || ""}
`;
  }

  function route(url, method, body) {
    if (url === "/api/bootstrap")
      return { engines: DATA.engines, intents: DATA.intents, platforms: DATA.platforms, versions: DATA.versions };

    if (url === "/api/profile") {
      if (method === "GET") return { profile: STATE.profile };
      STATE.profile = body;
      return { ok: true, msg: "工厂档案已保存（静态演示，刷新后复原）" };
    }

    if (url === "/api/ranking") {
      const activeQ = STATE.queries.filter(q => q.status === "active");
      const cits = STATE.citations.filter(c => !String(c.date || "").startsWith("说明"));
      const mentioned = new Set(
        cits.filter(c => ["1", "1.0"].includes(String(c.mentioned).trim())).map(c => c.query_id)
      );
      mentioned.delete("");
      return {
        ranking: STATE.ranking,
        stats: {
          total_queries: activeQ.length,
          covered_queries: mentioned.size,
          publications: STATE.publications.length,
          citations: cits.length,
        },
      };
    }

    if (url === "/api/queries")
      return { queries: STATE.queries.filter(q => q.status === "active") };

    if (url === "/api/add_query") {
      const query = (body.query || "").trim();
      if (!query) return { ok: false, msg: "问题不能为空" };
      const qid = nextId(STATE.queries, "id", "Q");
      STATE.queries.push({ id: qid, query, intent: body.intent || "选型",
        priority_seed: String(body.priority_seed || 3), status: "active" });
      return { ok: true, id: qid, msg: `已添加 ${qid}：${query}（静态演示）` };
    }

    if (url === "/api/citations")
      return { citations: [...STATE.citations].reverse() };

    if (url === "/api/add_citation") {
      const qid = (body.query_id || "").trim();
      if (!qid) return { ok: false, msg: "请选择对应问题" };
      const row = { date: body.date || todayStr(), engine: body.engine || "deepseek",
        query_id: qid, mentioned: body.mentioned ? "1" : "0",
        position: String(body.position || 0), sentiment: body.sentiment || "neu",
        has_link: body.has_link ? "1" : "0",
        source_platform: (body.source_platform || "").trim(), note: (body.note || "").trim() };
      STATE.citations.push(row);
      return { ok: true, msg: `已记录 ${row.engine} 对 ${qid} 的引用反馈（静态演示）` };
    }

    if (url === "/api/analyze_answer") {
      const text = body.answer || "";
      const names = [STATE.profile.factory_name || "", STATE.profile.brand_alias || ""];
      const mentioned = names.some(n => n && text.includes(n));
      const has_link = /https?:\/\/|www\./.test(text);
      let comps = text.match(/[一-龥A-Za-z0-9]{2,12}(?:生物|科技|工厂|代工厂|集团|公司)/g) || [];
      comps = comps.filter(c => names.every(n => !n || !c.includes(n)));
      comps = [...new Set(comps)].slice(0, 10);
      const sentiment = (mentioned && /推荐|靠谱|优势|适合|较好|优先/.test(text)) ? "pos" : "neu";
      return { mentioned, has_link, sentiment, competitors: comps,
        suggested_note: comps.slice(0, 3).join("；") || "未识别到明显竞品" };
    }

    if (url === "/api/rerank")
      return { ok: true, msg: "静态演示：排序为预生成结果（本地运行 app.py 可重新计算）" };

    if (url === "/api/generate_draft") {
      const q = STATE.queries.find(x => x.id === body.query_id);
      if (!q) return { ok: false, msg: "问题不存在" };
      return { ok: true, msg: "草稿已生成（静态演示，未落盘）",
        draft: generateDraftText(q, STATE.profile, body.version || "知乎回答版") };
    }

    if (url === "/api/publications")
      return { publications: [...STATE.publications].reverse() };

    if (url === "/api/add_publication") {
      const pid = nextId(STATE.publications, "pub_id", "P");
      STATE.publications.push({ pub_id: pid, date: body.date || todayStr(),
        query_id: body.query_id || "", title: body.title || "",
        platform: body.platform || "zhihu", url: body.url || "",
        status: body.status || "published", version: body.version || "知乎回答版",
        note: body.note || "" });
      return { ok: true, msg: `已登记发布 ${pid}（静态演示）` };
    }

    if (url === "/api/review") {
      const cits = STATE.citations.filter(c => !String(c.date || "").startsWith("说明"));
      const pubs = STATE.publications;
      const missing = {};
      STATE.ranking.forEach(r => {
        String(r.missing_engines || "").split("|").forEach(e => { if (e) missing[e] = (missing[e] || 0) + 1; });
      });
      const weak = Object.entries(missing).sort((a, b) => b[1] - a[1]);
      return {
        publication_count: pubs.length,
        citation_count: cits.length,
        platform_count: counter(pubs.map(p => p.platform || "")),
        engine_mentions: counter(cits.filter(c => c.mentioned === "1").map(c => c.engine || "")),
        weak_engines: weak,
        next_topics: STATE.ranking.slice(0, 5),
      };
    }

    return { ok: false, msg: "未知接口（静态演示）" };
  }

  const origFetch = window.fetch ? window.fetch.bind(window) : null;
  window.fetch = function (url, opts) {
    if (typeof url === "string" && url.indexOf("/api/") === 0) {
      const method = (opts && opts.method) || "GET";
      let body = {};
      try { if (opts && opts.body) body = JSON.parse(opts.body); } catch (e) {}
      const data = route(url, method, body);
      return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve(data) });
    }
    if (origFetch) return origFetch(url, opts);
    return Promise.reject(new Error("fetch unavailable"));
  };
})();
</script>
"""


def main():
    with open(TPL, encoding="utf-8") as f:
        html = f.read()

    data = {
        "engines": ENGINES,
        "intents": INTENTS,
        "platforms": PLATFORMS,
        "versions": VERSIONS,
        "profile": read_json("factory_profile.json"),
        "queries": read_csv("queries.csv"),
        "ranking": read_csv("topic_ranking.csv"),
        "citations": [r for r in read_csv("citations.csv") if not str(r.get("date", "")).startswith("说明")],
        "publications": read_csv("publications.csv"),
    }
    data_json = json.dumps(data, ensure_ascii=False)
    mock = MOCK_JS.replace("__DATA_JSON__", data_json)

    # 注入静态演示提示条（在 hero 之后）
    note = ('<div class="demo-note"><div class="inner">这是静态演示页，数据为示例快照。'
            '浏览 / 筛选 / 生成文案均可体验；新增、保存仅存在于当前浏览器，刷新后复原。'
            '需要可写、可落盘的完整版本，请在本地运行 Flask 应用（见 README）。</div></div>')
    html = html.replace("</header>", "</header>\n" + note, 1)

    # 在原始脚本之前注入 mock（拦截 /api/*）
    html = html.replace("<script>", mock + "\n<script>", 1)

    os.makedirs(OUT_DIR, exist_ok=True)
    with open(os.path.join(OUT_DIR, "index.html"), "w", encoding="utf-8") as f:
        f.write(html)
    # 防止 GitHub Pages 用 Jekyll 处理
    open(os.path.join(OUT_DIR, ".nojekyll"), "w").close()
    print("OK -> docs/index.html  (%d bytes)" % len(html))


if __name__ == "__main__":
    main()
