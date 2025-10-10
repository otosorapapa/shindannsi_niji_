from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

TAB_LABELS: Tuple[str, str, str] = ("講師A", "講師B", "採点観点")
CUSTOM_SLOT_PATH = Path("data/custom_model_slots.json")


def _empty_state() -> Dict[str, Any]:
    return {"entries": [], "index": {}, "errors": []}


def empty_state() -> Dict[str, Any]:
    """Return an empty state dictionary for custom slots."""

    return _empty_state()


def _build_state(entries: List[Dict[str, Any]], errors: Optional[List[str]] = None) -> Dict[str, Any]:
    return {
        "entries": entries,
        "index": _build_index(entries),
        "errors": errors or [],
    }


def load_custom_slots() -> Dict[str, Any]:
    """Load previously registered custom slots from disk."""

    if not CUSTOM_SLOT_PATH.exists():
        return _empty_state()

    try:
        raw_text = CUSTOM_SLOT_PATH.read_text(encoding="utf-8")
    except OSError:
        return _empty_state()

    try:
        payload = json.loads(raw_text)
    except json.JSONDecodeError:
        return _build_state([], ["保存済みのJSONを読み込めませんでした。フォーマットを確認してください。"])  # noqa: E501

    entries_payload = _extract_entries(payload)
    if entries_payload is None:
        return _build_state([], ["JSONにentries配列が見つかりませんでした。"])

    entries, errors = _normalize_entries(entries_payload)
    return _build_state(entries, errors)


def save_slots(entries: List[Dict[str, Any]]) -> None:
    """Persist entries to disk."""

    CUSTOM_SLOT_PATH.parent.mkdir(parents=True, exist_ok=True)
    payload = {"entries": entries}
    CUSTOM_SLOT_PATH.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def clear_slots() -> None:
    """Remove the persisted slot file if it exists."""

    try:
        CUSTOM_SLOT_PATH.unlink()
    except FileNotFoundError:
        return


def parse_json_bytes(data: bytes) -> Dict[str, Any]:
    """Parse uploaded JSON bytes and return normalized state."""

    try:
        payload = json.loads(data.decode("utf-8"))
    except UnicodeDecodeError as exc:  # pragma: no cover - defensive path
        raise ValueError("JSONはUTF-8でエンコードしてください。") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"JSONの解析に失敗しました: {exc}") from exc

    entries_payload = _extract_entries(payload)
    if entries_payload is None:
        raise ValueError("JSONにentries配列が含まれていません。")

    entries, errors = _normalize_entries(entries_payload)
    if not entries:
        raise ValueError("有効なスロットが含まれていません。項目を確認してください。")

    return _build_state(entries, errors)


def lookup(state: Optional[Dict[str, Any]], year: Any, case_label: Any, question: Any) -> Optional[Dict[str, Any]]:
    """Return slot data for the specified question if available."""

    if not state:
        return None

    try:
        key = (str(year), str(case_label), int(question))
    except (TypeError, ValueError):
        return None

    slot = state.get("index", {}).get(key)
    if not slot:
        return None

    return {label: slot.get(label) for label in TAB_LABELS}


def slot_has_content(slot: Optional[Dict[str, Any]]) -> bool:
    """Return True if the slot contains any meaningful content."""

    if not slot:
        return False
    return any(content_has_value(slot.get(label)) for label in TAB_LABELS)


def content_has_value(content: Any) -> bool:
    if not content:
        return False
    if isinstance(content, dict):
        for value in content.values():
            if isinstance(value, list) and any(str(item).strip() for item in value):
                return True
            if isinstance(value, str) and value.strip():
                return True
            if value not in (None, "", []):
                return True
        return False
    if isinstance(content, list):
        return any(str(item).strip() for item in content)
    if isinstance(content, str):
        return bool(content.strip())
    return True


def summarize_entries(entries: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Create a DataFrame-friendly summary of entries."""

    summary: List[Dict[str, Any]] = []
    for entry in entries:
        tabs = entry.get("tabs", {})
        summary.append(
            {
                "年度": entry.get("year", ""),
                "事例": entry.get("case", ""),
                "設問": entry.get("question", ""),
                "講師A": "○" if content_has_value(tabs.get("講師A")) else "-",
                "講師B": "○" if content_has_value(tabs.get("講師B")) else "-",
                "採点観点": "○" if content_has_value(tabs.get("採点観点")) else "-",
            }
        )
    return summary


def _extract_entries(payload: Any) -> Optional[List[Any]]:
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        entries = payload.get("entries")
        if isinstance(entries, list):
            return entries
    return None


def _normalize_entries(entries_payload: Iterable[Any]) -> Tuple[List[Dict[str, Any]], List[str]]:
    entries: List[Dict[str, Any]] = []
    errors: List[str] = []
    for raw in entries_payload:
        normalized = _normalize_entry(raw)
        if normalized:
            entries.append(normalized)
        else:
            errors.append("一部のエントリを読み込めませんでした。フォーマットを確認してください。")
    return entries, errors


def _normalize_entry(entry: Any) -> Optional[Dict[str, Any]]:
    if not isinstance(entry, dict):
        return None

    year = entry.get("year") or entry.get("年度")
    case_label = entry.get("case") or entry.get("case_label") or entry.get("事例")
    question = (
        entry.get("question")
        or entry.get("question_order")
        or entry.get("設問")
        or entry.get("設問番号")
    )
    if year is None or case_label is None or question is None:
        return None

    try:
        question_no = int(question)
    except (TypeError, ValueError):
        return None

    tabs_payload: Dict[str, Any]
    tabs_field = entry.get("tabs")
    if tabs_field is None:
        tabs_payload = {label: entry.get(label) for label in TAB_LABELS}
    elif isinstance(tabs_field, dict):
        tabs_payload = {label: tabs_field.get(label) for label in TAB_LABELS}
    else:
        return None

    normalized_tabs = {label: _normalize_tab_content(tabs_payload.get(label)) for label in TAB_LABELS}

    return {
        "year": str(year),
        "case": str(case_label),
        "question": question_no,
        "tabs": normalized_tabs,
    }


def _normalize_tab_content(raw: Any) -> Optional[Dict[str, Any]]:
    if raw is None:
        return None
    if isinstance(raw, str):
        text = raw.strip()
        return {"commentary": text} if text else None
    if isinstance(raw, list):
        items = [str(item).strip() for item in raw if str(item).strip()]
        return {"viewpoints": items} if items else None
    if isinstance(raw, dict):
        normalized: Dict[str, Any] = {}
        extras: Dict[str, Any] = {}
        for key, value in raw.items():
            if value is None:
                continue
            cleaned: Optional[Any]
            if isinstance(value, list):
                cleaned_list = [str(item).strip() for item in value if str(item).strip()]
                if not cleaned_list:
                    continue
                cleaned = cleaned_list
            else:
                cleaned_str = str(value).strip()
                if not cleaned_str:
                    continue
                cleaned = cleaned_str

            mapped_key = _map_tab_key(key)
            if mapped_key == "extras":
                extras[key] = cleaned
            else:
                normalized[mapped_key] = cleaned

        if extras:
            normalized.setdefault("extras", {}).update(extras)
        return normalized or None

    return {"commentary": str(raw).strip()}


def _map_tab_key(key: str) -> str:
    mapping = {
        "model_answer": "model_answer",
        "answer": "model_answer",
        "模範解答": "model_answer",
        "解答例": "model_answer",
        "commentary": "commentary",
        "講評": "commentary",
        "解説": "commentary",
        "viewpoints": "viewpoints",
        "観点": "viewpoints",
        "採点観点": "viewpoints",
        "チェックポイント": "viewpoints",
        "notes": "notes",
        "補足": "notes",
        "memo": "notes",
    }
    return mapping.get(key, "extras")


def _build_index(entries: Iterable[Dict[str, Any]]) -> Dict[Tuple[str, str, int], Dict[str, Any]]:
    index: Dict[Tuple[str, str, int], Dict[str, Any]] = {}
    for entry in entries:
        key = (str(entry.get("year", "")), str(entry.get("case", "")), int(entry.get("question", 0)))
        tabs = entry.get("tabs") or {}
        index[key] = {label: tabs.get(label) for label in TAB_LABELS}
    return index
