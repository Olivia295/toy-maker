/**
 * toy-bridge.ts —— B站 Toy JS SDK 的项目内统一入口（toy-maker skill 模板）
 *
 * 拷进项目（如 src/toy-bridge.ts），配合 types/toy.d.ts 使用。业务代码只 import 这里，
 * 不直接碰 window.toy，好处：
 *   - 本地开发 / 非 B站环境自动切到 localStorage mock，页面照样能跑；
 *   - 存档统一走「内存 → 关键节点批量落盘」，天然符合频率限制最佳实践；
 *   - 307044 限流统一指数退避；
 *   - 横竖屏切换返回「是否真的生效」。
 *
 * 前置：index.html <head> 中引入
 *   <script src="//s1.hdslb.com/bfs/seed/toy/app/sdk/toy-sdk.js"></script>
 *
 * URL 开关：?toymock=1 强制 mock；?toymock=0 禁止 mock（用来验证 SDK 缺失时的降级路径）。
 * 按需删减，不用的能力别留着。
 */

export type ToyEnv = 'sdk' | 'mock'

type Ability = Parameters<ToySDK.Toy['isSupport']>[0]

const LS_PREFIX = 'toy-mock:'

// ---------------------------------------------------------------------------
// 初始化
// ---------------------------------------------------------------------------

let toyRef: ToySDK.Toy | null = null
let env: ToyEnv = 'mock'

function mockFlag(): boolean | null {
  const v = new URLSearchParams(location.search).get('toymock')
  return v === '1' ? true : v === '0' ? false : null
}

/** 等 SDK 挂上 window.toy；拿不到时按开关决定是否用 mock。应用启动时 await 一次。 */
export async function initToy(timeoutMs = 3000): Promise<ToyEnv> {
  if (toyRef) return env
  const forced = mockFlag()
  if (forced !== true) {
    const start = Date.now()
    while (!window.toy && Date.now() - start < timeoutMs) {
      await new Promise((r) => setTimeout(r, 50))
    }
  }
  if (window.toy && forced !== true) {
    toyRef = window.toy
    env = 'sdk'
  } else if (forced === false) {
    throw new Error('[toy-bridge] SDK 未加载且 ?toymock=0 禁止 mock')
  } else {
    toyRef = createMockToy()
    env = 'mock'
    console.info('[toy-bridge] 使用本地 mock（非 B站环境或强制 mock）')
  }
  return env
}

export function toy(): ToySDK.Toy {
  if (!toyRef) throw new Error('[toy-bridge] 先 await initToy()')
  return toyRef
}

export function toyEnv(): ToyEnv {
  return env
}

const supportCache = new Map<Ability, Promise<boolean>>()

/** 能力检测（带缓存）。App 专属能力（share / saveImageToAlbum / 容器控制 / closeBrowser）调用前必查。 */
export function supports(ability: Ability): Promise<boolean> {
  if (!supportCache.has(ability)) {
    supportCache.set(ability, toy().isSupport(ability).catch(() => false))
  }
  return supportCache.get(ability)!
}

// ---------------------------------------------------------------------------
// 错误与退避
// ---------------------------------------------------------------------------

export function isRateLimited(err: unknown): boolean {
  const e = err as { type?: string; code?: number } | null
  return !!e && e.type === 'http_error' && e.code === 307044
}

/** 只对 307044 做指数退避重试；其他错误立即抛出。不要用它包轮询。 */
export async function withBackoff<T>(fn: () => Promise<T>, retries = 3, baseMs = 1000): Promise<T> {
  for (let attempt = 0; ; attempt++) {
    try {
      return await fn()
    } catch (err) {
      if (!isRateLimited(err) || attempt >= retries) throw err
      const delay = baseMs * 2 ** attempt + Math.random() * baseMs
      await new Promise((r) => setTimeout(r, delay))
    }
  }
}

// ---------------------------------------------------------------------------
// 存档：内存为主，关键节点批量落盘
// ---------------------------------------------------------------------------

export interface SaveStore<T extends Record<string, unknown>> {
  /** 当前存档（内存）。游玩中直接读写这里。 */
  readonly data: T
  /** 改内存 + 标脏，不发请求。 */
  set<K extends keyof T>(key: K, value: T[K]): void
  /** 把脏键一次性写云端。在结算、过关、退出前调用；页面隐藏时也会自动调用。 */
  flush(): Promise<void>
  /** 最近一次 flush 是否失败（未登录、限流重试耗尽等），UI 可据此提示「存档未同步」。 */
  readonly lastError: unknown
}

/**
 * 创建存档。每个顶层 key 对应一个云存储 key，值会 JSON 序列化（单值 ≤1024 字节，
 * 单 Toy 最多 128 个 key —— 大对象请自己拆）。云端读失败（未登录等）时退回本地镜像。
 */
export async function createSaveStore<T extends Record<string, unknown>>(defaults: T): Promise<SaveStore<T>> {
  const keys = Object.keys(defaults)
  const localKey = `${LS_PREFIX}save`
  const data = { ...defaults } as T
  let lastError: unknown = null

  const local = safeParse<Partial<T>>(localStorage.getItem(localKey)) ?? {}
  Object.assign(data, local)
  try {
    const remote = await withBackoff(() => toy().getCloudStorage(keys))
    for (const [k, v] of Object.entries(remote)) {
      const parsed = safeParse(v)
      if (parsed !== undefined) (data as Record<string, unknown>)[k] = parsed
    }
  } catch (err) {
    lastError = err // 未登录或限流：先用本地镜像，玩家照样能玩
  }

  const dirty = new Set<string>()
  let inflight: Promise<void> | null = null

  const store: SaveStore<T> = {
    data,
    get lastError() {
      return lastError
    },
    set(key, value) {
      data[key] = value
      dirty.add(key as string)
      try {
        localStorage.setItem(localKey, JSON.stringify(data))
      } catch {
        /* 隐私模式等 */
      }
    },
    async flush() {
      if (inflight) await inflight
      if (dirty.size === 0) return
      const batch: Record<string, string> = {}
      for (const k of dirty) batch[k] = JSON.stringify((data as Record<string, unknown>)[k])
      dirty.clear()
      inflight = withBackoff(() => toy().setCloudStorage(batch))
        .then(() => {
          lastError = null
        })
        .catch((err) => {
          lastError = err
          Object.keys(batch).forEach((k) => dirty.add(k)) // 下次再试
        })
        .finally(() => {
          inflight = null
        })
      await inflight
    },
  }

  const onHide = () => {
    if (document.visibilityState === 'hidden') void store.flush()
  }
  document.addEventListener('visibilitychange', onHide)
  window.addEventListener('pagehide', () => void store.flush())
  return store
}

function safeParse<T = unknown>(raw: string | null | undefined): T | undefined {
  if (raw == null) return undefined
  try {
    return JSON.parse(raw) as T
  } catch {
    return undefined
  }
}

// ---------------------------------------------------------------------------
// 排行榜：结算时提交一次；榜单读一次缓存，刷新交给用户
// ---------------------------------------------------------------------------

const rankCache = new Map<string, Promise<ToySDK.RankItem[]>>()

export function submitScore(score: number, board = 1) {
  return withBackoff(() => toy().submitScore({ board, score: Math.round(score) }))
}

export function getRankList(board = 1, period: ToySDK.RankPeriod = 'all', limit = 50, refresh = false) {
  const key = `${board}:${period}:${limit}`
  if (refresh || !rankCache.has(key)) {
    const p = withBackoff(() => toy().getRankList({ board, period, limit }))
    p.catch(() => rankCache.delete(key))
    rankCache.set(key, p)
  }
  return rankCache.get(key)!
}

// ---------------------------------------------------------------------------
// 容器：监听 + 切换并确认生效
// ---------------------------------------------------------------------------

/** 监听容器状态；不支持时（Web 端 / 旧客户端）用 window resize 合成一个近似状态。返回取消函数。 */
export async function watchContainer(cb: (s: ToySDK.ToyContainerState) => void): Promise<() => void> {
  if (await supports('onContainerChange')) return toy().onContainerChange(cb)
  const emit = () =>
    cb({
      deviceType: 'unknown',
      viewport: { width: innerWidth, height: innerHeight },
      orientation: innerWidth > innerHeight ? 'landscape' : 'portrait',
      immersive: false,
      safeArea: { top: 0, right: 0, bottom: 0, left: 0 },
      changedFields: ['viewport'],
    })
  emit()
  addEventListener('resize', emit)
  return () => removeEventListener('resize', emit)
}

/**
 * 切换横竖屏 / 沉浸，并等到 onContainerChange 报告目标状态才算成功。
 * 返回 false 表示不支持或超时未确认（旧客户端），调用方应走旋转自适应兜底。
 * 手机上横屏请同时 immersive: true。
 */
export async function requestContainerMode(mode: ToySDK.SetContainerModeReq, timeoutMs = 2500): Promise<boolean> {
  if (!(await supports('setContainerMode')) || !(await supports('onContainerChange'))) return false
  return new Promise<boolean>((resolve) => {
    let done = false
    const finish = (ok: boolean) => {
      if (done) return
      done = true
      off()
      clearTimeout(timer)
      resolve(ok)
    }
    const off = toy().onContainerChange((s) => {
      const okOrientation = mode.orientation === undefined || mode.orientation === 'auto' || s.orientation === mode.orientation
      const okImmersive = mode.immersive === undefined || s.immersive === mode.immersive
      if (okOrientation && okImmersive) finish(true)
    })
    const timer = setTimeout(() => finish(false), timeoutMs)
    toy().setContainerMode(mode).catch(() => finish(false))
  })
}

// ---------------------------------------------------------------------------
// 本地 mock：只求「能跑」，行为近似 Web 端（App 专属能力 isSupport=false）
// ---------------------------------------------------------------------------

function createMockToy(): ToySDK.Toy {
  const ls = {
    get: (k: string) => localStorage.getItem(LS_PREFIX + k),
    set: (k: string, v: string) => localStorage.setItem(LS_PREFIX + k, v),
    del: (k: string) => localStorage.removeItem(LS_PREFIX + k),
  }
  const cloud = (): Record<string, string> => safeParse(ls.get('cloud')) ?? {}
  const appOnly = new Set(['saveImageToAlbum', 'share', 'closeBrowser', 'onContainerChange', 'getContainerState', 'setContainerMode'])
  const unsupported = (name: string) => () => Promise.reject(Object.assign(new Error(`[ToySDK] mock: ${name} unsupported`), { type: 'unsupported' }))
  const scores = (board: number): Record<string, number> => safeParse(ls.get(`rank${board}`)) ?? {}

  const mock = {
    isSupport: async (a: string) => !appOnly.has(a),
    navigate: async (req: unknown) => console.info('[toy mock] navigate', req),
    getQrCode: async () => ({ base64: '', url: location.href }),
    getUserProfile: async () => ({ avatar: '', nickname: '本地玩家', toyOpenId: 'mock-open-id' }),
    getAuthorProfile: async () => ({ status: 'ok', data: { nickname: '作者（mock）', follower: 0 } }),
    getAuthorVideos: async () => ({ status: 'ok', items: [] }),
    getAuthorRelation: async () => ({
      status: 'ok',
      data: { isFollowing: false, isAuthor: false, isOldFan: false, hasFanMedal: false, isCharging: false },
    }),
    getVideoUserActions: async () => ({ status: 'ok', items: [] }),
    getCloudStorage: async (keys?: string[]) => {
      const all = cloud()
      if (!keys || keys.length === 0) return all
      return Object.fromEntries(keys.filter((k) => k in all).map((k) => [k, all[k]]))
    },
    setCloudStorage: async (items: Record<string, string>) => ls.set('cloud', JSON.stringify({ ...cloud(), ...items })),
    removeCloudStorage: async (keys: string[]) => {
      const all = cloud()
      keys.forEach((k) => delete all[k])
      ls.set('cloud', JSON.stringify(all))
    },
    getSharedStorage: async () => ({}),
    setSharedStorage: async () => {},
    removeSharedStorage: async () => {},
    submitScore: async ({ board = 1, score }: { board?: number; score: number }) => {
      const s = scores(board)
      s.me = Math.max(s.me ?? -Infinity, score)
      ls.set(`rank${board}`, JSON.stringify(s))
      return { score: s.me }
    },
    getRankList: async ({ board = 1 }: { board?: number } = {}) => {
      const s = scores(board)
      return s.me === undefined ? [] : [{ rank: 1, score: s.me, nickname: '本地玩家', avatar: '' }]
    },
    getMyRank: async ({ board = 1 }: { board?: number } = {}) => {
      const s = scores(board)
      return s.me === undefined ? { ranked: false, rank: 0, score: 0 } : { ranked: true, rank: 1, score: s.me }
    },
    checkInputSafety: async () => ({ status: 'ok', passed: true }),
    requestCamera: (o?: MediaStreamConstraints['video']) => navigator.mediaDevices.getUserMedia({ video: o ?? true }),
    requestMicrophone: () => navigator.mediaDevices.getUserMedia({ audio: true }),
    stopMedia: async (s: MediaStream) => s.getTracks().forEach((t) => t.stop()),
    saveImageToAlbum: unsupported('saveImageToAlbum'),
    share: unsupported('share'),
    closeBrowser: unsupported('closeBrowser'),
    getContainerState: unsupported('getContainerState'),
    setContainerMode: unsupported('setContainerMode'),
    onContainerChange: () => () => {},
  }
  return mock as unknown as ToySDK.Toy
}
