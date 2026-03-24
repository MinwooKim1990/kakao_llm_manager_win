import fs from "fs";
import path from "path";
import { BACKEND_CLI, STORAGE_DIR, listJobFiles } from "../../server-utils/storage";
import { runBackendJson } from "../../server-utils/backend";

function versionInfo(name) {
  try {
    const pkgPath = path.join(process.cwd(), "package.json");
    const pkg = JSON.parse(fs.readFileSync(pkgPath, "utf8"));
    return pkg.dependencies?.[name] || pkg.devDependencies?.[name] || null;
  } catch {
    return null;
  }
}

export default function handler(req, res) {
  try {
    const status = runBackendJson(["status", "--model-id", "Qwen/Qwen3.5-4B"]);
    res.status(200).json({
      ok: true,
      backendAvailable: true,
      backendCli: BACKEND_CLI,
      storageDir: STORAGE_DIR,
      python: {
        version: process.version
      },
      frontend: {
        next: versionInfo("next"),
        react: versionInfo("react"),
        reactDom: versionInfo("react-dom")
      },
      counts: {
        uploads: status?.storage?.uploads?.length || 0,
        jobs: listJobFiles().length
      },
      backendStatus: status
    });
  } catch (error) {
    res.status(200).json({
      ok: false,
      backendAvailable: fs.existsSync(BACKEND_CLI),
      backendCli: BACKEND_CLI,
      storageDir: STORAGE_DIR,
      error: String(error.message || error)
    });
  }
}
