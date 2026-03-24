import fs from "fs";
import path from "path";

export const APP_DIR = process.cwd();
export const STORAGE_DIR = path.join(APP_DIR, "storage");
export const BACKEND_DIR = path.join(APP_DIR, "backend");
export const BACKEND_CLI = path.join(BACKEND_DIR, "service_cli.py");
export const APP_STATE_PATH = path.join(STORAGE_DIR, "app_state.json");
export const JOBS_DIR = path.join(STORAGE_DIR, "jobs");
export const UPLOADS_DIR = path.join(STORAGE_DIR, "uploads");

const DEFAULT_STATE = {
  config: {
    pythonCommand: "python",
    backend: "transformers",
    modelId: "Qwen/Qwen3.5-4B",
    trustRemoteCode: true,
    responseTimeoutSeconds: 120,
    pollIntervalSeconds: 3,
    maxFollowUpMessages: 1,
    transcriptTurnLimit: 10,
    operatorGoal: "주문 CSV의 상품을 도매상에게 확인해 재고 여부를 기록합니다.",
    targetDescription: "카카오톡 채팅 상대는 도매상 또는 재고 확인 담당자입니다.",
    initialMessageTemplate: "안녕하세요. {item_name}{option_suffix}{quantity_suffix} 재고 있을까요?",
    systemPrompt:
      "답변이 명확한 재고 yes/no 가 아니면 사람 검토로 넘기고, 불필요하게 길게 말하지 마세요.",
    selectedOrdersCsv: "examples/orders_example.csv",
    selectedMappingCsv: ""
  },
  assistantMessage:
    "첫 실행에서는 Python 패키지와 모델 다운로드 때문에 시간이 걸릴 수 있습니다.",
  lastUpdatedAt: new Date().toISOString()
};

export function ensureStorageDirs() {
  [
    STORAGE_DIR,
    path.join(STORAGE_DIR, "uploads"),
    path.join(STORAGE_DIR, "results"),
    path.join(STORAGE_DIR, "logs"),
    path.join(STORAGE_DIR, "jobs"),
    path.join(STORAGE_DIR, "examples"),
    path.join(STORAGE_DIR, "transcripts")
  ].forEach((directory) => fs.mkdirSync(directory, { recursive: true }));
  if (!fs.existsSync(APP_STATE_PATH)) {
    writeAppState(DEFAULT_STATE);
  }
}

export function readAppState() {
  ensureStorageDirs();
  if (!fs.existsSync(APP_STATE_PATH)) {
    return { ...DEFAULT_STATE };
  }
  try {
    return JSON.parse(fs.readFileSync(APP_STATE_PATH, "utf8"));
  } catch {
    return { ...DEFAULT_STATE };
  }
}

export function writeAppState(nextState) {
  ensureStorageDirs();
  const state = {
    ...nextState,
    lastUpdatedAt: new Date().toISOString()
  };
  fs.writeFileSync(APP_STATE_PATH, JSON.stringify(state, null, 2), "utf8");
  return state;
}

export function listJobFiles() {
  ensureStorageDirs();
  return fs
    .readdirSync(JOBS_DIR)
    .filter((name) => name.endsWith(".json"))
    .sort()
    .reverse();
}

export function readJob(jobId) {
  const jobFile = path.join(JOBS_DIR, `${jobId}.json`);
  if (!fs.existsSync(jobFile)) {
    return null;
  }
  return JSON.parse(fs.readFileSync(jobFile, "utf8"));
}

export function writeJob(jobId, payload) {
  ensureStorageDirs();
  const nextPayload = {
    ...payload,
    jobId,
    updatedAt: new Date().toISOString()
  };
  fs.writeFileSync(
    path.join(JOBS_DIR, `${jobId}.json`),
    JSON.stringify(nextPayload, null, 2),
    "utf8"
  );
  return nextPayload;
}

export function sanitizeFilename(name) {
  return name.replace(/[^0-9A-Za-z가-힣._-]+/g, "_");
}
