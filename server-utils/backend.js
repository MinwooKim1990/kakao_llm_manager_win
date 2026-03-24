import fs from "fs";
import path from "path";
import { spawn, spawnSync } from "child_process";
import {
  BACKEND_CLI,
  JOBS_DIR,
  STORAGE_DIR,
  UPLOADS_DIR,
  ensureStorageDirs,
  readAppState,
  readJob,
  writeJob
} from "./storage";

const jobProcesses = globalThis.__kakaoJobProcesses || new Map();
if (!globalThis.__kakaoJobProcesses) {
  globalThis.__kakaoJobProcesses = jobProcesses;
}

function pythonCommand() {
  return readAppState()?.config?.pythonCommand || "python";
}

function pythonEnv() {
  return {
    ...process.env,
    PYTHONUNBUFFERED: "1",
    PYTHONUTF8: "1",
    PYTHONIOENCODING: "utf-8"
  };
}

function isTerminalStatus(status) {
  return ["completed", "failed", "stopped"].includes(String(status || ""));
}

function writeJobPatch(jobId, patch) {
  const current = readJob(jobId) || {};
  return writeJob(jobId, {
    ...current,
    ...patch
  });
}

function appendJobEvent(jobId, event) {
  const current = readJob(jobId) || {};
  const events = Array.isArray(current.progressEvents) ? current.progressEvents.slice(-39) : [];
  events.push({
    at: new Date().toISOString(),
    ...event
  });
  writeJob(jobId, {
    ...current,
    progressEvents: events
  });
}

function killPidTree(pid) {
  if (!pid) {
    return;
  }
  if (process.platform === "win32") {
    spawnSync("taskkill", ["/PID", String(pid), "/T", "/F"], {
      stdio: "ignore"
    });
    return;
  }
  try {
    process.kill(pid, "SIGTERM");
  } catch {}
}

function cleanupAllChildren() {
  for (const [, processInfo] of jobProcesses) {
    killPidTree(processInfo.pid);
  }
}

if (!globalThis.__kakaoCleanupRegistered) {
  globalThis.__kakaoCleanupRegistered = true;
  for (const signal of ["SIGINT", "SIGTERM", "SIGHUP"]) {
    process.on(signal, () => {
      cleanupAllChildren();
      process.exit(0);
    });
  }
  process.on("exit", cleanupAllChildren);
}

export function runBackendJson(args, options = {}) {
  ensureStorageDirs();
  const result = spawnSync(pythonCommand(), [BACKEND_CLI, ...args], {
    cwd: path.dirname(BACKEND_CLI),
    encoding: "utf8",
    env: pythonEnv(),
    ...options
  });
  if (result.status !== 0) {
    throw new Error(result.stderr || result.stdout || "Backend command failed");
  }
  return JSON.parse(result.stdout || "{}");
}

export function listActiveProcesses() {
  return Array.from(jobProcesses.values()).map((entry) => ({
    jobId: entry.jobId,
    pid: entry.pid,
    startedAt: entry.startedAt,
    ordersCsv: entry.ordersCsv,
    modelId: entry.modelId
  }));
}

export function hasActiveProcesses() {
  return jobProcesses.size > 0;
}

export function startAgentProcess(config) {
  ensureStorageDirs();
  if (hasActiveProcesses()) {
    throw new Error("현재 카카오 작업이 이미 실행 중입니다. 한 번에 하나의 작업만 실행할 수 있습니다.");
  }
  const jobId = `job_${Date.now()}`;
  const resultsCsv = `results/${jobId}_results.csv`;
  const transcriptsDir = `transcripts/${jobId}`;
  const logPath = path.join(JOBS_DIR, `${jobId}.log`);
  const stdoutFd = fs.openSync(logPath, "a");
  const ordersCsv = config.selectedOrdersCsv;
  const mappingCsv = config.selectedMappingCsv || "";

  writeJob(jobId, {
    status: "queued",
    startedAt: new Date().toISOString(),
    ordersCsv,
    mappingCsv,
    resultsCsv,
    transcriptsDir,
    backend: config.backend,
    modelId: config.modelId,
    trustRemoteCode: Boolean(config.trustRemoteCode),
    operatorGoal: config.operatorGoal || "",
    targetDescription: config.targetDescription || "",
    initialMessageTemplate: config.initialMessageTemplate || "",
    systemPrompt: config.systemPrompt || "",
    currentStep: "queued",
    assistantMessage: "작업 큐에 등록되었습니다.",
    logPath: `jobs/${jobId}.log`,
    progressEvents: [
      {
        at: new Date().toISOString(),
        step: "queued",
        message: "작업이 큐에 등록되었습니다."
      }
    ]
  });

  const args = [
    BACKEND_CLI,
    "run-agent",
    "--job-id",
    jobId,
    "--orders-csv",
    ordersCsv,
    "--results-csv",
    resultsCsv,
    "--transcripts-dir",
    transcriptsDir,
    "--backend",
    config.backend,
    "--model-id",
    config.modelId,
    "--response-timeout-seconds",
    String(config.responseTimeoutSeconds || 120),
    "--poll-interval-seconds",
    String(config.pollIntervalSeconds || 3),
    "--max-follow-up-messages",
    String(config.maxFollowUpMessages || 1),
    "--transcript-turn-limit",
    String(config.transcriptTurnLimit || 10),
    "--operator-goal",
    config.operatorGoal || "",
    "--target-description",
    config.targetDescription || "",
    "--initial-message-template",
    config.initialMessageTemplate || "",
    "--system-prompt",
    config.systemPrompt || ""
  ];

  if (mappingCsv) {
    args.push("--mapping-csv", mappingCsv);
  }
  if (config.trustRemoteCode) {
    args.push("--trust-remote-code");
  }

  const child = spawn(pythonCommand(), args, {
    cwd: path.dirname(BACKEND_CLI),
    env: pythonEnv(),
    stdio: ["ignore", stdoutFd, stdoutFd]
  });

  jobProcesses.set(jobId, {
    jobId,
    pid: child.pid,
    startedAt: new Date().toISOString(),
    ordersCsv,
    modelId: config.modelId,
    child
  });

  writeJobPatch(jobId, {
    pid: child.pid,
    currentStep: "running",
    assistantMessage: "백엔드 작업 프로세스가 시작되었습니다."
  });
  appendJobEvent(jobId, {
    step: "running",
    message: "백엔드 작업 프로세스가 시작되었습니다.",
    pid: child.pid
  });

  child.on("exit", (code, signal) => {
    jobProcesses.delete(jobId);
    const current = readJob(jobId);
    if (!current) {
      return;
    }
    if (isTerminalStatus(current.status)) {
      appendJobEvent(jobId, {
        step: "process_exit",
        message: `백엔드 프로세스 종료 code=${code ?? ""} signal=${signal ?? ""}`.trim(),
        code,
        signal
      });
      return;
    }
    const stopping = current.status === "stopping";
    writeJob(jobId, {
      ...current,
      status: stopping ? "stopped" : "failed",
      completedAt: current.completedAt || new Date().toISOString(),
      currentStep: stopping ? "stopped" : "process_exit",
      assistantMessage: stopping
        ? "사용자 요청으로 작업이 중지되었습니다."
        : `백엔드 프로세스가 종료되었습니다. code=${code ?? ""} signal=${signal ?? ""}`.trim()
    });
    appendJobEvent(jobId, {
      step: stopping ? "stopped" : "process_exit",
      message: stopping
        ? "사용자 요청으로 작업이 중지되었습니다."
        : `백엔드 프로세스가 종료되었습니다. code=${code ?? ""} signal=${signal ?? ""}`.trim(),
      code,
      signal
    });
  });

  return {
    jobId,
    resultsCsv,
    transcriptsDir,
    pid: child.pid
  };
}

export function stopAgentProcess(jobId) {
  const current = readJob(jobId);
  if (!current) {
    throw new Error("작업을 찾지 못했습니다.");
  }
  if (isTerminalStatus(current.status)) {
    return {
      jobId,
      alreadyStopped: true,
      status: current.status
    };
  }

  const processInfo = jobProcesses.get(jobId);
  const pid = processInfo?.pid || current.pid;
  writeJobPatch(jobId, {
    status: "stopping",
    currentStep: "stopping",
    assistantMessage: "작업 중지 요청을 보냈습니다."
  });
  appendJobEvent(jobId, {
    step: "stopping",
    message: "사용자가 작업 중지를 요청했습니다.",
    pid
  });
  killPidTree(pid);
  return {
    jobId,
    stopping: true,
    pid
  };
}

export function resolveUploadPath(filename) {
  ensureStorageDirs();
  return path.join(UPLOADS_DIR, filename);
}

export function storageRelative(absolutePath) {
  return path.relative(STORAGE_DIR, absolutePath).replaceAll("\\", "/");
}
