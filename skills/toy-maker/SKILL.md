---
name: toy-maker
description: "B站 Toy（bilibili.com/toy）全类型作品的创作与开发 skill：测试、工具、生成器/整活、攻略、合集、互动玩法、游戏都覆盖。先实时抓取 Toy 广场（btoy/square）的本周必玩、上升榜、同题材作品做对标，结合爆款规律和各类型手册，把开发者的想法打磨成一份成熟的定稿方案；再负责搭项目、接入 Toy JS SDK（window.toy：云存档、排行榜、共享存档、昵称头像、关注/充电/三连检测、分享、二维码、保存图片、横竖屏与沉浸、安全区、摄像头麦克风、输入内容检测）、适配 B站 App、合规自查、构建检查，最后交给官方 toy CLI 发布。只要用户想做/在做/想改一个 B站 Toy，或者只是有个点子想听听能不能火、问做什么类型、要对标、要方案，或提到 Toy 广场、本周必玩、Toy SDK、toy-sdk.js、window.toy、云存档、排行榜、横屏、安全区、审核不过、合规、白屏黑屏、index.html 1MB，就使用本 skill——即使用户没说「skill」「SDK」。纯发布/更新/统计/绑视频的 CLI 操作交给官方 `toy` skill。"
---

# toy-maker：把创意做成能过审、被人玩、被人传的 B站 Toy

Toy 是 B站的互动内容形态：一个跑在 `https://www.bilibili.com/toy/<slug>/` 下的纯前端网页包（测试、小游戏、工具、生成器、互动叙事……），主要在 B站 App 的 WebView 里被打开，也能在电脑浏览器访问。平台提供作者绑定、托管、安全扫描、审核，以及一套 JS SDK（`window.toy`）。

本 skill 管从想法到可发布包的全程：广场对标 → 方案定稿 → 搭项目 → 接 SDK → 适配容器 → 合规 → 构建与自查 → 交给发布。所有类型的 Toy 都适用，不只是游戏。发布本身（`toy create/update`、预览确认、绑视频、看数据）由官方 `toy` skill + `toy` CLI 负责，见文末「交给发布」。

## 资料地图（按需读，不要一次全读）

| 文件 | 什么时候读 |
| --- | --- |
| `scripts/fetch_square.py` | 每次开始构思或给建议前跑一次，拿 Toy 广场当下数据（零依赖、免登录）。 |
| `references/hit-patterns.md` | 解读广场数据的框架：赛道格局、首屏、题材、头部作品的 SDK 用法、各类型的互动信号、长期运营。 |
| `references/playbooks/<类型>.md` | 确定类型后读对应的一份：`test` 测试、`tool` 工具、`game` 游戏、`interactive-play` 互动玩法、`guide` 攻略、`collection` 合集、`meme-generator` 整活/生成器/模拟器。 |
| `references/final-plan.md` | 想法确定、动手前：Toy 版「高度-深度-广度」定稿流程和方案模板。 |
| `references/showcase.md` / `data/showcase.json` | 内置的广场快照（实时抓取失败时用，注意日期）。 |
| `references/sdk-api.md` | 写任何 `toy.xxx()` 调用前。官方 SDK 全文（参数、返回值、限制、环境支持表、频率限制）。**API 细节以它为准，别凭记忆。**（官方原文，随附版本下载于 2026-10-28，见下方「官方 SDK 文档」） |
| `assets/toy.d.ts` | TS 项目直接拷进 `types/toy.d.ts`，自动获得 `window.toy` 类型。也是数据类接口 `status` 枚举、错误名的权威来源。（官方原文，同上） |
| `references/recipes.md` | 要实现具体功能时：存档系统、排行榜、横屏游戏、结果分享卡、关注/充电福利、玩家输入、摄像头麦克风、三连检测。 |
| `references/platform-rules.md` | 做技术选型、打包、排查白屏/黑屏/预览不一致时；以及**任何涉及合规的设计决策**（输入框、昵称、外链、登录、付费、广告、音乐素材）。官方 FAQ 的开发者向浓缩。 |
| `assets/toy-bridge.ts` | 新项目或要接 SDK 时，拷进项目当统一入口：本地开发自动 mock、批量防抖存档、307044 退避、能力检测。 |
| `assets/vite.config.toy.ts` | Vite 项目的 Toy 构建配置模板。 |
| `scripts/toy_maker_check.py` | 构建后、发布前跑一遍（零依赖）。查 SDK 接入、合规风险、白名单外的文件；包结构/路径问题交给官方 `toy_doctor.py`。 |
| `references/publish-guide.md` | 官方发布流程（三种上传方式）、发布 FAQ（含文件后缀白名单）、《Toy 使用协议》中开发者会踩到的条款。涉及发布、留档、第三方代码、商标、数据收集、独家运营时读。 |
| `scripts/make_release.py` | 开发完成后：把构建产物整理成「ZIP / 单 HTML / 文件夹」三种上传形态 + 封面图标 + 源码 + 发布信息.md（含 CLI 命令）+ manifest，方便留档和上传。 |

### 官方 SDK 文档（第一次用 SDK 前确认）

`references/sdk-api.md` 和 `assets/toy.d.ts` 是 B站官方文档原文（官网需登录有 Toy 权限的账号才能查看），本 skill 随附 2026-10-28 下载的版本，版权归哔哩哔哩。要写 `toy.xxx()` 代码时先检查这两个文件在不在、日期是否太旧：

- **在**：直接用，注意文件顶部的日期。
- **不在或明显过期**（例如 `isSupport` 列表出现文档里没有的能力）：请用户打开 https://www.bilibili.com/toy/publish/sdk （登录有 Toy 权限的账号），点「下载 Markdown」和「下载 toy.d.ts」，把文件放到本 skill 目录的 `references/sdk-api.md` 和 `assets/toy.d.ts`（或直接发给你，由你放进去）。当前环境如果有能带用户登录态的浏览器工具，也可以经用户同意后代为下载。
- 用户暂时拿不到时：可以先做设计、方案、广场对标、合规和打包；写 SDK 代码时只用 `references/recipes.md` 和 `assets/toy-bridge.ts` 里出现过的方法与参数，并明确告诉用户「上线前对照官方文档核对一遍」，不要凭记忆补充其他 API。

## 工作流

### 0. 看看广场现在什么在火

用户带着点子来、问「做什么好」、或者要建议时，先跑：

```bash
python3 "<toy-maker-dir>/scripts/fetch_square.py" --search <题材关键词...>
```

输出在当前目录 `.toy-maker/showcase.md`（本周必玩、上升最快、今日推荐、各类型总榜、同题材搜索结果）。读法见 `references/hit-patterns.md`。

- 用的是广场网页自己调用的公开只读接口，不需要登录和浏览器。`--sdk-scan 20` 可以额外统计热门作品用了哪些 SDK 能力（较慢，按需）。
- 拿不到（退出码 3 表示用了内置快照，2 表示快照也没有）：说一句，改用快照，或用当前环境里任何能开网页的工具看 https://www.bilibili.com/btoy/square ，都不行就跳过，不影响后面的步骤。
- **热度 ≠ 值得模仿**：福利领取、信息差、拉人互助类高游玩作品贴着红线、几乎零互动，不作为对标。
- 引用具体作品和数字时带链接和抓取日期。

### 1. 定类型、出方案

先帮开发者定类型——不是所有点子都该做成游戏：

| 用户想要的体验 | 建议类型 | 手册 |
| --- | --- | --- |
| 回答问题得到一个「我是谁」的结果 | 测试 `TEST` | `playbooks/test.md` |
| 帮某群人查、算、规划、匹配 | 工具 `TOOL` | `playbooks/tool.md` |
| 有输赢、有关卡、有分数 | 游戏 `GAME`（未成年人不能玩） | `playbooks/game.md` |
| 没有输赢的玩具：音乐、捏人、创作、互动展览、教学实验 | 互动玩法 `INTERACTIVE_PLAY` | `playbooks/interactive-play.md` |
| 图鉴、卡组库、收集对照、逛展指南 | 攻略 `GUIDE` | `playbooks/guide.md` |
| 作者作品集、主题精选 | 合集 `COLLECTION` | `playbooks/collection.md` |
| 一个梗、一键生成、XX 模拟器、转盘 | 多为其他 `OTHER` | `playbooks/meme-generator.md` |

然后读对应手册，并**在开发者想法确定后走 `references/final-plan.md`**：拿广场对标、找目标背后的目标、按类型手册补齐首屏/循环/回访/传播/视频/SDK/合规，用几个专业视角挑错，输出一份定稿方案，开发者确认后再写代码。小改动、修 bug、纯技术问题不需要走这一步。

动手前要对齐的硬约束（已经清楚的就别问）：

- **分类**：选「游戏」后未成年人自动无法游玩——面向全年龄的轻互动考虑「互动玩法」或「测试」。
- **主要设备**：B站 App 手机竖屏是主场；横屏要接容器能力（见 §4）。PC 浏览器也能玩，但没有容器/分享/存相册能力。
- **要不要账号数据**：云存档、排行榜、昵称头像、关注/充电/三连检测，每一项都会带来授权弹窗或登录要求，按需接。
- **免交互可见内容**：不做任何互动也能玩到实质内容；关注/充电/三连只能解锁额外奖励。
- **分享点**：结算页/结果卡是天然分享点（`toy.share` / `toy.getQrCode` / `saveImageToAlbum`）。

### 2. 技术选型与脚手架

- 推荐：原生 HTML/Canvas 2D、Vite + 任意框架、Phaser、Three.js、PixiJS；引擎类 Unity WebGL 可用（注意关压缩、别带 .mp4）；Godot 4 Web 兼容性一般、包大，Web 向优先前两类。
- WebGPU 取决于 WebView 和设备，**必须有 WebGL/WebGL2 兜底**。
- 只传**构建产物**，入口 `index.html` 在 zip 根目录（或唯一一级子目录）。
- 资源一律**相对路径**；构建工具设 `base: './'`（Vite）/ `publicPath: './'`（webpack/Vue CLI）/ `"homepage": "."`（CRA）。
- 路由用 **hash 模式**（`#/page`）或多 HTML 文件；history 模式刷新会 404。
- **入口 index.html 解压后 ≤ 1MB 是硬上限**（超了 create/update/preview 都报 `307000`）。别用 `vite-plugin-singlefile` 这类单文件打包产出入口；大数据、base64 图都拆成独立文件。
- 整包默认上限 50MB（可在创作者设置申请更大）；只有白名单后缀会被发布，可执行文件/后端脚本会被过滤。
- Vite 项目直接用 `assets/vite.config.toy.ts` 模板（相对 base、contenthash、vendor 拆包，利于平台跨版本复用缓存）。

### 3. 接入 SDK

在 `index.html` 的 `<head>` 里引入（协议相对地址，原样照抄）：

```html
<script src="//s1.hdslb.com/bfs/seed/toy/app/sdk/toy-sdk.js"></script>
```

要点（细节以 `references/sdk-api.md` 为准）：

- 除 `onContainerChange`（同步返回取消函数）外全部返回 Promise。错误 message 带 `[ToySDK]` 前缀。
- **两类失败形态不同**：用户/作者/视频互动这些数据类接口**不抛错，用 `status` 字段表达**（`ok / partial / unauthorized / denied / unsupported / ...`），先判 `status === 'ok'` 再读 `data`；云存储、共享存档、排行榜失败时 **reject**，要 `try/catch`。
- 仅 App 内可用：`saveImageToAlbum`、`share`、`closeBrowser`、`onContainerChange`、`getContainerState`、`setContainerMode`。调用前 `await toy.isSupport('xxx')`，Web 端给替代方案（如 `<a download>`、展示二维码）。
- **必须在用户手势里直接调用**：`navigate`、`requestCamera`、`requestMicrophone`；`getUserProfile` 首次授权也要由用户操作触发。别在 `await` 了别的网络请求之后再调，手势激活可能已失效。
- 本地开发没有 `window.toy`（或 SDK 只认 `/toy/<slug>/` 路径），所以**通过一层桥接调用**，别在业务代码里到处直接写 `window.toy`。`assets/toy-bridge.ts` 已经处理：SDK 不可用时自动用 localStorage mock、批量防抖写存档、页面隐藏时落盘、307044 指数退避。拷进项目后按需裁剪。
- TS 项目把 `assets/toy.d.ts` 拷进 `types/toy.d.ts`。

**频率限制**（同一 Toy 所有玩家共享额度，超限报 `307044`）——云存储当存档不当内存、批量代替循环、读结果缓存不轮询、排行榜结算时提交一次、失败指数退避。**具体阈值不公开且可调，不要写死数字做节流，也别向用户报具体 QPS。** 拉取要设计「加载中」状态，别假设瞬时完成。

各能力的完整写法见 `references/recipes.md`。

### 4. 适配 B站 App 容器

- `<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">`。
- 横屏 / 沉浸：先 `onContainerChange` 监听，再 `setContainerMode({ orientation: 'landscape', immersive: true })`；`Promise<void>` 不代表生效，**以收到匹配的状态为准**。手机不支持「横屏且非沉浸」。需要 B站 App 9.9.0+；旧客户端要做旋转自适应兜底（CSS 检测宽高比，提示用户旋转）。
- 沉浸模式下：顶部有胶囊按钮，用 `state.safeArea` 避开，**交互元素不要放在安全区里（尤其顶部）**；评论栏会隐藏。
- 视口变化后要重新布局：Canvas 重设尺寸；Phaser 在 `onContainerChange` 里 `game.scale.refresh()`，再加一次延时重试兜底（全屏横屏后画面变小的已知问题）。
- 多机型按键：允许玩家在设置里调整虚拟按键位置；设置类入口收进二级菜单。
- 音频：移动端需用户手势后才能出声，首屏放「点击开始」解锁 AudioContext。
- 本地存储会被清缓存，重要进度走云存档；云存档需要登录，未登录时要能降级为本地。
- 鸿蒙版能进但无点赞评论；国际版功能较少；Safari 上传发布有问题（这是发布端，不影响玩家）。

### 5. 合规：设计时就避开，别等审核打回

最常见的打回/下架原因（完整清单与灰区判断见 `references/platform-rules.md` 的合规部分）：

- **UGC 是安全红线**：用户自由输入文字、上传图片/拍照后公开、聊天室、画板等，平台正在收敛为权限点审核。必须有输入时：只用于自己可见，或在提交时调 `toy.checkInputSafety`（`unavailable` 不等于通过），并且不允许用户上传底图。用 iframe 做聊天室同样不行。含自由绘制的 Toy 发布时须开 `--watermark`。
- **昵称头像**不能让用户自建，只能用 `getUserProfile` 拿到的或系统随机/预置候选。
- **不能跳站外**：不放外链、不接第三方登录（QQ、TapTap、微信……）、不放爱发电/收款码、不接广告联盟 SDK、不做支付。跳转用 `toy.navigate`（视频/空间/搜索/动态/小站/其他 Toy）。不用 b23 短链（约一年失效）。iframe 不能嵌外部网页，播 B站视频用 player.bilibili.com 播放器 iframe。
- **不锁基础功能**：至少一份内容免交互可得；关注引导放在复活/强化/新武器等环节，别放主线必经处；不做常驻式引导。
- **版权**：素材、BGM、音效都要可商用或已授权；同人/二创自行判断版权方态度；模拟真实机构/App 界面要显著标明「非真实」。
- **toyOpenId** 不是鉴权凭证，不要写入埋点或公开日志。
- 自建后端/调用自有 API 需要先开通对应权限（发布平台可查）。问卷可以做但要自建后端且不收敏感信息。
- **使用协议里容易忽略的几条**（详见 `references/publish-guide.md` 第三节）：不嵌统计/埋点代码和未经同意的第三方 SDK；依赖库打包进项目，不用远程脚本、动态加载、热更新绕过审核；名称/封面/图标不带「哔哩哔哩」「bilibili」「小电视」等平台标识，也不暗示官方合作；收集数据要先征得同意且只收必需的；协议写明服务期内平台有独家运营权，打算多平台同发的要提醒开发者看原文、先问平台。

### 6. 测试

- 本地：`npm run dev`，桥接层自动 mock；可加 `?toymock=0` 强制关闭 mock 验证降级路径。
- 真机：没有独立测试环境。用「链接访问」或「密码访问」发布，再用小号在 B站 App 里打开测试；或者另建一个测试用 Toy 与正式 Toy 分开。预览页与真实环境可能略有差异，以 App 内实测为准。
- 重点测：横竖屏切换与旧版本客户端、刘海屏安全区、未登录/拒绝授权路径、弱网下存档与榜单加载态、PC 浏览器（容器能力不可用的降级）。

### 7. 构建后自查

```bash
python3 "<toy-maker-dir>/scripts/toy_maker_check.py" <dist目录|zip|html> [--json]
```

它查：入口与 1MB 上限、SDK 有没有引入、App 专属能力有没有 `isSupport` 守卫、`setContainerMode` 是否配了监听、摄像头麦克风是否 `stopMedia`、存档/榜单轮询、输入框与 `checkInputSafety`、外链/第三方登录/收款/广告/b23、外部 iframe、只用 localStorage 存进度、可能被过滤的文件后缀、Unity 压缩与 .mp4 等。ERROR 先修；WARN 逐条讲给用户听，由用户判断（静态匹配在压缩产物里会有误判）。

如果装了官方 `toy` skill，再跑它的 `scripts/toy_doctor.py`（资源绝对路径、hash 路由、封面比例、contenthash、HTML 体积形态等），两者互补。

### 8. 打包留档，交给发布

开发完成、自查通过后，**主动**生成发布留档包，不用等用户要：

```bash
python3 "<toy-maker-dir>/scripts/make_release.py" <dist目录> --title "<Toy 名称>" --slug <页面地址> \
  --category <分类> --poster <封面> --icon <图标> --summary "<一句话简介>" [--description 介绍.md] \
  [--watermark] [--activity <活动code>] [--toy-id <已发布的id，更新时用>] --source <项目根目录>
```

产出 `release/<slug>-<时间>/`：
- `1-zip/<slug>.zip`、`2-html/index.html`、`3-folder/<slug>/`——对应官方发布页的三种上传方式（拖 ZIP / 拖单个 HTML / 选文件夹）。单 HTML 只在能安全内联成 ≤1MB 单文件时生成，否则写明原因（多文件项目通常不适用，这是正常的）。
- 只保留白名单后缀的文件，被排除的会列出来；`.DS_Store`、`node_modules`、`toy.yaml` 等自动去掉。
- `cover.*` / `icon.*`（校验格式、4:3、图标 ≤512KB ≤1024px）、`source-<slug>.zip`（源码，不含 node_modules/dist/.git）。
- `发布信息.md`：表单该填什么、三种网页上传步骤、在本目录下可直接运行的 CLI 命令（先预览、确认后加 `--yes`）、自查结果、留档说明；`manifest.json`：每个文件 sha256。

脚本有 ERROR（slug 不合法、入口超 1MB、封面图标格式不对、自查未通过）时先修再发。把留档目录和 `发布信息.md` 的要点告诉用户；协议 2.8 要求开发者自行备份，提醒用户把整个目录存好（不必提交到公开仓库）。

发布本身走官方 `toy` CLI 和官方 `toy` skill，不要自己拼流程：

- 没装 skill：`npx -y skills add bilibili/toy --skill toy -g -y`；没装 CLI：`curl -fsSL https://boss.hdslb.com/toy-cli/toy/install.sh | bash`，再 `toy login`。
- 装了就按官方 skill 走（`--help-json` 发现参数、`--json` 输出、**先预览 → 用户明确确认 → 才加 `--yes` 提交审核**、slug 发布后不可改）。
- 首发建议「链接访问」测试，确认后再改「所有人可见」（公开才进 Toy 广场）。审核通常 10 分钟内；新建 Toy 的封面图标也要审核，期间可能不显示。
- 封面建议 4:3（如 1200×900），图标 PNG/JPEG ≤512KB、≤1024px，二者是不同字段。
- 发布后：绑定本人视频（一个视频只能绑一个 Toy），推荐一条横屏 + 多条竖屏切片；多次修改攒一起更新以减少审核次数。

## 遇到问题时的排查顺序

1. **白屏 / 资源 404**：绝对路径、history 路由、zip 根目录没有 index.html、分享链接缺 `index.html`、slug 与历史条目重复。
2. **Unity 黑屏**：关闭构建压缩、移除 .mp4（改 CDN 加载）。Cocos 的 `.cconb.bin` 等可能被过滤。
3. **SDK 调用报错**：看 `[ToySDK]` 前缀的 message；`unsupported` → 环境不支持（Web 端/外部浏览器/不在 `/toy/<slug>/` 下）；`invalid_param` → 对照 `references/sdk-api.md` 的参数约束；`307044` → 频率限制，退避；数据类接口看 `status`。
4. **横屏不生效**：客户端版本 < 9.9.0、没先监听、手机上横屏没同时开沉浸。
5. **预览正常发布后异常**：带复现信息到 Toy 开发者小站反馈。

## 刷新官方文档

SDK 在持续迭代（`references/sdk-api.md` 顶部写着抓取日期）。用户提到新能力、或者 `isSupport` 列表里出现文档里没有的名字时，重新拉一次：打开 `https://www.bilibili.com/toy/publish/sdk`（需登录有 Toy 权限的账号；没登录会被重定向到 /toy/intro），点「下载 Markdown」和「下载 toy.d.ts」，覆盖 `references/sdk-api.md`（保留顶部来源注释）与 `assets/toy.d.ts`。官方 FAQ：`https://www.bilibili.com/opus/1241171666570051585`，有更新时同步到 `references/platform-rules.md`。打开这些页面用当前环境里任何能带登录态的浏览器工具；没有就请用户自己下载后提供文件。

内置广场快照的刷新（维护者用）：`python3 scripts/fetch_square.py --out data --sdk-scan 40 && mv data/showcase.md references/showcase.md`。广场规律有明显变化时同步更新 `references/hit-patterns.md`。
