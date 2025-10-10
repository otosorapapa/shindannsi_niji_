from __future__ import annotations

import io
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence

import pandas as pd

try:  # pragma: no cover - optional dependency fallback
    import pdfplumber  # type: ignore
except Exception:  # pragma: no cover - imported lazily in runtime context
    pdfplumber = None


KANJI_NUMERAL_MAP = {
    "〇": 0,
    "零": 0,
    "一": 1,
    "二": 2,
    "三": 3,
    "四": 4,
    "五": 5,
    "六": 6,
    "七": 7,
    "八": 8,
    "九": 9,
}

KANJI_UNIT_MAP = {
    "十": 10,
    "百": 100,
    "千": 1000,
}

FULLWIDTH_DIGITS = {ord(str(i)): ord("０") + i for i in range(10)}
REVERSED_FULLWIDTH_DIGITS = {v: k for k, v in FULLWIDTH_DIGITS.items()}

YEAR_PATTERN = re.compile(r"令和\s*([0-9０-９]+)\s*年度")
REIWA_SHORT_PATTERN = re.compile(r"R\s*([0-9０-９]+)", re.IGNORECASE)
CASE_PATTERN = re.compile(r"事例\s*([IVXⅠⅡⅢⅣ1-4１２３４])")
QUESTION_PATTERN = re.compile(r"第([0-9０-９一二三四五六七八九十]+)問")
QUESTION_HEADER_PATTERN = re.compile(
    r"^第[0-9０-９一二三四五六七八九十]+問[ 　\t]*(?:（[^）]*）)?",
    re.MULTILINE,
)
POINT_PATTERN = re.compile(r"配点[ 　\t]*([0-9０-９]+)点")
CHAR_COUNT_PATTERN = re.compile(
    r"([0-9０-９]+|[一二三四五六七八九十百千〇零]+)[ 　\t]*字(?:以内|以下|程度)?"
)

CASE_NORMALIZATION = {
    "I": "事例I",
    "Ⅰ": "事例I",
    "1": "事例I",
    "１": "事例I",
    "II": "事例II",
    "Ⅱ": "事例II",
    "2": "事例II",
    "２": "事例II",
    "III": "事例III",
    "Ⅲ": "事例III",
    "3": "事例III",
    "３": "事例III",
    "IV": "事例IV",
    "Ⅳ": "事例IV",
    "4": "事例IV",
    "４": "事例IV",
}


@dataclass
class ParsedExam:
    """Parsed representation of an uploaded past exam document."""

    dataframe: pd.DataFrame
    tables: Dict[int, List[Dict[str, List[List[str]]]]] = field(default_factory=dict)
    metadata: Dict[str, str] = field(default_factory=dict)


def parse_uploaded_exam(uploaded_file) -> ParsedExam:
    """Parse an uploaded CSV/Excel/PDF file into a normalized exam DataFrame."""

    filename = uploaded_file.name.lower()
    if filename.endswith(".csv"):
        uploaded_file.seek(0)
        df = pd.read_csv(uploaded_file)
        return ParsedExam(_normalize_dataframe(df), tables={}, metadata={})

    if filename.endswith(".xlsx") or filename.endswith(".xls"):
        uploaded_file.seek(0)
        df = pd.read_excel(uploaded_file)
        return ParsedExam(_normalize_dataframe(df), tables={}, metadata={})

    if filename.endswith(".pdf"):
        if pdfplumber is None:
            raise ValueError(
                "PDFの解析ライブラリがインポートできませんでした。requirements.txtにpdfplumberを追加してください。"
            )
        uploaded_file.seek(0)
        pdf_bytes = io.BytesIO(uploaded_file.read())
        return _parse_pdf(pdf_bytes)

    raise ValueError("対応していないファイル形式です。CSV/Excel/PDFをご利用ください。")


def table_payload_to_dataframe(payload: Dict[str, List[List[str]]]) -> pd.DataFrame:
    """Convert a stored table payload back into a DataFrame for display."""

    if not payload:
        return pd.DataFrame()

    rows = payload.get("rows", [])
    header = payload.get("header")
    if header:
        header = _normalize_table_row(header)
    normalized_rows = [_normalize_table_row(row) for row in rows]

    if header and all(len(row) == len(header) for row in normalized_rows):
        return pd.DataFrame(normalized_rows, columns=header)
    return pd.DataFrame(normalized_rows)


def _normalize_table_row(row: Sequence[Optional[str]]) -> List[str]:
    return [cell.strip() if isinstance(cell, str) else "" for cell in row]


def _normalize_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    working = df.copy()
    column_map = {}
    for col in working.columns:
        normalized = str(col).strip()
        if normalized in {"設問", "問番", "question"}:
            column_map[col] = "設問番号"
        elif normalized in {"年度", "year"}:
            column_map[col] = "年度"
        elif normalized in {"事例", "case"}:
            column_map[col] = "事例"
        elif normalized in {"問題文", "question_text"}:
            column_map[col] = "問題文"
        elif normalized in {"配点", "points"}:
            column_map[col] = "配点"
        elif normalized in {"模範解答", "model_answer"}:
            column_map[col] = "模範解答"
        elif normalized in {"解説", "explanation"}:
            column_map[col] = "解説"
        elif normalized in {"文字数", "文字数指定", "char_limit"}:
            column_map[col] = "文字数指定"
        elif normalized in {"数表", "tables"}:
            column_map[col] = "数表"
    if column_map:
        working = working.rename(columns=column_map)

    required_cols = {"年度", "事例", "設問番号", "問題文", "配点"}
    missing = required_cols.difference(working.columns)
    if missing:
        raise ValueError(
            "必要な列が不足しています。不足列: " + ", ".join(sorted(missing))
        )

    if "模範解答" not in working.columns:
        working["模範解答"] = ""
    if "解説" not in working.columns:
        working["解説"] = ""

    if "文字数指定" not in working.columns:
        working["文字数指定"] = working["問題文"].map(_extract_char_limit)
    else:
        working["文字数指定"] = working["文字数指定"].map(_normalize_int)

    if "数表" in working.columns:
        working["数表"] = working["数表"].map(_normalize_table_payload)

    working["設問番号"] = working["設問番号"].map(_normalize_int)
    working["配点"] = working["配点"].map(_normalize_int)

    return working


def _normalize_table_payload(value):
    if isinstance(value, dict) and {"header", "rows"}.issubset(value.keys()):
        return {
            "header": value.get("header", []),
            "rows": value.get("rows", []),
        }

    if isinstance(value, str):
        try:
            payload = json.loads(value)
        except json.JSONDecodeError:
            return value
        if isinstance(payload, dict):
            return {
                "header": payload.get("header", []),
                "rows": payload.get("rows", []),
            }
        if isinstance(payload, list):
            return {"header": payload[0] if payload else [], "rows": payload[1:]}
    if isinstance(value, list):
        if value and all(isinstance(row, list) for row in value):
            return {"header": value[0], "rows": value[1:]}
    return value


def _parse_pdf(pdf_bytes: io.BytesIO) -> ParsedExam:
    if pdfplumber is None:
        raise ValueError("pdfplumberが利用できないためPDFを解析できません。")

    with pdfplumber.open(pdf_bytes) as pdf:
        page_texts: List[str] = []
        page_tables: List[List[Dict[str, List[List[str]]]]] = []
        for page in pdf.pages:
            text = page.extract_text() or ""
            page_texts.append(text)
            tables_payload: List[Dict[str, List[List[str]]]] = []
            try:
                tables = page.extract_tables() or []
            except Exception:  # pragma: no cover - pdfplumber dependent
                tables = []
            for table in tables:
                if not table:
                    continue
                normalized_rows = [
                    [cell.strip() if isinstance(cell, str) else "" for cell in row]
                    for row in table
                ]
                if all(not any(row) for row in normalized_rows):
                    continue
                header = normalized_rows[0] if normalized_rows else []
                rows = normalized_rows[1:] if len(normalized_rows) > 1 else []
                tables_payload.append({"header": header, "rows": rows})
            page_tables.append(tables_payload)

    if not page_texts:
        raise ValueError("PDFからテキストを抽出できませんでした。")

    combined_text = "\n".join(page_texts)
    year = _extract_year(combined_text)
    case_label = _extract_case(combined_text)

    questions = _split_questions(combined_text)
    if not questions:
        raise ValueError("PDFから設問を抽出できませんでした。R6/R5原紙テンプレートに近い形式か確認してください。")

    # Assign tables to questions based on page ranges.
    offsets: List[int] = []
    total = 0
    for text in page_texts:
        offsets.append(total)
        total += len(text) + 1  # account for newline join

    for page_index, tables_payload in enumerate(page_tables):
        if not tables_payload:
            continue
        page_start = offsets[page_index]
        page_end = offsets[page_index] + len(page_texts[page_index])
        target_question = None
        for question in questions:
            if question["start"] <= page_end and question["end"] >= page_start:
                target_question = question
                break
        if target_question is None and questions:
            target_question = questions[-1]
        if target_question is None:
            continue
        target_question.setdefault("tables", []).extend(tables_payload)

    records = []
    tables_map: Dict[int, List[Dict[str, List[List[str]]]]] = {}
    for question in questions:
        number = question["number"]
        prompt = question["text"].strip()
        points = question["points"]
        char_limit = question.get("char_limit")
        tables_payload = question.get("tables", [])
        records.append(
            {
                "年度": year or "年度不明",
                "事例": case_label or "事例不明",
                "設問番号": number,
                "問題文": prompt,
                "配点": points,
                "模範解答": "",
                "解説": "",
                "文字数指定": char_limit,
                "数表": tables_payload if tables_payload else None,
            }
        )
        if tables_payload:
            tables_map[number] = tables_payload

    dataframe = pd.DataFrame(records)
    return ParsedExam(
        dataframe=dataframe,
        tables=tables_map,
        metadata={k: v for k, v in {"年度": year, "事例": case_label}.items() if v},
    )


def _split_questions(text: str) -> List[Dict[str, Optional[int]]]:
    matches = list(QUESTION_PATTERN.finditer(text))
    questions: List[Dict[str, Optional[int]]] = []
    for idx, match in enumerate(matches):
        start = match.start()
        end = matches[idx + 1].start() if idx + 1 < len(matches) else len(text)
        segment = text[start:end].strip()
        number = _parse_question_number(match.group(1))
        cleaned = QUESTION_HEADER_PATTERN.sub("", segment, count=1).strip()
        points = _extract_points(segment)
        char_limit = _extract_char_limit(segment)
        questions.append(
            {
                "number": number,
                "text": cleaned,
                "points": points,
                "char_limit": char_limit,
                "start": start,
                "end": end,
            }
        )
    return questions


def _extract_points(segment: str) -> Optional[int]:
    match = POINT_PATTERN.search(segment)
    if not match:
        return None
    return _normalize_int(match.group(1))


def _extract_char_limit(segment: str) -> Optional[int]:
    for match in CHAR_COUNT_PATTERN.finditer(segment):
        token = match.group(1)
        value = _normalize_int(token)
        if value:
            return value
    return None


def _extract_year(text: str) -> Optional[str]:
    match = YEAR_PATTERN.search(text)
    if match:
        year = _normalize_int(match.group(1))
        if year:
            return f"令和{year}年度"

    match = REIWA_SHORT_PATTERN.search(text)
    if match:
        year = _normalize_int(match.group(1))
        if year:
            return f"令和{year}年度"

    for template_text in _iter_template_texts():
        template_match = YEAR_PATTERN.search(template_text)
        if template_match:
            year = _normalize_int(template_match.group(1))
            if year:
                return f"令和{year}年度"

    return None


def _extract_case(text: str) -> Optional[str]:
    match = CASE_PATTERN.search(text)
    if match:
        token = match.group(1)
        normalized = CASE_NORMALIZATION.get(_normalize_case_token(token))
        if normalized:
            return normalized

    for template_text in _iter_template_texts():
        match = CASE_PATTERN.search(template_text)
        if match:
            normalized = CASE_NORMALIZATION.get(_normalize_case_token(match.group(1)))
            if normalized:
                return normalized

    return None


def _iter_template_texts() -> Iterable[str]:
    templates_dir = Path("data/templates")
    if not templates_dir.exists():
        return []
    texts: List[str] = []
    for path in templates_dir.glob("*.txt"):
        try:
            texts.append(path.read_text(encoding="utf-8"))
        except OSError:
            continue
    return texts


def _normalize_case_token(token: str) -> str:
    ascii_token = token.translate(REVERSED_FULLWIDTH_DIGITS)
    ascii_token = ascii_token.upper()
    return ascii_token


def _normalize_int(value) -> Optional[int]:
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)) and not pd.isna(value):
        return int(value)
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            return None
        normalized = stripped.translate(REVERSED_FULLWIDTH_DIGITS)
        if normalized.isdigit():
            return int(normalized)
        kanji_value = _kanji_to_int(stripped)
        if kanji_value:
            return kanji_value
    return None


def _kanji_to_int(text: str) -> Optional[int]:
    total = 0
    current = 0
    has_value = False
    for char in text:
        if char in KANJI_NUMERAL_MAP:
            current = KANJI_NUMERAL_MAP[char]
            has_value = True
        elif char in KANJI_UNIT_MAP:
            unit = KANJI_UNIT_MAP[char]
            if current == 0:
                current = 1
            total += current * unit
            current = 0
            has_value = True
    total += current
    return total if has_value and total > 0 else None


def _parse_question_number(token: str) -> Optional[int]:
    normalized = token.translate(REVERSED_FULLWIDTH_DIGITS)
    if normalized.isdigit():
        return int(normalized)
    return _kanji_to_int(token)

