from __future__ import annotations

import importlib.util
import os
import time
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Dict, List, Optional

from inventory_agent.models import ChatObservation, SendResult


def diff_transcript(previous_text: str, current_text: str) -> str:
    previous = (previous_text or "").strip()
    current = (current_text or "").strip()
    if not previous:
        return current
    if current.startswith(previous):
        return current[len(previous) :].strip()
    return current


class KakaoTool(ABC):
    @abstractmethod
    def open_room(self, chatroom_name: str) -> None:
        raise NotImplementedError

    @abstractmethod
    def read_transcript(self, chatroom_name: str) -> str:
        raise NotImplementedError

    @abstractmethod
    def send_message(self, chatroom_name: str, text: str) -> SendResult:
        raise NotImplementedError

    def wait_for_new_messages(
        self,
        chatroom_name: str,
        previous_text: str,
        timeout_seconds: float,
        poll_interval_seconds: float,
    ) -> ChatObservation:
        deadline = time.monotonic() + timeout_seconds
        while time.monotonic() < deadline:
            current_text = self.read_transcript(chatroom_name)
            new_text = diff_transcript(previous_text, current_text)
            if new_text:
                return ChatObservation(full_text=current_text, new_text=new_text, timed_out=False)
            time.sleep(poll_interval_seconds)
        return ChatObservation(full_text=previous_text, new_text="", timed_out=True)


class WindowsKakaoTool(KakaoTool):
    def __init__(self, script_path: str | Path | None = None):
        base_dir = Path(__file__).resolve().parents[1]
        self.script_path = Path(script_path) if script_path else base_dir / "kakao_test" / "uiautomation_kakao2.py"
        self._module = None

    def _load_module(self):
        if self._module is not None:
            return self._module
        if os.name != "nt":
            raise RuntimeError("WindowsKakaoTool can only run on Windows.")
        spec = importlib.util.spec_from_file_location("inventory_windows_kakao", self.script_path)
        if spec is None or spec.loader is None:
            raise RuntimeError(f"failed to load Kakao automation script: {self.script_path}")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        self._module = module
        return module

    def open_room(self, chatroom_name: str) -> None:
        module = self._load_module()
        module.open_chatroom(chatroom_name)

    def read_transcript(self, chatroom_name: str) -> str:
        module = self._load_module()
        return module.get_chat_text(chatroom_name)

    def send_message(self, chatroom_name: str, text: str) -> SendResult:
        module = self._load_module()
        success = module.send_message_and_verify(chatroom_name, text)
        transcript = None
        try:
            transcript = module.get_chat_text(chatroom_name)
        except Exception:
            transcript = None
        return SendResult(success=bool(success), transcript=transcript)


class MockKakaoTool(KakaoTool):
    def __init__(self, scripted_vendor_replies: Optional[Dict[str, List[Optional[str]]]] = None):
        self.scripted_vendor_replies = scripted_vendor_replies or {}
        self.transcripts: Dict[str, str] = {}
        self.sent_messages: Dict[str, List[str]] = {}

    def open_room(self, chatroom_name: str) -> None:
        self.transcripts.setdefault(chatroom_name, "")
        self.sent_messages.setdefault(chatroom_name, [])

    def read_transcript(self, chatroom_name: str) -> str:
        self.open_room(chatroom_name)
        return self.transcripts[chatroom_name]

    def send_message(self, chatroom_name: str, text: str) -> SendResult:
        self.open_room(chatroom_name)
        self.sent_messages[chatroom_name].append(text)
        self._append_line(chatroom_name, f"AGENT: {text}")
        return SendResult(success=True, transcript=self.transcripts[chatroom_name])

    def wait_for_new_messages(
        self,
        chatroom_name: str,
        previous_text: str,
        timeout_seconds: float,
        poll_interval_seconds: float,
    ) -> ChatObservation:
        self.open_room(chatroom_name)
        queue = self.scripted_vendor_replies.setdefault(chatroom_name, [])
        if not queue:
            return ChatObservation(full_text=previous_text, new_text="", timed_out=True)
        next_message = queue.pop(0)
        if not next_message:
            return ChatObservation(full_text=previous_text, new_text="", timed_out=True)
        self._append_line(chatroom_name, f"VENDOR: {next_message}")
        return ChatObservation(
            full_text=self.transcripts[chatroom_name],
            new_text=next_message,
            timed_out=False,
        )

    def get_sent_messages(self, chatroom_name: str) -> List[str]:
        return list(self.sent_messages.get(chatroom_name, []))

    def _append_line(self, chatroom_name: str, line: str) -> None:
        current = self.transcripts.get(chatroom_name, "")
        if current:
            current += "\n"
        current += line
        self.transcripts[chatroom_name] = current
