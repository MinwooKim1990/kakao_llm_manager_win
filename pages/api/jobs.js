import { listJobFiles, readJob } from "../../server-utils/storage";

export default function handler(req, res) {
  if (req.method !== "GET") {
    return res.status(405).json({ error: "Method not allowed" });
  }
  try {
    const jobs = listJobFiles()
      .map((fileName) => readJob(fileName.replace(/\.json$/, "")))
      .filter(Boolean);
    return res.status(200).json({ jobs });
  } catch (error) {
    return res.status(500).json({ error: String(error.message || error) });
  }
}
