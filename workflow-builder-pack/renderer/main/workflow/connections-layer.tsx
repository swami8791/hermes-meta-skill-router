import { NODE_SIZE, type Connection, type WorkflowNode } from "./types";

type Wire = { x1: number; y1: number; x2: number; y2: number; id?: string };

function portPos(node: WorkflowNode, side: "in" | "out", index = 0, count = 1) {
  const y = node.y + 22 + (count > 1 ? (index * 18) : 0);
  const x = side === "in" ? node.x : node.x + NODE_SIZE.w;
  return { x, y };
}

function bezier({ x1, y1, x2, y2 }: Wire) {
  const dx = Math.max(40, Math.abs(x2 - x1) * 0.5);
  return `M ${x1} ${y1} C ${x1 + dx} ${y1}, ${x2 - dx} ${y2}, ${x2} ${y2}`;
}

export function ConnectionsLayer({
  nodes,
  connections,
  draft,
  onDelete,
}: {
  nodes: WorkflowNode[];
  connections: Connection[];
  draft?: Wire | null;
  onDelete: (id: string) => void;
}) {
  const byId = new Map(nodes.map((n) => [n.id, n]));
  const wires: (Wire & { id: string })[] = [];
  for (const c of connections) {
    const from = byId.get(c.from);
    const to = byId.get(c.to);
    if (!from || !to) continue;
    const labels = from.type === "branch" ? from.data.labels ?? [] : ["out"];
    const idx = c.fromPort ? Math.max(0, labels.indexOf(c.fromPort)) : 0;
    const a = portPos(from, "out", idx, labels.length);
    const b = portPos(to, "in");
    wires.push({ id: c.id, x1: a.x, y1: a.y, x2: b.x, y2: b.y });
  }

  return (
    <svg
      style={{ position: "absolute", inset: 0, width: "100%", height: "100%", pointerEvents: "none", overflow: "visible" }}
    >
      {wires.map((w) => (
        <path
          key={w.id}
          d={bezier(w)}
          fill="none"
          stroke="#0a84ff"
          strokeWidth={2}
          style={{ pointerEvents: "stroke", cursor: "pointer" }}
          onClick={() => onDelete(w.id)}
        />
      ))}
      {draft && <path d={bezier(draft)} fill="none" stroke="#64d2ff" strokeWidth={2} strokeDasharray="6 4" />}
    </svg>
  );
}
