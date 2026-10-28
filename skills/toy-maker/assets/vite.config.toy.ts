// vite.config.ts —— B站 Toy 构建模板（toy-maker skill）
// 目标：相对路径、入口 index.html 远小于 1MB、文件名带 contenthash、依赖单独成 chunk 便于平台跨版本复用缓存。
import { defineConfig } from 'vite'

export default defineConfig({
  base: './', // 必须：Toy 跑在 /toy/<slug>/ 子路径下，绝对路径会白屏
  build: {
    outDir: 'dist', // 上传这个目录（或把它打成 zip），不要传源码
    target: 'es2019', // 照顾较老的 App WebView
    assetsInlineLimit: 4096, // 别把大图内联进 JS/HTML
    modulePreload: { polyfill: false },
    rollupOptions: {
      output: {
        // Vite 默认已带 [hash]；显式写出来，避免被改坏
        entryFileNames: 'assets/[name]-[hash].js',
        chunkFileNames: 'assets/[name]-[hash].js',
        assetFileNames: 'assets/[name]-[hash][extname]',
        manualChunks(id) {
          if (id.includes('node_modules')) return 'vendor'
        },
      },
    },
  },
})

// 注意：
// - 不要用 vite-plugin-singlefile 产出要上传的入口（入口 index.html 解压后 >1MB 会被拒）。
// - 大块 JSON 数据放 public/data/*.json 或 import 成独立 chunk，运行时 fetch('./data/xx.json')。
// - 路由用 hash 模式（createWebHashHistory / HashRouter）。
// - index.html 的 <head> 里保留 SDK：<script src="//s1.hdslb.com/bfs/seed/toy/app/sdk/toy-sdk.js"></script>
// - 若真机上 module 脚本加载异常，可尝试在构建后去掉 dist/index.html 里 <script>/<link> 的 crossorigin 属性
//   （例：sed -i '' 's/ crossorigin//g' dist/index.html），这是实践中的兜底，不是官方要求。
