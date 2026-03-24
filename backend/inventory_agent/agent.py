from __future__ import annotations

from typing import Callable, Optional

from inventory_agent.csv_tool import OrderCsvTool
from inventory_agent.kakao_tool import KakaoTool
from inventory_agent.llm import DecisionLLMClient
from inventory_agent.log_store import ConversationLogStore
from inventory_agent.models import (
    AgentAction,
    AgentConfig,
    AttemptResult,
    AttemptStatus,
    ChatTurn,
    DecisionContext,
    HumanEscalation,
    OrderAttempt,
    utc_now_iso,
)
from inventory_agent.notifications import Notifier


class InventoryAgent:
    def __init__(
        self,
        csv_tool: OrderCsvTool,
        kakao_tool: KakaoTool,
        llm_client: DecisionLLMClient,
        notifier: Notifier,
        log_store: ConversationLogStore,
        config: AgentConfig | None = None,
        progress_callback: Optional[Callable[..., None]] = None,
    ):
        self.csv_tool = csv_tool
        self.kakao_tool = kakao_tool
        self.llm_client = llm_client
        self.notifier = notifier
        self.log_store = log_store
        self.config = config or AgentConfig()
        self.progress_callback = progress_callback

    def run(self) -> list[AttemptResult]:
        results = []
        for attempt in self.csv_tool.load_attempts():
            self._report_progress(
                "attempt_start",
                f"{attempt.target.chatroom_name} 대상으로 {attempt.order.item_name} 문의를 시작합니다.",
                attempt=attempt,
            )
            results.append(self.run_attempt(attempt))
        return results

    def run_attempt(self, attempt: OrderAttempt) -> AttemptResult:
        started_at = utc_now_iso()
        room_name = attempt.target.chatroom_name
        self._report_progress("open_room", f"채팅방 '{room_name}' 을(를) 여는 중입니다.", attempt=attempt)
        self.kakao_tool.open_room(room_name)
        self._report_progress("read_transcript", "기존 대화 내용을 읽는 중입니다.", attempt=attempt)
        previous_transcript = self.kakao_tool.read_transcript(room_name)
        recent_turns = self.log_store.load_recent_turns(
            room_name,
            self.config.transcript_turn_limit,
        )
        transcript_summary = self.log_store.read_summary(room_name)
        initial_message_sent = False
        follow_up_count = 0
        no_reply_count = 0
        inquiry_message = ""
        last_vendor_message = ""

        for _ in range(self.config.max_steps_per_attempt):
            context = DecisionContext(
                attempt=attempt,
                transcript_summary=transcript_summary,
                recent_turns=recent_turns,
                new_vendor_message=last_vendor_message,
                initial_message_sent=initial_message_sent,
                follow_up_count=follow_up_count,
                no_reply_count=no_reply_count,
                max_follow_up_messages=self.config.max_follow_up_messages,
                operator_goal=self.config.operator_goal,
                target_description=self.config.target_description,
                initial_message_template=self.config.initial_message_template,
                system_prompt=self.config.system_prompt,
            )
            self._report_progress("llm_decide", "모델이 다음 행동을 결정하는 중입니다.", attempt=attempt)
            decision = self.llm_client.decide(context)
            if decision.summary:
                transcript_summary = decision.summary
                self.log_store.write_summary(room_name, transcript_summary)

            if decision.action == AgentAction.SEND_MESSAGE:
                self._report_progress(
                    "send_message",
                    f"메시지 전송: {decision.message_text[:120]}",
                    attempt=attempt,
                )
                send_result = self.kakao_tool.send_message(room_name, decision.message_text)
                self.log_store.append_turn(
                    room_name,
                    ChatTurn(
                        role="agent",
                        message=decision.message_text,
                        meta={
                            "attempt_id": attempt.attempt_id,
                            "vendor_name": attempt.target.vendor_name,
                        },
                    ),
                )
                recent_turns = self.log_store.load_recent_turns(
                    room_name,
                    self.config.transcript_turn_limit,
                )
                inquiry_message = inquiry_message or decision.message_text
                if initial_message_sent:
                    follow_up_count += 1
                initial_message_sent = True
                if not send_result.success:
                    return self._complete_attempt(
                        attempt=attempt,
                        started_at=started_at,
                        status=AttemptStatus.FAILED,
                        response_summary=decision.summary or send_result.error or "메시지 전송 실패",
                        transcript_summary=transcript_summary,
                        inquiry_message=inquiry_message,
                        last_vendor_message=last_vendor_message,
                        follow_up_count=follow_up_count,
                        human_message=send_result.error or "카카오톡 메시지 전송에 실패했습니다.",
                        notify_human=True,
                    )
                self._report_progress("wait_reply", "상대 답장을 기다리는 중입니다.", attempt=attempt)
                observation = self.kakao_tool.wait_for_new_messages(
                    room_name,
                    send_result.transcript or previous_transcript,
                    timeout_seconds=self.config.response_timeout_seconds,
                    poll_interval_seconds=self.config.poll_interval_seconds,
                )
                previous_transcript = observation.full_text
                if observation.timed_out:
                    last_vendor_message = ""
                    no_reply_count += 1
                    self._report_progress("reply_timeout", "응답 대기 시간이 초과되었습니다.", attempt=attempt)
                    continue
                last_vendor_message = observation.new_text.strip()
                no_reply_count = 0
                self._report_progress(
                    "reply_received",
                    f"답장 수신: {last_vendor_message[:120]}",
                    attempt=attempt,
                )
                self.log_store.append_turn(
                    room_name,
                    ChatTurn(
                        role="vendor",
                        message=last_vendor_message,
                        meta={
                            "attempt_id": attempt.attempt_id,
                            "vendor_name": attempt.target.vendor_name,
                        },
                    ),
                )
                recent_turns = self.log_store.load_recent_turns(
                    room_name,
                    self.config.transcript_turn_limit,
                )
                continue

            if decision.action == AgentAction.WAIT_FOR_REPLY:
                self._report_progress("wait_reply", "상대 답장을 기다리는 중입니다.", attempt=attempt)
                observation = self.kakao_tool.wait_for_new_messages(
                    room_name,
                    previous_transcript,
                    timeout_seconds=self.config.response_timeout_seconds,
                    poll_interval_seconds=self.config.poll_interval_seconds,
                )
                previous_transcript = observation.full_text
                if observation.timed_out:
                    last_vendor_message = ""
                    no_reply_count += 1
                    self._report_progress("reply_timeout", "응답 대기 시간이 초과되었습니다.", attempt=attempt)
                    continue
                last_vendor_message = observation.new_text.strip()
                no_reply_count = 0
                self._report_progress(
                    "reply_received",
                    f"답장 수신: {last_vendor_message[:120]}",
                    attempt=attempt,
                )
                self.log_store.append_turn(
                    room_name,
                    ChatTurn(
                        role="vendor",
                        message=last_vendor_message,
                        meta={
                            "attempt_id": attempt.attempt_id,
                            "vendor_name": attempt.target.vendor_name,
                        },
                    ),
                )
                recent_turns = self.log_store.load_recent_turns(
                    room_name,
                    self.config.transcript_turn_limit,
                )
                continue

            if decision.action == AgentAction.COMPLETE_ATTEMPT:
                status = decision.status or AttemptStatus.PENDING_HUMAN
                return self._complete_attempt(
                    attempt=attempt,
                    started_at=started_at,
                    status=status,
                    response_summary=decision.summary or last_vendor_message,
                    transcript_summary=transcript_summary,
                    inquiry_message=inquiry_message,
                    last_vendor_message=last_vendor_message,
                    follow_up_count=follow_up_count,
                    human_message="",
                    notify_human=False,
                )

            if decision.action == AgentAction.NOTIFY_HUMAN:
                status = decision.status or AttemptStatus.PENDING_HUMAN
                return self._complete_attempt(
                    attempt=attempt,
                    started_at=started_at,
                    status=status,
                    response_summary=decision.summary or last_vendor_message,
                    transcript_summary=transcript_summary,
                    inquiry_message=inquiry_message,
                    last_vendor_message=last_vendor_message,
                    follow_up_count=follow_up_count,
                    human_message=decision.human_message or decision.rationale,
                    notify_human=True,
                )

        fallback_status = AttemptStatus.PENDING_HUMAN if last_vendor_message else AttemptStatus.FAILED
        fallback_message = (
            "최대 단계 수를 초과해 사람이 확인해야 합니다."
            if last_vendor_message
            else "최대 단계 수를 초과했고 응답도 받지 못했습니다."
        )
        return self._complete_attempt(
            attempt=attempt,
            started_at=started_at,
            status=fallback_status,
            response_summary=transcript_summary or last_vendor_message or fallback_message,
            transcript_summary=transcript_summary,
            inquiry_message=inquiry_message,
            last_vendor_message=last_vendor_message,
            follow_up_count=follow_up_count,
            human_message=fallback_message,
            notify_human=True,
        )

    def _complete_attempt(
        self,
        attempt: OrderAttempt,
        started_at: str,
        status: AttemptStatus,
        response_summary: str,
        transcript_summary: str,
        inquiry_message: str,
        last_vendor_message: str,
        follow_up_count: int,
        human_message: str,
        notify_human: bool,
    ) -> AttemptResult:
        room_name = attempt.target.chatroom_name
        transcript_path = self.log_store.transcript_path(room_name)
        summary_path = self.log_store.summary_path(room_name)
        if transcript_summary:
            self.log_store.write_summary(room_name, transcript_summary)
        result = AttemptResult(
            attempt_id=attempt.attempt_id,
            order_id=attempt.order.order_id,
            item_name=attempt.order.item_name,
            option_text=attempt.order.option_text,
            quantity=attempt.order.quantity,
            vendor_name=attempt.target.vendor_name,
            chatroom_name=room_name,
            status=status,
            response_summary=response_summary.strip(),
            transcript_path=str(transcript_path),
            summary_path=str(summary_path),
            follow_up_count=follow_up_count,
            inquiry_message=inquiry_message,
            last_vendor_message=last_vendor_message,
            human_message=human_message,
            started_at=started_at,
            completed_at=utc_now_iso(),
            source_row=attempt.order.source_row,
        )
        self.csv_tool.append_result(result)
        if notify_human:
            self.notifier.notify(
                HumanEscalation(
                    attempt_id=attempt.attempt_id,
                    vendor_name=attempt.target.vendor_name,
                    chatroom_name=room_name,
                    item_name=attempt.order.item_name,
                    reason=human_message or response_summary,
                    transcript_tail=last_vendor_message,
                    status=status,
                )
            )
        self._report_progress(
            "attempt_complete",
            f"작업 종료: status={status.value} summary={response_summary[:120]}",
            attempt=attempt,
            status=status.value,
        )
        return result

    def _report_progress(self, step: str, message: str, attempt: OrderAttempt | None = None, **extra) -> None:
        if not self.progress_callback:
            return
        payload = dict(extra)
        if attempt is not None:
            payload.update(
                {
                    "attempt_id": attempt.attempt_id,
                    "order_id": attempt.order.order_id,
                    "item_name": attempt.order.item_name,
                    "vendor_name": attempt.target.vendor_name,
                    "chatroom_name": attempt.target.chatroom_name,
                }
            )
        self.progress_callback(step=step, message=message, **payload)
