export type Grade = "fast" | "smart" | "powerful";

export type NodeType =
  | "input"
  | "ai"
  | "extract"
  | "branch"
  | "template"
  | "web"
  | "file"
  | "output";

export type FieldType = "string" | "number" | "boolean";

export type ExtractField = {
  name: string;
  type: FieldType;
  description: string;
};

export type NodeData = {
  text?: string;
  prompt?: string;
  grade?: Grade;
  image?: { dataUrl: string; name: string };
  instructions?: string;
  fields?: ExtractField[];
  labels?: string[];
  template?: string;
  url?: string;
  path?: string;
  name?: string;
  params?: Record<string, string>;
};

export type WorkflowNode = {
  id: string;
  type: NodeType;
  x: number;
  y: number;
  title: string;
  data: NodeData;
};

export type Connection = {
  id: string;
  from: string;
  to: string;
  fromPort?: string;
};

export type Viewport = { x: number; y: number; zoom: number };

export type Workflow = {
  id: string;
  name: string;
  nodes: WorkflowNode[];
  connections: Connection[];
  viewport: Viewport;
  updatedAt: number;
  params?: { key: string; value: string }[];
};

export type RunState = "idle" | "running" | "streaming" | "done" | "skipped" | "error";

export type NodeRunResult = {
  state: RunState;
  output?: string;
  fields?: Record<string, string | number | boolean>;
  label?: string;
  error?: string;
};

export type RunSnapshot = {
  id: string;
  workflowId: string;
  workflowName: string;
  startedAt: number;
  finishedAt?: number;
  results: Record<string, NodeRunResult>;
  params?: Record<string, string>;
};

export const DEFAULT_TITLES: Record<NodeType, string> = {
  input: "Input",
  ai: "AI",
  extract: "Extract",
  branch: "Branch",
  template: "Template",
  web: "Web",
  file: "File",
  output: "Output",
};

export const NODE_SIZE = { w: 260, h: 168 };
export const LAST_OPENED_KEY = "workflow:last-opened-id";
export const RUN_HISTORY_KEY = "workflow:run-history";

export const BLOCKED_MESSAGE: Record<string, string> = {
  "consent-required": "Grant AI access to run this step.",
  "credits-exhausted": "Out of Glaze AI credits.",
  "host-unavailable": "AI host is unavailable. Enable it from Run.",
  "rate-limited": "Rate limited. Wait and retry.",
  "cancelled": "Run stopped.",
  "model-unavailable": "Selected grade is unavailable.",
  "unknown": "AI request failed.",
};
