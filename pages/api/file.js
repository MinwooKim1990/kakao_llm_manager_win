import { runBackendJson } from "../../server-utils/backend";

export default function handler(req, res) {
  if (req.method !== "GET") {
    return res.status(405).json({ error: "Method not allowed" });
  }
  try {
    const targetPath = String(req.query.path || "");
    if (!targetPath) {
      return res.status(400).json({ error: "path is required" });
    }
    const payload = runBackendJson(["read-file", "--path", targetPath]);
    return res.status(200).json(payload);
  } catch (error) {
    return res.status(500).json({ error: String(error.message || error) });
  }
}
