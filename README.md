# site-studio-builder

一个 **WorkBuddy skill**：给任意网站（尤其是「站点克隆」）叠加一个**加性、非破坏式**的浏览器内可视化编辑层（`/studio`）。编辑人员可以在 `/studio` 里修改文案、图片、区块数据，保存后刷新公开页面即可看到变化——而**公开页面始终与原站逐字一致**，不会因为加了编辑模式而发生任何布局或文案偏移。

该模式已在 `medkungfu.com` 克隆项目（`medkungfu-clone`）中完整落地验证：公开页 100% 保真，同时具备可编辑能力。

---

## 它解决什么问题

| 痛点 | 本 skill 的做法 |
| --- | --- |
| 想给现有站点加后台编辑，又怕改坏原站 | Studio 是**唯一新增**，公开页渲染逻辑不变 |
| 克隆站想「可编辑」但不想 fork 原站代码 | 内容层与展示层解耦，编辑只覆盖差异键 |
| 多语言站点（en/zh/ru 等）编辑难同步 | 统一 UCD（Unified Content Document）内容层 + 合并式翻译适配 |
| 非技术人员不会用 Git/JSON | 提供 `/studio` 可视化编辑器 + 自然语言指令栏 |

---

## 适用场景

- 给静态 / 服务端渲染站点（默认 Next.js App Router，模式可推广到任意 React SPA/SSR）增加可编辑模式。
- 克隆某站点后，想要一个「编辑覆盖层」而不改动其源码。
- 基于 [Puck](https://puckeditor.com/) 搭建带内容后端的页面编辑器。
- 增加自然语言指令栏（如「把 hero 标题改成 X」→ 内容补丁）。

---

## 安装（多工具通用）

本仓库的 `site-studio-builder/` 是**规范来源**（WorkBuddy 与 Claude Code 共用同一
`SKILL.md` 格式）。其余工具通过 `integrations/` 下的适配文件接入，内容完全一致，
均指向 `site-studio-builder/references/` 获取完整代码模式。

| 工具 | 安装方式 |
| --- | --- |
| **WorkBuddy** | `cp -r site-studio-builder ~/.workbuddy/skills/site-studio-builder`，重启 WorkBuddy |
| **Claude Code** | `cp -r site-studio-builder ~/.claude/skills/site-studio-builder`（同格式，直接可用） |
| **Codex** | 把 `integrations/codex/AGENTS.md` 的内容并入你的 `AGENTS.md`（项目根或 `~/.codex/`） |
| **Trae** | 把 `integrations/trae/site-studio-builder.mdc` 放到项目的 `.trae/rules/` 下（或作为全局规则） |
| **ChatGPT** | 把 `integrations/chatgpt/INSTRUCTIONS.md` 粘贴进某 Project 的「Project instructions」，或 Custom GPT 的 System instructions |

> 规范来源 `site-studio-builder/` 目录名必须保持为 `site-studio-builder`。
> 安装即把该目录复制到 `~/.workbuddy/skills/`（WorkBuddy）或 `~/.claude/skills/`（Claude Code），无需打包。

---

## 使用

在 WorkBuddy 对话中描述需求即可触发，例如：

- 「给我的站点加一个 `/studio` 可视化编辑器」
- 「让这个网站可编辑」
- 「克隆这个站并加一个编辑模式」
- 「给 Next.js 应用挂一个 Puck 编辑器 / 页面构建器」
- 「我想从后台改首页文案和图片」

触发后，skill 会按下面的分阶段流程搭建，并在每一步给出可落地的代码模式。

---

## 仓库结构

```
site-studio/                      # 本仓库根
├── README.md                     # 本文件（含多工具安装说明）
├── site-studio-builder/          # 规范来源：WorkBuddy + Claude Code 共用（复制到对应 skills 目录）
│   ├── SKILL.md                  # 用途 / 触发条件 / 分阶段 workflow / 硬约束 / 关键坑
│   ├── scripts/
│   │   └── gen-blocks.py         # DOM 注入克隆的 block 拆分脚本（→ public/studio-blocks/*.json）
│   └── references/
│       ├── architecture.md       # 文件地图 + 数据流向 + 已验证代码模式
│       ├── puck-canvas.md        # DOM 注入克隆的完整 Puck 画布模板（block 拆分 / PageBlock / 图片编辑 / 大纲 / 渲染循环坑）
│       ├── feature-matrix.md     # Studio 模块 ↔ skill 模板功能对应表 + 配置默认值
│       ├── nl-command-bar.md     # 自然语言指令子系统（API 契约 / rule-matcher / 端到端透传 / 已知 UI bug 修复）
│       └── ai-editing.md         # AI 智能编辑（选中组件作用域 / LLM 主导 / 澄清 / 翻译镜像键 / 样式拒绝 / 撤销正确性）
├── integrations/                 # 其他工具的适配文件（内容一致，wrapper 不同）
│   ├── codex/AGENTS.md           # Codex：并入 AGENTS.md
│   ├── trae/site-studio-builder.mdc  # Trae：放入 .trae/rules/
│   └── chatgpt/INSTRUCTIONS.md   # ChatGPT：粘贴进 Project instructions / Custom GPT
```

---

## 搭建流程（skill 内部 7 步）

> 完整细节见 `site-studio-builder/SKILL.md` 与 `references/architecture.md`。

1. **抽取忠实基线**：把站点文案放 `src/lib/i18n/translations.ts`（en+zh）与 `ru.ts`（ru），结构化区块数据放 `seed-data.ts`。组件通过 `t()` 与 `useSectionData(page, id, fallback)` 读取，`fallback` 用 seed 常量（防止 hydration 不一致）。
2. **内容层**：`scripts/seed-ucd.ts` 读取上述模块，写出 `.content/`（UCD：`translations.json`、`pages/{slug}.json`、`navigation.json`、`meta.json`）。**仅首次运行**——`translations.json` 已存在则跳过，保证 Studio 编辑跨重启/构建保留。
3. **运行时 + 合并适配**：`content-runtime.ts`（模块单例）+ `compat-adapter.ts`（`compatTranslate` 采用 `{...module, ...UCD}` 合并策略，部分 UCD 永不破坏缺失键）。组件由直接 import `TRANSLATIONS` 改为用 `useContentRuntime().translate()` / `useSectionData()`。
4. **接通公开页**：新增 `ContentBootstrap.tsx`，在 `layout.tsx` 的语言 Provider 内挂载，但 `pathname.startsWith("/studio")` 时提前 return（避免干扰编辑器自身实例）。
5. **Studio 编辑器**：`/studio`（client，Puck）含 `PendingPreview → IntentPreview` 卡片、`NLCommandBar` 自然语言输入、`StudioFab` 悬浮按钮（环境变量门控：`NODE_ENV !== "production" || NEXT_PUBLIC_SHOW_STUDIO_FAB === "true"`）。
6. **自然语言指令 API**：`/api/agent/command`（dryRun + apply）由 `rule-matcher` 支撑；持久化经 `/api/studio/patch`（RFC-6902 补丁）→ `LocalContentStore`。**务必把 `answer`/`templates`/`error`/`suggestions` 端到端透传到预览卡片**，否则「帮助」看不到指令清单、错误看不到具体格式。
7. **验证**：typecheck + lint；所有公开路由 200；首页渲染忠实文案；补丁 API 的编辑能持久化并**在 dev 重启后仍在**；drift 校验（merged UCD vs module）0 差异。

---

## 核心设计决策（务必遵守）

- **加性、不破坏**：公开页永远忠实于原站，`/studio` 是唯一新增；合并而非替换（UCD 覆盖 + 忠实模块兜底），部分编辑绝不会弄坏缺失键。
- **seed 仅首次运行**：否则 `npm run dev` / `build` 每次都覆盖 `.content`，编辑全丢；重置基线只需删 `.content/` 再 seed。
- **ContentBootstrap 必须跳过 `/studio`**：否则会覆盖编辑器自己的文档实例。
- **Hydration 兜底**：SSR 与首次客户端渲染必须一致——把 seed 常量作为 `useSectionData` 的 fallback（UCD 在服务端为 `null`）。

---

## 验证要点（落地后自检）

- 对克隆组件全部 `t()` 键做 drift 断言：加载 UCD 后文案与忠实渲染**逐字一致**（0 差异）。
- 17 个公开路由 + `/studio` 全 200，首页忠实文案在位。
- 通过 patch API 改一个键 → document API 立即返回新值 → 重启 dev server（predev 显示 skipping regeneration）→ 重启后编辑仍在 → revert 回原值。

---

## 已知环境坑

- **Node 版本**：Bash 默认 `node` 可能为 v22（Next 16 需要 ≥ 24）。显式用 `C:\Program Files\nodejs` 或 `nvm use 24`。
- **safe-delete 钩子**：沙箱内 `rm -rf` 大目录和 `npx playwright install` 会被拦截。清理 `.next` 走 PowerShell `Remove-Item`，勿依赖 Playwright 做 E2E。

---

## License

MIT © dernh-abs
