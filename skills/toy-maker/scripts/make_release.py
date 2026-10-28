#!/usr/bin/env python3
"""make_release.py — 把构建产物整理成 B站 Toy 发布留档包（toy-maker skill）

用法:
    python3 make_release.py <dist目录> --title 名称 [--slug 地址] [--category GAME|INTERACTIVE_PLAY|TOOL|TEST|GUIDE|COLLECTION|OTHER]
        [--visibility link-only|password|public] [--poster 封面.png] [--icon 图标.png] [--summary 一句话简介]
        [--description 详细介绍.md] [--activity 活动code] [--watermark] [--toy-id 已发布的id]
        [--source 项目源码目录] [--out 输出目录]

产出（默认 ./release/<slug>-<日期>/）：
    1-zip/<slug>.zip          发布方式一：拖拽 ZIP（index.html 在压缩包根目录）
    2-html/index.html         发布方式二：拖拽单个 HTML（只在能安全内联成 ≤1MB 单文件时生成，否则写明原因）
    3-folder/<slug>/          发布方式三：选择文件夹
    cover.* / icon.*          封面、图标（校验格式与尺寸）
    source-<slug>.zip         源码留档（传了 --source 才有；不含 node_modules / dist / .git）
    发布信息.md               表单填写内容、三种网页上传步骤、CLI 命令、自查结果、文件清单
    manifest.json             同上的机器可读版本（含每个文件 sha256）

所有产物只保留平台白名单后缀的文件（与发布页 FAQ 一致），被过滤的文件会列出来。零依赖。
平台协议要求开发者自行留存项目文件与备份，这个目录就是留档。
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import mimetypes
import os
import re
import shutil
import struct
import subprocess
import sys
import zipfile
from datetime import datetime

ENTRY_LIMIT = 1024 * 1024
# 发布页 FAQ「ZIP 包内可以包含哪些类型的文件？」的白名单（2026-10 版）
WHITELIST = {
    ".html", ".htm", ".css", ".js", ".json", ".wasm",
    ".data", ".md", ".csv", ".tsv",
    ".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp", ".ico",
    ".woff2", ".woff", ".ttf", ".eot",
    ".mp3", ".wav", ".ogg", ".m4a",
    ".mp4", ".webm",
    ".atlas", ".ani", ".part", ".nani", ".unityweb",
}
JUNK_DIRS = {"node_modules", ".git", "__MACOSX", ".svn", ".idea", ".vscode", ".toy-maker"}
JUNK_FILES = {".DS_Store", "Thumbs.db", "toy.yaml"}
SOURCE_SKIP = JUNK_DIRS | {"dist", "dist-toy", "build", "release", ".next", ".cache", "coverage"}
CATEGORIES = {"GAME": "游戏", "INTERACTIVE_PLAY": "互动玩法", "TOOL": "工具", "TEST": "测试",
              "GUIDE": "攻略", "COLLECTION": "合集", "OTHER": "其他"}
VIS = {"link-only": "链接访问", "password": "密码访问", "public": "所有人可见"}
BRAND = re.compile(r"哔哩哔哩|bilibili|b站|22娘|33娘|小电视", re.I)
SLUG_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
HERE = os.path.dirname(os.path.abspath(__file__))


def sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def find_root(dist: str) -> str:
    """入口规则：根目录有 index.html，或恰好一个一级子目录里有。"""
    if os.path.isfile(os.path.join(dist, "index.html")):
        return dist
    subs = [d for d in os.listdir(dist) if os.path.isfile(os.path.join(dist, d, "index.html"))]
    if len(subs) == 1:
        return os.path.join(dist, subs[0])
    raise SystemExit(f"错误：{dist} 根目录（或唯一一级子目录）里没有 index.html。框架项目请先构建，传 dist 目录。")


def collect_files(root: str):
    keep, dropped = [], []
    for base, dirs, names in os.walk(root):
        dirs[:] = sorted(d for d in dirs if d not in JUNK_DIRS)
        for n in sorted(names):
            full = os.path.join(base, n)
            rel = os.path.relpath(full, root).replace(os.sep, "/")
            if n in JUNK_FILES:
                continue
            if os.path.splitext(n)[1].lower() in WHITELIST:
                keep.append(rel)
            else:
                dropped.append(rel)
    return keep, dropped


def image_size(path: str):
    with open(path, "rb") as f:
        head = f.read(26)
        if head[:8] == b"\x89PNG\r\n\x1a\n":
            return "png", struct.unpack(">II", head[16:24])
        if head[:2] == b"\xff\xd8":
            f.seek(2)
            while True:
                b = f.read(1)
                while b and b != b"\xff":
                    b = f.read(1)
                while b == b"\xff":
                    b = f.read(1)
                if not b:
                    return "jpeg", None
                if b[0] in (0xC0, 0xC1, 0xC2):
                    f.read(3)
                    h, w = struct.unpack(">HH", f.read(4))
                    return "jpeg", (w, h)
                seg = struct.unpack(">H", f.read(2))[0]
                f.seek(seg - 2, 1)
    return None, None


def try_single_html(root: str, files: list[str]):
    """尽量把本地 CSS/JS/小图片内联进一个 HTML。运行时还要加载别的文件时放弃，避免产出打不开的单文件。"""
    with open(os.path.join(root, "index.html"), encoding="utf-8", errors="replace") as f:
        html = f.read()
    others = [p for p in files if p != "index.html"]
    if not others:
        return html, None
    if any(p.endswith((".html", ".htm")) for p in others):
        return None, "有多个 HTML 页面，单文件无法承载"
    used = set()

    def local(ref: str):
        ref = ref.split("?")[0].split("#")[0]
        if re.match(r"^([a-z]+:)?//", ref, re.I) or ref.startswith("data:"):
            return None
        p = os.path.normpath(ref.lstrip("./")).replace(os.sep, "/") if not ref.startswith("/") else None
        return p if p in files else None

    def css_tag(m):
        p = local(m.group(1))
        if not p:
            return m.group(0)
        used.add(p)
        return "<style>\n" + open(os.path.join(root, p), encoding="utf-8", errors="replace").read() + "\n</style>"

    def js_tag(m):
        attrs, src = m.group(1) + m.group(3), m.group(2)
        p = local(src)
        if not p:
            return m.group(0)
        used.add(p)
        code = open(os.path.join(root, p), encoding="utf-8", errors="replace").read().replace("</script", "<\\/script")
        attrs = re.sub(r"\s(crossorigin|defer|async)(=\"[^\"]*\")?", "", attrs)
        return f"<script{attrs}>\n{code}\n</script>"

    def asset(m):
        p = local(m.group(2))
        if not p or os.path.getsize(os.path.join(root, p)) > 200_000:
            return m.group(0)
        used.add(p)
        mime = mimetypes.guess_type(p)[0] or "application/octet-stream"
        data = base64.b64encode(open(os.path.join(root, p), "rb").read()).decode()
        return f"{m.group(1)}data:{mime};base64,{data}{m.group(3)}"

    html = re.sub(r"""<link[^>]+rel=["']stylesheet["'][^>]*href=["']([^"']+)["'][^>]*>""", css_tag, html)
    html = re.sub(r"""<link[^>]+href=["']([^"']+)["'][^>]*rel=["']stylesheet["'][^>]*>""", css_tag, html)
    html = re.sub(r"""<link[^>]+rel=["']modulepreload["'][^>]*>""", "", html)
    html = re.sub(r"""<script([^>]*?)\ssrc=["']([^"']+)["']([^>]*)>\s*</script>""", js_tag, html)
    html = re.sub(r"""(<img[^>]+src=["'])([^"']+)(["'])""", asset, html)
    left = [p for p in others if p not in used]
    if left:
        return None, f"页面运行时还要加载 {len(left)} 个文件（如 {left[0]}），内联成单文件会打不开"
    if re.search(r"""import\(|from\s+["']\./""", html):
        return None, "脚本里还有相对路径的模块导入，无法安全内联"
    if len(html.encode()) > ENTRY_LIMIT:
        return None, f"内联后 {len(html.encode())/1024/1024:.2f}MB，超过入口 1MB 上限"
    return html, None


def zip_dir(src_root: str, rels: list[str], dest: str):
    with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for rel in rels:
            z.write(os.path.join(src_root, rel), rel)


def zip_source(src: str, dest: str) -> int:
    n = 0
    with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED) as z:
        for base, dirs, names in os.walk(src):
            dirs[:] = [d for d in dirs if d not in SOURCE_SKIP and not d.startswith(".toy")]
            for nm in names:
                if nm in JUNK_FILES or nm.endswith((".zip", ".skill")) or nm.startswith(".env"):
                    continue
                full = os.path.join(base, nm)
                z.write(full, os.path.relpath(full, src))
                n += 1
    return n


def run_check(path: str):
    script = os.path.join(HERE, "toy_maker_check.py")
    if not os.path.exists(script):
        return None
    r = subprocess.run([sys.executable, script, path, "--json"], capture_output=True, text=True)
    try:
        return json.loads(r.stdout)
    except Exception:
        return None


def human(n: int) -> str:
    return f"{n/1024/1024:.2f} MB" if n >= 1024 * 1024 else f"{n/1024:.1f} KB"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("dist")
    ap.add_argument("--title", required=True)
    ap.add_argument("--slug")
    ap.add_argument("--category", choices=list(CATEGORIES))
    ap.add_argument("--visibility", choices=list(VIS), default="link-only")
    ap.add_argument("--poster")
    ap.add_argument("--icon")
    ap.add_argument("--summary", default="")
    ap.add_argument("--description", help="详细介绍（文本文件路径）")
    ap.add_argument("--activity", default="")
    ap.add_argument("--watermark", action="store_true", help="含自由绘制/用户内容时开启访问者水印")
    ap.add_argument("--theme", choices=["dark", "light"])
    ap.add_argument("--toy-id", help="已发布过就填 id，CLI 命令会生成 update 而不是 create")
    ap.add_argument("--source", help="项目源码目录，一并打包留档")
    ap.add_argument("--out", default="release")
    a = ap.parse_args(argv)

    root = find_root(os.path.abspath(a.dist))
    slug = a.slug or re.sub(r"[^A-Za-z0-9_-]+", "-", os.path.basename(os.path.abspath(a.source or a.dist))).strip("-")[:64] or "my-toy"
    problems, warns = [], []
    if not SLUG_RE.match(slug):
        problems.append(f"slug「{slug}」只能用字母、数字、下划线、连字符，最长 64 字节；发布后不可修改")
    if BRAND.search(a.title):
        warns.append("标题含「哔哩哔哩 / bilibili / B站」等平台标识：使用协议 3.5(3) 未经许可不得使用平台商业标识，建议去掉")
    if a.category == "GAME":
        warns.append("分类为「游戏」：未成年人将无法游玩；全年龄轻互动可考虑「互动玩法」或「测试」")

    files, dropped = collect_files(root)
    entry_size = os.path.getsize(os.path.join(root, "index.html"))
    if entry_size > ENTRY_LIMIT:
        problems.append(f"入口 index.html 为 {human(entry_size)}，超过 1MB 上限，提交会被拒（307000）")
    if dropped:
        warns.append(f"{len(dropped)} 个文件不在平台白名单里，已排除（发布时也会被过滤）：" + "、".join(dropped[:8])
                     + ("……" if len(dropped) > 8 else "") + "。如果页面依赖它们，请换成白名单格式")
    if any(f.endswith((".map",)) for f in dropped):
        warns.append("source map（.map）已排除，正常现象")
    with open(os.path.join(root, "index.html"), encoding="utf-8", errors="replace") as f:
        entry_html = f.read()
    m = re.search(r"<title>(.*?)</title>", entry_html, re.S | re.I)
    if not m or m.group(1).strip() != a.title:
        warns.append(f"index.html 的 <title> 是「{m.group(1).strip() if m else '（无）'}」，网页上传时会被自动当作默认名称，建议与 Toy 名称一致")

    stamp = datetime.now().strftime("%Y%m%d-%H%M")
    out = os.path.abspath(os.path.join(a.out, f"{slug}-{stamp}"))
    os.makedirs(out, exist_ok=True)

    # 方式一：ZIP
    os.makedirs(os.path.join(out, "1-zip"))
    zip_path = os.path.join(out, "1-zip", f"{slug}.zip")
    zip_dir(root, files, zip_path)
    # 方式三：文件夹
    folder = os.path.join(out, "3-folder", slug)
    for rel in files:
        dst = os.path.join(folder, rel)
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.copy2(os.path.join(root, rel), dst)
    # 方式二：单 HTML
    os.makedirs(os.path.join(out, "2-html"))
    single, why_not = try_single_html(root, files)
    if single is not None:
        with open(os.path.join(out, "2-html", "index.html"), "w", encoding="utf-8") as f:
            f.write(single)
    else:
        with open(os.path.join(out, "2-html", "不适用.txt"), "w", encoding="utf-8") as f:
            f.write(f"这个项目不适合用「拖拽单个 HTML」发布：{why_not}。\n请用方式一（ZIP）或方式三（文件夹）。\n")

    # 封面 / 图标
    assets = {}
    for kind, p in (("cover", a.poster), ("icon", a.icon)):
        if not p:
            warns.append("没有提供封面：建议 4:3（如 1200×900）PNG/JPG；网页上传 ZIP 时也可从包内图片里选" if kind == "cover"
                         else "没有提供图标：PNG/JPG，≤512KB，宽高 ≤1024px（与封面是两个字段）")
            continue
        fmt, size = image_size(p)
        ext = os.path.splitext(p)[1].lower()
        if fmt is None or ext not in (".png", ".jpg", ".jpeg"):
            problems.append(f"{p} 不是 PNG/JPEG（平台按图片内容校验，改扩展名无效）")
        dst = os.path.join(out, kind + ext)
        shutil.copy2(p, dst)
        info = {"file": os.path.basename(dst), "format": fmt, "size": list(size) if size else None, "bytes": os.path.getsize(p)}
        if kind == "cover" and size and abs(size[0] / size[1] - 4 / 3) > 0.05:
            warns.append(f"封面 {size[0]}×{size[1]} 不是 4:3，广场卡片会裁切")
        if kind == "icon":
            if os.path.getsize(p) > 512 * 1024:
                problems.append("图标超过 512KB")
            if size and max(size) > 1024:
                problems.append(f"图标 {size[0]}×{size[1]} 超过 1024px")
        assets[kind] = info

    src_files = None
    if a.source:
        src_files = zip_source(os.path.abspath(a.source), os.path.join(out, f"source-{slug}.zip"))

    check = run_check(zip_path)
    desc = open(a.description, encoding="utf-8").read().strip() if a.description else ""

    # CLI 命令
    flags = [f'--title "{a.title}"', f"--visibility {a.visibility}"]
    if a.category:
        flags.append(f"--category {a.category}")
    if a.theme:
        flags.append(f"--theme {a.theme}")
    if "cover" in assets:
        flags.append(f'--poster {assets["cover"]["file"]}')
    if "icon" in assets:
        flags.append(f'--icon {assets["icon"]["file"]}')
    if a.activity:
        flags.append(f"--activity {a.activity}")
    if a.watermark:
        flags.append("--watermark")
    if a.visibility == "password":
        flags.append('--access-password "<4-32 位密码>"')
    if a.toy_id:
        cli = f'toy update {a.toy_id} 1-zip/{slug}.zip ' + " ".join(f for f in flags if not f.startswith("--slug"))
    else:
        cli = f'toy create 1-zip/{slug}.zip --slug {slug} ' + " ".join(flags)

    manifest = {
        "title": a.title, "slug": slug, "url": f"https://www.bilibili.com/toy/{slug}/index.html",
        "category": a.category, "visibility": a.visibility, "activity": a.activity, "watermark": a.watermark,
        "summary": a.summary, "toy_id": a.toy_id, "created": stamp,
        "entry_index_html_bytes": entry_size, "zip_bytes": os.path.getsize(zip_path), "file_count": len(files),
        "single_html": single is not None, "single_html_reason": why_not,
        "assets": assets, "dropped_files": dropped, "problems": problems, "warnings": warns,
        "check": check, "cli": {"preview": cli + " --json", "submit_after_confirm": cli + " --json --yes"},
        "files": [{"path": r, "bytes": os.path.getsize(os.path.join(root, r)), "sha256": sha256(os.path.join(root, r))} for r in files],
    }
    with open(os.path.join(out, "manifest.json"), "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=1)

    L = [f"# {a.title} · Toy 发布留档", "",
         f"生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M')}　｜　页面地址：`{slug}`（发布后不可修改）→ {manifest['url']}", ""]
    if problems:
        L += ["## ❌ 发布前必须解决", ""] + [f"- {p}" for p in problems] + [""]
    if warns:
        L += ["## ⚠️ 请确认", ""] + [f"- {w}" for w in warns] + [""]
    L += ["## 表单填写", "",
          f"- **Toy 名称**：{a.title}",
          f"- **页面地址**：{slug}",
          f"- **分类**：{CATEGORIES.get(a.category, '（未指定）')}",
          f"- **发布方式**：{VIS[a.visibility]}（建议首发「链接访问」，用小号在 B站 App 实测后再改「所有人可见」）",
          f"- **访问者水印**：{'开启' if a.watermark else '关闭'}（含自由绘制/用户内容的 Toy 必须开启）",
          f"- **参与活动**：{a.activity or '不参与'}",
          f"- **封面**：{assets.get('cover', {}).get('file', '（未提供）')}　**图标**：{assets.get('icon', {}).get('file', '（未提供）')}"]
    if a.summary:
        L += ["", "**一句话简介**", "", f"> {a.summary}"]
    if desc:
        L += ["", "**详细介绍**", ""] + [f"> {ln}" if ln else ">" for ln in desc.splitlines()]
    L += ["", "## 三种网页上传方式（选一种）", "",
          "在 [Toy 发布页](https://www.bilibili.com/toy/publish/) 按「页面地址 → 上传文件 → 选择封面 → 填写名称 → 发布」操作：", "",
          f"1. **拖拽 ZIP**：`1-zip/{slug}.zip`（{human(manifest['zip_bytes'])}，{len(files)} 个文件，index.html 在根目录）",
          (f"2. **拖拽 HTML**：`2-html/index.html`（单文件，{human(len(single.encode()))}）" if single is not None
           else f"2. **拖拽 HTML**：不适用——{why_not}"),
          f"3. **选择文件夹**：`3-folder/{slug}/`（平台会自动打包成 ZIP）", "",
          "Mac 自带 Safari 上传后会卡在预览页，请用 Chrome。", "",
          "## 用 CLI 上传（官方 toy 命令行）", "",
          "需要先安装并登录：`curl -fsSL https://boss.hdslb.com/toy-cli/toy/install.sh | bash`，然后 `toy login`。", "",
          "以下命令都在本留档目录里运行（路径是相对的，整个目录拷到别处也能用）。第一步，只生成预览、不提交审核：", "", "```bash", f'cd "{out}"', manifest["cli"]["preview"], "```", "",
          "在浏览器检查返回的 `preview_url`，确认没问题后，用**同样的参数加 `--yes`** 提交审核：", "",
          "```bash", manifest["cli"]["submit_after_confirm"], "```", "",
          "参数以 `toy create --help-json` / `toy update --help-json` 的实际输出为准。", ""]
    if check:
        L += ["## 自查结果（toy_maker_check.py）", "",
              f"{'通过' if check.get('ok') else '未通过'}：{len(check.get('errors', []))} 个错误，{len(check.get('warnings', []))} 个提醒", ""]
        L += [f"- ERROR {e}" for e in check.get("errors", [])] + [f"- WARN {w}" for w in check.get("warnings", [])] + [""]
    L += ["## 留档说明", "",
          "- 《Toy 使用协议》2.8：平台不承诺永久存储、备份或版本回溯，**请自行保存本目录**。",
          f"- `source-{slug}.zip`：源码（{src_files} 个文件，不含 node_modules / dist / .git）" if src_files is not None else "- 未打包源码：可加 `--source <项目目录>` 一起留档",
          "- `manifest.json`：每个文件的大小与 sha256，用来核对线上版本。", ""]
    with open(os.path.join(out, "发布信息.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(L))

    print(f"留档目录：{out}")
    for p in problems:
        print(f"ERROR  {p}")
    for w in warns:
        print(f"WARN   {w}")
    if check and not check.get("ok"):
        print("自查未通过，详见 发布信息.md")
    return 1 if problems or (check and not check.get("ok")) else 0


if __name__ == "__main__":
    sys.exit(main())
