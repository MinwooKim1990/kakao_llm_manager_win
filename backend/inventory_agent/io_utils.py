from __future__ import annotations

import csv
import io
from pathlib import Path
from typing import Dict, Iterable, List, Tuple

TEXT_READ_ENCODINGS: Tuple[str, ...] = (
    "utf-8-sig",
    "utf-8",
    "cp949",
    "euc-kr",
    "utf-16",
)


def read_text_with_fallback(path: str | Path) -> tuple[str, str]:
    target = Path(path)
    data = target.read_bytes()
    for encoding in TEXT_READ_ENCODINGS:
        try:
            return data.decode(encoding), encoding
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace"), "utf-8-replace"


def read_csv_rows(path: str | Path) -> tuple[List[Dict[str, str]], List[str], str]:
    content, encoding = read_text_with_fallback(path)
    reader = csv.DictReader(io.StringIO(content, newline=""))
    rows = list(reader)
    return rows, list(reader.fieldnames or []), encoding


def preview_csv_rows(path: str | Path, max_rows: int = 20) -> tuple[List[Dict[str, str]], List[str], str]:
    rows, fieldnames, encoding = read_csv_rows(path)
    return rows[:max_rows], fieldnames, encoding
