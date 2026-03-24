import { readAppState, writeAppState } from "../../server-utils/storage";
import { listActiveProcesses, runBackendJson } from "../../server-utils/backend";

export default function handler(req, res) {
  try {
    if (req.method === "POST") {
      const currentState = readAppState();
      const nextState = {
        ...currentState,
        config: {
          ...currentState.config,
          ...(req.body?.config || {})
        }
      };
      const saved = writeAppState(nextState);
      return res.status(200).json(saved);
    }

    const state = readAppState();
    const status = runBackendJson(["status", "--model-id", state.config.modelId]);
    return res.status(200).json({
      ...status,
      serverRuntime: {
        activeWorkers: listActiveProcesses()
      }
    });
  } catch (error) {
    return res.status(500).json({ error: String(error.message || error) });
  }
}
