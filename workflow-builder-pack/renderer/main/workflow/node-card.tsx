import { useRef } from "react";
import { NODE_SIZE, type Grade, type NodeRunResult, type WorkflowNode } from "./types";

type Props = {
  node: WorkflowNode;
  selected: boolean;
  result?: NodeRunResult;
  zoom: number;
  onMove: (x: number, y: number) => void;
  onSelect: () => void;
  onChange: (node: WorkflowNode) => void;
  onDelete: () => void;
  onPortDown: (side: "in" | "out", port?: string, e?: React.PointerEvent) => void;
  onPickFile: () => void;
};

const GRADES: Grade[] = ["fast", "smart", "powerful"];

export function NodeCard({
  node,
  selected,
  result,
  zoom,
  onMove,
  onSelect,
  onChange,
  onDelete,
  onPortDown,
  onPickFile,
}: Props) {
  const drag = useRef<{ x: number; y: number; nx: number; ny: number } | null>(null);
  const labels = node.type === "branch" ? node.data.labels ?? ["yes", "no"] : ["out"];

  const patchData = (data: Partial<WorkflowNode["data"]>) =>
    onChange({ ...node, data: { ...node.data, ...data } });

  return (
    <div
      style={{
        position: "absolute",
        left: node.x,
        top: node.y,
        width: NODE_SIZE.w,
        minHeight: NODE_SIZE.h,
        transformOrigin: "top left",
        zIndex: selected ? 4 : 2,
      }}
      onPointerDown={(e) => {
        if ((e.target as HTMLElement).closest("textarea,input,select,button,.port")) return;
        onSelect();
        drag.current = { x: e.clientX, y: e.clientY, nx: node.x, ny: node.y };
        (e.currentTarget as HTMLElement).setPointerCapture(e.pointerId);
      }}
      onPointerMove={(e) => {
        if (!drag.current) return;
        const dx = (e.clientX - drag.current.x) / zoom;
        const dy = (e.clientY - drag.current.y) / zoom;
        onMove(drag.current.nx + dx, drag.current.ny + dy);
      }}
      onPointerUp={() => {
        drag.current = null;
      }}
    >
      <article
        style={{
          background: "var(--glaze-bg-elevated, #1c1c1e)",
          border: `1px solid ${selected ? "var(--glaze-accent, #0a84ff)" : "var(--glaze-border, #3a3a3c)"}`,
          borderRadius: 10,
          padding: 10,
          color: "var(--glaze-fg, #f2f2f7)",
          boxShadow: selected ? "0 0 0 2px rgba(10,132,255,.25)" : "0 8px 24px rgba(0,0,0,.28)",
        }}
      >
        <header style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 8 }}>
          <Port side="in" onDown={(e) => onPortDown("in", undefined, e)} />
          <input
            value={node.title}
            onChange={(e) => onChange({ ...node, title: e.target.value })}
            style={fieldStyle}
          />
          <span style={badge(result?.state)}>{result?.state ?? "idle"}</span>
          <button type="button" onClick={onDelete} style={iconBtn}>
            ×
          </button>
        </header>

        {node.type === "input" && (
          <textarea
            rows={4}
            value={node.data.text ?? ""}
            onChange={(e) => patchData({ text: e.target.value })}
            placeholder="Source text"
            style={areaStyle}
          />
        )}

        {node.type === "ai" && (
          <>
            <textarea
              rows={3}
              value={node.data.prompt ?? ""}
              onChange={(e) => patchData({ prompt: e.target.value })}
              placeholder="Prompt. Use {{input}} or {{Node title}} or {{field}}"
              style={areaStyle}
            />
            <GradeSelect value={node.data.grade ?? "smart"} onChange={(grade) => patchData({ grade })} />
            <label
              style={{ ...dropStyle, marginTop: 6 }}
              onDragOver={(e) => e.preventDefault()}
              onDrop={(e) => {
                e.preventDefault();
                const file = e.dataTransfer.files[0];
                if (!file || !file.type.startsWith("image/")) return;
                const reader = new FileReader();
                reader.onload = () =>
                  patchData({ image: { dataUrl: String(reader.result), name: file.name } });
                reader.readAsDataURL(file);
              }}
            >
              {node.data.image ? node.data.image.name : "Drop image for vision"}
              <input
                type="file"
                accept="image/*"
                hidden
                onChange={(e) => {
                  const file = e.target.files?.[0];
                  if (!file) return;
                  const reader = new FileReader();
                  reader.onload = () =>
                    patchData({ image: { dataUrl: String(reader.result), name: file.name } });
                  reader.readAsDataURL(file);
                }}
              />
            </label>
          </>
        )}

        {node.type === "extract" && (
          <>
            <textarea
              rows={2}
              value={node.data.instructions ?? ""}
              onChange={(e) => patchData({ instructions: e.target.value })}
              placeholder="Extract instructions"
              style={areaStyle}
            />
            <GradeSelect value={node.data.grade ?? "smart"} onChange={(grade) => patchData({ grade })} />
            {(node.data.fields ?? []).map((f, i) => (
              <div key={i} style={{ display: "flex", gap: 4, marginTop: 4 }}>
                <input
                  value={f.name}
                  placeholder="field"
                  style={fieldStyle}
                  onChange={(e) => {
                    const fields = [...(node.data.fields ?? [])];
                    fields[i] = { ...f, name: e.target.value };
                    patchData({ fields });
                  }}
                />
                <select
                  value={f.type}
                  style={fieldStyle}
                  onChange={(e) => {
                    const fields = [...(node.data.fields ?? [])];
                    fields[i] = { ...f, type: e.target.value as any };
                    patchData({ fields });
                  }}
                >
                  <option value="string">string</option>
                  <option value="number">number</option>
                  <option value="boolean">boolean</option>
                </select>
                <button
                  type="button"
                  style={iconBtn}
                  onClick={() =>
                    patchData({ fields: (node.data.fields ?? []).filter((_, j) => j !== i) })
                  }
                >
                  ×
                </button>
              </div>
            ))}
            <button
              type="button"
              style={{ ...iconBtn, width: "100%", marginTop: 6 }}
              onClick={() =>
                patchData({
                  fields: [...(node.data.fields ?? []), { name: "field", type: "string", description: "" }],
                })
              }
            >
              + field
            </button>
          </>
        )}

        {node.type === "branch" && (
          <>
            <textarea
              rows={2}
              value={node.data.instructions ?? ""}
              onChange={(e) => patchData({ instructions: e.target.value })}
              placeholder="Classify instructions"
              style={areaStyle}
            />
            <GradeSelect value={node.data.grade ?? "fast"} onChange={(grade) => patchData({ grade })} />
            {(node.data.labels ?? []).map((label, i) => (
              <input
                key={i}
                value={label}
                style={{ ...fieldStyle, marginTop: 4 }}
                onChange={(e) => {
                  const next = [...(node.data.labels ?? [])];
                  next[i] = e.target.value;
                  patchData({ labels: next });
                }}
              />
            ))}
            <button
              type="button"
              style={{ ...iconBtn, width: "100%", marginTop: 6 }}
              onClick={() => patchData({ labels: [...(node.data.labels ?? []), "label"] })}
            >
              + label
            </button>
          </>
        )}

        {node.type === "template" && (
          <textarea
            rows={4}
            value={node.data.template ?? ""}
            onChange={(e) => patchData({ template: e.target.value })}
            placeholder="Hello {{input}}"
            style={areaStyle}
          />
        )}

        {node.type === "web" && (
          <input
            value={node.data.url ?? ""}
            onChange={(e) => patchData({ url: e.target.value })}
            placeholder="https:// or {{param.url}}"
            style={fieldStyle}
          />
        )}

        {node.type === "file" && (
          <button type="button" onClick={onPickFile} style={{ ...iconBtn, width: "100%" }}>
            {node.data.name || node.data.path || "Choose file"}
          </button>
        )}

        {node.type === "output" && (
          <pre style={outStyle}>{result?.output || "Combined upstream output"}</pre>
        )}

        {result?.output && node.type !== "output" && (
          <pre style={outStyle}>{result.output.slice(0, 400)}</pre>
        )}
        {result?.error && <p style={{ color: "#ff453a", fontSize: 11 }}>{result.error}</p>}

        <div style={{ display: "flex", justifyContent: "flex-end", gap: 8, marginTop: 8 }}>
          {labels.map((label) => (
            <div key={label} style={{ display: "flex", alignItems: "center", gap: 4 }}>
              {node.type === "branch" && <span style={{ fontSize: 10, opacity: 0.7 }}>{label}</span>}
              <Port side="out" onDown={(e) => onPortDown("out", node.type === "branch" ? label : undefined, e)} />
            </div>
          ))}
        </div>
      </article>
    </div>
  );
}

function Port({ side, onDown }: { side: "in" | "out"; onDown: (e: React.PointerEvent) => void }) {
  return (
    <button
      type="button"
      className="port"
      aria-label={side}
      onPointerDown={(e) => {
        e.stopPropagation();
        onDown(e);
      }}
      style={{
        width: 12,
        height: 12,
        borderRadius: 99,
        border: "2px solid #0a84ff",
        background: side === "in" ? "#1c1c1e" : "#0a84ff",
        padding: 0,
        cursor: "crosshair",
      }}
    />
  );
}

function GradeSelect({ value, onChange }: { value: Grade; onChange: (g: Grade) => void }) {
  return (
    <select value={value} onChange={(e) => onChange(e.target.value as Grade)} style={{ ...fieldStyle, marginTop: 6 }}>
      {GRADES.map((g) => (
        <option key={g} value={g}>
          {g}
        </option>
      ))}
    </select>
  );
}

function badge(state?: string): React.CSSProperties {
  const color =
    state === "error"
      ? "#ff453a"
      : state === "done"
        ? "#30d158"
        : state === "skipped"
          ? "#8e8e93"
          : state === "streaming" || state === "running"
            ? "#0a84ff"
            : "#636366";
  return { fontSize: 10, padding: "1px 6px", borderRadius: 99, background: color, color: "#fff" };
}

const fieldStyle: React.CSSProperties = {
  flex: 1,
  minWidth: 0,
  background: "#2c2c2e",
  color: "inherit",
  border: "1px solid #3a3a3c",
  borderRadius: 6,
  padding: "4px 6px",
  fontSize: 12,
};
const areaStyle: React.CSSProperties = { ...fieldStyle, width: "100%", resize: "vertical" };
const outStyle: React.CSSProperties = {
  ...fieldStyle,
  maxHeight: 90,
  overflow: "auto",
  whiteSpace: "pre-wrap",
  marginTop: 6,
};
const dropStyle: React.CSSProperties = {
  ...fieldStyle,
  display: "block",
  textAlign: "center",
  padding: 8,
  borderStyle: "dashed",
};
const iconBtn: React.CSSProperties = {
  background: "#2c2c2e",
  color: "inherit",
  border: "1px solid #3a3a3c",
  borderRadius: 6,
  padding: "2px 8px",
  cursor: "pointer",
};
