# Natural-Language Command Bar — Studio subsystem

The NL command bar lets editors type instructions ("把 hero 标题改成 X",
"帮助", garbage) instead of using the Puck UI directly. It maps free text to a
content patch and shows a preview before applying. This subsystem is optional
but highly recommended — it is what makes the studio usable by non-technical
editors.

## API contract — `/api/agent/command`

Request body:
```json
{ "command": "帮助", "options": { "dryRun": true, "page": "home" } }
```

Response fields (carry **all** of them to the UI):
| Field | When present | Meaning |
|-------|--------------|---------|
| `success` | always | `true` if parsed into an intent/operations. |
| `intent` | success | structured intent (`{ question?, ... }`). |
| `operations` | success | RFC-6902 patch ops to apply. |
| `preview` | success | optional preview payload. |
| `answer` | `query/capability` (the "帮助" intent) | human-readable capability list (the command catalog). |
| `templates` | `query/capability` **and** parse failures | `string[]` of example instructions — **click-to-copy**. |
| `error` | failure | human-readable reason the parse failed. |
| `stage` / `message` | failure | where/why it failed. |

Two routes: `dryRun: true` returns the parsed plan without writing; the apply
call (without `dryRun`) persists via `/api/studio/patch` → `LocalContentStore`.

## rule-matcher — `src/lib/agent/rule-matcher.ts`

Maps NL text → a rule. Key rule used here: `query.help` (input "帮助" / "help"
/ "指令") resolves to the **capability** branch, which returns `answer` (the
full capability/command catalog) **and** `templates` (the example instructions,
13 in the proven build). Any unparseable input falls through to a parse-failure
response that still includes `templates` (so the user sees valid examples).

> The rule catalog and the `templates` list live in the rule-matcher / a
> command registry. Keep them in one place so "帮助" and the failure list never
> drift apart.

## End-to-end carry-through (the part that breaks)

The backend is correct: it returns `answer` + `templates` on both the help
intent and parse failures. The bugs are always on the **front-end dropping
fields**. Enforce this chain:

```
/api/agent/command
   └─ useAgentCommand (hook)        → keep data.answer + data.templates in the preview object
        └─ NLCommandBar.handleExecute → on failure, pass { intent:null, operations:[], command, error, suggestions }
             └─ PuckEditor.handleAgentPreview → DO NOT reset error/suggestions; merge pv fields through
                  └─ IntentPreview → render answer (whitespace-pre-line) + templates block on BOTH paths
```

### Bug 1 — "帮助" shows nothing

**Symptom:** typing "帮助" returns success but the preview card is empty / only
says "查询操作，无需补丁执行".

**Root cause:** `useAgentCommand` success path set `suggestions: []` and never
carried `data.answer`/`data.templates` into the preview payload.

**Fix:** in `useAgentCommand`, on success set
```ts
preview: {
  intent: data.intent,
  operations: data.operations ?? [],
  preview: data.preview,
  command,
  answer: data.answer,          // <-- carry through
  suggestions: data.templates ?? [],   // <-- carry through
},
```

### Bug 2 — parse error shows no concrete formats

**Symptom:** a bad command shows "请尝试以下格式：" with no actual formats.

**Root cause:** `NLCommandBar.handleExecute` on failure passed only
`{ intent: null, operations: [], command }`; and `PuckEditor.handleAgentPreview`
unconditionally did `setPreviewError(null); setPreviewSuggestions([])`.

**Fix:** pass the error + suggestions from the failure response:
```tsx
// NLCommandBar.handleExecute
if (resp && resp.success === false) {
  onPreview({ intent: null, operations: [], command, error: resp.error, suggestions: resp.templates });
}
```
```tsx
// PuckEditor.handleAgentPreview — stop resetting:
const handleAgentPreview = useCallback((pv: PendingPreview) => {
  setPendingPreview(pv);
  // do NOT clear error/suggestions here
}, []);
```

### IntentPreview rendering

Render `answer` (preserve line breaks with `whitespace-pre-line`) and a
click-to-copy `templates` list on **both** the help (success) and failure paths:
```tsx
{answer && (
  <pre className="whitespace-pre-line text-sm text-gray-800">{answer}</pre>
)}
{suggestions?.length > 0 && (
  <ul>
    {suggestions.map((t) => (
      <li key={t}>
        <button onClick={() => copyTemplate(t)} title={`点击复制：${t}`}>
          <span className="font-mono">{t}</span>
        </button>
      </li>
    ))}
  </ul>
)}
```

### DOM-injected clone: dom-ops-mapper + 1:1 path resolution

On a DOM-injected clone, the plan generator still emits component-rebuild
paths (`/pages/index/sections/hero/title`, `/translations/en/nav.about`), but
content lives in flat dotted keys (`translations.en["index.span.2"]`). Two
pieces reconcile them — the second is the one that caused a real bug:

1. **`dom-ops-mapper.ts`** — rewrites ops to flat keys **before** validation.
   Resolution order (most-specific first):
   - `base[key] !== undefined` → keep the key literal (1:1; the key shown in
     the right panel). This is the critical case: `hospitals.a.4` must land on
     `hospitals.a.4`, never a semantic fallback.
   - `nav.*` → the header block key whose baseline value contains the tail word.
   - `<section>.<field>` → the block's longest text key (heading/body approx).
   - Last resort → header nav fallback.
2. **`path-resolver.ts` `isRealFlatKey(t)`** — returns true when `t` is a real
   flat baseline key. If true, resolve 1:1 with **dots kept literal**. Never
   convert dots to `/` (JSON-pointer path) — that was the bug: `hospitals.a.4`
   was rewritten to `hospitals/a/4` and fell through to the nav fallback,
   so a command targeting `hospitals.a.4` edited a different key.

Both run in `/api/agent/command` **before** `validate()` so the validator sees
already-mapped flat-key ops.

## Verification

- `POST /api/agent/command` with `"帮助"` → `answer` non-empty, `templates.length === 13`.
- `POST` with garbage → `success === false`, `error` non-empty, `templates.length === 13`.
- In the UI: "帮助" shows the catalog + copyable examples; a bad command shows
  the error text **and** the same example list.
