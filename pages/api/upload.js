import fs from "fs";
import formidable from "formidable";
import { readAppState, sanitizeFilename, writeAppState } from "../../server-utils/storage";
import { resolveUploadPath, storageRelative } from "../../server-utils/backend";

export const config = {
  api: {
    bodyParser: false
  }
};

export default async function handler(req, res) {
  if (req.method !== "POST") {
    return res.status(405).json({ error: "Method not allowed" });
  }

  const form = formidable({});
  try {
    const [fields, files] = await form.parse(req);
    const uploaded = Array.isArray(files.file) ? files.file[0] : files.file;
    if (!uploaded?.filepath) {
      return res.status(400).json({ error: "No file uploaded" });
    }

    const safeName = `${Date.now()}_${sanitizeFilename(uploaded.originalFilename || "upload.csv")}`;
    const destination = resolveUploadPath(safeName);
    fs.copyFileSync(uploaded.filepath, destination);
    const relativePath = storageRelative(destination);

    const setSelected = String(fields.setSelected || "") === "true";
    const target = String(fields.target || "orders");
    if (setSelected) {
      const state = readAppState();
      const key = target === "mapping" ? "selectedMappingCsv" : "selectedOrdersCsv";
      state.config[key] = relativePath;
      writeAppState(state);
    }

    return res.status(200).json({
      uploaded: true,
      relativePath,
      fileName: safeName
    });
  } catch (error) {
    return res.status(500).json({ error: String(error.message || error) });
  }
}
