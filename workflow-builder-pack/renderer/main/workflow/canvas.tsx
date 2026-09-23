import { useRef, useState } from "react";
import { ConnectionsLayer } from "./connections-layer";
import { NodeCard } from "./node-card";
import type { NodeRunResult, Viewport, Workflow } from "./types";
import type { WorkflowStore } from "./use-workflow-store";

type Draft = { from: string; fromPort?: string; x1: number; y1: number; x2: number; y2: number };

export function Canvas({
  store,
  results,
}: {
  store: WorkflowStore;
  results: Record<string, NodeRunResult>;
}) {
  const { workflow, moveNode, updateNode, deleteNode, connect, deleteConnection, setViewport, addNode } = store;
  const [selected, setSelected] = useState<string | null>(null);
  const [draft, setDraft] = useState<Draft | null>(null);
  const root = useRef<HTMLDivElement>(null);

  const vp = workflow.viewport;

  const toWorld = (clientX: number, clientY: number) => {
    const rect = root.current!.getBoundingClientRect();
    return {
      x: (clientX - rect.left - vp.x) / vp.zoom,
      y: (clientY - rect.top - vp.y) / vp.zoom,
    };
  };

  const onWheel = (e: React.WheelEvent) => {
    e.preventDefault();
    const nextZoom = Math.min(1.8, Math.max(0.4, vp.zoom * (e.deltaY > 0 ? 0.92 : 1.08)));
    setViewport({ ...vp, zoom: nextZoom });
  };

  const pan = useRef<{ x: number; y: number; vx: number; vy: number } | null>(null);

  return (
    <div
      ref={root}
      onWheel={onWheel}
      onPointerDown={(e) => {
        if (e.target !== e.currentTarget) return;
        setSelected(null);
        pan.current = { x: e.clientX, y: e.clientY, vx: vp.x, vy: vp.y };
        (e.currentTarget as HTMLElement).setPointerCapture(e.pointerId);
      }}
      onPointerMove={(e) => {
        if (draft) {
          const w = toWorld(e.clientX, e.clientY);
          setDraft({ ...draft, x2: w.x, y2: w.y });
          return;
        }
        if (!pan.current) return;
        setViewport({
          ...vp,
          x: pan.current.vx + (e.clientX - pan.current.x),
          y: pan.current.vy + (e.clientY - pan.current.y),
        });
      }}
      onPointerUp={async (e) => {
        pan.current = null;
        if (draft) {
          const hit = workflow.nodes.find((n) => {
            const w = toWorld(e.clientX, e.clientY);
            return w.x >= n.x && w.x <= n.x + 260 && w.y >= n.y && w.y <= n.y + 180;
          });
          if (hit && hit.id !== draft.from) connect(draft.from, hit.id, draft.fromPort);
          setDraft(null);
        }
      }}
      onDragOver={(e) => e.preventDefault()}
      onDrop={(e) => {
        const type = e.dataTransfer.getData("application/x-node-type");
        if (!type) return;
        const w = toWorld(e.clientX, e.clientY);
        addNode(type as Workflow["nodes"][number]["type"], w.x, w.y);
      }}
      style={{
        position: "relative",
        flex: 1,
        overflow: "hidden",
        background:
          "radial-gradient(circle at 1px 1px, rgba(255,255,255,.06) 1px, transparent 0) 0 0 / 18px 18px #111",
        cursor: pan.current ? "grabbing" : "default",
      }}
    >
      <div style={{ transform: `translate(${vp.x}px, ${vp.y}px) scale(${vp.zoom})`, transformOrigin: "0 0" }}>
        <ConnectionsLayer
          nodes={workflow.nodes}
          connections={workflow.connections}
          draft={draft}
          onDelete={deleteConnection}
        />
        {workflow.nodes.map((node) => (
          <NodeCard
            key={node.id}
            node={node}
            selected={selected === node.id}
            result={results[node.id]}
            zoom={vp.zoom}
            onSelect={() => setSelected(node.id)}
            onMove={(x, y) => moveNode(node.id, x, y)}
            onChange={(n) => updateNode(n.id, n)}
            onDelete={() => deleteNode(node.id)}
            onPortDown={(side, port, ev) => {
              if (side !== "out" || !ev) return;
              const w = toWorld(ev.clientX, ev.clientY);
              setDraft({ from: node.id, fromPort: port, x1: w.x, y1: w.y, x2: w.x, y2: w.y });
            }}
            onPickFile={async () => {
              const picked = await window.glazeAPI!.glaze.ipc.invoke("workflow:openFileDialog");
              if (!picked) return;
              updateNode(node.id, {
                ...node,
                data: { ...node.data, path: picked.path, name: picked.name },
              });
            }}
          />
        ))}
      </div>
    </div>
  );
}
