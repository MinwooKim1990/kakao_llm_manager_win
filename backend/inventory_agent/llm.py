from __future__ import annotations

import ast
import json
import sys
from abc import ABC, abstractmethod
from typing import Dict, List

from inventory_agent.models import (
    AgentAction,
    AgentDecision,
    AttemptStatus,
    DecisionContext,
)

BASE_SYSTEM_PROMPT = """You are an inventory-checking sales assistant.
You only help with KakaoTalk stock checks between the seller and wholesalers.
Choose exactly one action and respond with JSON only.

Valid actions:
- send_message
- wait_for_reply
- complete_attempt
- notify_human

Valid statuses:
- available
- unavailable
- partial_or_variant_needed
- awaiting_reply
- pending_human
- failed

Rules:
- Keep outbound Kakao messages concise and natural Korean.
- If the wholesaler confirms stock, complete with available.
- If the wholesaler says there is no stock, complete with unavailable.
- If the reply needs human judgment, color/size negotiation, pricing, or anything outside a simple stock yes/no check, notify_human.
- If there is no reply yet, either wait_for_reply or send one follow-up reminder.
- Never output markdown. Output JSON only.
"""


class DecisionLLMClient(ABC):
    @abstractmethod
    def decide(self, context: DecisionContext) -> AgentDecision:
        raise NotImplementedError


def build_prompt(context: DecisionContext) -> List[Dict[str, str]]:
    attempt = context.attempt
    recent_turns = [
        {
            "role": turn.role,
            "message": turn.message,
            "timestamp": turn.timestamp,
            "meta": turn.meta,
        }
        for turn in context.recent_turns
    ]
    user_payload = {
        "order_id": attempt.order.order_id,
        "item_name": attempt.order.item_name,
        "option_text": attempt.order.option_text,
        "quantity": attempt.order.quantity,
        "vendor_name": attempt.target.vendor_name,
        "chatroom_name": attempt.target.chatroom_name,
        "operator_goal": context.operator_goal,
        "target_description": context.target_description,
        "initial_message_template": context.initial_message_template,
        "transcript_summary": context.transcript_summary,
        "recent_turns": recent_turns,
        "new_vendor_message": context.new_vendor_message,
        "initial_message_sent": context.initial_message_sent,
        "follow_up_count": context.follow_up_count,
        "no_reply_count": context.no_reply_count,
        "max_follow_up_messages": context.max_follow_up_messages,
    }
    system_prompt = build_system_prompt(context)
    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": json.dumps(user_payload, ensure_ascii=False, indent=2)},
    ]


def build_system_prompt(context: DecisionContext) -> str:
    sections = [
        BASE_SYSTEM_PROMPT.strip(),
        f"Operator goal:\n{context.operator_goal.strip()}",
        f"Target description:\n{context.target_description.strip()}",
        (
            "When sending the very first Kakao message, prefer the provided "
            "initial_message_template and fill placeholders naturally."
        ),
    ]
    if context.system_prompt.strip():
        sections.append(f"Additional system instructions:\n{context.system_prompt.strip()}")
    return "\n\n".join(section for section in sections if section.strip())


def render_initial_message(template: str, context: DecisionContext) -> str:
    order = context.attempt.order
    option_suffix = f", 옵션 {order.option_text}" if order.option_text else ""
    quantity_suffix = f", 수량 {order.quantity}" if order.quantity else ""
    mapping = {
        "order_id": order.order_id,
        "item_name": order.item_name,
        "option_text": order.option_text,
        "quantity": order.quantity,
        "vendor_name": context.attempt.target.vendor_name,
        "chatroom_name": context.attempt.target.chatroom_name,
        "option_suffix": option_suffix,
        "quantity_suffix": quantity_suffix,
    }
    try:
        rendered = template.format_map(_SafeDict(mapping)).strip()
    except Exception:
        rendered = ""
    return rendered or f"안녕하세요. {order.item_name}{option_suffix}{quantity_suffix} 재고 있을까요?"


class _SafeDict(dict):
    def __missing__(self, key):
        return ""


def parse_decision(text: str) -> AgentDecision:
    candidate = _extract_json_object(text)
    payload = _load_structured_payload(candidate)
    status = payload.get("status")
    return AgentDecision(
        action=AgentAction(payload["action"]),
        message_text=(payload.get("message_text") or "").strip(),
        status=AttemptStatus(status) if status else None,
        summary=(payload.get("summary") or "").strip(),
        rationale=(payload.get("rationale") or "").strip(),
        human_message=(payload.get("human_message") or "").strip(),
    )


def _extract_json_object(text: str) -> str:
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or start >= end:
        raise ValueError("no JSON object found in model output")
    return text[start : end + 1]


def _load_structured_payload(candidate: str) -> Dict[str, str]:
    try:
        payload = json.loads(candidate)
        if isinstance(payload, dict):
            return payload
    except json.JSONDecodeError:
        pass

    try:
        payload = ast.literal_eval(candidate)
        if isinstance(payload, dict):
            return payload
    except (SyntaxError, ValueError):
        pass

    normalized = _normalize_loose_object(candidate)
    payload = json.loads(normalized)
    if not isinstance(payload, dict):
        raise ValueError("model output is not an object")
    return payload


def _normalize_loose_object(candidate: str) -> str:
    normalized = candidate.strip()
    replacements = {
        "True": "true",
        "False": "false",
        "None": "null",
    }
    for source, target in replacements.items():
        normalized = normalized.replace(source, target)
    for key in ("action", "message_text", "status", "summary", "rationale", "human_message"):
        normalized = normalized.replace(f"'{key}'", f'"{key}"')
    return normalized


class HeuristicDecisionLLMClient(DecisionLLMClient):
    def decide(self, context: DecisionContext) -> AgentDecision:
        if not context.initial_message_sent:
            return AgentDecision(
                action=AgentAction.SEND_MESSAGE,
                message_text=self._build_initial_message(context),
                summary=f"{context.attempt.order.item_name} 재고 문의 시작",
                rationale="초기 문의 메시지를 전송합니다.",
            )

        vendor_text = context.new_vendor_message.strip()
        if not vendor_text:
            if context.follow_up_count < context.max_follow_up_messages:
                return AgentDecision(
                    action=AgentAction.SEND_MESSAGE,
                    message_text="혹시 위 상품 재고 확인 가능하실까요?",
                    summary="무응답으로 1회 재문의",
                    rationale="응답이 없어 한 번만 재문의합니다.",
                )
            return AgentDecision(
                action=AgentAction.NOTIFY_HUMAN,
                status=AttemptStatus.AWAITING_REPLY,
                summary="응답 지연으로 사람 검토 필요",
                rationale="재문의 후에도 응답이 없습니다.",
                human_message="도매상 응답이 없어 사람이 이어서 확인해야 합니다.",
            )

        normalized = vendor_text.replace(" ", "").lower()
        if any(token in normalized for token in ("사이즈", "색상", "컬러", "옵션", "부분", "일부")):
            if any(token in normalized for token in ("있", "가능", "재고")):
                return AgentDecision(
                    action=AgentAction.NOTIFY_HUMAN,
                    status=AttemptStatus.PARTIAL_OR_VARIANT_NEEDED,
                    summary=vendor_text,
                    rationale="부분 가능 또는 옵션 확인이 필요합니다.",
                    human_message="도매상이 일부 옵션만 가능하거나 추가 조건을 물었습니다.",
                )
            return AgentDecision(
                action=AgentAction.NOTIFY_HUMAN,
                status=AttemptStatus.PENDING_HUMAN,
                summary=vendor_text,
                rationale="추가 정보 요청으로 사람이 이어받아야 합니다.",
                human_message="도매상이 재고 외 추가 정보를 요구했습니다.",
            )

        if any(token in normalized for token in ("없", "품절", "안돼", "불가")):
            return AgentDecision(
                action=AgentAction.COMPLETE_ATTEMPT,
                status=AttemptStatus.UNAVAILABLE,
                summary=vendor_text,
                rationale="재고 없음으로 판정했습니다.",
            )

        if any(token in normalized for token in ("있", "가능", "보유", "재고")):
            return AgentDecision(
                action=AgentAction.COMPLETE_ATTEMPT,
                status=AttemptStatus.AVAILABLE,
                summary=vendor_text,
                rationale="재고 있음으로 판정했습니다.",
            )

        return AgentDecision(
            action=AgentAction.NOTIFY_HUMAN,
            status=AttemptStatus.PENDING_HUMAN,
            summary=vendor_text,
            rationale="애매한 답변이라 사람이 판단해야 합니다.",
            human_message="도매상 답변이 yes/no 로 명확하지 않습니다.",
        )

    @staticmethod
    def _build_initial_message(context: DecisionContext) -> str:
        return render_initial_message(context.initial_message_template, context)


class TransformersDecisionLLMClient(DecisionLLMClient):
    def __init__(
        self,
        model_id: str,
        max_new_tokens: int = 256,
        temperature: float = 0.1,
        trust_remote_code: bool = False,
    ):
        try:
            from transformers import AutoModelForCausalLM, AutoTokenizer
        except ImportError as exc:
            raise RuntimeError(
                "transformers is not installed. Install it before using the transformers backend."
            ) from exc

        self.model_id = model_id
        self.max_new_tokens = max_new_tokens
        self.temperature = temperature
        self.trust_remote_code = trust_remote_code
        self.tokenizer, self.model, self.trust_remote_code = self._load_model(
            AutoTokenizer=AutoTokenizer,
            AutoModelForCausalLM=AutoModelForCausalLM,
            model_id=model_id,
            trust_remote_code=trust_remote_code,
        )

    @staticmethod
    def _load_model(AutoTokenizer, AutoModelForCausalLM, model_id: str, trust_remote_code: bool):
        def _load(use_trust_remote_code: bool):
            tokenizer = AutoTokenizer.from_pretrained(
                model_id,
                trust_remote_code=use_trust_remote_code,
            )
            model = AutoModelForCausalLM.from_pretrained(
                model_id,
                trust_remote_code=use_trust_remote_code,
                torch_dtype="auto",
                device_map="auto",
            )
            return tokenizer, model, use_trust_remote_code

        try:
            return _load(trust_remote_code)
        except ValueError as exc:
            message = str(exc)
            if "qwen3_5" in message and not trust_remote_code:
                return _load(True)
            raise

    def decide(self, context: DecisionContext) -> AgentDecision:
        messages = build_prompt(context)
        prompt = self._render_prompt(messages)
        encoded = self.tokenizer(prompt, return_tensors="pt").to(self.model.device)
        output_ids = self.model.generate(
            **encoded,
            max_new_tokens=self.max_new_tokens,
            do_sample=self.temperature > 0,
            temperature=self.temperature,
            pad_token_id=self.tokenizer.eos_token_id,
        )
        generated_ids = output_ids[:, encoded["input_ids"].shape[1] :]
        text = self.tokenizer.decode(generated_ids[0], skip_special_tokens=True)
        try:
            return parse_decision(text)
        except Exception as exc:
            print("[llm] structured parse failed, falling back to heuristic decision", file=sys.stderr)
            print(f"[llm] parse_error={exc}", file=sys.stderr)
            print(f"[llm] raw_output={text[:2000]}", file=sys.stderr)
            return HeuristicDecisionLLMClient().decide(context)

    def _render_prompt(self, messages: List[Dict[str, str]]) -> str:
        if hasattr(self.tokenizer, "apply_chat_template"):
            return self.tokenizer.apply_chat_template(
                messages,
                tokenize=False,
                add_generation_prompt=True,
            )
        return "\n".join(f"{message['role'].upper()}: {message['content']}" for message in messages)
