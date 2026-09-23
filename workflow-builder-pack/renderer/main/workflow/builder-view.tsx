import { useMemo } from "react";
import { Canvas } from "./canvas";
import { NodePalette } from "./node-palette";
import { WorkflowSidebar } from "./workflow-sidebar";
import { useWorkflowRun } from "./use-workflow-run";
import { useWorkflowStore } from "./use-workflow-store";

// useGlazeAI is provided by the Glaze renderer runtime. Do not import @glaze/core/ai.
declare function useGlazeAI(): {
  generate: any;
  streamText: any;
  enableInHost?: () => Promise<void> | void;
};

export function BuilderView() {
  const store = useWorkflowStore();
  const ai = useMaybeGlazeAI();
  const { results, running, run, stop } = useWorkflowRun(store, ai);

  const summary = useMemo(() => {
    const vals = Object.values(results);
    const done = vals.filter((v) => v.state === "done").length;
    const err = vals.filter((v) => v.state === "error").length;
    const skipped = vals.filter((v) => v.state === "skipped").length;
    return `${done} done · ${skipped} skipped · ${err} error`;
  }, [results]);

  return (
    <div style={{ display: "flex", flexDirection: "column", height: "100%", background: "#000", color: "#f2f2f7" }}>
      <header
        style={{
          display: "flex",
          alignItems: "center",
          gap: 12,
          padding: "8px 12px",
          borderBottom: "1px solid #3a3a3c",
          WebkitAppRegion: "drag",
        } as React.CSSProperties}
      >
        <strong style={{ minWidth: 160 }}>{store.workflow.name}</strong>
        <div style={{ WebkitAppRegion: "no-drag" } as React.CSSProperties}>
          <NodePalette onAdd={(type) => store.addNode(type, 80 + store.workflow.nodes.length * 24, 80)} />
        </div>
        <div style={{ marginLeft: "auto", display: "flex", gap: 8, WebkitAppRegion: "no-drag" } as React.CSSProperties}>
          <span style={{ fontSize: 12, opacity: 0.7, alignSelf: "center" }}>{summary}</span>
          {store.dirty && <span style={{ fontSize: 12, opacity: 0.6 }}>unsaved</span>}
          <button type="button" onClick={() => store.save()} style={btn}>
            Save
          </button>
          <button
            type="button"
            onClick={() => navigator.clipboard.writeText(JSON.stringify(store.workflow, null, 2))}
            style={btn}
          >
            Copy JSON
          </button>
          {running ? (
            <button type="button" onClick={stop} style={{ ...btn, background: "#ff453a" }}>
              Stop
            </button>
          ) : (
            <button type="button" onClick={run} style={{ ...btn, background: "#0a84ff" }}>
              Run
            </button>
          )}
        </div>
      </header>
      <div style={{ display: "flex", flex: 1, minHeight: 0 }}>
        <WorkflowSidebar store={store} />
        <Canvas store={store} results={results} />
      </div>
    </div>
  );
}

function useMaybeGlazeAI() {
  try {
    return useGlazeAI();
  } catch {
    return {
      generate: async () => ({ text: "", state: "host-unavailable" }),
      streamText: async () => ({ text: "", state: "host-unavailable" }),
      enableInHost: async () => undefined,
    };
  }
}

const btn: React.CSSProperties = {
  background: "#2c2c2e",
  color: "#fff",
  border: "1px solid #3a3a3c",
  borderRadius: 8,
  padding: "6px 10px",
  cursor: "pointer",
};
