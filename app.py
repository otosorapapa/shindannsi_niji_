from __future__ import annotations

from collections import defaultdict
import copy
from datetime import date as dt_date, datetime, time as dt_time, timedelta
from pathlib import Path
from textwrap import dedent
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple
from uuid import uuid4
import logging

import html
import io
import json

import math

import random

import re

import uuid

import unicodedata

import zipfile

import altair as alt
import pandas as pd
import pdfplumber
import streamlit as st
import streamlit.components.v1 as components


st.set_page_config(
    page_title="中小企業診断士二次試験ナビゲーション",
    layout="wide",
    initial_sidebar_state="expanded",
)

import committee_analysis
import database
import mock_exam
import scoring
from database import RecordedAnswer
from scoring import QuestionSpec


MOCK_NOTICE_ITEMS = [
    "試験時間は80分です。開始と同時に計測し、終了合図とともに筆記を止めてください。",
    "机上に置けるのは HB〜2B 鉛筆・シャープペンシル、消しゴム、時計のみです。電子機器は使用禁止です。",
    "解答用紙の氏名・受験番号を最初に記入し、問題冊子・答案の持ち出しは禁止されています。",
    "途中退室は認められません。監督員の指示に従い、終了後は静かに退室してください。",
]


DEFAULT_KEYWORD_RESOURCES = [
    {
        "label": "中小企業診断協会: 2次試験過去問題", 
        "url": "https://www.j-smeca.or.jp/contents/0105007000.html",
    },
    {
        "label": "中小企業診断士ポータル: キーワード整理", 
        "url": "https://www.smeca.jp/consultant/exam/keyword.html",
    },
]


KEYWORD_RESOURCE_MAP = {
    "製造技術": [
        {
            "label": "運営管理テキスト 製造工程編",
            "url": "https://www.j-smeca.or.jp/contents/0105005000.html",
        },
    ],
    "信頼関係": [
        {
            "label": "組織・人事: 顧客との関係構築 事例解説",
            "url": "https://www.j-smeca.or.jp/contents/0105003000.html",
        },
    ],
    "高付加価値": [
        {
            "label": "経営戦略: 付加価値向上の施策",
            "url": "https://www.smrj.go.jp/diagnosis/",
        },
    ],
    "企画開発": [
        {
            "label": "新製品開発ロードマップ",
            "url": "https://www.jetro.go.jp/ext_images/jfile/report/07000648/report.pdf",
        },
    ],
    "技能伝承": [
        {
            "label": "技能伝承のポイント (厚労省)",
            "url": "https://www.mhlw.go.jp/stf/seisakunitsuite/bunya/0000084967.html",
        },
    ],
    "評価制度": [
        {
            "label": "人事評価制度設計ガイド",
            "url": "https://www.jil.go.jp/institute/",
        },
    ],
    "モチベーション": [
        {
            "label": "モチベーション理論と組織活性化",
            "url": "https://www.hataraku.metro.tokyo.lg.jp/sodan/itaku/",
        },
    ],
    "連携": [
        {
            "label": "地域連携によるサービス開発事例",
            "url": "https://www.chusho.meti.go.jp/",
        },
    ],
    "口コミ": [
        {
            "label": "マーケティング: 口コミ活用施策",
            "url": "https://www.smrj.go.jp/feature/",
        },
    ],
    "ROA": [
        {
            "label": "財務指標の読み方: ROA",
            "url": "https://www.jcci.or.jp/chusho/finance/",
        },
    ],
    "固定資産回転率": [
        {
            "label": "財務分析: 回転率の捉え方",
            "url": "https://www.jetro.go.jp/world/",
        },
    ],
    "キャッシュフロー": [
        {
            "label": "キャッシュフロー計算書の読み方",
            "url": "https://www.japaneselawtranslation.go.jp/",
        },
    ],
    "資本コスト": [
        {
            "label": "資本コストと投資判断入門",
            "url": "https://www.mof.go.jp/public_relations/finance/",
        },
    ],
}


CASE_ORDER = ["事例I", "事例II", "事例III", "事例IV"]


CASEIII_TIMELINE = [
    {
        "year": "R6",
        "theme": "設計DXでの多品種小ロット対応",
        "focus": "設計BOMと生産BOMの連携で立ち上げリードタイムを短縮。技術伝承の仕組み化がポイント。",
        "source": "https://www.j-smeca.or.jp/contents/0105007000_R6_case3.pdf",
    },
    {
        "year": "R5",
        "theme": "在庫圧縮と需要変動対応",
        "focus": "需要予測精度を上げつつ、かんばん方式と外段取り化で仕掛在庫を削減。",
        "source": "https://www.j-smeca.or.jp/contents/0105007000_R5_case3.pdf",
    },
    {
        "year": "R4",
        "theme": "段取り短縮と多能工化",
        "focus": "段取り時間の可視化と標準作業書で段取り替えを効率化。技能伝承と教育体制の整備が問われた。",
        "source": "https://www.j-smeca.or.jp/contents/0105007000_R4_case3.pdf",
    },
]


CASE_FRAME_SHORTCUTS = {
    "事例I": [
        {
            "label": "さちのひほ",
            "snippet": "【さちのひほ】採用で人材を確保し、配置で適材適所を図り、能力開発と評価で成長を促し、報酬・処遇で定着とモチベーションを高める。",
            "description": "人事施策を採用・配置・育成・評価・報酬の流れで整理。",
        },
        {
            "label": "けぶかいねこ",
            "snippet": "【けぶかいねこ】権限委譲で現場裁量を高め、部門編成と階層を見直し、情報共有とコミュニケーションを活性化し、ネットワーク・コラボで連携を強化する。",
            "description": "組織構造とコミュニケーションの課題整理に活用。",
        },
    ],
    "事例II": [
        {
            "label": "売上分解",
            "snippet": "【売上分解】売上＝客数×客単価で捉え、客数は新規獲得・来店頻度、客単価は関連購買・高付加価値提案で向上させる。",
            "description": "売上向上策を客数と客単価の両面から検討。",
        },
        {
            "label": "新規/既存×施策",
            "snippet": "【新規/既存×施策】新規顧客には認知拡大と体験機会、既存顧客にはリピート促進とLTV向上策を組み合わせる。",
            "description": "顧客区分別にマーケティング施策を整理。",
        },
        {
            "label": "チャネル・協業",
            "snippet": "【チャネル・協業】直販強化とEC・外部販路を組み合わせ、地域・異業種との協業で接点と提供価値を拡張する。",
            "description": "販路開拓と連携施策の方向性を提示。",
        },
    ],
    "事例III": [
        {
            "label": "QCD",
            "snippet": "【QCD】品質(Q)の安定化、コスト(C)の低減、納期(D)の短縮・遵守を同時に意識した改善策を提示する。",
            "description": "生産性向上策を品質・コスト・納期でバランス確認。",
        },
        {
            "label": "4M",
            "snippet": "【4M】Man・Machine・Method・Materialの視点で要因を洗い出し、標準化と教育で再発防止を図る。",
            "description": "工程の課題原因を人・設備・方法・材料で整理。",
        },
        {
            "label": "段取り短縮",
            "snippet": "【段取り短縮】内段取りの外段取り化、前準備の標準化、段取り時間の短縮でリードタイムを圧縮する。",
            "description": "段取り替えと準備の効率化視点。",
        },
        {
            "label": "ECRS",
            "snippet": "【ECRS】排除(Eliminate)→結合(Combine)→交換(Rearrange)→簡素化(Simplify)の順で工程改善案を検討する。",
            "description": "改善アイデアを体系的に展開。",
        },
    ],
    "事例IV": [
        {
            "label": "財務→CVP→投資判定",
            "snippet": "【財務分析→CVP→投資判定】財務指標で現状を把握し、CVP分析で損益分岐を確認し、投資回収・NPV等で施策の妥当性を検証する連鎖を意識する。",
            "description": "設問間の依存を踏まえて分析から投資判断へ展開。",
        }
    ],
}


PAST_EXAM_TEMPLATE_PATH = Path(__file__).resolve().parent / "data" / "past_exam_template.csv"
CASE_CONTEXT_TEMPLATE_PATH = Path(__file__).resolve().parent / "data" / "case_context_template.csv"
QUESTION_TEXT_TEMPLATE_PATH = (
    Path(__file__).resolve().parent / "data" / "question_text_template.csv"
)
QUESTION_TYPE_HISTORY_PATH = Path(__file__).resolve().parent / "data" / "question_type_history.csv"
EXAM_TEMPLATES_JSON_PATH = Path(__file__).resolve().parent / "data" / "exam_templates.json"
EXAM_COMMITTEE_PROFILES_JSON_PATH = (
    Path(__file__).resolve().parent / "data" / "exam_committee_profiles.json"
)
SEED_PROBLEMS_JSON_PATH = Path(__file__).resolve().parent / "data" / "seed_problems.json"

TEMPLATE_BUNDLE_FILES = [
    ("past_exam_template.csv", PAST_EXAM_TEMPLATE_PATH),
    ("case_context_template.csv", CASE_CONTEXT_TEMPLATE_PATH),
    ("question_text_template.csv", QUESTION_TEXT_TEMPLATE_PATH),
    ("question_type_history.csv", QUESTION_TYPE_HISTORY_PATH),
    ("exam_templates.json", EXAM_TEMPLATES_JSON_PATH),
    ("exam_committee_profiles.json", EXAM_COMMITTEE_PROFILES_JSON_PATH),
    ("seed_problems.json", SEED_PROBLEMS_JSON_PATH),
]


@st.cache_data(show_spinner=False)
def _load_exam_templates() -> List[Dict[str, Any]]:
    template_path = Path("data/exam_templates.json")
    if not template_path.exists():
        return []
    try:
        return json.loads(template_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return []


@st.cache_data(show_spinner=False)
def _load_past_exam_template_bytes() -> bytes:
    if not PAST_EXAM_TEMPLATE_PATH.exists():
        raise FileNotFoundError("past_exam_template.csv not found")
    return PAST_EXAM_TEMPLATE_PATH.read_bytes()


@st.cache_data(show_spinner=False)
def _load_past_exam_template_preview() -> pd.DataFrame:
    if not PAST_EXAM_TEMPLATE_PATH.exists():
        raise FileNotFoundError("past_exam_template.csv not found")
    return pd.read_csv(PAST_EXAM_TEMPLATE_PATH)


@st.cache_data(show_spinner=False)
def _load_case_context_template_bytes() -> bytes:
    if not CASE_CONTEXT_TEMPLATE_PATH.exists():
        raise FileNotFoundError("case_context_template.csv not found")
    return CASE_CONTEXT_TEMPLATE_PATH.read_bytes()


@st.cache_data(show_spinner=False)
def _load_case_context_template_preview() -> pd.DataFrame:
    if not CASE_CONTEXT_TEMPLATE_PATH.exists():
        raise FileNotFoundError("case_context_template.csv not found")
    return pd.read_csv(CASE_CONTEXT_TEMPLATE_PATH)


@st.cache_data(show_spinner=False)
def _load_question_text_template_bytes() -> bytes:
    if not QUESTION_TEXT_TEMPLATE_PATH.exists():
        raise FileNotFoundError("question_text_template.csv not found")
    return QUESTION_TEXT_TEMPLATE_PATH.read_bytes()


@st.cache_data(show_spinner=False)
def _load_question_text_template_preview() -> pd.DataFrame:
    if not QUESTION_TEXT_TEMPLATE_PATH.exists():
        raise FileNotFoundError("question_text_template.csv not found")
    return pd.read_csv(QUESTION_TEXT_TEMPLATE_PATH)


@st.cache_data(show_spinner=False)
def _load_template_bundle_bytes() -> bytes:
    missing_files = [
        name for name, path in TEMPLATE_BUNDLE_FILES if not path.exists()
    ]
    if missing_files:
        joined = ", ".join(missing_files)
        raise FileNotFoundError(f"Missing template files: {joined}")

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as zip_file:
        for archive_name, source_path in TEMPLATE_BUNDLE_FILES:
            zip_file.writestr(archive_name, source_path.read_bytes())

    buffer.seek(0)
    return buffer.getvalue()


def _normalize_case_label(raw: Optional[str]) -> Optional[str]:
    if not raw:
        return None
    mapping = {
        "Ⅰ": "事例I",
        "Ⅱ": "事例II",
        "Ⅲ": "事例III",
        "Ⅳ": "事例IV",
        "事例1": "事例I",
        "事例2": "事例II",
        "事例3": "事例III",
        "事例4": "事例IV",
    }
    raw = raw.strip()
    if raw in mapping:
        return mapping[raw]
    if raw.startswith("事例") and len(raw) == 3:
        return raw
    match = re.search(r"事例([ⅠⅡⅢⅣIV1234])", raw)
    if match:
        return mapping.get(match.group(1), f"事例{match.group(1)}")
    return raw


def _japanese_numeral_to_int(token: str) -> Optional[int]:
    if not token:
        return None
    token = token.strip()
    if token.isdigit():
        return int(token)
    numeral_map = {"一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9, "十": 10}
    total = 0
    for char in token:
        if char == "十" and total == 0:
            total = 10
            continue
        value = numeral_map.get(char)
        if value is None:
            return None
        if char == "十" and total >= 10:
            total += value
        else:
            total += value
    return total if total else None


def _extract_question_blocks(text: str) -> List[Tuple[int, str]]:
    if not text:
        return []
    pattern = re.compile(r"第\s*([0-9一二三四五六七八九十]+)問[：:（(\s]?", re.MULTILINE)
    matches = list(pattern.finditer(text))
    if not matches:
        return []
    blocks: List[Tuple[int, str]] = []
    for index, match in enumerate(matches):
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        order = _japanese_numeral_to_int(match.group(1)) or (index + 1)
        block = text[start:end].strip()
        blocks.append((order, block))
    return blocks


def _extract_questions_from_text(
    text: str,
    *,
    default_year: Optional[str] = None,
    default_case: Optional[str] = None,
) -> List[Dict[str, Any]]:
    if not text:
        return []

    year_match = re.search(r"令和\s*([0-9０-９]+)年度?", text)
    if year_match:
        digits = year_match.group(1).translate(str.maketrans("０１２３４５６７８９", "0123456789"))
        year_label = f"令和{digits}年"
    else:
        year_label = default_year

    case_match = re.search(r"事例[ⅠⅡⅢⅣIV1234]", text)
    case_label = _normalize_case_label(case_match.group(0) if case_match else default_case)

    questions: List[Dict[str, Any]] = []
    for order, block in _extract_question_blocks(text):
        block = block.replace("\u3000", " ").strip()
        limit_match = re.search(r"([0-9０-９]{2,3})\s*字以内", block)
        limit = None
        if limit_match:
            digits = limit_match.group(1).translate(str.maketrans("０１２３４５６７８９", "0123456789"))
            limit = int(digits)

        score_match = re.search(r"配点\s*([0-9０-９]{1,2})点", block)
        score = None
        if score_match:
            digits = score_match.group(1).translate(str.maketrans("０１２３４５６７８９", "0123456789"))
            score = int(digits)

        headline = block.splitlines()[0].strip() if block.splitlines() else ""
        body = block
        questions.append(
            {
                "年度": year_label or default_year or "年度不明",
                "事例": case_label or default_case or "事例不明",
                "設問番号": order,
                "問題文": body,
                "配点": score,
                "制限字数": limit,
                "設問見出し": headline,
                "模範解答": "未設定",
                "解説": "未設定",
            }
        )

    return questions


def _extract_tables_from_pdf(pages: Iterable[pdfplumber.page.Page]) -> List[pd.DataFrame]:
    tables: List[pd.DataFrame] = []
    for page in pages:
        for raw_table in page.extract_tables() or []:
            if not raw_table:
                continue
            df = pd.DataFrame(raw_table)
            df = df.dropna(how="all").dropna(axis=1, how="all")
            if df.empty:
                continue
            header = df.iloc[0].fillna("")
            if header.astype(str).str.len().sum() > 0:
                df = df[1:]
                df.columns = [str(col).strip() or f"列{idx + 1}" for idx, col in enumerate(header)]
            else:
                df.columns = [f"列{idx + 1}" for idx in range(len(df.columns))]
            cleaned = df.reset_index(drop=True)
            if not cleaned.empty:
                tables.append(cleaned)
    return tables


def _apply_template_metadata(
    questions: List[Dict[str, Any]],
    templates: Dict[Tuple[str, str], Dict[str, Any]],
    year_label: Optional[str],
    case_label: Optional[str],
) -> List[Dict[str, Any]]:
    if not questions:
        return questions
    key = (year_label or "", case_label or "")
    template = templates.get(key)
    if not template:
        return questions

    template_questions = {item.get("number"): item for item in template.get("questions", [])}
    for question in questions:
        template_info = template_questions.get(question.get("設問番号"))
        if not template_info:
            continue
        if pd.isna(question.get("制限字数")) and template_info.get("limit"):
            question["制限字数"] = template_info.get("limit")
        if pd.isna(question.get("配点")) and template_info.get("score"):
            question["配点"] = template_info.get("score")
        if not question.get("設問見出し") and template_info.get("headline"):
            question["設問見出し"] = template_info.get("headline")
    return questions


def _auto_parse_exam_document(file_bytes: bytes, filename: str) -> Tuple[pd.DataFrame, List[pd.DataFrame]]:
    name_lower = filename.lower()
    default_year = None
    default_case = None

    templates = {
        (item.get("year"), _normalize_case_label(item.get("case"))): item
        for item in _load_exam_templates()
        if item.get("year") and item.get("case")
    }

    match = re.search(r"r(\d{1,2})", name_lower)
    if match:
        default_year = f"令和{int(match.group(1))}年"
    if "case3" in name_lower or "jirei3" in name_lower:
        default_case = "事例III"
    elif "case4" in name_lower or "jirei4" in name_lower:
        default_case = "事例IV"
    elif "case2" in name_lower or "jirei2" in name_lower:
        default_case = "事例II"
    elif "case1" in name_lower or "jirei1" in name_lower:
        default_case = "事例I"

    if name_lower.endswith(".pdf"):
        with pdfplumber.open(io.BytesIO(file_bytes)) as pdf:
            text = "\n".join((page.extract_text() or "") for page in pdf.pages)
            tables = _extract_tables_from_pdf(pdf.pages)
        questions = _extract_questions_from_text(
            text,
            default_year=default_year,
            default_case=default_case,
        )
        normalized_year = questions[0]["年度"] if questions else default_year
        normalized_case = _normalize_case_label(questions[0]["事例"]) if questions else default_case
        questions = _apply_template_metadata(questions, templates, normalized_year, normalized_case)
        return pd.DataFrame(questions), tables

    buffer = io.BytesIO(file_bytes)
    if name_lower.endswith(".csv"):
        df = pd.read_csv(buffer)
    elif name_lower.endswith(".xlsx") or name_lower.endswith(".xls"):
        df = pd.read_excel(buffer)
    else:
        raise ValueError("サポートされていないファイル形式です")

    required_cols = {"年度", "事例", "設問番号", "問題文", "配点", "模範解答", "解説"}
    if required_cols.issubset(df.columns):
        return df, []

    text_source = "\n".join(
        str(value)
        for value in df.select_dtypes(include=["object", "string"]).fillna("").values.flatten()
    )
    questions = _extract_questions_from_text(
        text_source,
        default_year=default_year,
        default_case=default_case,
    )
    normalized_year = questions[0]["年度"] if questions else default_year
    normalized_case = _normalize_case_label(questions[0]["事例"]) if questions else default_case
    questions = _apply_template_metadata(questions, templates, normalized_year, normalized_case)
    return pd.DataFrame(questions), []


def _compose_slot_key(year: str, case_label: str, question_number: int) -> str:
    return f"{year}::{case_label}::{question_number}"


def _compose_case_key(year: str, case_label: str) -> str:
    return f"{year}::{case_label}"


def _normalize_question_number(value: Any) -> Optional[int]:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        if isinstance(value, float) and math.isnan(value):
            return None
        return int(value)
    if isinstance(value, str):
        token = value.strip()
        if not token:
            return None
        match = re.search(r"([0-9一二三四五六七八九十]+)", token)
        if match:
            token = match.group(1)
        token = token.translate(str.maketrans("０１２３４５６７８９", "0123456789"))
        if token.isdigit():
            return int(token)
        numeral = _japanese_numeral_to_int(token)
        if numeral:
            return numeral
    return None


def _select_first(data: Dict[str, Any], keys: Iterable[str]) -> Any:
    for key in keys:
        if key in data and data[key] not in (None, ""):
            return data[key]
    return None


def _ensure_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (list, tuple, set)):
        return "\n".join(str(item).strip() for item in value if str(item).strip())
    return str(value).strip()


def _normalize_text_block(value: Any) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, float):
        if pd.isna(value):
            return None
        text = str(value).strip()
        return text or None
    if isinstance(value, (list, tuple, set)):
        text = _ensure_text(value)
    else:
        text = str(value).strip()
    if not text:
        return None
    lowered = text.lower()
    if lowered in {"nan", "none"}:
        return None
    return text


def _iter_question_context_candidates(question: Dict[str, Any]) -> Iterable[Any]:
    if not question:
        return []

    candidates: List[Any] = [
        question.get("context"),
        question.get("context_text"),
        question.get("context_snippet"),
        question.get("与件文"),
        question.get("与件文全体"),
        question.get("与件"),
        question.get("context_body"),
    ]

    passages = question.get("context_passages")
    if isinstance(passages, (list, tuple, set)):
        for passage in passages:
            if isinstance(passage, dict):
                candidates.extend(
                    [
                        passage.get("text"),
                        passage.get("content"),
                        passage.get("body"),
                    ]
                )
            else:
                candidates.append(passage)
    elif passages is not None:
        candidates.append(passages)

    return candidates


def _collect_problem_context_text(problem: Dict[str, Any]) -> Optional[str]:
    if not problem:
        return None

    direct_keys = (
        "context",
        "context_text",
        "context_body",
        "context_passages",
        "与件文",
        "与件文全体",
        "与件",
    )
    for key in direct_keys:
        value = problem.get(key)
        if key == "context_passages" and value:
            collected: List[str] = []
            items = value if isinstance(value, (list, tuple, set)) else [value]
            for item in items:
                if isinstance(item, dict):
                    for sub_key in ("text", "content", "body"):
                        normalized = _normalize_text_block(item.get(sub_key))
                        if normalized:
                            collected.append(normalized)
                else:
                    normalized = _normalize_text_block(item)
                    if normalized:
                        collected.append(normalized)
            if collected:
                return "\n\n".join(collected)
        else:
            normalized = _normalize_text_block(value)
            if normalized:
                return normalized

    fragments: List[str] = []
    seen: Set[str] = set()

    for question in problem.get("questions", []):
        for candidate in _iter_question_context_candidates(question):
            normalized = _normalize_text_block(candidate)
            if not normalized or normalized in seen:
                continue
            seen.add(normalized)
            fragments.append(normalized)

    if not fragments:
        return None

    return "\n\n".join(fragments)


def _coerce_points(value: Any) -> List[str]:
    if value is None:
        return []
    if isinstance(value, (list, tuple, set)):
        return [str(item).strip() for item in value if str(item).strip()]
    text = _ensure_text(value)
    if not text:
        return []
    candidates = re.split(r"[\n,、]", text)
    return [candidate.strip() for candidate in candidates if candidate.strip()]


def _coerce_lecturer_payload(value: Any) -> Dict[str, str]:
    if value is None:
        return {}
    if isinstance(value, dict):
        answer_raw = _select_first(
            value,
            ["answer", "model_answer", "text", "模範解答", "content"],
        )
        commentary_raw = _select_first(
            value,
            ["commentary", "review", "comment", "講評", "解説", "note"],
        )
        payload = {}
        answer_text = _ensure_text(answer_raw)
        commentary_text = _ensure_text(commentary_raw)
        if answer_text:
            payload["answer"] = answer_text
        if commentary_text:
            payload["commentary"] = commentary_text
        return payload
    text = _ensure_text(value)
    if not text:
        return {}
    return {"answer": text}


def _coerce_scoring_payload(value: Any) -> Dict[str, Any]:
    if value is None:
        return {}
    if isinstance(value, dict):
        points_raw = _select_first(
            value,
            ["points", "items", "list", "観点", "チェック", "criteria"],
        )
        note_raw = _select_first(
            value,
            ["note", "commentary", "summary", "memo", "コメント", "解説"],
        )
        payload: Dict[str, Any] = {}
        points = _coerce_points(points_raw)
        note = _ensure_text(note_raw)
        if points:
            payload["points"] = points
        if note:
            payload["note"] = note
        return payload
    if isinstance(value, (list, tuple, set)):
        points = _coerce_points(value)
        return {"points": points} if points else {}
    text = _ensure_text(value)
    if text:
        return {"note": text}
    return {}


def _parse_model_answer_slots(payload: Any) -> Dict[str, Dict[str, Any]]:
    if isinstance(payload, dict):
        for key in ("entries", "questions", "items", "data", "slots"):
            nested = payload.get(key)
            if isinstance(nested, list):
                entries = nested
                break
        else:
            entries = [payload]
    elif isinstance(payload, list):
        entries = payload
    else:
        raise ValueError("JSONは配列または entries/items キーを持つオブジェクトで指定してください。")

    results: Dict[str, Dict[str, Any]] = {}
    for entry in entries:
        if not isinstance(entry, dict):
            raise ValueError("各エントリはオブジェクト形式で指定してください。")
        year_raw = _select_first(entry, ["year", "年度"])
        case_raw = _select_first(entry, ["case", "case_label", "事例"])
        question_raw = _select_first(entry, ["question", "question_number", "設問", "設問番号"])

        year = _ensure_text(year_raw)
        case_label = _normalize_case_label(_ensure_text(case_raw)) if case_raw else None
        question_number = _normalize_question_number(question_raw)

        if not year or not case_label or not question_number:
            raise ValueError("年度・事例・設問番号は必須です。値を確認してください。")

        lecturer_a_value = _select_first(entry, ["lecturer_a", "teacher_a", "講師A"])
        lecturer_b_value = _select_first(entry, ["lecturer_b", "teacher_b", "講師B"])
        scoring_value = _select_first(entry, ["scoring", "criteria", "score_points", "採点観点"])

        slot_entry = {
            "year": year,
            "case_label": case_label,
            "question_number": question_number,
            "lecturer_a": _coerce_lecturer_payload(lecturer_a_value),
            "lecturer_b": _coerce_lecturer_payload(lecturer_b_value),
            "scoring": _coerce_scoring_payload(scoring_value),
        }
        key = _compose_slot_key(year, case_label, question_number)
        results[key] = slot_entry

    if not results:
        raise ValueError("登録可能な設問データが見つかりませんでした。")
    return results


def _lookup_custom_model_slot(
    year: Optional[str], case_label: Optional[str], question_number: Optional[int]
) -> Optional[Dict[str, Any]]:
    if not year or not case_label or not question_number:
        return None
    slots: Dict[str, Dict[str, Any]] = st.session_state.get("model_answer_slots", {})
    key = _compose_slot_key(str(year), _normalize_case_label(case_label), int(question_number))
    return slots.get(key)


def _render_caseiii_timeline() -> None:
    if not CASEIII_TIMELINE:
        return

    if not st.session_state.get("_timeline_styles_injected"):
        st.markdown(
            dedent(
                """
                <style>
                .timeline-wrapper {
                    margin-top: 1.6rem;
                    padding: 1.2rem 1rem;
                    border-radius: 18px;
                    background: linear-gradient(120deg, rgba(15, 23, 42, 0.9), rgba(30, 41, 59, 0.92));
                    color: #e2e8f0;
                    border: 1px solid rgba(148, 163, 184, 0.3);
                    overflow: hidden;
                }
                .timeline-wrapper[data-theme="light"] {
                    background: linear-gradient(120deg, rgba(226, 232, 240, 0.95), rgba(203, 213, 225, 0.92));
                    color: #1f2937;
                    border-color: rgba(148, 163, 184, 0.35);
                }
                .timeline-track {
                    display: flex;
                    gap: 1rem;
                    overflow-x: auto;
                    padding-bottom: 0.4rem;
                    scroll-snap-type: x mandatory;
                    animation: timeline-enter 0.9s ease-out;
                }
                .timeline-track::-webkit-scrollbar {
                    height: 6px;
                }
                .timeline-track::-webkit-scrollbar-thumb {
                    background: rgba(148, 163, 184, 0.4);
                    border-radius: 999px;
                }
                .timeline-item {
                    min-width: 240px;
                    background: rgba(15, 23, 42, 0.55);
                    border-radius: 14px;
                    padding: 0.85rem;
                    position: relative;
                    scroll-snap-align: start;
                    border: 1px solid rgba(148, 163, 184, 0.35);
                    transition: transform 0.3s ease, box-shadow 0.3s ease;
                }
                .timeline-wrapper[data-theme="light"] .timeline-item {
                    background: rgba(255, 255, 255, 0.9);
                    border-color: rgba(148, 163, 184, 0.4);
                }
                .timeline-item:hover {
                    transform: translateY(-6px);
                    box-shadow: 0 18px 28px rgba(15, 23, 42, 0.28);
                }
                .timeline-year {
                    font-size: 0.78rem;
                    letter-spacing: 0.1em;
                    color: rgba(226, 232, 240, 0.75);
                    text-transform: uppercase;
                }
                .timeline-wrapper[data-theme="light"] .timeline-year {
                    color: rgba(30, 41, 59, 0.6);
                }
                .timeline-theme {
                    font-weight: 700;
                    margin: 0.3rem 0 0.35rem;
                    font-size: 0.95rem;
                }
                .timeline-focus {
                    font-size: 0.8rem;
                    line-height: 1.5;
                    margin: 0;
                }
                .timeline-item::after {
                    content: attr(data-source);
                    position: absolute;
                    left: 0.8rem;
                    right: 0.8rem;
                    bottom: 0.4rem;
                    font-size: 0.68rem;
                    color: rgba(148, 163, 184, 0.8);
                    opacity: 0;
                    transform: translateY(6px);
                    transition: opacity 0.2s ease, transform 0.2s ease;
                    pointer-events: none;
                }
                .timeline-item:hover::after {
                    opacity: 1;
                    transform: translateY(0);
                }
                @keyframes timeline-enter {
                    from { opacity: 0; transform: translateX(-12px); }
                    to { opacity: 1; transform: translateX(0); }
                }
                </style>
                """
            ),
            unsafe_allow_html=True,
        )
        st.session_state["_timeline_styles_injected"] = True

    theme = "dark" if _resolve_question_card_theme() == "dark" else "light"
    items_html = "".join(
        dedent(
            f"""
            <div class="timeline-item" data-source="PDF: {html.escape(item['source'])}">
                <span class="timeline-year">{html.escape(item['year'])}</span>
                <p class="timeline-theme">{html.escape(item['theme'])}</p>
                <p class="timeline-focus">{html.escape(item['focus'])}</p>
            </div>
            """
        )
        for item in CASEIII_TIMELINE
    )
    st.markdown(
        dedent(
            f"""
            <div class="timeline-wrapper" data-theme="{theme}">
                <div class="timeline-track">
                    {items_html}
                </div>
            </div>
            """
        ),
        unsafe_allow_html=True,
    )


EXAM_YEAR_NOTICE = {
    "R6": {
        "time": "80分 / 4設問構成",
        "notes": [
            "問題冊子と解答用紙は切り離し不可。解答は所定欄に黒または青のボールペンで記入。",
            "冒頭で受験番号と氏名を記載し、余白での下書きは最小限に。配点と制限字数を意識して時間配分。",
            "試験監督の指示があるまで問題冊子を開かない。開始合図後にページを確認し、60分経過時点を意識して見直し時間を確保。",
        ],
    },
    "R5": {
        "time": "80分 / 4設問構成",
        "notes": [
            "設問ごとに制限字数が異なるため、最初に全体を俯瞰して記述分量の見当を付ける。",
            "下線部や番号付き指示など原紙特有の表記に注意し、設問要求語をそのまま拾って構成する。",
            "解答欄外への書き込みは採点対象外。改行は不要で、文末は句点で統一すると読みやすい。",
        ],
    },
}


def _format_reiwa_label(year_label: str) -> str:
    if not year_label:
        return ""
    match = re.search(r"令和(\d+)年", year_label)
    if match:
        return f"R{int(match.group(1))}"
    return year_label


def _year_sort_key(year_label: str) -> int:
    match = re.search(r"令和(\d+)年", year_label)
    if match:
        return int(match.group(1))
    digits = re.findall(r"\d+", year_label)
    if digits:
        return int(digits[0])
    return 0


def _resolve_question_insight(question: Dict[str, Any]) -> Optional[str]:
    question = question or {}
    for key in (
        "uploaded_question_insight",
        "question_insight",
        "insight",
        "設問インサイト",
    ):
        normalized = _normalize_text_block(question.get(key))
        if normalized:
            return normalized
    return None


def _infer_question_aim(question: Dict[str, Any]) -> str:
    question = question or {}
    custom_aim = (
        question.get("uploaded_question_aim")
        or question.get("question_aim")
        or question.get("設問の狙い")
        or question.get("aim")
    )
    if custom_aim:
        return str(custom_aim)

    explanation = question.get("explanation")
    if explanation:
        return explanation
    prompt = question.get("prompt", "")
    return f"{prompt} の背景意図を整理し、与件の根拠に基づいて答えましょう。"


def _describe_output_requirements(question: Dict[str, Any]) -> str:
    question = question or {}
    custom_description = (
        question.get("uploaded_output_format")
        or question.get("output_format")
        or question.get("必要アウトプット形式")
        or question.get("required_output")
    )
    if custom_description:
        return str(custom_description)

    limit = question.get("character_limit")
    if not limit:
        return "明確な文字数指定なし。設問要求語に沿って簡潔に記述します。"
    template = {
        "limit": f"{limit}字以内",
        "score": f"配点 {question.get('max_score', '-')}点",
    }
    if limit <= 80:
        guidance = "結論→理由の2文構成で端的に。重要キーワードを確実に盛り込みましょう。"
    elif limit <= 100:
        guidance = "結論→理由→効果の3要素を1〜2文で整理し、因果と具体性を両立させます。"
    else:
        guidance = "課題→原因→施策の3段構成で、文頭に結論を置きながら補足説明を充実させます。"
    return f"{template['limit']}・{template['score']}。{guidance}"


def _suggest_solution_prompt(question: Dict[str, Any]) -> str:
    question = question or {}
    custom_prompt = (
        question.get("uploaded_solution_prompt")
        or question.get("solution_prompt")
        or question.get("定番解法プロンプト")
        or question.get("解法プロンプト")
    )
    if custom_prompt:
        return str(custom_prompt)

    prompt_text = question.get("prompt", "")
    limit = question.get("character_limit") or 0
    if "課題" in prompt_text and "改善" in prompt_text:
        return "課題→原因→改善策の3段構成。与件根拠を箇条書きで洗い出し、重要語を結論に盛り込む。"
    if "理由" in prompt_text or "効果" in prompt_text:
        return "因→果の2文構成。1文目で結論、2文目で理由・効果を与件の具体表現で裏付ける。"
    if "強み" in prompt_text or "特徴" in prompt_text:
        return "強み抽出テンプレ：①結論（強み）→②根拠（事実）→③活用方向。ブランド・資源・関係性を確認。"
    if limit >= 120:
        return "MECEで論点分解し、P(課題)→A(原因)→S(施策)→E(効果) の流れで80秒以内に骨子化。"
    return "結論先出し→根拠→効果の黄金パターン。設問要求語を冒頭に置き、与件引用で説得力を高める。"


def _problem_data_signature() -> float:
    """Return a signature that changes whenever the problem dataset is updated."""

    db_mtime = 0.0
    seed_mtime = 0.0

    try:
        db_mtime = database.DB_PATH.stat().st_mtime
    except FileNotFoundError:
        db_mtime = 0.0

    try:
        seed_mtime = SEED_PROBLEMS_JSON_PATH.stat().st_mtime
    except FileNotFoundError:
        seed_mtime = 0.0

    return db_mtime + seed_mtime


@st.cache_data(show_spinner=False)
def _load_problem_index(signature: float) -> List[Dict[str, Any]]:
    return database.list_problems()


@st.cache_data(show_spinner=False)
def _load_problem_years(signature: float) -> List[str]:
    return database.list_problem_years()


@st.cache_data(show_spinner=False)
def _load_problem_cases(year: str, signature: float) -> List[str]:
    return database.list_problem_cases(year)


@st.cache_data(show_spinner=False)
def _load_problem_detail(problem_id: int, signature: float) -> Optional[Dict[str, Any]]:
    return database.fetch_problem(problem_id)


@st.cache_data(show_spinner=False)
def _load_problem_by_year_case(
    year: str, case_label: str, signature: float
) -> Optional[Dict[str, Any]]:
    return database.fetch_problem_by_year_case(year, case_label)


def _render_mock_notice_overlay(start_time: datetime, total_minutes: int = 80) -> None:
    if not start_time:
        return

    start_iso = start_time.strftime("%Y-%m-%dT%H:%M:%SZ")
    notice_items = "".join(f"<li>{html.escape(item)}</li>" for item in MOCK_NOTICE_ITEMS)
    total_seconds = total_minutes * 60

    style_css = dedent(
        """
        .mock-overlay {
            position: fixed;
            top: 1.2rem;
            right: 1.2rem;
            width: 320px;
            background: rgba(15, 23, 42, 0.88);
            color: #f8fafc;
            padding: 1.1rem 1.3rem;
            border-radius: 16px;
            box-shadow: 0 18px 40px rgba(15, 23, 42, 0.35);
            z-index: 9999;
            font-size: 0.9rem;
            line-height: 1.5;
            backdrop-filter: blur(6px);
        }
        .mock-overlay h4 {
            margin: 0 0 0.5rem;
            font-size: 1.1rem;
            letter-spacing: 0.05em;
        }
        .mock-overlay-timer {
            font-size: 2.5rem;
            font-weight: 700;
            margin-bottom: 0.2rem;
            font-variant-numeric: tabular-nums;
            transition: color 0.3s ease;
        }
        .mock-overlay[data-state="warn"] .mock-overlay-timer {
            color: #fbbf24;
        }
        .mock-overlay[data-state="critical"] .mock-overlay-timer {
            color: #f87171;
        }
        .mock-overlay[data-state="end"] {
            background: rgba(153, 27, 27, 0.92);
        }
        .mock-overlay hr {
            border: none;
            border-top: 1px solid rgba(148, 163, 184, 0.35);
            margin: 0.8rem 0 0.7rem;
        }
        .mock-overlay ul {
            padding-left: 1.1rem;
            margin: 0 0 0.4rem;
        }
        .mock-overlay li {
            margin-bottom: 0.35rem;
        }
        .mock-overlay small {
            color: rgba(226, 232, 240, 0.75);
            display: block;
            margin-top: 0.6rem;
        }
        @media (max-width: 720px) {
            .mock-overlay {
                left: 1rem;
                right: 1rem;
                width: auto;
            }
        }
        """
    ).strip()

    overlay_body = dedent(
        f"""
        <h4>本番モード</h4>
        <div class=\"mock-overlay-timer\" data-timer>--:--</div>
        <div>残り時間 (80分)</div>
        <hr />
        <p style=\"margin: 0 0 0.3rem; font-weight: 600;\">試験注意事項</p>
        <ul>{notice_items}</ul>
        <small>注意書きはページ上部の切替で隠すことができます。</small>
        """
    ).strip()

    overlay_html = dedent(
        f"""
        <script>
            (function () {{
                const parentWin = window.parent;
                const parentDoc = parentWin.document;
                if (!parentDoc.getElementById('mock-overlay-style')) {{
                    const style = parentDoc.createElement('style');
                    style.id = 'mock-overlay-style';
                    style.textContent = {json.dumps(style_css)};
                    parentDoc.head.appendChild(style);
                }}

                let overlay = parentDoc.getElementById('mock-overlay');
                if (!overlay) {{
                    overlay = parentDoc.createElement('div');
                    overlay.id = 'mock-overlay';
                    overlay.className = 'mock-overlay';
                    overlay.setAttribute('role', 'status');
                    overlay.setAttribute('aria-live', 'polite');
                    parentDoc.body.appendChild(overlay);
                }}

                overlay.innerHTML = {json.dumps(overlay_body)};

                const timerEl = overlay.querySelector('[data-timer]');
                const totalSeconds = {total_seconds};
                const start = new Date('{start_iso}Z');

                function updateTimer() {{
                    const now = new Date();
                    const elapsed = Math.floor((now.getTime() - start.getTime()) / 1000);
                    const remaining = Math.max(totalSeconds - elapsed, 0);
                    const minutes = String(Math.floor(remaining / 60)).padStart(2, '0');
                    const seconds = String(remaining % 60).padStart(2, '0');
                    timerEl.textContent = minutes + ':' + seconds;

                    let state = 'normal';
                    if (remaining === 0) {{
                        state = 'end';
                    }} else if (remaining <= 60) {{
                        state = 'critical';
                    }} else if (remaining <= 300) {{
                        state = 'warn';
                    }}
                    overlay.dataset.state = state;
                }}

                updateTimer();
                parentWin.clearInterval(parentWin.__mockOverlayTimer);
                parentWin.__mockOverlayTimer = parentWin.setInterval(updateTimer, 1000);
            }})();
        </script>
        """
    ).strip()

    components.html(overlay_html, height=0, width=0)


def _remove_mock_notice_overlay() -> None:
    cleanup_script = dedent(
        """
        <script>
            (function () {
                const parentWin = window.parent;
                const parentDoc = parentWin.document;
                const overlay = parentDoc.getElementById('mock-overlay');
                if (overlay) {
                    parentDoc.body.removeChild(overlay);
                }
                const style = parentDoc.getElementById('mock-overlay-style');
                if (style) {
                    parentDoc.head.removeChild(style);
                }
                if (parentWin.__mockOverlayTimer) {
                    parentWin.clearInterval(parentWin.__mockOverlayTimer);
                    delete parentWin.__mockOverlayTimer;
                }
            })();
        </script>
        """
    ).strip()

    components.html(cleanup_script, height=0, width=0)


def _init_session_state() -> None:
    if "user" not in st.session_state:
        guest = database.get_or_create_guest_user()
        st.session_state.user = dict(guest)
    st.session_state.setdefault("page", "ホーム")
    st.session_state.setdefault("drafts", {})
    st.session_state.setdefault("saved_answers", {})
    st.session_state.setdefault("practice_started", None)
    st.session_state.setdefault("mock_session", None)
    st.session_state.setdefault("past_data", None)
    st.session_state.setdefault("past_data_tables", [])
    st.session_state.setdefault("uploaded_case_contexts", {})
    st.session_state.setdefault("uploaded_question_texts", {})
    st.session_state.setdefault("pending_past_data_upload", None)
    st.session_state.setdefault("uploaded_case_metadata", {})
    st.session_state.setdefault("uploaded_question_metadata", {})
    st.session_state.setdefault("pending_model_answer_slot_upload", None)
    st.session_state.setdefault("flashcard_states", {})
    st.session_state.setdefault("flashcard_progress", {})
    st.session_state.setdefault("ui_theme", "システム設定に合わせる")
    st.session_state.setdefault("_intent_card_styles_injected", False)
    st.session_state.setdefault("_question_card_styles_injected", False)
    st.session_state.setdefault("_timeline_styles_injected", False)
    st.session_state.setdefault("model_answer_slots", {})


def _guideline_visibility_key(problem_id: int, question_id: int) -> str:
    return f"guideline_visible::{problem_id}::{question_id}"


def _inject_guideline_styles() -> None:
    if st.session_state.get("_guideline_styles_injected"):
        return

    st.markdown(
        """
        <style>
        .guideline-card {
            margin: 0.5rem 0 1.5rem;
            padding: 1.25rem 1.35rem;
            border-radius: 16px;
            border: 1px solid rgba(148, 163, 184, 0.35);
            background: rgba(248, 250, 252, 0.92);
            box-shadow: 0 14px 32px rgba(15, 23, 42, 0.08);
        }
        .guideline-table {
            width: 100%;
            border-collapse: collapse;
        }
        .guideline-table tr + tr {
            border-top: 1px dashed rgba(148, 163, 184, 0.6);
        }
        .guideline-table th,
        .guideline-table td {
            padding: 0.75rem 0;
            vertical-align: top;
        }
        .guideline-table th {
            width: 32%;
            padding-right: 1rem;
        }
        .guideline-label {
            display: flex;
            align-items: center;
            gap: 0.65rem;
            color: #1f2937;
            font-size: 0.95rem;
            font-weight: 700;
        }
        .guideline-icon {
            display: inline-flex;
            align-items: center;
            justify-content: center;
            width: 2.2rem;
            height: 2.2rem;
            border-radius: 0.9rem;
            background: #111827;
            color: #f9fafb;
            font-weight: 700;
            font-size: 0.85rem;
            letter-spacing: 0.02em;
        }
        .guideline-icon::before {
            content: attr(data-icon);
        }
        .guideline-body {
            margin: 0;
            color: #334155;
            line-height: 1.7;
            font-size: 0.93rem;
        }
        .guideline-meta {
            display: block;
            margin-bottom: 0.45rem;
            color: #64748b;
            font-size: 0.82rem;
            font-weight: 600;
            letter-spacing: 0.01em;
        }
        .guideline-body p {
            margin: 0 0 0.35rem;
        }
        .guideline-body p:last-child {
            margin-bottom: 0;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )
    st.session_state["_guideline_styles_injected"] = True


def _inject_intent_card_styles() -> None:
    if st.session_state.get("_intent_card_styles_injected"):
        return

    st.markdown(
        dedent(
            """
            <style>
            .intent-card-header {
                font-weight: 700;
                color: #0f172a;
                margin-bottom: 0.1rem;
                font-size: 0.92rem;
                letter-spacing: 0.01em;
            }
            .intent-card-grid {
                display: grid;
                grid-template-columns: repeat(auto-fit, minmax(190px, 1fr));
                gap: 0.65rem;
                margin-top: 0.35rem;
                margin-bottom: 0.5rem;
            }
            .intent-card-wrapper {
                background: rgba(248, 250, 252, 0.92);
                border: 1px solid rgba(99, 102, 241, 0.18);
                border-radius: 13px;
                padding: 0.65rem 0.75rem 0.55rem;
                box-shadow: 0 10px 20px rgba(15, 23, 42, 0.06);
                display: flex;
                flex-direction: column;
                gap: 0.35rem;
            }
            .intent-card-wrapper button {
                width: 100%;
                border-radius: 9px;
                border: none;
                background: linear-gradient(135deg, rgba(59, 130, 246, 0.16), rgba(129, 140, 248, 0.22));
                color: #1e293b;
                font-weight: 600;
                font-size: 0.86rem;
                padding: 0.45rem 0.5rem;
                cursor: pointer;
                transition: transform 0.15s ease, box-shadow 0.15s ease;
            }
            .intent-card-wrapper button:hover {
                transform: translateY(-1px);
                box-shadow: 0 8px 20px rgba(99, 102, 241, 0.22);
            }
            .intent-card-example {
                font-size: 0.76rem;
                line-height: 1.45;
                color: #1f2937;
                background: rgba(255, 255, 255, 0.8);
                border-radius: 8px;
                padding: 0.35rem 0.55rem;
                border: 1px dashed rgba(99, 102, 241, 0.28);
                display: -webkit-box;
                -webkit-line-clamp: 3;
                -webkit-box-orient: vertical;
                overflow: hidden;
            }
            .intent-card-example::before {
                content: "✏️ ";
            }
            .case-frame-grid {
                display: grid;
                grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
                gap: 0.6rem;
                margin: 0.35rem 0 0.45rem;
            }
            .case-frame-card {
                background: rgba(248, 250, 252, 0.92);
                border: 1px solid rgba(148, 163, 184, 0.35);
                border-radius: 12px;
                padding: 0.55rem 0.6rem 0.5rem;
                display: flex;
                flex-direction: column;
                gap: 0.3rem;
            }
            .case-frame-card button {
                width: 100%;
                border-radius: 8px;
                border: none;
                background: rgba(255, 255, 255, 0.92);
                color: #0f172a;
                font-weight: 600;
                font-size: 0.85rem;
                padding: 0.4rem 0.45rem;
                cursor: pointer;
                border: 1px solid rgba(59, 130, 246, 0.28);
                transition: transform 0.12s ease, box-shadow 0.12s ease;
            }
            .case-frame-card button:hover {
                transform: translateY(-1px);
                box-shadow: 0 6px 16px rgba(59, 130, 246, 0.2);
            }
            .case-frame-desc {
                font-size: 0.74rem;
                line-height: 1.45;
                color: #475569;
                margin: 0;
            }
            .case-frame-snippet {
                font-size: 0.72rem;
                line-height: 1.4;
                color: #1f2937;
                background: rgba(255, 255, 255, 0.85);
                border-radius: 7px;
                padding: 0.25rem 0.45rem;
                border: 1px dashed rgba(148, 163, 184, 0.4);
                margin: 0;
            }
            </style>
            """
        ),
        unsafe_allow_html=True,
    )
    st.session_state["_intent_card_styles_injected"] = True


def _compact_text(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _format_preview_text(text: str, max_length: int = 72) -> str:
    compact = _compact_text(text)
    if len(compact) <= max_length:
        return compact
    return compact[: max_length - 1].rstrip(" 、。.,;・") + "…"


def _insert_template_snippet(
    draft_key: str, textarea_state_key: str, snippet: str
) -> None:
    snippet = snippet.strip()
    if not snippet:
        return

    current_text = st.session_state.drafts.get(draft_key, "").rstrip()
    if current_text:
        if not current_text.endswith(("。", "！", "？", "\n")):
            current_text += "。"
        new_text = f"{current_text}\n{snippet}"
    else:
        new_text = snippet

    st.session_state.drafts[draft_key] = new_text
    st.session_state[textarea_state_key] = new_text


def _resolve_question_card_theme() -> str:
    theme = st.session_state.get("ui_theme", "システム設定に合わせる")
    if theme == "ダークモード":
        return "dark"
    if theme == "ライトモード":
        return "light"
    return "auto"


def _inject_question_card_styles() -> None:
    if st.session_state.get("_question_card_styles_injected"):
        return

    st.markdown(
        dedent(
            """
            <style>
            .question-mini-card {
                border-radius: 16px;
                padding: 1rem 1.25rem;
                background: linear-gradient(140deg, rgba(30, 41, 59, 0.92), rgba(51, 65, 85, 0.92));
                color: #e2e8f0;
                box-shadow: 0 18px 32px rgba(15, 23, 42, 0.28);
                display: flex;
                flex-direction: column;
                gap: 0.6rem;
                border: 1px solid rgba(148, 163, 184, 0.25);
                position: relative;
                overflow: hidden;
            }
            .question-mini-card[data-theme="light"] {
                background: linear-gradient(135deg, rgba(226, 232, 240, 0.9), rgba(203, 213, 225, 0.95));
                color: #1e293b;
                box-shadow: 0 14px 28px rgba(15, 23, 42, 0.2);
                border-color: rgba(100, 116, 139, 0.35);
            }
            .question-mini-card::before {
                content: "";
                position: absolute;
                inset: -40% -45% auto auto;
                width: 240px;
                height: 240px;
                background: radial-gradient(circle at center, rgba(96, 165, 250, 0.25), transparent 70%);
                opacity: 0.65;
                pointer-events: none;
            }
            .question-mini-card .qm-eyebrow {
                font-size: 0.72rem;
                letter-spacing: 0.12em;
                text-transform: uppercase;
                color: rgba(226, 232, 240, 0.72);
            }
            .question-mini-card[data-theme="light"] .qm-eyebrow {
                color: rgba(30, 41, 59, 0.6);
            }
            .question-mini-card h4 {
                font-size: 1.02rem;
                margin: 0;
                font-weight: 700;
            }
            .question-mini-card p {
                margin: 0;
                font-size: 0.85rem;
                line-height: 1.6;
                color: inherit;
            }
            .question-mini-card .qm-meta {
                display: flex;
                flex-wrap: wrap;
                gap: 0.4rem;
            }
            .question-mini-card .qm-meta span {
                font-size: 0.74rem;
                padding: 0.2rem 0.55rem;
                border-radius: 999px;
                background: rgba(15, 23, 42, 0.28);
                border: 1px solid rgba(148, 163, 184, 0.35);
                color: inherit;
            }
            .question-mini-card[data-theme="light"] .qm-meta span {
                background: rgba(255, 255, 255, 0.75);
                border-color: rgba(148, 163, 184, 0.35);
            }
            .question-mini-card .qm-chips {
                display: flex;
                flex-wrap: wrap;
                gap: 0.3rem;
            }
            .question-mini-card .qm-chip {
                font-size: 0.72rem;
                padding: 0.2rem 0.6rem;
                border-radius: 999px;
                background: rgba(94, 234, 212, 0.12);
                border: 1px solid rgba(148, 163, 184, 0.45);
                color: inherit;
                backdrop-filter: blur(6px);
            }
            .question-mini-card[data-theme="light"] .qm-chip {
                background: rgba(30, 64, 175, 0.12);
                border-color: rgba(59, 130, 246, 0.35);
                color: #1e3a8a;
            }
            </style>
            """
        ),
        unsafe_allow_html=True,
    )
    st.session_state["_question_card_styles_injected"] = True


def _inject_context_highlight_styles() -> None:
    if st.session_state.get("_context_highlight_styles_injected"):
        return

    st.markdown(
        dedent(
            """
            <style>
            .context-highlight {
                border-radius: 0.85rem;
                border: 1px solid rgba(148, 163, 184, 0.45);
                padding: 0.9rem 1rem;
                margin: 0.4rem 0 0.8rem;
                background: linear-gradient(135deg, rgba(59, 130, 246, 0.18), rgba(59, 130, 246, 0.05));
                color: inherit;
            }
            .context-highlight[data-theme="light"] {
                background: linear-gradient(135deg, rgba(219, 234, 254, 0.9), rgba(191, 219, 254, 0.35));
                border-color: rgba(59, 130, 246, 0.35);
            }
            .context-highlight .context-eyebrow {
                display: inline-flex;
                align-items: center;
                gap: 0.35rem;
                font-size: 0.72rem;
                letter-spacing: 0.08em;
                font-weight: 600;
                text-transform: uppercase;
                background: rgba(30, 64, 175, 0.28);
                color: inherit;
                padding: 0.15rem 0.6rem;
                border-radius: 999px;
                border: 1px solid rgba(59, 130, 246, 0.25);
            }
            .context-highlight[data-theme="light"] .context-eyebrow {
                background: rgba(30, 64, 175, 0.12);
                color: #1e3a8a;
            }
            .context-highlight p {
                margin: 0.4rem 0 0;
                line-height: 1.7;
                font-size: 0.95rem;
            }
            </style>
            """
        ),
        unsafe_allow_html=True,
    )
    st.session_state["_context_highlight_styles_injected"] = True


def _inject_context_column_styles() -> None:
    if st.session_state.get("_context_panel_styles_injected_v2"):
        return

    st.markdown(
        dedent(
            """
            <style>
            :root {
                --context-panel-offset: 72px;
            }
            .context-panel-mobile-bar {
                display: none;
            }
            .context-panel-trigger {
                display: none;
                align-items: center;
                justify-content: center;
                gap: 0.4rem;
                width: 100%;
                border-radius: 999px;
                border: 1px solid #e5e7eb;
                background: #ffffff;
                color: #111827;
                font-weight: 600;
                font-size: 0.95rem;
                padding: 0.65rem 1.1rem;
                box-shadow: 0 2px 6px rgba(15, 23, 42, 0.08);
                cursor: pointer;
                transition: transform 120ms ease, box-shadow 120ms ease;
            }
            .context-panel-trigger:hover {
                transform: translateY(-1px);
                box-shadow: 0 8px 18px rgba(15, 23, 42, 0.12);
            }
            .context-panel-trigger:focus-visible,
            .context-panel-close:focus-visible,
            .context-panel-scroll:focus-visible {
                outline: 3px solid rgba(59, 130, 246, 0.45);
                outline-offset: 2px;
            }
            .context-panel-backdrop {
                display: none;
                position: fixed;
                inset: 0;
                background: rgba(15, 23, 42, 0.35);
                z-index: 60;
            }
            .context-panel {
                width: 100%;
                background: #ffffff;
                border: 1px solid #e5e7eb;
                border-radius: 0.5rem;
                padding: 1rem;
                line-height: 1.7;
                box-sizing: border-box;
                margin-bottom: 1.5rem;
            }
            .context-panel-inner {
                display: flex;
                flex-direction: column;
                gap: 0.75rem;
                height: 100%;
            }
            .context-panel-header {
                display: flex;
                align-items: center;
                justify-content: space-between;
                gap: 0.75rem;
            }
            .context-panel-title {
                margin: 0;
                font-size: 1.1rem;
                font-weight: 600;
                color: #111827;
            }
            .context-panel-close {
                display: none;
                border: 1px solid #e5e7eb;
                background: #f9fafb;
                color: #374151;
                border-radius: 999px;
                padding: 0.35rem 0.9rem;
                font-size: 0.85rem;
                cursor: pointer;
            }
            .context-panel-scroll {
                overflow-y: auto;
                padding-right: 0.75rem;
                scrollbar-gutter: stable;
                scrollbar-width: thin;
            }
            .context-panel-scroll::-webkit-scrollbar {
                width: 0.5rem;
            }
            .context-panel-scroll::-webkit-scrollbar-thumb {
                background-color: rgba(100, 116, 139, 0.55);
                border-radius: 999px;
            }
            .context-panel-scroll::-webkit-scrollbar-track {
                background-color: transparent;
            }
            @media (min-width: 901px) {
                .context-panel {
                    position: sticky;
                    top: var(--context-panel-offset, 72px);
                }
                .context-panel-scroll {
                    max-height: calc(100vh - 96px);
                }
            }
            @media (max-width: 900px) {
                .context-panel-mobile-bar {
                    display: block;
                    position: sticky;
                    top: var(--context-panel-offset, 72px);
                    z-index: 65;
                    padding: 0.25rem 0;
                    margin-bottom: 0.75rem;
                    background: linear-gradient(180deg, #ffffff 75%, rgba(255, 255, 255, 0));
                }
                .context-panel-trigger {
                    display: inline-flex;
                }
                .context-panel {
                    display: none;
                    position: fixed;
                    top: var(--context-panel-offset, 72px);
                    left: 50%;
                    transform: translateX(-50%);
                    width: min(640px, 92vw);
                    height: 85vh;
                    max-height: 90vh;
                    padding: 1.25rem;
                    margin-bottom: 0;
                    z-index: 70;
                    box-shadow: 0 24px 48px rgba(15, 23, 42, 0.25);
                }
                body.context-panel-open {
                    overflow: hidden;
                }
                body.context-panel-open .context-panel {
                    display: flex;
                    flex-direction: column;
                }
                body.context-panel-open .context-panel-backdrop {
                    display: block;
                }
                .context-panel-close {
                    display: inline-flex;
                    align-items: center;
                    justify-content: center;
                    background: #ffffff;
                }
                .context-panel-scroll {
                    flex: 1 1 auto;
                    max-height: none;
                }
            }
            </style>
            """
        ),
        unsafe_allow_html=True,
    )
    st.session_state["_context_panel_styles_injected_v2"] = True


def _inject_context_panel_behavior() -> None:
    st.markdown(
        dedent(
            """
            <script>
            (() => {
                const setupContextPanel = () => {
                    const doc = window.document;
                    const openButton = doc.querySelector('.context-panel-trigger');
                    const closeButton = doc.querySelector('.context-panel-close');
                    const backdrop = doc.querySelector('.context-panel-backdrop');
                    const panel = doc.getElementById('context-panel');
                    const scrollArea = panel ? panel.querySelector('.context-panel-scroll') : null;

                    if (panel && !panel.hasAttribute('aria-hidden')) {
                        panel.setAttribute('aria-hidden', 'true');
                    }

                    const setOpen = (open, options = {}) => {
                        const { suppressFocus = false, skipReturnFocus = false } = options;
                        if (!doc.body) {
                            return;
                        }
                        doc.body.classList.toggle('context-panel-open', open);
                        if (openButton) {
                            openButton.setAttribute('aria-expanded', open ? 'true' : 'false');
                        }
                        if (panel) {
                            panel.setAttribute('aria-hidden', open ? 'false' : 'true');
                        }
                        if (open && scrollArea && !suppressFocus) {
                            scrollArea.focus({ preventScroll: false });
                        }
                        if (!open && openButton && !skipReturnFocus) {
                            openButton.focus();
                        }
                    };

                    if (openButton && !openButton.dataset.bound) {
                        openButton.dataset.bound = 'true';
                        openButton.setAttribute('aria-expanded', 'false');
                        openButton.addEventListener('click', () => setOpen(true));
                        openButton.addEventListener('keydown', (event) => {
                            if (event.key === 'Enter' || event.key === ' ') {
                                event.preventDefault();
                                setOpen(true);
                            }
                        });
                    }

                    if (closeButton && !closeButton.dataset.bound) {
                        closeButton.dataset.bound = 'true';
                        closeButton.addEventListener('click', () => setOpen(false));
                        closeButton.addEventListener('keydown', (event) => {
                            if (event.key === 'Enter' || event.key === ' ') {
                                event.preventDefault();
                                setOpen(false);
                            }
                        });
                    }

                    if (backdrop && !backdrop.dataset.bound) {
                        backdrop.dataset.bound = 'true';
                        backdrop.addEventListener('click', () => setOpen(false));
                    }

                    const mediaQuery = window.matchMedia('(max-width: 900px)');
                    const syncForViewport = (mq) => {
                        if (!panel) {
                            return;
                        }
                        if (mq.matches) {
                            setOpen(false, { suppressFocus: true, skipReturnFocus: true });
                        } else {
                            panel.setAttribute('aria-hidden', 'false');
                            if (openButton) {
                                openButton.setAttribute('aria-expanded', 'true');
                            }
                            if (doc.body) {
                                doc.body.classList.remove('context-panel-open');
                            }
                        }
                    };

                    syncForViewport(mediaQuery);
                    if (mediaQuery.addEventListener) {
                        mediaQuery.addEventListener('change', syncForViewport);
                    } else if (mediaQuery.addListener) {
                        mediaQuery.addListener(syncForViewport);
                    }

                    if (doc.body && !doc.body.dataset.contextPanelEscapeBound) {
                        doc.body.dataset.contextPanelEscapeBound = 'true';
                        doc.addEventListener('keydown', (event) => {
                            if (event.key === 'Escape') {
                                setOpen(false, { suppressFocus: true });
                            }
                        });
                    }
                };

                if (document.readyState === 'loading') {
                    document.addEventListener('DOMContentLoaded', setupContextPanel);
                } else {
                    setupContextPanel();
                }
            })();
            </script>
            """
        ),
        unsafe_allow_html=True,
    )


def _render_question_context_block(context_value: Any) -> None:
    context_text = _normalize_text_block(context_value)
    if not context_text:
        return

    normalized = context_text.replace("\r\n", "\n").replace("\r", "\n")
    lines = [line.strip() for line in normalized.split("\n") if line.strip()]
    if not lines:
        return

    summary = " / ".join(lines[:2])
    if len(summary) > 160:
        summary = summary[:157].rstrip() + "…"

    _inject_context_highlight_styles()
    theme = _resolve_question_card_theme()
    st.markdown(
        dedent(
            f"""
            <div class="context-highlight" data-theme="{theme}">
                <span class="context-eyebrow">与件ハイライト</span>
                <p>{html.escape(summary)}</p>
            </div>
            """
        ),
        unsafe_allow_html=True,
    )

    with st.expander("与件文を全文表示", expanded=False):
        st.write("\n\n".join(lines))


def _split_long_japanese_paragraph(paragraph: str, max_chars: int = 120) -> List[str]:
    """Heuristically split a long Japanese paragraph into shorter segments.

    The 与件文データ often arrives as a single block of text without paragraph
    breaks. To improve readability we chunk the text by sentences (句点終止) while
    keeping each chunk reasonably sized.
    """

    stripped = paragraph.strip()
    if len(stripped) <= max_chars:
        return [stripped] if stripped else []

    sentences = [
        s.strip()
        for s in re.findall(r"[^。！？]+[。！？]?", stripped)
        if s.strip()
    ]

    if len(sentences) <= 1:
        return [stripped]

    chunks: List[str] = []
    current = ""
    for sentence in sentences:
        if not current:
            current = sentence
            continue

        candidate = f"{current}{sentence}"
        if len(candidate) <= max_chars or len(current) < max_chars * 0.6:
            current = candidate
            continue

        chunks.append(current.strip())
        current = sentence

    if current:
        chunks.append(current.strip())

    # Fall back to the original paragraph if the heuristic failed to create
    # multiple meaningful chunks.
    if len(chunks) <= 1:
        return [stripped]

    return chunks


def _render_problem_context_block(context_text: str) -> None:
    normalized = _normalize_text_block(context_text)
    if not normalized:
        return

    paragraphs: List[str] = []
    for raw_block in normalized.replace("\r\n", "\n").replace("\r", "\n").split("\n\n"):
        paragraph = raw_block.strip()
        if paragraph:
            paragraphs.append(paragraph)

    if not paragraphs:
        return

    if len(paragraphs) == 1:
        paragraphs = _split_long_japanese_paragraph(paragraphs[0])

    blocks: List[str] = []
    for paragraph in paragraphs:
        lines = [html.escape(line.strip()) for line in paragraph.split("\n") if line.strip()]
        if lines:
            blocks.append(f"<p>{'<br/>'.join(lines)}</p>")

    if not blocks:
        return

    element_id = f"problem-context-{uuid.uuid4().hex}"
    toolbar_id = f"{element_id}-toolbar"
    total_lines = sum(block.count("<br/>") + 1 for block in blocks)
    estimated_height = max(620, min(1200, 260 + total_lines * 30))

    highlight_html = dedent(
        f"""
        <div class="problem-context-root">
            <div class="context-toolbar" id="{toolbar_id}">
                <div class="toolbar-actions">
                    <button type="button" class="toolbar-button toggle" data-action="highlight" data-target="{element_id}" aria-pressed="false" data-default-color="amber">
                        選択範囲にマーカー
                    </button>
                    <div class="marker-palette" role="group" aria-label="マーカー色">
                        <button type="button" class="marker-color selected" data-action="set-color" data-color="amber" aria-label="イエローマーカー"></button>
                        <button type="button" class="marker-color" data-action="set-color" data-color="rose" aria-label="ピンクマーカー"></button>
                        <button type="button" class="marker-color" data-action="set-color" data-color="sky" aria-label="ブルーマーカー"></button>
                        <button type="button" class="marker-color" data-action="set-color" data-color="lime" aria-label="グリーンマーカー"></button>
                    </div>
                    <button type="button" class="toolbar-button undo" data-action="undo" aria-disabled="true" disabled>
                        直前の操作を取り消す
                    </button>
                    <button type="button" class="toolbar-button clear" data-action="clear-all" data-target="{element_id}">
                        マーカーを全て解除
                    </button>
                </div>
                <span class="toolbar-hint">テキストをドラッグして蛍光マーカーを適用できます。</span>
            </div>
            <div class="problem-context-block" id="{element_id}" tabindex="0">
                {''.join(blocks)}
            </div>
        </div>
        <style>
            * {{
                box-sizing: border-box;
            }}
            body {{
                margin: 0;
                font-family: "Noto Sans JP", "Yu Gothic", sans-serif;
                color: #0f172a;
            }}
            .problem-context-root {{
                width: 100%;
                display: flex;
                flex-direction: column;
                gap: 0.65rem;
                min-height: min(85vh, 880px);
                height: 100%;
            }}
            @media (max-width: 1099px) {{
                .problem-context-root {{
                    height: auto;
                    min-height: auto;
                }}
            }}
            .context-toolbar {{
                display: flex;
                flex-direction: column;
                gap: 0.35rem;
                font-size: 0.82rem;
                color: #475569;
                position: sticky;
                top: 0;
                z-index: 12;
                padding: 0.6rem 0.75rem;
                border-radius: 14px;
                background: linear-gradient(180deg, rgba(255, 255, 255, 0.98), rgba(248, 250, 252, 0.95));
                border: 1px solid rgba(148, 163, 184, 0.18);
                box-shadow: 0 8px 18px rgba(15, 23, 42, 0.08);
                backdrop-filter: blur(6px);
            }}
            .context-toolbar.is-floating {{
                box-shadow: 0 16px 36px rgba(15, 23, 42, 0.16);
            }}
            .toolbar-actions {{
                display: flex;
                flex-wrap: wrap;
                align-items: center;
                gap: 0.5rem;
            }}
            .toolbar-button {{
                background: linear-gradient(135deg, rgba(250, 204, 21, 0.85), rgba(234, 179, 8, 0.65));
                color: #422006;
                border: none;
                border-radius: 999px;
                padding: 0.35rem 0.95rem;
                font-size: 0.82rem;
                font-weight: 600;
                cursor: pointer;
                box-shadow: inset 0 0 0 1px rgba(120, 53, 15, 0.15);
                transition: transform 120ms ease, box-shadow 120ms ease;
            }}
            .toolbar-button.toggle.active {{
                box-shadow: inset 0 0 0 2px rgba(120, 53, 15, 0.35), 0 6px 14px rgba(234, 179, 8, 0.32);
                transform: translateY(-1px);
            }}
            .toolbar-button:hover {{
                transform: translateY(-1px);
                box-shadow: inset 0 0 0 1px rgba(120, 53, 15, 0.28), 0 6px 12px rgba(234, 179, 8, 0.25);
            }}
            .toolbar-button:active {{
                transform: translateY(0);
            }}
            .toolbar-button.undo {{
                background: linear-gradient(135deg, rgba(59, 130, 246, 0.16), rgba(29, 78, 216, 0.12));
                color: #1d4ed8;
                box-shadow: inset 0 0 0 1px rgba(37, 99, 235, 0.28);
            }}
            .toolbar-button.undo:hover {{
                box-shadow: inset 0 0 0 1px rgba(37, 99, 235, 0.35), 0 6px 12px rgba(37, 99, 235, 0.28);
            }}
            .toolbar-button.undo:disabled {{
                background: rgba(226, 232, 240, 0.85);
                color: rgba(71, 85, 105, 0.9);
                box-shadow: inset 0 0 0 1px rgba(148, 163, 184, 0.3);
                cursor: not-allowed;
                opacity: 0.88;
                transform: none;
                pointer-events: none;
            }}
            .toolbar-button.clear {{
                background: rgba(15, 23, 42, 0.08);
                color: #0f172a;
                box-shadow: inset 0 0 0 1px rgba(15, 23, 42, 0.2);
            }}
            .toolbar-button.clear:hover {{
                box-shadow: inset 0 0 0 1px rgba(15, 23, 42, 0.35), 0 6px 14px rgba(15, 23, 42, 0.18);
            }}
            .marker-palette {{
                display: inline-flex;
                align-items: center;
                gap: 0.4rem;
                padding: 0.25rem 0.45rem;
                border-radius: 999px;
                background: rgba(15, 23, 42, 0.06);
                box-shadow: inset 0 0 0 1px rgba(15, 23, 42, 0.12);
            }}
            .marker-color {{
                width: 1.35rem;
                height: 1.35rem;
                border-radius: 50%;
                border: none;
                cursor: pointer;
                padding: 0;
                position: relative;
                background: transparent;
                box-shadow: 0 0 0 1px rgba(15, 23, 42, 0.15);
                transition: transform 120ms ease, box-shadow 120ms ease;
            }}
            .marker-color:focus-visible {{
                outline: 2px solid rgba(37, 99, 235, 0.8);
                outline-offset: 2px;
            }}
            .marker-color::after {{
                content: "";
                position: absolute;
                inset: 0.15rem;
                border-radius: 50%;
                background: currentColor;
                opacity: 0.85;
            }}
            .marker-color[data-color="amber"] {{
                color: rgba(250, 204, 21, 1);
            }}
            .marker-color[data-color="rose"] {{
                color: rgba(244, 114, 182, 1);
            }}
            .marker-color[data-color="sky"] {{
                color: rgba(125, 211, 252, 1);
            }}
            .marker-color[data-color="lime"] {{
                color: rgba(163, 230, 53, 1);
            }}
            .marker-color:hover {{
                transform: translateY(-1px);
                box-shadow: 0 3px 6px rgba(15, 23, 42, 0.12), 0 0 0 1px rgba(15, 23, 42, 0.2);
            }}
            .marker-color.selected {{
                box-shadow: 0 0 0 2px #fff, 0 0 0 4px rgba(15, 23, 42, 0.35);
            }}
            .toolbar-hint {{
                font-size: 0.76rem;
            }}
            .problem-context-block {{
                border-left: 4px solid rgba(37, 99, 235, 0.8);
                background: rgba(37, 99, 235, 0.06);
                padding: 1.1rem 1.35rem;
                border-radius: 14px;
                margin: 0 0 0.3rem;
                line-height: 1.75;
                font-size: 0.96rem;
                outline: none;
                overflow-y: auto;
                flex: 1 1 auto;
                min-height: 320px;
                max-height: 100%;
                scrollbar-gutter: stable both-edges;
                user-select: text;
            }}
            .problem-context-block p {{
                margin: 0 0 0.9rem;
            }}
            .problem-context-block p:last-child {{
                margin-bottom: 0;
            }}
            .problem-context-block mark.fluorescent-marker {{
                padding: 0 0.15rem;
                border-radius: 0.2rem;
                box-shadow: 0 0 0 1px rgba(202, 138, 4, 0.05);
                background: linear-gradient(transparent 40%, rgba(250, 204, 21, 0.95) 40%);
            }}
            .problem-context-block mark.fluorescent-marker.color-amber {{
                background: linear-gradient(transparent 40%, rgba(250, 204, 21, 0.95) 40%);
                box-shadow: 0 0 0 1px rgba(217, 119, 6, 0.12);
            }}
            .problem-context-block mark.fluorescent-marker.color-rose {{
                background: linear-gradient(transparent 40%, rgba(244, 114, 182, 0.9) 40%);
                box-shadow: 0 0 0 1px rgba(190, 24, 93, 0.12);
            }}
            .problem-context-block mark.fluorescent-marker.color-sky {{
                background: linear-gradient(transparent 40%, rgba(125, 211, 252, 0.9) 40%);
                box-shadow: 0 0 0 1px rgba(14, 116, 144, 0.12);
            }}
            .problem-context-block mark.fluorescent-marker.color-lime {{
                background: linear-gradient(transparent 40%, rgba(163, 230, 53, 0.9) 40%);
                box-shadow: 0 0 0 1px rgba(63, 98, 18, 0.12);
            }}
        </style>
        <script>
            (function() {{
                const container = document.getElementById("{element_id}");
                const toolbar = document.getElementById("{toolbar_id}");
                if (!container || !toolbar) {{
                    return;
                }}

                const highlightButton = toolbar.querySelector('[data-action="highlight"]');
                const undoButton = toolbar.querySelector('[data-action="undo"]');
                const clearButton = toolbar.querySelector('[data-action="clear-all"]');
                const colorButtons = Array.from(toolbar.querySelectorAll('[data-action="set-color"]'));

                let highlightMode = false;
                let activeColor = (highlightButton && highlightButton.dataset.defaultColor) || (colorButtons[0] && colorButtons[0].dataset.color) || "amber";
                const history = [];
                const maxHistory = 30;

                const updateUndoState = () => {{
                    if (!undoButton) {{
                        return;
                    }}
                    const disabled = history.length === 0;
                    undoButton.disabled = disabled;
                    undoButton.setAttribute("aria-disabled", disabled ? "true" : "false");
                }};

                const pushHistory = (snapshot) => {{
                    if (!undoButton || !snapshot || history[history.length - 1] === snapshot) {{
                        return;
                    }}
                    history.push(snapshot);
                    if (history.length > maxHistory) {{
                        history.shift();
                    }}
                    updateUndoState();
                }};

                updateUndoState();

                const setHighlightMode = (value) => {{
                    highlightMode = Boolean(value);
                    if (highlightButton) {{
                        highlightButton.classList.toggle("active", highlightMode);
                        highlightButton.setAttribute("aria-pressed", highlightMode ? "true" : "false");
                    }}
                }};

                const applyHighlight = () => {{
                    const selection = window.getSelection();
                    if (!selection || selection.rangeCount === 0) {{
                        return false;
                    }}
                    const range = selection.getRangeAt(0);
                    if (range.collapsed) {{
                        return false;
                    }}
                    if (!container.contains(range.commonAncestorContainer)) {{
                        return false;
                    }}

                    const snapshot = container.innerHTML;
                    const mark = document.createElement("mark");
                    mark.className = "fluorescent-marker color-" + activeColor;
                    mark.appendChild(range.extractContents());
                    range.insertNode(mark);
                    container.normalize();
                    selection.removeAllRanges();
                    pushHistory(snapshot);
                    return true;
                }};

                const clearAll = () => {{
                    const marks = Array.from(container.querySelectorAll("mark.fluorescent-marker"));
                    if (!marks.length) {{
                        return false;
                    }}
                    const snapshot = container.innerHTML;
                    marks.forEach((mark) => {{
                        const parent = mark.parentNode;
                        if (!parent) {{
                            return;
                        }}
                        while (mark.firstChild) {{
                            parent.insertBefore(mark.firstChild, mark);
                        }}
                        parent.removeChild(mark);
                        parent.normalize();
                    }});
                    pushHistory(snapshot);
                    return true;
                }};

                const scheduleAutoHighlight = () => {{
                    if (!highlightMode) {{
                        return;
                    }}
                    requestAnimationFrame(() => {{
                        applyHighlight();
                    }});
                }};

                if (highlightButton) {{
                    highlightButton.addEventListener("click", () => {{
                        const nextState = !highlightMode;
                        setHighlightMode(nextState);
                        if (nextState) {{
                            if (!applyHighlight()) {{
                                container.focus();
                            }}
                        }} else {{
                            const selection = window.getSelection();
                            if (selection) {{
                                selection.removeAllRanges();
                            }}
                        }}
                    }});
                }}

                if (clearButton) {{
                    clearButton.addEventListener("click", () => {{
                        const changed = clearAll();
                        if (!changed) {{
                            return;
                        }}
                        const selection = window.getSelection();
                        if (selection) {{
                            selection.removeAllRanges();
                        }}
                    }});
                }}

                if (undoButton) {{
                    undoButton.addEventListener("click", () => {{
                        if (!history.length) {{
                            return;
                        }}
                        const previous = history.pop();
                        container.innerHTML = previous;
                        container.normalize();
                        updateUndoState();
                        const selection = window.getSelection();
                        if (selection) {{
                            selection.removeAllRanges();
                        }}
                    }});
                }}

                if (colorButtons.length) {{
                    colorButtons.forEach((button) => {{
                        button.addEventListener("click", () => {{
                            const nextColor = button.dataset.color || "amber";
                            activeColor = nextColor;
                            colorButtons.forEach((candidate) => {{
                                candidate.classList.toggle("selected", candidate === button);
                            }});
                            if (highlightMode) {{
                                requestAnimationFrame(() => {{
                                    applyHighlight();
                                }});
                            }}
                        }});
                    }});
                }}

                container.addEventListener("keydown", (event) => {{
                    if (event.key === "Escape") {{
                        if (highlightMode) {{
                            setHighlightMode(false);
                        }}
                        const selection = window.getSelection();
                        if (selection) {{
                            selection.removeAllRanges();
                        }}
                        return;
                    }}
                    const allowed = [
                        "ArrowLeft",
                        "ArrowRight",
                        "ArrowUp",
                        "ArrowDown",
                        "Home",
                        "End",
                        "PageUp",
                        "PageDown",
                        "Shift",
                        "Control",
                        "Meta",
                        "Alt",
                        "Tab",
                        "Escape"
                    ];
                    if (allowed.includes(event.key)) {{
                        return;
                    }}
                    event.preventDefault();
                }});

                container.addEventListener("beforeinput", (event) => {{
                    event.preventDefault();
                }});
                ["paste", "drop"].forEach((type) => {{
                    container.addEventListener(type, (event) => event.preventDefault());
                }});

                ["mouseup", "keyup", "touchend"].forEach((type) => {{
                    container.addEventListener(type, () => {{
                        scheduleAutoHighlight();
                    }});
                }});

                const handleScroll = () => {{
                    if (!toolbar) {{
                        return;
                    }}
                    toolbar.classList.toggle("is-floating", container.scrollTop > 4);
                }};
                container.addEventListener("scroll", handleScroll);
                handleScroll();

            }})();
        </script>
        """
    )

    components.html(highlight_html, height=estimated_height, scrolling=True)


def _render_question_overview_card(
    question: Dict[str, Any],
    *,
    case_label: Optional[str] = None,
    source_label: Optional[str] = None,
) -> None:
    if not question:
        return

    _inject_question_card_styles()
    theme = _resolve_question_card_theme()
    prompt = html.escape(question.get("prompt") or question.get("設問見出し") or "設問")
    order = question.get("order") or question.get("設問番号")
    eyebrow = f"設問{order}" if order else "設問"
    limit = question.get("character_limit") or question.get("制限字数")
    max_score = question.get("max_score") or question.get("配点")

    element_label = "3点構成"
    if limit and int(limit) <= 80:
        element_label = "2点構成"

    meta_items = [element_label]
    if limit and pd.notna(limit):
        meta_items.append(f"{int(limit)}字以内")
    if max_score is not None and not pd.isna(max_score):
        if isinstance(max_score, (int, float)) and float(max_score).is_integer():
            score_label = str(int(max_score))
        else:
            score_label = str(max_score)
        meta_items.append(f"配点 {score_label}点")
    if source_label:
        meta_items.append(source_label)

    question_for_aim = dict(question)
    if not question_for_aim.get("prompt") and question_for_aim.get("問題文"):
        first_line = str(question_for_aim["問題文"]).splitlines()[0].strip()
        if first_line:
            question_for_aim["prompt"] = first_line
    aim_text = question.get("aim") or _infer_question_aim(question_for_aim)
    aim = html.escape(aim_text)

    frames = CASE_FRAME_SHORTCUTS.get(case_label or question.get("case_label") or "", [])
    frame_labels = [frame.get("label") for frame in frames[:4] if frame.get("label")]

    meta_html = "".join(f"<span>{html.escape(str(item))}</span>" for item in meta_items if item)
    chips_html = "".join(
        f"<span class=\"qm-chip\">{html.escape(label)}</span>" for label in frame_labels
    )

    st.markdown(
        dedent(
            f"""
            <div class="question-mini-card" data-theme="{theme}">
                <span class="qm-eyebrow">{html.escape(eyebrow)}</span>
                <h4>{prompt}</h4>
                <div class="qm-meta">{meta_html}</div>
                <p>{aim}</p>
                <div class="qm-chips">{chips_html}</div>
            </div>
            """
        ),
        unsafe_allow_html=True,
    )


def _render_intent_cards(
    question: Dict[str, Any], draft_key: str, textarea_state_key: str
) -> None:
    cards: List[Dict[str, str]] = [
        card
        for card in question.get("intent_cards", [])
        if card and card.get("label") and card.get("example")
    ]
    if not cards:
        return

    _inject_intent_card_styles()
    st.markdown("<p class=\"intent-card-header\">設問趣旨カード</p>", unsafe_allow_html=True)
    st.caption("クリックで例示表現をドラフトに素早く差し込めます。ホバーで全文を確認できます。")

    grid_container = st.container()
    with grid_container:
        st.markdown("<div class=\"intent-card-grid\">", unsafe_allow_html=True)
        for index, card in enumerate(cards):
            st.markdown("<div class=\"intent-card-wrapper\">", unsafe_allow_html=True)
            clicked = st.button(
                card["label"],
                key=f"intent-card-{draft_key}-{index}",
                use_container_width=True,
            )
            example_text = card["example"]
            preview_text = _format_preview_text(example_text, 90)
            st.markdown(
                (
                    "<div class=\"intent-card-example\" title=\"{title}\">"
                    "例: {preview}</div>"
                ).format(
                    title=html.escape(_compact_text(example_text), quote=True),
                    preview=html.escape(preview_text),
                ),
                unsafe_allow_html=True,
            )
            st.markdown("</div>", unsafe_allow_html=True)
            if clicked:
                _insert_template_snippet(draft_key, textarea_state_key, card["example"])
                st.session_state["_intent_card_notice"] = {
                    "draft_key": draft_key,
                    "label": card["label"],
                }
        st.markdown("</div>", unsafe_allow_html=True)


def _render_case_frame_shortcuts(
    case_label: Optional[str], draft_key: str, textarea_state_key: str
) -> None:
    if not case_label:
        return

    frames = CASE_FRAME_SHORTCUTS.get(case_label)
    if not frames:
        return

    st.markdown("<p class=\"intent-card-header\">頻出フレーム</p>", unsafe_allow_html=True)
    st.caption("一読で狙いを掴み、クリックで定番フレーズを挿入できます。")

    grid_container = st.container()
    with grid_container:
        st.markdown("<div class=\"case-frame-grid\">", unsafe_allow_html=True)
        for index, frame in enumerate(frames):
            st.markdown("<div class=\"case-frame-card\">", unsafe_allow_html=True)
            clicked = st.button(
                frame["label"],
                key=f"case-frame-{draft_key}-{index}",
                use_container_width=True,
                help=frame.get("description"),
            )
            description = frame.get("description")
            if description:
                desc_preview = _format_preview_text(description, 68)
                st.markdown(
                    (
                        "<p class=\"case-frame-desc\" title=\"{title}\">"
                        "{content}</p>"
                    ).format(
                        title=html.escape(_compact_text(description), quote=True),
                        content=html.escape(desc_preview),
                    ),
                    unsafe_allow_html=True,
                )
            snippet = frame.get("snippet")
            if snippet:
                snippet_preview = _format_preview_text(snippet, 74)
                st.markdown(
                    (
                        "<p class=\"case-frame-snippet\" title=\"{title}\">"
                        "{content}</p>"
                    ).format(
                        title=html.escape(_compact_text(snippet), quote=True),
                        content=html.escape(snippet_preview),
                    ),
                    unsafe_allow_html=True,
                )
            st.markdown("</div>", unsafe_allow_html=True)
            if clicked:
                _insert_template_snippet(draft_key, textarea_state_key, frame["snippet"])
                st.session_state["_case_frame_notice"] = {
                    "draft_key": draft_key,
                    "label": frame["label"],
                }
        st.markdown("</div>", unsafe_allow_html=True)


def _format_amount(value: Optional[float]) -> str:
    if value is None:
        return "-"
    if isinstance(value, float) and not math.isfinite(value):
        return "-"
    return f"{value:,.1f}"


def _format_percent(value: Optional[float]) -> str:
    if value is None:
        return "-"
    if isinstance(value, float) and not math.isfinite(value):
        return "-"
    return f"{value * 100:.1f}%"


def _render_case_iv_bridge(draft_key: str) -> None:
    prefix = f"cvp_bridge_{draft_key}"
    st.markdown("##### 事例IV『計算→記述』ブリッジ")
    st.caption(
        "令和5・6年のCVP分析レイアウトに合わせ、損益分岐点の計算結果から記述ドラフトまでをワンストップで整理します。"
    )

    input_col1, input_col2, input_col3 = st.columns(3)
    with input_col1:
        sales = st.number_input(
            "実績売上高（万円）",
            min_value=0.0,
            value=st.session_state.get(f"{prefix}_sales", 0.0),
            step=10.0,
            key=f"{prefix}_sales",
        )
    with input_col2:
        variable_percent = st.number_input(
            "変動費率（%）",
            min_value=0.0,
            max_value=99.9,
            value=st.session_state.get(f"{prefix}_variable", 60.0),
            step=0.1,
            key=f"{prefix}_variable",
        )
    with input_col3:
        fixed_cost = st.number_input(
            "固定費（万円）",
            min_value=0.0,
            value=st.session_state.get(f"{prefix}_fixed", 0.0),
            step=10.0,
            key=f"{prefix}_fixed",
        )

    variable_ratio = variable_percent / 100.0
    contribution_margin_ratio = 1.0 - variable_ratio
    cm_ratio_valid = contribution_margin_ratio > 0

    st.markdown("**① 変動費率・固定費**")
    contribution_margin_text = (
        _format_percent(contribution_margin_ratio) if cm_ratio_valid else "-"
    )
    st.markdown(
        f"{'✅' if cm_ratio_valid else '⚠️'} 貢献利益率 {_format_percent(contribution_margin_ratio) if cm_ratio_valid else '算出不可'}"
        f" / 固定費 {_format_amount(fixed_cost)}万円"
    )

    break_even_sales = None
    if cm_ratio_valid:
        break_even_sales = fixed_cost / contribution_margin_ratio if contribution_margin_ratio else None

    st.markdown("**② 損益分岐点 (BEP)**")
    if break_even_sales is None:
        st.markdown("⚠️ 貢献利益率が0%以下のため損益分岐点を計算できません。変動費率の前提を見直しましょう。")
    else:
        gap_amount = sales - break_even_sales
        gap_direction = "上回る" if gap_amount >= 0 else "下回る"
        st.markdown(
            f"{'✅' if sales > 0 else '⚠️'} 損益分岐点売上高 {_format_amount(break_even_sales)}万円"
            f"（実績との差 {_format_amount(abs(gap_amount))}万円{gap_direction}）"
        )

    st.markdown("**③ 安全余裕率**")
    safety_margin_ratio = None
    safety_margin_amount = None
    if break_even_sales is not None and sales > 0:
        safety_margin_amount = sales - break_even_sales
        safety_margin_ratio = safety_margin_amount / sales

    if safety_margin_ratio is None:
        st.markdown("⚠️ 売上高を入力すると安全余裕率が自動計算されます。")
    else:
        if safety_margin_ratio < 0:
            status_icon = "❌"
            evaluation = "損益分岐点を下回っており赤字圏です。固定費削減や売上拡大が急務です。"
        elif safety_margin_ratio < 0.05:
            status_icon = "⚠️"
            evaluation = "安全余裕率が5%未満と極小です。単価向上や固定費圧縮で余裕を確保しましょう。"
        elif safety_margin_ratio < 0.15:
            status_icon = "⚠️"
            evaluation = "安全余裕率が1桁台と小さいため、コスト管理と高付加価値施策で厚みを持たせましょう。"
        else:
            status_icon = "✅"
            evaluation = "安全余裕率に一定の余裕があり、貢献利益率向上や固定費回収後の利益拡大策が検討できます。"

        st.markdown(
            f"{status_icon} 安全余裕率 {_format_percent(safety_margin_ratio)}"
            f"（余裕 {_format_amount(abs(safety_margin_amount or 0.0))}万円）"
        )
        st.caption(evaluation)

    analysis_lines: List[str] = []
    analysis_lines.append(
        f"売上高{_format_amount(sales)}万円、変動費率{variable_percent:.1f}%"
        f"（貢献利益率 {contribution_margin_text}）で固定費{_format_amount(fixed_cost)}万円と整理。"
    )

    if break_even_sales is None:
        analysis_lines.append(
            "貢献利益率が確保できず損益分岐点を計算できないため、コスト構造の把握と前提の再確認を優先します。"
        )
    else:
        gap_amount = sales - break_even_sales
        gap_phrase = "上回" if gap_amount >= 0 else "下回"
        analysis_lines.append(
            f"損益分岐点売上高は{_format_amount(break_even_sales)}万円で、実績との差は"
            f"{_format_amount(abs(gap_amount))}万円{gap_phrase}っている。"
        )
        if safety_margin_ratio is None:
            analysis_lines.append("安全余裕率の算定には売上高入力が必要です。値を確定させて余裕度を評価しましょう。")
        else:
            if safety_margin_ratio < 0:
                action_text = "赤字脱却に向けた固定費削減と売上テコ入れを記述で強調する。"
            elif safety_margin_ratio < 0.05:
                action_text = "安全余裕が薄いため、短期施策での単価・数量増と固定費圧縮を提案する。"
            elif safety_margin_ratio < 0.15:
                action_text = "余裕が限定的なため、貢献利益率向上策と費用対効果の高い投資選別を述べる。"
            else:
                action_text = "余裕を活かし、固定費回収後の利益拡大策や投資判断へ接続する。"
            analysis_lines.append(
                f"安全余裕率は{_format_percent(safety_margin_ratio)}で、{action_text}"
            )

    analysis_text = "".join(analysis_lines)
    draft_state_key = f"{prefix}_draft"
    st.session_state[draft_state_key] = analysis_text

    st.markdown("**④ 示唆ドラフト**")
    st.caption("計算結果を要約した文章をコピーして答案骨子に活用できます。")
    st.text_area(
        "ドラフト (自動生成)",
        value=st.session_state[draft_state_key],
        height=140,
        key=draft_state_key,
        disabled=True,
    )


def _ensure_media_styles() -> None:
    if st.session_state.get("_media_styles_injected"):
        return

    st.markdown(
        dedent(
            """
            <style>
            .media-player video {
                width: 100%;
                border-radius: 16px;
                box-shadow: 0 16px 30px rgba(15, 23, 42, 0.18);
            }
            .media-player__controls {
                margin-top: 0.75rem;
                display: flex;
                flex-direction: column;
                gap: 0.65rem;
            }
            .media-player__row {
                display: flex;
                flex-wrap: wrap;
                align-items: center;
                gap: 0.5rem;
            }
            .media-player__row span {
                font-weight: 600;
                color: #1f2937;
            }
            .media-control-button {
                background: #f8fafc;
                border: 1px solid rgba(99, 102, 241, 0.35);
                color: #1e293b;
                border-radius: 999px;
                padding: 0.35rem 0.9rem;
                font-size: 0.85rem;
                cursor: pointer;
                transition: all 0.2s ease;
            }
            .media-control-button:hover {
                background: rgba(99, 102, 241, 0.1);
            }
            .media-control-button.active {
                background: #4338ca;
                color: #fff;
                border-color: #4338ca;
            }
            </style>
            """
        ),
        unsafe_allow_html=True,
    )
    st.session_state["_media_styles_injected"] = True


def _render_video_player(url: str, *, key_prefix: str) -> None:
    if not url:
        return

    _ensure_media_styles()
    player_id = f"media-player-{key_prefix}-{uuid4().hex}"
    escaped_url = html.escape(url, quote=True)
    speeds = [0.75, 1.0, 1.25, 1.5, 2.0]
    speed_buttons = "".join(
        f'<button class="media-control-button" data-speed="{speed}">{speed}x</button>'
        for speed in speeds
    )

    components.html(
        dedent(
            f"""
            <div class="media-player" id="{player_id}">
              <video controls playsinline preload="metadata" src="{escaped_url}"></video>
              <div class="media-player__controls">
                <div class="media-player__row">
                  <span>再生速度</span>
                  {speed_buttons}
                </div>
                <div class="media-player__row">
                  <button class="media-control-button" data-action="back">⏪ 10秒戻る</button>
                  <button class="media-control-button" data-action="forward">⏩ 10秒進む</button>
                </div>
              </div>
            </div>
            <script>
            (function() {{
              const container = document.getElementById('{player_id}');
              if (!container) return;
              const video = container.querySelector('video');
              const speedButtons = Array.from(container.querySelectorAll('[data-speed]'));
              const backButton = container.querySelector('[data-action="back"]');
              const forwardButton = container.querySelector('[data-action="forward"]');

              function setActiveSpeed(rate) {{
                if (!video) return;
                video.playbackRate = rate;
                speedButtons.forEach((button) => {{
                  const isActive = Number(button.dataset.speed) === rate;
                  button.classList.toggle('active', isActive);
                }});
              }}

              speedButtons.forEach((button) => {{
                button.addEventListener('click', () => {{
                  const rate = Number(button.dataset.speed) || 1.0;
                  setActiveSpeed(rate);
                }});
              }});

              if (backButton) {{
                backButton.addEventListener('click', () => {{
                  if (!video) return;
                  video.currentTime = Math.max(0, video.currentTime - 10);
                }});
              }}

              if (forwardButton) {{
                forwardButton.addEventListener('click', () => {{
                  if (!video) return;
                  const target = video.currentTime + 10;
                  video.currentTime = Math.min(video.duration || target, target);
                }});
              }}

              setActiveSpeed(1.0);
            }})();
            </script>
            """
        ),
        height=380,
    )


def _resolve_diagram_path(diagram_path: str) -> Path:
    path = Path(diagram_path)
    if not path.is_absolute():
        base_dir = Path(__file__).resolve().parent
        path = base_dir / path
    return path


def _render_diagram_resource(diagram_path: Optional[str], caption: Optional[str]) -> None:
    if not diagram_path:
        return

    path = _resolve_diagram_path(diagram_path)
    if not path.exists():
        st.warning("図解ファイルが見つかりませんでした。", icon="⚠️")
        return

    try:
        st.image(path.read_bytes(), caption=caption, use_column_width=True)
    except Exception as exc:  # pragma: no cover - rendering guard
        st.warning(f"図解の表示中に問題が発生しました: {exc}", icon="⚠️")


def _render_slot_lecturer_tab(tab: "st._DeltaGenerator", payload: Dict[str, str], empty_message: str) -> None:
    with tab:
        if not payload or not any(value for value in payload.values()):
            st.caption(empty_message)
            return
        answer_text = payload.get("answer")
        commentary_text = payload.get("commentary")
        if answer_text:
            st.markdown("**模範解答**")
            st.write(answer_text)
        if commentary_text:
            st.markdown("**講評**")
            st.write(commentary_text)


def _render_slot_scoring_tab(tab: "st._DeltaGenerator", payload: Dict[str, Any]) -> None:
    with tab:
        if not payload:
            st.caption("採点観点は登録されていません。JSONの 'scoring' または '採点観点' キーを確認してください。")
            return
        points = payload.get("points") or []
        note = payload.get("note")
        if points:
            st.markdown("**チェックポイント**")
            st.markdown("\n".join(f"- {point}" for point in points))
        if note:
            st.markdown("**講評メモ**")
            st.write(note)
        if not points and not note:
            st.caption("採点観点の内容が空です。JSONの配列やコメントを設定してください。")


def _render_model_answer_section(
    *,
    model_answer: Any,
    explanation: Any,
    video_url: Optional[str],
    diagram_path: Optional[str],
    diagram_caption: Optional[str],
    context_id: str,
    year: Optional[str] = None,
    case_label: Optional[str] = None,
    question_number: Optional[int] = None,
    detailed_explanation: Optional[str] = None,
) -> None:
    custom_slot = _lookup_custom_model_slot(year, case_label, question_number)
    if custom_slot:
        st.markdown("**ワンクリック模範解答スロット**")
        tab_a, tab_b, tab_scoring = st.tabs(["講師A", "講師B", "採点観点"])
        _render_slot_lecturer_tab(
            tab_a,
            custom_slot.get("lecturer_a", {}),
            "講師Aのスロットが未設定です。JSONの 'lecturer_a' / '講師A' を確認してください。",
        )
        _render_slot_lecturer_tab(
            tab_b,
            custom_slot.get("lecturer_b", {}),
            "講師Bのスロットが未設定です。JSONの 'lecturer_b' / '講師B' を確認してください。",
        )
        _render_slot_scoring_tab(tab_scoring, custom_slot.get("scoring", {}))
        st.caption(
            f"年度: {custom_slot['year']} / {custom_slot['case_label']} 第{custom_slot['question_number']}問"
        )

    model_answer_text = _normalize_text_block(model_answer)
    explanation_text = _normalize_text_block(explanation)
    detailed_text = _normalize_text_block(detailed_explanation)

    st.write("**模範解答**")
    if model_answer_text:
        st.write(model_answer_text)
    else:
        st.caption("模範解答が登録されていません。")

    st.write("**解説サマリ**")
    if explanation_text:
        st.write(explanation_text)
    else:
        st.caption("解説が登録されていません。")

    if detailed_text:
        with st.expander("詳細解説をじっくり読む", expanded=False):
            st.write(detailed_text)
            st.caption("採点者視点の根拠や書き方のポイントを深掘りできます。")

    if video_url:
        st.markdown("**動画解説**")
        _render_video_player(video_url, key_prefix=context_id)
        st.caption("倍速再生と10秒スキップで効率的に復習できます。")

    if diagram_path:
        st.markdown("**図解で押さえるポイント**")
        _render_diagram_resource(diagram_path, diagram_caption)

def main_view() -> None:
    user = st.session_state.user

    navigation_items = {
        "ホーム": dashboard_page,
        "過去問演習": practice_page,
        "模擬試験": mock_exam_page,
        "学習履歴": history_page,
        "設定": settings_page,
    }

    st.sidebar.title("ナビゲーション")
    st.sidebar.markdown(
        dedent(
            """
            <style>
            section[data-testid="stSidebar"] div[role="radiogroup"] > label[data-baseweb="radio"] {
                margin-bottom: 0.3rem;
            }
            section[data-testid="stSidebar"] div[role="radiogroup"] > label[data-baseweb="radio"] > div:first-child {
                display: none;
            }
            section[data-testid="stSidebar"] div[role="radiogroup"] > label[data-baseweb="radio"] > div:last-child {
                width: 100%;
                padding: 0.5rem 0.75rem;
                border-radius: 0.6rem;
                border: 1px solid transparent;
                transition: background-color 0.2s ease, border-color 0.2s ease, color 0.2s ease;
            }
            section[data-testid="stSidebar"] div[role="radiogroup"] > label[data-baseweb="radio"] > div:last-child:hover {
                border-color: rgba(49, 51, 63, 0.2);
                background-color: rgba(49, 51, 63, 0.05);
            }
            section[data-testid="stSidebar"] div[role="radiogroup"] > label[data-baseweb="radio"] > input:checked + div {
                background-color: rgba(49, 51, 63, 0.06);
                border-color: var(--primary-color);
                color: var(--primary-color);
                box-shadow: 0 0 0 1px var(--primary-color) inset;
                font-weight: 600;
            }
            </style>
            """
        ).strip(),
        unsafe_allow_html=True,
    )

    nav_labels = list(navigation_items.keys())
    if st.session_state.page not in navigation_items:
        st.session_state.page = nav_labels[0]

    navigation_key = "navigation_selection"
    current_page = st.session_state.page

    if navigation_key not in st.session_state:
        st.session_state[navigation_key] = current_page
    elif st.session_state[navigation_key] not in navigation_items:
        st.session_state[navigation_key] = current_page

    selected_page = st.sidebar.radio(
        "ページを選択",
        nav_labels,
        key=navigation_key,
    )

    st.session_state.page = selected_page

    st.sidebar.divider()
    st.sidebar.info(f"利用者: {user['name']} ({user['plan']}プラン)")
    st.sidebar.caption(
        "必要な情報にすぐアクセスできるよう、ページ別にコンテンツを整理しています。"
    )

    page = st.session_state.page
    navigation_items[page](user)


def _inject_dashboard_styles() -> None:
    if st.session_state.get("_dashboard_styles_injected"):
        return

    st.markdown(
        dedent(
            """
            <style>
            [data-testid="stAppViewContainer"] {
                background: linear-gradient(180deg, #f3f6fb 0%, #ffffff 45%);
            }
            .block-container {
                padding: 1.2rem 1.8rem 3rem;
                max-width: min(1500px, 96vw);
            }
            .metric-row {
                display: grid;
                grid-template-columns: repeat(auto-fit, minmax(210px, 1fr));
                gap: 1rem;
                margin-top: 1rem;
            }
            .metric-card {
                position: relative;
                border-radius: 18px;
                padding: 1.4rem;
                color: #0f172a;
                background: linear-gradient(135deg, rgba(255,255,255,0.95), rgba(241,245,249,0.95));
                border: 1px solid rgba(148, 163, 184, 0.35);
                box-shadow: 0 16px 30px rgba(15, 23, 42, 0.12);
            }
            .metric-card::after {
                content: "";
                position: absolute;
                inset: 1px;
                border-radius: 16px;
                border: 1px solid rgba(255,255,255,0.5);
            }
            .metric-card .metric-label {
                font-size: 0.9rem;
                font-weight: 600;
                color: #475569;
                letter-spacing: 0.04em;
                text-transform: uppercase;
            }
            .metric-card .metric-value {
                font-size: 2rem;
                font-weight: 700;
                margin: 0.4rem 0;
            }
            .metric-card .metric-desc {
                font-size: 0.85rem;
                color: #64748b;
                margin: 0;
            }
            .metric-card.progress {
                background: linear-gradient(135deg, #1d4ed8, #2563eb);
                color: #f8fafc;
            }
            .metric-card.progress .metric-label,
            .metric-card.progress .metric-desc {
                color: rgba(248, 250, 252, 0.85);
            }
            .metric-card.score {
                background: linear-gradient(135deg, #15803d, #22c55e);
                color: #0f172a;
            }
            .metric-card.alert {
                background: linear-gradient(135deg, #f97316, #fb923c);
                color: #0f172a;
            }
            .insight-grid {
                display: grid;
                grid-template-columns: repeat(auto-fit, minmax(250px, 1fr));
                gap: 1rem;
                margin: 1.5rem 0 0;
            }
            .insight-card {
                display: flex;
                gap: 1rem;
                align-items: center;
                border-radius: 18px;
                padding: 1.2rem 1.4rem;
                background: #ffffff;
                border: 1px solid rgba(148, 163, 184, 0.28);
                box-shadow: 0 20px 32px rgba(15, 23, 42, 0.12);
            }
            .insight-icon {
                font-size: 1.8rem;
            }
            .insight-title {
                font-weight: 600;
                margin: 0;
                color: #475569;
            }
            .insight-value {
                font-size: 1.35rem;
                font-weight: 700;
                margin: 0.2rem 0 0.3rem;
                color: #0f172a;
            }
            .insight-desc {
                font-size: 0.85rem;
                margin: 0;
                color: #64748b;
            }
            .action-grid {
                display: grid;
                grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
                gap: 1rem;
                margin-top: 1rem;
            }
            .action-card {
                border-radius: 16px;
                padding: 1.2rem 1.3rem;
                background: linear-gradient(135deg, rgba(37,99,235,0.08), rgba(14,165,233,0.08));
                border: 1px solid rgba(148, 163, 184, 0.3);
                box-shadow: 0 12px 24px rgba(15, 23, 42, 0.08);
            }
            .action-card strong {
                display: block;
                font-size: 1.05rem;
                margin-bottom: 0.4rem;
                color: #1e293b;
            }
            .action-card p {
                margin: 0;
                font-size: 0.88rem;
                color: #475569;
            }
            .table-card {
                border-radius: 18px;
                padding: 1.2rem 1rem 0.6rem;
                background: rgba(255, 255, 255, 0.95);
                border: 1px solid rgba(226, 232, 240, 0.7);
                box-shadow: 0 10px 20px rgba(15, 23, 42, 0.08);
            }
            .stTabs [data-baseweb="tab-list"] {
                gap: 0.6rem;
                padding: 0.4rem;
                background: rgba(226, 232, 240, 0.5);
                border-radius: 999px;
            }
            .stTabs [data-baseweb="tab"] {
                border-radius: 999px;
                padding: 0.4rem 1.4rem;
                background: rgba(255,255,255,0.7);
                border: 1px solid transparent;
            }
            .stTabs [aria-selected="true"] {
                background: rgba(37, 99, 235, 0.14) !important;
                border-color: rgba(59, 130, 246, 0.4) !important;
                color: #1d4ed8 !important;
            }
            </style>
            """
        ).strip(),
        unsafe_allow_html=True,
    )
    st.session_state["_dashboard_styles_injected"] = True


def _format_datetime_label(value: datetime | str | None) -> str:
    if isinstance(value, datetime):
        return value.strftime("%Y年%m月%d日")
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value)
            return parsed.strftime("%Y年%m月%d日")
        except ValueError:
            return value
    return "記録なし"


def _format_duration_minutes(total_minutes: int) -> str:
    hours, minutes = divmod(total_minutes, 60)
    if hours and minutes:
        return f"{hours}時間{minutes}分"
    if hours:
        return f"{hours}時間"
    return f"{minutes}分"


def _goal_period(period_type: str, reference: dt_date) -> tuple[dt_date, dt_date]:
    if period_type == "weekly":
        start = reference - timedelta(days=reference.weekday())
        end = start + timedelta(days=6)
    else:
        start = reference.replace(day=1)
        if start.month == 12:
            next_month = start.replace(year=start.year + 1, month=1, day=1)
        else:
            next_month = start.replace(month=start.month + 1, day=1)
        end = next_month - timedelta(days=1)
    return start, end


def _distribute_minutes(total_minutes: int, total_days: int) -> List[int]:
    if total_days <= 0:
        return []
    base = total_minutes // total_days if total_minutes else 0
    remainder = total_minutes % total_days if total_minutes else 0
    distribution: List[int] = []
    for index in range(total_days):
        minutes = base
        if remainder and index < remainder:
            minutes += 1
        distribution.append(minutes)
    return distribution


def _generate_default_sessions(
    *,
    period_type: str,
    start: dt_date,
    end: dt_date,
    total_minutes: int,
    preferred_time: dt_time,
    practice_target: int,
    score_target: float,
) -> List[Dict[str, Any]]:
    total_days = (end - start).days + 1
    preferred_time = preferred_time or dt_time(hour=20, minute=0)
    distribution = _distribute_minutes(total_minutes, total_days)
    label = "週間" if period_type == "weekly" else "月間"
    sessions: List[Dict[str, Any]] = []
    for offset in range(total_days):
        session_date = start + timedelta(days=offset)
        duration = distribution[offset] if offset < len(distribution) else 0
        description = (
            f"{label}目標: 演習{practice_target}回 / 平均{score_target:.0f}点を目指す学習時間"
        )
        sessions.append(
            {
                "session_date": session_date,
                "start_time": preferred_time,
                "duration_minutes": duration,
                "description": description,
            }
        )
    return sessions


def _build_calendar_export(
    *, goal: Dict[str, Any], sessions: List[Dict[str, Any]], user_name: str
) -> bytes:
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//Shindanshi Planner//JP",
        "CALSCALE:GREGORIAN",
    ]
    now_stamp = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
    summary_label = "週間学習" if goal["period_type"] == "weekly" else "月間学習"
    for index, session in enumerate(sessions):
        start_dt = datetime.combine(session["session_date"], session["start_time"])
        duration = max(int(session.get("duration_minutes", 0)), 0)
        end_dt = start_dt + timedelta(minutes=duration or 30)
        uid = f"{goal['id']}-{index}-{uuid.uuid4().hex[:8]}@studyplanner"
        description = session.get("description", "")
        lines.extend(
            [
                "BEGIN:VEVENT",
                f"UID:{uid}",
                f"DTSTAMP:{now_stamp}",
                f"DTSTART:{start_dt.strftime('%Y%m%dT%H%M%S')}",
                f"DTEND:{end_dt.strftime('%Y%m%dT%H%M%S')}",
                f"SUMMARY:{summary_label} ({user_name})",
                f"DESCRIPTION:{description.replace(chr(10), ' ')}",
            ]
        )
        lines.append("END:VEVENT")
    lines.append("END:VCALENDAR")
    return "\r\n".join(lines).encode("utf-8")


def _render_committee_heatmap_section(default_year: str = "令和7年度") -> None:
    dataset = committee_analysis.load_committee_dataset()
    if not dataset:
        return

    df = committee_analysis.flatten_profiles(dataset)
    if df.empty:
        return

    summary_df = committee_analysis.aggregate_heatmap(df)
    if summary_df.empty:
        return

    year_label = dataset.get("year", default_year)

    st.subheader("試験委員“専門×事例”ヒートマップ")
    st.caption(f"{year_label}の基本/出題委員の専門領域と担当事例をマッピングしました。")

    primary_focus = committee_analysis.identify_primary_focus(dataset, summary_df)
    if primary_focus:
        info_lines = [f"今年の“重心”は「{primary_focus['label']}」。"]
        rationale = primary_focus.get("rationale")
        if rationale:
            info_lines.append(str(rationale))
        study_list = primary_focus.get("study_list") or []
        if study_list:
            info_lines.append("推奨テーマ: " + " / ".join(study_list[:3]))
        st.info("\n".join(info_lines), icon="🎯")

    domain_order = committee_analysis.domain_order(summary_df)
    chart_data = summary_df.copy()
    chart = (
        alt.Chart(chart_data)
        .mark_rect()
        .encode(
            x=alt.X("事例:N", sort=CASE_ORDER, title="事例"),
            y=alt.Y("専門カテゴリ:N", sort=domain_order, title="専門領域"),
            color=alt.Color(
                "重み:Q",
                scale=alt.Scale(scheme="blues", domainMin=0),
                title="影響度",
            ),
            tooltip=[
                alt.Tooltip("専門カテゴリ:N", title="専門領域"),
                alt.Tooltip("事例:N", title="事例"),
                alt.Tooltip("重み:Q", title="重み", format=".2f"),
                alt.Tooltip("委員数:Q", title="担当委員数"),
                alt.Tooltip("重点テーマ:N", title="重点テーマ"),
            ],
        )
        .properties(height=320)
    )
    text_layer = (
        alt.Chart(chart_data)
        .mark_text(color="#0f172a", fontSize=12)
        .encode(
            x="事例:N",
            y="専門カテゴリ:N",
            text=alt.Text("重み:Q", format=".1f"),
        )
    )
    st.altair_chart(chart + text_layer, use_container_width=True)

    recommendations = committee_analysis.focus_recommendations(summary_df, limit=5)
    if recommendations:
        st.markdown("**狙い撃ち予習リスト**")
        for item in recommendations:
            themes = item.get("themes", [])
            comment = item.get("comment")
            bullet = f"- **{item.get('case', '')} × {item.get('domain', '')}**"
            if comment:
                bullet += f" — {comment}"
            st.markdown(bullet)
            if themes:
                st.caption("推奨演習: " + " / ".join(themes[:3]))

    cross_focuses = committee_analysis.cross_focus_highlights(dataset, limit=2)
    if cross_focuses:
        st.markdown("**横断テーマ候補**")
        for entry in cross_focuses:
            cases = "・".join(entry.get("cases", []))
            headline = f"- 🔗 **{entry.get('label', '')}**"
            if cases:
                headline += f" ({cases})"
            rationale = entry.get("rationale")
            if rationale:
                headline += f" — {rationale}"
            st.markdown(headline)
            study_list = entry.get("study_list") or []
            if study_list:
                st.caption("推奨演習: " + " / ".join(study_list[:3]))


def _render_study_planner(user: Dict) -> None:
    today = dt_date.today()
    st.subheader("スタディプランナー")
    st.caption("週間・月間の学習目標を設定し、進捗と予定を一括で管理できます。")
    weekly_tab, monthly_tab = st.tabs(["週間プラン", "月間プラン"])
    with weekly_tab:
        _render_study_goal_panel(user, period_type="weekly", reference_date=today)
    with monthly_tab:
        _render_study_goal_panel(user, period_type="monthly", reference_date=today)


def _render_study_goal_panel(
    user: Dict, *, period_type: str, reference_date: dt_date
) -> None:
    label = "週間" if period_type == "weekly" else "月間"
    start, end = _goal_period(period_type, reference_date)
    st.markdown(f"**対象期間:** {start.strftime('%Y-%m-%d')} 〜 {end.strftime('%Y-%m-%d')}")

    existing_goal = database.get_current_study_goal(
        user_id=user["id"], period_type=period_type, reference_date=reference_date
    )
    default_practice = int(existing_goal["target_practice_count"]) if existing_goal else 3
    default_minutes = int(existing_goal["target_study_minutes"]) if existing_goal else 300
    default_hours = round(default_minutes / 60, 1) if default_minutes else 0.0
    default_score = float(existing_goal["target_score"]) if existing_goal else 65.0
    default_time = existing_goal["preferred_start_time"] if existing_goal else dt_time(20, 0)

    with st.form(f"{period_type}_goal_form", clear_on_submit=False):
        practice_target = st.number_input(
            "演習回数目標 (回)", min_value=0, value=default_practice, step=1
        )
        study_hours = st.number_input(
            "学習時間目標 (時間)", min_value=0.0, step=0.5, value=float(default_hours)
        )
        score_target = st.number_input(
            "平均得点目標 (点)", min_value=0.0, step=1.0, value=float(default_score)
        )
        preferred_time = st.time_input("学習開始時間", value=default_time or dt_time(20, 0))
        submitted = st.form_submit_button("目標を保存")

    if submitted:
        target_minutes = int(round(study_hours * 60))
        goal_id = database.upsert_study_goal(
            user_id=user["id"],
            period_type=period_type,
            start_date=start,
            end_date=end,
            target_practice_count=int(practice_target),
            target_study_minutes=target_minutes,
            target_score=float(score_target),
            preferred_start_time=preferred_time,
        )
        sessions = _generate_default_sessions(
            period_type=period_type,
            start=start,
            end=end,
            total_minutes=target_minutes,
            preferred_time=preferred_time,
            practice_target=int(practice_target),
            score_target=float(score_target),
        )
        database.replace_study_sessions(goal_id, sessions)
        st.success(f"{label}目標を保存しました。外部カレンダーへの同期も更新されています。")
        st.experimental_rerun()

    goal = database.get_current_study_goal(
        user_id=user["id"], period_type=period_type, reference_date=reference_date
    )
    if not goal:
        st.info(f"{label}目標を設定すると進捗が表示されます。")
        return

    progress = database.aggregate_attempts_between(
        user_id=user["id"], start_date=goal["start_date"], end_date=goal["end_date"]
    )
    practice_target = goal["target_practice_count"]
    time_target = goal["target_study_minutes"]
    score_target = goal["target_score"]

    practice_ratio = (
        progress["practice_count"] / practice_target if practice_target else 0.0
    )
    time_ratio = (
        progress["total_duration_minutes"] / time_target if time_target else 0.0
    )
    score_ratio = (
        progress["average_score"] / score_target if score_target else 0.0
    )

    col1, col2, col3 = st.columns(3)
    practice_value = (
        f"{progress['practice_count']} / {practice_target} 回"
        if practice_target
        else f"{progress['practice_count']} 回"
    )
    practice_delta = (
        f"{practice_ratio * 100:.0f}% 達成" if practice_target else "目標未設定"
    )
    time_value = (
        f"{progress['total_duration_minutes']} / {time_target} 分"
        if time_target
        else f"{progress['total_duration_minutes']} 分"
    )
    time_delta = f"{time_ratio * 100:.0f}% 達成" if time_target else "目標未設定"
    score_value = (
        f"{progress['average_score']:.1f} / {score_target:.1f} 点"
        if score_target
        else f"{progress['average_score']:.1f} 点"
    )
    score_delta = f"{score_ratio * 100:.0f}% 達成" if score_target else "目標未設定"

    with col1:
        st.metric("演習回数進捗", practice_value, delta=practice_delta)
    with col2:
        st.metric("学習時間進捗", time_value, delta=time_delta)
    with col3:
        st.metric("平均得点進捗", score_value, delta=score_delta)

    st.progress(min(practice_ratio, 1.0) if practice_target else 1.0)
    st.caption("演習回数の進捗率")
    st.progress(min(time_ratio, 1.0) if time_target else 1.0)
    st.caption("学習時間の進捗率")
    st.progress(min(score_ratio, 1.0) if score_target else 1.0)
    st.caption("得点目標の達成率 (平均点)")

    total_days = (goal["end_date"] - goal["start_date"]).days + 1
    days_elapsed = (min(dt_date.today(), goal["end_date"]) - goal["start_date"]).days + 1
    days_elapsed = max(1, min(days_elapsed, total_days))
    expected_ratio = days_elapsed / total_days if total_days else 1.0

    if (
        practice_ratio >= 1.0
        and (time_target == 0 or time_ratio >= 1.0)
        and (score_target == 0 or score_ratio >= 1.0)
    ):
        st.success(f"{label}目標をすべて達成しました！引き続き学習を継続しましょう。")
    elif practice_ratio < expected_ratio - 0.2 or time_ratio < expected_ratio - 0.2:
        st.warning(
            f"{label}目標の進捗が想定より遅れています。カレンダーの予定を活用して学習時間を確保しましょう。"
        )
    else:
        st.info(f"{label}目標は計画通りに進んでいます。今のペースを維持しましょう。")

    sessions = database.list_study_sessions(goal["id"])
    if sessions:
        session_df = pd.DataFrame(
            [
                {
                    "日付": session["session_date"].strftime("%Y-%m-%d (%a)"),
                    "開始": session["start_time"].strftime("%H:%M"),
                    "予定時間": f"{session['duration_minutes']}分",
                    "内容": session["description"] or "",
                }
                for session in sessions
            ]
        )
        st.markdown("### 日々の学習予定")
        st.data_editor(session_df, hide_index=True, disabled=True, use_container_width=True)

        ics_bytes = _build_calendar_export(goal=goal, sessions=sessions, user_name=user["name"])
        st.download_button(
            f"{label}プランを外部カレンダーへ同期 (ICS)",
            data=ics_bytes,
            file_name=f"{period_type}_study_plan.ics",
            mime="text/calendar",
        )
        st.caption(
            "ダウンロードした ICS ファイルを Google カレンダーや Notion のカレンダーにインポートすると、予定が自動登録されます。"
        )
    else:
        st.info("学習時間目標を設定すると日々の予定が自動生成されます。")


def dashboard_page(user: Dict) -> None:
    _inject_dashboard_styles()

    st.title("ホームダッシュボード")
    st.caption("学習状況のサマリと機能へのショートカット")

    attempts = database.list_attempts(user_id=user["id"])
    gamification = _calculate_gamification(attempts)
    total_attempts = len(attempts)
    total_score = sum(row["total_score"] or 0 for row in attempts)
    total_max = sum(row["total_max_score"] or 0 for row in attempts)
    average_score = round(total_score / total_attempts, 1) if total_attempts else 0
    completion_rate = (total_score / total_max * 100) if total_max else 0

    point_col, streak_col, badge_col = st.columns([1, 1, 2])
    with point_col:
        st.metric("累計ポイント", f"{gamification['points']} pt")
        level_progress = 0.0
        if gamification["level_threshold"]:
            level_progress = gamification["level_progress"] / gamification["level_threshold"]
        st.progress(min(level_progress, 1.0))
        if gamification["points"] == 0:
            st.caption("演習を実施するとポイントが貯まりレベルアップします。")
        else:
            st.caption(
                f"レベル{gamification['level']} / 次のレベルまであと {gamification['points_to_next_level']} pt"
            )
    with streak_col:
        st.metric("連続学習日数", f"{gamification['current_streak']}日")
        if gamification["next_milestone"]:
            progress = gamification["attempts"] / gamification["next_milestone"]
            st.progress(min(progress, 1.0))
            st.caption(
                f"次の称号まであと {max(gamification['next_milestone'] - gamification['attempts'], 0)} 回の演習"
            )
        else:
            st.caption("最高ランクに到達しました！継続おめでとうございます。")
    with badge_col:
        st.subheader("獲得バッジ")
        if gamification["badges"]:
            for badge in gamification["badges"]:
                st.markdown(f"- 🏅 **{badge['title']}** — {badge['description']}")
        else:
            st.caption("バッジはまだありません。演習や模試で獲得を目指しましょう。")

    stats = database.aggregate_statistics(user["id"])
    total_learning_minutes = sum((row["duration_seconds"] or 0) for row in attempts) // 60

    best_case_label = None
    best_case_rate = 0.0
    if stats:
        case_ratios = [
            (case_label, (values["avg_score"] / values["avg_max"] * 100) if values["avg_max"] else 0)
            for case_label, values in stats.items()
        ]
        if case_ratios:
            best_case_label, best_case_rate = max(case_ratios, key=lambda item: item[1])

    metric_cards = [
        {
            "label": "演習回数",
            "value": f"{total_attempts}回",
            "desc": "これまで解いたケースの累計",
            "class": "progress",
        },
        {
            "label": "平均得点",
            "value": f"{average_score}点",
            "desc": "全演習の平均スコア",
            "class": "score",
        },
        {
            "label": "得点達成率",
            "value": f"{completion_rate:.0f}%",
            "desc": "満点に対する平均達成度",
            "class": "score",
        },
        {
            "label": "得意な事例",
            "value": best_case_label or "記録なし",
            "desc": f"平均達成率 {best_case_rate:.0f}%" if best_case_label else "データが蓄積されると表示されます",
            "class": "progress",
        },
    ]

    card_blocks = "\n".join(
        dedent(
            f"""
            <div class="metric-card {card['class']}">
                <div class="metric-label">{card['label']}</div>
                <div class="metric-value">{card['value']}</div>
                <p class="metric-desc">{card['desc']}</p>
            </div>
            """
        ).strip()
        for card in metric_cards
    )
    st.markdown(
        dedent(
            f"""
            <div class="metric-row">
            {card_blocks}
            </div>
            """
        ).strip(),
        unsafe_allow_html=True,
    )

    _render_committee_heatmap_section()
    _render_study_planner(user)

    upcoming_reviews = database.list_upcoming_reviews(user_id=user["id"], limit=6)
    due_review_count = database.count_due_reviews(user_id=user["id"])
    st.subheader("復習スケジュール（間隔反復）")
    if upcoming_reviews:
        if due_review_count:
            st.warning(
                f"{due_review_count}件の復習が期限到来または超過しています。優先的に取り組みましょう。",
                icon="⏳",
            )
        schedule_df = pd.DataFrame(
            [
                {
                    "次回予定": review["due_at"].strftime("%Y-%m-%d"),
                    "事例": f"{review['year']} {review['case_label']}",
                    "タイトル": review["title"],
                    "前回達成度": f"{(review['last_score_ratio'] or 0) * 100:.0f}%",
                    "間隔": f"{review['interval_days']}日",
                    "ステータス": "要復習" if review["due_at"] <= datetime.utcnow() else "予定",
                }
                for review in upcoming_reviews
            ]
        )
        st.data_editor(
            schedule_df,
            hide_index=True,
            use_container_width=True,
            disabled=True,
        )
        st.caption("演習結果に応じて次回の復習タイミングを自動で提案します。")
    else:
        st.info("演習データが蓄積されると復習スケジュールがここに表示されます。")

    overview_tab, chart_tab = st.tabs(["進捗サマリ", "事例別分析"])

    with overview_tab:
        if attempts:
            summary_df = pd.DataFrame(
                [
                    {
                        "実施日": row["submitted_at"].strftime("%Y-%m-%d")
                        if isinstance(row["submitted_at"], datetime)
                        else row["submitted_at"],
                        "年度": row["year"],
                        "事例": row["case_label"],
                        "モード": "模試" if row["mode"] == "mock" else "演習",
                        "得点": row["total_score"],
                        "満点": row["total_max_score"],
                    }
                    for row in attempts
                ]
            )
            st.markdown('<div class="table-card">', unsafe_allow_html=True)
            st.data_editor(
                summary_df,
                use_container_width=True,
                hide_index=True,
                disabled=True,
            )
            st.markdown('</div>', unsafe_allow_html=True)
            st.caption("最近の受験結果を表形式で確認できます。列ヘッダーにマウスを合わせるとソートが可能です。")
        else:
            st.info("まだ演習結果がありません。『過去問演習』から学習を開始しましょう。")

    with chart_tab:
        if stats:
            chart_data = []
            for case_label, values in stats.items():
                chart_data.append(
                    {
                        "事例": case_label,
                        "得点": values["avg_score"],
                        "満点": values["avg_max"],
                    }
                )
            df = pd.DataFrame(chart_data)
            df["達成率"] = df.apply(
                lambda row: row["得点"] / row["満点"] * 100 if row["満点"] else 0,
                axis=1,
            )
            st.subheader("事例別平均達成率")
            bar = (
                alt.Chart(df)
                .mark_bar(cornerRadiusTopRight=8, cornerRadiusBottomRight=8)
                .encode(
                    y=alt.Y("事例:N", sort="-x", title=None),
                    x=alt.X("達成率:Q", scale=alt.Scale(domain=[0, 100]), title="平均達成率 (%)"),
                    color=alt.value("#22c55e"),
                    tooltip=["事例", "得点", "満点", alt.Tooltip("達成率:Q", format=".1f")],
                )
            )
            target_line = (
                alt.Chart(pd.DataFrame({"ベンチマーク": [60]}))
                .mark_rule(color="#f97316", strokeDash=[6, 4])
                .encode(x="ベンチマーク:Q")
            )
            st.altair_chart(bar + target_line, use_container_width=True)
        else:
            st.info("演習データが蓄積すると事例別の分析が表示されます。")

    latest_attempt = attempts[0] if attempts else None
    next_focus_card = {
        "icon": "🎯",
        "title": "次に集中すべき事例",
        "value": "最初の演習を始めましょう",
        "desc": "演習を完了すると優先度が表示されます。",
    }
    if stats:
        focus_case_label = None
        focus_rate = None
        for case_label, values in stats.items():
            if not values["avg_max"]:
                continue
            ratio = values["avg_score"] / values["avg_max"] * 100
            if focus_rate is None or ratio < focus_rate:
                focus_rate = ratio
                focus_case_label = case_label
        if focus_case_label:
            next_focus_card = {
                "icon": "🎯",
                "title": "次に集中すべき事例",
                "value": focus_case_label,
                "desc": f"平均達成率 {focus_rate:.0f}%。重点復習で底上げしましょう。",
            }

    learning_time_card = {
        "icon": "⏱️",
        "title": "累計学習時間",
        "value": _format_duration_minutes(total_learning_minutes),
        "desc": "記録された演習・模試の回答時間の合計",
    }
    if total_learning_minutes == 0:
        learning_time_card["value"] = "0分"
        learning_time_card["desc"] = "初回の演習で学習時間を記録しましょう。"

    latest_result_card = {
        "icon": "📈",
        "title": "直近の結果",
        "value": "データなし",
        "desc": "演習を完了すると最新結果が表示されます。",
    }
    if latest_attempt:
        latest_score = latest_attempt["total_score"] or 0
        latest_max = latest_attempt["total_max_score"] or 0
        latest_ratio = (latest_score / latest_max * 100) if latest_max else 0
        latest_result_card = {
            "icon": "📈",
            "title": "直近の結果",
            "value": f"{latest_score:.0f} / {latest_max:.0f}点 ({latest_ratio:.0f}%)",
            "desc": f"{_format_datetime_label(latest_attempt['submitted_at'])} 実施",
        }

    insight_cards = "\n".join(
        dedent(
            f"""
            <div class="insight-card">
                <div class="insight-icon">{card['icon']}</div>
                <div>
                    <p class="insight-title">{card['title']}</p>
                    <p class="insight-value">{card['value']}</p>
                    <p class="insight-desc">{card['desc']}</p>
                </div>
            </div>
            """
        ).strip()
        for card in [next_focus_card, learning_time_card, latest_result_card]
    )
    st.markdown(
        dedent(
            f"""
            <div class="insight-grid">
            {insight_cards}
            </div>
            """
        ).strip(),
        unsafe_allow_html=True,
    )

    st.markdown(
        dedent(
            """
            ### 次のアクション
            <div class="action-grid">
                <div class="action-card">
                    <strong>過去問演習</strong>
                    <p>年度・事例を指定して弱点補強の演習を行いましょう。</p>
                </div>
                <div class="action-card">
                    <strong>模擬試験</strong>
                    <p>タイマー付きの本番形式で得点力とタイムマネジメントを鍛えます。</p>
                </div>
                <div class="action-card">
                    <strong>学習履歴</strong>
                    <p>得点推移を可視化し、改善の兆しや課題を振り返りましょう。</p>
                </div>
            </div>
            """
        ).strip(),
        unsafe_allow_html=True,
    )

    st.markdown("### 過去問タイムライン")
    st.caption("令和6年から4年にかけての事例III『生産』テーマの変遷を俯瞰できます。ホバーで原紙PDFリンクを確認できます。")
    _render_caseiii_timeline()


def _calculate_gamification(attempts: List[Dict]) -> Dict[str, object]:
    if not attempts:
        return {
            "attempts": 0,
            "current_streak": 0,
            "badges": [],
            "next_milestone": 3,
            "points": 0,
            "level": 1,
            "level_progress": 0,
            "level_threshold": 100,
            "points_to_next_level": 100,
        }

    parsed_attempts = []
    for row in attempts:
        submitted_at = row.get("submitted_at")
        if isinstance(submitted_at, datetime):
            parsed_attempts.append(submitted_at)
        elif submitted_at:
            try:
                parsed_attempts.append(datetime.fromisoformat(submitted_at))
            except ValueError:
                continue

    unique_dates = sorted({dt.date() for dt in parsed_attempts}, reverse=True)
    streak = 0
    previous_date = None
    for current in unique_dates:
        if previous_date is None:
            streak = 1
        else:
            gap = (previous_date - current).days
            if gap == 1:
                streak += 1
            elif gap > 1:
                break
        previous_date = current

    best_ratio = 0.0
    mock_clears = 0
    high_mock_scores = 0
    badges: List[Dict[str, str]] = []
    total_attempts = len(attempts)
    points = 0
    level_threshold = 100
    for row in attempts:
        total = row.get("total_score") or 0
        maximum = row.get("total_max_score") or 0
        ratio = (total / maximum) if maximum else 0
        best_ratio = max(best_ratio, ratio)
        mode = row.get("mode")
        if mode == "mock":
            points += 40
            if ratio >= 0.7:
                mock_clears += 1
            if ratio >= 0.85:
                high_mock_scores += 1
        else:
            points += 20
        if ratio >= 0.8:
            points += 10
        elif ratio >= 0.6:
            points += 5

    points += streak * 2

    if total_attempts >= 1:
        badges.append({"title": "スタートダッシュ", "description": "初めての演習を完了しました"})
    if streak >= 3:
        badges.append({"title": "連続学習3日達成", "description": "継続学習のリズムが身についています"})
    if streak >= 7:
        badges.append({"title": "週間皆勤", "description": "7日連続で学習を継続しました"})
    if mock_clears:
        badges.append({"title": "模擬試験クリア", "description": "模擬試験で70%の得点を獲得しました"})
    if best_ratio >= 0.85:
        badges.append({"title": "ハイスコア達人", "description": "高得点を獲得し自信が高まりました"})
    if total_attempts >= 10:
        badges.append({"title": "継続学習バッジ", "description": "演習を積み重ね学習の習慣化が進んでいます"})
    if high_mock_scores:
        badges.append({"title": "優秀回答者バッジ", "description": "模試で高得点を記録しました"})

    milestones = [3, 7, 15, 30]
    next_milestone = None
    for milestone in milestones:
        if total_attempts < milestone:
            next_milestone = milestone
            break

    level = points // level_threshold + 1
    level_progress = points % level_threshold
    points_to_next_level = level_threshold - level_progress if level_progress else level_threshold

    return {
        "attempts": total_attempts,
        "current_streak": streak,
        "badges": badges,
        "next_milestone": next_milestone,
        "points": points,
        "level": level,
        "level_progress": level_progress,
        "level_threshold": level_threshold,
        "points_to_next_level": points_to_next_level,
    }


def _draft_key(problem_id: int, question_id: int) -> str:
    return f"draft_{problem_id}_{question_id}"


def _compute_fullwidth_length(text: str) -> float:
    total = 0.0
    for char in text:
        width = unicodedata.east_asian_width(char)
        if width in {"F", "W", "A"}:
            total += 1.0
        elif width in {"Na", "H"}:
            total += 0.5
        else:
            total += 1.0
    return total


def _format_fullwidth_length(value: float) -> str:
    rounded = round(value, 1)
    if abs(rounded - round(rounded)) < 1e-6:
        return f"{int(round(rounded))}"
    return f"{rounded:.1f}"


def _ensure_character_meter_styles() -> None:
    if st.session_state.get("_char_meter_styles_injected"):
        return
    st.markdown(
        """
        <style>
        .char-meter-wrapper {
            margin: 0.35rem 0 0.6rem;
        }
        .char-meter-bar {
            position: relative;
            height: 10px;
            background: #e2e8f0;
            border-radius: 999px;
            overflow: hidden;
        }
        .char-meter-fill {
            height: 100%;
            background: linear-gradient(90deg, #22d3ee 0%, #6366f1 100%);
            transition: width 0.25s ease;
        }
        .char-meter-marker {
            position: absolute;
            top: 50%;
            transform: translate(-50%, -50%);
            width: 0;
            height: 14px;
        }
        .char-meter-marker span {
            position: absolute;
            top: 16px;
            left: 50%;
            transform: translateX(-50%);
            font-size: 0.7rem;
            color: #475569;
            white-space: nowrap;
        }
        .char-meter-marker::after {
            content: "";
            display: block;
            width: 2px;
            height: 14px;
            background: #94a3b8;
            border-radius: 2px;
        }
        .char-meter-wrapper[data-state="over"] .char-meter-fill {
            background: linear-gradient(90deg, #f97316 0%, #ef4444 100%);
        }
        .char-meter-wrapper[data-state="warn"] .char-meter-fill {
            background: linear-gradient(90deg, #facc15 0%, #fb923c 100%);
        }
        .char-meter-caption {
            display: flex;
            justify-content: space-between;
            font-size: 0.78rem;
            margin-top: 0.25rem;
            color: #475569;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )
    st.session_state["_char_meter_styles_injected"] = True


def _render_character_meter(current: float, limit: Optional[int]) -> None:
    _ensure_character_meter_styles()
    checkpoints = [80, 100, 120]
    gauge_max = max([limit or 0, *checkpoints, current, 1])
    fill_ratio = min(current / gauge_max, 1.0)
    if limit:
        gauge_max = max(gauge_max, limit)
    fill_width = fill_ratio * 100
    state = ""
    if limit and current > limit:
        state = "over"
    elif current >= 120:
        state = "over"
    elif current >= 100:
        state = "warn"
    meter_html = [f'<div class="char-meter-wrapper" data-state="{state}">']
    meter_html.append(
        f'<div class="char-meter-bar"><div class="char-meter-fill" style="width: {fill_width:.2f}%;"></div>'
    )
    for checkpoint in checkpoints:
        if checkpoint > gauge_max:
            continue
        position = min(max(checkpoint / gauge_max * 100, 0), 100)
        meter_html.append(
            f'<div class="char-meter-marker" style="left: {position:.2f}%;"><span>{checkpoint}字</span></div>'
        )
    if limit and limit not in checkpoints:
        position = min(max(limit / gauge_max * 100, 0), 100)
        meter_html.append(
            f'<div class="char-meter-marker" style="left: {position:.2f}%;"><span>{limit}字</span></div>'
        )
    meter_html.append("</div></div>")
    st.markdown("".join(meter_html), unsafe_allow_html=True)

    formatted_current = _format_fullwidth_length(current)
    if limit:
        caption_left = f"全角換算 {formatted_current}字"
        remaining = limit - current
        if remaining >= 0:
            caption_right = f"残り {_format_fullwidth_length(remaining)}字"
        else:
            caption_right = f"{_format_fullwidth_length(abs(remaining))}字オーバー"
    else:
        caption_left = f"全角換算 {formatted_current}字"
        caption_right = "100字=2〜3文が目安"
    st.markdown(
        f'<div class="char-meter-caption"><span>{caption_left}</span><span title="100字は2〜3文が目安です。">{caption_right}</span></div>',
        unsafe_allow_html=True,
    )


def _render_character_counter(text: str, limit: Optional[int]) -> None:
    fullwidth_length = _compute_fullwidth_length(text)
    if limit is None:
        st.caption(
            f"現在の文字数: {len(text)}字 ／ 全角換算: {_format_fullwidth_length(fullwidth_length)}字"
        )
        _render_character_meter(fullwidth_length, limit)
        if fullwidth_length >= 120:
            st.error("120字を超えています。要素を整理して因果の主軸を絞りましょう。")
        return

    remaining = limit - fullwidth_length
    if remaining >= 0:
        remaining_text = f"残り {_format_fullwidth_length(remaining)}字"
    else:
        remaining_text = f"{_format_fullwidth_length(abs(remaining))}字オーバー"
    st.caption(
        f"文字数: {_format_fullwidth_length(fullwidth_length)} / {limit}字（{remaining_text}）"
    )
    if remaining < 0:
        st.error("文字数が上限を超えています。赤字の警告に従い削減しましょう。")
    elif fullwidth_length >= 120 and limit > 120:
        st.error("120字を超えると冗長になりやすいです。重要語に絞りましょう。")

    _render_character_meter(fullwidth_length, limit)


TOKEN_PATTERN = re.compile(r"[ぁ-んァ-ヶ一-龥ａ-ｚＡ-Ｚa-zA-Z0-9]+")
SYNONYM_GROUPS = [
    {"label": "改善・向上", "words": ["改善", "改良", "向上", "高め", "高める", "強化", "底上げ"]},
    {"label": "課題・問題", "words": ["課題", "問題", "懸念", "ボトルネック", "弱み"]},
    {"label": "顧客関連", "words": ["顧客", "客層", "利用者", "来店客", "ユーザー"]},
    {"label": "売上・拡大", "words": ["売上", "収益", "増加", "拡大", "伸長"]},
]
ENUMERATION_CONNECTORS = ["ため", "ので", "こと", "結果", "よって", "そのため", "さらに", "一方"]
CAUSAL_STARTERS = ["そのため", "その結果", "結果として", "よって", "したがって", "だから", "ゆえに"]


def _inject_mece_scanner_styles() -> None:
    if st.session_state.get("_mece_scanner_styles_injected"):
        return
    st.markdown(
        """
        <style>
        .mece-scan-block {
            padding: 0.75rem 0.9rem;
            background: #f8fafc;
            border: 1px solid #e2e8f0;
            border-radius: 12px;
            font-size: 0.9rem;
            line-height: 1.8;
            white-space: pre-wrap;
        }
        .mece-highlight {
            padding: 0 2px;
            border-radius: 4px;
            transition: background 0.2s ease;
        }
        .mece-highlight.duplicate {
            background: rgba(250, 204, 21, 0.35);
        }
        .mece-highlight.synonym {
            background: rgba(248, 113, 113, 0.3);
            border-bottom: 2px solid rgba(248, 113, 113, 0.65);
        }
        .mece-highlight.enumeration {
            background: rgba(96, 165, 250, 0.25);
            box-shadow: inset 0 -2px 0 rgba(59, 130, 246, 0.55);
        }
        .mece-scan-summary {
            font-size: 0.85rem;
            color: #1e293b;
            margin-top: 0.6rem;
        }
        .mece-scan-summary ul {
            padding-left: 1.2rem;
            margin: 0.2rem 0 0.4rem;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )
    st.session_state["_mece_scanner_styles_injected"] = True


def _build_highlight_html(text: str, spans: List[Dict[str, Any]]) -> str:
    if not text:
        return "<p class='mece-scan-block'>入力された文章がここに表示されます。</p>"
    if not spans:
        escaped = html.escape(text).replace("\n", "<br />")
        return f"<div class='mece-scan-block'>{escaped}</div>"

    boundaries = sorted({0, len(text), *[span["start"] for span in spans], *[span["end"] for span in spans]})
    pieces: List[str] = []
    for index in range(len(boundaries) - 1):
        start = boundaries[index]
        end = boundaries[index + 1]
        if start == end:
            continue
        segment = text[start:end]
        active = [span for span in spans if span["start"] <= start and span["end"] >= end]
        escaped = html.escape(segment).replace("\n", "<br />")
        if not active:
            pieces.append(escaped)
            continue
        classes = " ".join(sorted({span["class"] for span in active}))
        tooltip = " / ".join(sorted({span["label"] for span in active}))
        pieces.append(
            f"<span class='mece-highlight {classes}' title='{html.escape(tooltip)}'>{escaped}</span>"
        )
    return f"<div class='mece-scan-block'>{''.join(pieces)}</div>"


def _find_duplicate_tokens(text: str) -> Tuple[List[Dict[str, Any]], List[str]]:
    occurrences: Dict[str, List[Tuple[int, int]]] = defaultdict(list)
    for match in TOKEN_PATTERN.finditer(text):
        token = match.group()
        if len(token.strip()) < 2:
            continue
        occurrences[token].append((match.start(), match.end()))

    spans: List[Dict[str, Any]] = []
    summary: List[str] = []
    for token, positions in occurrences.items():
        if len(positions) < 2:
            continue
        summary.append(f"「{token}」×{len(positions)}")
        for start, end in positions:
            spans.append(
                {"start": start, "end": end, "class": "duplicate", "label": f"重複語: {token}"}
            )
    return spans, summary


def _find_synonym_redundancies(text: str) -> Tuple[List[Dict[str, Any]], List[str]]:
    spans: List[Dict[str, Any]] = []
    summary: List[str] = []
    for group in SYNONYM_GROUPS:
        present: Dict[str, List[Tuple[int, int]]] = {}
        for word in group["words"]:
            matches = list(re.finditer(re.escape(word), text))
            if matches:
                present[word] = [(match.start(), match.end()) for match in matches]
        if len(present) < 2:
            continue
        words_used = "／".join(sorted(present.keys()))
        summary.append(f"{group['label']}（{words_used}）")
        for word, positions in present.items():
            for start, end in positions:
                spans.append(
                    {"start": start, "end": end, "class": "synonym", "label": f"同義反復: {group['label']}"}
                )
    return spans, summary


def _detect_simple_enumerations(text: str) -> Tuple[List[Dict[str, Any]], List[str]]:
    spans: List[Dict[str, Any]] = []
    summary: List[str] = []
    length = len(text)
    index = 0
    while index < length:
        end = index
        while end < length and text[end] not in "。！？":
            end += 1
        if end < length:
            end += 1
        sentence = text[index:end]
        index = end
        stripped = sentence.strip()
        if not stripped:
            continue
        segments = [seg for seg in re.split(r"[、,]", stripped) if seg.strip()]
        if len(segments) < 3:
            continue
        if any(connector in stripped for connector in ENUMERATION_CONNECTORS):
            continue
        spans.append(
            {
                "start": index - len(sentence),
                "end": index,
                "class": "enumeration",
                "label": "単純列挙",
            }
        )
        summary.append(stripped[:30] + ("…" if len(stripped) > 30 else ""))
    return spans, summary


def _suggest_causal_bridges(text: str) -> List[str]:
    sentences: List[str] = []
    length = len(text)
    index = 0
    while index < length:
        end = index
        while end < length and text[end] not in "。！？":
            end += 1
        if end < length:
            end += 1
        sentence = text[index:end].strip()
        index = end
        if sentence:
            sentences.append(sentence)

    suggestions: List[str] = []
    if len(sentences) < 2:
        return suggestions

    for i in range(len(sentences) - 1):
        current_sentence = sentences[i]
        next_sentence = sentences[i + 1]
        if any(starter in next_sentence for starter in CAUSAL_STARTERS):
            continue
        if any(connector in current_sentence for connector in ENUMERATION_CONNECTORS):
            continue
        head_current = current_sentence[:12] + ("…" if len(current_sentence) > 12 else "")
        head_next = next_sentence[:12] + ("…" if len(next_sentence) > 12 else "")
        suggestions.append(
            f"「{head_current}」→「{head_next}」の間に『その結果』『だから』などの接続詞で因果を明示しましょう。"
        )
    if not suggestions and not any(starter in sentence for sentence in sentences for starter in CAUSAL_STARTERS):
        suggestions.append("因→果の接続詞（その結果／だから等）を入れると論理の流れが明確になります。")
    return suggestions


def _analyze_mece_causal(text: str) -> Dict[str, Any]:
    duplicate_spans, duplicate_summary = _find_duplicate_tokens(text)
    synonym_spans, synonym_summary = _find_synonym_redundancies(text)
    enumeration_spans, enumeration_summary = _detect_simple_enumerations(text)

    all_spans = duplicate_spans + synonym_spans + enumeration_spans
    combined_spans: List[Dict[str, Any]] = []
    seen = set()
    for span in all_spans:
        key = (span["start"], span["end"], span["class"], span["label"])
        if key in seen:
            continue
        seen.add(key)
        combined_spans.append(span)

    return {
        "spans": combined_spans,
        "duplicates": duplicate_summary,
        "synonyms": synonym_summary,
        "enumerations": enumeration_summary,
        "suggestions": _suggest_causal_bridges(text),
    }


def _render_mece_causal_scanner(text: str) -> None:
    _inject_mece_scanner_styles()
    st.caption("MECE/因果スキャナ：重複語・列挙・接続詞不足を自動チェックします。")
    if not text.strip():
        st.info("文章を入力するとハイライト結果と因果接続の提案が表示されます。")
        return

    analysis = _analyze_mece_causal(text)
    st.markdown(_build_highlight_html(text, analysis["spans"]), unsafe_allow_html=True)

    summary_blocks: List[str] = []
    if analysis["duplicates"]:
        summary_blocks.append(
            f"<p><strong>重複語</strong>: {'、'.join(html.escape(item) for item in analysis['duplicates'])}</p>"
        )
    if analysis["synonyms"]:
        summary_blocks.append(
            f"<p><strong>同義反復</strong>: {'、'.join(html.escape(item) for item in analysis['synonyms'])}</p>"
        )
    if analysis["enumerations"]:
        items = "".join(f"<li>{html.escape(item)}</li>" for item in analysis["enumerations"])
        summary_blocks.append(
            f"<div><strong>単純列挙の疑い</strong><ul>{items}</ul></div>"
        )

    if summary_blocks:
        st.markdown(
            "<div class='mece-scan-summary'>" + "".join(summary_blocks) + "</div>",
            unsafe_allow_html=True,
        )

    for suggestion in analysis["suggestions"]:
        st.warning(suggestion)


def _question_input(
    problem_id: int,
    question: Dict,
    *,
    disabled: bool = False,
    widget_prefix: str = "textarea_",
    case_label: Optional[str] = None,
) -> str:
    key = _draft_key(problem_id, question["id"])
    if key not in st.session_state.drafts:
        saved_default = st.session_state.saved_answers.get(key, "")
        st.session_state.drafts[key] = saved_default

    textarea_state_key = f"{widget_prefix}{key}"

    question_overview = dict(question)
    question_overview.setdefault("order", question.get("order"))
    question_overview.setdefault("case_label", case_label)
    _render_question_overview_card(question_overview, case_label=case_label)
    _render_intent_cards(question, key, textarea_state_key)
    _render_case_frame_shortcuts(case_label, key, textarea_state_key)

    context_candidates = [
        question.get("context"),
        question.get("context_text"),
        question.get("context_snippet"),
        question.get("与件文全体"),
        question.get("与件文"),
        question.get("与件"),
        question.get("context_passages"),
    ]
    for candidate in context_candidates:
        normalized_context = _normalize_text_block(candidate)
        if normalized_context:
            _render_question_context_block(normalized_context)
            break

    question_body = _normalize_text_block(
        _select_first(
            question,
            ["設問文", "問題文", "question_text", "body"],
        )
    )
    if question_body:
        st.markdown("**設問文**")
        st.write(question_body)

    if case_label == "事例IV":
        _render_case_iv_bridge(key)

    notice = st.session_state.get("_intent_card_notice")
    if notice and notice.get("draft_key") == key:
        st.success(f"「{notice['label']}」の例示表現を挿入しました。", icon="✍️")
        st.session_state.pop("_intent_card_notice", None)

    frame_notice = st.session_state.get("_case_frame_notice")
    if frame_notice and frame_notice.get("draft_key") == key:
        st.success(f"「{frame_notice['label']}」フレームを挿入しました。", icon="🧩")
        st.session_state.pop("_case_frame_notice", None)

    value = st.session_state.drafts.get(key, "")
    help_text = f"文字数目安: {question['character_limit']}字" if question["character_limit"] else ""
    st.caption("入力内容は自動保存されます。")
    text = st.text_area(
        label=question["prompt"],
        key=textarea_state_key,
        value=value,
        height=160,
        help=help_text,
        disabled=disabled,
    )
    _render_character_counter(text, question.get("character_limit"))
    with st.expander("MECE/因果スキャナ", expanded=bool(text.strip())):
        _render_mece_causal_scanner(text)
    st.session_state.drafts[key] = text
    st.session_state.saved_answers.setdefault(key, value)
    status_placeholder = st.empty()
    saved_text = st.session_state.saved_answers.get(key)
    restore_disabled = not saved_text
    if restore_disabled:
        status_placeholder.caption("復元できる下書きはまだありません。")
    if st.button(
        "下書きを復元",
        key=f"restore_{key}",
        disabled=restore_disabled,
    ):
        st.session_state.drafts[key] = saved_text
        st.session_state[textarea_state_key] = saved_text
        status_placeholder.info("保存済みの下書きを復元しました。")
    return text


def _reset_flashcard_state(problem_id: int, size: int) -> Dict[str, Any]:
    order = list(range(size))
    random.shuffle(order)
    state = {"order": order, "index": 0, "revealed": False, "size": size}
    st.session_state.flashcard_states[str(problem_id)] = state
    result_prefix = f"flashcard_result::{problem_id}::"
    for key in [key for key in st.session_state.keys() if key.startswith(result_prefix)]:
        st.session_state.pop(key, None)
    return state


def _get_flashcard_state(problem_id: int, size: int) -> Dict[str, Any]:
    key = str(problem_id)
    state = st.session_state.flashcard_states.get(key)
    if not state or state.get("size") != size:
        state = _reset_flashcard_state(problem_id, size)
    return state


def _normalize_keyword_for_matching(text: str) -> str:
    normalized = unicodedata.normalize("NFKC", str(text or "").strip())
    normalized = re.sub(r"[\s\u3000]+", "", normalized)
    normalized = normalized.replace("・", "")
    return normalized


def _evaluate_flashcard_guess(
    problem_id: int, card_index: int, keywords: Iterable[str], guess_text: str
) -> Dict[str, Any]:
    keyword_pairs: List[Tuple[str, str]] = []
    for keyword in keywords:
        normalized = _normalize_keyword_for_matching(keyword)
        if not normalized:
            continue
        keyword_pairs.append((keyword, normalized))

    raw_entries = [part.strip() for part in re.split(r"[\n,、/]+", guess_text or "") if part.strip()]
    entry_pairs: List[Tuple[str, str]] = []
    seen_entries: Set[str] = set()
    for entry in raw_entries:
        normalized = _normalize_keyword_for_matching(entry)
        if not normalized or normalized in seen_entries:
            continue
        seen_entries.add(normalized)
        entry_pairs.append((entry, normalized))

    remaining_indices: List[int] = list(range(len(keyword_pairs)))
    matched_keywords: List[str] = []
    extra_inputs: List[str] = []

    for entry, normalized in entry_pairs:
        matched_index: Optional[int] = None
        for idx in remaining_indices:
            if keyword_pairs[idx][1] == normalized:
                matched_index = idx
                break
        if matched_index is None:
            extra_inputs.append(entry)
            continue
        matched_keywords.append(keyword_pairs[matched_index][0])
        remaining_indices.remove(matched_index)

    missed_keywords = [keyword_pairs[idx][0] for idx in remaining_indices]

    matched_count = len(matched_keywords)
    total_keywords = len(keyword_pairs)
    accuracy = matched_count / total_keywords if total_keywords else 0.0

    progress_root = st.session_state.setdefault("flashcard_progress", {})
    problem_progress = progress_root.setdefault(str(problem_id), {})
    card_key = str(card_index)
    entry = problem_progress.setdefault(
        card_key,
        {
            "attempts": 0,
            "keyword_count": total_keywords,
            "best_accuracy": 0.0,
            "last_correct": 0,
            "last_accuracy": 0.0,
        },
    )
    entry["attempts"] += 1
    entry["keyword_count"] = total_keywords
    prev_best = float(entry.get("best_accuracy", 0.0))
    improved = accuracy > prev_best + 1e-6
    entry["best_accuracy"] = max(prev_best, accuracy)
    entry["last_correct"] = matched_count
    entry["last_accuracy"] = accuracy
    entry["last_attempted_at"] = datetime.now().isoformat()
    entry["last_improved"] = improved

    return {
        "matched": matched_keywords,
        "missed": missed_keywords,
        "extras": extra_inputs,
        "matched_count": matched_count,
        "total_keywords": total_keywords,
        "accuracy": accuracy,
        "improved": improved,
        "attempts": entry["attempts"],
    }


def _render_retrieval_flashcards(problem: Dict) -> None:
    flashcards: List[Dict[str, Any]] = []
    for index, question in enumerate(problem.get("questions", [])):
        keywords = [kw for kw in question.get("keywords", []) if kw]
        if not keywords:
            continue
        flashcards.append(
            {
                "title": f"設問{index + 1}: キーワード想起クイズ",
                "prompt": question.get("prompt", ""),
                "keywords": keywords,
            }
        )

    if not flashcards:
        st.info("この問題ではキーワードが登録されていないため、フラッシュカードを生成できません。")
        return

    st.subheader("リトリーバル・プラクティス")
    st.caption(
        "回答作成の前に、設問の重要キーワードを記憶から呼び起こしましょう。"
        " 思い出しの練習（retrieval practice）は再読よりも記憶定着を高めるとされています。"
    )

    st.session_state.setdefault("flashcard_progress", {})
    problem_progress = st.session_state.flashcard_progress.setdefault(str(problem["id"]), {})

    progress_container = st.container()

    state = _get_flashcard_state(problem["id"], len(flashcards))

    completed_entries = [entry for entry in problem_progress.values() if entry.get("attempts", 0) > 0]
    with progress_container:
        if completed_entries:
            total_keywords = sum(entry.get("keyword_count", 0) for entry in completed_entries)
            total_recalled = sum(entry.get("last_correct", 0) for entry in completed_entries)
            st.markdown("**想起状況サマリー**")
            if total_keywords > 0:
                overall_accuracy = total_recalled / total_keywords
                st.progress(overall_accuracy)
                st.caption(f"想起できたキーワード: {total_recalled} / {total_keywords}")
            else:
                st.caption("採点結果を記録するには、キーワードを入力して答え合わせを行いましょう。")
            improvements = sum(1 for entry in completed_entries if entry.get("last_improved"))
            if improvements:
                st.success(f"前回より想起率が向上したカードが {improvements} 枚あります。", icon="🚀")
            latest_iso = max(
                (entry.get("last_attempted_at") for entry in completed_entries if entry.get("last_attempted_at")),
                default=None,
            )
            if latest_iso:
                try:
                    latest_dt = datetime.fromisoformat(str(latest_iso))
                    st.caption(f"最終トレーニング: {latest_dt.strftime('%Y/%m/%d %H:%M')}")
                except ValueError:
                    pass
        else:
            st.caption("カードごとにキーワードを書き出して想起力を測定しましょう。")

    card_placeholder = st.container()
    button_placeholder = st.container()

    with button_placeholder:
        col_reveal, _, col_next, _, col_shuffle = st.columns([1, 0.1, 1, 0.1, 1])
        reveal_clicked = col_reveal.button("キーワードを表示", key=f"flashcard_reveal_{problem['id']}")
        next_clicked = col_next.button("次のカードへ", key=f"flashcard_next_{problem['id']}")
        shuffle_clicked = col_shuffle.button("カードを再シャッフル", key=f"flashcard_shuffle_{problem['id']}")

    if shuffle_clicked:
        state = _reset_flashcard_state(problem["id"], len(flashcards))
    else:
        if next_clicked:
            state["index"] = (state["index"] + 1) % len(state["order"])
            state["revealed"] = False
        if reveal_clicked:
            state["revealed"] = True

    st.session_state.flashcard_states[str(problem["id"])] = state

    order = state["order"]
    current_position = state["index"]
    card = flashcards[order[current_position]]

    card_index = order[current_position]
    result_state_key = f"flashcard_result::{problem['id']}::{card_index}"
    guess_state_key = f"flashcard_guess::{problem['id']}::{card_index}"

    with card_placeholder:
        st.markdown(f"**カード {current_position + 1} / {len(flashcards)}**")
        st.write(card["title"])
        card_html = f"""
        <div style='padding:0.75rem 1rem;border:1px solid #CBD5E1;border-radius:0.75rem;background-color:#F8FAFC;'>
            <p style='margin:0;color:#1E293B;font-weight:600;'>設問の概要</p>
            <p style='margin:0.35rem 0 0;color:#334155;'>{card['prompt']}</p>
            <p style='margin:0.75rem 0 0;color:#64748B;'>キーワードを声に出すか、メモに書き出してみてください。</p>
        </div>
        """
        st.markdown(card_html, unsafe_allow_html=True)

        guess_text = st.text_area(
            "思い出したキーワードを箇条書きで入力",
            key=guess_state_key,
            height=120,
            placeholder="例: SWOT分析\nブランド認知向上\n外注管理",
            help="Enterキーで改行し、思い出した単語を一行ずつ入力してください。",
        )
        st.caption("答えを見る前に、自分の言葉でキーワードを書き出してみましょう。")

        evaluation = st.session_state.get(result_state_key)
        if reveal_clicked:
            evaluation = _evaluate_flashcard_guess(
                problem["id"], card_index, card["keywords"], guess_text
            )
            st.session_state[result_state_key] = evaluation

        if state["revealed"]:
            st.success("\n".join(f"・{keyword}" for keyword in card["keywords"]), icon="✅")
            if evaluation is None:
                evaluation = st.session_state.get(result_state_key)
            if evaluation:
                st.markdown("**自己採点結果**")
                st.progress(evaluation["accuracy"])
                st.caption(
                    f"想起できたキーワード: {evaluation['matched_count']} / {evaluation['total_keywords']}"
                )
                if evaluation.get("improved") and evaluation.get("attempts", 0) > 1:
                    st.success("前回より正答率がアップしました！", icon="🎉")
                if evaluation.get("matched"):
                    st.success(
                        "\n".join(f"・{keyword}" for keyword in evaluation["matched"]),
                        icon="🧠",
                    )
                if evaluation.get("missed"):
                    st.warning(
                        "思い出せなかったキーワード:\n" + "\n".join(f"・{kw}" for kw in evaluation["missed"]),
                        icon="🔁",
                    )
                if evaluation.get("extras"):
                    st.info(
                        "リストにない入力:\n" + "\n".join(f"・{item}" for item in evaluation["extras"]),
                        icon="✍️",
                    )
        else:
            st.info("キーワードを思い出したら、上のボタンから答え合わせをしましょう。")




def _compute_learning_stats(history_df: pd.DataFrame) -> Dict[str, Any]:
    stats: Dict[str, Any] = {"total_sessions": int(len(history_df))}
    if history_df.empty:
        now = datetime.now()
        stats.update(
            {
                "recent_average": None,
                "best_score": None,
                "streak_days": 0,
                "last_study_at": None,
                "recommended_interval": 3,
                "next_study_at": now + timedelta(days=3),
                "reference_datetime": now,
            }
        )
        return stats

    sorted_dates = history_df.dropna(subset=["日付"]).sort_values("日付")["日付"]
    python_dates = [
        value.to_pydatetime() if hasattr(value, "to_pydatetime") else value for value in sorted_dates
    ]
    last_study_at = python_dates[-1]

    intervals = sorted_dates.diff().dropna()
    intervals_days = intervals.dt.total_seconds() / (60 * 60 * 24)
    intervals_days = intervals_days[intervals_days > 0]
    recommended_interval = int(round(intervals_days.median())) if not intervals_days.empty else 3
    recommended_interval = max(1, recommended_interval)
    next_study_at = last_study_at + timedelta(days=recommended_interval)

    unique_days = sorted({value.date() for value in python_dates})
    streak = 0
    previous_day: Optional[dt_date] = None
    for day in reversed(unique_days):
        if previous_day is None:
            streak = 1
        else:
            if (previous_day - day).days == 1:
                streak += 1
            else:
                break
        previous_day = day

    recent_scores = history_df["得点"].dropna().tail(5)
    recent_average = float(recent_scores.mean()) if not recent_scores.empty else None
    best_score = float(history_df["得点"].dropna().max()) if history_df["得点"].notna().any() else None

    stats.update(
        {
            "recent_average": recent_average,
            "best_score": best_score,
            "streak_days": streak,
            "last_study_at": last_study_at,
            "recommended_interval": recommended_interval,
            "next_study_at": next_study_at,
            "reference_datetime": last_study_at,
        }
    )
    return stats


def _calculate_level(total_experience: float) -> Dict[str, float]:
    level = 1
    xp_needed = 200.0
    xp_floor = 0.0
    xp_remaining = float(total_experience)

    while xp_remaining >= xp_needed:
        xp_remaining -= xp_needed
        xp_floor += xp_needed
        level += 1
        xp_needed = 200.0 + (level - 1) * 120.0

    progress_ratio = 0.0
    if xp_needed > 0:
        progress_ratio = max(0.0, min(1.0, xp_remaining / xp_needed))

    return {
        "level": level,
        "total_experience": total_experience,
        "current_level_floor": xp_floor,
        "next_level_cap": xp_floor + xp_needed,
        "xp_into_level": xp_remaining,
        "xp_to_next_level": max(xp_needed - xp_remaining, 0.0),
        "next_level_requirement": xp_needed,
        "progress_ratio": progress_ratio,
    }


def _compute_progress_overview(history_df: pd.DataFrame) -> Dict[str, Any]:
    signature = _problem_data_signature()
    problems = _load_problem_index(signature)
    total_pairs = {
        (row["year"], row["case_label"])
        for row in problems
        if row["year"] and row["case_label"]
    }

    year_totals: Dict[str, set] = defaultdict(set)
    case_totals: Dict[str, set] = defaultdict(set)
    for row in problems:
        year = row["year"]
        case_label = row["case_label"]
        if not year or not case_label:
            continue
        year_totals[year].add(case_label)
        case_totals[case_label].add(year)

    completed_pairs: set = set()
    pair_bonus_awarded: set = set()
    total_experience = 0.0

    if not history_df.empty:
        for _, record in history_df.iterrows():
            score = record.get("得点")
            max_score = record.get("満点")
            mode_label = record.get("モード")
            year = record.get("年度")
            case_label = record.get("事例")

            base_xp = 120.0 if mode_label == "模試" else 100.0
            ratio = 0.0
            if pd.notna(score) and pd.notna(max_score) and max_score:
                try:
                    ratio = max(0.0, min(1.0, float(score) / float(max_score)))
                except (TypeError, ZeroDivisionError):
                    ratio = 0.0
            total_experience += base_xp + ratio * 100.0

            if isinstance(year, str) and isinstance(case_label, str):
                pair = (year, case_label)
                if pair in total_pairs:
                    completed_pairs.add(pair)
                    if pair not in pair_bonus_awarded:
                        total_experience += 40.0
                        pair_bonus_awarded.add(pair)

    year_progress = []
    for year in sorted(year_totals.keys(), reverse=True):
        total_count = len(year_totals[year])
        completed_count = len({case for (y, case) in completed_pairs if y == year})
        ratio = completed_count / total_count if total_count else 0.0
        year_progress.append(
            {
                "label": year,
                "completed": completed_count,
                "total": total_count,
                "ratio": max(0.0, min(1.0, ratio)),
            }
        )

    case_progress = []
    for case_label in sorted(case_totals.keys()):
        total_count = len(case_totals[case_label])
        completed_count = len({y for (y, c) in completed_pairs if c == case_label})
        ratio = completed_count / total_count if total_count else 0.0
        case_progress.append(
            {
                "label": case_label,
                "completed": completed_count,
                "total": total_count,
                "ratio": max(0.0, min(1.0, ratio)),
            }
        )

    overall_total = len(total_pairs)
    overall_completed = len(completed_pairs)
    overall_ratio = overall_completed / overall_total if overall_total else 0.0

    level_info = _calculate_level(total_experience)

    return {
        "experience": total_experience,
        "level": level_info,
        "years": year_progress,
        "cases": case_progress,
        "overall": {
            "completed": overall_completed,
            "total": overall_total,
            "ratio": max(0.0, min(1.0, overall_ratio)),
        },
    }


def _safe_time_from_string(value: Optional[str]) -> dt_time:
    if not value:
        return dt_time(hour=20, minute=0)
    try:
        hour, minute = value.split(":")[:2]
        return dt_time(hour=int(hour), minute=int(minute))
    except Exception:
        return dt_time(hour=20, minute=0)


def _parse_iso_datetime(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _calculate_next_reminder(reference: datetime, interval_days: int, reminder_time: dt_time) -> datetime:
    interval_days = max(1, interval_days)
    minimum_dt = reference + timedelta(days=interval_days)
    candidate = datetime.combine(minimum_dt.date(), reminder_time)
    if candidate < minimum_dt:
        candidate += timedelta(days=1)

    now = datetime.now()
    if candidate <= now:
        delta = now - candidate
        periods = int(delta.total_seconds() // (interval_days * 24 * 60 * 60)) + 1
        candidate += timedelta(days=interval_days * periods)

    return candidate


def _build_schedule_preview(
    reference: datetime,
    interval_days: int,
    reminder_time: dt_time,
    channels: List[str],
    *,
    first_event: Optional[datetime] = None,
    count: int = 3,
) -> pd.DataFrame:
    interval_days = max(1, interval_days)
    first_event_dt = first_event or _calculate_next_reminder(reference, interval_days, reminder_time)
    events = []
    current = first_event_dt
    for idx in range(count):
        events.append(
            {
                "回次": f"#{idx + 1}",
                "通知予定": current.strftime("%Y-%m-%d %H:%M"),
                "チャネル": "、".join(channels) if channels else "未設定",
            }
        )
        current += timedelta(days=interval_days)

    return pd.DataFrame(events)


def _mode_label(mode: str) -> str:
    return "模試" if mode == "mock" else "演習"


def _analyze_keyword_records(records: List[Dict]) -> Dict[str, Any]:
    if not records:
        return {
            "answers": pd.DataFrame(),
            "summary": pd.DataFrame(),
            "recommendations": [],
        }

    answer_rows: List[Dict[str, Any]] = []
    keyword_stats: Dict[str, Dict[str, Any]] = {}

    for record in records:
        keyword_hits: Dict[str, bool] = record.get("keyword_hits") or {}
        total_keywords = len(keyword_hits)
        if total_keywords == 0:
            coverage_ratio = None
        else:
            coverage_ratio = sum(1 for hit in keyword_hits.values() if hit) / total_keywords
        score_ratio = None
        if record.get("max_score"):
            try:
                score_ratio = (record.get("score") or 0) / record["max_score"]
            except ZeroDivisionError:
                score_ratio = None

        matched_keywords = [kw for kw, hit in keyword_hits.items() if hit]
        missing_keywords = [kw for kw, hit in keyword_hits.items() if not hit]

        answer_rows.append(
            {
                "attempt_id": record["attempt_id"],
                "年度": record["year"],
                "事例": record["case_label"],
                "タイトル": record["title"],
                "設問": record["prompt"],
                "回答日時": record["submitted_at"],
                "キーワード網羅率": coverage_ratio * 100 if coverage_ratio is not None else None,
                "得点率": score_ratio * 100 if score_ratio is not None else None,
                "含まれたキーワード": matched_keywords,
                "不足キーワード": missing_keywords,
                "モード": _mode_label(record.get("mode", "practice")),
            }
        )

        for keyword, hit in keyword_hits.items():
            stat = keyword_stats.setdefault(
                keyword,
                {
                    "attempts": 0,
                    "hits": 0,
                    "cases": set(),
                    "years": set(),
                    "examples": [],
                },
            )
            stat["attempts"] += 1
            if hit:
                stat["hits"] += 1
            stat["cases"].add(record["case_label"])
            stat["years"].add(record["year"])
            if len(stat["examples"]) < 3:
                stat["examples"].append(
                    {
                        "year": record["year"],
                        "case_label": record["case_label"],
                        "title": record["title"],
                        "prompt": record["prompt"],
                        "hit": hit,
                    }
                )

    answers_df = pd.DataFrame(answer_rows)
    if not answers_df.empty:
        answers_df["回答日時"] = pd.to_datetime(answers_df["回答日時"], errors="coerce")
        answers_df["不足キーワード表示"] = answers_df["不足キーワード"].apply(
            lambda keywords: "、".join(keywords) if keywords else "-"
        )
        answers_df["含まれたキーワード表示"] = answers_df["含まれたキーワード"].apply(
            lambda keywords: "、".join(keywords) if keywords else "-"
        )

    summary_rows: List[Dict[str, Any]] = []
    recommendations: List[Dict[str, Any]] = []

    for keyword, stat in keyword_stats.items():
        attempts = stat["attempts"]
        hits = stat["hits"]
        hit_rate = hits / attempts if attempts else 0.0
        summary_rows.append(
            {
                "キーワード": keyword,
                "出題数": attempts,
                "達成率(%)": hit_rate * 100,
                "主な事例": "、".join(sorted(stat["cases"])) if stat["cases"] else "-",
                "出題年度": "、".join(sorted(stat["years"])) if stat["years"] else "-",
            }
        )

        if attempts >= 1 and hit_rate < 0.6:
            example_entry = next((ex for ex in stat["examples"] if not ex["hit"]), None)
            if example_entry is None and stat["examples"]:
                example_entry = stat["examples"][0]
            example_text = None
            if example_entry:
                example_text = (
                    f"{example_entry['year']} {example_entry['case_label']}『{example_entry['title']}』"
                )
            recommendations.append(
                {
                    "keyword": keyword,
                    "hit_rate": hit_rate,
                    "attempts": attempts,
                    "example": example_text,
                }
            )

    summary_df = pd.DataFrame(summary_rows)
    if not summary_df.empty:
        summary_df.sort_values(["出題数", "達成率(%)"], ascending=[False, False], inplace=True)

    recommendations.sort(key=lambda item: (item["hit_rate"], -item["attempts"]))

    return {
        "answers": answers_df,
        "summary": summary_df,
        "recommendations": recommendations,
    }


def _apply_uploaded_text_overrides(problem: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if not problem:
        return problem

    contexts = st.session_state.get("uploaded_case_contexts", {}) or {}
    question_texts = st.session_state.get("uploaded_question_texts", {}) or {}
    uploaded_case_metadata = st.session_state.get("uploaded_case_metadata", {}) or {}
    uploaded_question_metadata = (
        st.session_state.get("uploaded_question_metadata", {}) or {}
    )
    if not contexts and not question_texts:
        if not uploaded_case_metadata and not uploaded_question_metadata:
            return problem

    cloned = copy.deepcopy(problem)
    raw_year_label = _normalize_text_block(cloned.get("year") or cloned.get("年度")) or ""
    year_label = _format_reiwa_label(str(raw_year_label)) if raw_year_label else ""
    case_label_raw = cloned.get("case_label") or cloned.get("case")
    case_label = _normalize_case_label(_normalize_text_block(case_label_raw)) if case_label_raw else None
    if case_label:
        cloned["case_label"] = case_label

    case_key = _compose_case_key(year_label, case_label) if year_label and case_label else None
    if year_label and case_label:
        context_text = contexts.get(case_key) if case_key else None
        if not context_text:
            context_text = (uploaded_case_metadata.get(case_key, {}) or {}).get("context")
        normalized_context = _normalize_text_block(context_text)
        if normalized_context:
            cloned["context"] = normalized_context
            cloned["与件文"] = normalized_context
            cloned["与件文全体"] = normalized_context
    if case_key:
        case_meta = uploaded_case_metadata.get(case_key, {})
        if case_meta.get("title"):
            cloned["title"] = case_meta["title"]
        if case_meta.get("overview"):
            cloned["overview"] = case_meta["overview"]

    questions: List[Dict[str, Any]] = []
    for question in cloned.get("questions", []):
        q = dict(question)
        if year_label and case_label and question_texts:
            normalized_number = _normalize_question_number(
                q.get("order") or q.get("question_order") or q.get("設問番号")
            )
            if normalized_number is None and q.get("order") is not None:
                try:
                    normalized_number = int(q.get("order"))
                except (TypeError, ValueError):
                    normalized_number = None
            if normalized_number is not None:
                key = _compose_slot_key(year_label, case_label, int(normalized_number))
                question_entry = question_texts.get(key)
                if isinstance(question_entry, dict):
                    question_text = question_entry.get("question_text") or question_entry.get(
                        "設問文"
                    )
                    aim_override = _normalize_text_block(
                        question_entry.get("question_aim")
                        or question_entry.get("設問の狙い")
                    )
                    output_override = _normalize_text_block(
                        question_entry.get("output_format")
                        or question_entry.get("必要アウトプット形式")
                    )
                    solution_override = _normalize_text_block(
                        question_entry.get("solution_prompt")
                        or question_entry.get("定番解法プロンプト")
                    )
                    insight_override = _normalize_text_block(
                        question_entry.get("question_insight")
                        or question_entry.get("設問インサイト")
                    )
                else:
                    question_text = question_entry
                    aim_override = None
                    output_override = None
                    solution_override = None
                    insight_override = None

                normalized_text = _normalize_text_block(question_text)
                if normalized_text:
                    q["設問文"] = normalized_text
                    lines = [line.strip() for line in normalized_text.splitlines() if line.strip()]
                    first_line = lines[0] if lines else normalized_text.strip()
                    q["prompt"] = first_line or normalized_text
                if insight_override:
                    q["uploaded_question_insight"] = insight_override
                if aim_override:
                    q["uploaded_question_aim"] = aim_override
                if output_override:
                    q["uploaded_output_format"] = output_override
                if solution_override:
                    q["uploaded_solution_prompt"] = solution_override
                metadata = uploaded_question_metadata.get(key)
                if metadata:
                    prompt_override = metadata.get("prompt")
                    if prompt_override:
                        q["prompt"] = prompt_override
                    metadata_question_text = _normalize_text_block(
                        metadata.get("question_text")
                    )
                    if metadata_question_text:
                        q["設問文"] = metadata_question_text
                    if metadata.get("character_limit") is not None:
                        q["character_limit"] = metadata.get("character_limit")
                    metadata_aim = _normalize_text_block(metadata.get("question_aim"))
                    if metadata_aim:
                        q["uploaded_question_aim"] = metadata_aim
                    metadata_insight = _normalize_text_block(
                        metadata.get("question_insight")
                        or metadata.get("insight")
                    )
                    if metadata_insight:
                        q["uploaded_question_insight"] = metadata_insight
                    metadata_output = _normalize_text_block(
                        metadata.get("output_format")
                    )
                    if metadata_output:
                        q["uploaded_output_format"] = metadata_output
                    metadata_solution = _normalize_text_block(
                        metadata.get("solution_prompt")
                    )
                    if metadata_solution:
                        q["uploaded_solution_prompt"] = metadata_solution
                    if metadata.get("max_score") is not None:
                        q["max_score"] = metadata.get("max_score")
                    if metadata.get("model_answer"):
                        q["model_answer"] = metadata.get("model_answer")
                    if metadata.get("explanation"):
                        q["explanation"] = metadata.get("explanation")
                    if metadata.get("detailed_explanation"):
                        q["detailed_explanation"] = metadata.get("detailed_explanation")
                    if metadata.get("keywords"):
                        q["keywords"] = metadata.get("keywords")
                    if metadata.get("video_url"):
                        q["video_url"] = metadata.get("video_url")
                    if metadata.get("diagram_path"):
                        q["diagram_path"] = metadata.get("diagram_path")
                    if metadata.get("diagram_caption"):
                        q["diagram_caption"] = metadata.get("diagram_caption")
        questions.append(q)

    if questions:
        cloned["questions"] = questions

    return cloned


def practice_page(user: Dict) -> None:
    st.title("過去問演習")
    st.caption("年度と事例を選択して記述式演習を行います。与件ハイライトと詳細解説で復習効果を高めましょう。")

    st.info(
        "左側のセレクターで年度・事例を切り替え、下部の解答欄から回答を入力してください。与件ハイライトを読み込みながら構成を練りましょう。"
    )

    due_reviews = database.list_due_reviews(user["id"], limit=3)
    if due_reviews:
        st.warning(
            "本日復習推奨の事例があります。該当の年度・事例を選択して復習しましょう。",
            icon="⏰",
        )
        for review in due_reviews:
            ratio = review["last_score_ratio"] or 0
            st.markdown(
                f"- **{review['year']} {review['case_label']}** {review['title']}"
                f" — 前回達成度 {ratio * 100:.0f}% / 推奨間隔 {review['interval_days']}日"
            )

    st.markdown(
        dedent(
            """
            <style>
            .practice-quick-nav {
                display: flex;
                gap: 0.75rem;
                flex-wrap: wrap;
                margin-bottom: 0.5rem;
            }
            .practice-quick-nav a {
                text-decoration: none;
            }
            .practice-quick-nav a button {
                padding: 0.45rem 1.2rem;
                border-radius: 0.5rem;
                border: none;
                background-color: #2563eb;
                color: white;
                font-weight: 600;
                cursor: pointer;
            }
            .practice-quick-nav a button:hover {
                background-color: #1d4ed8;
            }
            </style>
            """
        ).strip(),
        unsafe_allow_html=True,
    )

    past_data_df = st.session_state.get("past_data")
    signature = _problem_data_signature()
    index = _load_problem_index(signature)

    has_uploaded_data = past_data_df is not None and hasattr(past_data_df, "empty") and not past_data_df.empty
    has_database_data = bool(index)

    source_labels = {
        "database": "データベース登録問題",
        "uploaded": "アップロードデータ",
    }
    available_sources: List[str] = []
    if has_database_data:
        available_sources.append("database")
    if has_uploaded_data:
        available_sources.append("uploaded")

    if not available_sources:
        st.warning(
            "問題データが登録されていません。seed_problems.jsonを確認するか、設定ページから過去問データをアップロードしてください。"
        )
        return

    data_source_key = "practice_data_source"
    default_source = st.session_state.get(data_source_key)
    if default_source not in available_sources:
        if has_uploaded_data and not has_database_data:
            default_source = "uploaded"
        else:
            default_source = available_sources[0]
        st.session_state[data_source_key] = default_source

    if len(available_sources) > 1:
        data_source = st.radio(
            "利用する出題データ",
            options=available_sources,
            format_func=lambda key: source_labels[key],
            key=data_source_key,
        )
    else:
        data_source = available_sources[0]
        st.session_state[data_source_key] = data_source
        st.caption(f"出題データ: {source_labels[data_source]}")

    if data_source == "uploaded":
        _practice_with_uploaded_data(past_data_df)
        return

    if not has_database_data:
        st.warning("問題データが登録されていません。seed_problems.jsonを確認してください。")
        return

    case_map: Dict[str, Dict[str, int]] = defaultdict(dict)
    for entry in index:
        case_map[entry["case_label"]][entry["year"]] = entry["id"]

    case_options = sorted(
        case_map.keys(),
        key=lambda label: (
            CASE_ORDER.index(label) if label in CASE_ORDER else len(CASE_ORDER),
            label,
        ),
    )

    if not case_options:
        st.warning("事例が登録されていません。データを追加してください。")
        return

    st.markdown(
        dedent(
            """
            <style>
            .practice-tree .stRadio > div[role="radiogroup"] {
                gap: 0.35rem;
            }
            .practice-tree .tree-level-title {
                font-size: 0.85rem;
                font-weight: 600;
                color: #1f2937;
                margin-bottom: 0.15rem;
            }
            .practice-tree .tree-level-year .stRadio > div[role="radiogroup"] label {
                padding-left: 0.75rem;
            }
            .practice-tree .tree-level-question .stRadio > div[role="radiogroup"] label {
                padding-left: 1.5rem;
            }
            </style>
            """
        ).strip(),
        unsafe_allow_html=True,
    )

    problem: Optional[Dict[str, Any]] = None
    selected_case: Optional[str] = None
    selected_year: Optional[str] = None
    selected_question: Optional[Dict[str, Any]] = None

    tree_col, insight_col = st.columns([0.42, 0.58], gap="large")

    with tree_col:
        st.markdown('<div class="practice-tree">', unsafe_allow_html=True)
        st.markdown("#### 出題ナビゲーション")
        st.caption("事例→年度→設問の順にクリックすると、右側に要点が即時表示されます。")

        case_key = "practice_tree_case"
        if case_key not in st.session_state or st.session_state[case_key] not in case_options:
            st.session_state[case_key] = case_options[0]
        selected_case = st.radio(
            "事例I〜IV",
            case_options,
            key=case_key,
            label_visibility="collapsed",
        )

        year_options = sorted(
            case_map[selected_case].keys(),
            key=_year_sort_key,
            reverse=True,
        )
        year_key = "practice_tree_year"
        problem_id: Optional[int] = None
        question_lookup: Dict[int, Dict[str, Any]] = {}
        question_options: List[int] = []

        if not year_options:
            st.warning("選択した事例の年度が登録されていません。", icon="⚠️")
        else:
            if year_key not in st.session_state or st.session_state[year_key] not in year_options:
                st.session_state[year_key] = year_options[0]
            selected_year = st.radio(
                "↳ 年度 (R6/R5/R4…)",
                year_options,
                key=year_key,
                format_func=_format_reiwa_label,
                label_visibility="collapsed",
            )

            problem_id = case_map[selected_case][selected_year]
            raw_problem = _load_problem_detail(problem_id, signature)
            problem = _apply_uploaded_text_overrides(raw_problem)

            if problem and problem["questions"]:
                question_lookup = {q["id"]: q for q in problem["questions"]}
                question_options = list(question_lookup.keys())

        question_key = f"practice_tree_question_{problem_id}" if problem_id else "practice_tree_question"
        if question_options:
            if question_key not in st.session_state or st.session_state[question_key] not in question_options:
                st.session_state[question_key] = question_options[0]

            def _format_question_option(question_id: int) -> str:
                question = question_lookup.get(question_id)
                if not question:
                    return "設問"
                return f"設問{question['order']}"

            selected_question_id = st.radio(
                "↳ 設問1〜",
                question_options,
                key=question_key,
                format_func=_format_question_option,
                label_visibility="collapsed",
            )
            selected_question = question_lookup.get(selected_question_id)
        elif selected_year:
            st.info("この事例の設問データが見つかりません。設定ページから追加してください。", icon="ℹ️")

        st.markdown("</div>", unsafe_allow_html=True)

    with insight_col:
        st.markdown("#### 設問インサイト")
        if selected_case and selected_year:
            st.markdown(f"**{selected_case} / {_format_reiwa_label(selected_year)}**")
        if problem:
            st.caption(problem["title"])

        short_year = _format_reiwa_label(selected_year or "")
        notice = EXAM_YEAR_NOTICE.get(short_year)
        if notice:
            notes_text = "\n".join(f"・{item}" for item in notice["notes"])
            st.info(
                f"試験時間: {notice['time']}\n{notes_text}",
                icon="📝",
            )

        if selected_question:
            st.markdown(
                f"**設問{selected_question['order']}：{selected_question['prompt']}**"
            )
            insight_text = _resolve_question_insight(selected_question)
            if insight_text:
                st.markdown("##### 設問インサイト")
                st.write(insight_text)
            full_question_text = _normalize_text_block(
                _select_first(
                    selected_question,
                    ["設問文", "問題文", "question_text", "body"],
                )
            )
            if full_question_text:
                st.markdown("##### 設問文")
                st.write(full_question_text)
            st.markdown("##### 設問の狙い")
            st.write(_infer_question_aim(selected_question))
            st.markdown("##### 必要アウトプット形式")
            st.write(_describe_output_requirements(selected_question))
            st.markdown("##### 定番解法プロンプト")
            st.write(_suggest_solution_prompt(selected_question))
        else:
            st.caption("設問を選択すると狙いや解法テンプレートを表示します。")

    if not problem:
        st.error("問題を取得できませんでした。")
        return

    st.markdown('<div id="practice-top"></div>', unsafe_allow_html=True)

    if selected_year and selected_case:
        st.subheader(f"{selected_year} {selected_case}『{problem['title']}』")
    else:
        st.subheader(problem["title"])
    st.write(problem["overview"])

    layout_container = st.container()
    problem_context = _collect_problem_context_text(problem)
    if problem_context:
        _inject_context_column_styles()
        st.markdown(
            dedent(
                """
                <div class="context-panel-mobile-bar">
                    <button type="button" class="context-panel-trigger" aria-expanded="false" aria-controls="context-panel">
                        与件文を開く
                    </button>
                </div>
                <div class="context-panel-backdrop" aria-hidden="true"></div>
                """
            ).strip(),
            unsafe_allow_html=True,
        )
        context_col, main_col = layout_container.columns([0.42, 0.58], gap="large")
        with context_col:
            st.markdown(
                dedent(
                    """
                    <section id="context-panel" class="context-panel" aria-labelledby="context-panel-heading" aria-hidden="false">
                        <div class="context-panel-inner">
                            <div class="context-panel-header">
                                <h3 id="context-panel-heading" class="context-panel-title" aria-label="与件文">与件文</h3>
                                <button type="button" class="context-panel-close" aria-label="与件文を閉じる">閉じる</button>
                            </div>
                            <div class="context-panel-scroll" tabindex="-1">
                    """
                ).strip(),
                unsafe_allow_html=True,
            )
            _render_problem_context_block(problem_context)
            st.markdown("</div></div></section>", unsafe_allow_html=True)
            _inject_context_panel_behavior()
    else:
        main_col = layout_container

    answers: List[RecordedAnswer] = []
    question_specs: List[QuestionSpec] = []
    submitted = False

    with main_col:
        st.markdown(
            dedent(
                """
                <div class="practice-quick-nav">
                    <a href="#practice-answers"><button type="button">質問へ移動</button></a>
                    <a href="#practice-actions"><button type="button">下へスクロール</button></a>
                </div>
                """
            ).strip(),
            unsafe_allow_html=True,
        )

        question_overview = pd.DataFrame(
            [
                {
                    "設問": idx + 1,
                    "配点": q["max_score"],
                    "キーワード": "、".join(q["keywords"]) if q["keywords"] else "-",
                    "評価したい力": "・".join(
                        card.get("label", "") for card in q.get("intent_cards", []) if card.get("label")
                    )
                    or "-",
                }
                for idx, q in enumerate(problem["questions"])
            ]
        )
        st.data_editor(
            question_overview,
            hide_index=True,
            use_container_width=True,
            disabled=True,
            column_config={
                "キーワード": st.column_config.TextColumn(help="採点で評価される重要ポイント"),
                "評価したい力": st.column_config.TextColumn(help="設問趣旨から読み取れる評価観点"),
            },
        )
        st.caption("採点の観点を事前に確認してから回答に取り組みましょう。")

        _render_retrieval_flashcards(problem)

        if not st.session_state.practice_started:
            st.session_state.practice_started = datetime.utcnow()

        st.markdown('<div id="practice-answers"></div>', unsafe_allow_html=True)

        _inject_guideline_styles()

        for question in problem["questions"]:
            text = _question_input(
                problem["id"],
                question,
                case_label=problem.get("case_label") or problem.get("case"),
            )
            question_specs.append(
                QuestionSpec(
                    id=question["id"],
                    prompt=question["prompt"],
                    max_score=question["max_score"],
                    model_answer=question["model_answer"],
                    keywords=question["keywords"],
                )
            )
            visibility_key = _guideline_visibility_key(problem["id"], question["id"])
            if visibility_key not in st.session_state:
                st.session_state[visibility_key] = True
            show_guideline = st.checkbox(
                "模範解答・採点ガイドラインを表示",
                key=visibility_key,
                help="模範解答全文と採点時に確認されるポイントを必要なときに開閉できます。",
            )
            if show_guideline:
                rows: List[str] = []
                if question["keywords"]:
                    keywords_text = "、".join(question["keywords"])
                    rows.append(
                        dedent(
                            f"""
                            <tr>
                                <th scope=\"row\">
                                    <div class=\"guideline-label\">
                                        <span class=\"guideline-icon\" data-icon=\"KW\"></span>
                                        <span>キーワード評価</span>
                                    </div>
                                </th>
                                <td>
                                    <div class=\"guideline-body\">{html.escape(keywords_text)} を含めると加点対象です。</div>
                                </td>
                            </tr>
                            """
                        ).strip()
                    )

                model_answer_text = _normalize_text_block(question.get("model_answer"))
                if model_answer_text:
                    model_answer_html = html.escape(model_answer_text).replace("\n", "<br>")
                    model_answer_length_value = _compute_fullwidth_length(
                        model_answer_text.replace("\n", "")
                    )
                    model_answer_length = _format_fullwidth_length(model_answer_length_value)
                    rows.append(
                        dedent(
                            f"""
                            <tr>
                                <th scope=\"row\">
                                    <div class=\"guideline-label\">
                                        <span class=\"guideline-icon\" data-icon=\"模\"></span>
                                        <span>模範解答</span>
                                    </div>
                                </th>
                                <td>
                                    <div class=\"guideline-body\">
                                        <span class=\"guideline-meta\">文字数: {model_answer_length}字</span>
                                        {model_answer_html}
                                    </div>
                                </td>
                            </tr>
                            """
                        ).strip()
                    )

                explanation_text = _normalize_text_block(
                    question.get("explanation") or question.get("解説")
                )
                if explanation_text:
                    explanation_html = html.escape(explanation_text).replace("\n", "<br>")
                    rows.append(
                        dedent(
                            f"""
                            <tr>
                                <th scope=\"row\">
                                    <div class=\"guideline-label\">
                                        <span class=\"guideline-icon\" data-icon=\"解\"></span>
                                        <span>模範解答の解説</span>
                                    </div>
                                </th>
                                <td>
                                    <div class=\"guideline-body\">{explanation_html}</div>
                                </td>
                            </tr>
                            """
                        ).strip()
                    )

                if rows:
                    st.markdown(
                        """
                        <div class="guideline-card">
                            <table class="guideline-table">
                                <tbody>
                                    {rows}
                                </tbody>
                            </table>
                        </div>
                        """.format(rows="".join(rows)),
                        unsafe_allow_html=True,
                    )
                st.caption(
                    "模範解答は構成や論理展開の参考例です。キーワードを押さえつつ自分の言葉で表現しましょう。"
                )

        st.markdown('<div id="practice-actions"></div>', unsafe_allow_html=True)

        submitted = st.button("AI採点に送信", type="primary")

    if submitted:
        answers = []
        for question, spec in zip(problem["questions"], question_specs):
            text = st.session_state.drafts.get(_draft_key(problem["id"], question["id"]), "")
            result = scoring.score_answer(text, spec)
            answers.append(
                RecordedAnswer(
                    question_id=question["id"],
                    answer_text=text,
                    score=result.score,
                    feedback=result.feedback,
                    keyword_hits=result.keyword_hits,
                )
            )

        submitted_at = datetime.utcnow()
        started_at = st.session_state.practice_started or submitted_at
        duration = int((submitted_at - started_at).total_seconds())
        total_score = sum(answer.score for answer in answers)
        total_max = sum(question["max_score"] for question in problem["questions"])
        score_ratio = (total_score / total_max) if total_max else 0.0

        attempt_id = database.record_attempt(
            user_id=user["id"],
            problem_id=problem["id"],
            mode="practice",
            answers=answers,
            started_at=started_at,
            submitted_at=submitted_at,
            duration_seconds=duration,
        )
        database.update_spaced_review(
            user_id=user["id"],
            problem_id=problem["id"],
            score_ratio=score_ratio,
            reviewed_at=submitted_at,
        )
        st.session_state.practice_started = None

        st.success("採点が完了しました。結果を確認してください。")
        render_attempt_results(attempt_id)


def _practice_with_uploaded_data(df: pd.DataFrame) -> None:
    if df is None or df.empty:
        st.info("アップロード済みの過去問データがありません。設定ページからファイルを登録してください。")
        return

    required_cols = {"年度", "事例", "設問番号", "問題文", "配点", "模範解答", "解説"}
    if not required_cols.issubset(df.columns):
        missing = required_cols.difference(set(df.columns))
        st.error(f"必要な列が不足しています: {', '.join(sorted(missing))}")
        return

    optional_context_cols = {"与件文", "与件文全体", "詳細解説"}
    if not optional_context_cols.issubset(df.columns):
        st.info(
            "テンプレートに『与件文全体』『与件文』『詳細解説』列を追加すると、演習画面にハイライトと深掘り解説が表示されます。",
            icon="💡",
        )

    contexts = dict(st.session_state.get("uploaded_case_contexts", {}))
    question_texts = dict(st.session_state.get("uploaded_question_texts", {}))
    case_metadata = dict(st.session_state.get("uploaded_case_metadata", {}))
    question_metadata = dict(st.session_state.get("uploaded_question_metadata", {}))

    normalized_columns = {str(col).lower(): col for col in df.columns}
    video_col = None
    diagram_col = None
    diagram_caption_col = None
    for key, col in normalized_columns.items():
        if key in {"動画url", "video_url"}:
            video_col = col
        elif key in {"図解パス", "diagram_path"}:
            diagram_col = col
        elif key in {"図解キャプション", "diagram_caption"}:
            diagram_caption_col = col

    def _display_numeric(value: Any) -> str:
        if value is None:
            return "-"
        try:
            if pd.isna(value):
                return "-"
        except TypeError:
            pass
        if isinstance(value, (int, float)):
            if isinstance(value, float) and float(value).is_integer():
                return str(int(value))
            return str(value)
        text = str(value).strip()
        return text or "-"

    def _has_value(value: Any) -> bool:
        if value is None:
            return False
        try:
            if pd.isna(value):
                return False
        except TypeError:
            pass
        if isinstance(value, str) and not value.strip():
            return False
        return True

    def _extract_keywords(value: Any) -> List[str]:
        if value is None:
            return []
        if isinstance(value, str):
            parts = re.split(r"[、,;\n]", value)
            return [part.strip() for part in parts if part.strip()]
        if isinstance(value, Iterable):
            return [str(item).strip() for item in value if str(item).strip()]
        return []

    records: List[Dict[str, Any]] = []
    for row_order, (row_index, row) in enumerate(df.iterrows()):
        year_value = _normalize_text_block(row.get("年度"))
        case_raw = _normalize_text_block(row.get("事例"))
        if not year_value or not case_raw:
            continue
        year_label = _format_reiwa_label(str(year_value))
        case_label = _normalize_case_label(case_raw) or str(case_raw)
        case_key = _compose_case_key(year_label, case_label)
        record = dict(row)
        record["_option_key"] = f"{case_label}::{year_label}::{row_index}"
        record["_row_order"] = row_order
        record["_year_label"] = year_label
        record["_year_display"] = year_value
        record["_case_label"] = case_label
        record["_case_metadata_key"] = case_key
        meta_case = case_metadata.get(case_key, {})
        record["_case_title"] = meta_case.get("title") or _normalize_text_block(
            _select_first(
                row,
                ("ケースタイトル", "問題タイトル", "タイトル", "ケース名", "問題名"),
            )
        )
        record["_case_overview"] = meta_case.get("overview") or _normalize_text_block(
            _select_first(
                row,
                ("ケース概要", "概要", "問題概要", "背景"),
            )
        )
        normalized_number = _normalize_question_number(row.get("設問番号"))
        record["_normalized_question_number"] = normalized_number
        if normalized_number is not None:
            slot_key = _compose_slot_key(year_label, case_label, int(normalized_number))
            record["_slot_key"] = slot_key
            override_text = question_texts.get(slot_key)
            if isinstance(override_text, dict):
                override_body = override_text.get("question_text") or override_text.get(
                    "設問文"
                )
                aim_override = _normalize_text_block(
                    override_text.get("question_aim")
                    or override_text.get("設問の狙い")
                )
                output_override = _normalize_text_block(
                    override_text.get("output_format")
                    or override_text.get("必要アウトプット形式")
                )
                solution_override = _normalize_text_block(
                    override_text.get("solution_prompt")
                    or override_text.get("定番解法プロンプト")
                )
                insight_override = _normalize_text_block(
                    override_text.get("question_insight")
                    or override_text.get("設問インサイト")
                )
            else:
                override_body = override_text
                aim_override = None
                output_override = None
                solution_override = None
                insight_override = None

            normalized_override = _normalize_text_block(override_body)
            if normalized_override:
                record["問題文"] = normalized_override
            if aim_override:
                record["uploaded_question_aim"] = aim_override
            if insight_override:
                record["uploaded_question_insight"] = insight_override
            if output_override:
                record["uploaded_output_format"] = output_override
            if solution_override:
                record["uploaded_solution_prompt"] = solution_override
            meta_question = question_metadata.get(slot_key, {})
            if meta_question.get("prompt"):
                record["設問見出し"] = meta_question.get("prompt")
            if meta_question.get("question_text") and not normalized_override:
                record["問題文"] = meta_question.get("question_text")
            if meta_question.get("character_limit") is not None:
                record["制限字数"] = meta_question.get("character_limit")
            if meta_question.get("max_score") is not None:
                record["配点"] = meta_question.get("max_score")
            if meta_question.get("model_answer"):
                record["模範解答"] = meta_question.get("model_answer")
            if meta_question.get("explanation"):
                record["解説"] = meta_question.get("explanation")
            if meta_question.get("detailed_explanation"):
                record["詳細解説"] = meta_question.get("detailed_explanation")
            if meta_question.get("question_insight"):
                record["uploaded_question_insight"] = meta_question.get("question_insight")
            if meta_question.get("keywords"):
                record["キーワード"] = "、".join(meta_question.get("keywords") or [])
            if meta_question.get("video_url"):
                if not video_col:
                    video_col = "動画URL"
                record[video_col] = meta_question.get("video_url")
            if meta_question.get("diagram_path"):
                if not diagram_col:
                    diagram_col = "図解パス"
                record[diagram_col] = meta_question.get("diagram_path")
            if meta_question.get("diagram_caption"):
                if not diagram_caption_col:
                    diagram_caption_col = "図解キャプション"
                record[diagram_caption_col] = meta_question.get("diagram_caption")
        if contexts:
            context_override = _normalize_text_block(contexts.get(case_key))
            if context_override and not any(
                _normalize_text_block(record.get(col)) for col in optional_context_cols
            ):
                record["与件文全体"] = context_override
                record.setdefault("与件文", context_override)
        elif meta_case.get("context") and not any(
            _normalize_text_block(record.get(col)) for col in optional_context_cols
        ):
            context_text = meta_case.get("context")
            record["与件文全体"] = context_text
            record.setdefault("与件文", context_text)
        records.append(record)

    if not records:
        st.warning("年度または事例が不足しているため、ナビゲーションを生成できません。アップロードデータを確認してください。")
        return

    case_map: Dict[str, Dict[str, List[str]]] = defaultdict(lambda: defaultdict(list))
    question_lookup: Dict[str, Dict[str, Any]] = {}
    for record in records:
        option_key = record["_option_key"]
        case_map[record["_case_label"]][record["_year_label"]].append(option_key)
        question_lookup[option_key] = record

    for case_label, years in case_map.items():
        for year_label, option_keys in years.items():
            option_keys.sort(
                key=lambda key: (
                    1 if question_lookup[key].get("_normalized_question_number") is None else 0,
                    question_lookup[key].get("_normalized_question_number")
                    if question_lookup[key].get("_normalized_question_number") is not None
                    else question_lookup[key].get("_row_order", 0),
                    question_lookup[key].get("_row_order", 0),
                )
            )

    def _case_sort_key(label: str) -> Tuple[int, str]:
        return (
            CASE_ORDER.index(label) if label in CASE_ORDER else len(CASE_ORDER),
            label,
        )

    case_options = sorted(case_map.keys(), key=_case_sort_key)
    if not case_options:
        st.warning("事例の情報が見つかりませんでした。")
        return

    tree_col, insight_col = st.columns([0.42, 0.58], gap="large")
    selected_case: Optional[str] = None
    selected_year: Optional[str] = None
    selected_question_key: Optional[str] = None
    selected_question: Optional[Dict[str, Any]] = None

    question_body_text: str = ""

    with tree_col:
        st.markdown('<div class="practice-tree">', unsafe_allow_html=True)
        st.markdown("#### 出題ナビゲーション")
        st.caption("事例→年度→設問の順にクリックすると、右側に要点が即時表示されます。")

        case_key = "uploaded_tree_case"
        if case_key not in st.session_state or st.session_state[case_key] not in case_options:
            st.session_state[case_key] = case_options[0]
        selected_case = st.radio(
            "事例I〜IV",
            case_options,
            key=case_key,
            label_visibility="collapsed",
        )

        year_options = sorted(
            case_map[selected_case].keys(),
            key=_year_sort_key,
            reverse=True,
        )
        if not year_options:
            st.warning("選択した事例の年度が見つかりませんでした。", icon="⚠️")
        else:
            year_key = f"uploaded_tree_year::{selected_case}"
            if year_key not in st.session_state or st.session_state[year_key] not in year_options:
                st.session_state[year_key] = year_options[0]
            selected_year = st.radio(
                "↳ 年度 (R6/R5/R4…)",
                year_options,
                key=year_key,
                format_func=_format_reiwa_label,
                label_visibility="collapsed",
            )

            question_keys = case_map[selected_case][selected_year]

            def _format_question_option(option_key: str) -> str:
                data = question_lookup.get(option_key, {})
                number = data.get("_normalized_question_number")
                if number is not None:
                    try:
                        return f"設問{int(number)}"
                    except (TypeError, ValueError):
                        return f"設問{number}"
                raw_number = _normalize_text_block(data.get("設問番号"))
                return f"設問{raw_number}" if raw_number else "設問"

            question_key = f"uploaded_tree_question::{selected_case}::{selected_year}"
            if question_keys:
                if (
                    question_key not in st.session_state
                    or st.session_state[question_key] not in question_keys
                ):
                    st.session_state[question_key] = question_keys[0]
                selected_question_key = st.radio(
                    "↳ 設問1〜",
                    question_keys,
                    key=question_key,
                    format_func=_format_question_option,
                    label_visibility="collapsed",
                )
                selected_question = question_lookup.get(selected_question_key)
                if selected_question:
                    slot_key = selected_question.get("_slot_key")
                    meta_question = (
                        question_metadata.get(slot_key)
                        if slot_key in question_metadata
                        else {}
                    )
                    raw_question_text = selected_question.get("問題文")
                    normalized_text = _normalize_text_block(raw_question_text)
                    if meta_question.get("question_text"):
                        normalized_text = meta_question.get("question_text")
                    if normalized_text:
                        question_body_text = normalized_text
                    else:
                        try:
                            if pd.isna(raw_question_text):
                                question_body_text = ""
                            else:
                                question_body_text = str(raw_question_text) if raw_question_text is not None else ""
                        except TypeError:
                            question_body_text = str(raw_question_text) if raw_question_text is not None else ""
            else:
                st.info("この年度の設問データが見つかりません。設定ページを確認してください。", icon="ℹ️")

        st.markdown("</div>", unsafe_allow_html=True)

    with insight_col:
        st.markdown("#### 設問インサイト")
        case_meta = {}
        if selected_case and selected_year:
            st.markdown(f"**{selected_case} / {_format_reiwa_label(selected_year)}**")
            case_meta = case_metadata.get(
                _compose_case_key(selected_year, selected_case), {}
            )
        if selected_question:
            if case_meta:
                case_title = case_meta.get("title")
                if case_title:
                    st.markdown(f"### {case_title}")
                case_overview = case_meta.get("overview")
                if case_overview:
                    st.write(case_overview)
            elif selected_question.get("_case_title"):
                st.markdown(f"### {selected_question['_case_title']}")
                if selected_question.get("_case_overview"):
                    st.write(selected_question.get("_case_overview"))
            prompt_line = _normalize_text_block(
                selected_question.get("設問見出し")
            ) or (question_body_text.splitlines()[0] if question_body_text else "")
            limit_value_normalized = _normalize_question_number(selected_question.get("制限字数"))
            insight_question = {
                "prompt": prompt_line,
                "設問文": question_body_text,
                "character_limit": limit_value_normalized,
                "max_score": selected_question.get("配点"),
                "explanation": selected_question.get("解説"),
                "keywords": _extract_keywords(
                    selected_question.get("キーワード") or selected_question.get("keywords")
                ),
            }
            insight_override = _resolve_question_insight(selected_question)
            if insight_override:
                insight_question["uploaded_question_insight"] = insight_override
            aim_override = _normalize_text_block(
                selected_question.get("uploaded_question_aim")
                or selected_question.get("question_aim")
                or selected_question.get("設問の狙い")
            )
            if aim_override:
                insight_question["uploaded_question_aim"] = aim_override
            output_override = _normalize_text_block(
                selected_question.get("uploaded_output_format")
                or selected_question.get("output_format")
                or selected_question.get("必要アウトプット形式")
            )
            if output_override:
                insight_question["uploaded_output_format"] = output_override
            solution_override = _normalize_text_block(
                selected_question.get("uploaded_solution_prompt")
                or selected_question.get("solution_prompt")
                or selected_question.get("定番解法プロンプト")
                or selected_question.get("解法プロンプト")
            )
            if solution_override:
                insight_question["uploaded_solution_prompt"] = solution_override
            question_label = _format_question_option(selected_question_key) if selected_question_key else "設問"
            st.markdown(f"**{question_label}：{prompt_line}**")
            insight_text = _resolve_question_insight(insight_question)
            if insight_text:
                st.markdown("##### 設問インサイト")
                st.write(insight_text)
            full_question_text = question_body_text
            if full_question_text:
                st.markdown("##### 設問文")
                st.write(full_question_text)
            st.markdown("##### 設問の狙い")
            st.write(_infer_question_aim(insight_question))
            st.markdown("##### 必要アウトプット形式")
            st.write(_describe_output_requirements(insight_question))
            st.markdown("##### 定番解法プロンプト")
            st.write(_suggest_solution_prompt(insight_question))
        else:
            st.caption("設問を選択すると狙いや解法テンプレートを表示します。")

    if not (selected_case and selected_year and selected_question):
        st.info("出題ナビゲーションから設問を選択すると詳細が表示されます。")
        return

    subset_keys = case_map[selected_case][selected_year]
    include_limit = any(
        _has_value(question_lookup[key].get("制限字数")) for key in subset_keys
    )
    include_keywords = any(
        _extract_keywords(
            question_lookup[key].get("キーワード") or question_lookup[key].get("keywords")
        )
        for key in subset_keys
    )
    overview_rows = []
    for key in subset_keys:
        data = question_lookup[key]
        number_label = _normalize_text_block(data.get("設問番号"))
        normalized_number = data.get("_normalized_question_number")
        if normalized_number is not None:
            number_label = str(int(normalized_number))
        overview_row = {
            "設問": number_label or "-",
            "配点": _display_numeric(data.get("配点")),
        }
        if include_limit:
            overview_row["制限字数"] = _display_numeric(data.get("制限字数"))
        if include_keywords:
            keywords = _extract_keywords(
                data.get("キーワード") or data.get("keywords")
            )
            overview_row["キーワード"] = "、".join(keywords) if keywords else "-"
        overview_rows.append(overview_row)

    if overview_rows:
        overview_df = pd.DataFrame(overview_rows)
        column_config: Dict[str, Any] = {}
        if "キーワード" in overview_df.columns:
            column_config["キーワード"] = st.column_config.TextColumn(help="採点で評価される重要ポイント")
        if "制限字数" in overview_df.columns:
            column_config["制限字数"] = st.column_config.TextColumn(help="設問に指定された文字数上限")
        st.data_editor(
            overview_df,
            hide_index=True,
            use_container_width=True,
            disabled=True,
            column_config=column_config,
        )
        st.caption("選択した年度・事例の設問一覧です。配点や制限字数を確認しましょう。")

    question_number = selected_question.get("_normalized_question_number")
    question_heading = (
        f"第{int(question_number)}問" if isinstance(question_number, (int, float)) else None
    )
    if not question_heading:
        raw_number_label = _normalize_text_block(selected_question.get("設問番号"))
        question_heading = f"設問{raw_number_label}" if raw_number_label else "設問"

    raw_score = selected_question.get("配点")
    score_display = _display_numeric(raw_score)
    st.subheader(f"{question_heading} ({score_display}点)")

    prompt_line = _normalize_text_block(selected_question.get("設問見出し")) or (
        question_body_text.splitlines()[0] if question_body_text else ""
    )
    limit_value_raw = selected_question.get("制限字数")
    limit_int: Optional[int] = _normalize_question_number(limit_value_raw)
    if limit_int is None and limit_value_raw is not None:
        try:
            if not pd.isna(limit_value_raw):
                limit_int = int(float(limit_value_raw))
        except (TypeError, ValueError):
            limit_int = None

    overview_question = {
        "order": question_number or selected_question.get("設問番号"),
        "prompt": prompt_line,
        "character_limit": limit_int,
        "max_score": raw_score,
        "aim": question_body_text.split("\n\n")[0] if question_body_text else "",
    }
    _render_question_overview_card(
        overview_question,
        case_label=selected_case,
        source_label=f"{selected_year} {selected_case}",
    )

    context_candidates = [
        selected_question.get("与件文全体"),
        selected_question.get("与件文"),
        selected_question.get("与件"),
        selected_question.get("context"),
        selected_question.get("context_text"),
    ]
    for candidate in context_candidates:
        normalized_context = _normalize_text_block(candidate)
        if normalized_context:
            _render_question_context_block(normalized_context)
            break

    st.markdown("**問題文**")
    st.write(question_body_text)

    if limit_int is not None:
        max_chars = limit_int
    else:
        score_numeric = None
        try:
            if pd.notna(raw_score):
                score_numeric = float(raw_score)
        except (TypeError, ValueError):
            score_numeric = None
        if score_numeric is not None and score_numeric <= 25:
            max_chars = 60
        else:
            max_chars = 80

    answer_fragment = (
        _normalize_text_block(selected_question.get("設問番号"))
        or (str(question_number) if question_number is not None else selected_question_key)
    )
    answer_key = f"uploaded_answer_{selected_year}_{selected_case}_{answer_fragment}"
    user_answer = st.text_area("回答を入力", key=answer_key)
    _render_character_counter(user_answer, max_chars)

    if limit_int is not None:
        with st.expander("文字数スライサー"):
            slider_key = f"extract_{selected_year}_{selected_case}_{answer_fragment}"
            slider_min = min(20, limit_int)
            slider_step = max(1, min(5, limit_int))
            extract_count = st.slider(
                "指定字数で抜き出し",
                min_value=slider_min,
                max_value=limit_int,
                value=limit_int,
                step=slider_step,
                key=slider_key,
            )
            excerpt = (question_body_text or "")[: extract_count]
            st.code(excerpt, language="markdown")

    with st.expander("MECE/因果スキャナ", expanded=bool(user_answer.strip())):
        _render_mece_causal_scanner(user_answer)

    detailed_explanation = _normalize_text_block(selected_question.get("詳細解説"))
    expander_label = "模範解答／解説を見る"
    if detailed_explanation:
        expander_label += "（詳細あり）"

    with st.expander(expander_label):
        video_url = None
        diagram_path = None
        diagram_caption = None
        if video_col and pd.notna(selected_question.get(video_col)):
            video_url = str(selected_question.get(video_col))
        if diagram_col and pd.notna(selected_question.get(diagram_col)):
            diagram_path = str(selected_question.get(diagram_col))
        if diagram_caption_col and pd.notna(selected_question.get(diagram_caption_col)):
            diagram_caption = str(selected_question.get(diagram_caption_col))
        _render_model_answer_section(
            model_answer=selected_question.get("模範解答"),
            explanation=selected_question.get("解説"),
            video_url=video_url,
            diagram_path=diagram_path,
            diagram_caption=diagram_caption,
            context_id=f"uploaded-{selected_year}-{selected_case}-{answer_fragment}",
            year=selected_year,
            case_label=selected_case,
            question_number=_normalize_question_number(selected_question.get("設問番号")),
            detailed_explanation=detailed_explanation,
        )


def _load_tabular_frame(file_bytes: bytes, filename: str) -> pd.DataFrame:
    name_lower = filename.lower()
    buffer = io.BytesIO(file_bytes)
    if name_lower.endswith(".csv"):
        return pd.read_csv(buffer)
    if name_lower.endswith(".xlsx") or name_lower.endswith(".xls"):
        return pd.read_excel(buffer)
    raise ValueError("サポートされていないファイル形式です")


def _build_uploaded_exam_metadata(
    df: pd.DataFrame,
) -> Tuple[Dict[str, Dict[str, Any]], Dict[str, Dict[str, Any]]]:
    case_metadata: Dict[str, Dict[str, Any]] = {}
    question_metadata: Dict[str, Dict[str, Any]] = {}

    for _, row in df.iterrows():
        year_value = _normalize_text_block(row.get("年度"))
        case_raw = _normalize_text_block(row.get("事例"))
        if not year_value or not case_raw:
            continue

        year_label = _format_reiwa_label(str(year_value))
        case_label = _normalize_case_label(case_raw) or str(case_raw)
        case_key = _compose_case_key(year_label, case_label)

        title = _normalize_text_block(
            _select_first(
                row,
                (
                    "ケースタイトル",
                    "問題タイトル",
                    "タイトル",
                    "ケース名",
                    "問題名",
                ),
            )
        )
        overview = _normalize_text_block(
            _select_first(
                row,
                (
                    "ケース概要",
                    "概要",
                    "問題概要",
                    "背景",
                ),
            )
        )
        context_text = _normalize_text_block(
            _select_first(
                row,
                (
                    "与件文全体",
                    "与件文",
                    "与件",
                    "context",
                    "context_text",
                ),
            )
        )

        case_entry = case_metadata.setdefault(case_key, {})
        if title:
            case_entry["title"] = title
        if overview:
            case_entry["overview"] = overview
        if context_text:
            case_entry.setdefault("context", context_text)

        number = _normalize_question_number(row.get("設問番号"))
        if number is None:
            continue

        slot_key = _compose_slot_key(year_label, case_label, int(number))
        aim_text = _normalize_text_block(
            _select_first(
                row,
                (
                    "設問の狙い",
                    "question_aim",
                    "aim",
                ),
            )
        )
        output_format_text = _normalize_text_block(
            _select_first(
                row,
                (
                    "必要アウトプット形式",
                    "output_format",
                    "required_output",
                ),
            )
        )
        solution_prompt_text = _normalize_text_block(
            _select_first(
                row,
                (
                    "定番解法プロンプト",
                    "solution_prompt",
                    "解法プロンプト",
                ),
            )
        )
        insight_text = _normalize_text_block(
            _select_first(
                row,
                (
                    "設問インサイト",
                    "question_insight",
                    "insight",
                ),
            )
        )
        keywords = _normalize_text_block(row.get("キーワード"))
        if keywords:
            keyword_list = [
                token.strip()
                for token in re.split(r"[、,;\n]", keywords)
                if token.strip()
            ]
        else:
            keyword_list = []

        question_metadata[slot_key] = {
            "prompt": _normalize_text_block(row.get("設問見出し")),
            "question_text": _normalize_text_block(row.get("問題文")),
            "character_limit": _normalize_question_number(row.get("制限字数")),
            "max_score": row.get("配点"),
            "model_answer": _normalize_text_block(row.get("模範解答")),
            "explanation": _normalize_text_block(row.get("解説")),
            "detailed_explanation": _normalize_text_block(row.get("詳細解説")),
            "keywords": keyword_list,
            "video_url": _normalize_text_block(row.get("動画URL")),
            "diagram_path": _normalize_text_block(row.get("図解パス")),
            "diagram_caption": _normalize_text_block(row.get("図解キャプション")),
            "question_aim": aim_text,
            "output_format": output_format_text,
            "solution_prompt": solution_prompt_text,
            "question_insight": insight_text,
        }

    return case_metadata, question_metadata


def _handle_past_data_upload(file_bytes: bytes, filename: str) -> bool:
    try:
        df, tables = _auto_parse_exam_document(file_bytes, filename)
    except Exception as exc:  # pragma: no cover - Streamlit runtime feedback
        st.error(f"ファイルの読み込み中にエラーが発生しました: {exc}")
        return False

    required_cols = {"年度", "事例", "設問番号", "問題文", "配点", "模範解答", "解説"}
    missing = required_cols.difference(set(df.columns))
    if missing:
        st.error(f"必要な列が含まれていません。不足列: {', '.join(sorted(missing))}")
        return False

    st.session_state.past_data = df
    st.session_state.past_data_tables = tables
    case_metadata, question_metadata = _build_uploaded_exam_metadata(df)
    st.session_state.uploaded_case_metadata = case_metadata
    st.session_state.uploaded_question_metadata = question_metadata

    contexts = dict(st.session_state.get("uploaded_case_contexts", {}))
    for case_key, meta in case_metadata.items():
        if not isinstance(case_key, str):
            continue
        context_text = _normalize_text_block((meta or {}).get("context")) if meta else None
        if context_text:
            contexts[case_key] = context_text
    st.session_state.uploaded_case_contexts = contexts

    existing_question_texts = dict(st.session_state.get("uploaded_question_texts", {}))
    normalized_question_texts: Dict[str, Dict[str, Any]] = {}
    for key, value in existing_question_texts.items():
        if isinstance(value, dict):
            normalized_question_texts[key] = dict(value)
        else:
            normalized_question_texts[key] = {"question_text": value}

    question_texts = normalized_question_texts
    text_col = next(
        (col for col in ("設問文", "問題文", "question_text") if col in df.columns),
        None,
    )
    aim_col = next(
        (col for col in ("設問の狙い", "question_aim", "aim") if col in df.columns),
        None,
    )
    output_col = next(
        (
            col
            for col in ("必要アウトプット形式", "output_format", "required_output")
            if col in df.columns
        ),
        None,
    )
    solution_col = next(
        (
            col
            for col in ("定番解法プロンプト", "solution_prompt", "解法プロンプト")
            if col in df.columns
        ),
        None,
    )
    insight_col = next(
        (
            col
            for col in ("設問インサイト", "question_insight", "insight")
            if col in df.columns
        ),
        None,
    )

    if text_col or aim_col or output_col or solution_col or insight_col:
        for _, row in df.iterrows():
            year_value = _normalize_text_block(row.get("年度"))
            case_raw = _normalize_text_block(row.get("事例"))
            question_number = _normalize_question_number(row.get("設問番号"))
            if not year_value or not case_raw or question_number is None:
                continue

            year_label = _format_reiwa_label(str(year_value))
            case_label = _normalize_case_label(case_raw)
            if not case_label:
                continue

            key = _compose_slot_key(year_label, case_label, int(question_number))
            entry = question_texts.setdefault(key, {})

            if text_col:
                question_text = _normalize_text_block(row.get(text_col))
                if question_text:
                    entry["question_text"] = question_text
            if aim_col:
                aim_text = _normalize_text_block(row.get(aim_col))
                if aim_text:
                    entry["question_aim"] = aim_text
            if output_col:
                output_text = _normalize_text_block(row.get(output_col))
                if output_text:
                    entry["output_format"] = output_text
            if solution_col:
                solution_prompt = _normalize_text_block(row.get(solution_col))
                if solution_prompt:
                    entry["solution_prompt"] = solution_prompt
            if insight_col:
                insight_text = _normalize_text_block(row.get(insight_col))
                if insight_text:
                    entry["question_insight"] = insight_text

    st.session_state.uploaded_question_texts = question_texts
    context_count = sum(
        1 for meta in case_metadata.values() if (meta or {}).get("context")
    )
    question_body_count = sum(
        1
        for entry in question_texts.values()
        if isinstance(entry, dict)
        and _normalize_text_block(entry.get("question_text"))
    )
    if df.empty:
        st.warning("設問が抽出できませんでした。原紙テンプレートと照合できるPDF/CSVを指定してください。")
        return False
    message = f"過去問データを読み込みました（{len(df)}件）。『過去問演習』ページで利用できます。"
    metadata_summary = []
    if context_count:
        metadata_summary.append(f"与件文 {context_count}件")
    if question_body_count:
        metadata_summary.append(f"設問文 {question_body_count}件")
    if metadata_summary:
        message += " " + " / ".join(metadata_summary) + "を更新しました。"
    if tables:
        message += f" 数表 {len(tables)}件をPandas DataFrameとして抽出しました。"
    st.success(message)
    return True


def _handle_model_answer_slot_upload(file_bytes: bytes, filename: str) -> bool:
    try:
        payload = json.loads(file_bytes.decode("utf-8"))
    except UnicodeDecodeError as exc:  # pragma: no cover - Streamlit runtime feedback
        st.error(f"JSONの読み込みに失敗しました（エンコーディングエラー）: {exc}")
        return False
    except json.JSONDecodeError as exc:  # pragma: no cover - Streamlit runtime feedback
        st.error(f"JSONの読み込みに失敗しました: {exc}")
        return False

    try:
        parsed_slots = _parse_model_answer_slots(payload)
    except ValueError as exc:  # pragma: no cover - Streamlit runtime feedback
        st.error(str(exc))
        return False

    existing = dict(st.session_state.get("model_answer_slots", {}))
    added = 0
    updated = 0

    for key, slot in parsed_slots.items():
        if key in existing:
            updated += 1
        else:
            added += 1
        existing[key] = slot

    st.session_state.model_answer_slots = existing
    st.success(f"模範解答スロットを登録しました。（新規 {added}件 / 上書き {updated}件）")
    return True


def render_attempt_results(attempt_id: int) -> None:
    detail = database.fetch_attempt_detail(attempt_id)
    attempt = detail["attempt"]
    answers = detail["answers"]

    st.subheader("採点結果")
    total_score = attempt["total_score"] or 0
    total_max = attempt["total_max_score"] or 0
    st.metric("総合得点", f"{total_score:.1f} / {total_max:.1f}")
    review_plan = database.get_spaced_review(attempt["user_id"], attempt["problem_id"])
    if review_plan:
        due_at = review_plan["due_at"]
        interval = review_plan["interval_days"]
        if due_at <= datetime.utcnow():
            st.warning(
                f"この事例の復習期限が到来しています。推奨: {due_at.strftime('%Y-%m-%d %H:%M')} (間隔 {interval}日)",
                icon="🔁",
            )
        else:
            st.info(
                f"次回の復習目安は {due_at.strftime('%Y-%m-%d %H:%M')} ごろです (推奨間隔 {interval}日)",
                icon="🔁",
            )
    if attempt["mode"] == "mock" and total_max:
        ratio = total_score / total_max
        if ratio >= 0.7:
            st.success("模擬試験クリア！称号『模試コンプリート』を獲得しました。")
            st.balloons()

    summary_rows = []
    for idx, answer in enumerate(answers, start=1):
        summary_rows.append(
            {
                "設問": idx,
                "得点": answer["score"],
                "満点": answer["max_score"],
                "キーワード達成": ", ".join(
                    [kw for kw, hit in (answer["keyword_hits"] or {}).items() if hit]
                )
                or "-",
            }
        )
    if summary_rows:
        st.data_editor(
            pd.DataFrame(summary_rows),
            hide_index=True,
            use_container_width=True,
            disabled=True,
        )
        st.caption("各設問の得点とキーワード達成状況を整理しました。弱点分析に活用してください。")

    case_label = answers[0].get("case_label") if answers else None
    bundle_evaluation = scoring.evaluate_case_bundle(case_label=case_label, answers=answers)
    if bundle_evaluation:
        _render_case_bundle_feedback(bundle_evaluation)

    for idx, answer in enumerate(answers, start=1):
        with st.expander(f"設問{idx}の結果", expanded=True):
            st.write(f"**得点:** {answer['score']} / {answer['max_score']}")
            st.write("**フィードバック**")
            st.markdown(f"<pre>{answer['feedback']}</pre>", unsafe_allow_html=True)
            if answer["keyword_hits"]:
                keyword_df = pd.DataFrame(
                    [[kw, "○" if hit else "×"] for kw, hit in answer["keyword_hits"].items()],
                    columns=["キーワード", "判定"],
                )
                st.table(keyword_df)
            with st.expander("模範解答と解説", expanded=False):
                _render_model_answer_section(
                    model_answer=answer["model_answer"],
                    explanation=answer["explanation"],
                    video_url=answer.get("video_url"),
                    diagram_path=answer.get("diagram_path"),
                    diagram_caption=answer.get("diagram_caption"),
                    context_id=f"attempt-{attempt_id}-q{idx}",
                    year=answer.get("year"),
                    case_label=answer.get("case_label"),
                    question_number=_normalize_question_number(answer.get("question_order")),
                    detailed_explanation=answer.get("detailed_explanation"),
                )
                st.caption("採点基準: 模範解答の論点とキーワードが盛り込まれているかを中心に評価しています。")

    st.info("学習履歴ページから過去の答案をいつでも振り返ることができます。")


def _render_case_bundle_feedback(evaluation: scoring.BundleEvaluation) -> None:
    st.markdown("### 観点別フィードバック")
    score_col, chart_col = st.columns([0.9, 1.1])
    with score_col:
        st.metric("提言力スコア", f"{evaluation.overall_score:.0f} / 100")
        st.caption(evaluation.summary)

    criteria_df = pd.DataFrame(
        [
            {
                "観点": crit.label,
                "スコア": crit.score,
                "配点比重": crit.weight,
                "コメント": crit.commentary,
            }
            for crit in evaluation.criteria
        ]
    )

    with chart_col:
        if not criteria_df.empty:
            chart = (
                alt.Chart(criteria_df)
                .mark_bar(cornerRadius=6)
                .encode(
                    x=alt.X("スコア:Q", axis=alt.Axis(format="%"), scale=alt.Scale(domain=[0, 1])),
                    y=alt.Y("観点:N", sort="-x"),
                    color=alt.Color("観点:N", legend=None, scale=alt.Scale(scheme="tealblues")),
                    tooltip=[
                        alt.Tooltip("観点:N", title="観点"),
                        alt.Tooltip("スコア:Q", title="スコア", format=".0%"),
                        alt.Tooltip("配点比重:Q", title="比重", format=".0%"),
                        alt.Tooltip("コメント:N", title="コメント"),
                    ],
                )
                .properties(height=180)
            )
            st.altair_chart(chart, use_container_width=True)

    st.markdown("**観点別コメント**")
    for row in criteria_df.itertuples():
        score_pct = row.スコア * 100
        weight_pct = row.配点比重 * 100
        st.markdown(
            f"- **{row.観点}** （{score_pct:.0f}点 / 比重{weight_pct:.0f}%）: {row.コメント}"
        )

    if evaluation.recommendations:
        st.markdown("**次のアクション**")
        for recommendation in evaluation.recommendations:
            st.markdown(f"- {recommendation}")


def _render_mock_exam_overview(
    exam: mock_exam.MockExam, *, container: Optional[Any] = None
) -> None:
    target = container or st
    if not (exam.notices or exam.timetable or exam.case_guides):
        return

    if exam.notices:
        target.markdown("#### 受験上の注意")
        target.markdown("\n".join(f"- {note}" for note in exam.notices))

    if exam.timetable:
        target.markdown("#### 本番時間割")
        rows = ["| 区分 | 時刻 | 補足 |", "| --- | --- | --- |"]
        for slot in exam.timetable:
            detail = slot.get("detail", "")
            rows.append(
                f"| {slot.get('slot', '')} | {slot.get('time', '')} | {detail} |"
            )
        target.markdown("\n".join(rows))

    if exam.case_guides:
        target.markdown("#### 事例別の体裁・確認ポイント")
        for guide in exam.case_guides:
            case_label = guide.get("case_label", "")
            focus = guide.get("focus")
            heading = case_label
            if focus:
                heading = f"{case_label}（{focus}）"
            target.markdown(f"**{heading}**")
            format_notes = guide.get("format") or []
            if format_notes:
                target.caption("体裁")
                target.markdown("\n".join(f"- {note}" for note in format_notes))
            specific_notes = guide.get("notes") or []
            if specific_notes:
                target.caption("注意")
                target.markdown("\n".join(f"- {note}" for note in specific_notes))


def _render_mock_exam_sidebar(exam: mock_exam.MockExam) -> None:
    if not (exam.timetable or exam.notices):
        return

    sidebar = st.sidebar.container()
    sidebar.divider()
    if exam.timetable:
        sidebar.markdown("#### 本番時間割")
        for slot in exam.timetable:
            detail = slot.get("detail")
            detail_text = f"（{detail}）" if detail else ""
            sidebar.markdown(
                f"- **{slot.get('slot', '')}**: {slot.get('time', '')}{detail_text}"
            )
    if exam.notices:
        sidebar.markdown("#### 注意事項")
        for note in exam.notices:
            sidebar.markdown(f"- {note}")


def _infer_case_weakness_tags(
    problem: Dict[str, Any], question_results: List[Dict[str, Any]]
) -> List[str]:
    tags: set[str] = set()
    if not question_results:
        return []

    keyword_ratios: List[float] = []
    lacking_causality = 0
    action_without_effect = 0
    missing_financial = False
    blank_answers = 0

    for item in question_results:
        answer_text = item.get("answer", "") or ""
        result = item.get("result")

        if not answer_text.strip():
            blank_answers += 1

        if result is not None:
            keyword_hits = result.keyword_hits or {}
            if keyword_hits:
                ratio = sum(1 for hit in keyword_hits.values() if hit) / len(keyword_hits)
                keyword_ratios.append(ratio)
                for keyword, hit in keyword_hits.items():
                    if not hit and _looks_financial_keyword(keyword):
                        missing_financial = True
            elif answer_text.strip():
                keyword_ratios.append(1.0)

        if answer_text.strip():
            if not _has_causal_connector(answer_text):
                lacking_causality += 1
            if _mentions_action_without_effect(answer_text):
                action_without_effect += 1

    total_questions = len(question_results)
    if keyword_ratios and sum(ratio < 0.5 for ratio in keyword_ratios) >= max(1, total_questions // 2):
        tags.add("キーワード網羅不足")
    if lacking_causality >= max(1, total_questions // 2):
        tags.add("因果の明示不足")
    if action_without_effect:
        tags.add("施策→効果が薄い")
    if missing_financial and problem.get("case_label") == "事例IV":
        tags.add("財務指標の選定ミス")
    if blank_answers:
        tags.add("未回答あり")

    return sorted(tags)


def _has_causal_connector(text: str) -> bool:
    normalized = text.replace(" ", "").replace("　", "")
    connectors = [
        "ため",
        "ので",
        "から",
        "結果",
        "につなが",
        "ことにより",
        "によって",
        "結果として",
        "ことで",
        "ゆえ",
    ]
    return any(connector in normalized for connector in connectors)


def _mentions_action_without_effect(text: str) -> bool:
    normalized = text.replace(" ", "").replace("　", "")
    action_keywords = [
        "施策",
        "実施",
        "導入",
        "提案",
        "取り組",
        "構築",
        "展開",
        "活用",
        "する",
    ]
    effect_keywords = [
        "効果",
        "成果",
        "結果",
        "向上",
        "改善",
        "高め",
        "促進",
        "波及",
        "貢献",
        "定着",
        "拡大",
        "増加",
        "維持",
    ]
    has_action = any(keyword in normalized for keyword in action_keywords)
    has_effect = any(keyword in normalized for keyword in effect_keywords)
    return has_action and not has_effect


def _looks_financial_keyword(keyword: str) -> bool:
    return bool(re.search(r"[A-Z]{2,}", keyword)) or any(
        token in keyword for token in ["率", "利益", "回転", "負債", "CF", "キャッシュ", "NPV", "ROA", "ROE", "ROI", "原価", "損益", "資本"]
    )


def mock_exam_page(user: Dict) -> None:
    st.title("模擬試験モード")
    st.caption("事例I～IVをまとめて演習し、時間管理と一括採点を体験します。")

    session = st.session_state.mock_session
    signature = _problem_data_signature()

    if not session:
        _remove_mock_notice_overlay()
        st.subheader("模試セットを選択")
        st.caption("説明を確認し、解きたい模試セットを選んでください。開始ボタンは右側に配置しています。")

        exams = mock_exam.available_mock_exams()
        exam_options = {exam.title: exam for exam in exams}
        exam_options["ランダム演習セット"] = mock_exam.random_mock_exam()

        select_col, start_col = st.columns([3, 1])
        with select_col:
            selected_title = st.selectbox("模試セット", list(exam_options.keys()))

        selected_exam = exam_options[selected_title]

        with start_col:
            st.write("")
            start_clicked = st.button(
                "模試を開始", type="primary", use_container_width=True
            )

        case_summaries = []
        for problem_id in selected_exam.problem_ids:
            problem = _apply_uploaded_text_overrides(
                _load_problem_detail(problem_id, signature)
            )
            if not problem:
                continue
            case_summaries.append(
                f"- {problem['year']} {problem['case_label']}：{problem['title']}"
            )
        if case_summaries:
            st.markdown("**セット内容の概要**")
            st.markdown("\n".join(case_summaries))

        _render_mock_exam_overview(selected_exam)

        if start_clicked:
            st.session_state.mock_session = {
                "exam": selected_exam,
                "start": datetime.utcnow(),
                "answers": {},
            }
            st.session_state["mock_notice_toggle"] = True
            st.rerun()
        return

    exam = session["exam"]
    start_time = session["start"]
    elapsed = datetime.utcnow() - start_time
    elapsed_total_seconds = max(int(elapsed.total_seconds()), 0)
    elapsed_minutes = elapsed_total_seconds // 60
    elapsed_seconds = elapsed_total_seconds % 60
    st.info(
        f"模試開始からの経過時間: {elapsed_minutes:02d}分{elapsed_seconds:02d}秒"
    )

    if "mock_notice_toggle" not in st.session_state:
        st.session_state["mock_notice_toggle"] = True

    show_notice = st.checkbox(
        "本番モードの注意書きを表示する",
        key="mock_notice_toggle",
    )
    if show_notice:
        _render_mock_notice_overlay(start_time=start_time)
    else:
        _remove_mock_notice_overlay()

    _render_mock_exam_sidebar(exam)
    if exam.notices or exam.timetable or exam.case_guides:
        with st.expander("本番セット（R6）の注意事項・体裁を確認する", expanded=False) as exp:
            _render_mock_exam_overview(exam, container=exp)

    tab_labels: List[str] = []
    for idx, problem_id in enumerate(exam.problem_ids):
        problem = _apply_uploaded_text_overrides(
            _load_problem_detail(problem_id, signature)
        )
        case_label = problem["case_label"] if problem else "不明"
        tab_labels.append(f"{idx+1}. {case_label}")

    tabs = st.tabs(tab_labels)
    for tab, problem_id in zip(tabs, exam.problem_ids):
        with tab:
            problem = _apply_uploaded_text_overrides(
                _load_problem_detail(problem_id, signature)
            )
            if not problem:
                st.error("問題の読み込みに失敗しました。")
                continue
            st.subheader(problem["title"])
            st.write(problem["overview"])
            for question in problem["questions"]:
                _question_input(
                    problem_id,
                    question,
                    widget_prefix="mock_textarea_",
                    case_label=problem.get("case_label") or problem.get("case"),
                )

    if st.button("模試を提出", type="primary"):
        overall_results = []
        for problem_id in exam.problem_ids:
            problem = _apply_uploaded_text_overrides(
                _load_problem_detail(problem_id, signature)
            )
            if not problem:
                st.warning("一部の問題データが取得できなかったため採点をスキップしました。")
                continue
            answers: List[RecordedAnswer] = []
            case_question_results: List[Dict[str, Any]] = []
            for question in problem["questions"]:
                text = st.session_state.drafts.get(_draft_key(problem_id, question["id"]), "")
                result = scoring.score_answer(
                    text,
                    QuestionSpec(
                        id=question["id"],
                        prompt=question["prompt"],
                        max_score=question["max_score"],
                        model_answer=question["model_answer"],
                        keywords=question["keywords"],
                    ),
                )
                answers.append(
                    RecordedAnswer(
                        question_id=question["id"],
                        answer_text=text,
                        score=result.score,
                        feedback=result.feedback,
                        keyword_hits=result.keyword_hits,
                    )
                )
                case_question_results.append({"question": question, "answer": text, "result": result})
            submitted_at = datetime.utcnow()
            attempt_id = database.record_attempt(
                user_id=user["id"],
                problem_id=problem_id,
                mode="mock",
                answers=answers,
                started_at=start_time,
                submitted_at=submitted_at,
                duration_seconds=int((submitted_at - start_time).total_seconds()),
            )
            total_score = sum(answer.score for answer in answers)
            total_max = sum(question["max_score"] for question in problem["questions"])
            score_ratio = (total_score / total_max) if total_max else 0.0
            database.update_spaced_review(
                user_id=user["id"],
                problem_id=problem_id,
                score_ratio=score_ratio,
                reviewed_at=submitted_at,
            )
            weakness_tags = _infer_case_weakness_tags(problem, case_question_results)
            overall_results.append((problem, attempt_id, weakness_tags))

        st.session_state.mock_session = None
        st.session_state.pop("mock_notice_toggle", None)
        _remove_mock_notice_overlay()
        st.success("模擬試験の採点が完了しました。結果を確認してください。")
        for problem, attempt_id, weakness_tags in overall_results:
            st.markdown(f"### {problem['year']} {problem['case_label']} {problem['title']}")
            render_attempt_results(attempt_id)
            st.markdown("**弱点タグ**")
            if weakness_tags:
                chips = "  ".join(f"`{tag}`" for tag in weakness_tags)
                st.markdown(chips)
            else:
                st.caption("特筆すべき弱点は検出されませんでした。")


def history_page(user: Dict) -> None:
    st.title("学習履歴")
    st.caption("演習記録・得点推移・エクスポートを確認します。")

    history_records = database.fetch_learning_history(user["id"])
    if not history_records:
        st.info("まだ演習履歴がありません。演習を実施するとここに表示されます。")
        return

    history_df = pd.DataFrame(history_records)
    history_df["日付"] = pd.to_datetime(history_df["日付"], errors="coerce")
    history_df.sort_values("日付", inplace=True)

    keyword_records = database.fetch_keyword_performance(user["id"])

    stats = _compute_learning_stats(history_df)
    progress_overview = _compute_progress_overview(history_df)
    reminder_settings = database.get_reminder_settings(user["id"])
    review_schedule = database.list_upcoming_reviews(user_id=user["id"], limit=10)
    due_reviews_count = database.count_due_reviews(user_id=user["id"])
    active_interval = (
        reminder_settings["interval_days"] if reminder_settings else stats["recommended_interval"]
    )
    reminder_time_value = _safe_time_from_string(
        reminder_settings["reminder_time"] if reminder_settings else None
    )
    selected_channels = (
        list(reminder_settings["preferred_channels"])
        if reminder_settings
        else ["メール通知"]
    )
    next_trigger_dt = _parse_iso_datetime(
        reminder_settings["next_trigger_at"] if reminder_settings else None
    )
    last_notified_dt = _parse_iso_datetime(
        reminder_settings["last_notified_at"] if reminder_settings else None
    )

    st.subheader("進捗ハイライトとスケジュール")
    summary_col1, summary_col2, summary_col3 = st.columns(3)
    summary_col1.metric("累計演習", f"{stats['total_sessions']}回")
    avg_display = f"{stats['recent_average']:.1f}点" if stats["recent_average"] is not None else "ー"
    summary_col2.metric("直近5回平均", avg_display)
    summary_col3.metric("連続学習日数", f"{stats['streak_days']}日")

    if stats["last_study_at"] is not None:
        st.info(
            f"直近の演習は {stats['last_study_at'].strftime('%Y-%m-%d %H:%M')} 実施。"
            f"推奨間隔 {stats['recommended_interval']}日 → 次回の目安は"
            f" {stats['next_study_at'].strftime('%Y-%m-%d %H:%M')} ごろです。"
        )
    else:
        st.info("これから学習を始めましょう。初期推奨リマインダーは3日おきです。")

    if review_schedule:
        st.markdown("#### 復習予定リスト")
        if due_reviews_count:
            st.warning(
                f"{due_reviews_count}件の復習期限が到来しています。『過去問演習』から優先的に復習しましょう。",
                icon="📌",
            )
        review_df = pd.DataFrame(
            [
                {
                    "次回予定": item["due_at"].strftime("%Y-%m-%d"),
                    "事例": f"{item['year']} {item['case_label']}",
                    "タイトル": item["title"],
                    "達成度": f"{(item['last_score_ratio'] or 0) * 100:.0f}%",
                    "間隔": f"{item['interval_days']}日",
                }
                for item in review_schedule
            ]
        )
        st.dataframe(review_df, use_container_width=True)
    else:
        st.caption("演習完了後に復習予定が自動生成されます。")

    with st.expander("リマインダー設定", expanded=reminder_settings is None):
        st.write("学習リズムに合わせて通知頻度・時刻・チャネルをカスタマイズできます。")
        cadence_labels = {
            "recommended": f"推奨 ({stats['recommended_interval']}日おき)",
            "every_other_day": "隔日 (2日おき)",
            "weekly": "週1回 (7日間隔)",
            "custom": "カスタム設定",
        }
        default_cadence = reminder_settings["cadence"] if reminder_settings else "recommended"
        custom_default = (
            reminder_settings["interval_days"]
            if reminder_settings and reminder_settings["cadence"] == "custom"
            else stats["recommended_interval"]
        )

        with st.form("reminder_form"):
            cadence_choice = st.selectbox(
                "通知頻度",
                options=list(cadence_labels.keys()),
                index=list(cadence_labels.keys()).index(default_cadence)
                if default_cadence in cadence_labels
                else 0,
                format_func=lambda key: cadence_labels[key],
            )
            custom_interval = None
            if cadence_choice == "custom":
                custom_interval = st.number_input(
                    "通知間隔（日）",
                    min_value=1,
                    max_value=30,
                    value=int(custom_default),
                    step=1,
                )
            reminder_time_input = st.time_input("通知時刻", value=reminder_time_value)
            channel_options = ["メール通知", "スマートフォン通知"]
            channels_selection = st.multiselect(
                "通知チャネル",
                options=channel_options,
                default=[c for c in selected_channels if c in channel_options] or channel_options[:1],
            )

            submitted = st.form_submit_button("設定を保存")

            if submitted:
                if not channels_selection:
                    st.warning("通知チャネルを1つ以上選択してください。")
                else:
                    if cadence_choice == "recommended":
                        interval_days = stats["recommended_interval"]
                    elif cadence_choice == "every_other_day":
                        interval_days = 2
                    elif cadence_choice == "weekly":
                        interval_days = 7
                    else:
                        interval_days = int(custom_interval) if custom_interval else 1

                    next_trigger = _calculate_next_reminder(
                        stats["reference_datetime"], interval_days, reminder_time_input
                    )
                    database.upsert_reminder_settings(
                        user_id=user["id"],
                        cadence=cadence_choice,
                        interval_days=interval_days,
                        preferred_channels=channels_selection,
                        reminder_time=reminder_time_input.strftime("%H:%M"),
                        next_trigger_at=next_trigger,
                    )
                    st.success(
                        f"リマインダーを保存しました。次回通知予定: {next_trigger.strftime('%Y-%m-%d %H:%M')}"
                    )
                    reminder_settings = database.get_reminder_settings(user["id"])
                    active_interval = reminder_settings["interval_days"]
                    reminder_time_value = _safe_time_from_string(reminder_settings["reminder_time"])
                    selected_channels = list(reminder_settings["preferred_channels"])
                    next_trigger_dt = _parse_iso_datetime(reminder_settings["next_trigger_at"])
                    last_notified_dt = _parse_iso_datetime(reminder_settings["last_notified_at"])

    if reminder_settings and next_trigger_dt:
        st.success(
            f"次回の通知予定: {next_trigger_dt.strftime('%Y-%m-%d %H:%M')}"
            f" / チャネル: {'、'.join(selected_channels)}"
        )
        if last_notified_dt:
            st.caption(f"前回記録された通知送信: {last_notified_dt.strftime('%Y-%m-%d %H:%M')}")
        if st.button("テスト通知を送信（シミュレーション）"):
            simulated_next = next_trigger_dt + timedelta(days=active_interval)
            database.mark_reminder_sent(
                reminder_settings["id"], next_trigger_at=simulated_next
            )
            st.info(
                f"通知送信を記録しました（ダミー）。次回予定: {simulated_next.strftime('%Y-%m-%d %H:%M')}"
            )
            reminder_settings = database.get_reminder_settings(user["id"])
            active_interval = reminder_settings["interval_days"]
            reminder_time_value = _safe_time_from_string(reminder_settings["reminder_time"])
            selected_channels = list(reminder_settings["preferred_channels"])
            next_trigger_dt = _parse_iso_datetime(reminder_settings["next_trigger_at"])
            last_notified_dt = _parse_iso_datetime(reminder_settings["last_notified_at"])
    else:
        st.info("リマインダーを設定すると、メールやスマートフォン通知と連携した学習習慣づくりをサポートできます。")

    schedule_preview = _build_schedule_preview(
        stats["reference_datetime"],
        active_interval,
        reminder_time_value,
        selected_channels,
        first_event=next_trigger_dt,
    )
    st.dataframe(schedule_preview, use_container_width=True)
    st.caption("今後の通知予定（サンプル）を確認し、リマインダー運用のイメージを掴めます。")

    st.caption(
        "通知APIやワークフロー自動化ツールと連携すると、保存した予定に合わせたメール送信やモバイル通知の運用が可能です。"
    )

    st.subheader("学習レベルと進捗状況")
    level_info = progress_overview["level"]
    level_col, summary_col = st.columns([1, 2])
    with level_col:
        st.metric("現在のレベル", f"Lv.{int(level_info['level'])}")
        st.caption(f"累計経験値: {level_info['total_experience']:.0f} XP")
    with summary_col:
        st.markdown("次のレベルまで")
        st.progress(level_info["progress_ratio"])
        st.caption(
            f"あと {level_info['xp_to_next_level']:.0f} XP でレベル{int(level_info['level']) + 1}"
        )
        overall = progress_overview["overall"]
        st.caption(
            f"年度×事例の進捗: {overall['completed']} / {overall['total']}"
            f" ({overall['ratio'] * 100:.0f}%)"
        )

    year_col, case_col = st.columns(2)
    with year_col:
        st.markdown("##### 年度別進捗")
        if progress_overview["years"]:
            for year_item in progress_overview["years"]:
                st.markdown(
                    f"**{year_item['label']}** {year_item['completed']} / {year_item['total']} 事例"
                )
                st.progress(year_item["ratio"])
        else:
            st.info("問題データが登録されていません。")

    with case_col:
        st.markdown("##### 事例別進捗")
        if progress_overview["cases"]:
            for case_item in progress_overview["cases"]:
                st.markdown(
                    f"**{case_item['label']}** {case_item['completed']} / {case_item['total']} 年度"
                )
                st.progress(case_item["ratio"])
        else:
            st.info("問題データが登録されていません。")

    st.divider()

    unique_years = sorted(history_df["年度"].dropna().unique())
    unique_cases = sorted(history_df["事例"].dropna().unique())
    modes = {"practice": "演習", "mock": "模試"}

    filter_col1, filter_col2, filter_col3 = st.columns(3)
    with filter_col1:
        selected_years = st.multiselect("年度で絞り込む", options=unique_years)
    with filter_col2:
        selected_cases = st.multiselect("事例で絞り込む", options=unique_cases)
    with filter_col3:
        selected_modes = st.multiselect("モード", options=list(modes.keys()), format_func=lambda key: modes[key])

    filtered_df = history_df.copy()
    if selected_years:
        filtered_df = filtered_df[filtered_df["年度"].isin(selected_years)]
    if selected_cases:
        filtered_df = filtered_df[filtered_df["事例"].isin(selected_cases)]
    if selected_modes:
        selected_mode_labels = [modes[key] for key in selected_modes]
        filtered_df = filtered_df[filtered_df["モード"].isin(selected_mode_labels)]

    filtered_keyword_records = keyword_records
    if selected_years:
        filtered_keyword_records = [
            record for record in filtered_keyword_records if record["year"] in selected_years
        ]
    if selected_cases:
        filtered_keyword_records = [
            record for record in filtered_keyword_records if record["case_label"] in selected_cases
        ]
    if selected_modes:
        filtered_keyword_records = [
            record for record in filtered_keyword_records if record["mode"] in selected_modes
        ]

    keyword_analysis = _analyze_keyword_records(filtered_keyword_records)

    overview_tab, chart_tab, keyword_tab, detail_tab = st.tabs(
        ["一覧", "グラフ", "キーワード分析", "詳細・エクスポート"]
    )

    with overview_tab:
        display_df = filtered_df.copy()
        display_df["日付"] = display_df["日付"].dt.strftime("%Y-%m-%d %H:%M")
        st.data_editor(
            display_df.drop(columns=["attempt_id"]),
            hide_index=True,
            use_container_width=True,
            disabled=True,
        )
        st.caption("複数条件でフィルタした演習履歴を確認できます。列名をクリックすると並び替えできます。")

    with chart_tab:
        score_history = filtered_df.dropna(subset=["得点", "日付"])
        if score_history.empty:
            st.info("選択した条件に該当する得点推移がありません。")
        else:
            line_chart = (
                alt.Chart(score_history)
                .mark_line(point=True)
                .encode(
                    x="日付:T",
                    y="得点:Q",
                    color="事例:N",
                    tooltip=["日付", "年度", "事例", "得点", "満点", "モード"],
                )
                .properties(height=320)
            )
            st.altair_chart(line_chart, use_container_width=True)

            avg_df = score_history.groupby("事例", as_index=False)["得点"].mean()
            st.subheader("事例別平均点")
            bar_chart = alt.Chart(avg_df).mark_bar().encode(x="事例:N", y="得点:Q")
            st.altair_chart(bar_chart, use_container_width=True)

    with keyword_tab:
        answers_df = keyword_analysis["answers"]
        summary_df = keyword_analysis["summary"]
        recommendations = keyword_analysis["recommendations"]

        if answers_df.empty and summary_df.empty:
            st.info("キーワード採点の記録がまだありません。演習を重ねると分析が表示されます。")
        else:
            if not answers_df.empty:
                scatter_source = answers_df.dropna(subset=["キーワード網羅率", "得点率"])
                if not scatter_source.empty:
                    scatter_chart = (
                        alt.Chart(scatter_source)
                        .mark_circle(size=90, opacity=0.75)
                        .encode(
                            x=alt.X(
                                "キーワード網羅率:Q",
                                title="キーワード網羅率 (%)",
                                scale=alt.Scale(domain=[0, 100]),
                            ),
                            y=alt.Y(
                                "得点率:Q",
                                title="設問得点率 (%)",
                                scale=alt.Scale(domain=[0, 100]),
                            ),
                            color=alt.Color("事例:N"),
                            tooltip=[
                                "年度",
                                "事例",
                                "タイトル",
                                "設問",
                                alt.Tooltip("キーワード網羅率:Q", format=".1f"),
                                alt.Tooltip("得点率:Q", format=".1f"),
                                "不足キーワード表示",
                            ],
                        )
                    )
                    st.subheader("キーワード網羅率と得点率の相関")
                    st.altair_chart(scatter_chart, use_container_width=True)
                    st.caption("左下に位置する設問はキーワード・得点ともに伸びしろがあります。重点的に復習しましょう。")
                else:
                    st.info("スコアとキーワード判定が揃った設問がまだありません。")

            if not summary_df.empty:
                st.markdown("#### 頻出キーワードの達成状況")
                display_summary = summary_df.copy()
                display_summary["達成率(%)"] = display_summary["達成率(%)"].map(
                    lambda v: f"{v:.0f}%"
                )
                st.data_editor(
                    display_summary,
                    hide_index=True,
                    use_container_width=True,
                    disabled=True,
                )
                st.caption("出題頻度が高いキーワードほど上位に表示されます。達成率が低いキーワードは計画的に復習しましょう。")

            if recommendations:
                st.markdown("#### 優先して復習したいテーマ")
                for recommendation in recommendations[:5]:
                    keyword = recommendation["keyword"]
                    hit_rate = recommendation["hit_rate"] * 100
                    attempts = recommendation["attempts"]
                    example = recommendation.get("example")
                    resources = KEYWORD_RESOURCE_MAP.get(keyword, DEFAULT_KEYWORD_RESOURCES)
                    lines = [
                        f"- **{keyword}** — 達成率 {hit_rate:.0f}% / 出題 {attempts}回",
                    ]
                    if example:
                        lines.append(f"    - 出題例: {example}")
                    for resource in resources:
                        lines.append(f"    - [参考資料]({resource['url']}): {resource['label']}")
                    st.markdown("\n".join(lines))

            if not answers_df.empty:
                st.markdown("#### 設問別キーワード判定一覧")
                detail_df = answers_df[
                    [
                        "年度",
                        "事例",
                        "タイトル",
                        "設問",
                        "モード",
                        "キーワード網羅率",
                        "得点率",
                        "含まれたキーワード表示",
                        "不足キーワード表示",
                    ]
                ].copy()
                detail_df["キーワード網羅率"] = detail_df["キーワード網羅率"].map(
                    lambda v: f"{v:.0f}%" if pd.notna(v) else "-"
                )
                detail_df["得点率"] = detail_df["得点率"].map(
                    lambda v: f"{v:.0f}%" if pd.notna(v) else "-"
                )
                st.data_editor(detail_df, hide_index=True, use_container_width=True, disabled=True)
                st.caption("各設問の到達状況と不足キーワードを一覧化しました。学習計画に反映してください。")

    with detail_tab:
        csv_export = filtered_df.copy()
        csv_export["日付"] = csv_export["日付"].dt.strftime("%Y-%m-%d %H:%M:%S")
        csv_bytes = csv_export.drop(columns=["attempt_id"]).to_csv(index=False).encode("utf-8-sig")
        st.download_button(
            "CSVをダウンロード",
            data=csv_bytes,
            file_name="history.csv",
            mime="text/csv",
        )

        recent_history = filtered_df.dropna(subset=["日付"]).sort_values("日付", ascending=False)
        if recent_history.empty:
            st.info("詳細表示できる履歴がありません。フィルタ条件を変更してください。")
            return

        options = list(recent_history.index)
        selected_idx = st.selectbox(
            "詳細を確認する演習",
            options=options,
            format_func=lambda idx: f"{recent_history.loc[idx, '日付'].strftime('%Y-%m-%d %H:%M')} {recent_history.loc[idx, '年度']} {recent_history.loc[idx, '事例']}",
        )
        attempt_id = int(recent_history.loc[selected_idx, "attempt_id"])
        render_attempt_results(attempt_id)


def settings_page(user: Dict) -> None:
    st.title("設定・プラン管理")

    st.write(
        f"**ユーザー名:** {user['name']}\n"
        f"**メールアドレス:** {user['email']}\n"
        f"**契約プラン:** {user['plan']}"
    )

    plan_tab, learning_tab = st.tabs(["プラン管理", "学習設定"])

    with plan_tab:
        st.subheader("プラン一覧")

        plan_features = pd.DataFrame(
            [
                {
                    "プラン": "無料プラン",
                    "月額料金": "¥0",
                    "AI採点": "\u2705 月20回まで",
                    "詳細解説": "\u26aa 最新3回分のみ",
                    "学習レポート": "\u26aa ハイライトのみ",
                },
                {
                    "プラン": "プレミアム",
                    "月額料金": "¥1,480",
                    "AI採点": "\u2b50\ufe0f 無制限",
                    "詳細解説": "\u2b50\ufe0f 全設問を無制限閲覧",
                    "学習レポート": "\u2b50\ufe0f 個別アドバイス付き",
                },
            ]
        )
        st.dataframe(plan_features, use_container_width=True, hide_index=True)

        st.caption(
            "\U0001f4a1 プレミアムプランでは AI 採点の上限が解除され、全ての模擬試験・過去問で詳細解説を好きなだけ閲覧できます。"
        )

        st.subheader("アップグレードのメリット")
        col1, col2 = st.columns(2)
        with col1:
            st.markdown(
                """
                - 🧠 **AI採点の無制限化**: 事例演習の回数を気にせずフィードバックを受けられます。
                - 📊 **詳細な学習レポート**: 記述力の伸びや課題を自動分析し、次に取り組むべきテーマを提案します。
                """
            )
        with col2:
            st.markdown(
                """
                - 📚 **詳細解説の読み放題**: 各設問の模範答案・解説を制限なく確認できます。
                - 🕒 **優先サポート**: 24時間以内のメール返信で学習の悩みをサポートします。
                """
            )

        st.subheader("プラン変更")
        st.write("AI採点の回数制限を拡張し、詳細解説を無制限に閲覧できる有料プランをご用意しています。")

        pricing_col, action_col = st.columns([1.2, 1])
        with pricing_col:
            st.markdown(
                """
                - 💳 **月額: 1,480円 (税込)**
                - 🧾 クレジットカード (Visa / MasterCard / JCB)、デビットカード、主要電子マネーに対応
                - 🔁 いつでも解約可能。更新日まではプレミアム機能を利用できます。
                """
            )
        with action_col:
            if user["plan"] == "free":
                if st.button("有料プランにアップグレードする"):
                    database.update_user_plan(user_id=user["id"], plan="premium")
                    st.session_state.user = dict(database.get_user_by_email(user["email"]))
                    st.success("プレミアムプランに変更しました。")
            else:
                st.info("既にプレミアムプランをご利用中です。")

        st.subheader("サポート")
        st.markdown(
            dedent(
                """
                - お問い合わせ: support@example.com
                - 利用規約: coming soon
                - 退会をご希望の場合はサポートまでご連絡ください。
                """
            ).strip()
        )

    with learning_tab:
        st.subheader("データアップロード")
        st.caption(
            "過去問・与件文・設問文を1つのCSV/Excel/PDFで一括管理できます。テンプレートを確認しながらアップロードしてください。"
        )

        st.markdown("#### テンプレートダウンロード")
        try:
            bundle_bytes = _load_template_bundle_bytes()
        except FileNotFoundError:
            st.warning(
                "テンプレートファイルの一部を読み込めませんでした。リポジトリの data フォルダを確認してください。"
            )
        else:
            st.download_button(
                "テンプレートを一括ダウンロード (ZIP)",
                data=bundle_bytes,
                file_name="templates_bundle.zip",
                mime="application/zip",
                help="CSVとJSONのテンプレートをまとめて取得できます。",
                key="template_bundle_download",
            )
            included = " / ".join(name for name, _ in TEMPLATE_BUNDLE_FILES)
            st.caption(f"含まれるファイル: {included}")

        st.markdown("#### 過去問データ（与件文・設問文を含む）")
        uploaded_file = st.file_uploader(
            "過去問データファイルをアップロード (CSV/Excel/PDF)",
            type=["csv", "xlsx", "xls", "pdf"],
            key="past_exam_uploader",
        )
        st.caption(
            "R6/R5 事例III原紙テンプレートを同梱し、自動分解の精度を高めています。PDFアップロードにも対応しています。"
        )
        try:
            template_bytes = _load_past_exam_template_bytes()
        except FileNotFoundError:
            st.warning("テンプレートファイルを読み込めませんでした。リポジトリの data フォルダを確認してください。")
        else:
            st.download_button(
                "テンプレートCSVをダウンロード",
                data=template_bytes,
                file_name="past_exam_template.csv",
                mime="text/csv",
                help="アップロード用のひな形です。必須列とサンプル設問を含みます。",
                key="past_exam_template_download",
            )
            with st.expander("テンプレートのサンプルを見る", expanded=False):
                preview_df = _load_past_exam_template_preview()
                st.dataframe(preview_df, use_container_width=True, hide_index=True)

        if uploaded_file is not None:
            st.session_state.pending_past_data_upload = {
                "name": uploaded_file.name,
                "data": uploaded_file.getvalue(),
            }

        pending_past = st.session_state.get("pending_past_data_upload")
        if pending_past:
            st.caption(f"選択中のファイル: {pending_past['name']}")
            exec_col, clear_col = st.columns([1, 1])
            with exec_col:
                if st.button(
                    "過去問データを取り込む",
                    key="execute_past_data_upload",
                    type="primary",
                ):
                    success = _handle_past_data_upload(
                        pending_past["data"], pending_past["name"]
                    )
                    if success:
                        st.session_state.pending_past_data_upload = None
            with clear_col:
                if st.button("選択中のファイルをクリア", key="reset_past_data_upload"):
                    st.session_state.pending_past_data_upload = None

        past_df = st.session_state.past_data
        if past_df is not None:
            st.caption(f"読み込み済みのレコード数: {len(past_df)}件")
            st.dataframe(past_df.head(), use_container_width=True)
            case_meta = st.session_state.get("uploaded_case_metadata", {}) or {}
            question_meta = st.session_state.get("uploaded_question_metadata", {}) or {}
            if case_meta:
                summary_rows: List[Dict[str, Any]] = []
                for case_key, meta in case_meta.items():
                    if not isinstance(case_key, str) or "::" not in case_key:
                        continue
                    year_label, case_label = case_key.split("::", 1)
                    question_keys = [
                        key
                        for key in question_meta.keys()
                        if isinstance(key, str)
                        and key.startswith(f"{year_label}::{case_label}::")
                    ]
                    summary_rows.append(
                        {
                            "年度": year_label,
                            "事例": case_label,
                            "ケースタイトル": meta.get("title") or "-",
                            "設問数": len(question_keys),
                            "詳細解説数": sum(
                                1
                                for key in question_keys
                                if question_meta.get(key, {}).get("detailed_explanation")
                            ),
                            "動画リンク数": sum(
                                1
                                for key in question_keys
                                if question_meta.get(key, {}).get("video_url")
                            ),
                            "図解数": sum(
                                1
                                for key in question_keys
                                if question_meta.get(key, {}).get("diagram_path")
                            ),
                        }
                    )
                if summary_rows:
                    summary_df = pd.DataFrame(summary_rows)
                    summary_df["_year_sort"] = summary_df["年度"].map(_year_sort_key)
                    summary_df["_case_sort"] = summary_df["事例"].map(
                        lambda x: CASE_ORDER.index(x)
                        if x in CASE_ORDER
                        else len(CASE_ORDER)
                    )
                    summary_df = summary_df.sort_values(
                        ["_year_sort", "_case_sort"], ascending=[False, True]
                    ).drop(columns=["_year_sort", "_case_sort"])
                    st.dataframe(summary_df, use_container_width=True, hide_index=True)
                    st.caption("年度・事例ごとの登録状況です。詳細解説や動画リンクの有無を確認できます。")
            tables = st.session_state.get("past_data_tables") or []
            if tables:
                with st.expander("抽出された数表", expanded=False):
                    for idx, table in enumerate(tables, start=1):
                        st.markdown(f"**数表 {idx}**")
                        st.dataframe(table, use_container_width=True)
            if st.button("アップロードデータをクリア", key="clear_past_data"):
                st.session_state.past_data = None
                st.session_state.past_data_tables = []
                st.session_state.uploaded_case_metadata = {}
                st.session_state.uploaded_question_metadata = {}
                st.session_state.uploaded_case_contexts = {}
                st.session_state.uploaded_question_texts = {}
                st.info("アップロードデータを削除しました。")
        else:
            st.info("過去問データは未登録です。テンプレートを利用してアップロードしてください。")

        st.markdown("##### 与件文プレビュー")
        contexts = st.session_state.get("uploaded_case_contexts", {}) or {}
        if contexts:
            context_rows = []
            for case_key, text in contexts.items():
                if not isinstance(case_key, str):
                    continue
                parts = case_key.split("::", 1)
                year_label = parts[0]
                case_label = parts[1] if len(parts) > 1 else ""
                normalized_text = str(text or "").strip()
                lines = normalized_text.splitlines()
                first_line = lines[0] if lines else normalized_text
                preview = first_line[:40]
                if normalized_text and len(normalized_text) > 40:
                    preview = preview.rstrip() + "…"
                context_rows.append(
                    {
                        "年度": year_label,
                        "事例": case_label,
                        "文字数": len(str(text)),
                        "冒頭プレビュー": preview,
                    }
                )
            if context_rows:
                context_df = pd.DataFrame(context_rows)
                context_df["_year_sort"] = context_df["年度"].map(
                    lambda x: _year_sort_key(str(x))
                )
                context_df["_case_sort"] = context_df["事例"].map(
                    lambda x: CASE_ORDER.index(x)
                    if x in CASE_ORDER
                    else len(CASE_ORDER)
                )
                context_df = context_df.sort_values(
                    ["_year_sort", "_case_sort", "事例"],
                    ascending=[False, True, True],
                )
                context_df = context_df.drop(columns=["_year_sort", "_case_sort"])
                st.dataframe(context_df, use_container_width=True, hide_index=True)
                st.caption("年度・事例ごとに最新の与件文が登録されています。再アップロードすると同じキーの内容は上書きされます。")
            if st.button("与件文データをクリア", key="clear_case_contexts"):
                st.session_state.uploaded_case_contexts = {}
                st.info("登録済みの与件文データを削除しました。")
        else:
            st.info(
                "登録済みの与件文データはありません。テンプレートの『与件文全体』または『与件文』列を入力すると自動で取り込まれます。"
            )

        st.markdown("##### 設問文プレビュー")
        question_texts = st.session_state.get("uploaded_question_texts", {}) or {}
        if question_texts:
            question_rows = []
            for slot_key, text in question_texts.items():
                if not isinstance(slot_key, str):
                    continue
                parts = slot_key.split("::")
                if len(parts) < 3:
                    continue
                year_label, case_label, question_no = parts[0], parts[1], parts[2]
                if isinstance(text, dict):
                    body_text = text.get("question_text") or text.get("設問文") or ""
                    insight_text = text.get("question_insight") or text.get("設問インサイト") or ""
                    aim_text = text.get("question_aim") or text.get("設問の狙い") or ""
                    output_text = text.get("output_format") or text.get("必要アウトプット形式") or ""
                    solution_text = text.get("solution_prompt") or text.get("定番解法プロンプト") or ""
                else:
                    body_text = text or ""
                    insight_text = ""
                    aim_text = ""
                    output_text = ""
                    solution_text = ""
                normalized_text = str(body_text or "").strip()
                lines = normalized_text.splitlines()
                first_line = lines[0] if lines else normalized_text
                preview = first_line[:40]
                if normalized_text and len(normalized_text) > 40:
                    preview = preview.rstrip() + "…"
                question_rows.append(
                    {
                        "年度": year_label,
                        "事例": case_label,
                        "設問": question_no,
                        "文字数": len(normalized_text),
                        "冒頭プレビュー": preview,
                        "設問インサイト": insight_text or "-",
                        "設問の狙い": aim_text or "-",
                        "アウトプット形式": output_text or "-",
                        "解法プロンプト": solution_text or "-",
                    }
                )
            if question_rows:
                question_df = pd.DataFrame(question_rows)
                question_df["_year_sort"] = question_df["年度"].map(
                    lambda x: _year_sort_key(str(x))
                )
                question_df["_case_sort"] = question_df["事例"].map(
                    lambda x: CASE_ORDER.index(x)
                    if x in CASE_ORDER
                    else len(CASE_ORDER)
                )
                question_df["_question_sort"] = question_df["設問"].map(
                    lambda x: _normalize_question_number(x) or 0
                )
                question_df = question_df.sort_values(
                    ["_year_sort", "_case_sort", "_question_sort"],
                    ascending=[False, True, True],
                )
                question_df = question_df.drop(columns=["_year_sort", "_case_sort", "_question_sort"])
                st.dataframe(question_df, use_container_width=True, hide_index=True)
                st.caption("登録済みの設問文です。年度・事例・設問番号ごとに最新の内容が適用されます。")
            if st.button("設問文データをクリア", key="clear_question_texts"):
                st.session_state.uploaded_question_texts = {}
                st.info("登録済みの設問文データを削除しました。")
        else:
            st.info("登録済みの設問文データはありません。テンプレートの『問題文』『設問の狙い』列などを入力すると自動で反映されます。")

        st.subheader("ワンクリック模範解答スロット")
        st.caption("講師別の模範解答・講評セットを JSON でまとめて登録し、設問ごとにワンクリックで参照できます。")
        slot_file = st.file_uploader(
            "模範解答スロットJSONをアップロード",
            type=["json"],
            key="model_answer_slot_uploader",
            help="年度・事例・設問番号をキーに、講師A/Bと採点観点を登録します。",
        )
        if slot_file is not None:
            st.session_state.pending_model_answer_slot_upload = {
                "name": slot_file.name,
                "data": slot_file.getvalue(),
            }

        pending_slots = st.session_state.get("pending_model_answer_slot_upload")
        if pending_slots:
            st.caption(f"選択中のファイル: {pending_slots['name']}")
            exec_col, clear_col = st.columns([1, 1])
            with exec_col:
                if st.button(
                    "模範解答スロットを登録",
                    key="execute_model_answer_slot_upload",
                    type="primary",
                ):
                    success = _handle_model_answer_slot_upload(
                        pending_slots["data"], pending_slots["name"]
                    )
                    if success:
                        st.session_state.pending_model_answer_slot_upload = None
            with clear_col:
                if st.button(
                    "選択中のファイルをクリア", key="reset_model_answer_slot_upload"
                ):
                    st.session_state.pending_model_answer_slot_upload = None

        slots = st.session_state.get("model_answer_slots", {})
        if slots:
            summary_rows = []
            for slot in sorted(
                slots.values(), key=lambda x: (x["year"], x["case_label"], x["question_number"])
            ):
                scoring = slot.get("scoring", {}) or {}
                points = scoring.get("points") or []
                note = scoring.get("note")
                if points and note:
                    scoring_summary = f"{len(points)}項目 / コメントあり"
                elif points:
                    scoring_summary = f"{len(points)}項目"
                elif note:
                    scoring_summary = "コメントあり"
                else:
                    scoring_summary = "-"
                summary_rows.append(
                    {
                        "年度": slot["year"],
                        "事例": slot["case_label"],
                        "設問": slot["question_number"],
                        "講師A": "○" if slot.get("lecturer_a") else "-",
                        "講師B": "○" if slot.get("lecturer_b") else "-",
                        "採点観点": scoring_summary,
                    }
                )
            st.dataframe(pd.DataFrame(summary_rows), use_container_width=True, hide_index=True)
            st.caption("登録済みスロットの一覧です。再アップロードすると同じキーのデータは上書きされます。")
            if st.button("模範解答スロットをクリア", key="clear_model_answer_slots"):
                st.session_state.model_answer_slots = {}
                st.info("模範解答スロットを削除しました。")
        else:
            st.info("登録済みの模範解答スロットはありません。JSONをアップロードして利用を開始してください。")

        with st.expander("JSONフォーマットのサンプル", expanded=False):
            sample_payload = {
                "entries": [
                    {
                        "year": "令和5年",
                        "case": "事例I",
                        "question": 1,
                        "lecturer_a": {
                            "answer": "模範解答の骨子を入力",
                            "commentary": "講師Aによる講評や書き方のポイントを記載",
                        },
                        "lecturer_b": {
                            "answer": "別の視点の模範解答を入力",
                            "commentary": "講師Bのフィードバックを記載",
                        },
                        "scoring": {
                            "points": ["与件からの課題抽出", "効果・因果の明示"],
                            "note": "評価基準や減点要素をメモできます。",
                        },
                    }
                ]
            }
            st.code(json.dumps(sample_payload, ensure_ascii=False, indent=2), language="json")

        st.subheader("表示テーマ")
        theme_options = [
            "システム設定に合わせる",
            "ライトモード",
            "ダークモード",
        ]
        selected_theme = st.radio(
            "アプリのカラーテーマ",
            options=theme_options,
            index=theme_options.index(st.session_state.ui_theme)
            if st.session_state.ui_theme in theme_options
            else 0,
            help="視認性に合わせてテーマを切り替えできます。",
        )
        if selected_theme != st.session_state.ui_theme:
            st.session_state.ui_theme = selected_theme
            st.success(f"テーマを『{selected_theme}』に変更しました。")


logger = logging.getLogger(__name__)


if __name__ == "__main__":
    database.initialize_database()
    _init_session_state()
    try:
        main_view()
    except Exception:  # pragma: no cover - defensive UI fallback
        logger.exception("Unhandled exception in main_view")
        st.error("現在、システムに不具合が発生しています。時間を置いて再度アクセスしてください。")
        st.caption("お問い合わせ: support@example.com")
