import { STARTER_TEMPLATES } from "./templates";
import type { WorkflowStore } from "./use-workflow-store";

export function WorkflowSidebar({ store }: { store: WorkflowStore }) {
  const { workflow, list, history, rename, load, createNew, remove, applyTemplate, setParams } = store;

  return (
    <aside
      style={{
        width: 240,
        borderRight: "1px solid #3a3a3c",
        background: "#1c1c1e",
        color: "#f2f2f7",
        padding: 12,
        overflow: "auto",
        display: "flex",
        flexDirection: "column",
        gap: 16,
      }}
    >
      <section>
        <h3 style={h}>Workflows</h3>
        <button type="button" style={btn} onClick={createNew}>
          New
        </button>
        <ul style={{ listStyle: "none", padding: 0, margin: "8px 0 0" }}>
          {list.map((item) => (
            <li key={item.id} style={{ display: "flex", gap: 6, marginBottom: 4 }}>
              <button
                type="button"
                onClick={() => load(item.id)}
                style={{
                  ...btn,
                  flex: 1,
                  textAlign: "left",
                  background: item.id === workflow.id ? "#0a84ff" : "#2c2c2e",
                }}
              >
                {item.name}
              </button>
              <button type="button" style={btn} onClick={() => remove(item.id)}>
                ×
              </button>
            </li>
          ))}
        </ul>
      </section>

      <section>
        <h3 style={h}>Name</h3>
        <input value={workflow.name} onChange={(e) => rename(e.target.value)} style={input} />
      </section>

      <section>
        <h3 style={h}>Run params</h3>
        {(workflow.params ?? []).map((p, i) => (
          <div key={i} style={{ display: "flex", gap: 4, marginBottom: 4 }}>
            <input
              value={p.key}
              placeholder="key"
              style={input}
              onChange={(e) => {
                const next = [...(workflow.params ?? [])];
                next[i] = { ...p, key: e.target.value };
                setParams(next);
              }}
            />
            <input
              value={p.value}
              placeholder="value"
              style={input}
              onChange={(e) => {
                const next = [...(workflow.params ?? [])];
                next[i] = { ...p, value: e.target.value };
                setParams(next);
              }}
            />
          </div>
        ))}
        <button
          type="button"
          style={btn}
          onClick={() => setParams([...(workflow.params ?? []), { key: "key", value: "" }])}
        >
          + param
        </button>
        <p style={{ fontSize: 11, opacity: 0.6 }}>Use as {"{{param.key}}"}</p>
      </section>

      <section>
        <h3 style={h}>Starters</h3>
        {STARTER_TEMPLATES.map((t) => (
          <button key={t.id} type="button" style={{ ...btn, width: "100%", marginBottom: 4 }} onClick={() => applyTemplate(t.id)}>
            {t.name}
          </button>
        ))}
      </section>

      <section>
        <h3 style={h}>History</h3>
        {history.length === 0 && <p style={{ fontSize: 12, opacity: 0.6 }}>No runs yet</p>}
        {history.slice(0, 8).map((hitem) => (
          <div key={hitem.id} style={{ fontSize: 11, opacity: 0.8, marginBottom: 6 }}>
            {new Date(hitem.startedAt).toLocaleString()} · {hitem.workflowName}
          </div>
        ))}
      </section>
    </aside>
  );
}

const h: React.CSSProperties = { margin: "0 0 8px", fontSize: 12, textTransform: "uppercase", letterSpacing: 0.4 };
const btn: React.CSSProperties = {
  background: "#2c2c2e",
  color: "inherit",
  border: "1px solid #3a3a3c",
  borderRadius: 8,
  padding: "4px 8px",
  cursor: "pointer",
};
const input: React.CSSProperties = {
  width: "100%",
  background: "#2c2c2e",
  color: "inherit",
  border: "1px solid #3a3a3c",
  borderRadius: 6,
  padding: "4px 6px",
};
