import { runBackendJson } from "../../../server-utils/backend";

export default function handler(req, res) {
  if (req.method !== "GET") {
    return res.status(405).json({ error: "Method not allowed" });
  }
  try {
    const jobId = String(req.query.jobId || "");
    if (!jobId) {
      return res.status(400).json({ error: "jobId is required" });
    }
    const payload = runBackendJson(["read-job", "--job-id", jobId]);
    return res.status(200).json(payload);
  } catch (error) {
    return res.status(500).json({ error: String(error.message || error) });
  }
}
