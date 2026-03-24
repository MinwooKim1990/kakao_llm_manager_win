import { runBackendJson } from "../../server-utils/backend";

export default function handler(req, res) {
  try {
    const category = req.query.category ? String(req.query.category) : "all";
    const files = runBackendJson(["list-files", "--category", category]);
    return res.status(200).json(files);
  } catch (error) {
    return res.status(500).json({ error: String(error.message || error) });
  }
}
