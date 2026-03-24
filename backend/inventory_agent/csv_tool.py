from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Sequence

from inventory_agent.io_utils import read_csv_rows
from inventory_agent.models import AttemptResult, OrderAttempt, OrderTask, VendorTarget

STANDARD_RESULT_FIELDS = [
    "attempt_id",
    "order_id",
    "item_name",
    "option_text",
    "quantity",
    "vendor_name",
    "chatroom_name",
    "status",
    "response_summary",
    "transcript_path",
    "summary_path",
    "follow_up_count",
    "inquiry_message",
    "last_vendor_message",
    "human_message",
    "started_at",
    "completed_at",
]


@dataclass
class CsvSchema:
    order_id_column: str = "order_id"
    item_name_column: str = "item_name"
    option_column: str = "option_text"
    quantity_column: str = "quantity"
    vendor_name_column: str = "vendor_name"
    vendor_names_column: str = "vendor_names"
    chatroom_name_column: str = "chatroom_name"
    chatroom_names_column: str = "chatroom_names"


class OrderCsvTool:
    def __init__(
        self,
        orders_csv_path: str | Path,
        results_csv_path: str | Path,
        schema: CsvSchema | None = None,
        mapping_csv_path: str | Path | None = None,
        vendor_separator: str = "|",
    ):
        self.orders_csv_path = Path(orders_csv_path)
        self.results_csv_path = Path(results_csv_path)
        self.schema = schema or CsvSchema()
        self.mapping_csv_path = Path(mapping_csv_path) if mapping_csv_path else None
        self.vendor_separator = vendor_separator

    def load_attempts(self) -> List[OrderAttempt]:
        completed_attempt_ids = self._load_completed_attempt_ids()
        item_mappings = self._load_item_mappings()
        attempts: List[OrderAttempt] = []
        rows, _, _ = read_csv_rows(self.orders_csv_path)
        for row_index, row in enumerate(rows, start=1):
            order = self._row_to_order(row, row_index, item_mappings)
            for target in order.targets:
                attempt_id = f"{order.order_id}::{target.chatroom_name}"
                if attempt_id in completed_attempt_ids:
                    continue
                attempts.append(
                    OrderAttempt(
                        attempt_id=attempt_id,
                        order=order,
                        target=target,
                    )
                )
        return attempts

    def append_result(self, result: AttemptResult) -> None:
        self.results_csv_path.parent.mkdir(parents=True, exist_ok=True)
        result_row = dict(result.source_row)
        result_row.update(
            {
                "attempt_id": result.attempt_id,
                "order_id": result.order_id,
                "item_name": result.item_name,
                "option_text": result.option_text,
                "quantity": result.quantity,
                "vendor_name": result.vendor_name,
                "chatroom_name": result.chatroom_name,
                "status": result.status.value,
                "response_summary": result.response_summary,
                "transcript_path": result.transcript_path,
                "summary_path": result.summary_path,
                "follow_up_count": str(result.follow_up_count),
                "inquiry_message": result.inquiry_message,
                "last_vendor_message": result.last_vendor_message,
                "human_message": result.human_message,
                "started_at": result.started_at,
                "completed_at": result.completed_at,
            }
        )
        existing_fieldnames = self._existing_fieldnames()
        fieldnames = existing_fieldnames or self._merge_fieldnames(
            list(result.source_row.keys()) + STANDARD_RESULT_FIELDS
        )
        with self.results_csv_path.open("a", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fieldnames)
            if not existing_fieldnames:
                writer.writeheader()
            writer.writerow({name: result_row.get(name, "") for name in fieldnames})

    def _existing_fieldnames(self) -> List[str] | None:
        if not self.results_csv_path.exists():
            return None
        _, fieldnames, _ = read_csv_rows(self.results_csv_path)
        return fieldnames or None

    @staticmethod
    def _merge_fieldnames(fieldnames: Iterable[str]) -> List[str]:
        merged: List[str] = []
        seen = set()
        for fieldname in fieldnames:
            if fieldname in seen:
                continue
            merged.append(fieldname)
            seen.add(fieldname)
        return merged

    def _load_completed_attempt_ids(self) -> set[str]:
        if not self.results_csv_path.exists():
            return set()
        completed: set[str] = set()
        rows, _, _ = read_csv_rows(self.results_csv_path)
        for row in rows:
            attempt_id = (row.get("attempt_id") or "").strip()
            if attempt_id:
                completed.add(attempt_id)
        return completed

    def _load_item_mappings(self) -> Dict[str, List[VendorTarget]]:
        if not self.mapping_csv_path:
            return {}
        mappings: Dict[str, List[VendorTarget]] = {}
        rows, _, _ = read_csv_rows(self.mapping_csv_path)
        for row in rows:
            item_name = (row.get(self.schema.item_name_column) or row.get("item_name") or "").strip()
            vendor_name = (row.get(self.schema.vendor_name_column) or row.get("vendor_name") or "").strip()
            chatroom_name = (row.get(self.schema.chatroom_name_column) or row.get("chatroom_name") or vendor_name).strip()
            if not item_name or not vendor_name:
                continue
            mappings.setdefault(item_name, []).append(
                VendorTarget(vendor_name=vendor_name, chatroom_name=chatroom_name)
            )
        return mappings

    def _row_to_order(
        self,
        row: Dict[str, str],
        row_index: int,
        item_mappings: Dict[str, List[VendorTarget]],
    ) -> OrderTask:
        order_id = (row.get(self.schema.order_id_column) or "").strip() or f"row-{row_index}"
        item_name = self._pick_value(row, self.schema.item_name_column, ("product_name", "product", "sku", "style_name"))
        option_text = self._pick_value(row, self.schema.option_column, ("option", "options", "variant", "size_color"))
        quantity = self._pick_value(row, self.schema.quantity_column, ("qty", "count", "amount"))
        targets = self._resolve_targets(row, item_name, item_mappings)
        if not item_name:
            raise ValueError(f"item_name is missing for order row {row_index}")
        if not targets:
            raise ValueError(
                f"no vendor target found for order '{order_id}'. "
                "Provide vendor_name/vendor_names/chatroom_name or a mapping CSV."
            )
        return OrderTask(
            order_id=order_id,
            item_name=item_name,
            option_text=option_text,
            quantity=quantity,
            source_row=row,
            targets=targets,
        )

    def _resolve_targets(
        self,
        row: Dict[str, str],
        item_name: str,
        item_mappings: Dict[str, List[VendorTarget]],
    ) -> List[VendorTarget]:
        schema = self.schema
        vendor_names = self._split_values(row.get(schema.vendor_names_column, ""))
        chatroom_names = self._split_values(row.get(schema.chatroom_names_column, ""))
        if vendor_names:
            targets: List[VendorTarget] = []
            for index, vendor_name in enumerate(vendor_names):
                chatroom_name = chatroom_names[index] if index < len(chatroom_names) else vendor_name
                targets.append(VendorTarget(vendor_name=vendor_name, chatroom_name=chatroom_name))
            return targets

        vendor_name = (row.get(schema.vendor_name_column) or "").strip()
        chatroom_name = (row.get(schema.chatroom_name_column) or vendor_name).strip()
        if vendor_name or chatroom_name:
            return [VendorTarget(vendor_name=vendor_name or chatroom_name, chatroom_name=chatroom_name)]

        return list(item_mappings.get(item_name, []))

    def _split_values(self, raw_value: str) -> List[str]:
        values = [part.strip() for part in (raw_value or "").split(self.vendor_separator)]
        return [value for value in values if value]

    @staticmethod
    def _pick_value(row: Dict[str, str], primary_key: str, fallback_keys: Sequence[str]) -> str:
        value = (row.get(primary_key) or "").strip()
        if value:
            return value
        for key in fallback_keys:
            value = (row.get(key) or "").strip()
            if value:
                return value
        return ""
