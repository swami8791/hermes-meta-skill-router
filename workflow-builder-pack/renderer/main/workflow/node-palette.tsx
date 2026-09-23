import type { NodeType } from "./types";

const TYPES: { type: NodeType; label: string }[] = [
  { type: "input", label: "Input" },
  { type: "ai", label: "AI" },
  { type: "extract", label: "Extract" },
  { type: "branch", label: "Branch" },
  { type: "template", label: "Template" },
  { type: "web", label: "Web" },
  { type: "file", label: "File" },
  { type: "output", label: "Output" },
];

export function NodePalette({ onAdd }: { onAdd: (type: NodeType) => void }) {
  return (
    <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
      {TYPES.map((t) => (
        <button
          key={t.type}
          type="button"
          draggable
          onDragStart={(e) => e.dataTransfer.setData("application/x-node-type", t.type)}
          onClick={() => onAdd(t.type)}
          style={{
            fontSize: 12,
            padding: "4px 8px",
            borderRadius: 8,
            border: "1px solid #3a3a3c",
            background: "#2c2c2e",
            color: "#f2f2f7",
            cursor: "grab",
          }}
        >
          {t.label}
        </button>
      ))}
    </div>
  );
}
