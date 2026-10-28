#!/usr/bin/env python3
"""fetch_square.py — 抓取 B站 Toy 广场的当下热门，生成对标素材（toy-maker skill）

用法:
    python3 fetch_square.py [--out DIR] [--top N] [--search 关键词 ...] [--sdk-scan K] [--quiet]

默认输出到 ./.toy-maker/：
    showcase.json   结构化数据（本周必玩、今日推荐、各分类热门、上升最快、往期必玩、搜索结果、SDK 使用统计）
    showcase.md     给人和模型读的摘要

数据来源是 Toy 广场网页（https://www.bilibili.com/btoy/square）自己调用的公开只读接口
api.bilibili.com/x/toy/plaza/*，不需要登录、不需要浏览器、零依赖。
接口拿不到时（断网、改版、风控），退回 skill 自带的快照 data/showcase.json，并在输出里标明快照日期；
退出码 3 表示用的是快照。

--sdk-scan K：对最热的 K 个作品抓取公开的 index.html 与同目录 JS，统计用了哪些 Toy SDK 能力、
什么引擎/框架。只读静态文件，逐个请求、有间隔，K 默认 0（不扫）。
"""
from __future__ import annotations

import argparse
import gzip
import json
import os
import re
import shutil
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone, timedelta

API = "https://api.bilibili.com/x/toy"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (toy-maker skill; +https://www.bilibili.com/btoy/square)",
    "Referer": "https://www.bilibili.com/btoy/square",
}
CATEGORIES = {
    "GAME": "游戏", "INTERACTIVE_PLAY": "互动玩法", "TOOL": "工具", "TEST": "测试",
    "GUIDE": "攻略", "COLLECTION": "合集", "OTHER": "其他",
}
CST = timezone(timedelta(hours=8))
SKILL_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SNAPSHOT = os.path.join(SKILL_DIR, "data", "showcase.json")

SDK_METHODS = ("isSupport navigate saveImageToAlbum share getQrCode closeBrowser getUserProfile "
               "getAuthorProfile getAuthorVideos getAuthorRelation getVideoUserActions setCloudStorage "
               "getCloudStorage removeCloudStorage setSharedStorage getSharedStorage removeSharedStorage "
               "submitScore getRankList getMyRank requestCamera requestMicrophone stopMedia "
               "onContainerChange getContainerState setContainerMode checkInputSafety").split()
ENGINES = [
    ("Unity", re.compile(r"UnityLoader|createUnityInstance|\.unityweb|\.framework\.js", re.I)),
    ("Cocos", re.compile(r"cocos2d|cc\.game|CCClass|cocos-js", re.I)),
    ("Godot", re.compile(r"godot\.js|Engine\(\s*GODOT_CONFIG|GODOT_CONFIG")),
    ("TurboWarp/Scratch", re.compile(r"turbowarp|scratch-vm|Scratch\.", re.I)),
    ("Phaser", re.compile(r"Phaser\.(Game|AUTO|Scene)|phaser(\.min)?\.js", re.I)),
    ("Three.js", re.compile(r"THREE\.(WebGLRenderer|Scene)|three(\.module)?(\.min)?\.js|REVISION\s*=\s*\"1\d\d", re.I)),
    ("PixiJS", re.compile(r"PIXI\.|pixi(\.min)?\.js", re.I)),
    ("Vue", re.compile(r"__VUE__|createApp\(|vue(\.runtime)?(\.esm|\.global)?(\.prod)?\.js|data-v-[0-9a-f]{8}")),
    ("React", re.compile(r"react-dom|__REACT_DEVTOOLS|createRoot\(|React\.createElement")),
]


def fetch(url: str, limit: int = 8_000_000, timeout: float = 12) -> bytes:
    req = urllib.request.Request(url, headers={**HEADERS, "Accept-Encoding": "gzip"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        raw = r.read(limit)
    if raw[:2] == b"\x1f\x8b":  # 部分 CDN 无论请求头都回 gzip
        raw = gzip.decompress(raw)
    return raw


def get_json(path: str, timeout: float = 10):
    d = json.loads(fetch(API + path, timeout=timeout))
    if d.get("code") != 0:
        raise RuntimeError(f"{path}: code={d.get('code')} {d.get('message')}")
    return d["data"]


def get_text(url: str, limit: int = 8_000_000, timeout: float = 12) -> str:
    return fetch(url, limit, timeout).decode("utf-8", errors="replace")


def slim(item: dict, now: float) -> dict:
    ctime = item.get("ctime") or 0
    days = max((now - ctime) / 86400, 1) if ctime else None
    plays = item.get("play_count") or 0
    slug = re.sub(r"^.*/toy/([^/]+)/.*$", r"\1", item.get("url", ""))
    return {
        "id": item.get("id"),
        "title": item.get("title"),
        "category": item.get("category"),
        "category_cn": CATEGORIES.get(item.get("category"), item.get("category")),
        "play_count": plays,
        "url": item.get("url"),
        "slug": slug,
        "author": (item.get("user_info") or {}).get("name"),
        "dynamic_url": f"https://www.bilibili.com/opus/{item['dyn_id']}" if item.get("dyn_id") else None,
        "poster_url": item.get("poster_url"),
        "versions": item.get("version"),
        "created": datetime.fromtimestamp(ctime, CST).strftime("%Y-%m-%d") if ctime else None,
        "updated": datetime.fromtimestamp(item["mtime"], CST).strftime("%Y-%m-%d") if item.get("mtime") else None,
        "days_online": round(days) if days else None,
        "plays_per_day": round(plays / days) if days else None,
    }


def collect(top: int, searches: list[str], editions_n: int, log) -> dict:
    now = time.time()
    out: dict = {
        "source": "https://www.bilibili.com/btoy/square",
        "fetched_at": datetime.now(CST).strftime("%Y-%m-%d %H:%M") + " 北京时间",
        "is_snapshot": False,
    }

    w = get_json("/plaza/weekly")
    out["weekly"] = {
        "edition_no": w.get("edition_no"),
        "published": datetime.fromtimestamp(w["published_at"], CST).strftime("%Y-%m-%d") if w.get("published_at") else None,
        "items": [slim(i, now) for i in w.get("items") or []],
    }
    log(f"本周必玩 第{w.get('edition_no')}期：{len(out['weekly']['items'])} 个")

    rec = get_json("/plaza/recommend?page=1&days=7")
    out["recommend"] = {"show_date": rec.get("show_date"), "items": [slim(i, now) for i in rec.get("list") or []]}
    log(f"今日推荐：{len(out['recommend']['items'])} 个")

    out["categories"] = {}
    pool: dict = {}
    for code, cn in CATEGORIES.items():
        try:
            d = get_json(f"/plaza/category?category={code}&pn=1&ps={min(max(top, 1), 50)}")
        except Exception as e:  # 单个分类失败不影响整体
            log(f"分类 {cn} 获取失败：{e}")
            continue
        items = [slim(i, now) for i in d.get("list") or []]
        out["categories"][code] = {"name": cn, "total": d.get("total"), "items": items}
        for it in items:
            pool[it["id"]] = it
        log(f"分类 {cn}：共 {d.get('total')} 个，取前 {len(items)}")
        time.sleep(0.2)

    for it in out["weekly"]["items"] + out["recommend"]["items"]:
        pool.setdefault(it["id"], it)
    rising = [it for it in pool.values() if it["days_online"] and it["days_online"] <= 45]
    rising.sort(key=lambda x: x["plays_per_day"] or 0, reverse=True)
    out["rising"] = rising[:20]

    # 往期本周必玩：哪些作品被反复选中、各类型占比
    history = []
    try:
        eds = get_json(f"/plaza/weekly/editions?pn=1&ps={editions_n}").get("list") or []
        for e in eds:
            try:
                d = get_json(f"/plaza/weekly/edition?edition_no={e['edition_no']}")
                history.append({
                    "edition_no": e["edition_no"],
                    "published": datetime.fromtimestamp(e["published_at"], CST).strftime("%Y-%m-%d"),
                    "items": [{"title": i.get("title"), "category": i.get("category"), "url": i.get("url"),
                               "play_count": i.get("play_count")} for i in d.get("items") or []],
                })
                time.sleep(0.2)
            except Exception as ex:
                log(f"第{e['edition_no']}期获取失败：{ex}")
    except Exception as ex:
        log(f"往期本周必玩获取失败：{ex}")
    out["weekly_history"] = history
    mix: dict = {}
    for ed in history:
        for i in ed["items"]:
            mix[i["category"]] = mix.get(i["category"], 0) + 1
    out["weekly_category_mix"] = dict(sorted(mix.items(), key=lambda x: -x[1]))

    out["searches"] = {}
    for kw in searches:
        try:
            d = get_json(f"/plaza/search?keyword={urllib.parse.quote(kw)}&pn=1&ps=20")
            out["searches"][kw] = [slim(i, now) for i in d.get("list") or []]
            log(f"搜索「{kw}」：{len(out['searches'][kw])} 个")
        except Exception as ex:
            log(f"搜索「{kw}」失败：{ex}")
    return out


def sdk_scan(works: list[dict], log) -> dict:
    """抓公开静态文件，统计 SDK 能力与引擎。只做计数，不保存作品代码。"""
    usage: dict = {m: 0 for m in SDK_METHODS}
    engines: dict = {}
    per = []
    for w in works:
        try:
            # www.bilibili.com/toy/<slug>/ 是平台外壳，作品本体在外壳里的沙箱 iframe（www.bilibilitoy.com）
            shell = get_text(w["url"], 2_000_000)
            m = re.search(r"""<iframe[^>]+src=["']([^"']+)["']""", shell)
            content_url = m.group(1) if m else w["url"]
            html = get_text(content_url, 2_000_000)
        except Exception as ex:
            log(f"扫描跳过 {w['title']}：{ex}")
            continue
        base = content_url.rsplit("/", 1)[0] + "/"
        srcs = re.findall(r"""<script[^>]+src=["']([^"']+)["']""", html, re.I)
        # 平台注入的性能探针里写着 UnityLoader / THREE / PIXI 等检测词，先剔掉，避免引擎误判
        code = re.sub(r"<script>(?:(?!</script>).)*?(__TOY_PERF__|__TOY_META__|__MIRROR_CONFIG__|ReporterPb)(?:(?!</script>).)*</script>",
                      "", html, flags=re.S)
        for s in srcs[:8]:
            if "toy-sdk.js" in s or s.startswith(("http://", "https://", "//")) and "bilibilitoy.com/toy/" not in s:
                continue
            try:
                code += "\n" + get_text(urllib.parse.urljoin(base, s), 6_000_000)
            except Exception:
                pass
            time.sleep(0.15)
        has_sdk = "toy-sdk.js" in html
        used = [m for m in SDK_METHODS if re.search(r"\.\s*" + m + r"\s*\(", code)] if has_sdk else []
        eng = [name for name, rx in ENGINES if rx.search(code)]
        for m in used:
            usage[m] += 1
        for e in eng:
            engines[e] = engines.get(e, 0) + 1
        per.append({"title": w["title"], "category": w["category"], "url": w["url"], "has_sdk": has_sdk,
                    "sdk_methods": used, "engines": eng, "entry_html_kb": round(len(html.encode()) / 1024)})
        time.sleep(0.3)
    n = len(per)
    return {
        "scanned": n,
        "with_sdk": sum(p["has_sdk"] for p in per),
        "method_usage": {k: v for k, v in sorted(usage.items(), key=lambda x: -x[1]) if v},
        "engines": dict(sorted(engines.items(), key=lambda x: -x[1])),
        "works": per,
        "note": "静态匹配：压缩/混淆代码或运行时动态加载的脚本可能漏检，只作趋势参考",
    }


def add_details(works: list[dict], log) -> int:
    """补作品发布动态的简介与点赞/评论/转发（公开接口，失败就跳过）。原地写回 works。"""
    ok = 0
    for w in works:
        dyn = (w.get("dynamic_url") or "").rsplit("/", 1)[-1]
        if not dyn or "likes" in w:
            continue
        try:
            raw = fetch(f"https://api.bilibili.com/x/polymer/web-dynamic/v1/detail?id={dyn}&features=itemOpusStyle")
            d = json.loads(raw)
            if d.get("code") == -352:  # 风控：匿名请求被限，后面的也会失败，直接停
                log("动态详情接口触发风控（-352），跳过剩余详情")
                break
            if d.get("code") != 0:
                raise RuntimeError(d.get("message"))
            m = d["data"]["item"]["modules"]
            st = m.get("module_stat") or {}
            major = ((m.get("module_dynamic") or {}).get("major") or {}).get("opus") or {}
            text = ((major.get("summary") or {}).get("text") or "")
            text = re.sub(r"https?://\S+", "", text).strip()
            w["summary"] = text[:200]
            w["likes"] = (st.get("like") or {}).get("count")
            w["comments"] = (st.get("comment") or {}).get("count")
            w["forwards"] = (st.get("forward") or {}).get("count")
            plays = w.get("play_count") or 0
            w["comments_per_10k_plays"] = round(w["comments"] * 10000 / plays, 1) if plays and w["comments"] is not None else None
            ok += 1
        except Exception as ex:
            log(f"详情跳过 {w['title']}：{ex}")
        time.sleep(0.3)
    return ok


def fmt_n(n) -> str:
    if n is None:
        return "-"
    return f"{n/10000:.1f}万" if n >= 10000 else str(n)


def line(it: dict) -> str:
    extra = f"上线{it['days_online']}天，日均{fmt_n(it['plays_per_day'])}" if it.get("days_online") else ""
    eng = (f"｜赞{fmt_n(it['likes'])} 评{fmt_n(it['comments'])}" if it.get("likes") is not None else "")
    desc = f"\n  简介：{it['summary'][:80]}" if it.get("summary") and it["summary"] != it["title"] else ""
    return (f"- [{it['title']}]({it['url']})｜{it['category_cn']}｜{fmt_n(it['play_count'])}次游玩"
            f"｜{extra}{eng}｜作者 {it['author']}｜更新{it['versions']}版{desc}")


def render_md(d: dict) -> str:
    L = [f"# Toy 广场对标素材（{d['fetched_at']} 抓取）", ""]
    if d.get("is_snapshot"):
        L += [f"> ⚠️ 实时抓取失败，以下是 skill 内置快照（{d['fetched_at']}），时效性有限。", ""]
    L += ["来源：" + d["source"] + "。游玩数为广场公开计数；**热度 ≠ 值得模仿**——先过合规（见 platform-rules.md），"
          "不少高游玩作品踩在灰线上（如领福利/互助类工具），不要照搬。", ""]
    wk = d.get("weekly") or {}
    L += [f"## 本周必玩（第{wk.get('edition_no')}期，{wk.get('published')}）", "运营每周一晚从「娱乐」「工具」两条赛道精选，最能代表平台想推的方向。", ""]
    L += [line(i) for i in wk.get("items", [])] + [""]
    if d.get("weekly_category_mix"):
        mix = "、".join(f"{CATEGORIES.get(k, k)} {v}" for k, v in d["weekly_category_mix"].items())
        L += [f"往期 {len(d.get('weekly_history', []))} 期必玩的类型分布：{mix}", ""]
    if d.get("rising"):
        L += ["## 上升最快（上线 ≤45 天，按日均游玩排序）", "比总榜更能反映「现在什么在火」。", ""]
        L += [line(i) for i in d["rising"][:15]] + [""]
    rec = d.get("recommend") or {}
    if rec.get("items"):
        L += [f"## 今日推荐（{rec.get('show_date')}，系统按游玩量自动产生）", ""]
        L += [line(i) for i in rec["items"][:12]] + [""]
    L += ["## 各类型总榜 Top 8", ""]
    for code, c in (d.get("categories") or {}).items():
        L += [f"### {c['name']}（共 {c.get('total')} 个）", ""] + [line(i) for i in c["items"][:8]] + [""]
    for kw, items in (d.get("searches") or {}).items():
        L += [f"## 搜索「{kw}」：同题材已有作品", ""] + ([line(i) for i in items[:12]] or ["- 没有搜到，题材较新"]) + [""]
    sc = d.get("sdk_scan")
    if sc and sc.get("scanned"):
        L += [f"## 热门作品 SDK / 技术栈统计（扫描 {sc['scanned']} 个）", "",
              f"- 引入 Toy SDK：{sc['with_sdk']}/{sc['scanned']}",
              "- SDK 能力使用次数：" + ("、".join(f"{k} {v}" for k, v in sc["method_usage"].items()) or "无"),
              "- 引擎/框架：" + ("、".join(f"{k} {v}" for k, v in sc["engines"].items()) or "未识别（多为原生 JS/Canvas）"),
              f"- {sc['note']}", ""]
    return "\n".join(L)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", default=".toy-maker", help="输出目录（默认 ./.toy-maker）")
    ap.add_argument("--top", type=int, default=20, help="每个分类取前 N（≤50）")
    ap.add_argument("--search", nargs="*", default=[], help="按关键词搜同题材作品，可多个")
    ap.add_argument("--editions", type=int, default=12, help="往期本周必玩取最近几期")
    ap.add_argument("--sdk-scan", type=int, default=0, help="扫描最热 K 个作品的 SDK 用法")
    ap.add_argument("--details", type=int, default=0, help="为最相关的 K 个作品补简介与赞/评/转（匿名访问易被风控，尽力而为）")
    ap.add_argument("--quiet", action="store_true")
    a = ap.parse_args(argv)
    log = (lambda *_: None) if a.quiet else (lambda m: print(m, file=sys.stderr))
    os.makedirs(a.out, exist_ok=True)
    jpath, mpath = os.path.join(a.out, "showcase.json"), os.path.join(a.out, "showcase.md")

    try:
        data = collect(a.top, a.search, a.editions, log)
        if a.sdk_scan:
            seen, targets = set(), []
            pools = [data["weekly"]["items"], data["rising"]] + [c["items"] for c in data["categories"].values()]
            ranked = sorted({i["id"]: i for p in pools for i in p}.values(), key=lambda x: -x["play_count"])
            for it in data["weekly"]["items"] + data["rising"][:10] + ranked:
                if it["id"] not in seen and len(targets) < a.sdk_scan:
                    seen.add(it["id"]); targets.append(it)
            data["sdk_scan"] = sdk_scan(targets, log)
        if a.details:
            lists = ([data["weekly"]["items"], data["rising"][:10]] + list(data["searches"].values())
                     + [c["items"][:5] for c in data["categories"].values()] + [data["recommend"]["items"]])
            reps: dict = {}
            for lst in lists:
                for it in lst:
                    if it["id"] not in reps and len(reps) < a.details:
                        reps[it["id"]] = it
            n = add_details(list(reps.values()), log)
            keys = ("summary", "likes", "comments", "forwards", "comments_per_10k_plays")
            for lst in [data["weekly"]["items"], data["rising"], data["recommend"]["items"]] + \
                    list(data["searches"].values()) + [c["items"] for c in data["categories"].values()]:
                for it in lst:
                    src = reps.get(it["id"])
                    if src is not None and src is not it:
                        it.update({k: src[k] for k in keys if k in src})
            log(f"作品详情：{n}/{len(reps)}")
        code = 0
    except Exception as ex:
        log(f"实时抓取失败：{ex}")
        if not os.path.exists(SNAPSHOT):
            print("实时抓取失败，且没有内置快照。可以用任意浏览器打开 https://www.bilibili.com/btoy/square 人工查看，或跳过对标这一步。",
                  file=sys.stderr)
            return 2
        with open(SNAPSHOT, encoding="utf-8") as f:
            data = json.load(f)
        data["is_snapshot"] = True
        log(f"已退回内置快照（{data.get('fetched_at')}）")
        code = 3

    if not (code == 3 and os.path.abspath(jpath) == os.path.abspath(SNAPSHOT)):
        with open(jpath, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=1)
    with open(mpath, "w", encoding="utf-8") as f:
        f.write(render_md(data))
    print(f"{'快照' if code == 3 else '已抓取'}：{jpath}\n摘要：{mpath}")
    return code


if __name__ == "__main__":
    sys.exit(main())
