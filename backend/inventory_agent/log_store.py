from __future__ import annotations

import json
import re
from pathlib import Path
from typing import List

from inventory_agent.models import ChatTurn

TURN_PREFIX = "--- TURN "
TURN_END = "--- END TURN"


def _sanitize_name(value: str) -> str:
    cleaned = re.sub(r"[^0-9A-Za-z가-힣._-]+", "_", value.strip())
    return cleaned or "unknown"


class ConversationLogStore:
    def __init__(self, base_dir: str | Path):
        self.base_dir = Path(base_dir)
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def transcript_path(self, room_name: str) -> Path:
        return self.base_dir / f"{_sanitize_name(room_name)}.md"

    def summary_path(self, room_name: str) -> Path:
        return self.base_dir / f"{_sanitize_name(room_name)}.summary.txt"

    def append_turn(self, room_name: str, turn: ChatTurn) -> Path:
        path = self.transcript_path(room_name)
        header = json.dumps(
            {
                "timestamp": turn.timestamp,
                "role": turn.role,
                "meta": turn.meta,
            },
            ensure_ascii=False,
            sort_keys=True,
        )
        with path.open("a", encoding="utf-8") as handle:
            handle.write(f"{TURN_PREFIX}{header}\n")
            handle.write(f"{turn.message.rstrip()}\n")
            handle.write(f"{TURN_END}\n")
        return path

    def load_recent_turns(self, room_name: str, limit: int) -> List[ChatTurn]:
        path = self.transcript_path(room_name)
        if not path.exists():
            return []
        turns: List[ChatTurn] = []
        current_header = None
        buffer: List[str] = []
        for raw_line in path.read_text(encoding="utf-8").splitlines():
            if raw_line.startswith(TURN_PREFIX):
                current_header = json.loads(raw_line[len(TURN_PREFIX) :])
                buffer = []
                continue
            if raw_line == TURN_END and current_header is not None:
                turns.append(
                    ChatTurn(
                        role=current_header["role"],
                        timestamp=current_header["timestamp"],
                        message="\n".join(buffer).strip(),
                        meta=current_header.get("meta", {}),
                    )
                )
                current_header = None
                buffer = []
                continue
            if current_header is not None:
                buffer.append(raw_line)
        return turns[-limit:]

    def read_summary(self, room_name: str) -> str:
        path = self.summary_path(room_name)
        if not path.exists():
            return ""
        return path.read_text(encoding="utf-8").strip()

    def write_summary(self, room_name: str, summary: str) -> Path:
        path = self.summary_path(room_name)
        path.write_text(summary.strip() + "\n", encoding="utf-8")
        return path
