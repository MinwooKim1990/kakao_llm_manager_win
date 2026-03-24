const fs = require("fs");
const path = require("path");
const { spawnSync } = require("child_process");

const rootDir = process.cwd();
const nextDir = path.join(rootDir, ".next");

function sleep(ms) {
  Atomics.wait(new Int32Array(new SharedArrayBuffer(4)), 0, 0, ms);
}

function pathExists(targetPath) {
  try {
    return fs.existsSync(targetPath);
  } catch {
    return false;
  }
}

function removeWithNode(targetPath) {
  fs.rmSync(targetPath, {
    recursive: true,
    force: true,
    maxRetries: 5,
    retryDelay: 250,
  });
}

function clearWindowsAttributes() {
  if (process.platform !== "win32") {
    return;
  }
  spawnSync("cmd.exe", ["/d", "/s", "/c", "attrib -R .next /S /D >nul 2>nul"], {
    cwd: rootDir,
    stdio: "ignore",
  });
}

function removeWithWindowsCommand() {
  if (process.platform !== "win32") {
    return false;
  }
  const attempt = spawnSync("cmd.exe", ["/d", "/s", "/c", "rmdir /s /q .next"], {
    cwd: rootDir,
    stdio: "ignore",
  });
  return attempt.status === 0 || !pathExists(nextDir);
}

function tryRenameAside() {
  const staleDir = path.join(rootDir, `.next_stale_${Date.now()}`);
  fs.renameSync(nextDir, staleDir);
  return staleDir;
}

function collectErrorInfo(error) {
  const nested = Array.isArray(error?.errors) && error.errors.length ? error.errors[0] : null;
  const source = nested || error || {};
  return {
    code: String(source.code || error?.code || "UNKNOWN"),
    message: String(source.message || error?.message || "unknown error"),
    path: String(source.path || error?.path || nextDir),
  };
}

if (!pathExists(nextDir)) {
  process.exit(0);
}

let lastError = null;

for (let index = 0; index < 3; index += 1) {
  try {
    clearWindowsAttributes();
    removeWithNode(nextDir);
    if (!pathExists(nextDir)) {
      process.exit(0);
    }
  } catch (error) {
    lastError = error;
    sleep(250);
  }
}

if (pathExists(nextDir) && removeWithWindowsCommand() && !pathExists(nextDir)) {
  process.exit(0);
}

if (pathExists(nextDir)) {
  try {
    const staleDir = tryRenameAside();
    try {
      clearWindowsAttributes();
      removeWithNode(staleDir);
    } catch {
      // Build can continue once `.next` itself has been moved out of the way.
    }
    console.warn(`[prebuild] 기존 .next 폴더를 ${path.basename(staleDir)} 로 이동했습니다.`);
    process.exit(0);
  } catch (error) {
    lastError = error;
  }
}

const details = collectErrorInfo(lastError);
const message = [
  "",
  "[prebuild] .next 폴더를 정리하지 못했습니다.",
  `code: ${details.code}`,
  `path: ${details.path}`,
  `message: ${details.message}`,
  "실행 중인 서버가 없어도 Windows Defender, Explorer 미리보기, 에디터 파일 감시, 이전 빌드의 traced 폴더 때문에 잠금이 남을 수 있습니다.",
  "해결:",
  "1. 파일 탐색기에서 이 프로젝트 폴더 미리보기/검색을 닫습니다.",
  "2. VS Code 터미널/Explorer에서 이 폴더를 보고 있다면 잠시 닫습니다.",
  "3. PowerShell 또는 CMD를 새로 열고 `npm run clean` 을 다시 실행합니다.",
  "4. 그래도 안 되면 Windows에서 남아 있는 `node.exe` 를 종료하거나 재부팅 후 다시 시도합니다.",
  "",
].join("\n");
console.error(message);
process.exit(1);
