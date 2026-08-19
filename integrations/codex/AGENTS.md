# Site Studio Builder — Agent Instructions (Codex-optimized)

> Codex-optimized variant of the `site-studio-builder` skill. This file is
> **self-contained**: it inlines the verified code patterns and the full
> pitfall list so Codex does not depend on any external `references/` folder.
> Merge this into your project `AGENTS.md` (root or `~/.codex/`).

Use these instructions to add an **additive, non-destructive in-browser visual
editor** (a "Studio", served at route `/studio`) on top of an existing website —
most usefully when the site is a clone of another site. The public pages keep
rendering exactly as before; `/studio` lets editors change text / images /
section data, and those edits persist and appear on the public pages after
reload.

Proven on a `medkungfu.com` clone (Next.js 16 + React 19 + Puck 0.20): public
pages stayed byte-for-byte faithful while a studio editing mode was layered on.

---

## Hard constraint — clone fidelity

The public pages **MUST remain byte-for-byte faithful** to the original site.
Studio is the **only** addition. Never overwrite clone copy/layout with
editor-authored defaults. Enforce with a merge adapter: the original
dictionaries are the **base**; Studio edits only **override** specific keys.

---

## Codex operating notes (read first)

- **Node ≥ 24 is mandatory** (Next 16 needs it). A managed `node` v22 is too
  old. Before any `npm`/`next` command, assert the version:
  ```bash
  node -v   # must be >= 24; if not, run: nvm use 24   (or use the system Node 24 path)
  ```
- **Autonomous defaults — do NOT ask the user.** When a choice is unspecified,
  pick the default and proceed; mention the assumption in your final summary:
  - Baseline shape: **component-rebuilt** unless the user explicitly says the
    site is a DOM-injection clone.
  - Language provider: assume en + zh (+ ru mirror) as in the proven build.
  - LLM: leave disabled (deterministic rules only) unless the user supplies an
    endpoint; editors still use the command bar.
- **Headless verification only.** Codex has no browser. Verify with `curl` and
  a node script (see "Verify" below), not by opening `/studio` visually.
- **Sandbox file ops.** `rm -rf` on a large dir and `npx playwright install`
  are blocked. Clear `.next` via PowerShell `Remove-Item`, not `rm -rf`. Do not
  rely on Playwright for E2E here.
- **Seed is first-run-only.** Never regenerate `.content/` if it exists — that
  wipes Studio edits.

---

## Workflow

**1. Extract a faithful baseline into modules.** Put site copy in
`src/lib/i18n/translations.ts` (en+zh) and `ru.ts` (ru), plus `seed-data.ts`
for structured section data (hero image, ctaLinks, statKeys…). Components read
via `t()` and `useSectionData(page, id, fallback)`, where `fallback` is the seed
constant (prevents hydration mismatch because the content doc is `null` on the
server).

**2. Build the content layer.** Create `scripts/seed-ucd.ts` that reads those
modules and writes `.content/`: `translations.json` (en/zh/ru),
`pages/{slug}.json` (section data), `navigation.json`, `meta.json`. **First-run
only** — if `translations.json` already exists, skip regeneration so Studio
edits survive restarts/builds. Wire via `predev`/`prebuild` npm hooks
(`"seed": "tsx scripts/seed-ucd.ts"`). Add `.content/`, `versions/` to `.gitignore`.

**3. Runtime + compat adapter.** Add `content-runtime.ts` (module singleton
holding the in-memory UCD) and `compat-adapter.ts` (`compatTranslate` that
**MERGES** the UCD over the hardcoded baseline: `{...module, ...UCD}`).
Components switch from importing `TRANSLATIONS` directly to
`useContentRuntime().translate()` / `useSectionData()`. A partial doc can never
break rendering.

**4. Reconnect to public pages.** Add `ContentBootstrap.tsx` and mount it in
`layout.tsx` inside the language provider, but `return` early when
`pathname.startsWith("/studio")` (so it doesn't clobber the editor's own
document instance).

**5. Studio editor.** Scaffold `/studio` (client) with Puck: a
`PendingPreview` → `IntentPreview` card showing the parsed intent/operations, an
`NLCommandBar` for natural-language input, and a `StudioFab` floating button
(env-gated: show in dev or when `NEXT_PUBLIC_SHOW_STUDIO_FAB === "true"`).

**6. NL command API.** Add `/api/agent/command` (dryRun + apply) backed by a
`rule-matcher`; persist via `/api/studio/patch` (RFC-6902 ops) →
`LocalContentStore`. **Carry `answer` / `templates` / `error` / `suggestions`
end-to-end** to the preview so "help" shows the command list and failures show
concrete formats.

**7. Verify (headless).** Typecheck + lint; all public routes + `/studio` return
200 (`curl -s -o /dev/null -w "%{http_code}"`); home renders faithful copy
(compare a known hero string via `curl`); a patch-API edit persists and
**survives a dev restart**; drift check (merged doc vs module) shows 0
differences. See "Verify" for the scripted form.

---

## Verified code patterns (inline — do NOT look for external files)

### A. ContentRuntime — module singleton
```ts
// src/lib/executor/content-runtime.ts
import { compatTranslate } from "@/lib/content/compat-adapter";
import { subscribe, notifySubscribers } from "./notify";

let doc: UnifiedContentDocument | null = null;
let snapshotVersion = 0;

export function getDocument(): UnifiedContentDocument | null { return doc; }
export function translate(lang: SupportedLanguage, key: string): string {
  const translations = doc?.translations ?? null;
  return compatTranslate(lang, translations, key);
}
export function getSectionData(page: string, sectionId: string): unknown {
  const pageData = doc?.pages?.[page as keyof typeof doc.pages];
  if (!pageData) return null;
  return (pageData as { sections?: Record<string, unknown> }).sections?.[sectionId] ?? null;
}
export function subscribeRuntime(listener: () => void): () => void { return subscribe(listener); }
export function getSnapshot(): number { return snapshotVersion; }
export function commitDocument(next: UnifiedContentDocument | null): void {
  doc = next; snapshotVersion++; notifySubscribers();
}
```

### B. compat-adapter — MERGE policy (the safety net)
```ts
// src/lib/content/compat-adapter.ts
export function compatTranslate(lang, translations, key): string {
  const moduleEn = (TRANSLATIONS.en?.translation as Record<string, unknown>) ?? {};
  const enDict = translations?.en ? { ...moduleEn, ...translations.en } : moduleEn;
  const enText = lookup(enDict, key) ?? resolve(enDict, key) ?? key;
  if (lang === "ru") {
    const ruMap = translations?.ru ? { ...RU, ...translations.ru } : RU;
    const v = ruMap[enText];
    return typeof v === "string" ? v : enText;
  }
  const moduleLang = (TRANSLATIONS[lang]?.translation as Record<string, unknown>) ?? {};
  const dict = translations?.[lang] ? { ...moduleLang, ...translations[lang] } : moduleLang;
  if (dict) {
    const direct = lookup(dict, key);
    if (direct !== undefined) return direct;
    const nested = resolve(dict, key);
    if (nested !== undefined) return nested;
  }
  return enText;
}
```

### C. ContentBootstrap — reconnect edits, skip /studio
```tsx
// src/components/ContentBootstrap.tsx  ("use client")
import { useEffect } from "react";
import { usePathname } from "next/navigation";
import { commitDocument } from "@/lib/executor/content-runtime";

export function ContentBootstrap() {
  const pathname = usePathname();
  useEffect(() => {
    if (pathname?.startsWith("/studio")) return;   // never clobber the editor's doc
    let cancelled = false;
    fetch("/api/studio/document")
      .then((res) => (res.ok ? res.json() : null))
      .then((data) => {
        if (cancelled || !data?.success || !data.document) return;
        commitDocument(data.document);
      })
      .catch(() => { /* fall back to faithful baseline (doc stays null) */ });
    return () => { cancelled = true; };
  }, [pathname]);
  return null;
}
```

### D. seed-ucd.ts — first-run-only guard
```ts
const CONTENT_DIR = path.join(process.cwd(), ".content");
if (fsSync.existsSync(path.join(CONTENT_DIR, "translations.json"))) {
  console.log("[seed-ucd] .content/ already exists — skipping to preserve edits.");
  return;
}
// ... write translations.json, pages/*.json, navigation.json, meta.json ...
```

### E. useSectionData — SSR-safe fallback (no hydration mismatch)
```ts
// src/lib/executor/use-content-runtime.ts
export function useSectionData<T>(page: string, sectionId: string, fallback: T): T {
  useSyncExternalStore(subscribeRuntime, getSnapshot, getSnapshot);
  const data = getSectionData(page, sectionId);
  return (data as T | null) ?? fallback;   // doc is null on server -> seed fallback
}
```

### F. mtime-validated content cache (Next 16 cross-instance fix)
Next 16 compiles Route Handlers and page rendering into **separate module
instances**; an in-memory cache invalidated by the patch API is invisible to the
page side. Validate by file mtime on every read:
```ts
const cache = new Map<string, { mtimeMs: number; data: unknown }>();
async function readJsonFile<T>(rel: string): Promise<T | null> {
  const abs = path.join(process.cwd(), CONTENT_DIR, rel);
  const st = await fs.stat(abs);
  const hit = cache.get(rel);
  if (hit && hit.mtimeMs === st.mtimeMs) return hit.data as T;
  const parsed = JSON.parse(await fs.readFile(abs, "utf-8")) as T;
  cache.set(rel, { mtimeMs: st.mtimeMs, data: parsed });
  return parsed;
}
```

### G. Developer gate — bound across button, routes, AND API
Hiding the button is NOT a gate: `/studio` URLs and `POST /api/studio/patch`
are public back doors. One shared gate, applied in all three places:
```ts
// src/lib/studio/developer-gate.ts
import { headers } from "next/headers";
export async function isDeveloperRequest(): Promise<boolean> {
  const h = await headers();
  const host = h.get("host") ?? "";
  if (!/^(localhost|127\.0\.0\.1|\[::1\])(:\d+)?$/.test(host)) return false; // hard gate: loopback only
  if (process.env.NODE_ENV !== "production") return true;                    // soft gate: dev
  return process.env.NEXT_PUBLIC_SHOW_STUDIO_FAB === "true";                 // soft gate: flag build
}
```
Apply in: (1) layout `<StudioFab show={await isDeveloperRequest()} />`, (2)
`/studio/page.tsx` & `/studio/[page]/page.tsx` → `if (!(await isDeveloperRequest())) notFound();`,
(3) every `/api/studio/*` handler → `if (!(await isDeveloperRequest())) return NextResponse.json({ success:false, error:"Not found" }, { status: 404 });`.
Verified matrix: loopback+dev/flag → button+200+API; public host → hidden+404 everywhere.

---

## Critical pitfalls (ALL of them — these break autonomous builds)

- **Node version.** Use Node ≥ 24 explicitly (`node -v`; `nvm use 24`).
- **Seed must be first-run-only.** Guard on `translations.json` existence; tell
  users to delete `.content/` to reset. Otherwise every restart/build wipes edits.
- **Merge, don't replace.** `compatTranslate` must be `{...module, ...UCD}`;
  replacing with the UCD breaks any key the UCD does not cover.
- **ContentBootstrap must skip `/studio`** or it clobbers the editor's own doc.
- **Hydration.** SSR and first client render must be identical — pass the
  seed-data constant as the `useSectionData` fallback (UCD is `null` on server).
- **Next 16 module-instance isolation — "edit saved but page unchanged".**
  Route Handlers and page rendering are separate module instances; a pure
  in-memory cache invalidated by the patch API is invisible to the page. Fix:
  validate the content cache by file **mtime** on every read (pattern F).
- **Editable pages must be dynamic.** Add `export const dynamic = "force-dynamic"`
  to every page the Studio edits, or it is statically prerendered and never
  re-renders after an edit.
- **Interactivity vs editing: per-page, not global** (DOM-injected clones). The
  original bundle's `createRoot()` wipes edited HTML, but only where it runs. Use
  `InteractiveTier` + `has-page-edits`: pages with NO edits inject the bundle
  (full interactivity), pages WITH edits return null (static + overrides win).
  Valid only under plain-`<a>` full-page navigation.
- **New components: styles in your own globals.css, not clone Tailwind classes.**
  `cloned-site.css` is compiled Tailwind with only the original site's utilities.
  New-component classes (`.fixed bottom-6 right-6 z-[9999]`) won't compile →
  `position: fixed` keeps in-flow position → element lands thousands of px below
  the viewport (invisible). Define a plain `.studio-fab` class in your
  `globals.css`. Verify with `getBoundingClientRect()` inside the viewport.
- **Developer gate must cover ALL three entry points** (pattern G). Hiding the
  button is not enough — direct `/studio` URL and `POST /api/studio/patch` are
  public back doors. Bind all three; verify the matrix.
- **Puck render loop → "This page couldn't load".** Three things compound:
  `usePuck()` with **no selector** (subscribes whole store), **inline
  `viewports`/`overrides` literals** (new identity each render → Puck remounts
  subtree), and `setSelectedBlock` passing a **fresh object** each call. Fix all
  three: `createUsePuck()` narrow selectors, `useMemo(..., [])` the viewports/
  overrides, and serialize-compare before `setSelectedBlock`.
- **NL apply must reuse the dry-run ops, never re-parse.** The dry-run sends
  `selectedBlock`, so the LLM resolves the right key; re-`POST /api/agent/command`
  without it falls back to the rule matcher and lands on a DIFFERENT key. Persist
  the exact dry-run ops via `/api/studio/patch`.
- **Programmatic `setData` triggers onChange → double save → undo no-op.** Guard
  `handleChange` with an `applyingRef` that returns early while a command apply is
  in flight.
- **Translate writes mirror keys, not lang dictionaries.** The clone's zh/ru
  dicts are empty; Russian lives in the **en** dict under `ru__` prefixes
  (`ru__hospitals.h1.1`). Translating to ru writes `ru__<key>` into the en dict;
  `readTranslationValue` must fall back to the baseline module.
- **Style edits (color/font/weight…) need a targeted refusal.** Add a
  SYSTEM_PROMPT rule → `query(question:"style")` and a concrete "样式修改暂不支持"
  answer, or the LLM returns the generic capability list and feels like "no reaction".
- **dry-run preview must be a diff.** Return `PreviewChange[] { path, before, after }`
  (a few hundred bytes), not the whole ~800KB UCD.
- **Block splitting must re-inject fixed-header clearance** (DOM-injected clones).
  Carry an `inherited_pt` offset through `gen-blocks.py` recursion and
  `inject_padding_top` it back onto emitted blocks, or the canvas' fixed header
  covers the top of the first main block.

---

## Verify (headless, Codex-safe)

```bash
# 1. typecheck + lint
npx tsc --noEmit && npx eslint .

# 2. routes 200 (loopback so the dev gate passes)
for r in / /studio /api/studio/document; do
  echo "$r -> $(curl -s -o /dev/null -w '%{http_code}' http://localhost:3000$r)"
done

# 3. patch persists + survives restart
curl -s -X POST http://localhost:3000/api/studio/patch \
  -H 'content-type: application/json' \
  -d '{"operations":[{"op":"replace","path":"/translations/en/nav.home","value":"新首页"}]}'
curl -s http://localhost:3000/api/studio/document | grep -o '"新首页"'   # expect a hit

# 4. drift check (merged UCD vs module = 0 differences) — run as a node one-liner
#    for every t(key) the public components call, assert merged(key) === moduleOnly(key)
```

In the proven build the drift check passed for all 73 sampled keys; home rendered
the exact original hero string; a patch edit survived a `npm run dev` restart
(seed skipped regeneration).

---

## Reference

This Codex variant is self-contained. If you need the DOM-injected Puck canvas
template (block splitting, `puck-adapter`/`PageBlock`, image editing, custom
outline, render-loop fix details) or the full AI-editing layer (selected-component
scope, LLM wiring, clarification, translation mirror keys), copy the upstream
`site-studio-builder/references/{architecture,puck-canvas,nl-command-bar,ai-editing}.md`
into the project and read them — but everything required to build the standard
(component-rebuilt) studio is already inlined above.
