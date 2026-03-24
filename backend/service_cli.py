#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import importlib.util
import json
import os
import platform
import subprocess
import sys
import traceback
from dataclasses import asdict
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

BASE_DIR = Path(__file__).resolve().parent
APP_DIR = BASE_DIR.parent
STORAGE_DIR = APP_DIR / "storage"
UPLOADS_DIR = STORAGE_DIR / "uploads"
RESULTS_DIR = STORAGE_DIR / "results"
LOGS_DIR = STORAGE_DIR / "logs"
JOBS_DIR = STORAGE_DIR / "jobs"
TRANSCRIPTS_DIR = STORAGE_DIR / "transcripts"
EXAMPLES_DIR = STORAGE_DIR / "examples"
APP_STATE_PATH = STORAGE_DIR / "app_state.json"

sys.path.insert(0, str(BASE_DIR))

from inventory_agent.agent import InventoryAgent
from inventory_agent.csv_tool import CsvSchema, OrderCsvTool
from inventory_agent.io_utils import preview_csv_rows, read_text_with_fallback
from inventory_agent.log_store import ConversationLogStore
from inventory_agent.models import AgentConfig, HumanEscalation
from inventory_agent.notifications import Notifier
from inventory_agent.kakao_tool import WindowsKakaoTool
from inventory_agent.llm import HeuristicDecisionLLMClient, TransformersDecisionLLMClient


def configure_stdio() -> None:
    for stream_name in ("stdout", "stderr"):
        stream = getattr(sys, stream_name, None)
        if stream and hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")


configure_stdio()


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def json_safe(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, dict):
        return {key: json_safe(item) for key, item in value.items()}
    if isinstance(value, list):
        return [json_safe(item) for item in value]
    return value


def ensure_storage() -> None:
    for path in (
        STORAGE_DIR,
        UPLOADS_DIR,
        RESULTS_DIR,
        LOGS_DIR,
        JOBS_DIR,
        TRANSCRIPTS_DIR,
        EXAMPLES_DIR,
    ):
        path.mkdir(parents=True, exist_ok=True)
    if not APP_STATE_PATH.exists():
        write_app_state(default_app_state())


def default_app_state() -> Dict[str, Any]:
    return {
        "config": {
            "pythonCommand": "python",
            "backend": "transformers",
            "modelId": "Qwen/Qwen3.5-4B",
            "trustRemoteCode": True,
            "responseTimeoutSeconds": 120,
            "pollIntervalSeconds": 3,
            "maxFollowUpMessages": 1,
            "transcriptTurnLimit": 10,
            "operatorGoal": "주문 CSV의 상품을 도매상에게 확인해 재고 여부를 기록합니다.",
            "targetDescription": "카카오톡 채팅 상대는 도매상 또는 재고 확인 담당자입니다.",
            "initialMessageTemplate": "안녕하세요. {item_name}{option_suffix}{quantity_suffix} 재고 있을까요?",
            "systemPrompt": (
                "답변이 명확한 재고 yes/no 가 아니면 사람 검토로 넘기고, "
                "불필요하게 길게 말하지 마세요."
            ),
            "selectedOrdersCsv": "examples/orders_example.csv",
            "selectedMappingCsv": "",
        },
        "assistantMessage": (
            "첫 실행에서 모델 다운로드가 시작될 수 있습니다. "
            "카카오톡 PC가 실행된 상태에서만 실제 문의가 동작합니다."
        ),
        "lastUpdatedAt": now_iso(),
    }


def read_app_state() -> Dict[str, Any]:
    ensure_storage()
    if not APP_STATE_PATH.exists():
        return default_app_state()
    try:
        return json.loads(APP_STATE_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return default_app_state()


def write_app_state(state: Dict[str, Any]) -> None:
    state["lastUpdatedAt"] = now_iso()
    APP_STATE_PATH.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def package_available(name: str) -> bool:
    return importlib.util.find_spec(name) is not None


def model_cache_candidates(model_id: str) -> List[Path]:
    slug = "models--" + model_id.replace("/", "--")
    roots: List[Path] = []
    if os.environ.get("HF_HOME"):
        roots.append(Path(os.environ["HF_HOME"]) / "hub")
    if os.environ.get("TRANSFORMERS_CACHE"):
        roots.append(Path(os.environ["TRANSFORMERS_CACHE"]))
    roots.append(Path.home() / ".cache" / "huggingface" / "hub")
    existing = []
    for root in roots:
        candidate = root / slug
        if candidate.exists():
            existing.append(candidate)
    return existing


def relative_storage_path(path: Path) -> str:
    return path.resolve().relative_to(STORAGE_DIR.resolve()).as_posix()


def resolve_storage_path(relative_path: str) -> Path:
    path = (STORAGE_DIR / relative_path).resolve()
    if STORAGE_DIR.resolve() not in path.parents and path != STORAGE_DIR.resolve():
        raise ValueError("path must stay inside storage/")
    return path


def list_category_files(base: Path, category: str, suffixes: Optional[Iterable[str]] = None) -> List[Dict[str, Any]]:
    files = []
    if not base.exists():
        return files
    allowed = set(suffixes or [])
    for path in sorted(base.rglob("*")):
        if not path.is_file():
            continue
        if allowed and path.suffix.lower() not in allowed:
            continue
        stat = path.stat()
        files.append(
            {
                "category": category,
                "name": path.name,
                "relativePath": relative_storage_path(path),
                "size": stat.st_size,
                "updatedAt": datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat(),
            }
        )
    return files


def tail_text(path: Path, max_chars: int = 12000) -> str:
    if not path.exists():
        return ""
    content, _ = read_text_with_fallback(path)
    return content[-max_chars:]


def preview_csv(path: Path, max_rows: int = 20) -> tuple[List[Dict[str, str]], str]:
    if not path.exists():
        return [], ""
    rows, _, encoding = preview_csv_rows(path, max_rows=max_rows)
    return rows, encoding


class JobNotifier(Notifier):
    def __init__(self, job_id: str):
        self.job_id = job_id

    def notify(self, event: HumanEscalation) -> None:
        job = read_job(self.job_id)
        events = job.setdefault("humanEscalations", [])
        events.append(json_safe(asdict(event)))
        write_job(self.job_id, job)


def job_path(job_id: str) -> Path:
    return JOBS_DIR / f"{job_id}.json"


def write_job(job_id: str, payload: Dict[str, Any]) -> None:
    payload["jobId"] = job_id
    payload["updatedAt"] = now_iso()
    job_path(job_id).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def read_job(job_id: str) -> Dict[str, Any]:
    path = job_path(job_id)
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def append_job_event(job_id: str, step: str, message: str, **extra) -> None:
    payload = read_job(job_id)
    events = payload.get("progressEvents") or []
    if not isinstance(events, list):
        events = []
    events = events[-39:]
    events.append(
        {
            "at": now_iso(),
            "step": step,
            "message": message,
            **json_safe(extra),
        }
    )
    payload["progressEvents"] = events
    write_job(job_id, payload)


def list_jobs() -> List[Dict[str, Any]]:
    jobs = []
    for path in sorted(JOBS_DIR.glob("*.json")):
        try:
            job = json.loads(path.read_text(encoding="utf-8"))
            jobs.append(job)
        except json.JSONDecodeError:
            continue
    jobs.sort(key=lambda item: item.get("updatedAt", ""), reverse=True)
    return jobs


def create_llm_client(args: argparse.Namespace):
    if args.backend == "transformers":
        return TransformersDecisionLLMClient(
            model_id=args.model_id,
            trust_remote_code=args.trust_remote_code,
        )
    return HeuristicDecisionLLMClient()


def run_agent_job(args: argparse.Namespace) -> int:
    ensure_storage()
    orders_csv = resolve_storage_path(args.orders_csv)
    mapping_csv = resolve_storage_path(args.mapping_csv) if args.mapping_csv else None
    results_csv = resolve_storage_path(args.results_csv)
    transcripts_dir = resolve_storage_path(args.transcripts_dir)
    transcripts_dir.mkdir(parents=True, exist_ok=True)

    schema = CsvSchema(
        order_id_column=args.order_id_column,
        item_name_column=args.item_name_column,
        option_column=args.option_column,
        quantity_column=args.quantity_column,
        vendor_name_column=args.vendor_name_column,
        vendor_names_column=args.vendor_names_column,
        chatroom_name_column=args.chatroom_name_column,
        chatroom_names_column=args.chatroom_names_column,
    )

    write_job(
        args.job_id,
        {
            "status": "running",
            "startedAt": now_iso(),
            "ordersCsv": args.orders_csv,
            "mappingCsv": args.mapping_csv or "",
            "resultsCsv": args.results_csv,
            "transcriptsDir": args.transcripts_dir,
            "backend": args.backend,
            "modelId": args.model_id,
            "trustRemoteCode": args.trust_remote_code,
            "operatorGoal": args.operator_goal,
            "targetDescription": args.target_description,
            "initialMessageTemplate": args.initial_message_template,
            "systemPrompt": args.system_prompt,
            "logPath": f"jobs/{args.job_id}.log",
            "currentStep": "starting",
            "assistantMessage": "작업을 시작했습니다.",
            "humanEscalations": [],
            "progressEvents": [
                {
                    "at": now_iso(),
                    "step": "starting",
                    "message": "작업을 시작했습니다.",
                }
            ],
        },
    )

    state = read_app_state()
    state["assistantMessage"] = (
        f"작업 {args.job_id} 실행 중입니다. "
        "첫 실행에서는 모델 다운로드 때문에 시간이 걸릴 수 있습니다."
    )
    write_app_state(state)

    def report_progress(step: str, message: str, **extra) -> None:
        payload = read_job(args.job_id)
        payload.update(
            {
                "status": "running",
                "currentStep": step,
                "assistantMessage": message,
            }
        )
        if extra.get("attempt_id"):
            payload["currentAttemptId"] = extra["attempt_id"]
        if extra.get("order_id"):
            payload["currentOrderId"] = extra["order_id"]
        if extra.get("item_name"):
            payload["currentItemName"] = extra["item_name"]
        if extra.get("vendor_name"):
            payload["currentVendorName"] = extra["vendor_name"]
        if extra.get("chatroom_name"):
            payload["currentChatroomName"] = extra["chatroom_name"]
        if extra.get("status"):
            payload["latestAttemptStatus"] = extra["status"]
        write_job(args.job_id, payload)
        append_job_event(args.job_id, step, message, **extra)
        print(f"[job:{args.job_id}] {step} {message}", flush=True)

    try:
        agent = InventoryAgent(
            csv_tool=OrderCsvTool(
                orders_csv_path=orders_csv,
                results_csv_path=results_csv,
                schema=schema,
                mapping_csv_path=mapping_csv,
            ),
            kakao_tool=WindowsKakaoTool(),
            llm_client=create_llm_client(args),
            notifier=JobNotifier(args.job_id),
            log_store=ConversationLogStore(transcripts_dir),
            config=AgentConfig(
                transcript_turn_limit=args.transcript_turn_limit,
                response_timeout_seconds=args.response_timeout_seconds,
                poll_interval_seconds=args.poll_interval_seconds,
                max_follow_up_messages=args.max_follow_up_messages,
                operator_goal=args.operator_goal,
                target_description=args.target_description,
                initial_message_template=args.initial_message_template,
                system_prompt=args.system_prompt,
            ),
            progress_callback=report_progress,
        )
        results = agent.run()
        payload = read_job(args.job_id)
        payload.update(
            {
                "status": "completed",
                "completedAt": now_iso(),
                "processedAttempts": len(results),
                "resultsPreview": [json_safe(asdict(result)) for result in results[:10]],
                "currentStep": "completed",
                "assistantMessage": f"작업 {args.job_id} 이(가) 완료되었습니다.",
            }
        )
        write_job(args.job_id, payload)
        append_job_event(
            args.job_id,
            "completed",
            f"작업 {args.job_id} 이(가) 완료되었습니다.",
            processed_attempts=len(results),
        )

        state = read_app_state()
        state["assistantMessage"] = (
            f"작업 {args.job_id} 완료. "
            f"{len(results)}개 문의 시도를 처리했습니다."
        )
        write_app_state(state)
        return 0
    except Exception as exc:
        payload = read_job(args.job_id)
        payload.update(
            {
                "status": "failed",
                "completedAt": now_iso(),
                "currentStep": "failed",
                "error": str(exc),
                "traceback": traceback.format_exc(),
                "assistantMessage": (
                    "작업이 실패했습니다. 카카오톡 PC 상태, CSV 내용, "
                    "모델 로딩 상태를 확인하세요."
                ),
            }
        )
        write_job(args.job_id, payload)
        append_job_event(
            args.job_id,
            "failed",
            "작업이 실패했습니다.",
            error=str(exc),
        )
        state = read_app_state()
        state["assistantMessage"] = (
            f"작업 {args.job_id} 실패: {exc}"
        )
        write_app_state(state)
        print(traceback.format_exc(), file=sys.stderr)
        return 1


def status_payload(model_id: str) -> Dict[str, Any]:
    ensure_storage()
    app_state = read_app_state()
    jobs = list_jobs()
    cache_hits = model_cache_candidates(model_id)
    packages = {
        "torch": package_available("torch"),
        "transformers": package_available("transformers"),
        "accelerate": package_available("accelerate"),
        "pywinauto": package_available("pywinauto"),
        "uiautomation": package_available("uiautomation"),
        "win32api": package_available("win32api"),
    }
    return {
        "python": {
            "executable": sys.executable,
            "version": sys.version,
            "platform": platform.platform(),
            "osName": os.name,
        },
        "packages": packages,
        "model": {
            "selectedModelId": model_id,
            "downloaded": bool(cache_hits),
            "cachePaths": [str(path) for path in cache_hits],
        },
        "storage": {
            "examples": list_category_files(EXAMPLES_DIR, "example", {".csv"}),
            "uploads": list_category_files(UPLOADS_DIR, "upload", {".csv"}),
            "results": list_category_files(RESULTS_DIR, "result", {".csv"}),
            "transcripts": list_category_files(TRANSCRIPTS_DIR, "transcript", {".md", ".txt"}),
            "jobs": list_category_files(JOBS_DIR, "job", {".json", ".log"}),
        },
        "jobs": jobs[:20],
        "appState": app_state,
        "kakaoScriptExists": (BASE_DIR / "kakao_test" / "uiautomation_kakao2.py").exists(),
    }


def bootstrap_python() -> int:
    requirements_path = BASE_DIR / "requirements.txt"
    command = [sys.executable, "-m", "pip", "install", "-r", str(requirements_path)]
    return subprocess.call(command)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Backend service CLI for Kakao LLM frontend")
    subparsers = parser.add_subparsers(dest="command", required=True)

    status_parser = subparsers.add_parser("status")
    status_parser.add_argument("--model-id", default=read_app_state().get("config", {}).get("modelId", "Qwen/Qwen3.5-4B"))

    read_file_parser = subparsers.add_parser("read-file")
    read_file_parser.add_argument("--path", required=True)

    list_files_parser = subparsers.add_parser("list-files")
    list_files_parser.add_argument("--category", choices=("all", "examples", "uploads", "results", "transcripts", "jobs"), default="all")

    run_parser = subparsers.add_parser("run-agent")
    run_parser.add_argument("--job-id", required=True)
    run_parser.add_argument("--orders-csv", required=True)
    run_parser.add_argument("--mapping-csv")
    run_parser.add_argument("--results-csv", required=True)
    run_parser.add_argument("--transcripts-dir", required=True)
    run_parser.add_argument("--backend", choices=("transformers", "heuristic"), default="transformers")
    run_parser.add_argument("--model-id", default="Qwen/Qwen3.5-4B")
    run_parser.add_argument("--trust-remote-code", action="store_true")
    run_parser.add_argument("--response-timeout-seconds", type=float, default=120.0)
    run_parser.add_argument("--poll-interval-seconds", type=float, default=3.0)
    run_parser.add_argument("--max-follow-up-messages", type=int, default=1)
    run_parser.add_argument("--transcript-turn-limit", type=int, default=10)
    run_parser.add_argument(
        "--operator-goal",
        default="주문 CSV의 상품을 도매상에게 확인해 재고 여부를 기록합니다.",
    )
    run_parser.add_argument(
        "--target-description",
        default="카카오톡 채팅 상대는 도매상 또는 재고 확인 담당자입니다.",
    )
    run_parser.add_argument(
        "--initial-message-template",
        default="안녕하세요. {item_name}{option_suffix}{quantity_suffix} 재고 있을까요?",
    )
    run_parser.add_argument(
        "--system-prompt",
        default="답변이 명확한 재고 yes/no 가 아니면 사람 검토로 넘기고, 불필요하게 길게 말하지 마세요.",
    )
    run_parser.add_argument("--order-id-column", default="order_id")
    run_parser.add_argument("--item-name-column", default="item_name")
    run_parser.add_argument("--option-column", default="option_text")
    run_parser.add_argument("--quantity-column", default="quantity")
    run_parser.add_argument("--vendor-name-column", default="vendor_name")
    run_parser.add_argument("--vendor-names-column", default="vendor_names")
    run_parser.add_argument("--chatroom-name-column", default="chatroom_name")
    run_parser.add_argument("--chatroom-names-column", default="chatroom_names")

    job_parser = subparsers.add_parser("read-job")
    job_parser.add_argument("--job-id", required=True)

    subparsers.add_parser("bootstrap-python")
    return parser


def main() -> int:
    ensure_storage()
    parser = build_parser()
    args = parser.parse_args()

    if args.command == "bootstrap-python":
        return bootstrap_python()

    if args.command == "status":
        print(json.dumps(status_payload(args.model_id), ensure_ascii=False, indent=2))
        return 0

    if args.command == "list-files":
        payload = status_payload(read_app_state().get("config", {}).get("modelId", "Qwen/Qwen3.5-4B"))["storage"]
        if args.category != "all":
            payload = {args.category: payload.get(args.category, [])}
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0

    if args.command == "read-file":
        path = resolve_storage_path(args.path)
        content, encoding = read_text_with_fallback(path) if path.exists() else ("", "")
        data = {
            "path": args.path,
            "exists": path.exists(),
            "encoding": encoding,
            "content": content,
        }
        if path.suffix.lower() == ".csv" and path.exists():
            preview, preview_encoding = preview_csv(path)
            data["preview"] = preview
            data["encoding"] = preview_encoding or encoding
        print(json.dumps(data, ensure_ascii=False, indent=2))
        return 0

    if args.command == "read-job":
        job = read_job(args.job_id)
        log_path = resolve_storage_path(job.get("logPath", f"jobs/{args.job_id}.log")) if job else JOBS_DIR / f"{args.job_id}.log"
        payload = {
            "job": job,
            "logTail": tail_text(log_path),
        }
        results_csv = job.get("resultsCsv") if job else ""
        if results_csv:
            preview, encoding = preview_csv(resolve_storage_path(results_csv))
            payload["resultsPreviewCsv"] = preview
            payload["resultsPreviewEncoding"] = encoding
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0

    if args.command == "run-agent":
        return run_agent_job(args)

    parser.error("unknown command")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
