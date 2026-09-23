// PATCH this file in your project. Keep existing registrations.
// Add the block below next to the other handler imports/registers.

import { registerWorkflowHandlers } from "./workflow";

export function registerAllHandlers(ipc: {
  handle: (channel: string, fn: (...args: unknown[]) => unknown) => void;
}) {
  registerWorkflowHandlers(ipc);
}

/*
Exact channels to register if you already have a hand-written index:

  workflow:list
  workflow:load
  workflow:save
  workflow:delete
  workflow:fetchUrl
  workflow:readFile
  workflow:openFileDialog
*/
