# Toy 功能实现配方

每段默认已 `await initToy()`，并通过 `assets/toy-bridge.ts` 的 `toy()` / `supports()` 调用。参数约束以 `sdk-api.md` 为准。

## 目录

1. 启动顺序与首屏
2. 存档（云存储）
3. 排行榜
4. 多榜位存复合数据、分数缩放
5. 跨 Toy 进度（共享存档 + 跳转）
6. 用户昵称头像（不允许自建）
7. 关注 / 充电 / 老粉 / 三连 福利
8. 作者资料与作者视频墙
9. 结果分享：share、二维码、保存图片
10. 横屏游戏（Canvas / Phaser）
11. 玩家输入（昵称、留言）
12. 摄像头 / 麦克风
13. 站内跳转

---

## 1. 启动顺序与首屏

```ts
import { initToy, toyEnv } from './toy-bridge'

await initToy()               // SDK 在 <head> 同步加载，通常立即就绪
renderTitleScreen()           // 首屏内容不依赖任何网络/授权：满足「免交互可见」
startButton.onclick = async () => {
  unlockAudio()               // 手势内解锁 AudioContext
  const save = await createSaveStore(DEFAULT_SAVE)  // 读存档可以放在这里，带加载态
  startGame(save)
}
```

- 不要在页面加载时就弹授权（`getUserProfile`、摄像头等）。等用户主动触发相关功能。
- 加载中状态是必须的：云端读写、榜单都可能慢或限流。

## 2. 存档（云存储）

```ts
const save = await createSaveStore({ coins: 0, level: 1, unlocked: [] as string[] })

// 游玩中：只改内存
save.set('coins', save.data.coins + 10)

// 关键节点：过关、结算、回主菜单
await save.flush()
if (save.lastError) showToast('存档暂未同步，稍后会自动重试')
```

要点：
- 一个顶层字段 = 一个云存储 key；单值 ≤1024 字节，最多 128 个 key。大的列表拆成多个 key（如 `inv_0`…`inv_3`）或压缩编码（位图、短字段名）。
- key 只能 `[A-Za-z0-9_-]`，≤128 字节，不能以 `__` 开头。
- 未登录时 `getCloudStorage` 会失败，桥接层自动退回 localStorage 镜像，玩家照样能玩；可在 UI 提示「登录后进度可跨设备同步」。
- **不要**每次得分写一次，**不要** `setInterval` 定时保存，**不要** for 循环逐 key 写。

## 3. 排行榜

```ts
import { submitScore, getRankList } from './toy-bridge'

// 结算时提交一次（只保留历史最高；同分重复提交也耗额度）
const { score: best } = await submitScore(finalScore, 1)

// 打开排行榜面板时读一次，之后复用；「刷新」按钮才传 refresh=true
const list = await getRankList(1, 'week', 50)
const mine = await toy().getMyRank({ board: 1, period: 'week' })
if (mine.ranked) showMyRank(mine.rank, mine.score)   // 必须用 ranked 判断，score 可能是 0/负数
```

- 首次 `submitScore` 会触发平台的用户数据确认；用户拒绝会 reject，要 catch 并允许「不上榜继续玩」。
- `getRankList` 游客可读，`getMyRank` / `submitScore` 需登录。
- 榜单头像是协议相对地址（`//p0.hdslb.com/...`），`<img>` 可直接用；画到 Canvas 上会有跨域污染，导出图片前要注意。
- 刷分：管理端可拉黑账号；重要比赛类玩法把每局结算放到自建后端验签。

## 4. 多榜位存复合数据、分数缩放

- 5 个榜位各自独立：例如 board 1 = 最高分，board 2 = 最快通关（用负的毫秒数存，这样「越快越高」），board 3 = 收集数。
- 分数是 Float32 精确整数范围（±16777215）。小数分数先乘倍数取整；超范围的分数在本地做对数/偏移压缩后上传，展示时自行还原（SDK 不管展示）。
- 想在榜单显示额外字段（如角色、关卡）：榜单只有 rank/score/nickname/avatar，扩展字段暂不支持，可以把小信息编码进分数的低位（如 `score * 10 + roleId`），展示时拆开。

## 5. 跨 Toy 进度（共享存档 + 跳转）

```ts
const STORAGE_ID = 'st_xxxxxxxxxxxxxxxx'  // 创作中心「共享存档」创建，或 toy shared-storage
const { chapter = '1' } = await toy().getSharedStorage(STORAGE_ID, ['chapter'])
// 通关后
await toy().setSharedStorage(STORAGE_ID, { chapter: String(Number(chapter) + 1) })
nextChapterBtn.onclick = () => toy().navigate({ type: 'toy', id: '<下一个 Toy 的 id>' })  // toy id 见 toy mylist --json
```

- 共享的是「同一个玩家」在多个 Toy 之间的数据，不是玩家之间共享。
- `no_permission`（作者未被授权）、`not_found`（存档被删）重试无用，提示即可。
- 私有云存储不会自动迁移到共享存档。
- `navigate` 各 type 的 id：video=BV 号、space=用户 mid、search=关键词、opus=动态 id、tribee=小站 id、toy=toy id。

## 6. 用户昵称头像（不允许自建）

```ts
nameButton.onclick = async () => {               // 首次授权需要用户操作触发
  try {
    const { nickname, avatar } = await toy().getUserProfile()
    player.name = nickname
    player.avatar = avatar
  } catch {
    player.name = pickRandom(PRESET_NAMES)        // 拒绝授权：系统随机 / 预置候选
  }
}
```

- 合规：不能提供「自己起名」输入框来给公开展示的昵称；可以提供一组预置候选让玩家选。
- `toyOpenId` 只在当前 Toy 内稳定，用来在自建后端关联数据；不写埋点、不进日志。

## 7. 关注 / 充电 / 老粉 / 三连 福利

```ts
const rel = await toy().getAuthorRelation()
if (rel.status === 'ok') {
  if (rel.data.isFollowing) grantBonus('follow_skin')
  if (rel.data.isCharging) grantBonus('charge_badge')
  if (rel.data.hasFanMedal && (rel.data.fanMedalLevel ?? 0) >= 10) grantBonus('medal_title')
} else if (rel.status === 'unsupported') {
  showHint('在 B站 App 内打开可领取粉丝福利')
}

// 三连检测：指定作者自己的视频（含联合投稿）
const acts = await toy().getVideoUserActions({ videos: [{ bvid: 'BVxxxx' }] })
const v = acts.items?.[0]
const tripled = v?.status === 'ok' && v.liked && (v.coinCount ?? 0) > 0 && v.favorited
```

- 这些都是**数据类接口：不抛错，看 `status`**。外部手机浏览器返回 `unsupported`。
- 福利只能是附加内容（皮肤、称号、额外关卡、复活次数），不能锁主线；引导关注放在复活/强化等节点，不要每局都弹。
- 前端判断可被破解，不要用它保护真正有价值的东西。
- 玩家关注后回到页面，需要重新调用一次才能拿到新状态——提供「我已关注，刷新」按钮，不要轮询。

## 8. 作者资料与作者视频墙

```ts
const prof = await toy().getAuthorProfile()
if (prof.status === 'ok') renderAuthorCard(prof.data)   // 昵称、粉丝数、稿件数、充电聚合、勋章配置

const vids = await toy().getAuthorVideos({ videos: [{ bvid: 'BV1...' }, { aid: 123 }] }) // 1–50 项
vids.items?.forEach((it) => it.status === 'ok' && renderVideo(it.data))
```

- 只能查**当前 Toy 作者**参与创作的视频，别人的视频返回 `author_mismatch`。
- 点击视频卡片用 `navigate({ type: 'video', id: bvid })`，必须在 click 里调用。

## 9. 结果分享：share、二维码、保存图片

```ts
resultShareBtn.onclick = async () => {
  const path = `index.html#/result?s=${score}`   // 相对当前 Toy 根；不能是绝对 URL 或 ../
  if (await supports('share')) return toy().share({ path })
  // Web 端：展示二维码，让手机扫码
  const { base64 } = await toy().getQrCode({ path, size: 320 })
  qrImg.src = base64
}

saveBtn.onclick = async () => {
  const dataUrl = posterCanvas.toDataURL('image/jpeg', 0.9)   // 尽量控制在 2MB 以内
  if (await supports('saveImageToAlbum')) {
    await toy().saveImageToAlbum({ base64Data: dataUrl, hintMsg: '保存你的结果卡' })
  } else {
    const a = document.createElement('a')
    a.href = dataUrl
    a.download = 'result.jpg'
    a.click()                                                  // Web 端：用户点击触发下载
  }
}
```

- 结果卡上放 `getQrCode()` 的二维码，把 Toy 入口带进截图传播（FAQ 认可的做法）。二维码 base64 可以直接画进 Canvas 或作为 `base64Data` 保存。
- `base64Data` 上限 5MB（按字符串长度算），建议 ≤2MB；更大用 `url`。
- 画进 Canvas 的跨域图片（榜单头像等）会污染画布导致 `toDataURL` 失败，海报里避免直接画外域图，或使用允许 CORS 的资源。
- 只能保存图片，不能生成/下载视频。

## 10. 横屏游戏（Canvas / Phaser）

```ts
import { watchContainer, requestContainerMode } from './toy-bridge'

const off = await watchContainer((s) => {
  const { width, height } = s.viewport
  layoutStage(width, height, s.safeArea)        // 交互按钮避开 safeArea，顶部尤其
  if (s.changedFields.includes('viewport')) {
    game.scale.refresh()                          // Phaser；其他引擎重设 canvas 尺寸
    setTimeout(() => game.scale.refresh(), 300)   // 全屏横屏后画面变小的兜底
  }
})

playBtn.onclick = async () => {
  const ok = await requestContainerMode({ orientation: 'landscape', immersive: true })
  if (!ok) showRotateHint()                       // 旧客户端/Web：CSS 旋转自适应 + 提示用户横置手机
  startGame()
}
```

- 手机上「横屏 + 非沉浸」不支持，横屏一律同时开沉浸。
- 退出游戏回菜单时可以 `requestContainerMode({ orientation: 'portrait', immersive: false })`。
- 沉浸模式下评论栏隐藏，顶部有胶囊按钮（位置由 safeArea 体现）。
- Web 端无容器能力，`watchContainer` 会用 window resize 兜底。

## 11. 玩家输入（昵称、留言）

先问自己：这段文字会不会被**其他玩家**看到？不会 → 只本地展示，风险小；会 → 属于 UGC，按下面做，并接受平台审核结论。

```ts
submitBtn.onclick = async () => {
  const text = input.value.trim()
  if (!text) return
  try {
    const r = await toy().checkInputSafety({ text, scene: 'message' })  // 提交时检测一次，不要每次按键
    if (r.passed) return postMessage(text)
    tip(r.status === 'rejected' ? '这段内容不能发布，换个说法试试' : '暂时没法验证，稍后再试')  // unavailable ≠ 通过
  } catch (err) {
    tip(isRateLimited(err) ? '操作太频繁，稍后再试' : '提交失败')
  }
}
```

- 不提供图片上传、拍照公开、聊天室、自由画板公开展示——这些是红线，除非平台给了对应权限点。
- 有自由绘制能力的 Toy 发布时开 `--watermark`。

## 12. 摄像头 / 麦克风

```ts
camBtn.onclick = async () => {                     // 必须在手势里直接调用，前面别 await 其他请求
  try {
    const stream = await toy().requestCamera({ facingMode: 'user' })
    video.srcObject = stream
    await video.play().catch(() => {})             // iOS 必须显式 play
    stopBtn.onclick = () => toy().stopMedia(stream)
  } catch (e) {
    // e.name: BusinessDenied / NotAllowedError / NotFoundError / NotReadableError / AbortError
    showFallback()
  }
}
```

- 用完必须 `stopMedia`，页面隐藏时也释放。
- 麦克风返回实时流：录音用 `MediaRecorder`，音量用 `AudioContext` + `AnalyserNode` 自己算。
- 拍照结果只在本地处理/展示；不要上传公开（UGC 红线）。
- 不支持指定超广角镜头。

## 13. 站内跳转

```ts
btn.onclick = () => toy().navigate({ type: 'space', id: AUTHOR_MID })   // 作者主页（引导充电只能来这里）
btn2.onclick = () => toy().navigate({ type: 'video', id: 'BV1xxxx' })
```

- `type`：video | space | search | opus | tribee | toy。必须在用户手势里调用。
- 不要用 `<a href="https://...">` 或 `window.open` 跳站外；B站站内域名也优先用 `navigate`。
- 页内跳转用相对路径（`./page2.html`）或 hash 路由。
