# AI Workflow Builder — Glaze drop-in pack

Drop these files into your Glaze project (`sources/`). Paths match the locked architecture.

## Layout

```
main/handlers/workflow.ts          NEW
main/handlers/index.ts             PATCH (see snippet at bottom of that file)
renderer/main/home-view.tsx        REPLACE
renderer/main/workflow/types.ts    NEW
renderer/main/workflow/templates.ts NEW
renderer/main/workflow/use-workflow-store.ts
renderer/main/workflow/use-workflow-run.ts
renderer/main/workflow/node-card.tsx
renderer/main/workflow/connections-layer.tsx
renderer/main/workflow/canvas.tsx
renderer/main/workflow/node-palette.tsx
renderer/main/workflow/workflow-sidebar.tsx
renderer/main/workflow/builder-view.tsx
```

## package.json

Ensure this exact capability block (grades must match what AI/Extract/Branch pass):

```json
"glaze": {
  "capabilities": {
    "ai": {
      "grades": ["fast", "smart", "powerful"],
      "purpose": "Runs your AI workflow steps — chaining, branching, and extracting data across each step.",
      "mode": "required"
    }
  }
}
```

## Assumptions

- `useGlazeAI()` is already available in the renderer. Do not import `@glaze/core/ai`.
- Preload already exposes `glaze.ipc.stream` / `cancelStream` and `window.glazeAPI.glaze.ipc.invoke`.
- `@glaze/core` exports `Button`, `Card`, `Panel`, `Select`, `Toolbar`, `TextArea`, `Input`, `Badge`. If a name differs, map it in `builder-view.tsx` only.
- File picker uses `workflow:openFileDialog` (registered in the handler).
- Web/File content is untrusted. Never execute it.

## Verify (no live AI)

1. Add Input → Template → Output, wire them, Run. Template should resolve without AI.
2. Add Web + File nodes, fetch/read, confirm text lands on Output.
3. Add Branch with two labels, wire both ports, confirm only one path is marked reachable after a mock label.
4. Save, reload, confirm nodes/wires/viewport restore.
5. Hit Run on an AI node yourself — consent prompt is owned by `useGlazeAI`.
