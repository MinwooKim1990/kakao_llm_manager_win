from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional


class AttemptStatus(str, Enum):
    AVAILABLE = "available"
    UNAVAILABLE = "unavailable"
    PARTIAL_OR_VARIANT_NEEDED = "partial_or_variant_needed"
    AWAITING_REPLY = "awaiting_reply"
    PENDING_HUMAN = "pending_human"
    FAILED = "failed"


TERMINAL_STATUSES = {
    AttemptStatus.AVAILABLE,
    AttemptStatus.UNAVAILABLE,
    AttemptStatus.PARTIAL_OR_VARIANT_NEEDED,
    AttemptStatus.AWAITING_REPLY,
    AttemptStatus.PENDING_HUMAN,
    AttemptStatus.FAILED,
}


class AgentAction(str, Enum):
    SEND_MESSAGE = "send_message"
    WAIT_FOR_REPLY = "wait_for_reply"
    COMPLETE_ATTEMPT = "complete_attempt"
    NOTIFY_HUMAN = "notify_human"


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


@dataclass
class VendorTarget:
    vendor_name: str
    chatroom_name: str


@dataclass
class OrderTask:
    order_id: str
    item_name: str
    option_text: str = ""
    quantity: str = ""
    source_row: Dict[str, str] = field(default_factory=dict)
    targets: List[VendorTarget] = field(default_factory=list)


@dataclass
class OrderAttempt:
    attempt_id: str
    order: OrderTask
    target: VendorTarget


@dataclass
class ChatTurn:
    role: str
    message: str
    timestamp: str = field(default_factory=utc_now_iso)
    meta: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ChatObservation:
    full_text: str
    new_text: str = ""
    timed_out: bool = False


@dataclass
class SendResult:
    success: bool
    error: Optional[str] = None
    transcript: Optional[str] = None


@dataclass
class AgentDecision:
    action: AgentAction
    message_text: str = ""
    status: Optional[AttemptStatus] = None
    summary: str = ""
    rationale: str = ""
    human_message: str = ""


@dataclass
class HumanEscalation:
    attempt_id: str
    vendor_name: str
    chatroom_name: str
    item_name: str
    reason: str
    transcript_tail: str = ""
    status: AttemptStatus = AttemptStatus.PENDING_HUMAN


@dataclass
class AttemptResult:
    attempt_id: str
    order_id: str
    item_name: str
    option_text: str
    quantity: str
    vendor_name: str
    chatroom_name: str
    status: AttemptStatus
    response_summary: str
    transcript_path: str
    summary_path: str
    follow_up_count: int
    inquiry_message: str
    last_vendor_message: str
    human_message: str
    started_at: str
    completed_at: str
    source_row: Dict[str, str] = field(default_factory=dict)


@dataclass
class AgentConfig:
    transcript_turn_limit: int = 10
    response_timeout_seconds: float = 120.0
    poll_interval_seconds: float = 3.0
    max_follow_up_messages: int = 1
    max_steps_per_attempt: int = 6
    operator_goal: str = "주문 CSV의 상품을 도매상에게 확인해 재고 여부를 기록합니다."
    target_description: str = "카카오톡 채팅 상대는 도매상 또는 재고 확인 담당자입니다."
    initial_message_template: str = (
        "안녕하세요. {item_name}{option_suffix}{quantity_suffix} 재고 있을까요?"
    )
    system_prompt: str = ""


@dataclass
class DecisionContext:
    attempt: OrderAttempt
    transcript_summary: str
    recent_turns: List[ChatTurn]
    new_vendor_message: str
    initial_message_sent: bool
    follow_up_count: int
    no_reply_count: int
    max_follow_up_messages: int
    operator_goal: str
    target_description: str
    initial_message_template: str
    system_prompt: str
