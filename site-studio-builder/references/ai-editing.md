# AI smart editing — selected-component scope + LLM-driven understanding

The Studio's natural-language bar has two layers: a deterministic rule-matcher
(undo/redo/help/`?` only) and a **real LLM** that does the actual free-form
understanding. The key design decision that makes it reliable: **the user first
clicks a component on the canvas, and the AI only ever edits the fields of that
selected component.** The AI never guesses which field across the whole page —
its scope is bounded by the click.

## Architecture — three layers, the hub is never optional

```
中枢 (/api/agent/command 服务端 agent)   ← fixed, always present
   ├─ 默认内置模型   ← 部署者 sets LLM_PROVIDER/API_KEY/BASE_URL once; editors are zero-config
   └─ 可选自接模型   ← 部署者 overrides baseUrl/key; editors still hit the same hub
无 AI 降级            ← if no model is configured, fall back to deterministic rules + a friendly hint
```

- The **hub** is `/api/agent/command` — server-side logic that "receives intent →
  calls the LLM → returns a command". It is a fixed part of the architecture,
  decoupled from *which* model runs underneath.
- The **default model** is configured by the *deployer* (the person running the
  studio), NOT by each editor. Editors just use the hub with zero setup.
- A **local model (Ollama)** is the cheapest default — see "Ollama" below. Any
  OpenAI-compatible endpoint works by changing `LLM_BASE_URL`.

## Selected-component scope (the critical piece)

A flat dotted key like `hospitals.h1.1` carries no semantics the LLM can read, so
the only reliable way to locate "the hero title" is to **feed the LLM the
selected component's field list** (key = current value) and forbid it from
inventing keys.

1. **Track the selection.** Extend `PuckDataBridge` (already mounted via
   `overrides.header`) to read `appState.ui.itemSelector` + `appState.data.content`
   and report the selected block back to the parent:

```ts
interface SelectedBlockField { key: string; value: string; kind: "text" | "image"; }
interface SelectedBlockContext { id: string; fields: SelectedBlockField[]; }
```

   `computeSelectedBlock(itemSelector, content)` resolves the selected item's
   `keys`/`images` into `fields` (key + current value). Register a setter on the
   shared ref so the bridge pushes the selection up to `PuckEditor`, which keeps
   it in `selectedBlock` state and passes it into the command bar.

2. **Submit the scope with the command.** The command bar sends
   `options.selectedBlock` on both dryRun and apply. The backend's
   `buildUserPrompt` injects the field list and the SYSTEM_PROMPT says:
   *`target` 或 `source` 必须从字段清单里选，禁止自造键。*

3. **Unselected fallback.** With no selection, the bar hints "先在画布左侧选中
   组件" and (optionally) degrades to whole-page value matching — but the
   selected-component path is the primary, most reliable flow.

## LLM-driven understanding (not regex)

The deterministic `rule-matcher` is reduced to **action-word short-circuits only**
— `undo`, `redo`, `help`/`?`. Everything else (any phrasing of "change the title",
"this copy is too verbose, tighten it", "translate to Russian") goes to the LLM,
because a regex catalog can never cover free-form natural language. This is the
"真自然语言" property: users say it however they like; the LLM normalizes it.

SYSTEM_PROMPT (DOM mode — see `llm-client.ts` in the proven build):

```
你是一个网站内容编辑助手。用户在画布上选中了一个组件，用户消息里会列出该组件所有可编辑字段（格式：键 = 当前值）。
只支持这些类型：
- update_text: { type, target: "<字段键>", value: "<完整文本>" }
- translate: { type, source: "<字段键>", targetLang: "en"|"zh"|"ru" }
- query: { type, question: "capability" | "style" }
- undo / redo
硬性规则：
1. target/source 必须从字段键中选，禁止自造键。
2. value 是完整文本，不是增量/解释/对话。
3. 措辞随意也能懂，先理解意图再操作。
4. 意图不明确 → query(capability)。
5. 只返回 JSON，不要 markdown。
6. 样式修改（颜色/字体/字号/加粗/斜体/对齐/间距/背景色）超出能力 → query(style)。
```

### Style edits are out of scope — return a targeted refusal

"改字体颜色" is a style operation, which the flat-key content model cannot
express. Without an explicit rule the LLM classifies it as "unclear intent" and
returns the generic capability list — which does **not** answer "can I change
the color?", so the user sees "no reaction". Fix with two pieces:

- SYSTEM_PROMPT rule 6: style changes → `{ type: "query", question: "style" }`.
- `/api/agent/command` query switch adds a `"style"` case returning a concrete
  answer: "样式修改暂不支持：我只能改文本、图片、链接… 如果想改文字请说「把…改成…」".

## Clarification (ambiguous target → let the user pick)

When the LLM can't uniquely identify the target field, it returns
`ClarificationError` with candidate options. The frontend renders them as a
clickable list; picking one resubmits with `options.clarifyKey`, which skips
re-parsing and constructs `update_text(target: clarifyKey, value: extractEditValue(command))`
directly. Never let the AI silently guess when multiple fields match.

## Translation — mirror keys, not lang dictionaries

**The clone's language model is "main site + `/ru` mirror", not split
`translations.zh/ru` dictionaries.** The zh/ru dicts are EMPTY; Russian text
lives in the **en** dict under a `ru__` prefix (the `/ru` routes render with
slug `ru__<page>`, so their keys are `ru__hospitals.h1.1` etc.).

Two fixes required in `plan-generator.ts`:

1. **Translate target** — write the `ru__` key into the en dict, not a
   `/translations/ru/...` path (which fails validation — no such key):
```ts
let targetKey = intent.source;          // "hospitals.h1.1"
let targetLang = intent.targetLang;     // "ru"
if (intent.targetLang === "ru") {
  targetKey = `ru__${intent.source}`;   // "ru__hospitals.h1.1"
  targetLang = "en";
}
const resolved = resolveTarget(targetKey, targetLang);  // /translations/en/ru__hospitals.h1.1
```

2. **Read source with baseline fallback** — an unedited key lives only in the
   baseline module (the UCD stores overrides only), so `readTranslationValue`
   must fall back to `TRANSLATIONS[lang].translation[key]` before returning
   null. Otherwise translating any untouched key fails with "Source key not
   found".

## Ollama (local model, OpenAI-compatible)

`llm-client.ts` uses the OpenAI chat-completions shape, so any OpenAI-compatible
endpoint works. Proven config (`.env.local`):

```
ENABLE_LLM=true
LLM_PROVIDER=openai                 # Ollama speaks OpenAI-compatible /v1
LLM_BASE_URL=http://localhost:11434/v1
LLM_MODEL=qwen2.5:7b
LLM_API_KEY=ollama                  # placeholder; Ollama ignores it
```

- Pull the model first: `ollama pull qwen2.5:7b` (≈4.7 GB). `ollama list` shows
  installed models; `ollama ps` shows loaded ones.
- **`ollama ps` may show an empty list after idle** — that's the default
  `keep_alive` (5 min) unloading the model, NOT a crash. The next request
  reloads it automatically.
- **Drop `response_format: { type: "json_object" }`** — Ollama ignores/errors on
  it. Instead tolerate fenced output: `extractJson()` strips ``` ```json ```
  fences and trailing prose before `JSON.parse`.
- The LLM reply must pass two gates regardless of provider: `validate()`
  (key exists + `/translations/*` only) and a hard "key must be in the injected
  field list" check — so a hallucinated path is rejected.

## Pitfalls — apply & undo correctness (both cost real bugs)

### Bug A — apply re-parsing loses the selected scope

`dryRun` sends `selectedBlock`, so the LLM resolves the right key. But if the
**apply** call re-`POST /api/agent/command` WITHOUT `selectedBlock`, the backend
falls back to the rule matcher and lands on a DIFFERENT key (`hospitals.span.2`
instead of `hospitals.h1.1`) — the preview edits one field, the save edits
another, and undo then reverts the wrong field. Symptom: "the command edit
can't be undone" (it was never applied to the visible field).

**Fix:** apply must **reuse the dry-run's already-resolved operations**, persisted
via `/api/studio/patch`, never re-parse:
```ts
// handleAgentApply
const res = await fetch("/api/studio/patch", {
  method: "POST",
  body: JSON.stringify({ operations: pendingPreview.operations, description: `Agent: ...` }),
});
```
The dry-run has already run parse → plan → domMapOps → validate; applying the
exact same ops guarantees preview === saved.

### Bug B — programmatic `setData` triggers onChange → double save → undo no-op

`pushPuckData` (dispatch `setData`) surfaces as a Puck `onChange`, which hits
`handleChange` → `debouncedSave` → `savePatch`, writing a SECOND, idempotent
version right after the apply. The next Undo reverts that no-op version (its
parent already had the new value, so the inverse is a no-op), so the visible
text never changes back. Symptom: undo succeeds (version +1) but the text
stays.

**Fix:** guard `handleChange` with an `applyingRef` so programmatic pushes during
a command apply never auto-save:
```ts
const applyingRef = useRef(false);
// handleAgentApply: applyingRef.current = true; ... finally { applyingRef.current = false; }
const handleChange = (newPuckData) => {
  if (applyingRef.current) return;   // ignore programmatic setData during apply
  ...
};
```

### dryRun preview must be a diff, not the whole UCD

`validate()` used to return `produce(currentDoc, applyOps)` — the entire UCD
(~800 KB) — in the dryRun response, and the UI never consumed it. Return a
lightweight diff instead:

```ts
export interface PreviewChange { path: string; before: unknown; after: unknown; }
// validator:
preview = operations.map((op) => ({
  path: op.path,
  before: getValueByPointer(currentDoc, op.path),
  after: getValueByPointer(newDoc, op.path),
}));
```
Dry-run response drops from ~800 KB to a few hundred bytes.

## Verification

- Selected block + "把标题改成 X" → `update_text`, `target` = the clicked key.
- "帮助" / "撤销" / "重做" → rule short-circuit (no LLM call).
- "翻译成俄语" → `translate` + op path `/translations/en/ru__<key>`; apply + undo round-trips.
- "把字体改成红色" → `query(question:"style")` + a concrete "样式修改暂不支持" answer.
- Multi-title block + "把标题改成 X" → clarification with candidates; picking one targets that exact key.
- apply produces exactly ONE version (no `studio canvas edit` duplicate); undo restores the text.
- dryRun response size is a few hundred bytes, not ~800 KB.
