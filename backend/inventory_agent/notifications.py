from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import asdict
from typing import Iterable

from inventory_agent.models import HumanEscalation

logger = logging.getLogger(__name__)


class Notifier(ABC):
    @abstractmethod
    def notify(self, event: HumanEscalation) -> None:
        raise NotImplementedError


class ConsoleNotifier(Notifier):
    def notify(self, event: HumanEscalation) -> None:
        logger.warning(
            "human escalation attempt_id=%s vendor=%s status=%s reason=%s",
            event.attempt_id,
            event.vendor_name,
            event.status.value,
            event.reason,
        )


class WebhookNotifier(Notifier):
    def __init__(self, url: str, timeout_seconds: float = 10.0):
        self.url = url
        self.timeout_seconds = timeout_seconds

    def notify(self, event: HumanEscalation) -> None:
        import httpx

        payload = asdict(event)
        payload["status"] = event.status.value
        with httpx.Client(timeout=self.timeout_seconds) as client:
            response = client.post(self.url, json=payload)
            response.raise_for_status()


class CompositeNotifier(Notifier):
    def __init__(self, notifiers: Iterable[Notifier]):
        self.notifiers = list(notifiers)

    def notify(self, event: HumanEscalation) -> None:
        for notifier in self.notifiers:
            notifier.notify(event)
