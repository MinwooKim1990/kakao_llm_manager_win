import { readAppState, writeAppState } from "../../server-utils/storage";
import { startAgentProcess } from "../../server-utils/backend";

export default function handler(req, res) {
  if (req.method !== "POST") {
    return res.status(405).json({ error: "Method not allowed" });
  }
  try {
    const currentState = readAppState();
    const nextConfig = {
      ...currentState.config,
      ...(req.body?.config || {})
    };
    if (!nextConfig.selectedOrdersCsv) {
      return res.status(400).json({ error: "주문 CSV를 먼저 선택하세요." });
    }
    const saved = writeAppState({
      ...currentState,
      config: nextConfig
    });
    const started = startAgentProcess(saved.config);
    return res.status(200).json(started);
  } catch (error) {
    return res.status(500).json({ error: String(error.message || error) });
  }
}
