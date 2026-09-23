import { useCallback, useEffect, useMemo, useState } from "react";
import { STARTER_TEMPLATES } from "./templates";
import {
  DEFAULT_TITLES,
  LAST_OPENED_KEY,
  RUN_HISTORY_KEY,
  type Connection,
  type NodeType,
  type RunSnapshot,
  type Viewport,
  type Workflow,
  type WorkflowNode,
} from "./types";

declare global {
  interface Window {
    glazeAPI?: {
      glaze: {
        ipc: {
          invoke: (channel: string, ...args: unknown[]) => Promise<any>;
        };
      };
    };
  }
}

const ipc = (channel: string, ...args: unknown[]) =>
  window.glazeAPI!.glaze.ipc.invoke(channel, ...args);

function uid(prefix = "id") {
  return `${prefix}-${Math.random().toString(36).slice(2, 9)}`;
}

function blankWorkflow(): Workflow {
  return {
    id: uid("wf"),
    name: "Untitled",
    nodes: [],
    connections: [],
    viewport: { x: 0, y: 0, zoom: 1 },
    updatedAt: Date.now(),
    params: [],
  };
}

export function useWorkflowStore() {
  const [workflow, setWorkflow] = useState<Workflow>(blankWorkflow);
  const [list, setList] = useState<{ id: string; name: string; updatedAt: number }[]>([]);
  const [dirty, setDirty] = useState(false);
  const [history, setHistory] = useState<RunSnapshot[]>(() => {
    try {
      return JSON.parse(localStorage.getItem(RUN_HISTORY_KEY) || "[]");
    } catch {
      return [];
    }
  });

  const refreshList = useCallback(async () => {
    try {
      setList(await ipc("workflow:list"));
    } catch {
      setList([]);
    }
  }, []);

  const load = useCallback(async (id: string) => {
    const wf = (await ipc("workflow:load", id)) as Workflow;
    setWorkflow(wf);
    setDirty(false);
    localStorage.setItem(LAST_OPENED_KEY, id);
  }, []);

  const save = useCallback(async () => {
    const saved = (await ipc("workflow:save", { ...workflow, updatedAt: Date.now() })) as Workflow;
    setWorkflow(saved);
    setDirty(false);
    localStorage.setItem(LAST_OPENED_KEY, saved.id);
    await refreshList();
    return saved;
  }, [workflow, refreshList]);

  const createNew = useCallback(() => {
    const wf = blankWorkflow();
    setWorkflow(wf);
    setDirty(true);
  }, []);

  const applyTemplate = useCallback((templateId: string) => {
    const t = STARTER_TEMPLATES.find((x) => x.id === templateId);
    if (!t) return;
    const built = t.build();
    setWorkflow({ ...built, id: uid("wf"), updatedAt: Date.now() });
    setDirty(true);
  }, []);

  const remove = useCallback(
    async (id: string) => {
      await ipc("workflow:delete", id);
      if (workflow.id === id) createNew();
      await refreshList();
    },
    [workflow.id, createNew, refreshList]
  );

  useEffect(() => {
    (async () => {
      await refreshList();
      const last = localStorage.getItem(LAST_OPENED_KEY);
      if (last) {
        try {
          await load(last);
        } catch {
          createNew();
        }
      }
    })();
  }, [refreshList, load, createNew]);

  const patch = useCallback((fn: (w: Workflow) => Workflow) => {
    setWorkflow((w) => fn(w));
    setDirty(true);
  }, []);

  const addNode = useCallback(
    (type: NodeType, x: number, y: number) => {
      const node: WorkflowNode = {
        id: uid("n"),
        type,
        x,
        y,
        title: DEFAULT_TITLES[type],
        data:
          type === "ai" || type === "extract" || type === "branch"
            ? { grade: "smart", prompt: "", instructions: "", fields: [], labels: ["yes", "no"] }
            : type === "template"
              ? { template: "{{input}}" }
              : {},
      };
      patch((w) => ({ ...w, nodes: [...w.nodes, node] }));
      return node.id;
    },
    [patch]
  );

  const moveNode = useCallback(
    (id: string, x: number, y: number) => {
      patch((w) => ({
        ...w,
        nodes: w.nodes.map((n) => (n.id === id ? { ...n, x, y } : n)),
      }));
    },
    [patch]
  );

  const updateNode = useCallback(
    (id: string, next: Partial<WorkflowNode> | ((n: WorkflowNode) => WorkflowNode)) => {
      patch((w) => ({
        ...w,
        nodes: w.nodes.map((n) =>
          n.id === id ? (typeof next === "function" ? next(n) : { ...n, ...next, data: { ...n.data, ...(next as any).data } }) : n
        ),
      }));
    },
    [patch]
  );

  const deleteNode = useCallback(
    (id: string) => {
      patch((w) => ({
        ...w,
        nodes: w.nodes.filter((n) => n.id !== id),
        connections: w.connections.filter((c) => c.from !== id && c.to !== id),
      }));
    },
    [patch]
  );

  const connect = useCallback(
    (from: string, to: string, fromPort?: string) => {
      if (from === to) return;
      patch((w) => {
        if (w.connections.some((c) => c.from === from && c.to === to && c.fromPort === fromPort)) return w;
        return {
          ...w,
          connections: [...w.connections, { id: uid("c"), from, to, fromPort }],
        };
      });
    },
    [patch]
  );

  const deleteConnection = useCallback(
    (id: string) => {
      patch((w) => ({ ...w, connections: w.connections.filter((c) => c.id !== id) }));
    },
    [patch]
  );

  const setViewport = useCallback(
    (viewport: Viewport) => {
      setWorkflow((w) => ({ ...w, viewport }));
    },
    []
  );

  const rename = useCallback(
    (name: string) => {
      patch((w) => ({ ...w, name }));
    },
    [patch]
  );

  const pushHistory = useCallback((snap: RunSnapshot) => {
    setHistory((prev) => {
      const next = [snap, ...prev].slice(0, 30);
      localStorage.setItem(RUN_HISTORY_KEY, JSON.stringify(next));
      return next;
    });
  }, []);

  const paramMap = useMemo(() => {
    const out: Record<string, string> = {};
    for (const p of workflow.params ?? []) out[p.key] = p.value;
    return out;
  }, [workflow.params]);

  return {
    workflow,
    list,
    dirty,
    history,
    paramMap,
    addNode,
    moveNode,
    updateNode,
    deleteNode,
    connect,
    deleteConnection,
    setViewport,
    rename,
    save,
    load,
    createNew,
    remove,
    applyTemplate,
    refreshList,
    pushHistory,
    setParams: (params: { key: string; value: string }[]) => patch((w) => ({ ...w, params })),
  };
}

export type WorkflowStore = ReturnType<typeof useWorkflowStore>;
export type { Connection };
