import { app, dialog } from "electron";
import { mkdir, readdir, readFile, writeFile, unlink } from "node:fs/promises";
import { join, basename } from "node:path";

const MAX_TEXT = 80_000;

type WorkflowPayload = {
  id: string;
  name: string;
  nodes: unknown[];
  connections: unknown[];
  viewport: unknown;
  updatedAt: number;
  params?: unknown;
};

function dir() {
  return join(app.getPath("userData"), "workflows");
}

async function ensureDir() {
  await mkdir(dir(), { recursive: true });
}

function fileFor(id: string) {
  const safe = id.replace(/[^a-zA-Z0-9_-]/g, "");
  if (!safe) throw new Error("Invalid workflow id");
  return join(dir(), `${safe}.json`);
}

function stripTags(html: string) {
  return html
    .replace(/<script[\s\S]*?<\/script>/gi, " ")
    .replace(/<style[\s\S]*?<\/style>/gi, " ")
    .replace(/<[^>]+>/g, " ")
    .replace(/\s+/g, " ")
    .trim();
}

export const workflowHandlers = {
  "workflow:list": async () => {
    await ensureDir();
    const files = (await readdir(dir())).filter((f) => f.endsWith(".json"));
    const items: { id: string; name: string; updatedAt: number }[] = [];
    for (const f of files) {
      try {
        const raw = JSON.parse(await readFile(join(dir(), f), "utf8")) as WorkflowPayload;
        items.push({ id: raw.id, name: raw.name, updatedAt: raw.updatedAt });
      } catch {
        // skip corrupt
      }
    }
    return items.sort((a, b) => b.updatedAt - a.updatedAt);
  },

  "workflow:load": async (id: string) => {
    const raw = await readFile(fileFor(id), "utf8");
    return JSON.parse(raw) as WorkflowPayload;
  },

  "workflow:save": async (wf: WorkflowPayload) => {
    if (!wf?.id || !wf?.name) throw new Error("Workflow id and name required");
    await ensureDir();
    const payload: WorkflowPayload = { ...wf, updatedAt: Date.now() };
    await writeFile(fileFor(wf.id), JSON.stringify(payload, null, 2), "utf8");
    return payload;
  },

  "workflow:delete": async (id: string) => {
    await unlink(fileFor(id));
    return { ok: true };
  },

  "workflow:fetchUrl": async (url: string) => {
    if (!/^https?:\/\//i.test(url)) throw new Error("Only http(s) URLs are allowed");
    const res = await fetch(url, { redirect: "follow" });
    if (!res.ok) throw new Error(`Fetch failed (${res.status})`);
    const contentType = res.headers.get("content-type") ?? "";
    const body = await res.text();
    const text = contentType.includes("html") ? stripTags(body) : body;
    return {
      text: text.slice(0, MAX_TEXT),
      untrusted: true,
      source: url,
    };
  },

  "workflow:readFile": async (path: string) => {
    if (!path) throw new Error("Missing path");
    const text = await readFile(path, "utf8");
    return {
      text: text.slice(0, MAX_TEXT),
      name: basename(path),
      untrusted: true,
      path,
    };
  },

  "workflow:openFileDialog": async () => {
    const result = await dialog.showOpenDialog({
      properties: ["openFile"],
      filters: [
        { name: "Text", extensions: ["txt", "md", "json", "csv", "html", "xml", "log"] },
        { name: "All", extensions: ["*"] },
      ],
    });
    if (result.canceled || !result.filePaths[0]) return null;
    const path = result.filePaths[0];
    const text = await readFile(path, "utf8");
    return { path, name: basename(path), text: text.slice(0, MAX_TEXT), untrusted: true };
  },
};

export function registerWorkflowHandlers(
  ipc: { handle: (channel: string, fn: (...args: unknown[]) => unknown) => void }
) {
  for (const [channel, fn] of Object.entries(workflowHandlers)) {
    ipc.handle(channel, (_event: unknown, ...args: unknown[]) => (fn as Function)(...args));
  }
}
