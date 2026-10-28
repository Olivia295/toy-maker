#!/usr/bin/env python3
"""toy_maker_check.py — B站 Toy 构建产物的 SDK 接入与合规静态自查（toy-maker skill）

用法:
    python3 toy_maker_check.py <dist目录 | xxx.zip | index.html> [--json]

与官方 toy skill 的 toy_doctor.py 互补：这里重点查 SDK 用法与合规风险，
资源绝对路径 / hash 路由 / 封面 / contenthash / HTML 体积形态请交给 toy_doctor.py。

级别：ERROR = 发不出去或几乎必然出问题；WARN = 需要人看一眼（静态匹配，压缩产物里可能误判）。
退出码：有 ERROR 为 1，否则 0。零依赖。
"""
from __future__ import annotations

import json
import os
import re
import sys
import zipfile
from dataclasses import dataclass, field

ENTRY_LIMIT = 1024 * 1024
TEXT_EXT = {".html", ".htm", ".js", ".mjs", ".css", ".json"}
SKIP_PARTS = {"node_modules", ".git", "__MACOSX"}
# 发布页 FAQ 公布的后缀白名单（2026-10），其余文件发布时会被过滤
WHITELIST_EXT = {".html", ".htm", ".css", ".js", ".json", ".wasm", ".data", ".md", ".csv", ".tsv",
                 ".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp", ".ico", ".woff2", ".woff", ".ttf", ".eot",
                 ".mp3", ".wav", ".ogg", ".m4a", ".mp4", ".webm", ".atlas", ".ani", ".part", ".nani", ".unityweb"}
IGNORED_NAMES = {".DS_Store", "Thumbs.db", "toy.yaml"}
ANALYTICS = re.compile(r"googletagmanager|google-analytics\.com|gtag\(|hm\.baidu\.com|_hmt\.push|cnzz\.com|umeng|"
                       r"sensorsdata|51\.la|clarity\.ms|plausible\.io|umami", re.I)
SDK_SRC = "s1.hdslb.com/bfs/seed/toy/app/sdk/toy-sdk.js"
SDK_METHODS = ("isSupport navigate saveImageToAlbum share getQrCode closeBrowser getUserProfile "
               "getAuthorProfile getAuthorVideos getAuthorRelation getVideoUserActions setCloudStorage "
               "getCloudStorage removeCloudStorage setSharedStorage getSharedStorage removeSharedStorage "
               "submitScore getRankList getMyRank requestCamera requestMicrophone stopMedia "
               "onContainerChange getContainerState setContainerMode checkInputSafety").split()
APP_ONLY = ["saveImageToAlbum", "share", "closeBrowser", "onContainerChange", "getContainerState", "setContainerMode"]
RATE_LIMITED = ["getCloudStorage", "setCloudStorage", "removeCloudStorage", "getSharedStorage",
                "setSharedStorage", "submitScore", "getRankList", "getMyRank"]

THIRD_PARTY_LOGIN = re.compile(
    r"graph\.qq\.com|connect\.qq\.com|open\.weixin\.qq\.com|api\.weibo\.com/oauth|taptap\.(?:com|cn)|"
    r"accounts\.google\.com|appleid\.apple\.com|openauth\.alipay|github\.com/login/oauth", re.I)
PAYMENT = re.compile(r"afdian\.(?:net|com)|ifdian\.net|wxp://|qr\.alipay\.com|ko-fi\.com|patreon\.com|"
                     r"paypal\.(?:com|me)|buymeacoffee\.com", re.I)
ADS = re.compile(r"googlesyndication|doubleclick\.net|adsbygoogle|pangle|pglstatp|bytedance.*\bad\b|"
                 r"gdt\.qq\.com|qzs\.qq\.com/union|unityads|applovin|admob", re.I)
B23 = re.compile(r"\bb23\.tv/", re.I)
STORE_ALLOWED_HOSTS = re.compile(r"(?:^|\.)(?:bilibili\.com|biligame\.com|hdslb\.com|bilivideo\.com|"
                                 r"biliapi\.net|w3\.org|schema\.org|example\.com)$", re.I)
EXT_LINK = re.compile(r"""(?:href\s*=\s*["']|window\.open\(\s*["']|location(?:\.href)?\s*=\s*["'])(https?:)?//([^/"'\s?#]+)""", re.I)
IFRAME_SRC = re.compile(r"""<iframe[^>]*\ssrc\s*=\s*["']([^"']+)["']""", re.I)
INPUT_TAG = re.compile(r"<(?:textarea)\b|<input\b(?![^>]*type\s*=\s*[\"']?(?:button|submit|checkbox|radio|range|hidden|file|color|reset|image)\b)", re.I)
FILE_INPUT = re.compile(r"""<input[^>]*type\s*=\s*["']?file""", re.I)
LOCALSTORAGE = re.compile(r"\blocalStorage\.setItem\b|\blocalStorage\[")
INTERVAL_CALL = re.compile(r"setInterval\s*\([^;]{0,400}?\b(" + "|".join(RATE_LIMITED) + r")\b", re.S)
LOOP_CALL = re.compile(r"\b(?:for|while)\s*\([^)]{0,200}\)\s*\{?[^{}]{0,300}?\b(" + "|".join(RATE_LIMITED) + r")\b", re.S)
UNITY_COMPRESSED = re.compile(r"\.(?:data|wasm|framework\.js)\.(?:gz|br)$|\.unityweb$", re.I)


@dataclass
class Report:
    errors: list = field(default_factory=list)
    warns: list = field(default_factory=list)
    infos: list = field(default_factory=list)

    def error(self, msg): self.errors.append(msg)
    def warn(self, msg): self.warns.append(msg)
    def info(self, msg): self.infos.append(msg)


def load(path: str) -> dict[str, bytes]:
    files: dict[str, bytes] = {}
    if os.path.isdir(path):
        for root, dirs, names in os.walk(path):
            dirs[:] = [d for d in dirs if d not in SKIP_PARTS]
            for n in names:
                full = os.path.join(root, n)
                rel = os.path.relpath(full, path).replace(os.sep, "/")
                with open(full, "rb") as f:
                    files[rel] = f.read()
    elif path.lower().endswith(".zip"):
        with zipfile.ZipFile(path) as z:
            for info in z.infolist():
                if info.is_dir() or any(p in SKIP_PARTS for p in info.filename.split("/")):
                    continue
                files[info.filename] = z.read(info)
    else:
        with open(path, "rb") as f:
            files["index.html"] = f.read()
    return files


def find_entry(files: dict[str, bytes]) -> str | None:
    if "index.html" in files:
        return "index.html"
    tops = [p for p in files if p.count("/") == 1 and p.endswith("/index.html")]
    return tops[0] if len(tops) == 1 else None


def has_call(text: str, method: str) -> bool:
    return re.search(r"\.\s*" + method + r"\s*\(", text) is not None


def check(path: str) -> Report:
    r = Report()
    files = load(path)
    if not files:
        r.error("包是空的")
        return r

    # --- 包结构 ---
    entry = find_entry(files)
    if not entry:
        r.error("找不到入口 index.html：需要在 zip 根目录，或恰好一个一级子目录里")
    else:
        size = len(files[entry])
        if size > ENTRY_LIMIT:
            r.error(f"入口 {entry} 解压后 {size/1024/1024:.2f}MB，超过 1MB 硬上限（create/update/preview 都会报 307000）。"
                    "把内联脚本/样式/base64 图/大 JSON 拆成独立文件；别用单文件打包器产出入口")
        elif size > ENTRY_LIMIT * 0.8:
            r.warn(f"入口 {entry} 已有 {size/1024:.0f}KB，接近 1MB 上限")

    texts: dict[str, str] = {}
    for p, b in files.items():
        ext = os.path.splitext(p)[1].lower()
        if ext not in WHITELIST_EXT and os.path.basename(p) not in IGNORED_NAMES and not ext == ".map":
            r.warn(f"{p}: 后缀 {ext or '（无）'} 不在平台白名单里，发布时会被过滤；页面若依赖它（如 .glb/.bin/.txt），换成白名单格式（如 .json/.data）或改名")
        if ext == ".mp4":
            r.warn(f"{p}: 包含 .mp4（Unity 项目带视频常导致黑屏；视频过大也占包体），考虑改 CDN 加载或移除")
        if UNITY_COMPRESSED.search(p):
            r.warn(f"{p}: Unity 压缩构建产物，官方 FAQ 指出开启压缩是黑屏常见原因，建议构建时关闭压缩")
        if ext in TEXT_EXT:
            texts[p] = b.decode("utf-8", errors="replace")
    if any(os.path.basename(p) in ("package.json", "tsconfig.json") for p in files) or any(p.startswith("src/") for p in files):
        r.warn("包里有 package.json / tsconfig.json / src/，像是传了源码；只传构建产物（dist）")
    total = sum(len(b) for b in files.values())
    if total > 50 * 1024 * 1024:
        r.warn(f"整包 {total/1024/1024:.1f}MB，超过默认 50MB 上限（可在创作者设置申请更大）")

    html = {p: t for p, t in texts.items() if p.lower().endswith((".html", ".htm"))}
    code = "\n".join(texts.values())

    # --- SDK 接入 ---
    used = [m for m in SDK_METHODS if re.search(r"\btoy\s*\.\s*" + m + r"\s*\(", code) or
            re.search(r"\b(?:window\.toy|toy\(\))\s*\.\s*" + m + r"\b", code)]
    uses_sdk = bool(used) or "window.toy" in code
    sdk_tag = any(SDK_SRC in t for t in html.values())
    if uses_sdk and not sdk_tag:
        r.error("代码里调用了 Toy SDK，但没有任何 HTML 引入 " + SDK_SRC +
                "；在入口 <head> 加 <script src=\"//" + SDK_SRC + "\"></script>")
    if sdk_tag:
        r.info("已引入 Toy SDK" + (f"，检测到调用：{', '.join(used)}" if used else "（未检测到具体调用，压缩产物可能匹配不到）"))
    if entry and sdk_tag and SDK_SRC not in texts.get(entry, ""):
        r.warn("SDK 没有在入口 index.html 里引入，确认每个用到 window.toy 的页面都引入了")

    app_only_used = [m for m in APP_ONLY if has_call(code, m)]
    if app_only_used and not re.search(r"isSupport\s*\(", code):
        r.warn(f"用了仅 B站 App 内可用的能力 {app_only_used}，但没看到 isSupport 判断；Web 端会抛 unsupported，需要降级方案")
    if has_call(code, "setContainerMode") and not has_call(code, "onContainerChange"):
        r.warn("调用 setContainerMode 但没有 onContainerChange：Promise 返回不代表切换生效，应先监听再切换并以状态为准")
    if (has_call(code, "requestCamera") or has_call(code, "requestMicrophone")) and not has_call(code, "stopMedia"):
        r.warn("申请了摄像头/麦克风但没看到 stopMedia：用完必须释放设备")
    for m in INTERVAL_CALL.finditer(code):
        r.warn(f"setInterval 附近调用了 {m.group(1)}：疑似轮询云存储/排行榜（全体玩家共享额度，易触发 307044）")
        break
    for m in LOOP_CALL.finditer(code):
        r.warn(f"循环体内调用了 {m.group(1)}：应改成一次批量调用")
        break
    if any(has_call(code, m) for m in RATE_LIMITED) and "307044" not in code:
        r.warn("用了云存储/排行榜，但没看到对 307044（限流）的处理：catch 后应指数退避并提示玩家")
    if "toyOpenId" in code and re.search(r"(gtag|_hmt|sensors|umeng|track|analytics)\s*[\.(]", code, re.I):
        r.warn("代码里同时出现 toyOpenId 和埋点调用：toyOpenId 不得写入埋点或公开日志，请人工确认")
    if LOCALSTORAGE.search(code) and not any(has_call(code, m) for m in ("setCloudStorage", "setSharedStorage")):
        r.warn("只用 localStorage 存数据：会被清缓存丢失；重要进度建议用云存档（setCloudStorage）")

    # --- 合规 ---
    ext_scripts = sorted({m.group(1) for t in html.values() for m in re.finditer(r"""<script[^>]+src=["']((?:https?:)?//[^"']+)["']""", t, re.I)
                          if "hdslb.com/bfs/seed/toy/app/sdk/" not in m.group(1)})
    if ext_scripts:
        r.warn(f"从外部地址加载脚本 {ext_scripts[:3]}：使用协议禁止用远程脚本/动态加载规避审核、未经同意接入第三方 SDK——把依赖打包进项目")
    for p, t in texts.items():
        if ANALYTICS.search(t):
            r.warn(f"{p}: 疑似统计/埋点代码（{ANALYTICS.search(t).group(0)}）——使用协议 2.5 未经书面同意不得嵌入统计代码")
        if THIRD_PARTY_LOGIN.search(t):
            r.warn(f"{p}: 疑似第三方登录（{THIRD_PARTY_LOGIN.search(t).group(0)}）——Toy 禁止第三方平台登录/跳转")
        if PAYMENT.search(t):
            r.warn(f"{p}: 疑似站外收款/赞助链接（{PAYMENT.search(t).group(0)}）——禁止，引导充电请跳作者 B站主页")
        if ADS.search(t):
            r.warn(f"{p}: 疑似广告 SDK（{ADS.search(t).group(0)}）——Toy 不得放广告/接广告联盟")
        if B23.search(t):
            r.warn(f"{p}: 使用了 b23.tv 短链——约一年后失效，会导致功能失效")
        hosts = sorted({m.group(2).lower() for m in EXT_LINK.finditer(t)
                        if not STORE_ALLOWED_HOSTS.search(m.group(2).split(":")[0])})
        if hosts:
            r.warn(f"{p}: 有跳转到站外域名的链接/跳转 {hosts[:5]}——Toy 不得跳站外，站内跳转用 toy.navigate")

    for p, t in html.items():
        for m in IFRAME_SRC.finditer(t):
            src = m.group(1)
            if re.match(r"^(https?:)?//", src) and "player.bilibili.com" not in src:
                r.warn(f"{p}: iframe 嵌入外部页面 {src[:80]}——Toy 不能通过 iframe 外链网页（B站播放器 player.bilibili.com 除外）")
        if FILE_INPUT.search(t):
            r.warn(f"{p}: 有文件上传 <input type=file>——用户上传图片等属于 UGC 红线，确认仅本地使用、不对他人展示")
    if any(INPUT_TAG.search(t) for t in html.values()) or re.search(r"createElement\(\s*[\"'](?:input|textarea)[\"']", code):
        if not has_call(code, "checkInputSafety"):
            r.warn("页面有文本输入框但没看到 checkInputSafety：若内容会被其他玩家看到（昵称/留言），提交时必须检测；"
                   "昵称不允许用户自建，用 getUserProfile 或系统随机/预置候选")
    if re.search(r"contenteditable|<canvas", code, re.I) and re.search(r"pointermove|touchmove|mousemove", code) \
            and re.search(r"toDataURL|toBlob", code):
        r.info("像是有自由绘制并导出图片的功能：含自由绘制的 Toy 发布时需开启 --watermark，且绘制内容不要公开给他人")
    return r


def main(argv: list[str]) -> int:
    args = [a for a in argv if not a.startswith("--")]
    as_json = "--json" in argv
    if len(args) != 1:
        print(__doc__)
        return 2
    path = args[0]
    if not os.path.exists(path):
        print(f"路径不存在: {path}", file=sys.stderr)
        return 2
    r = check(path)
    if as_json:
        print(json.dumps({"ok": not r.errors, "errors": r.errors, "warnings": r.warns, "info": r.infos},
                         ensure_ascii=False, indent=2))
    else:
        for m in r.errors:
            print(f"ERROR  {m}")
        for m in r.warns:
            print(f"WARN   {m}")
        for m in r.infos:
            print(f"INFO   {m}")
        status = "FAILED" if r.errors else "OK"
        print(f"{status}: {len(r.errors)} error(s), {len(r.warns)} warning(s)")
    return 1 if r.errors else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
