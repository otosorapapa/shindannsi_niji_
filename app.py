from __future__ import annotations

from collections import defaultdict
import copy
from datetime import date as dt_date, datetime, time as dt_time, timedelta
from pathlib import Path
from textwrap import dedent
from typing import Any, Dict, Iterable, List, Optional, Pattern, Set, Tuple
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
from xml.sax.saxutils import escape


st.set_page_config(
    page_title="中小企業診断士二次試験ナビゲーション",
    layout="wide",
    initial_sidebar_state="expanded",
)

import committee_analysis
import database
import mock_exam
import personalized_recommendation
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
    st.session_state.setdefault("_practice_question_styles_injected", False)
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


def _inject_practice_question_styles() -> None:
    if st.session_state.get("_practice_question_styles_injected"):
        return

    st.markdown(
        dedent(
            """
            <style>
            :root {
                --practice-shadow-card: 0 18px 40px rgba(15, 23, 42, 0.08);
                --practice-text-strong: #0f172a;
                --practice-text-muted: #475569;
                --practice-focus-ring: #2563eb;
                --practice-focus-ring-soft: rgba(37, 99, 235, 0.18);
                --practice-chip-bg: rgba(15, 23, 42, 0.06);
                --pastel-mint-bg: #f0fdf4;
                --pastel-mint-border: rgba(34, 197, 94, 0.28);
                --pastel-mint-inner: rgba(34, 197, 94, 0.18);
                --pastel-lemon-bg: #fefce8;
                --pastel-lemon-border: rgba(250, 204, 21, 0.32);
                --pastel-lemon-inner: rgba(250, 204, 21, 0.2);
            }
            .practice-question-block {
                position: relative;
                margin: 0 0 2.6rem;
                scroll-margin-top: 110px;
                transition: box-shadow 0.2s ease, transform 0.2s ease;
            }
            .practice-question-block:last-of-type {
                margin-bottom: 1.8rem;
            }
            .practice-question-block[data-tone="mint"] .practice-question-card {
                --card-bg: var(--pastel-mint-bg);
                --card-border: var(--pastel-mint-border);
                --card-inner: var(--pastel-mint-inner);
            }
            .practice-question-block[data-tone="lemon"] .practice-question-card {
                --card-bg: var(--pastel-lemon-bg);
                --card-border: var(--pastel-lemon-border);
                --card-inner: var(--pastel-lemon-inner);
            }
            .practice-question-block.is-active .practice-question-card {
                border-color: rgba(37, 99, 235, 0.55);
                box-shadow: 0 0 0 3px rgba(37, 99, 235, 0.18), var(--practice-shadow-card);
            }
            .practice-question-block.is-highlighted .practice-question-card {
                animation: practiceCardPulse 2s ease;
            }
            @keyframes practiceCardPulse {
                0% { box-shadow: 0 0 0 0 rgba(37, 99, 235, 0.35), var(--practice-shadow-card); }
                100% { box-shadow: var(--practice-shadow-card); }
            }
            .practice-question-card {
                position: relative;
                padding: 1.8rem 1.95rem 2rem;
                border-radius: 24px;
                background: var(--card-bg, #ffffff);
                border: 1px solid var(--card-border, rgba(148, 163, 184, 0.35));
                box-shadow: var(--practice-shadow-card);
                color: var(--practice-text-strong);
                display: flex;
                flex-direction: column;
                gap: 1.25rem;
                line-height: 1.75;
            }
            .practice-question-card::before {
                content: "";
                position: absolute;
                inset: 10px;
                border-radius: 18px;
                border: 1px solid var(--card-inner, rgba(148, 163, 184, 0.28));
                pointer-events: none;
            }
            .practice-question-card > *:last-child {
                margin-bottom: 0;
            }
            .practice-question-header {
                position: relative;
                display: flex;
                flex-wrap: wrap;
                align-items: flex-start;
                justify-content: space-between;
                gap: 0.85rem 1.2rem;
                z-index: 1;
            }
            .practice-question-header-main {
                display: flex;
                flex-direction: column;
                gap: 0.35rem;
                min-width: 0;
            }
            .practice-question-number {
                display: inline-flex;
                align-items: center;
                justify-content: center;
                padding: 0.25rem 0.75rem;
                border-radius: 999px;
                font-size: 0.82rem;
                font-weight: 700;
                letter-spacing: 0.05em;
                text-transform: uppercase;
                background: rgba(15, 23, 42, 0.08);
                color: var(--practice-text-strong);
            }
            .practice-question-title {
                margin: 0;
                font-size: clamp(1rem, 1.8vw, 1.2rem);
                font-weight: 700;
                color: var(--practice-text-strong);
            }
            .practice-question-header-meta {
                display: flex;
                flex-direction: column;
                align-items: flex-end;
                gap: 0.45rem;
            }
            .practice-question-meta-items {
                display: flex;
                flex-wrap: wrap;
                justify-content: flex-end;
                gap: 0.4rem;
            }
            .practice-question-meta-item {
                display: inline-flex;
                align-items: center;
                padding: 0.28rem 0.65rem;
                border-radius: 999px;
                border: 1px solid rgba(15, 23, 42, 0.15);
                background: rgba(255, 255, 255, 0.85);
                font-size: 0.78rem;
                color: var(--practice-text-muted);
                white-space: nowrap;
            }
            .practice-question-summary {
                margin: 0;
                font-size: 0.95rem;
                color: var(--practice-text-muted);
                z-index: 1;
            }
            .practice-question-summary strong {
                color: var(--practice-text-strong);
            }
            .practice-question-chips {
                display: flex;
                flex-wrap: wrap;
                gap: 0.4rem;
                z-index: 1;
            }
            .practice-question-chip {
                display: inline-flex;
                align-items: center;
                padding: 0.25rem 0.6rem;
                border-radius: 999px;
                font-size: 0.75rem;
                font-weight: 600;
                letter-spacing: 0.02em;
                background: rgba(59, 130, 246, 0.12);
                color: #1d4ed8;
                border: 1px solid rgba(59, 130, 246, 0.28);
            }
            .practice-floating-buttons {
                position: fixed;
                right: 1.5rem;
                bottom: 1.5rem;
                z-index: 1050;
                display: flex;
                flex-direction: column;
                align-items: flex-end;
                gap: 0.75rem;
            }
            .practice-return-button {
                display: inline-flex;
                align-items: center;
                gap: 0.45rem;
                border-radius: 999px;
                font-size: 0.9rem;
                font-weight: 600;
                letter-spacing: 0.02em;
                padding: 0.55rem 1.05rem;
                cursor: pointer;
                min-width: 0;
                transform: translateY(0);
                transition: opacity 0.2s ease, transform 0.2s ease, box-shadow 0.2s ease;
            }
            .practice-return-button:focus-visible {
                outline: 3px solid var(--practice-focus-ring-soft);
                outline-offset: 4px;
            }
            .practice-return-button.is-hidden {
                opacity: 0;
                pointer-events: none;
                transform: translateY(12px);
            }
            .practice-return-button-icon {
                display: inline-flex;
                align-items: center;
                justify-content: center;
            }
            .practice-return-button svg {
                width: 18px;
                height: 18px;
            }
            .practice-return-nav-button {
                border: 1px solid rgba(37, 99, 235, 0.58);
                background: rgba(37, 99, 235, 0.96);
                color: #f8fafc;
                box-shadow: 0 18px 36px rgba(37, 99, 235, 0.28);
            }
            .practice-return-nav-button:hover {
                transform: translateY(-2px);
                box-shadow: 0 20px 36px rgba(37, 99, 235, 0.32);
            }
            .practice-return-button-text {
                white-space: nowrap;
            }
            .practice-return-context-button {
                border: 1px solid rgba(16, 185, 129, 0.55);
                background: rgba(15, 118, 110, 0.95);
                color: #ecfeff;
                box-shadow: 0 18px 32px rgba(13, 148, 136, 0.28);
            }
            .practice-return-context-button:hover {
                transform: translateY(-2px);
                box-shadow: 0 20px 36px rgba(13, 148, 136, 0.32);
            }
            .practice-autosave-caption {
                font-size: 0.78rem;
                letter-spacing: 0.02em;
                color: var(--practice-text-muted);
                margin: 0.45rem 0 0.85rem;
            }
            .practice-question-block .stTextArea textarea {
                border-radius: 16px;
                border: 1px solid rgba(148, 163, 184, 0.5);
                background: rgba(255, 255, 255, 0.96);
                color: var(--practice-text-strong);
                box-shadow: inset 0 2px 6px rgba(15, 23, 42, 0.08);
                transition: border-color 0.15s ease, box-shadow 0.15s ease;
            }
            .practice-question-block .stTextArea textarea:focus-visible {
                border-color: var(--practice-focus-ring);
                box-shadow: 0 0 0 2px var(--practice-focus-ring-soft);
                outline: 2px solid transparent;
                outline-offset: 2px;
            }
            .practice-question-block .stTextArea textarea::placeholder {
                color: rgba(100, 116, 139, 0.7);
            }
            .practice-question-block .stButton > button {
                border-radius: 14px;
                padding: 0.55rem 1.3rem;
                border: 1px solid rgba(148, 163, 184, 0.45);
                background: rgba(248, 250, 252, 0.95);
                color: var(--practice-text-strong);
                font-weight: 600;
                transition: transform 0.15s ease, box-shadow 0.15s ease;
            }
            .practice-question-block .stButton > button:hover {
                transform: translateY(-1px);
                box-shadow: 0 10px 20px rgba(15, 23, 42, 0.12);
            }
            .practice-question-divider {
                height: 1px;
                margin: 1.8rem auto 0;
                max-width: 92%;
                background: linear-gradient(90deg, transparent, rgba(148, 163, 184, 0.45), transparent);
            }
            @media (max-width: 900px) {
                .practice-question-card {
                    padding: 1.5rem 1.35rem 1.7rem;
                    border-radius: 22px;
                }
                .practice-question-card::before {
                    inset: 8px;
                    border-radius: 16px;
                }
                .practice-question-header {
                    flex-direction: column;
                    align-items: stretch;
                }
                .practice-question-header-meta {
                    align-items: stretch;
                }
                .practice-question-meta-items {
                    justify-content: flex-start;
                }
                .practice-floating-buttons {
                    right: 1rem;
                    bottom: 1rem;
                    gap: 0.6rem;
                }
                .practice-return-button {
                    font-size: 0.82rem;
                    padding: 0.5rem 0.95rem;
                }
                .practice-return-button svg {
                    width: 17px;
                    height: 17px;
                }
            }
            @media (prefers-color-scheme: dark) {
                .practice-question-card {
                    background: rgba(17, 24, 39, 0.88);
                    color: #e2e8f0;
                    border-color: rgba(148, 163, 184, 0.35);
                }
                .practice-question-card::before {
                    border-color: rgba(148, 163, 184, 0.3);
                }
                .practice-question-number {
                    background: rgba(148, 163, 184, 0.25);
                    color: #f8fafc;
                }
                .practice-question-meta-item {
                    background: rgba(15, 23, 42, 0.35);
                    border-color: rgba(148, 163, 184, 0.4);
                    color: #e2e8f0;
                }
                .practice-question-summary {
                    color: rgba(226, 232, 240, 0.85);
                }
                .practice-question-chip {
                    background: rgba(59, 130, 246, 0.2);
                    color: #bfdbfe;
                    border-color: rgba(147, 197, 253, 0.45);
                }
                .practice-return-nav-button {
                    background: rgba(59, 130, 246, 0.9);
                    border-color: rgba(96, 165, 250, 0.65);
                    color: #e0f2fe;
                    box-shadow: 0 18px 32px rgba(59, 130, 246, 0.35);
                }
                .practice-return-nav-button:hover {
                    box-shadow: 0 20px 36px rgba(59, 130, 246, 0.4);
                }
                .practice-return-context-button {
                    background: rgba(20, 184, 166, 0.92);
                    border-color: rgba(45, 212, 191, 0.65);
                    color: #ecfeff;
                    box-shadow: 0 18px 32px rgba(20, 184, 166, 0.35);
                }
                .practice-return-context-button:hover {
                    box-shadow: 0 20px 36px rgba(20, 184, 166, 0.4);
                }
                .practice-autosave-caption {
                    color: rgba(226, 232, 240, 0.78);
                }
                .practice-question-block .stTextArea textarea {
                    background: rgba(15, 23, 42, 0.92);
                    color: #f8fafc;
                    border-color: rgba(100, 116, 139, 0.55);
                }
                .practice-question-block .stTextArea textarea:focus-visible {
                    box-shadow: 0 0 0 2px rgba(148, 163, 184, 0.35);
                }
                .practice-question-block .stButton > button {
                    background: rgba(30, 41, 59, 0.92);
                    border-color: rgba(100, 116, 139, 0.45);
                    color: #f8fafc;
                }
            }
            </style>
            """
        ),
        unsafe_allow_html=True,
    )
    st.session_state["_practice_question_styles_injected"] = True


def _practice_tone_for_index(index: Optional[int]) -> str:
    try:
        numeric_index = int(index) if index is not None else 1
    except (TypeError, ValueError):
        numeric_index = 1
    return "mint" if numeric_index % 2 == 1 else "lemon"


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
                border-radius: 20px;
                padding: 1.5rem 1.7rem;
                background: var(--card-surface, #ffffff);
                color: var(--card-text, #0f172a);
                border: 1px solid rgba(148, 163, 184, 0.35);
                box-shadow: var(--practice-shadow-card, 0 18px 32px rgba(15, 23, 42, 0.12));
                display: flex;
                flex-direction: column;
                gap: 0.9rem;
                line-height: 1.7;
                position: relative;
            }
            .question-mini-card::before {
                content: "";
                position: absolute;
                inset: 10px;
                border-radius: 16px;
                border: 1px solid rgba(148, 163, 184, 0.25);
                pointer-events: none;
            }
            .question-mini-card[data-theme="dark"] {
                --card-surface: rgba(17, 24, 39, 0.92);
                --card-text: #e2e8f0;
                border-color: rgba(148, 163, 184, 0.4);
            }
            .question-mini-card[data-theme="auto"] {
                --card-surface: #ffffff;
                --card-text: #0f172a;
            }
            .question-mini-card h4,
            .question-mini-card .practice-question-title {
                margin: 0;
                font-size: clamp(1rem, 1.7vw, 1.18rem);
                font-weight: 700;
                color: inherit;
            }
            .question-mini-card p,
            .question-mini-card .practice-question-summary {
                margin: 0;
                font-size: 0.92rem;
                color: rgba(71, 85, 105, 0.95);
            }
            .question-mini-card[data-theme="dark"] p,
            .question-mini-card[data-theme="dark"] .practice-question-summary {
                color: rgba(226, 232, 240, 0.86);
            }
            .question-mini-card .qm-meta,
            .question-mini-card .practice-question-meta-items {
                display: flex;
                flex-wrap: wrap;
                gap: 0.4rem;
            }
            .question-mini-card .qm-meta span,
            .question-mini-card .practice-question-meta-item {
                display: inline-flex;
                align-items: center;
                padding: 0.28rem 0.6rem;
                border-radius: 999px;
                font-size: 0.78rem;
                border: 1px solid rgba(148, 163, 184, 0.38);
                background: rgba(248, 250, 252, 0.88);
                color: inherit;
            }
            .question-mini-card[data-theme="dark"] .qm-meta span,
            .question-mini-card[data-theme="dark"] .practice-question-meta-item {
                background: rgba(30, 41, 59, 0.65);
                border-color: rgba(148, 163, 184, 0.35);
            }
            .question-mini-card .qm-chips,
            .question-mini-card .practice-question-chips {
                display: flex;
                flex-wrap: wrap;
                gap: 0.3rem;
            }
            .question-mini-card .qm-chip,
            .question-mini-card .practice-question-chip {
                display: inline-flex;
                align-items: center;
                padding: 0.24rem 0.55rem;
                border-radius: 999px;
                font-size: 0.74rem;
                letter-spacing: 0.02em;
                background: rgba(59, 130, 246, 0.12);
                color: #1d4ed8;
                border: 1px solid rgba(59, 130, 246, 0.28);
            }
            .question-mini-card[data-theme="dark"] .qm-chip,
            .question-mini-card[data-theme="dark"] .practice-question-chip {
                background: rgba(59, 130, 246, 0.25);
                color: #bfdbfe;
                border-color: rgba(147, 197, 253, 0.4);
            }
            </style>
            """
        ),
        unsafe_allow_html=True,
    )
    st.session_state["_question_card_styles_injected"] = True


def _inject_question_insight_styles() -> None:
    if st.session_state.get("_question_insight_styles_injected"):
        return

    st.markdown(
        dedent(
            """
            <style>
            .question-insight-card {
                position: relative;
                border-radius: 18px;
                padding: 1.4rem 1.6rem;
                margin: 0.8rem 0 1.3rem;
                background: linear-gradient(135deg, rgba(224, 242, 254, 0.85), rgba(237, 233, 254, 0.92));
                border: 1px solid rgba(148, 163, 184, 0.35);
                box-shadow: 0 18px 32px rgba(15, 23, 42, 0.08);
            }
            .question-insight-card::after {
                content: "";
                position: absolute;
                inset: 10px;
                border-radius: 14px;
                border: 1px dashed rgba(99, 102, 241, 0.35);
                pointer-events: none;
            }
            .question-insight-header {
                display: flex;
                align-items: center;
                gap: 0.75rem;
                margin-bottom: 1rem;
            }
            .question-insight-eyebrow {
                font-size: 0.75rem;
                letter-spacing: 0.12em;
                font-weight: 700;
                color: #4338ca;
                text-transform: uppercase;
            }
            .question-insight-divider {
                flex: 1;
                height: 1px;
                background: linear-gradient(90deg, rgba(59, 130, 246, 0.35), rgba(59, 130, 246, 0));
            }
            .question-insight-body {
                font-size: 0.98rem;
                line-height: 1.8;
                color: #0f172a;
                white-space: pre-wrap;
            }
            </style>
            """
        ),
        unsafe_allow_html=True,
    )
    st.session_state["_question_insight_styles_injected"] = True


def _render_question_insight_block(text: str) -> None:
    if not text:
        return

    _inject_question_insight_styles()
    insight_html = html.escape(text).replace("\n", "<br />")
    st.markdown(
        dedent(
            f"""
            <div class="question-insight-card">
                <div class="question-insight-header">
                    <span class="question-insight-eyebrow">INSIGHT</span>
                    <div class="question-insight-divider"></div>
                </div>
                <div class="question-insight-body">{insight_html}</div>
            </div>
            """
        ),
        unsafe_allow_html=True,
    )


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
    if st.session_state.get("_context_panel_styles_injected_v3"):
        return

    st.markdown(
        dedent(
            """
            <style>
            :root {
                --context-panel-offset: 72px;
            }
            html {
                scroll-behavior: smooth;
            }
            .practice-context-column {
                position: sticky;
                top: var(--context-panel-offset, 72px);
                align-self: flex-start;
                display: flex;
                flex-direction: column;
                min-height: var(
                    --context-column-min-height,
                    calc(100vh - var(--context-panel-offset, 72px) - 16px)
                );
                padding-bottom: 1rem;
            }
            .practice-context-inner {
                display: flex;
                flex-direction: column;
                gap: 1rem;
                flex: 1 1 auto;
                min-height: 0;
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
                padding: 1.25rem;
                line-height: 1.7;
                box-sizing: border-box;
                margin-bottom: 1.5rem;
                display: flex;
                flex-direction: column;
                gap: 0.75rem;
                overflow: hidden;
                transition: box-shadow 0.25s ease, transform 0.25s ease;
            }
            .context-panel.is-highlighted {
                box-shadow: 0 0 0 3px rgba(16, 185, 129, 0.28), 0 24px 48px rgba(13, 148, 136, 0.18);
                transform: translateY(-1px);
            }
            .practice-context-inner > .context-panel {
                flex: 1 1 auto;
                min-height: 0;
            }
            .context-panel-inner {
                display: flex;
                flex-direction: column;
                gap: 0.75rem;
                flex: 1 1 auto;
                min-height: 0;
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
                padding-right: calc(0.85rem + var(--context-scrollbar-compensation, 0px));
                margin-right: calc(-1 * var(--context-scrollbar-compensation, 0px));
                scrollbar-gutter: stable both-edges;
                scrollbar-width: thin;
                flex: 1 1 auto;
                min-height: 0;
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
            .context-search-control {
                margin-bottom: 0.85rem;
                padding: 0.75rem 0.85rem;
                border-radius: 0.75rem;
                border: 1px solid #e5e7eb;
                background: rgba(248, 250, 252, 0.9);
            }
            .context-search-control [data-testid="stTextInput"] {
                margin-bottom: 0.35rem;
            }
            .context-search-control [data-testid="stTextInput"] > label {
                font-weight: 600;
                color: #1f2937;
                font-size: 0.85rem;
                margin-bottom: 0.35rem;
            }
            .context-search-control [data-testid="stTextInput"] input {
                border-radius: 0.5rem;
                border: 1px solid #cbd5f5;
                padding: 0.45rem 0.75rem;
                background: #ffffff;
                box-shadow: inset 0 1px 2px rgba(15, 23, 42, 0.04);
            }
            .context-search-control [data-testid="stCaptionContainer"] {
                margin: 0.35rem 0 0;
                color: #475569;
            }
            @media (min-width: 901px) {
                .practice-context-inner {
                    max-height: calc(100vh - var(--context-panel-offset, 72px) - 16px);
                    overflow: visible;
                }
                .practice-context-inner > .context-panel {
                    position: sticky;
                    top: var(--context-panel-offset, 72px);
                    max-height: calc(100vh - var(--context-panel-offset, 72px) - 16px);
                    box-shadow: 0 18px 36px rgba(15, 23, 42, 0.12);
                }
                .context-panel-inner {
                    flex: 1 1 auto;
                    min-height: 0;
                }
                .context-panel-scroll {
                    max-height: none;
                }
            }
            @media (max-width: 900px) {
                .practice-context-column {
                    position: static;
                    top: auto;
                    min-height: 0;
                    max-height: none;
                    overflow: visible;
                    display: block;
                    padding-bottom: 0;
                }
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
    st.session_state["_context_panel_styles_injected_v3"] = True


def _inject_context_panel_behavior() -> None:
    st.markdown(
        dedent(
            """
            <script>
            (() => {
                const setupContextPanel = () => {
                    const doc = window.document;
                    const panel = doc.getElementById('context-panel');
                    const scrollArea = panel ? panel.querySelector('.context-panel-scroll') : null;
                    const column = panel ? panel.closest('.practice-context-column') : null;
                    const mainColumn = doc.querySelector('.practice-main-column');
                    const triggers = Array.from(doc.querySelectorAll('.context-panel-trigger'));
                    let lastTrigger = null;

                    if (panel && !panel.hasAttribute('aria-hidden')) {
                        panel.setAttribute('aria-hidden', 'true');
                    }

                    const getPanelOffset = () => {
                        const rootStyles = window.getComputedStyle(doc.documentElement);
                        const rawOffset = rootStyles.getPropertyValue('--context-panel-offset');
                        const parsed = parseFloat(rawOffset);
                        return Number.isFinite(parsed) ? parsed : 72;
                    };

                    const updateScrollbarCompensation = () => {
                        if (!panel || !scrollArea) {
                            return;
                        }
                        const scrollbarWidth = Math.max(
                            0,
                            scrollArea.offsetWidth - scrollArea.clientWidth
                        );
                        panel.style.setProperty(
                            '--context-scrollbar-compensation',
                            `${scrollbarWidth}px`
                        );
                    };

                    const syncColumnMinHeight = (mq) => {
                        if (!column) {
                            return;
                        }
                        column.style.removeProperty('--context-column-min-height');
                        const media = mq || window.matchMedia('(max-width: 900px)');
                        if (media.matches) {
                            return;
                        }
                        const offset = getPanelOffset();
                        const viewportHeight = Math.max(0, window.innerHeight - offset - 16);
                        let mainHeight = 0;
                        if (mainColumn) {
                            const rect = mainColumn.getBoundingClientRect();
                            mainHeight = rect.height;
                        }
                        const target = Math.max(viewportHeight, mainHeight);
                        if (target > 0) {
                            column.style.setProperty(
                                '--context-column-min-height',
                                `${Math.ceil(target)}px`
                            );
                        }
                    };

                    const setAriaExpanded = (open) => {
                        triggers.forEach((button) => {
                            button.setAttribute('aria-expanded', open ? 'true' : 'false');
                        });
                    };

                    const setOpen = (open, options = {}) => {
                        const {
                            suppressFocus = false,
                            skipReturnFocus = false,
                            trigger = null,
                            returnFocusTo = null,
                        } = options;

                        if (!doc.body) {
                            return;
                        }

                        if (trigger) {
                            lastTrigger = trigger;
                        }

                        doc.body.classList.toggle('context-panel-open', open);
                        setAriaExpanded(open);

                        if (panel) {
                            panel.setAttribute('aria-hidden', open ? 'false' : 'true');
                        }

                        if (open) {
                            window.requestAnimationFrame(updateScrollbarCompensation);
                        } else {
                            updateScrollbarCompensation();
                        }

                        if (open && scrollArea && !suppressFocus) {
                            scrollArea.focus({ preventScroll: false });
                        }

                        if (!open && !skipReturnFocus) {
                            const focusTarget = returnFocusTo || lastTrigger || triggers[0];
                            if (focusTarget) {
                                focusTarget.focus();
                            }
                        }
                    };

                    const handleTrigger = (button) => {
                        setOpen(true, { trigger: button });
                    };

                    const handleClose = (options = {}) => {
                        setOpen(false, options);
                    };

                    if (triggers.length) {
                        triggers.forEach((button) => {
                            if (button.dataset.bound === 'true') {
                                return;
                            }
                            button.dataset.bound = 'true';
                            button.setAttribute('aria-expanded', 'false');
                        });
                    }

                    if (doc.body && doc.body.dataset.contextPanelDelegated !== 'true') {
                        doc.body.dataset.contextPanelDelegated = 'true';

                        doc.addEventListener(
                            'click',
                            (event) => {
                                const triggerButton = event.target.closest('.context-panel-trigger');
                                if (triggerButton) {
                                    event.preventDefault();
                                    handleTrigger(triggerButton);
                                    return;
                                }

                                const closeButton = event.target.closest('.context-panel-close');
                                if (closeButton) {
                                    event.preventDefault();
                                    handleClose();
                                    return;
                                }

                                const backdrop = event.target.closest('.context-panel-backdrop');
                                if (backdrop && event.target === backdrop) {
                                    handleClose({ suppressFocus: true, skipReturnFocus: true });
                                }
                            },
                            { passive: false }
                        );

                        doc.addEventListener(
                            'keydown',
                            (event) => {
                                const triggerButton = event.target.closest('.context-panel-trigger');
                                if (triggerButton && (event.key === 'Enter' || event.key === ' ')) {
                                    event.preventDefault();
                                    handleTrigger(triggerButton);
                                    return;
                                }

                                const closeButton = event.target.closest('.context-panel-close');
                                if (closeButton && (event.key === 'Enter' || event.key === ' ')) {
                                    event.preventDefault();
                                    handleClose();
                                }
                            },
                            { passive: false }
                        );
                    }

                    const mediaQuery = window.matchMedia('(max-width: 900px)');
                    const syncForViewport = (mq) => {
                        if (!panel) {
                            return;
                        }
                        if (mq.matches) {
                            handleClose({ suppressFocus: true, skipReturnFocus: true });
                        } else {
                            panel.setAttribute('aria-hidden', 'false');
                            setAriaExpanded(true);
                            if (doc.body) {
                                doc.body.classList.remove('context-panel-open');
                            }
                        }
                        syncColumnMinHeight(mq);
                    };

                    syncForViewport(mediaQuery);
                    if (mediaQuery.addEventListener) {
                        mediaQuery.addEventListener('change', syncForViewport);
                    } else if (mediaQuery.addListener) {
                        mediaQuery.addListener(syncForViewport);
                    }

                    updateScrollbarCompensation();
                    syncColumnMinHeight(mediaQuery);

                    if (scrollArea && typeof ResizeObserver !== 'undefined') {
                        if (!scrollArea.__contextPanelResizeObserver) {
                            scrollArea.__contextPanelResizeObserver = new ResizeObserver(
                                updateScrollbarCompensation
                            );
                            scrollArea.__contextPanelResizeObserver.observe(scrollArea);
                        }
                    }

                    if (mainColumn && typeof ResizeObserver !== 'undefined') {
                        if (!mainColumn.__contextColumnResizeObserver) {
                            mainColumn.__contextColumnResizeObserver = new ResizeObserver(() => {
                                syncColumnMinHeight(mediaQuery);
                            });
                            mainColumn.__contextColumnResizeObserver.observe(mainColumn);
                        }
                    }

                    if (doc.body && !doc.body.dataset.contextPanelResizeBound) {
                        doc.body.dataset.contextPanelResizeBound = 'true';
                        window.addEventListener(
                            'resize',
                            () => {
                                updateScrollbarCompensation();
                                syncColumnMinHeight(mediaQuery);
                            },
                            {
                                passive: true,
                            }
                        );
                    }

                    if (doc.body && !doc.body.dataset.contextPanelEscapeBound) {
                        doc.body.dataset.contextPanelEscapeBound = 'true';
                        doc.addEventListener('keydown', (event) => {
                            if (event.key === 'Escape') {
                                handleClose({ suppressFocus: true });
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


def _inject_practice_navigation_styles() -> None:
    if st.session_state.get("_practice_nav_styles_injected"):
        return

    st.markdown(
        dedent(
            """
            <style>
            .practice-tab-wrapper {
                position: sticky;
                top: calc(env(safe-area-inset-top, 0px) + 0px);
                z-index: 32;
                padding: 0.25rem 0 0.75rem;
                margin-bottom: -0.25rem;
                background: linear-gradient(180deg, rgba(248, 250, 252, 0.95), rgba(248, 250, 252, 0));
                backdrop-filter: blur(4px);
            }
            .practice-question-tabs {
                display: flex;
                align-items: center;
                width: 100%;
                padding: 0.5rem 0.85rem;
                border-radius: 999px;
                border: 1px solid rgba(148, 163, 184, 0.35);
                background: rgba(255, 255, 255, 0.92);
                box-shadow: 0 10px 26px rgba(15, 23, 42, 0.12);
            }
            .practice-tab-track {
                list-style: none;
                display: flex;
                gap: 0.5rem;
                padding: 0;
                margin: 0;
                width: 100%;
                overflow-x: auto;
                scrollbar-width: thin;
            }
            .practice-tab-track::-webkit-scrollbar {
                height: 6px;
            }
            .practice-tab-track::-webkit-scrollbar-thumb {
                background: rgba(148, 163, 184, 0.55);
                border-radius: 999px;
            }
            .practice-tab-track::-webkit-scrollbar-track {
                background: transparent;
            }
            .practice-tab-item {
                flex: 0 0 auto;
            }
            .practice-tab-link {
                display: inline-flex;
                align-items: center;
                justify-content: center;
                min-width: 96px;
                padding: 0.5rem 0.95rem;
                border-radius: 999px;
                border: 1px solid transparent;
                font-weight: 600;
                font-size: 0.92rem;
                color: #1e293b;
                background: rgba(241, 245, 249, 0.9);
                text-decoration: none;
                transition: background 0.2s ease, color 0.2s ease, box-shadow 0.2s ease, border-color 0.2s ease;
            }
            .practice-tab-link:hover {
                background: rgba(219, 234, 254, 0.9);
                border-color: rgba(59, 130, 246, 0.35);
                box-shadow: 0 8px 18px rgba(37, 99, 235, 0.18);
            }
            .practice-tab-link:focus-visible {
                outline: 3px solid var(--practice-focus-ring-soft);
                outline-offset: 2px;
            }
            .practice-tab-link[aria-selected="true"],
            .practice-tab-link.is-active {
                background: linear-gradient(135deg, #2563eb, #1d4ed8);
                color: #ffffff;
                box-shadow: 0 0 0 3px rgba(37, 99, 235, 0.25);
            }
            .practice-main-column {
                display: flex;
                flex-direction: column;
                gap: 1.6rem;
            }
            .practice-toc {
                position: sticky;
                top: calc(var(--context-panel-offset, 72px) + 12px);
                display: flex;
                flex-direction: column;
                gap: 0.6rem;
                padding: 0.75rem 1rem 0.9rem;
                border-radius: 18px;
                border: 1px solid rgba(148, 163, 184, 0.35);
                background: rgba(248, 250, 252, 0.95);
                box-shadow: 0 12px 24px rgba(15, 23, 42, 0.08);
                backdrop-filter: blur(6px);
                z-index: 12;
            }
            .practice-main-column > .practice-toc:first-child {
                margin-top: 0.6rem;
            }
            .practice-toc-label {
                font-size: 0.75rem;
                letter-spacing: 0.12em;
                font-weight: 700;
                text-transform: uppercase;
                color: #2563eb;
            }
            .practice-toc-track {
                list-style: none;
                display: flex;
                gap: 0.55rem;
                padding: 0;
                margin: 0;
                overflow-x: auto;
                scrollbar-width: thin;
            }
            .practice-toc-track::-webkit-scrollbar {
                height: 6px;
            }
            .practice-toc-track::-webkit-scrollbar-thumb {
                background: rgba(148, 163, 184, 0.6);
                border-radius: 999px;
            }
            .practice-toc-track::-webkit-scrollbar-track {
                background: transparent;
            }
            .practice-toc-item {
                flex: 0 0 auto;
            }
            .practice-toc-link {
                display: flex;
                flex-direction: column;
                gap: 0.25rem;
                min-width: 128px;
                text-decoration: none;
                border-radius: 999px;
                border: 1px solid rgba(148, 163, 184, 0.38);
                background: #ffffff;
                color: #0f172a;
                padding: 0.55rem 1rem;
                box-shadow: 0 6px 12px rgba(15, 23, 42, 0.06);
                transition: background 0.15s ease, color 0.15s ease, border-color 0.15s ease, box-shadow 0.15s ease;
            }
            .practice-toc-link:hover {
                border-color: rgba(37, 99, 235, 0.4);
                box-shadow: 0 10px 20px rgba(37, 99, 235, 0.12);
            }
            .practice-toc-link:focus-visible {
                outline: 3px solid var(--practice-focus-ring-soft);
                outline-offset: 3px;
            }
            .practice-toc-link[aria-current="location"] {
                background: linear-gradient(135deg, #2563eb, #1d4ed8);
                color: #ffffff;
                border-color: rgba(37, 99, 235, 0.8);
                box-shadow: 0 0 0 3px rgba(37, 99, 235, 0.25);
                font-weight: 700;
            }
            .practice-toc-link[aria-current="location"] .practice-toc-index {
                color: rgba(255, 255, 255, 0.92);
            }
            .practice-toc-index {
                font-size: 0.75rem;
                font-weight: 700;
                letter-spacing: 0.08em;
                text-transform: uppercase;
                color: #1d4ed8;
            }
            .practice-toc-text {
                font-size: 0.8rem;
                line-height: 1.3;
                color: #1f2937;
            }
            .practice-toc-link[aria-current="location"] .practice-toc-text {
                color: rgba(255, 255, 255, 0.92);
            }
            .practice-stepper {
                position: sticky;
                bottom: 1.5rem;
                margin: 2.2rem 0 1.9rem;
                display: flex;
                gap: 0.75rem;
                align-items: center;
                justify-content: space-between;
                padding: 0.75rem 1rem;
                border-radius: 18px;
                border: 1px solid rgba(148, 163, 184, 0.38);
                background: rgba(248, 250, 252, 0.92);
                box-shadow: 0 14px 36px rgba(15, 23, 42, 0.12);
                backdrop-filter: blur(12px);
                z-index: 14;
            }
            .practice-stepper-button {
                flex: 1 1 0;
                display: flex;
                flex-direction: column;
                align-items: flex-start;
                gap: 0.2rem;
                border: none;
                border-radius: 12px;
                padding: 0.65rem 1rem;
                background: rgba(255, 255, 255, 0.85);
                color: #0f172a;
                font-weight: 600;
                font-size: 0.92rem;
                cursor: pointer;
                transition: background 0.15s ease, box-shadow 0.15s ease, transform 0.15s ease;
            }
            .practice-stepper-button:hover:not(:disabled) {
                background: rgba(219, 234, 254, 0.65);
                box-shadow: 0 8px 20px rgba(59, 130, 246, 0.18);
                transform: translateY(-1px);
            }
            .practice-stepper-button:focus-visible {
                outline: 3px solid var(--practice-focus-ring-soft);
                outline-offset: 2px;
            }
            .practice-stepper-button:disabled,
            .practice-stepper-button[aria-disabled="true"] {
                opacity: 0.5;
                cursor: not-allowed;
                box-shadow: none;
                transform: none;
            }
            .practice-stepper-main {
                font-size: 0.82rem;
                letter-spacing: 0.06em;
                text-transform: uppercase;
                color: #1d4ed8;
            }
            .practice-stepper-sub {
                font-size: 0.86rem;
                color: #0f172a;
            }
            @media (max-width: 1024px) {
                .practice-tab-wrapper {
                    top: 0;
                }
                .practice-toc {
                    position: static;
                    box-shadow: none;
                }
            }
            @media (max-width: 768px) {
                .practice-tab-wrapper {
                    padding: 0.35rem 0 0.65rem;
                    background: rgba(15, 23, 42, 0.04);
                }
                .practice-question-tabs {
                    padding: 0.45rem 0.65rem;
                    border-radius: 18px;
                }
                .practice-tab-link {
                    min-width: 84px;
                    font-size: 0.85rem;
                    padding: 0.45rem 0.75rem;
                }
                .practice-toc {
                    padding: 0.65rem 0.75rem 0.85rem;
                }
                .practice-stepper {
                    position: fixed;
                    left: 0;
                    right: 0;
                    bottom: 0;
                    margin: 0;
                    border-radius: 0;
                    padding: 0.65rem 1rem calc(0.65rem + env(safe-area-inset-bottom, 0px));
                    box-shadow: 0 -12px 24px rgba(15, 23, 42, 0.22);
                    border-top: 1px solid rgba(148, 163, 184, 0.35);
                }
                .practice-stepper-button {
                    align-items: center;
                    text-align: center;
                    background: rgba(255, 255, 255, 0.92);
                }
                .practice-stepper-sub {
                    font-size: 0.8rem;
                }
            }
            @media (prefers-color-scheme: dark) {
                .practice-tab-wrapper {
                    background: linear-gradient(180deg, rgba(17, 24, 39, 0.9), rgba(17, 24, 39, 0));
                }
                .practice-question-tabs {
                    background: rgba(30, 41, 59, 0.94);
                    border-color: rgba(148, 163, 184, 0.35);
                    box-shadow: 0 16px 36px rgba(2, 6, 23, 0.55);
                }
                .practice-tab-link {
                    background: rgba(51, 65, 85, 0.85);
                    color: #e2e8f0;
                }
                .practice-tab-link:hover {
                    background: rgba(96, 165, 250, 0.25);
                    border-color: rgba(59, 130, 246, 0.45);
                    box-shadow: 0 10px 24px rgba(37, 99, 235, 0.28);
                }
                .practice-toc {
                    background: rgba(17, 24, 39, 0.9);
                    border-color: rgba(148, 163, 184, 0.35);
                    box-shadow: 0 12px 32px rgba(2, 6, 23, 0.55);
                }
                .practice-toc-link {
                    background: rgba(30, 41, 59, 0.92);
                    color: #e2e8f0;
                    border-color: rgba(148, 163, 184, 0.4);
                }
                .practice-toc-index {
                    color: #bfdbfe;
                }
                .practice-toc-text {
                    color: rgba(226, 232, 240, 0.85);
                }
                .practice-stepper {
                    background: rgba(15, 23, 42, 0.9);
                    border-color: rgba(148, 163, 184, 0.35);
                    box-shadow: 0 16px 40px rgba(2, 6, 23, 0.6);
                }
                .practice-stepper-button {
                    background: rgba(30, 41, 59, 0.88);
                    color: #e2e8f0;
                }
                .practice-stepper-main {
                    color: #93c5fd;
                }
                .practice-stepper-sub {
                    color: #e2e8f0;
                }
            }
            </style>
            """
        ),
        unsafe_allow_html=True,
    )
    st.session_state["_practice_nav_styles_injected"] = True


def _inject_practice_navigation_script() -> None:
    st.markdown(
        dedent(
            """
            <script>
            (() => {
                const win = window.parent || window;
                const doc = win.document;
                if (!doc) {
                    return;
                }

                const sections = Array.from(doc.querySelectorAll('.practice-question-block'));
                const navLinks = Array.from(
                    doc.querySelectorAll('.practice-toc-link, .practice-tab-link')
                );
                const quickNav = doc.getElementById('practice-quick-nav');
                const returnButton = doc.querySelector('.practice-return-nav-button');
                const contextButton = doc.querySelector('.practice-return-context-button');
                const contextPanel = doc.getElementById('context-panel');

                const attachContextButton = () => {
                    if (!contextButton) {
                        return;
                    }
                    if (!contextPanel) {
                        contextButton.classList.add('is-hidden');
                        return;
                    }
                    contextButton.classList.remove('is-hidden');
                    if (contextButton.dataset.enhanced === '1') {
                        return;
                    }

                    const triggers = Array.from(doc.querySelectorAll('.context-panel-trigger'));
                    const scrollArea = contextPanel.querySelector('.context-panel-scroll');
                    const mediaQuery = win.matchMedia('(max-width: 900px)');

                    const highlightPanel = () => {
                        contextPanel.classList.add('is-highlighted');
                        win.setTimeout(() => contextPanel.classList.remove('is-highlighted'), 1600);
                    };

                    contextButton.dataset.enhanced = '1';
                    contextButton.addEventListener('click', (event) => {
                        event.preventDefault();
                        if (!contextPanel) {
                            return;
                        }
                        if (mediaQuery.matches && triggers.length) {
                            const trigger =
                                triggers.find((button) => button.offsetParent !== null) || triggers[0];
                            if (trigger) {
                                trigger.click();
                                win.setTimeout(() => {
                                    if (scrollArea) {
                                        scrollArea.scrollTo({ top: 0, behavior: 'smooth' });
                                        scrollArea.focus({ preventScroll: true });
                                    }
                                    highlightPanel();
                                }, 220);
                            }
                            return;
                        }
                        contextPanel.scrollIntoView({ behavior: 'smooth', block: 'start' });
                        if (scrollArea) {
                            scrollArea.scrollTo({ top: 0, behavior: 'smooth' });
                        }
                        highlightPanel();
                    });

                    const syncVisibility = () => {
                        if (!doc.contains(contextPanel)) {
                            contextButton.classList.add('is-hidden');
                        } else {
                            contextButton.classList.remove('is-hidden');
                        }
                    };

                    syncVisibility();

                    if (mediaQuery.addEventListener) {
                        mediaQuery.addEventListener('change', syncVisibility);
                    } else if (mediaQuery.addListener) {
                        mediaQuery.addListener(syncVisibility);
                    }
                };

                attachContextButton();

                if (!sections.length || !navLinks.length) {
                    return;
                }

                const stepper = doc.querySelector('.practice-stepper');
                const prevButton = stepper ? stepper.querySelector('[data-step="prev"]') : null;
                const nextButton = stepper ? stepper.querySelector('[data-step="next"]') : null;

                if (win.__practiceNavObserver) {
                    win.__practiceNavObserver.disconnect();
                }

                const sectionAnchors = sections.map((section) => {
                    const explicit = section.getAttribute('data-anchor-id');
                    if (explicit) {
                        return explicit;
                    }
                    const marker = section.querySelector('.practice-question-anchor');
                    return marker ? marker.id : '';
                });

                const sectionLabels = sections.map((section, index) => {
                    const label = section.getAttribute('data-label');
                    if (label) {
                        return label;
                    }
                    const numberEl = section.querySelector('.practice-question-number');
                    if (numberEl && numberEl.textContent.trim()) {
                        return numberEl.textContent.trim();
                    }
                    return `設問${index + 1}`;
                });

                const sectionMap = new Map();
                sections.forEach((section, index) => {
                    const anchor = sectionAnchors[index];
                    if (anchor) {
                        sectionMap.set(anchor, { section, index });
                    }
                });

                let activeAnchor = sectionAnchors[0] || '';

                const highlightSection = (anchor) => {
                    const data = sectionMap.get(anchor);
                    if (!data) {
                        return;
                    }
                    const { section } = data;
                    section.classList.add('is-highlighted');
                    win.setTimeout(() => section.classList.remove('is-highlighted'), 2000);
                };

                const updateStepper = () => {
                    if (!stepper) {
                        return;
                    }
                    const currentIndex = sectionAnchors.indexOf(activeAnchor);
                    const setButton = (button, targetIndex, prefix) => {
                        if (!button) {
                            return;
                        }
                        if (targetIndex < 0 || targetIndex >= sectionAnchors.length || !sectionAnchors[targetIndex]) {
                            button.dataset.anchor = '';
                            button.disabled = true;
                            button.setAttribute('aria-disabled', 'true');
                            const sub = button.querySelector('.practice-stepper-sub');
                            if (sub) {
                                sub.textContent = '';
                            }
                            button.setAttribute('aria-label', prefix);
                            return;
                        }
                        const anchor = sectionAnchors[targetIndex];
                        const label = sectionLabels[targetIndex] || `設問${targetIndex + 1}`;
                        button.dataset.anchor = anchor;
                        button.disabled = false;
                        button.setAttribute('aria-disabled', 'false');
                        const sub = button.querySelector('.practice-stepper-sub');
                        if (sub) {
                            sub.textContent = label;
                        }
                        button.setAttribute('aria-label', `${prefix}（${label}）`);
                    };
                    setButton(prevButton, currentIndex - 1, '前の設問');
                    setButton(nextButton, currentIndex + 1, '次の設問');
                };

                const setActive = (anchor, options = {}) => {
                    if (!anchor) {
                        return;
                    }
                    const changed = anchor !== activeAnchor;
                    activeAnchor = anchor;
                    navLinks.forEach((link) => {
                        const isActive = link.dataset.anchor === anchor;
                        if (isActive) {
                            link.setAttribute('aria-current', 'location');
                            link.classList.add('is-active');
                            if (options.scrollNav) {
                                link.scrollIntoView({ block: 'nearest', inline: 'center', behavior: 'smooth' });
                            }
                        } else {
                            link.removeAttribute('aria-current');
                            link.classList.remove('is-active');
                        }
                        if (link.classList.contains('practice-tab-link')) {
                            link.setAttribute('aria-selected', isActive ? 'true' : 'false');
                            link.setAttribute('tabindex', isActive ? '0' : '-1');
                        }
                    });
                    sections.forEach((section, index) => {
                        section.classList.toggle('is-active', sectionAnchors[index] === anchor);
                    });
                    if (changed || options.forceUpdate) {
                        updateStepper();
                    }
                };

                const scrollToAnchor = (anchor, emphasize = false) => {
                    if (!anchor) {
                        return;
                    }
                    const target = doc.getElementById(anchor);
                    if (!target) {
                        return;
                    }
                    target.scrollIntoView({ behavior: 'smooth', block: 'start' });
                    if (history.replaceState) {
                        const nextUrl = new URL(win.location);
                        nextUrl.hash = anchor;
                        history.replaceState(null, '', nextUrl.toString());
                    }
                    if (emphasize) {
                        highlightSection(anchor);
                    }
                    win.requestAnimationFrame(() => setActive(anchor, { scrollNav: true, forceUpdate: true }));
                };

                navLinks.forEach((link) => {
                    if (link.dataset.enhanced === '1') {
                        return;
                    }
                    link.dataset.enhanced = '1';
                    link.addEventListener('click', (event) => {
                        const anchor = link.dataset.anchor;
                        if (!anchor) {
                            return;
                        }
                        event.preventDefault();
                        scrollToAnchor(anchor, true);
                    });
                });

                [prevButton, nextButton].forEach((button) => {
                    if (!button || button.dataset.enhanced === '1') {
                        return;
                    }
                    button.dataset.enhanced = '1';
                    button.addEventListener('click', (event) => {
                        const anchor = button.dataset.anchor;
                        if (!anchor) {
                            return;
                        }
                        event.preventDefault();
                        scrollToAnchor(anchor, true);
                    });
                });

                const attachReturnButton = () => {
                    if (!quickNav || !returnButton) {
                        return;
                    }
                    const updateVisibility = () => {
                        const rect = quickNav.getBoundingClientRect();
                        if (rect.top >= 80) {
                            returnButton.classList.add('is-hidden');
                        } else {
                            returnButton.classList.remove('is-hidden');
                        }
                    };
                    if (returnButton.dataset.enhanced !== '1') {
                        returnButton.dataset.enhanced = '1';
                        returnButton.addEventListener('click', (event) => {
                            event.preventDefault();
                            quickNav.scrollIntoView({ behavior: 'smooth', block: 'start' });
                        });
                        win.addEventListener('scroll', updateVisibility, { passive: true });
                        win.addEventListener('resize', updateVisibility);
                    }
                    updateVisibility();
                };

                attachReturnButton();

                if ('IntersectionObserver' in win) {
                    const observer = new IntersectionObserver(
                        (entries) => {
                            const candidates = entries
                                .filter((entry) => entry.isIntersecting)
                                .sort((a, b) => b.intersectionRatio - a.intersectionRatio);
                            if (!candidates.length) {
                                return;
                            }
                            const targetSection = candidates[0].target;
                            const index = sections.indexOf(targetSection);
                            const anchor = sectionAnchors[index];
                            if (anchor) {
                                setActive(anchor, { forceUpdate: true });
                            }
                        },
                        { rootMargin: '-45% 0px -45% 0px', threshold: [0.25, 0.5, 0.7] }
                    );
                    sections.forEach((section) => observer.observe(section));
                    win.__practiceNavObserver = observer;
                }

                setActive(activeAnchor || sectionAnchors[0] || '', { forceUpdate: true });
                updateStepper();

                win.addEventListener('hashchange', () => {
                    const anchor = win.location.hash.replace('#', '');
                    if (anchor && sectionMap.has(anchor)) {
                        setActive(anchor, { scrollNav: true, forceUpdate: true });
                    }
                });
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


def _compile_context_search_pattern(query: Optional[str]) -> Optional[Pattern[str]]:
    if query is None:
        return None

    normalized = str(query).replace("\u3000", " ").strip()
    if not normalized:
        return None

    parts = [re.escape(part) for part in re.split(r"\s+", normalized) if part]
    if not parts:
        return None

    return re.compile("|".join(parts), re.IGNORECASE)


def _highlight_context_line(
    text: str, pattern: Optional[Pattern[str]]
) -> Tuple[str, int]:
    if not text:
        return "", 0

    if not pattern:
        return html.escape(text), 0

    segments: List[str] = []
    match_count = 0
    last_index = 0

    for match in pattern.finditer(text):
        start, end = match.span()
        if start == end:
            continue

        if start > last_index:
            segments.append(html.escape(text[last_index:start]))

        segments.append(
            f'<mark class="context-search-hit">{html.escape(match.group(0))}</mark>'
        )
        match_count += 1
        last_index = end

    segments.append(html.escape(text[last_index:]))

    return "".join(segments), match_count


def _render_problem_context_block(
    context_text: str, search_query: Optional[str] = None
) -> int:
    normalized = _normalize_text_block(context_text)
    if not normalized:
        return 0

    paragraphs: List[str] = []
    for raw_block in normalized.replace("\r\n", "\n").replace("\r", "\n").split("\n\n"):
        paragraph = raw_block.strip()
        if paragraph:
            paragraphs.append(paragraph)

    if not paragraphs:
        return 0

    if len(paragraphs) == 1:
        paragraphs = _split_long_japanese_paragraph(paragraphs[0])

    blocks: List[str] = []
    search_pattern = _compile_context_search_pattern(search_query)
    total_matches = 0
    for paragraph in paragraphs:
        line_fragments: List[str] = []
        for raw_line in paragraph.split("\n"):
            stripped_line = raw_line.strip()
            if not stripped_line:
                continue

            highlighted_line, matches = _highlight_context_line(
                stripped_line, search_pattern
            )
            total_matches += matches
            line_fragments.append(highlighted_line)

        if line_fragments:
            blocks.append(f"<p>{'<br/>'.join(line_fragments)}</p>")

    if not blocks:
        return total_matches

    element_id = f"problem-context-{uuid.uuid4().hex}"
    toolbar_id = f"{element_id}-toolbar"
    total_lines = sum(block.count("<br/>") + 1 for block in blocks)
    estimated_height = max(620, min(1200, 260 + total_lines * 30))

    highlight_html = dedent(
        f"""
        <div class="problem-context-root">
            <div class="context-toolbar" id="{toolbar_id}">
                <div class="toolbar-actions">
                    <button type="button" class="toolbar-button toggle" data-action="highlight" data-target="{element_id}" aria-pressed="false" data-default-color="gold">
                        選択範囲にマーカー
                    </button>
                    <div class="marker-palette" role="group" aria-label="マーカー色">
                        <button type="button" class="marker-color selected" data-action="set-color" data-color="gold" aria-label="ゴールドマーカー"></button>
                        <button type="button" class="marker-color" data-action="set-color" data-color="violet" aria-label="バイオレットマーカー"></button>
                        <button type="button" class="marker-color" data-action="set-color" data-color="cerulean" aria-label="セルリアンマーカー"></button>
                        <button type="button" class="marker-color" data-action="set-color" data-color="teal" aria-label="ティールマーカー"></button>
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
                background: linear-gradient(135deg, rgba(59, 130, 246, 0.18), rgba(37, 99, 235, 0.22));
                color: #1f2937;
                border: none;
                border-radius: 999px;
                padding: 0.35rem 0.95rem;
                font-size: 0.82rem;
                font-weight: 600;
                cursor: pointer;
                box-shadow: inset 0 0 0 1px rgba(37, 99, 235, 0.25);
                transition: transform 120ms ease, box-shadow 120ms ease;
            }}
            .toolbar-button.toggle.active {{
                box-shadow: inset 0 0 0 2px rgba(37, 99, 235, 0.38), 0 6px 14px rgba(37, 99, 235, 0.22);
                transform: translateY(-1px);
            }}
            .toolbar-button:hover {{
                transform: translateY(-1px);
                box-shadow: inset 0 0 0 1px rgba(37, 99, 235, 0.32), 0 6px 12px rgba(37, 99, 235, 0.2);
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
            .marker-color[data-color="gold"] {{
                color: #f5c04e;
            }}
            .marker-color[data-color="violet"] {{
                color: #b286f6;
            }}
            .marker-color[data-color="cerulean"] {{
                color: #64b4eb;
            }}
            .marker-color[data-color="teal"] {{
                color: #4cc0a4;
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
                box-shadow: 0 0 0 1px rgba(37, 99, 235, 0.08);
                background: linear-gradient(transparent 40%, rgba(99, 102, 241, 0.18) 40%);
            }}
            .problem-context-block mark.fluorescent-marker.color-gold {{
                background: linear-gradient(transparent 40%, rgba(245, 192, 78, 0.95) 40%);
                box-shadow: 0 0 0 1px rgba(180, 128, 20, 0.18);
            }}
            .problem-context-block mark.fluorescent-marker.color-violet {{
                background: linear-gradient(transparent 40%, rgba(178, 134, 246, 0.92) 40%);
                box-shadow: 0 0 0 1px rgba(109, 71, 187, 0.22);
            }}
            .problem-context-block mark.fluorescent-marker.color-cerulean {{
                background: linear-gradient(transparent 40%, rgba(100, 180, 235, 0.92) 40%);
                box-shadow: 0 0 0 1px rgba(26, 112, 158, 0.2);
            }}
            .problem-context-block mark.fluorescent-marker.color-teal {{
                background: linear-gradient(transparent 40%, rgba(76, 192, 164, 0.9) 40%);
                box-shadow: 0 0 0 1px rgba(22, 109, 96, 0.2);
            }}
            .problem-context-block mark.context-search-hit {{
                padding: 0 0.1rem;
                border-radius: 0.2rem;
                background: linear-gradient(transparent 45%, rgba(129, 140, 248, 0.65) 45%);
                box-shadow: 0 0 0 1px rgba(99, 102, 241, 0.2);
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
                let activeColor = (highlightButton && highlightButton.dataset.defaultColor) || (colorButtons[0] && colorButtons[0].dataset.color) || "gold";
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
                            const nextColor = button.dataset.color || "gold";
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

    return total_matches


def _render_question_overview_card(
    question: Dict[str, Any],
    *,
    case_label: Optional[str] = None,
    source_label: Optional[str] = None,
    anchor_id: Optional[str] = None,
    header_id: Optional[str] = None,
) -> None:
    if not question:
        return

    _inject_question_card_styles()
    theme = _resolve_question_card_theme()
    prompt_text = _normalize_text_block(
        question.get("prompt") or question.get("設問見出し") or ""
    )
    if not prompt_text:
        prompt_text = "設問タイトル未設定"
    prompt = html.escape(prompt_text)

    order = question.get("order") or question.get("設問番号")
    try:
        numeric_order = int(order) if order is not None else None
    except (TypeError, ValueError):
        numeric_order = None
    order_label = (
        f"設問{numeric_order}"
        if numeric_order is not None
        else f"設問{order}" if order is not None else "設問"
    )

    limit = question.get("character_limit") or question.get("制限字数")
    if isinstance(limit, float) and float(limit).is_integer():
        limit = int(limit)
    max_score = question.get("max_score") or question.get("配点")
    if isinstance(max_score, float) and float(max_score).is_integer():
        max_score = int(max_score)

    meta_items: List[str] = []
    if limit and not pd.isna(limit):
        meta_items.append(f"制限 {int(limit)}字")
    if max_score is not None and not pd.isna(max_score):
        meta_items.append(f"配点 {max_score}点")
    if source_label:
        meta_items.append(str(source_label))

    question_for_aim = dict(question)
    if not question_for_aim.get("prompt") and question_for_aim.get("問題文"):
        first_line = str(question_for_aim["問題文"]).splitlines()[0].strip()
        if first_line:
            question_for_aim["prompt"] = first_line
    aim_text = question.get("aim") or _infer_question_aim(question_for_aim)
    aim_html = ""
    if aim_text:
        aim_html = html.escape(aim_text).replace("\n", "<br>")

    frames = CASE_FRAME_SHORTCUTS.get(case_label or question.get("case_label") or "", [])
    frame_labels = [frame.get("label") for frame in frames[:4] if frame.get("label")]

    meta_html = "".join(
        f"<span class=\"practice-question-meta-item\">{html.escape(str(item))}</span>"
        for item in meta_items
        if item
    )
    chips_html = "".join(
        f"<span class=\"practice-question-chip\">{html.escape(label)}</span>"
        for label in frame_labels
    )

    header_attributes = f' id="{html.escape(header_id)}"' if header_id else ""

    st.markdown(
        dedent(
            f"""
            <div class=\"question-mini-card practice-question-card\" data-theme=\"{theme}\">
                <header class=\"practice-question-header\"{header_attributes}>
                    <div class=\"practice-question-header-main\">
                        <span class=\"practice-question-number\">{html.escape(order_label)}</span>
                        <h3 class=\"practice-question-title\">{prompt}</h3>
                    </div>
                    <div class=\"practice-question-header-meta\">
                        <div class=\"practice-question-meta-items\">{meta_html}</div>
                    </div>
                </header>
                {f'<p class="practice-question-summary">{aim_html}</p>' if aim_html else ''}
                {f'<div class="practice-question-chips">{chips_html}</div>' if chips_html else ''}
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
    with st.expander("設問趣旨カード（ヒント集）", expanded=False):
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

    with st.expander("頻出フレーム（参考）", expanded=False):
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

    # 添付図解の表示は現在無効化しているため、diagram_path が指定されていても描画しない

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
            .mobile-bottom-nav {
                display: none;
            }
            @media (max-width: 960px) {
                section[data-testid="stSidebar"] {
                    display: none !important;
                }
                [data-testid="stAppViewContainer"] > .main {
                    padding-left: 0 !important;
                }
                .block-container {
                    padding: 1rem 1rem 5.5rem;
                    max-width: 100%;
                }
                .dashboard-grid {
                    display: flex;
                    flex-direction: column;
                    gap: 1.25rem;
                }
                .dashboard-toc {
                    flex-wrap: wrap;
                    gap: 0.65rem;
                }
                .dashboard-toc__link {
                    flex: 1 1 calc(50% - 0.65rem);
                    text-align: center;
                }
                .dashboard-card {
                    padding: 1rem 1.05rem 1.1rem;
                }
                .kpi-tiles,
                .metric-grid {
                    grid-template-columns: 1fr;
                }
                .mobile-bottom-nav {
                    display: block;
                    position: fixed;
                    left: 0;
                    right: 0;
                    bottom: 0;
                    z-index: 1200;
                    padding: 0.5rem 0.75rem calc(env(safe-area-inset-bottom, 0px) + 0.5rem);
                    background: rgba(255, 255, 255, 0.94);
                    box-shadow: 0 -6px 20px rgba(15, 23, 42, 0.12);
                    border-top: 1px solid rgba(148, 163, 184, 0.35);
                    backdrop-filter: blur(12px);
                }
                .mobile-bottom-nav [role="radiogroup"] {
                    display: flex;
                    justify-content: space-between;
                    align-items: stretch;
                    gap: 0.25rem;
                }
                .mobile-bottom-nav label[data-baseweb="radio"] {
                    flex: 1 1 0;
                }
                .mobile-bottom-nav label[data-baseweb="radio"] > div:first-child {
                    display: none;
                }
                .mobile-bottom-nav label[data-baseweb="radio"] > div:last-child {
                    border-radius: 14px;
                    border: 1px solid transparent;
                    padding: 0.45rem 0.35rem 0.4rem;
                    font-size: 0.78rem;
                    font-weight: 600;
                    text-align: center;
                    color: var(--text-muted);
                    background: rgba(248, 250, 252, 0.9);
                    transition: border-color 160ms ease, color 160ms ease, background 160ms ease;
                }
                .mobile-bottom-nav label[data-baseweb="radio"] > input:checked + div {
                    border-color: rgba(37, 99, 235, 0.45);
                    color: var(--brand-strong);
                    background: rgba(219, 234, 254, 0.9);
                    box-shadow: 0 6px 14px rgba(37, 99, 235, 0.18);
                }
            }
            @media (min-width: 961px) {
                .mobile-bottom-nav {
                    display: none !important;
                }
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

    mobile_nav_key = "mobile_navigation"

    def _sync_mobile_nav_to_sidebar() -> None:
        selection = st.session_state.get(mobile_nav_key)
        if selection in navigation_items:
            st.session_state[navigation_key] = selection
            st.session_state.page = selection

    current_selection = st.session_state[navigation_key]
    if st.session_state.get(mobile_nav_key) != current_selection:
        st.session_state[mobile_nav_key] = current_selection

    with st.container():
        st.markdown(
            "<div class=\"mobile-bottom-nav\" role=\"navigation\" aria-label=\"主要メニュー\">",
            unsafe_allow_html=True,
        )
        st.radio(
            "主要メニュー",  # ラベルはスクリーンリーダー向けに保持
            nav_labels,
            key=mobile_nav_key,
            horizontal=True,
            label_visibility="collapsed",
            on_change=_sync_mobile_nav_to_sidebar,
        )
        st.markdown("</div>", unsafe_allow_html=True)

    page = st.session_state[navigation_key]
    st.session_state.page = page
    navigation_items[page](user)


def _inject_dashboard_styles() -> None:
    if st.session_state.get("_dashboard_styles_injected"):
        return

    st.markdown(
        dedent(
            """
            <style>
            :root {
                --dashboard-max-width: min(1320px, 96vw);
                --grid-gap: clamp(1rem, 2vw, 1.75rem);
                --pastel-blue: #e8f1ff;
                --pastel-green: #e5f7ed;
                --pastel-yellow: #fff6da;
                --pastel-pink: #ffe9f3;
                --brand: #2563eb;
                --brand-strong: #1d4ed8;
                --text-body: #1f2937;
                --text-muted: #4b5563;
                --border-soft: rgba(148, 163, 184, 0.4);
                --border-strong: rgba(71, 85, 105, 0.6);
                --shadow-card: 0 18px 38px rgba(15, 23, 42, 0.12);
            }
            [data-testid="stAppViewContainer"] {
                background: linear-gradient(180deg, #fdfdfc 0%, #f7f9ff 48%, #ffffff 100%);
            }
            .block-container {
                padding: 1.25rem 1.8rem 3rem;
                max-width: var(--dashboard-max-width);
            }
            .dashboard-toc {
                display: flex;
                gap: 0.75rem;
                flex-wrap: wrap;
                align-items: center;
                margin: 1.5rem 0 2rem;
            }
            .dashboard-toc__link {
                display: inline-flex;
                align-items: center;
                gap: 0.35rem;
                border-radius: 999px;
                padding: 0.45rem 0.95rem;
                font-size: 0.88rem;
                font-weight: 600;
                background: rgba(37, 99, 235, 0.08);
                color: var(--brand-strong);
                border: 1px solid rgba(37, 99, 235, 0.18);
                transition: background 200ms ease, border-color 200ms ease, box-shadow 200ms ease;
            }
            .dashboard-toc__link[aria-current="location"],
            .dashboard-toc__link:hover {
                background: rgba(37, 99, 235, 0.18);
                border-color: rgba(37, 99, 235, 0.35);
            }
            .dashboard-toc__link:focus-visible,
            .insight-pill:focus-visible,
            .kpi-tile button:focus-visible,
            .insight-banner__toggle:focus-visible,
            .timeline-filter__clear:focus-visible {
                outline: none;
                box-shadow: 0 0 0 3px rgba(37, 99, 235, 0.35);
            }
            .dashboard-grid {
                display: grid;
                grid-template-columns: repeat(12, minmax(0, 1fr));
                gap: var(--grid-gap);
                width: 100%;
            }
            .dashboard-lane {
                grid-column: 1 / -1;
                display: flex;
                flex-direction: column;
                gap: 1.1rem;
            }
            .dashboard-lane__header {
                display: flex;
                flex-direction: column;
                gap: 0.15rem;
            }
            .dashboard-lane__title {
                font-size: clamp(1.15rem, 1.6vw, 1.4rem);
                font-weight: 700;
                color: var(--text-body);
                margin: 0;
            }
            .dashboard-lane__subtitle {
                font-size: 0.95rem;
                color: var(--text-muted);
                margin: 0;
            }
            .dashboard-card {
                border-radius: 20px;
                padding: clamp(1rem, 1.6vw, 1.35rem) clamp(1.05rem, 1.8vw, 1.6rem);
                background: #ffffff;
                border: 1px solid rgba(148, 163, 184, 0.35);
                box-shadow: var(--shadow-card);
                position: relative;
                overflow: hidden;
            }
            .dashboard-card::after {
                content: "";
                position: absolute;
                inset: 0;
                border-radius: inherit;
                border: 1px solid rgba(255, 255, 255, 0.45);
                pointer-events: none;
            }
            .dashboard-card.card--tone-blue {
                background: linear-gradient(180deg, rgba(232, 241, 255, 0.95), rgba(255, 255, 255, 0.95));
            }
            .dashboard-card.card--tone-green {
                background: linear-gradient(180deg, rgba(229, 247, 237, 0.95), rgba(255, 255, 255, 0.95));
            }
            .dashboard-card.card--tone-yellow {
                background: linear-gradient(180deg, rgba(255, 246, 218, 0.98), rgba(255, 255, 255, 0.95));
            }
            .dashboard-card.card--tone-pink {
                background: linear-gradient(180deg, rgba(255, 233, 243, 0.98), rgba(255, 255, 255, 0.95));
            }
            .dashboard-card:focus-within {
                box-shadow: 0 0 0 2px rgba(37, 99, 235, 0.32), var(--shadow-card);
            }
            .kpi-tiles {
                display: grid;
                grid-template-columns: repeat(auto-fit, minmax(230px, 1fr));
                gap: clamp(1rem, 1.8vw, 1.5rem);
            }
            .kpi-tile {
                position: relative;
                border-radius: 18px;
                padding: 1.2rem 1.35rem 1.1rem;
                border: 1px solid rgba(148, 163, 184, 0.38);
                background: var(--tile-background, #ffffff);
                box-shadow: 0 12px 24px rgba(15, 23, 42, 0.1);
                display: flex;
                flex-direction: column;
                gap: 0.65rem;
            }
            .kpi-tile[data-tone="blue"] {
                --tile-background: var(--pastel-blue);
            }
            .kpi-tile[data-tone="green"] {
                --tile-background: var(--pastel-green);
            }
            .kpi-tile[data-tone="pink"] {
                --tile-background: var(--pastel-pink);
            }
            .kpi-tile__label {
                font-size: 0.95rem;
                font-weight: 600;
                color: var(--text-muted);
                margin: 0;
                letter-spacing: 0.02em;
            }
            .kpi-tile__value {
                font-size: clamp(2.1rem, 3vw, 2.6rem);
                font-weight: 700;
                margin: 0;
                color: #111827;
            }
            .kpi-tile__meta {
                font-size: 0.9rem;
                color: var(--text-muted);
                margin: 0;
            }
            .progress-bar {
                display: flex;
                flex-direction: column;
                gap: 0.35rem;
            }
            .progress-bar__label {
                font-size: 0.85rem;
                font-weight: 600;
                color: var(--text-muted);
            }
            .progress-bar__track {
                position: relative;
                height: 11px;
                border-radius: 999px;
                background: rgba(148, 163, 184, 0.35);
                overflow: hidden;
            }
            .progress-bar__fill {
                position: absolute;
                inset: 0;
                width: var(--progress, 0%);
                border-radius: inherit;
                background: linear-gradient(90deg, rgba(37, 99, 235, 0.85), rgba(59, 130, 246, 0.85));
                transition: width 600ms ease;
            }
            .progress-bar__value {
                font-size: 0.85rem;
                color: var(--text-body);
            }
            .progress-bar[data-tone="green"] .progress-bar__fill {
                background: linear-gradient(90deg, rgba(34, 197, 94, 0.85), rgba(22, 163, 74, 0.9));
            }
            .progress-bar[data-tone="yellow"] .progress-bar__fill {
                background: linear-gradient(90deg, rgba(234, 179, 8, 0.85), rgba(217, 119, 6, 0.9));
            }
            .metric-grid {
                display: grid;
                grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
                gap: 1rem;
                margin-top: 1rem;
            }
            .metric-chip {
                border-radius: 16px;
                padding: 0.95rem 1.1rem;
                border: 1px solid rgba(148, 163, 184, 0.32);
                background: rgba(255, 255, 255, 0.92);
                box-shadow: 0 8px 16px rgba(15, 23, 42, 0.08);
            }
            .metric-chip__label {
                font-size: 0.78rem;
                text-transform: uppercase;
                letter-spacing: 0.08em;
                color: var(--text-muted);
                margin-bottom: 0.4rem;
            }
            .metric-chip__value {
                font-size: 1.4rem;
                font-weight: 700;
                margin: 0;
            }
            .metric-chip__desc {
                margin: 0.35rem 0 0;
                font-size: 0.85rem;
                color: var(--text-muted);
            }
            .achievement-timeline {
                position: relative;
                padding-left: 1.5rem;
                margin: 0;
                list-style: none;
            }
            .achievement-timeline::before {
                content: "";
                position: absolute;
                left: 0.6rem;
                top: 0;
                bottom: 0;
                width: 2px;
                background: rgba(148, 163, 184, 0.55);
            }
            .achievement-timeline__item {
                position: relative;
                padding: 0 0 1.4rem 0;
            }
            .achievement-timeline__item:last-child {
                padding-bottom: 0;
            }
            .achievement-timeline__item::before {
                content: "";
                position: absolute;
                left: -1rem;
                top: 0.35rem;
                width: 12px;
                height: 12px;
                border-radius: 50%;
                background: #ffffff;
                border: 2px solid var(--brand-strong);
                box-shadow: 0 0 0 2px rgba(37, 99, 235, 0.18);
            }
            .achievement-timeline__time {
                font-size: 0.82rem;
                color: var(--text-muted);
                margin-bottom: 0.15rem;
            }
            .achievement-timeline__title {
                margin: 0;
                font-weight: 600;
                color: var(--text-body);
            }
            .achievement-timeline__meta {
                margin: 0.25rem 0 0;
                font-size: 0.85rem;
                color: var(--text-muted);
            }
            .timeline-filter {
                display: flex;
                justify-content: space-between;
                align-items: center;
                gap: 1rem;
                margin-bottom: 0.85rem;
            }
            .timeline-filter__label {
                font-size: 0.85rem;
                color: var(--text-muted);
            }
            .timeline-filter__actions {
                display: flex;
                gap: 0.5rem;
                flex-wrap: wrap;
            }
            .timeline-filter__clear {
                border-radius: 999px;
                border: 1px solid rgba(37, 99, 235, 0.25);
                background: transparent;
                padding: 0.3rem 0.75rem;
                font-size: 0.8rem;
                font-weight: 600;
                color: var(--brand-strong);
                cursor: pointer;
                transition: background 200ms ease, border-color 200ms ease;
            }
            .timeline-filter__clear:hover {
                background: rgba(37, 99, 235, 0.12);
                border-color: rgba(37, 99, 235, 0.4);
            }
            .insight-pill {
                border-radius: 999px;
                border: 1px solid rgba(71, 85, 105, 0.28);
                background: rgba(148, 163, 184, 0.12);
                padding: 0.4rem 0.85rem;
                font-size: 0.82rem;
                font-weight: 600;
                color: var(--text-body);
                cursor: pointer;
                transition: background 200ms ease, border-color 200ms ease, transform 150ms ease;
            }
            .insight-pill[data-strength="strong"] {
                background: rgba(34, 197, 94, 0.16);
                border-color: rgba(22, 163, 74, 0.35);
                color: #166534;
            }
            .insight-pill[data-strength="watch"] {
                background: rgba(234, 179, 8, 0.18);
                border-color: rgba(202, 138, 4, 0.38);
                color: #92400e;
            }
            .insight-pill[aria-pressed="true"] {
                transform: translateY(-1px);
                box-shadow: 0 10px 18px rgba(37, 99, 235, 0.18);
                background: rgba(37, 99, 235, 0.18);
                border-color: rgba(37, 99, 235, 0.45);
                color: var(--brand-strong);
            }
            .insight-banner {
                border-radius: 16px;
                border: 1px solid rgba(37, 99, 235, 0.3);
                background: linear-gradient(180deg, rgba(232, 241, 255, 0.92), rgba(255, 255, 255, 0.95));
                padding: 0.85rem 1rem;
                box-shadow: 0 12px 24px rgba(37, 99, 235, 0.12);
            }
            .insight-banner__summary {
                display: flex;
                align-items: center;
                gap: 0.55rem;
                font-weight: 600;
                color: var(--brand-strong);
            }
            .insight-banner__content {
                margin-top: 0.65rem;
                font-size: 0.9rem;
                color: var(--text-muted);
            }
            .insight-grid {
                display: grid;
                grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
                gap: 1rem;
            }
            .insight-card {
                display: grid;
                grid-template-columns: auto 1fr;
                gap: 0.8rem;
                align-items: center;
            }
            .insight-icon {
                display: inline-flex;
                align-items: center;
                justify-content: center;
                width: 54px;
                height: 54px;
                border-radius: 16px;
                background: linear-gradient(135deg, rgba(30, 64, 175, 0.16), rgba(30, 64, 175, 0.3));
                color: #1e3a8a;
                box-shadow: 0 10px 20px rgba(30, 64, 175, 0.18);
            }
            .insight-icon[data-accent="teal"] {
                background: linear-gradient(135deg, rgba(13, 148, 136, 0.16), rgba(13, 148, 136, 0.3));
                color: #0f766e;
                box-shadow: 0 10px 20px rgba(15, 118, 110, 0.18);
            }
            .insight-icon[data-accent="slate"] {
                background: linear-gradient(135deg, rgba(51, 65, 85, 0.16), rgba(51, 65, 85, 0.28));
                color: #1f2937;
                box-shadow: 0 10px 20px rgba(30, 41, 59, 0.18);
            }
            .insight-icon svg {
                width: 26px;
                height: 26px;
            }
            .insight-copy {
                display: flex;
                flex-direction: column;
                gap: 0.15rem;
            }
            .insight-title {
                margin: 0;
                font-size: 0.82rem;
                color: var(--text-muted);
                font-weight: 600;
            }
            .insight-value {
                margin: 0;
                font-size: 1.35rem;
                font-weight: 700;
                color: var(--text-body);
            }
            .insight-desc {
                margin: 0;
                font-size: 0.85rem;
                color: var(--text-muted);
            }
            .heatmap-legend {
                display: flex;
                align-items: center;
                gap: 0.75rem;
                margin-top: 1rem;
                font-size: 0.85rem;
                color: var(--text-muted);
                flex-wrap: wrap;
            }
            .heatmap-legend__swatch {
                width: 84px;
                height: 12px;
                border-radius: 999px;
                background: linear-gradient(90deg, rgba(219, 234, 254, 1) 0%, rgba(37, 99, 235, 1) 100%);
                border: 1px solid rgba(37, 99, 235, 0.35);
            }
            .heatmap-highlight {
                display: grid;
                gap: 0.6rem;
                margin-top: 1rem;
                font-size: 0.9rem;
                color: var(--text-muted);
            }
            .section-highlight {
                animation: sectionGlow 2s ease;
            }
            @keyframes sectionGlow {
                0% {
                    box-shadow: 0 0 0 0 rgba(37, 99, 235, 0.0);
                }
                35% {
                    box-shadow: 0 0 0 6px rgba(37, 99, 235, 0.18);
                }
                100% {
                    box-shadow: 0 0 0 0 rgba(37, 99, 235, 0.0);
                }
            }
            .dashboard-lane[data-section-id].is-active {
                outline: 2px solid rgba(37, 99, 235, 0.35);
                outline-offset: 4px;
                transition: outline 200ms ease;
            }
            [data-testid="stDataFrame"] table,
            [data-testid="stDataFrame"] tbody,
            [data-testid="stDataFrame"] th,
            [data-testid="stDataFrame"] td {
                font-size: 0.9rem;
            }
            [data-testid="stDataFrame"] table {
                border-color: rgba(148, 163, 184, 0.4);
            }
            @media (min-width: 1120px) {
                .dashboard-lane--analysis {
                    grid-column: 1 / span 7;
                }
                .dashboard-lane--insight {
                    grid-column: 8 / span 5;
                }
            }
            @media (max-width: 900px) {
                .dashboard-toc {
                    justify-content: flex-start;
                }
                .dashboard-card {
                    padding: 1rem 1.1rem 1.2rem;
                }
                .achievement-timeline::before {
                    left: 0.45rem;
                }
                .achievement-timeline__item::before {
                    left: -1.15rem;
                }
            }
            </style>
            <script>
            (function () {
                if (window.__dashboardEnhancements) return;
                window.__dashboardEnhancements = true;
                const root = document;
                const navLinks = Array.from(root.querySelectorAll('.dashboard-toc__link'));
                const sections = Array.from(root.querySelectorAll('[data-section-id]'));
                const highlight = (sectionId) => {
                    navLinks.forEach((link) => {
                        const target = link.getAttribute('data-target');
                        const isCurrent = target === sectionId;
                        link.setAttribute('aria-current', isCurrent ? 'location' : 'false');
                    });
                    sections.forEach((section) => {
                        const isTarget = section.getAttribute('data-section-id') === sectionId;
                        if (isTarget) {
                            section.classList.add('section-highlight');
                            setTimeout(() => section.classList.remove('section-highlight'), 2000);
                        }
                    });
                };
                navLinks.forEach((link) => {
                    link.addEventListener('click', (event) => {
                        const href = link.getAttribute('href');
                        if (!href || !href.startsWith('#')) return;
                        event.preventDefault();
                        const targetId = href.slice(1);
                        const target = root.getElementById(targetId);
                        if (!target) return;
                        target.scrollIntoView({ behavior: 'smooth', block: 'start' });
                        history.replaceState(null, '', '#' + targetId);
                        highlight(targetId);
                    });
                });
                if ('IntersectionObserver' in window) {
                    const observer = new IntersectionObserver(
                        (entries) => {
                            entries
                                .filter((entry) => entry.isIntersecting)
                                .forEach((entry) => {
                                    const sectionId = entry.target.getAttribute('data-section-id');
                                    navLinks.forEach((link) => {
                                        const isCurrent = link.getAttribute('data-target') === sectionId;
                                        link.setAttribute('aria-current', isCurrent ? 'location' : 'false');
                                    });
                                    sections.forEach((section) => {
                                        section.classList.toggle(
                                            'is-active',
                                            section.getAttribute('data-section-id') === sectionId
                                        );
                                    });
                                });
                        },
                        { threshold: 0.4 }
                    );
                    sections.forEach((section) => observer.observe(section));
                }
                const timelineItems = Array.from(root.querySelectorAll('.achievement-timeline__item'));
                const applyTimelineFilter = (activeCase) => {
                    timelineItems.forEach((item) => {
                        const caseKey = item.getAttribute('data-case');
                        const visible = !activeCase || caseKey === activeCase;
                        item.style.display = visible ? '' : 'none';
                    });
                };
                const pills = Array.from(root.querySelectorAll('.insight-pill'));
                pills.forEach((pill) => {
                    pill.addEventListener('click', () => {
                        const alreadyActive = pill.getAttribute('aria-pressed') === 'true';
                        pills.forEach((other) => other.setAttribute('aria-pressed', 'false'));
                        if (alreadyActive) {
                            pill.setAttribute('aria-pressed', 'false');
                            applyTimelineFilter('');
                            return;
                        }
                        pill.setAttribute('aria-pressed', 'true');
                        applyTimelineFilter(pill.getAttribute('data-case'));
                    });
                });
                const clearButton = root.querySelector('.timeline-filter__clear');
                if (clearButton) {
                    clearButton.addEventListener('click', () => {
                        pills.forEach((pill) => pill.setAttribute('aria-pressed', 'false'));
                        applyTimelineFilter('');
                    });
                }
                root.querySelectorAll('[data-banner-storage]').forEach((details) => {
                    const storageKey = details.getAttribute('data-banner-storage');
                    if (!storageKey || !('localStorage' in window)) return;
                    const stored = window.localStorage.getItem(storageKey);
                    if (stored === 'closed') {
                        details.removeAttribute('open');
                    }
                    details.addEventListener('toggle', () => {
                        if (details.open) {
                            window.localStorage.setItem(storageKey, 'open');
                        } else {
                            window.localStorage.setItem(storageKey, 'closed');
                        }
                    });
                });
            })();
            </script>
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


def _get_attempt_timestamp(value):
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value)
        except ValueError:
            return None
    return None


def _build_dashboard_timeline_events(attempts: List[Dict]) -> List[Dict[str, str]]:
    events: List[Dict[str, str]] = []
    for attempt in sorted(
        attempts,
        key=lambda item: (
            _get_attempt_timestamp(item.get("submitted_at"))
            or _get_attempt_timestamp(item.get("created_at"))
            or datetime.min
        ),
        reverse=True,
    ):
        timestamp = _get_attempt_timestamp(attempt.get("submitted_at"))
        if not timestamp:
            timestamp = _get_attempt_timestamp(attempt.get("created_at"))
        date_label = _format_datetime_label(timestamp or attempt.get("submitted_at"))
        case_label = attempt.get("case_label") or "未分類"
        year_label = attempt.get("year") or ""
        mode = "模試" if attempt.get("mode") == "mock" else "演習"
        score = float(attempt.get("total_score") or 0)
        max_score = float(attempt.get("total_max_score") or 0)
        ratio = (score / max_score * 100) if max_score else 0.0
        case_key = (case_label or "case").replace(" ", "").replace("　", "")
        events.append(
            {
                "date": date_label,
                "title": f"{year_label} {case_label}".strip(),
                "meta": f"{mode} / {score:.0f}点 / {max_score:.0f}点 ({ratio:.0f}%)" if max_score else f"{mode} / {score:.0f}点",
                "case_key": case_key or "case",
            }
        )
        if len(events) >= 8:
            break
    return events


def _calculate_strength_tags(stats: Dict[str, Any]) -> List[Dict[str, Any]]:
    tags: List[Dict[str, Any]] = []
    for case_label, values in (stats or {}).items():
        avg_score = float(values.get("avg_score") or 0)
        avg_max = float(values.get("avg_max") or 0)
        ratio = (avg_score / avg_max * 100) if avg_max else 0.0
        if ratio >= 70:
            strength = "strong"
        elif ratio < 50:
            strength = "watch"
        else:
            strength = "neutral"
        tags.append(
            {
                "case": case_label,
                "ratio": ratio,
                "strength": strength,
                "description": f"平均 {avg_score:.1f} / {avg_max:.0f}点" if avg_max else "データ蓄積中",
            }
        )
    tags.sort(key=lambda item: item["ratio"], reverse=True)
    return tags[:6]


def _get_committee_heatmap_context(default_year: str = "令和7年度") -> Optional[Dict[str, Any]]:
    dataset = committee_analysis.load_committee_dataset()
    if not dataset:
        return None

    df = committee_analysis.flatten_profiles(dataset)
    if df.empty:
        return None

    summary_df = committee_analysis.aggregate_heatmap(df)
    if summary_df.empty:
        return None

    year_label = dataset.get("year", default_year)
    total_committees = int(df["委員"].nunique())
    case_totals = summary_df.groupby("事例")["重み"].sum().sort_values(ascending=False)
    domain_totals = summary_df.groupby("専門カテゴリ")["重み"].sum().sort_values(ascending=False)

    top_case_label = case_totals.index[0] if not case_totals.empty else "-"
    top_case_weight = float(case_totals.iloc[0]) if not case_totals.empty else 0.0
    top_domain_label = domain_totals.index[0] if not domain_totals.empty else "-"
    top_domain_weight = float(domain_totals.iloc[0]) if not domain_totals.empty else 0.0

    weights = summary_df["重み"].astype(float)
    min_weight = float(weights.min() or 0)
    max_weight = float(weights.max() or 0)
    median_weight = float(weights.median() or 0)

    domain_order = committee_analysis.domain_order(summary_df)
    chart_data = summary_df.copy()
    color_scale = alt.Scale(
        scheme="blues",
        domain=(0, max_weight if max_weight > 0 else 1),
        domainMin=0,
    )

    base_chart = (
        alt.Chart(chart_data)
        .mark_rect()
        .encode(
            x=alt.X("事例:N", sort=CASE_ORDER, title="事例"),
            y=alt.Y("専門カテゴリ:N", sort=domain_order, title="専門領域"),
            color=alt.Color("重み:Q", scale=color_scale, title="影響度"),
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
    text_layer_weight = (
        alt.Chart(chart_data)
        .mark_text(color="#0f172a", fontSize=13, fontWeight="bold", dy=-6)
        .encode(x="事例:N", y="専門カテゴリ:N", text=alt.Text("重み:Q", format=".1f"))
    )
    text_layer_members = (
        alt.Chart(chart_data)
        .mark_text(color="#334155", fontSize=11, dy=10)
        .encode(x="事例:N", y="専門カテゴリ:N", text=alt.Text("委員数:Q", format=".0f"))
    )
    highlight_rows = chart_data.nlargest(3, "重み")
    highlight_layer = (
        alt.Chart(highlight_rows)
        .mark_rect(stroke="#1d4ed8", strokeWidth=2, fillOpacity=0)
        .encode(x="事例:N", y="専門カテゴリ:N")
    )
    chart = base_chart + text_layer_weight + text_layer_members + highlight_layer

    primary_focus = committee_analysis.identify_primary_focus(dataset, summary_df)
    recommendations = committee_analysis.focus_recommendations(summary_df, limit=5)
    cross_focuses = committee_analysis.cross_focus_highlights(dataset, limit=2)

    return {
        "year_label": year_label,
        "total_committees": total_committees,
        "top_case_label": top_case_label,
        "top_case_weight": top_case_weight,
        "top_domain_label": top_domain_label,
        "top_domain_weight": top_domain_weight,
        "min_weight": min_weight,
        "max_weight": max_weight,
        "median_weight": median_weight,
        "chart": chart,
        "summary_df": summary_df,
        "primary_focus": primary_focus,
        "recommendations": recommendations,
        "cross_focuses": cross_focuses,
    }

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


def _insight_icon_svg(name: str) -> str:
    icon_map = {
        "target": dedent(
            """
            <svg viewBox="0 0 24 24" aria-hidden="true" focusable="false">
                <circle cx="12" cy="12" r="9" fill="none" stroke="currentColor" stroke-width="1.6" />
                <circle cx="12" cy="12" r="4.5" fill="none" stroke="currentColor" stroke-width="1.6" />
                <path d="M12 7v5l3 1" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" />
            </svg>
            """
        ).strip(),
        "clock": dedent(
            """
            <svg viewBox="0 0 24 24" aria-hidden="true" focusable="false">
                <circle cx="12" cy="12" r="9" fill="none" stroke="currentColor" stroke-width="1.6" />
                <path d="M12 7v5.2l3 2.3" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" />
            </svg>
            """
        ).strip(),
        "trend": dedent(
            """
            <svg viewBox="0 0 24 24" aria-hidden="true" focusable="false">
                <path d="M4 16.5 9.2 11l3.1 3.1 7.7-7.7" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" />
                <polyline points="18 6.4 18 10.8 13.6 10.8" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" />
            </svg>
            """
        ).strip(),
    }
    return icon_map.get(name, icon_map["target"])


def dashboard_page(user: Dict) -> None:
    _inject_dashboard_styles()

    st.title("ホームダッシュボード")
    st.caption("学習状況のサマリと機能へのショートカット")

    attempts = database.list_attempts(user_id=user["id"])
    gamification = _calculate_gamification(attempts)
    stats = database.aggregate_statistics(user["id"])
    keyword_records = database.fetch_keyword_performance(user["id"])
    dashboard_analysis = _prepare_dashboard_analysis_data(keyword_records)

    total_attempts = len(attempts)
    total_score = sum(row["total_score"] or 0 for row in attempts)
    total_max = sum(row["total_max_score"] or 0 for row in attempts)
    average_score = round(total_score / total_attempts, 1) if total_attempts else 0
    completion_rate = (total_score / total_max * 100) if total_max else 0.0

    total_learning_minutes = sum((row.get("duration_seconds") or 0) for row in attempts) // 60

    level_threshold = gamification.get("level_threshold") or 0
    level_progress_ratio = (
        gamification.get("level_progress", 0) / level_threshold if level_threshold else 0
    )
    level_progress_percent = max(0.0, min(level_progress_ratio * 100, 100.0))

    next_milestone = gamification.get("next_milestone") or 0
    streak_progress_ratio = (
        gamification.get("attempts", 0) / next_milestone if next_milestone else 1.0
    )
    streak_progress_percent = max(0.0, min(streak_progress_ratio * 100, 100.0))
    remaining_attempts = max(next_milestone - gamification.get("attempts", 0), 0) if next_milestone else 0

    expected_minutes = max(total_attempts * 45, 180)
    time_ratio = total_learning_minutes / expected_minutes if expected_minutes else 0.0
    time_percent = max(0.0, min(time_ratio * 100, 100.0))

    best_case_label = None
    best_case_rate = 0.0
    if stats:
        case_ratios = [
            (
                case_label,
                (values.get("avg_score", 0) / values.get("avg_max", 0) * 100)
                if values.get("avg_max")
                else 0.0,
            )
            for case_label, values in stats.items()
        ]
        if case_ratios:
            best_case_label, best_case_rate = max(case_ratios, key=lambda item: item[1])

    metric_cards = [
        {
            "label": "演習回数",
            "value": f"{total_attempts}回",
            "desc": "これまで解いたケースの累計",
        },
        {
            "label": "平均得点",
            "value": f"{average_score}点",
            "desc": "全演習の平均スコア",
        },
        {
            "label": "得点達成率",
            "value": f"{completion_rate:.0f}%",
            "desc": "満点に対する平均達成度",
        },
        {
            "label": "得意な事例",
            "value": best_case_label or "記録なし",
            "desc": (
                f"平均達成率 {best_case_rate:.0f}%" if best_case_label else "データが蓄積されると表示されます"
            ),
        },
    ]

    timeline_events = _build_dashboard_timeline_events(attempts)
    heatmap_context = _get_committee_heatmap_context()

    upcoming_reviews = database.list_upcoming_reviews(user_id=user["id"], limit=6)
    due_review_count = database.count_due_reviews(user_id=user["id"])

    strength_tags = _calculate_strength_tags(stats)

    personalized_bundle = personalized_recommendation.generate_personalised_learning_plan(
        user_id=user["id"],
        attempts=attempts,
        problem_catalog=database.list_problems(),
        keyword_resource_map=KEYWORD_RESOURCE_MAP,
        default_resources=DEFAULT_KEYWORD_RESOURCES,
    )

    latest_attempt = attempts[0] if attempts else None
    next_focus_card = {
        "icon": "target",
        "accent": "indigo",
        "title": "次に集中すべき事例",
        "value": "最初の演習を始めましょう",
        "desc": "演習を完了すると優先度が表示されます。",
    }
    if stats:
        focus_case_label = None
        focus_rate = None
        for case_label, values in stats.items():
            if not values.get("avg_max"):
                continue
            ratio = values.get("avg_score", 0) / values.get("avg_max", 0) * 100
            if focus_rate is None or ratio < focus_rate:
                focus_rate = ratio
                focus_case_label = case_label
        if focus_case_label:
            next_focus_card = {
                "icon": "target",
                "accent": "indigo",
                "title": "次に集中すべき事例",
                "value": focus_case_label,
                "desc": f"平均達成率 {focus_rate:.0f}%。重点復習で底上げしましょう。",
            }

    learning_time_card = {
        "icon": "clock",
        "accent": "teal",
        "title": "累計学習時間",
        "value": _format_duration_minutes(total_learning_minutes),
        "desc": "記録された演習・模試の回答時間の合計",
    }
    if total_learning_minutes == 0:
        learning_time_card["value"] = "0分"
        learning_time_card["desc"] = "初回の演習で学習時間を記録しましょう。"

    latest_result_card = {
        "icon": "trend",
        "accent": "slate",
        "title": "直近の結果",
        "value": "データなし",
        "desc": "演習を完了すると最新結果が表示されます。",
    }
    if latest_attempt:
        latest_score = latest_attempt.get("total_score") or 0
        latest_max = latest_attempt.get("total_max_score") or 0
        latest_ratio = (latest_score / latest_max * 100) if latest_max else 0
        latest_result_card = {
            "icon": "trend",
            "accent": "slate",
            "title": "直近の結果",
            "value": f"{latest_score:.0f} / {latest_max:.0f}点 ({latest_ratio:.0f}%)",
            "desc": f"{_format_datetime_label(latest_attempt.get('submitted_at'))} 実施",
        }

    toc_items = [
        ("kpi-lane", "KPI"),
        ("progress-lane", "進捗"),
        ("analysis-lane", "ヒートマップ"),
        ("insight-lane", "洞察"),
    ]
    toc_html = "".join(
        f"<a href='#" + item_id + f"' class='dashboard-toc__link' data-target='{item_id}' aria-current='false'>{label}</a>"
        for item_id, label in toc_items
    )
    st.markdown(
        f"<nav class='dashboard-toc' aria-label='ページ内ナビゲーション'>{toc_html}</nav>",
        unsafe_allow_html=True,
    )

    grid_container = st.container()
    with grid_container:
        st.markdown("<div class='dashboard-grid'>", unsafe_allow_html=True)

        kpi_tiles_html = []
        kpi_tiles_html.append(
            dedent(
                f"""
                <article class="kpi-tile" data-tone="blue" role="article">
                    <p class="kpi-tile__label">累計ポイント</p>
                    <p class="kpi-tile__value">{gamification['points']} pt</p>
                    <p class="kpi-tile__meta">レベル{gamification['level']} / 次のレベルまであと {gamification['points_to_next_level']} pt</p>
                    <div class="progress-bar" role="progressbar" aria-valuemin="0" aria-valuemax="100" aria-valuenow="{level_progress_percent:.0f}" aria-label="次のレベルまで">
                        <span class="progress-bar__label">次のレベルまで</span>
                        <div class="progress-bar__track" aria-hidden="true">
                            <div class="progress-bar__fill" style="--progress: {level_progress_percent:.0f}%"></div>
                        </div>
                        <span class="progress-bar__value">{level_progress_percent:.0f}%</span>
                    </div>
                </article>
                """
            ).strip()
        )
        streak_caption = (
            f"次の称号まであと {remaining_attempts} 回の演習"
            if next_milestone
            else "最高ランクに到達しました！継続おめでとうございます。"
        )
        kpi_tiles_html.append(
            dedent(
                f"""
                <article class="kpi-tile" data-tone="green" role="article">
                    <p class="kpi-tile__label">連続学習日数</p>
                    <p class="kpi-tile__value">{gamification['current_streak']}日</p>
                    <p class="kpi-tile__meta">{streak_caption}</p>
                    <div class="progress-bar" role="progressbar" aria-valuemin="0" aria-valuemax="100" aria-valuenow="{streak_progress_percent:.0f}" aria-label="称号達成まで">
                        <span class="progress-bar__label">称号達成まで</span>
                        <div class="progress-bar__track" aria-hidden="true">
                            <div class="progress-bar__fill" data-tone="yellow" style="--progress: {streak_progress_percent:.0f}%"></div>
                        </div>
                        <span class="progress-bar__value">{streak_progress_percent:.0f}%</span>
                    </div>
                </article>
                """
            ).strip()
        )
        badges = gamification.get("badges") or []
        if badges:
            badge_items = "".join(
                f"<li><span>🏅</span><span>{badge['title']}</span></li>" for badge in badges[:4]
            )
            badge_meta = "直近の獲得バッジ"
        else:
            badge_items = "<li>バッジはまだありません。演習や模試で獲得を目指しましょう。</li>"
            badge_meta = "実績が増えるとバッジが表示されます"
        kpi_tiles_html.append(
            dedent(
                f"""
                <article class="kpi-tile" data-tone="pink" role="article">
                    <p class="kpi-tile__label">バッジコレクション</p>
                    <p class="kpi-tile__value">{len(badges)}種</p>
                    <p class="kpi-tile__meta">{badge_meta}</p>
                    <ul class="kpi-tile__badges" aria-label="獲得バッジ一覧">{badge_items}</ul>
                </article>
                """
            ).strip()
        )
        kpi_section_html = dedent(
            f"""
            <section class="dashboard-lane dashboard-lane--kpi" id="kpi-lane" data-section-id="kpi-lane" role="region" aria-labelledby="kpi-lane-title">
                <header class="dashboard-lane__header">
                    <h2 id="kpi-lane-title" class="dashboard-lane__title">KPIレーン</h2>
                    <p class="dashboard-lane__subtitle">ポイントと連続学習の到達度をひと目で確認できます。</p>
                </header>
                <div class="dashboard-card card--tone-blue" role="group" aria-label="ポイントと連続学習の指標">
                    <div class="kpi-tiles">
                        {''.join(kpi_tiles_html)}
                    </div>
                </div>
            </section>
            """
        )
        st.markdown(kpi_section_html, unsafe_allow_html=True)

        progress_bars = [
            {
                "label": "得点達成率",
                "value": f"{completion_rate:.0f}%",
                "progress": max(0.0, min(completion_rate, 100.0)),
                "tone": "green",
                "helper": f"平均 {average_score:.1f} 点",
            },
            {
                "label": "次のレベルまで",
                "value": f"{level_progress_percent:.0f}%",
                "progress": level_progress_percent,
                "tone": "blue",
                "helper": f"あと {gamification['points_to_next_level']} pt",
            },
            {
                "label": "称号達成まで",
                "value": f"{streak_progress_percent:.0f}%",
                "progress": streak_progress_percent,
                "tone": "yellow",
                "helper": f"残り {remaining_attempts} 回" if next_milestone else "達成済",
            },
            {
                "label": "学習時間目安",
                "value": f"{time_percent:.0f}%",
                "progress": time_percent,
                "tone": "blue",
                "helper": f"{total_learning_minutes}分 / 目安 {expected_minutes}分",
            },
        ]
        progress_bars_html = "".join(
            dedent(
                f"""
                <div class="progress-bar" role="progressbar" aria-valuemin="0" aria-valuemax="100" aria-valuenow="{bar['progress']:.0f}" aria-label="{bar['label']}" data-tone="{bar['tone']}">
                    <span class="progress-bar__label">{bar['label']}</span>
                    <div class="progress-bar__track" aria-hidden="true">
                        <div class="progress-bar__fill" style="--progress: {bar['progress']:.0f}%"></div>
                    </div>
                    <span class="progress-bar__value">{bar['value']}</span>
                    <span class="progress-bar__helper">{bar['helper']}</span>
                </div>
                """
            ).strip()
            for bar in progress_bars
        )
        metric_chips_html = "".join(
            dedent(
                f"""
                <div class="metric-chip">
                    <div class="metric-chip__label">{card['label']}</div>
                    <p class="metric-chip__value">{card['value']}</p>
                    <p class="metric-chip__desc">{card['desc']}</p>
                </div>
                """
            ).strip()
            for card in metric_cards
        )
        progress_section_html = dedent(
            """
            <section class="dashboard-lane" id="progress-lane" data-section-id="progress-lane" role="region" aria-labelledby="progress-lane-title">
                <header class="dashboard-lane__header">
                    <h2 id="progress-lane-title" class="dashboard-lane__title">進捗レーン</h2>
                    <p class="dashboard-lane__subtitle">主要指標の進捗と履歴を一覧できます。</p>
                </header>
                <div class="dashboard-card card--tone-green" role="group" aria-label="進捗バー群">
                    <div class="progress-grid">
                        {progress_bars_html}
                    </div>
                    <div class="metric-grid">
                        {metric_chips_html}
                    </div>
                </div>
            </section>
            """
        )
        st.markdown(progress_section_html, unsafe_allow_html=True)

        if timeline_events:
            timeline_items_html = "".join(
                dedent(
                    f"""
                    <li class="achievement-timeline__item" data-case="{event['case_key']}">
                        <p class="achievement-timeline__time">{event['date']}</p>
                        <p class="achievement-timeline__title">{event['title']}</p>
                        <p class="achievement-timeline__meta">{event['meta']}</p>
                    </li>
                    """
                ).strip()
                for event in timeline_events
            )
            timeline_html = dedent(
                """
                <div class="dashboard-card card--tone-pink" role="region" aria-labelledby="achievement-timeline-title">
                    <div class="timeline-filter">
                        <p id="achievement-timeline-title" class="timeline-filter__label">実績フィード（最新8件）</p>
                        <div class="timeline-filter__actions">
                            <button type="button" class="timeline-filter__clear">フィルタを解除</button>
                        </div>
                    </div>
                    <ol class="achievement-timeline">{timeline_items_html}</ol>
                </div>
                """
            )
            st.markdown(timeline_html, unsafe_allow_html=True)
        else:
            st.markdown(
                """
                <div class="dashboard-card" role="region" aria-labelledby="achievement-timeline-title">
                    <p id="achievement-timeline-title" class="timeline-filter__label">実績フィード</p>
                    <p class="achievement-timeline__meta">演習を開始すると最新の実績がここに並びます。</p>
                </div>
                """,
                unsafe_allow_html=True,
            )

        review_card_header = dedent(
            """
            <section class="dashboard-lane" role="region" aria-labelledby="review-lane-title">
                <header class="dashboard-lane__header">
                    <h2 id="review-lane-title" class="dashboard-lane__title">復習スケジュール</h2>
                    <p class="dashboard-lane__subtitle">間隔反復で優先度の高い復習を提示します。</p>
                </header>
            """
        )
        st.markdown(review_card_header, unsafe_allow_html=True)
        st.markdown(
            "<div class='dashboard-card card--tone-blue review-card'>",
            unsafe_allow_html=True,
        )
        if due_review_count:
            st.markdown(
                f"<p class='timeline-filter__label'>⏳ {due_review_count}件の復習が期限到来または超過しています。優先的に取り組みましょう。</p>",
                unsafe_allow_html=True,
            )
        if upcoming_reviews:
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
            st.info("演習データが蓄積されると復習スケジュールが表示されます。")
        st.markdown("</div></section>", unsafe_allow_html=True)

        analysis_section_open = dedent(
            """
            <section class="dashboard-lane dashboard-lane--analysis" id="analysis-lane" data-section-id="analysis-lane" role="region" aria-labelledby="analysis-lane-title">
                <header class="dashboard-lane__header">
                    <h2 id="analysis-lane-title" class="dashboard-lane__title">分析レーン</h2>
                    <p class="dashboard-lane__subtitle">試験委員の専門×事例ヒートマップと実績分析を確認できます。</p>
                </header>
            """
        )
        st.markdown(analysis_section_open, unsafe_allow_html=True)
        st.markdown(
            "<div class='dashboard-card card--tone-yellow heatmap-card' role='region' aria-labelledby='committee-heatmap-title'>",
            unsafe_allow_html=True,
        )
        if heatmap_context:
            legend_html = dedent(
                f"""
                <div class="heatmap-header">
                    <p id="committee-heatmap-title" class="timeline-filter__label">{heatmap_context['year_label']} 試験委員“専門×事例”ヒートマップ</p>
                    <p class="achievement-timeline__meta">色が濃いほど影響度が高い組み合わせです。</p>
                </div>
                <div class="heatmap-legend">
                    <span class="heatmap-legend__swatch" aria-hidden="true"></span>
                    <span>最小 {heatmap_context['min_weight']:.1f}</span>
                    <span>中央値 {heatmap_context['median_weight']:.1f}</span>
                    <span>最大 {heatmap_context['max_weight']:.1f}</span>
                </div>
                <div class="heatmap-highlight">
                    <span>委員数: {heatmap_context['total_committees']} 名</span>
                    <span>最注目の事例: {heatmap_context['top_case_label']} (重み {heatmap_context['top_case_weight']:.1f})</span>
                    <span>強みの専門領域: {heatmap_context['top_domain_label']} (重み {heatmap_context['top_domain_weight']:.1f})</span>
                </div>
                """
            )
            st.markdown(legend_html, unsafe_allow_html=True)
            st.altair_chart(heatmap_context["chart"], use_container_width=True)
        else:
            st.markdown(
                "<p class='achievement-timeline__meta'>ヒートマップのデータが取得できませんでした。</p>",
                unsafe_allow_html=True,
            )
        st.markdown("</div>", unsafe_allow_html=True)

        if heatmap_context:
            summary_df = heatmap_context["summary_df"]
            st.markdown(
                "<div class='dashboard-card card--tone-blue analysis-table-card'>",
                unsafe_allow_html=True,
            )
            overview_tab, chart_tab = st.tabs(["進捗サマリ", "事例別分析"])
            with overview_tab:
                if attempts:
                    summary_df_table = pd.DataFrame(
                        [
                            {
                                "実施日": (
                                    row["submitted_at"].strftime("%Y-%m-%d")
                                    if isinstance(row["submitted_at"], datetime)
                                    else row["submitted_at"]
                                ),
                                "年度": row["year"],
                                "事例": row["case_label"],
                                "モード": "模試" if row["mode"] == "mock" else "演習",
                                "得点": row["total_score"],
                                "満点": row["total_max_score"],
                            }
                            for row in attempts
                        ]
                    )
                    st.data_editor(
                        summary_df_table,
                        use_container_width=True,
                        hide_index=True,
                        disabled=True,
                    )
                    st.caption("最近の受験結果を表形式で確認できます。列ヘッダーでソート可能です。")
                else:
                    st.info("まだ演習結果がありません。『過去問演習』から学習を開始しましょう。")
            with chart_tab:
                if stats:
                    chart_data = []
                    for case_label, values in stats.items():
                        chart_data.append(
                            {
                                "事例": case_label,
                                "得点": values.get("avg_score", 0),
                                "満点": values.get("avg_max", 0),
                            }
                        )
                    df = pd.DataFrame(chart_data)
                    df["達成率"] = df.apply(
                        lambda row: row["得点"] / row["満点"] * 100 if row["満点"] else 0,
                        axis=1,
                    )
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
            st.markdown("</div>", unsafe_allow_html=True)

        has_case_chart = not dashboard_analysis["case_chart_source"].empty
        has_question_heatmap = not dashboard_analysis["question_source"].empty
        has_keyword_heatmap = not dashboard_analysis["keyword_source"].empty

        if has_case_chart or has_question_heatmap or has_keyword_heatmap:
            st.markdown(
                "<div class='dashboard-card card--tone-purple analysis-visual-card'>",
                unsafe_allow_html=True,
            )
            st.markdown(
                "<p class='timeline-filter__label'>得点率×キーワード網羅の弱点診断</p>",
                unsafe_allow_html=True,
            )

            if has_case_chart:
                st.markdown("#### 事例別レーダーチャート")
                radar_source = dashboard_analysis["case_chart_source"].dropna(subset=["値"])
                if not radar_source.empty:
                    radar_chart = (
                        alt.Chart(radar_source)
                        .mark_line(point=True)
                        .encode(
                            theta=alt.Theta("指標:N", sort=["平均得点率", "平均キーワード網羅率"], title=None),
                            radius=alt.Radius(
                                "値:Q", scale=alt.Scale(domain=[0, 100]), title="達成率 (%)"
                            ),
                            color=alt.Color("事例:N", sort=CASE_ORDER, title=None),
                            tooltip=["事例", "指標", alt.Tooltip("値:Q", format=".1f")],
                        )
                        .properties(height=320)
                    )
                    st.altair_chart(radar_chart, use_container_width=True)
                    improvement_low, improvement_high = dashboard_analysis["improvement_range"]
                    st.caption(
                        f"フェルミ推定では弱点分析を踏まえた学習時間の再配分により平均得点が"
                        f"{improvement_low * 100:.0f}〜{improvement_high * 100:.0f}%向上する余地があります。"
                    )
                else:
                    st.info("事例別のレーダーチャートを描画するには演習データが必要です。")

            if has_question_heatmap:
                st.markdown("#### 設問別のヒートマップ")
                question_df = dashboard_analysis["question_source"].copy()
                question_sort = dashboard_analysis["question_order_labels"] or "ascending"
                score_heatmap = (
                    alt.Chart(question_df.dropna(subset=["平均得点率"]))
                    .mark_rect()
                    .encode(
                        x=alt.X("設問:N", sort=question_sort, title="設問"),
                        y=alt.Y("事例:N", sort=CASE_ORDER, title=None),
                        color=alt.Color(
                            "平均得点率:Q",
                            scale=alt.Scale(domain=[0, 100], scheme="teals"),
                            title="平均得点率 (%)",
                        ),
                        tooltip=[
                            "事例",
                            "設問",
                            alt.Tooltip("平均得点率:Q", format=".1f"),
                            alt.Tooltip("平均キーワード網羅率:Q", format=".1f"),
                        ],
                    )
                    .properties(height=260)
                )
                coverage_heatmap = (
                    alt.Chart(question_df.dropna(subset=["平均キーワード網羅率"]))
                    .mark_rect()
                    .encode(
                        x=alt.X("設問:N", sort=question_sort, title="設問"),
                        y=alt.Y("事例:N", sort=CASE_ORDER, title=None),
                        color=alt.Color(
                            "平均キーワード網羅率:Q",
                            scale=alt.Scale(domain=[0, 100], scheme="purples"),
                            title="平均キーワード網羅率 (%)",
                        ),
                        tooltip=[
                            "事例",
                            "設問",
                            alt.Tooltip("平均得点率:Q", format=".1f"),
                            alt.Tooltip("平均キーワード網羅率:Q", format=".1f"),
                        ],
                    )
                    .properties(height=260)
                )
                heatmap_col1, heatmap_col2 = st.columns(2)
                with heatmap_col1:
                    if score_heatmap.data.empty:
                        st.info("得点率ヒートマップを表示するには得点データが必要です。")
                    else:
                        st.altair_chart(score_heatmap, use_container_width=True)
                with heatmap_col2:
                    if coverage_heatmap.data.empty:
                        st.info("キーワード網羅率ヒートマップを表示するには判定データが必要です。")
                    else:
                        st.altair_chart(coverage_heatmap, use_container_width=True)
                st.caption("濃淡が薄いセルは優先復習したい設問を示します。")

            if has_keyword_heatmap:
                st.markdown("#### テーマ別（キーワード）網羅率ヒートマップ")
                keyword_df = dashboard_analysis["keyword_source"].copy()
                keyword_sort = dashboard_analysis["keyword_labels"] or "ascending"
                keyword_heatmap = (
                    alt.Chart(keyword_df.dropna(subset=["網羅率"]))
                    .mark_rect()
                    .encode(
                        x=alt.X("キーワード:N", sort=keyword_sort, title="キーワード"),
                        y=alt.Y("事例:N", sort=CASE_ORDER, title=None),
                        color=alt.Color(
                            "網羅率:Q",
                            scale=alt.Scale(domain=[0, 100], scheme="oranges"),
                            title="網羅率 (%)",
                        ),
                        tooltip=[
                            "事例",
                            "キーワード",
                            alt.Tooltip("網羅率:Q", format=".1f"),
                            alt.Tooltip("出題数:Q", format=".0f", title="出題数"),
                        ],
                    )
                    .properties(height=260)
                )
                st.altair_chart(keyword_heatmap, use_container_width=True)
                st.caption("特に網羅率が低いテーマは早期に補強しましょう。")

            st.markdown("</div>", unsafe_allow_html=True)
        st.markdown("</section>", unsafe_allow_html=True)

        insight_section_open = dedent(
            """
            <section class="dashboard-lane dashboard-lane--insight" id="insight-lane" data-section-id="insight-lane" role="region" aria-labelledby="insight-lane-title">
                <header class="dashboard-lane__header">
                    <h2 id="insight-lane-title" class="dashboard-lane__title">洞察レーン</h2>
                    <p class="dashboard-lane__subtitle">強み・推奨テーマ・アクションプランを表示します。</p>
                </header>
            """
        )
        st.markdown(insight_section_open, unsafe_allow_html=True)

        if due_review_count:
            banner_html = dedent(
                f"""
                <details class="insight-banner" open data-banner-storage="dashboard-review-banner">
                    <summary class="insight-banner__summary insight-banner__toggle">ℹ️ 復習アラート ({due_review_count}件)</summary>
                    <div class="insight-banner__content">期限が到来した復習があります。復習スケジュールを確認し、優先対応しましょう。</div>
                </details>
                """
            )
            st.markdown(banner_html, unsafe_allow_html=True)
        elif heatmap_context and heatmap_context.get("primary_focus"):
            focus = heatmap_context["primary_focus"]
            rationale = focus.get("rationale") or ""
            study_list = focus.get("study_list") or []
            focus_html = dedent(
                f"""
                <details class="insight-banner" open data-banner-storage="dashboard-focus-banner">
                    <summary class="insight-banner__summary insight-banner__toggle">🎯 今年の重心: {focus.get('label')}</summary>
                    <div class="insight-banner__content">{rationale} {' / '.join(study_list[:3]) if study_list else ''}</div>
                </details>
                """
            )
            st.markdown(focus_html, unsafe_allow_html=True)

        if strength_tags:
            tags_html = "".join(
                dedent(
                    f"""
                    <button type="button" class="insight-pill" data-case="{tag['case'].replace(' ', '').replace('　', '')}" data-strength="{tag['strength']}" aria-pressed="false">
                        {tag['case']} ({tag['ratio']:.0f}%)
                    </button>
                    """
                ).strip()
                for tag in strength_tags
            )
            st.markdown(
                dedent(
                    f"""
                    <div class="dashboard-card card--tone-pink" role="group" aria-label="強みタグ">
                        <p class="timeline-filter__label">強み・注視したい事例タグ</p>
                        <div class="insight-pill-group">{tags_html}</div>
                        <p class="achievement-timeline__meta">タグをクリックすると実績フィードが該当事例でハイライトされます。</p>
                    </div>
                    """
                ),
                unsafe_allow_html=True,
            )

        insight_cards_html: List[str] = []
        for card in [next_focus_card, learning_time_card, latest_result_card]:
            accent = card.get("accent", "indigo")
            icon_html = _insight_icon_svg(card.get("icon", "target"))
            insight_cards_html.append(
                dedent(
                    f"""
                    <div class="insight-card" data-accent="{accent}">
                        <div class="insight-icon" data-accent="{accent}">{icon_html}</div>
                        <div class="insight-copy">
                            <p class="insight-title">{card['title']}</p>
                            <p class="insight-value">{card['value']}</p>
                            <p class="insight-desc">{card['desc']}</p>
                        </div>
                    </div>
                    """
                ).strip()
            )
        insight_cards_html_str = "".join(insight_cards_html)
        st.markdown(
            dedent(
                f"""
                <div class="dashboard-card card--tone-green" role="group" aria-label="学習ハイライト">
                    <div class="insight-grid">{insight_cards_html_str}</div>
                </div>
                """
            ),
            unsafe_allow_html=True,
        )

        if heatmap_context:
            rec_html_parts = []
            for item in heatmap_context.get("recommendations") or []:
                themes = item.get("themes", [])
                comment = item.get("comment")
                bullet = f"<li><strong>{item.get('case', '')} × {item.get('domain', '')}</strong>"
                if comment:
                    bullet += f" — {comment}"
                if themes:
                    bullet += f"<br><span class='achievement-timeline__meta'>推奨演習: {' / '.join(themes[:3])}</span>"
                bullet += "</li>"
                rec_html_parts.append(bullet)
            cross_html_parts = []
            for entry in heatmap_context.get("cross_focuses") or []:
                cases = "・".join(entry.get("cases", []))
                headline = f"<li><strong>{entry.get('label', '')}</strong>"
                if cases:
                    headline += f" ({cases})"
                rationale = entry.get("rationale")
                if rationale:
                    headline += f" — {rationale}"
                study_list = entry.get("study_list") or []
                if study_list:
                    headline += f"<br><span class='achievement-timeline__meta'>推奨演習: {' / '.join(study_list[:3])}</span>"
                headline += "</li>"
                cross_html_parts.append(headline)
            st.markdown(
                dedent(
                    f"""
                    <div class="dashboard-card" role="region" aria-label="推奨テーマ">
                        <p class="timeline-filter__label">推奨テーマと横断候補</p>
                        <ul>{''.join(rec_html_parts) or '<li>推奨テーマは現在分析中です。</li>'}</ul>
                        <ul>{''.join(cross_html_parts)}</ul>
                    </div>
                    """
                ),
                unsafe_allow_html=True,
            )

        personalized_context = personalized_bundle.get("context")
        problem_recs = personalized_bundle.get("problem_recommendations") or []
        question_recs = personalized_bundle.get("question_recommendations") or []
        resource_recs = personalized_bundle.get("resource_recommendations") or []

        sections: List[str] = []

        if problem_recs:
            problem_items: List[str] = []
            for rec in problem_recs:
                summary = personalized_recommendation.format_recommendation_summary(rec)
                reason = html.escape(rec.get("reason") or "")
                problem_items.append(
                    f"<li><strong>{summary}</strong><br><span class='achievement-timeline__meta'>{reason}</span></li>"
                )
            sections.append(
                dedent(
                    f"""
                    <div class="personalized-section" role="group" aria-label="おすすめの事例">
                        <p class="timeline-filter__label">おすすめの年度・事例</p>
                        <ol>{''.join(problem_items)}</ol>
                    </div>
                    """
                )
            )

        if question_recs:
            question_items: List[str] = []
            for rec in question_recs:
                header = f"{html.escape(str(rec.get('year') or '―'))} {html.escape(str(rec.get('case_label') or ''))}".strip()
                prompt = html.escape(rec.get("prompt") or "設問文を確認してください")
                reason = html.escape(rec.get("reason") or "復習推奨")
                missing = rec.get("missing_keywords") or []
                missing_html = ""
                if missing:
                    missing_html = (
                        "<br><span class='achievement-timeline__meta'>不足キーワード: "
                        + " / ".join(html.escape(keyword) for keyword in missing[:4])
                        + "</span>"
                    )
                question_items.append(
                    "<li>"
                    + (f"<strong>{header}</strong><br>" if header else "")
                    + prompt
                    + f"<br><span class='achievement-timeline__meta'>{reason}</span>"
                    + missing_html
                    + "</li>"
                )
            sections.append(
                dedent(
                    f"""
                    <div class="personalized-section" role="group" aria-label="重点設問">
                        <p class="timeline-filter__label">重点設問</p>
                        <ol>{''.join(question_items)}</ol>
                    </div>
                    """
                )
            )

        if resource_recs:
            resource_items: List[str] = []
            for resource in resource_recs:
                label = html.escape(resource.get("label") or "参考資料")
                url = html.escape(resource.get("url") or "#")
                reason = html.escape(resource.get("reason") or "")
                resource_items.append(
                    "<li>"
                    + f"<a href='{url}' target='_blank' rel='noopener noreferrer'>{label}</a>"
                    + (f"<br><span class='achievement-timeline__meta'>{reason}</span>" if reason else "")
                    + "</li>"
                )
            sections.append(
                dedent(
                    f"""
                    <div class="personalized-section" role="group" aria-label="おすすめ教材">
                        <p class="timeline-filter__label">おすすめ教材</p>
                        <ol>{''.join(resource_items)}</ol>
                    </div>
                    """
                )
            )

        message_text = getattr(personalized_context, "message", "") if personalized_context else ""
        message_html = (
            f"<p class='achievement-timeline__meta'>{html.escape(message_text)}</p>" if message_text else ""
        )

        if message_html or sections:
            sections_html = "".join(sections) or "<p class='achievement-timeline__meta'>推奨項目を準備中です。</p>"
            st.markdown(
                dedent(
                    f"""
                    <div class="dashboard-card card--tone-blue" role="region" aria-label="パーソナライズ推薦">
                        <p class="timeline-filter__label">パーソナライズ推薦</p>
                        {message_html}
                        {sections_html}
                    </div>
                    """
                ),
                unsafe_allow_html=True,
            )

        st.markdown(
            dedent(
                """
                <div class="dashboard-card" role="region" aria-label="ショートカット">
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
                </div>
                """
            ),
            unsafe_allow_html=True,
        )

        st.markdown("</section>", unsafe_allow_html=True)
        st.markdown("</div>", unsafe_allow_html=True)

    _render_study_planner(user)

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


def _ensure_mece_status_styles() -> None:
    if st.session_state.get("_mece_status_styles_injected"):
        return
    st.markdown(
        """
        <style>
        .mece-status-row {
            display: flex;
            flex-wrap: wrap;
            gap: 0.4rem;
            align-items: center;
            margin: 0.35rem 0 0.5rem;
        }
        .mece-status-chip {
            display: inline-flex;
            align-items: center;
            gap: 0.3rem;
            font-size: 0.76rem;
            font-weight: 500;
            border-radius: 999px;
            padding: 0.25rem 0.65rem;
            background: #e2e8f0;
            color: #1e293b;
        }
        .mece-status-chip.ok {
            background: rgba(134, 239, 172, 0.55);
            color: #14532d;
        }
        .mece-status-chip.warn {
            background: rgba(253, 230, 138, 0.55);
            color: #92400e;
        }
        .mece-status-chip.alert {
            background: rgba(248, 113, 113, 0.55);
            color: #991b1b;
        }
        .mece-status-chip.neutral {
            background: rgba(226, 232, 240, 0.65);
            color: #334155;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )
    st.session_state["_mece_status_styles_injected"] = True


def _render_mece_status_labels(text: str) -> Optional[Dict[str, Any]]:
    _ensure_mece_status_styles()
    if not text.strip():
        st.markdown(
            "<div class='mece-status-row'>"
            "<span class='mece-status-chip neutral'>🧭 文章を入力すると構造ラベルを表示します</span>"
            "</div>",
            unsafe_allow_html=True,
        )
        return None

    analysis = _analyze_mece_causal(text)
    chips: List[str] = []

    duplicates = analysis.get("duplicates", [])
    synonyms = analysis.get("synonyms", [])
    enumerations = analysis.get("enumerations", [])
    suggestions = analysis.get("suggestions", [])

    if duplicates:
        chips.append(
            "<span class='mece-status-chip warn' title='重複語: {detail}'>🔁 重複 {count}</span>".format(
                count=len(duplicates),
                detail=html.escape("、".join(duplicates)),
            )
        )
    if synonyms:
        chips.append(
            "<span class='mece-status-chip warn' title='同義反復: {detail}'>🔄 同義 {count}</span>".format(
                count=len(synonyms),
                detail=html.escape("、".join(synonyms)),
            )
        )
    if enumerations:
        chips.append(
            "<span class='mece-status-chip warn' title='単純列挙の疑い: {detail}'>📋 列挙 {count}</span>".format(
                count=len(enumerations),
                detail=html.escape("、".join(enumerations)),
            )
        )
    if suggestions:
        chips.append(
            "<span class='mece-status-chip alert' title='{detail}'>🔗 因果補強</span>".format(
                detail=html.escape(" / ".join(suggestions[:3])),
            )
        )

    if not chips:
        chips.append("<span class='mece-status-chip ok'>✅ 構造バランス良好</span>")

    st.markdown(
        "<div class='mece-status-row'>{chips}</div>".format(chips="".join(chips)),
        unsafe_allow_html=True,
    )
    return analysis


def _render_mece_causal_scanner(text: str, analysis: Optional[Dict[str, Any]] = None) -> None:
    _inject_mece_scanner_styles()
    st.caption("MECE/因果スキャナ：重複語・列挙・接続詞不足を自動チェックします。")
    if not text.strip():
        st.info("文章を入力するとハイライト結果と因果接続の提案が表示されます。")
        return

    if analysis is None:
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
    question_index: Optional[int] = None,
    anchor_id: Optional[str] = None,
    header_id: Optional[str] = None,
) -> str:
    _inject_practice_question_styles()
    key = _draft_key(problem_id, question["id"])
    if key not in st.session_state.drafts:
        saved_default = st.session_state.saved_answers.get(key, "")
        st.session_state.drafts[key] = saved_default

    textarea_state_key = f"{widget_prefix}{key}"

    if not anchor_id:
        anchor_source = (
            question_index
            if question_index is not None
            else question.get("order")
            or question.get("設問番号")
            or question.get("prompt")
            or question.get("id")
        )
        if anchor_source is not None:
            anchor_slug = re.sub(r"[^0-9a-zA-Z]+", "-", str(anchor_source)).strip("-")
            if not anchor_slug:
                anchor_slug = str(question.get("id"))
            anchor_id = f"question-q{anchor_slug}"
    if anchor_id:
        st.markdown(
            f"<div id=\"{html.escape(anchor_id)}\" class=\"practice-question-anchor\" aria-hidden=\"true\"></div>",
            unsafe_allow_html=True,
        )

    question_overview = dict(question)
    question_overview.setdefault("order", question.get("order"))
    question_overview.setdefault("case_label", case_label)
    _render_question_overview_card(
        question_overview,
        case_label=case_label,
        anchor_id=anchor_id,
        header_id=header_id,
    )

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
    st.markdown(
        "<p class=\"practice-autosave-caption\">入力内容は自動保存されます。</p>",
        unsafe_allow_html=True,
    )
    text = st.text_area(
        label=question["prompt"],
        key=textarea_state_key,
        value=value,
        height=160,
        help=help_text,
        disabled=disabled,
    )
    _render_character_counter(text, question.get("character_limit"))
    analysis = _render_mece_status_labels(text)
    with st.expander("MECE/因果スキャナ", expanded=bool(text.strip())):
        _render_mece_causal_scanner(text, analysis=analysis)
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

    st.divider()
    _render_intent_cards(question, key, textarea_state_key)
    _render_case_frame_shortcuts(case_label, key, textarea_state_key)
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


def _build_learning_report(history_df: pd.DataFrame) -> Dict[str, Any]:
    report: Dict[str, Any] = {
        "module_summary": pd.DataFrame(),
        "monthly_summary": pd.DataFrame(),
        "weekly_summary": pd.DataFrame(),
        "pdca": {
            "plan": "",
            "do": "",
            "check": "",
            "act": "",
        },
        "export": {},
    }

    if history_df.empty or "日付" not in history_df.columns:
        return report

    working = history_df.dropna(subset=["日付"]).copy()
    if working.empty:
        return report

    working["日付"] = pd.to_datetime(working["日付"], errors="coerce")
    working = working.dropna(subset=["日付"])
    if working.empty:
        return report

    working = working[working["事例"].notna()].copy()
    if working.empty:
        return report

    working["学習時間(分)"] = pd.to_numeric(working.get("学習時間(分)"), errors="coerce").fillna(0.0)
    working["得点"] = pd.to_numeric(working.get("得点"), errors="coerce")
    working["満点"] = pd.to_numeric(working.get("満点"), errors="coerce")
    working["得点率"] = working.apply(
        lambda row: (row["得点"] / row["満点"]) * 100
        if pd.notna(row["得点"]) and pd.notna(row["満点"]) and row["満点"]
        else None,
        axis=1,
    )

    module_summary_raw = (
        working.groupby("事例")
        .agg(
            演習回数=("attempt_id", "count"),
            学習時間分=("学習時間(分)", "sum"),
            平均得点=("得点", "mean"),
            平均得点率=("得点率", "mean"),
        )
        .reset_index()
    )

    latest_records = (
        working.sort_values("日付")
        .groupby("事例")
        .tail(1)
        .loc[:, ["事例", "日付", "得点", "得点率"]]
    )

    module_summary_raw = module_summary_raw.merge(latest_records, on="事例", how="left")
    module_summary_raw["学習時間時間"] = module_summary_raw["学習時間分"] / 60.0

    module_summary = module_summary_raw.rename(
        columns={
            "事例": "モジュール",
            "学習時間分": "学習時間(分)",
            "学習時間時間": "学習時間(時間)",
            "得点": "直近得点",
            "得点率": "直近得点率",
            "日付": "直近実施日",
        }
    )

    monthly_summary_raw = _aggregate_module_by_period(working, freq="M")
    weekly_summary_raw = _aggregate_module_by_period(working, freq="W-MON")

    report.update(
        {
            "module_summary": module_summary,
            "monthly_summary": _format_period_dataframe(monthly_summary_raw),
            "weekly_summary": _format_period_dataframe(weekly_summary_raw),
            "pdca": _generate_pdca_insights(
                module_summary_raw, weekly_summary_raw, working
            ),
            "export": {
                "モジュール別サマリ": module_summary,
                "月次トレンド": _prepare_export_dataframe(monthly_summary_raw),
                "週次トレンド": _prepare_export_dataframe(weekly_summary_raw),
            },
        }
    )

    return report


def _aggregate_module_by_period(history_df: pd.DataFrame, *, freq: str) -> pd.DataFrame:
    period_index = history_df["日付"].dt.to_period(freq)
    period_index.name = "期間"
    grouped = history_df.groupby([period_index, "事例"])
    aggregated = grouped.agg(
        演習回数=("attempt_id", "count"),
        学習時間分=("学習時間(分)", "sum"),
        平均得点=("得点", "mean"),
        平均得点率=("得点率", "mean"),
    )
    aggregated = aggregated.reset_index()
    aggregated["期間開始"] = aggregated["期間"].dt.to_timestamp()

    if freq == "M":
        aggregated["期間ラベル"] = aggregated["期間開始"].dt.strftime("%Y-%m")
    else:
        start = aggregated["期間開始"].dt.strftime("%Y-%m-%d")
        aggregated["期間ラベル"] = start + " 週"

    aggregated["学習時間時間"] = aggregated["学習時間分"] / 60.0
    aggregated.rename(columns={"事例": "モジュール"}, inplace=True)

    return aggregated[
        [
            "期間",
            "期間開始",
            "期間ラベル",
            "モジュール",
            "演習回数",
            "学習時間分",
            "学習時間時間",
            "平均得点",
            "平均得点率",
        ]
    ]


def _format_period_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df
    formatted = df.copy()
    formatted.rename(
        columns={
            "学習時間分": "学習時間(分)",
            "学習時間時間": "学習時間(時間)",
        },
        inplace=True,
    )
    return formatted


def _prepare_export_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df
    export_df = df.copy()
    export_df["期間開始"] = pd.to_datetime(export_df["期間開始"], errors="coerce")
    export_df["期間"] = export_df["期間"].astype(str)
    export_df.rename(
        columns={
            "学習時間分": "学習時間(分)",
            "学習時間時間": "学習時間(時間)",
        },
        inplace=True,
    )
    return export_df


def _generate_pdca_insights(
    module_summary: pd.DataFrame,
    weekly_summary: pd.DataFrame,
    working_df: pd.DataFrame,
) -> Dict[str, str]:
    insights = {"plan": "", "do": "", "check": "", "act": ""}

    if module_summary.empty:
        return insights

    sorted_by_score = module_summary.sort_values("平均得点率")
    if not sorted_by_score.empty:
        focus_row = sorted_by_score.iloc[0]
        avg_score = focus_row["平均得点率"]
        insights["plan"] = (
            f"平均得点率が{avg_score:.1f}%の『{focus_row['事例']}』を重点的に計画に組み込みましょう。"
        )

    recent_cutoff = working_df["日付"].max() - pd.Timedelta(days=28)
    recent_slice = working_df[working_df["日付"] >= recent_cutoff]
    if recent_slice.empty:
        recent_slice = working_df
    time_totals = (
        recent_slice.groupby("事例")["学習時間(分)"].sum().sort_values(ascending=False)
    )
    if not time_totals.empty:
        top_module = time_totals.index[0]
        minutes = time_totals.iloc[0]
        insights["do"] = (
            f"直近4週間で{minutes:.0f}分の学習を行った『{top_module}』の取り組みを継続しましょう。"
        )

    if not weekly_summary.empty:
        weekly_sorted = weekly_summary.sort_values(["モジュール", "期間開始"])
        weekly_sorted["前回得点率"] = (
            weekly_sorted.groupby("モジュール")["平均得点率"].shift(1)
        )
        weekly_sorted["差分"] = weekly_sorted["平均得点率"] - weekly_sorted["前回得点率"]
        latest_rows = weekly_sorted.groupby("モジュール").tail(1)
        improvement = latest_rows.dropna(subset=["差分"])
        if not improvement.empty:
            best = improvement.sort_values("差分", ascending=False).iloc[0]
            if best["差分"] > 0:
                insights["check"] = (
                    f"『{best['モジュール']}』は直近週で得点率が{best['差分']:.1f}pt向上しています。"
                )
            else:
                insights["check"] = (
                    "各モジュールの得点率に大きな変化はありませんでした。"
                )

            worst = improvement.sort_values("差分").iloc[0]
            if worst["差分"] < 0:
                insights["act"] = (
                    f"『{worst['モジュール']}』は得点率が{abs(worst['差分']):.1f}pt低下。復習方針を見直しましょう。"
                )
        if not insights["check"]:
            insights["check"] = "週次データが1件のみのため推移分析はできません。"
        if not insights["act"]:
            fallback = sorted_by_score.iloc[0]
            insights["act"] = (
                f"平均得点率が伸び悩む『{fallback['事例']}』の復習素材を追加しましょう。"
            )
    else:
        insights["check"] = "週次データが不足しているため、推移把握のために演習を追加しましょう。"
        fallback = sorted_by_score.iloc[0]
        insights["act"] = (
            f"『{fallback['事例']}』の追加演習をスケジュールして改善施策を検証してください。"
        )

    return insights


def _prepare_learning_report_excel(tables: Dict[str, pd.DataFrame]) -> bytes:
    if not tables:
        return b""

    for engine in ("xlsxwriter", "openpyxl"):
        buffer = io.BytesIO()
        try:
            with pd.ExcelWriter(buffer, engine=engine) as writer:
                for sheet_name, df in tables.items():
                    clean_name = _sanitize_sheet_name(sheet_name)
                    df.to_excel(writer, index=False, sheet_name=clean_name)
            buffer.seek(0)
            return buffer.read()
        except ModuleNotFoundError:
            continue

    sanitized_tables: Dict[str, pd.DataFrame] = {}
    for sheet_name, df in tables.items():
        prepared = df.copy()
        for column in prepared.columns:
            if pd.api.types.is_datetime64_any_dtype(prepared[column]):
                prepared[column] = prepared[column].dt.strftime("%Y-%m-%d %H:%M:%S")
        sanitized_tables[_sanitize_sheet_name(sheet_name)] = prepared

    return _simple_xlsx_bytes(sanitized_tables)


def _sanitize_sheet_name(name: str) -> str:
    invalid_chars = set('[]:*?/\\')
    cleaned = "".join(ch for ch in name if ch not in invalid_chars)
    if not cleaned:
        cleaned = "Sheet"
    return cleaned[:31]


def _simple_xlsx_bytes(tables: Dict[str, pd.DataFrame]) -> bytes:
    timestamp = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
    sheet_entries: List[Tuple[str, str]] = []
    sheet_xml_parts: List[Tuple[str, str]] = []

    for idx, (name, df) in enumerate(tables.items(), start=1):
        sheet_id = f"sheet{idx}"
        sheet_xml = _dataframe_to_sheet_xml(df)
        sheet_entries.append((name, sheet_id))
        sheet_xml_parts.append((sheet_id, sheet_xml))

    content_types = [
        "<?xml version=\"1.0\" encoding=\"UTF-8\" standalone=\"yes\"?>",
        "<Types xmlns=\"http://schemas.openxmlformats.org/package/2006/content-types\">",
        "  <Default Extension=\"rels\" ContentType=\"application/vnd.openxmlformats-package.relationships+xml\"/>",
        "  <Default Extension=\"xml\" ContentType=\"application/xml\"/>",
        "  <Override PartName=\"/xl/workbook.xml\" ContentType=\"application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml\"/>",
        "  <Override PartName=\"/xl/styles.xml\" ContentType=\"application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml\"/>",
        "  <Override PartName=\"/docProps/core.xml\" ContentType=\"application/vnd.openxmlformats-package.core-properties+xml\"/>",
        "  <Override PartName=\"/docProps/app.xml\" ContentType=\"application/vnd.openxmlformats-officedocument.extended-properties+xml\"/>",
    ]
    for idx in range(1, len(sheet_entries) + 1):
        content_types.append(
            f"  <Override PartName=\"/xl/worksheets/sheet{idx}.xml\" ContentType=\"application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml\"/>"
        )
    content_types.append("</Types>")
    content_types_xml = "\n".join(content_types)

    rels_xml = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>
  <Relationship Id="rId2" Type="http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties" Target="docProps/core.xml"/>
  <Relationship Id="rId3" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/extended-properties" Target="docProps/app.xml"/>
</Relationships>
"""

    workbook_sheets = []
    workbook_rels = []
    for idx, (name, sheet_id) in enumerate(sheet_entries, start=1):
        workbook_sheets.append(
            f"  <sheet name=\"{escape(name)}\" sheetId=\"{idx}\" r:id=\"rId{idx}\"/>"
        )
        workbook_rels.append(
            f"  <Relationship Id=\"rId{idx}\" Type=\"http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet\" Target=\"worksheets/{sheet_id}.xml\"/>"
        )
    workbook_rels.append(
        "  <Relationship Id=\"rId{0}\" Type=\"http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles\" Target=\"styles.xml\"/>".format(
            len(sheet_entries) + 1
        )
    )

    workbook_xml = (
        "<?xml version=\"1.0\" encoding=\"UTF-8\" standalone=\"yes\"?>\n"
        "<workbook xmlns=\"http://schemas.openxmlformats.org/spreadsheetml/2006/main\" "
        "xmlns:r=\"http://schemas.openxmlformats.org/officeDocument/2006/relationships\">\n"
        "  <sheets>\n"
        + "\n".join(workbook_sheets)
        + "\n  </sheets>\n"
        + "</workbook>\n"
    )

    workbook_rels_xml = (
        "<?xml version=\"1.0\" encoding=\"UTF-8\" standalone=\"yes\"?>\n"
        "<Relationships xmlns=\"http://schemas.openxmlformats.org/package/2006/relationships\">\n"
        + "\n".join(workbook_rels)
        + "\n</Relationships>\n"
    )

    styles_xml = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
  <fonts count="1"><font><sz val="11"/><color theme="1"/><name val="Calibri"/><family val="2"/></font></fonts>
  <fills count="2"><fill><patternFill patternType="none"/></fill><fill><patternFill patternType="gray125"/></fill></fills>
  <borders count="1"><border><left/><right/><top/><bottom/><diagonal/></border></borders>
  <cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>
  <cellXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/></cellXfs>
  <cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles>
</styleSheet>
"""

    titles_vector = [
        "    <vt:lpstr>{}</vt:lpstr>".format(escape(name)) for name, _ in sheet_entries
    ]
    docprops_app = (
        "<?xml version=\"1.0\" encoding=\"UTF-8\" standalone=\"yes\"?>\n"
        "<Properties xmlns=\"http://schemas.openxmlformats.org/officeDocument/2006/extended-properties\" "
        "xmlns:vt=\"http://schemas.openxmlformats.org/officeDocument/2006/docPropsVTypes\">\n"
        "  <Application>Streamlit Report</Application>\n"
        "  <HeadingPairs>\n"
        "    <vt:vector size=\"2\" baseType=\"variant\">\n"
        "      <vt:variant><vt:lpstr>Worksheets</vt:lpstr></vt:variant>\n"
        "      <vt:variant><vt:i4>{}</vt:i4></vt:variant>\n"
        "    </vt:vector>\n"
        "  </HeadingPairs>\n"
        "  <TitlesOfParts>\n"
        "    <vt:vector size=\"{}\" baseType=\"lpstr\">\n"
        + "\n".join(titles_vector)
        + "\n    </vt:vector>\n"
        "  </TitlesOfParts>\n"
        "</Properties>\n"
    ).format(len(sheet_entries), len(sheet_entries))

    docprops_core = (
        "<?xml version=\"1.0\" encoding=\"UTF-8\" standalone=\"yes\"?>\n"
        "<cp:coreProperties xmlns:cp=\"http://schemas.openxmlformats.org/package/2006/metadata/core-properties\" "
        "xmlns:dc=\"http://purl.org/dc/elements/1.1/\" xmlns:dcterms=\"http://purl.org/dc/terms/\" "
        "xmlns:dcmitype=\"http://purl.org/dc/dcmitype/\" xmlns:xsi=\"http://www.w3.org/2001/XMLSchema-instance\">\n"
        "  <dc:creator>Learning Tracker</dc:creator>\n"
        "  <cp:lastModifiedBy>Learning Tracker</cp:lastModifiedBy>\n"
        f"  <dcterms:created xsi:type=\"dcterms:W3CDTF\">{timestamp}</dcterms:created>\n"
        f"  <dcterms:modified xsi:type=\"dcterms:W3CDTF\">{timestamp}</dcterms:modified>\n"
        "</cp:coreProperties>\n"
    )

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("[Content_Types].xml", content_types_xml)
        zf.writestr("_rels/.rels", rels_xml)
        zf.writestr("xl/workbook.xml", workbook_xml)
        zf.writestr("xl/_rels/workbook.xml.rels", workbook_rels_xml)
        zf.writestr("xl/styles.xml", styles_xml)
        zf.writestr("docProps/app.xml", docprops_app)
        zf.writestr("docProps/core.xml", docprops_core)
        for sheet_id, sheet_xml in sheet_xml_parts:
            zf.writestr(f"xl/worksheets/{sheet_id}.xml", sheet_xml)

    buffer.seek(0)
    return buffer.read()


def _excel_column_name(index: int) -> str:
    name = ""
    while index >= 0:
        index, remainder = divmod(index, 26)
        name = chr(65 + remainder) + name
        index -= 1
    return name


def _dataframe_to_sheet_xml(df: pd.DataFrame) -> str:
    header_cells = []
    for col_idx, column in enumerate(df.columns, start=1):
        cell_ref = f"{_excel_column_name(col_idx - 1)}1"
        header_cells.append(
            f"<c r=\"{cell_ref}\" t=\"inlineStr\"><is><t>{escape(str(column))}</t></is></c>"
        )

    rows_xml = [f"<row r=\"1\">{''.join(header_cells)}</row>"]

    for row_idx, row in enumerate(df.itertuples(index=False, name=None), start=2):
        cell_xmls: List[str] = []
        for col_idx, value in enumerate(row, start=1):
            if value is None or (isinstance(value, float) and math.isnan(value)):
                continue
            if pd.isna(value):
                continue
            cell_ref = f"{_excel_column_name(col_idx - 1)}{row_idx}"
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                cell_xmls.append(f"<c r=\"{cell_ref}\"><v>{value}</v></c>")
            else:
                text = escape(str(value))
                cell_xmls.append(
                    f"<c r=\"{cell_ref}\" t=\"inlineStr\"><is><t>{text}</t></is></c>"
                )
        rows_xml.append(f"<row r=\"{row_idx}\">{''.join(cell_xmls)}</row>")

    sheet_xml = (
        "<?xml version=\"1.0\" encoding=\"UTF-8\" standalone=\"yes\"?>\n"
        "<worksheet xmlns=\"http://schemas.openxmlformats.org/spreadsheetml/2006/main\" "
        "xmlns:r=\"http://schemas.openxmlformats.org/officeDocument/2006/relationships\">\n"
        "  <sheetData>\n"
        + "\n".join(rows_xml)
        + "\n  </sheetData>\n"
        + "</worksheet>\n"
    )
    return sheet_xml


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


def _prepare_dashboard_analysis_data(records: List[Dict[str, Any]]) -> Dict[str, Any]:
    if not records:
        return {
            "case_chart_source": pd.DataFrame(),
            "question_source": pd.DataFrame(),
            "question_order_labels": [],
            "keyword_source": pd.DataFrame(),
            "keyword_labels": [],
            "improvement_range": (0.10, 0.15),
        }

    def _case_order(label: str) -> int:
        try:
            return CASE_ORDER.index(label)
        except ValueError:
            return len(CASE_ORDER)

    case_stats: Dict[str, Dict[str, float]] = defaultdict(
        lambda: {
            "score_sum": 0.0,
            "score_count": 0,
            "coverage_sum": 0.0,
            "coverage_count": 0,
        }
    )
    question_stats: Dict[Tuple[str, int], Dict[str, float]] = defaultdict(
        lambda: {
            "score_sum": 0.0,
            "score_count": 0,
            "coverage_sum": 0.0,
            "coverage_count": 0,
        }
    )
    keyword_stats: Dict[Tuple[str, str], Dict[str, float]] = defaultdict(
        lambda: {"attempts": 0, "hits": 0}
    )

    question_numbers: Set[int] = set()

    for record in records:
        case_label = record.get("case_label") or "不明"
        max_score = record.get("max_score") or 0
        score = record.get("score") or 0
        keyword_hits: Dict[str, bool] = record.get("keyword_hits") or {}

        score_ratio: Optional[float]
        if max_score:
            try:
                score_ratio = score / max_score
            except ZeroDivisionError:
                score_ratio = None
        else:
            score_ratio = None

        coverage_ratio: Optional[float]
        if keyword_hits:
            coverage_ratio = sum(1 for hit in keyword_hits.values() if hit) / len(keyword_hits)
        else:
            coverage_ratio = None

        if score_ratio is not None:
            stat = case_stats[case_label]
            stat["score_sum"] += score_ratio
            stat["score_count"] += 1
        if coverage_ratio is not None:
            stat = case_stats[case_label]
            stat["coverage_sum"] += coverage_ratio
            stat["coverage_count"] += 1

        question_number = _normalize_question_number(record.get("question_order"))
        if question_number is not None:
            question_numbers.add(question_number)
            q_stat = question_stats[(case_label, question_number)]
            if score_ratio is not None:
                q_stat["score_sum"] += score_ratio
                q_stat["score_count"] += 1
            if coverage_ratio is not None:
                q_stat["coverage_sum"] += coverage_ratio
                q_stat["coverage_count"] += 1

        for keyword, hit in keyword_hits.items():
            k_stat = keyword_stats[(case_label, keyword)]
            k_stat["attempts"] += 1
            if hit:
                k_stat["hits"] += 1

    case_rows: List[Dict[str, Any]] = []
    for case_label, stat in case_stats.items():
        avg_score = (
            stat["score_sum"] / stat["score_count"] * 100
            if stat["score_count"]
            else None
        )
        avg_coverage = (
            stat["coverage_sum"] / stat["coverage_count"] * 100
            if stat["coverage_count"]
            else None
        )
        case_rows.append(
            {
                "事例": case_label,
                "平均得点率": avg_score,
                "平均キーワード網羅率": avg_coverage,
            }
        )

    case_df = pd.DataFrame(case_rows)
    if not case_df.empty:
        case_df["_order"] = case_df["事例"].map(_case_order)
        case_df.sort_values("_order", inplace=True)
        case_df.drop(columns=["_order"], inplace=True)
        case_chart_source = case_df.melt(
            id_vars=["事例"],
            value_vars=["平均得点率", "平均キーワード網羅率"],
            var_name="指標",
            value_name="値",
        )
    else:
        case_chart_source = case_df

    question_rows: List[Dict[str, Any]] = []
    for (case_label, question_number), stat in question_stats.items():
        avg_score = (
            stat["score_sum"] / stat["score_count"] * 100
            if stat["score_count"]
            else None
        )
        avg_coverage = (
            stat["coverage_sum"] / stat["coverage_count"] * 100
            if stat["coverage_count"]
            else None
        )
        question_rows.append(
            {
                "事例": case_label,
                "設問": f"第{question_number}問",
                "平均得点率": avg_score,
                "平均キーワード網羅率": avg_coverage,
                "設問番号": question_number,
            }
        )

    question_df = pd.DataFrame(question_rows)
    if not question_df.empty:
        question_df["_order"] = question_df["事例"].map(_case_order)
        question_df.sort_values(["_order", "設問番号"], inplace=True)
        question_df.drop(columns=["_order"], inplace=True)

    keyword_rows: List[Dict[str, Any]] = []
    for (case_label, keyword), stat in keyword_stats.items():
        attempts = stat["attempts"]
        if attempts == 0:
            continue
        hit_rate = stat["hits"] / attempts if attempts else None
        keyword_rows.append(
            {
                "事例": case_label,
                "キーワード": keyword,
                "網羅率": hit_rate * 100 if hit_rate is not None else None,
                "出題数": attempts,
            }
        )

    keyword_df = pd.DataFrame(keyword_rows)
    keyword_labels: List[str] = []
    if not keyword_df.empty:
        keyword_totals = (
            keyword_df.groupby("キーワード")["出題数"].sum().sort_values(ascending=False)
        )
        keyword_labels = keyword_totals.head(8).index.tolist()
        keyword_df = keyword_df[keyword_df["キーワード"].isin(keyword_labels)]
        keyword_df["_order"] = keyword_df["事例"].map(_case_order)
        keyword_df.sort_values(["_order", "キーワード"], inplace=True)
        keyword_df.drop(columns=["_order"], inplace=True)

    question_order_labels = [f"第{num}問" for num in sorted(question_numbers)]

    return {
        "case_chart_source": case_chart_source,
        "question_source": question_df,
        "question_order_labels": question_order_labels,
        "keyword_source": keyword_df,
        "keyword_labels": keyword_labels,
        "improvement_range": (0.10, 0.15),
    }


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

    _inject_practice_navigation_styles()

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
            .practice-tree .tree-level {
                margin-bottom: 0.75rem;
            }
            .practice-tree .tree-level .stRadio > div[role="radiogroup"] {
                display: flex;
                flex-wrap: wrap;
                gap: 0.5rem;
            }
            .practice-tree .tree-level .stRadio > div[role="radiogroup"] label {
                padding-left: 0.5rem;
                padding-right: 0.5rem;
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
        st.markdown('<div class="tree-level tree-level-case">', unsafe_allow_html=True)
        selected_case = st.radio(
            "事例I〜IV",
            case_options,
            key=case_key,
            label_visibility="collapsed",
            horizontal=True,
        )
        st.markdown("</div>", unsafe_allow_html=True)

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
            st.markdown('<div class="tree-level tree-level-year">', unsafe_allow_html=True)
            selected_year = st.radio(
                "↳ 年度 (R6/R5/R4…)",
                year_options,
                key=year_key,
                format_func=_format_reiwa_label,
                label_visibility="collapsed",
                horizontal=True,
            )
            st.markdown("</div>", unsafe_allow_html=True)

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

            st.markdown('<div class="tree-level tree-level-question">', unsafe_allow_html=True)
            selected_question_id = st.radio(
                "↳ 設問1〜",
                question_options,
                key=question_key,
                format_func=_format_question_option,
                label_visibility="collapsed",
                horizontal=True,
            )
            st.markdown("</div>", unsafe_allow_html=True)
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
                _render_question_insight_block(insight_text)
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
                    <div class="practice-context-column">
                        <div class="practice-context-inner">
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
            st.markdown(
                '<div class="context-search-control" role="search">',
                unsafe_allow_html=True,
            )
            with st.container():
                problem_identifier = (
                    problem.get("id")
                    or problem.get("slug")
                    or problem.get("title")
                    or "default"
                )
                search_query = st.text_input(
                    "与件文内検索",
                    key=f"context-search-{problem_identifier}",
                    placeholder="キーワードを入力",
                    help="与件文内の気になるキーワードを検索すると該当箇所がハイライトされます。",
                )
                search_feedback = st.empty()
            st.markdown("</div>", unsafe_allow_html=True)

            match_count = _render_problem_context_block(problem_context, search_query)

            normalized_query = (search_query or "").strip()
            if normalized_query:
                if match_count:
                    search_feedback.caption(f"該当箇所: {match_count}件")
                else:
                    search_feedback.caption("該当箇所は見つかりませんでした。")
            else:
                search_feedback.empty()

            st.markdown("</div></div></section></div></div>", unsafe_allow_html=True)
            _inject_context_panel_behavior()
    else:
        main_col = layout_container

    answers: List[RecordedAnswer] = []
    question_specs: List[QuestionSpec] = []
    submitted = False

    with main_col:
        st.markdown('<div class="practice-main-column">', unsafe_allow_html=True)
        question_entries: List[Dict[str, str]] = []
        for idx, q in enumerate(problem["questions"], start=1):
            anchor_id = f"question-q{idx}"
            header_id = f"{anchor_id}-header"
            raw_prompt = _normalize_text_block(q.get("prompt") or q.get("設問見出し") or "")
            preview_text = _format_preview_text(raw_prompt, 24) if raw_prompt else "概要未登録"
            label = f"設問{idx}"
            stepper_label = f"{label}：{preview_text}" if preview_text else label
            question_entries.append(
                {
                    "anchor": anchor_id,
                    "header_id": header_id,
                    "label": label,
                    "preview": preview_text,
                    "title": raw_prompt or label,
                    "stepper": stepper_label,
                }
            )

        question_count = len(question_entries)

        if question_entries:
            tab_items = "".join(
                (
                    "<li class=\"practice-tab-item\" role=\"presentation\">"
                    f"<a class=\"practice-tab-link\" role=\"tab\" data-anchor=\"{html.escape(entry['anchor'])}\" "
                    f"href=\"#{html.escape(entry['anchor'])}\" aria-controls=\"{html.escape(entry['anchor'])}\" "
                    f"title=\"{html.escape(entry['title'], quote=True)}\">{html.escape(entry['label'])}</a>"
                    "</li>"
                )
                for entry in question_entries
            )

            st.markdown(
                dedent(
                    f"""
                    <div class=\"practice-tab-wrapper\" aria-label=\"設問タブ\">
                        <nav id=\"practice-question-tabs\" class=\"practice-question-tabs\" role=\"navigation\" aria-label=\"設問タブ\">
                            <ol class=\"practice-tab-track\" role=\"tablist\">{tab_items}</ol>
                        </nav>
                    </div>
                    """
                ).strip(),
                unsafe_allow_html=True,
            )

            context_return_html = ""
            if problem_context:
                context_return_html = "\n" + dedent(
                    """
                        <button type=\"button\" class=\"practice-return-button practice-return-context-button\" aria-label=\"与件文に戻る\">
                            <span class=\"practice-return-button-icon\" aria-hidden=\"true\">
                                <svg viewBox=\"0 0 24 24\" focusable=\"false\" aria-hidden=\"true\">
                                    <path d=\"M5.5 4A2.5 2.5 0 0 1 8 1.5h6a1 1 0 0 1 1 1V19l-2.7-1.35a3.5 3.5 0 0 0-3.12 0L6.5 19H6a2 2 0 0 1-2-2V5.5A1.5 1.5 0 0 1 5.5 4z\" fill=\"currentColor\" />
                                    <path d=\"M19 1.5a1 1 0 0 1 1 1V19a2 2 0 0 1-2 2h-.5l-3.38-1.69a1.5 1.5 0 0 1-.82-1.34V2.5a1 1 0 0 1 1-1H19z\" fill=\"currentColor\" />
                                </svg>
                            </span>
                            <span class=\"practice-return-button-text\">与件文に戻る</span>
                        </button>
                    """
                ).strip()
            nav_items = "".join(
                (
                    "<li class=\"practice-toc-item\">"
                    f"<a class=\"practice-toc-link\" data-anchor=\"{html.escape(entry['anchor'])}\" "
                    f"href=\"#{html.escape(entry['anchor'])}\" data-index=\"{index}\" "
                    f"title=\"{html.escape(entry['title'], quote=True)}\""
                    f"{' aria-current=\"location\"' if index == 0 else ''}>"
                    f"<span class=\"practice-toc-index\">{html.escape(entry['label'])}</span>"
                    f"<span class=\"practice-toc-text\">{html.escape(entry['preview'])}</span>"
                    "</a></li>"
                )
                for index, entry in enumerate(question_entries)
            )
            st.markdown(
                dedent(
                    f"""
                    <nav id=\"practice-quick-nav\" class=\"practice-toc\" aria-label=\"設問セクション\">
                        <span class=\"practice-toc-label\">設問ナビ</span>
                        <ol class=\"practice-toc-track\" role=\"list\">{nav_items}</ol>
                    </nav>
                    """
                ),
                unsafe_allow_html=True,
            )
            st.markdown(
                dedent(
                    f"""
                    <div class=\"practice-floating-buttons\">
                        <button type=\"button\" class=\"practice-return-button practice-return-nav-button is-hidden\" aria-label=\"設問ナビに戻る\">
                            <span class=\"practice-return-button-icon\" aria-hidden=\"true\">
                                <svg viewBox=\"0 0 24 24\" focusable=\"false\" aria-hidden=\"true\">
                                    <path d=\"M12 5a1 1 0 0 1 .71.29l6 6a1 1 0 0 1-1.42 1.42L12 7.41l-5.29 5.3a1 1 0 0 1-1.42-1.42l6-6A1 1 0 0 1 12 5z\" fill=\"currentColor\" />
                                    <path d=\"M12 5a1 1 0 0 1 1 1v12a1 1 0 0 1-2 0V6a1 1 0 0 1 1-1z\" fill=\"currentColor\" />
                                </svg>
                            </span>
                            <span class=\"practice-return-button-text\">設問ナビに戻る</span>
                        </button>
                        {context_return_html}
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

        for idx, question in enumerate(problem["questions"], start=1):
            tone = _practice_tone_for_index(idx)
            entry = question_entries[idx - 1] if idx - 1 < len(question_entries) else None
            anchor_value = entry["anchor"] if entry else f"question-q{idx}"
            header_value = entry["header_id"] if entry else f"question-q{idx}-header"
            label_value = entry["stepper"] if entry else f"設問{idx}"
            st.markdown(
                (
                    f'<section class="practice-question-block" data-tone="{tone}" '
                    f'data-anchor-id="{html.escape(anchor_value)}" '
                    f'data-index="{idx}" '
                    f'data-label="{html.escape(label_value)}" '
                    f'role="region" aria-labelledby="{html.escape(header_value)}">'
                ),
                unsafe_allow_html=True,
            )
            text = _question_input(
                problem["id"],
                question,
                case_label=problem.get("case_label") or problem.get("case"),
                question_index=idx,
                anchor_id=anchor_value,
                header_id=header_value,
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

            st.markdown("</section>", unsafe_allow_html=True)
            if idx < question_count:
                st.markdown(
                    '<div class="practice-question-divider" aria-hidden="true"></div>',
                    unsafe_allow_html=True,
                )

        if question_entries:
            st.markdown(
                dedent(
                    """
                    <nav class="practice-stepper" aria-label="設問ステッパー">
                        <button type="button" class="practice-stepper-button" data-step="prev" data-anchor="" aria-disabled="true">
                            <span class="practice-stepper-main">前の設問</span>
                            <span class="practice-stepper-sub" aria-hidden="true"></span>
                        </button>
                        <button type="button" class="practice-stepper-button" data-step="next" data-anchor="">
                            <span class="practice-stepper-main">次の設問</span>
                            <span class="practice-stepper-sub" aria-hidden="true"></span>
                        </button>
                    </nav>
                    """
                ),
                unsafe_allow_html=True,
            )
            _inject_practice_navigation_script()

        st.markdown('<div id="practice-actions"></div>', unsafe_allow_html=True)

        submitted = st.button("AI採点に送信", type="primary")

        st.markdown('</div>', unsafe_allow_html=True)

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
                    axis_breakdown=result.axis_breakdown,
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
        st.markdown('<div class="tree-level tree-level-case">', unsafe_allow_html=True)
        selected_case = st.radio(
            "事例I〜IV",
            case_options,
            key=case_key,
            label_visibility="collapsed",
            horizontal=True,
        )
        st.markdown("</div>", unsafe_allow_html=True)

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
            st.markdown('<div class="tree-level tree-level-year">', unsafe_allow_html=True)
            selected_year = st.radio(
                "↳ 年度 (R6/R5/R4…)",
                year_options,
                key=year_key,
                format_func=_format_reiwa_label,
                label_visibility="collapsed",
                horizontal=True,
            )
            st.markdown("</div>", unsafe_allow_html=True)

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
                st.markdown('<div class="tree-level tree-level-question">', unsafe_allow_html=True)
                selected_question_key = st.radio(
                    "↳ 設問1〜",
                    question_keys,
                    key=question_key,
                    format_func=_format_question_option,
                    label_visibility="collapsed",
                    horizontal=True,
                )
                st.markdown("</div>", unsafe_allow_html=True)
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
                _render_question_insight_block(insight_text)
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
            axis_breakdown = answer.get("axis_breakdown") or {}
            if axis_breakdown:
                st.markdown("**観点別スコアの内訳**")
                _render_axis_breakdown(axis_breakdown)
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


def _render_axis_breakdown(axis_breakdown: Dict[str, Dict[str, object]]) -> None:
    axis_order = [axis["label"] for axis in scoring.EVALUATION_AXES]
    if not axis_breakdown or not axis_order:
        return

    display_rows = []
    chart_points = []
    for idx, metadata in enumerate(scoring.EVALUATION_AXES):
        label = metadata["label"]
        breakdown = axis_breakdown.get(label) or {}
        score_value = float(breakdown.get("score") or 0.0)
        detail = str(breakdown.get("detail") or metadata.get("description") or "")
        weight_pct = float(metadata.get("weight", 0.0)) * 100
        display_rows.append(
            {
                "観点": label,
                "スコア(%)": round(score_value * 100, 1),
                "配点比重(%)": round(weight_pct, 1),
                "評価コメント": detail,
            }
        )
        chart_points.append({"観点": label, "スコア": score_value, "order": idx})

    if not chart_points:
        return

    chart_df = pd.DataFrame(chart_points)
    if len(chart_df) > 1:
        chart_df = pd.concat([chart_df, chart_df.iloc[[0]]], ignore_index=True)
        chart_df.loc[chart_df.index[-1], "order"] = len(chart_points)
    chart_df["角度"] = chart_df["order"] / max(len(chart_points), 1) * 2 * math.pi

    area = (
        alt.Chart(chart_df)
        .mark_area(line={"color": "#0F6AB2"}, color="rgba(15, 106, 178, 0.25)")
        .encode(
            theta=alt.Theta("角度:Q", stack=None),
            radius=alt.Radius("スコア:Q", scale=alt.Scale(domain=[0, 1.05], nice=False)),
            tooltip=[
                alt.Tooltip("観点:N", title="観点"),
                alt.Tooltip("スコア:Q", title="スコア", format=".0%"),
            ],
        )
    )
    points = (
        alt.Chart(chart_df)
        .mark_point(size=90, color="#0F6AB2")
        .encode(
            theta=alt.Theta("角度:Q", stack=None),
            radius=alt.Radius("スコア:Q", scale=alt.Scale(domain=[0, 1.05], nice=False)),
        )
    )

    label_df = pd.DataFrame(
        {
            "観点": [metadata["label"] for metadata in scoring.EVALUATION_AXES],
            "角度": [idx / max(len(axis_order), 1) * 2 * math.pi for idx in range(len(axis_order))],
            "radius": [1.08 for _ in axis_order],
        }
    )
    labels = (
        alt.Chart(label_df)
        .mark_text(fontWeight="bold", color="#0F6AB2")
        .encode(
            theta=alt.Theta("角度:Q", stack=None),
            radius=alt.Radius("radius:Q", scale=alt.Scale(domain=[0, 1.1], nice=False)),
            text="観点:N",
        )
    )

    chart = (area + points + labels).properties(height=320)
    st.altair_chart(chart, use_container_width=True)

    detail_df = pd.DataFrame(display_rows)
    st.dataframe(detail_df, hide_index=True, use_container_width=True)
    st.caption("レーダーチャートは各観点の0〜100%スコアを示し、配点比重は総合得点への寄与度を表します。")


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
            question_total = len(problem["questions"])
            for idx, question in enumerate(problem["questions"], start=1):
                tone = _practice_tone_for_index(idx)
                st.markdown(
                    f'<section class="practice-question-block" data-tone="{tone}">',
                    unsafe_allow_html=True,
                )
                _question_input(
                    problem_id,
                    question,
                    widget_prefix="mock_textarea_",
                    case_label=problem.get("case_label") or problem.get("case"),
                    question_index=idx,
                )
                st.markdown("</section>", unsafe_allow_html=True)
                if idx < question_total:
                    st.markdown(
                        '<div class="practice-question-divider" aria-hidden="true"></div>',
                        unsafe_allow_html=True,
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
                        axis_breakdown=result.axis_breakdown,
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
    if "学習時間(分)" in history_df.columns:
        history_df["学習時間(分)"] = pd.to_numeric(
            history_df["学習時間(分)"], errors="coerce"
        ).fillna(0.0)
    else:
        history_df["学習時間(分)"] = 0.0
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
    report_data = _build_learning_report(filtered_df)

    overview_tab, chart_tab, report_tab, keyword_tab, detail_tab = st.tabs(
        ["一覧", "グラフ", "分析レポート", "キーワード分析", "詳細・エクスポート"]
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

    with report_tab:
        module_summary = report_data["module_summary"]
        if module_summary.empty:
            st.info("分析レポートを表示するには該当する演習データが必要です。")
        else:
            pdca = report_data["pdca"]
            st.markdown("#### PDCAハイライト")
            plan_col, do_col = st.columns(2)
            with plan_col:
                st.markdown("**Plan**")
                st.markdown(pdca.get("plan") or "重点対象を選ぶための演習データを蓄積しましょう。")
            with do_col:
                st.markdown("**Do**")
                st.markdown(pdca.get("do") or "直近の学習実績をもとに実行状況を確認します。")
            check_col, act_col = st.columns(2)
            with check_col:
                st.markdown("**Check**")
                st.markdown(pdca.get("check") or "週次推移を確認できるデータを集めましょう。")
            with act_col:
                st.markdown("**Act**")
                st.markdown(pdca.get("act") or "改善アクションを検討できるよう追加演習を実施しましょう。")

            st.markdown("#### モジュール別サマリ")
            module_display = module_summary.copy()
            if "直近実施日" in module_display.columns:
                module_display["直近実施日"] = pd.to_datetime(
                    module_display["直近実施日"], errors="coerce"
                ).dt.strftime("%Y-%m-%d")
            for column in ["平均得点", "直近得点"]:
                if column in module_display.columns:
                    module_display[column] = module_display[column].map(
                        lambda v: f"{v:.1f}" if pd.notna(v) else "-"
                    )
            for column in ["平均得点率", "直近得点率"]:
                if column in module_display.columns:
                    module_display[column] = module_display[column].map(
                        lambda v: f"{v:.1f}%" if pd.notna(v) else "-"
                    )
            if "学習時間(分)" in module_display.columns:
                module_display["学習時間(分)"] = module_display["学習時間(分)"].map(
                    lambda v: f"{v:.0f}"
                )
            if "学習時間(時間)" in module_display.columns:
                module_display["学習時間(時間)"] = module_display["学習時間(時間)"].map(
                    lambda v: f"{v:.1f}"
                )
            st.dataframe(module_display, use_container_width=True, hide_index=True)

            monthly_df = report_data["monthly_summary"]
            weekly_df = report_data["weekly_summary"]
            monthly_tab, weekly_tab_inner = st.tabs(["月次トレンド", "週次トレンド"])

            with monthly_tab:
                if monthly_df.empty:
                    st.info("月次トレンドを表示できるデータがありません。")
                else:
                    monthly_chart_df = monthly_df.sort_values("期間開始")
                    unique_months = monthly_chart_df["期間開始"].dropna().unique()
                    if len(unique_months) > 12:
                        allowed = set(sorted(unique_months)[-12:])
                        monthly_chart_df = monthly_chart_df[
                            monthly_chart_df["期間開始"].isin(allowed)
                        ]

                    score_chart = (
                        alt.Chart(monthly_chart_df)
                        .mark_line(point=True)
                        .encode(
                            x=alt.X("期間開始:T", title="月"),
                            y=alt.Y(
                                "平均得点率:Q",
                                title="平均得点率 (%)",
                                scale=alt.Scale(domain=[0, 100]),
                            ),
                            color="モジュール:N",
                            tooltip=[
                                "期間ラベル",
                                "モジュール",
                                alt.Tooltip("平均得点:Q", format=".1f"),
                                alt.Tooltip("平均得点率:Q", format=".1f"),
                                "演習回数",
                            ],
                        )
                    )
                    st.altair_chart(score_chart, use_container_width=True)

                    time_chart = (
                        alt.Chart(monthly_chart_df)
                        .mark_bar(opacity=0.65)
                        .encode(
                            x=alt.X("期間開始:T", title="月"),
                            y=alt.Y(
                                "学習時間(時間):Q",
                                title="学習時間 (時間)",
                                stack="zero",
                            ),
                            color="モジュール:N",
                            tooltip=[
                                "期間ラベル",
                                "モジュール",
                                alt.Tooltip("学習時間(時間):Q", format=".1f"),
                                "演習回数",
                            ],
                        )
                    )
                    st.altair_chart(time_chart, use_container_width=True)

                    monthly_table = monthly_chart_df.copy()
                    monthly_table["期間"] = monthly_table["期間ラベル"]
                    monthly_table["期間開始"] = monthly_table["期間開始"].dt.strftime("%Y-%m-%d")
                    monthly_table["平均得点"] = monthly_table["平均得点"].map(
                        lambda v: f"{v:.1f}" if pd.notna(v) else "-"
                    )
                    monthly_table["平均得点率"] = monthly_table["平均得点率"].map(
                        lambda v: f"{v:.1f}%" if pd.notna(v) else "-"
                    )
                    monthly_table["学習時間(時間)"] = monthly_table["学習時間(時間)"].map(
                        lambda v: f"{v:.1f}"
                    )
                    monthly_table["学習時間(分)"] = monthly_table["学習時間(分)"].map(
                        lambda v: f"{v:.0f}"
                    )
                    monthly_display_cols = [
                        "期間",
                        "モジュール",
                        "演習回数",
                        "学習時間(分)",
                        "学習時間(時間)",
                        "平均得点",
                        "平均得点率",
                    ]
                    st.dataframe(
                        monthly_table[monthly_display_cols],
                        use_container_width=True,
                        hide_index=True,
                    )

            with weekly_tab_inner:
                if weekly_df.empty:
                    st.info("週次トレンドを表示できるデータがありません。")
                else:
                    weekly_chart_df = weekly_df.sort_values("期間開始")
                    unique_weeks = weekly_chart_df["期間開始"].dropna().unique()
                    if len(unique_weeks) > 12:
                        allowed_weeks = set(sorted(unique_weeks)[-12:])
                        weekly_chart_df = weekly_chart_df[
                            weekly_chart_df["期間開始"].isin(allowed_weeks)
                        ]

                    weekly_score_chart = (
                        alt.Chart(weekly_chart_df)
                        .mark_line(point=True)
                        .encode(
                            x=alt.X("期間開始:T", title="週"),
                            y=alt.Y(
                                "平均得点率:Q",
                                title="平均得点率 (%)",
                                scale=alt.Scale(domain=[0, 100]),
                            ),
                            color="モジュール:N",
                            tooltip=[
                                "期間ラベル",
                                "モジュール",
                                alt.Tooltip("平均得点:Q", format=".1f"),
                                alt.Tooltip("平均得点率:Q", format=".1f"),
                                "演習回数",
                            ],
                        )
                    )
                    st.altair_chart(weekly_score_chart, use_container_width=True)

                    weekly_time_chart = (
                        alt.Chart(weekly_chart_df)
                        .mark_bar(opacity=0.65)
                        .encode(
                            x=alt.X("期間開始:T", title="週"),
                            y=alt.Y(
                                "学習時間(時間):Q",
                                title="学習時間 (時間)",
                                stack="zero",
                            ),
                            color="モジュール:N",
                            tooltip=[
                                "期間ラベル",
                                "モジュール",
                                alt.Tooltip("学習時間(時間):Q", format=".1f"),
                                "演習回数",
                            ],
                        )
                    )
                    st.altair_chart(weekly_time_chart, use_container_width=True)

                    weekly_table = weekly_chart_df.copy()
                    weekly_table["期間"] = weekly_table["期間ラベル"]
                    weekly_table["期間開始"] = weekly_table["期間開始"].dt.strftime("%Y-%m-%d")
                    weekly_table["平均得点"] = weekly_table["平均得点"].map(
                        lambda v: f"{v:.1f}" if pd.notna(v) else "-"
                    )
                    weekly_table["平均得点率"] = weekly_table["平均得点率"].map(
                        lambda v: f"{v:.1f}%" if pd.notna(v) else "-"
                    )
                    weekly_table["学習時間(時間)"] = weekly_table["学習時間(時間)"].map(
                        lambda v: f"{v:.1f}"
                    )
                    weekly_table["学習時間(分)"] = weekly_table["学習時間(分)"].map(
                        lambda v: f"{v:.0f}"
                    )
                    weekly_display_cols = [
                        "期間",
                        "モジュール",
                        "演習回数",
                        "学習時間(分)",
                        "学習時間(時間)",
                        "平均得点",
                        "平均得点率",
                    ]
                    st.dataframe(
                        weekly_table[weekly_display_cols],
                        use_container_width=True,
                        hide_index=True,
                    )

            export_tables = report_data.get("export", {})
            module_export = export_tables.get("モジュール別サマリ", pd.DataFrame())
            if not module_export.empty:
                module_csv = module_export.copy()
                if "直近実施日" in module_csv.columns:
                    module_csv["直近実施日"] = pd.to_datetime(
                        module_csv["直近実施日"], errors="coerce"
                    ).dt.strftime("%Y-%m-%d %H:%M:%S")
                csv_bytes = module_csv.to_csv(index=False).encode("utf-8-sig")
                st.download_button(
                    "モジュール別サマリをCSVでダウンロード",
                    data=csv_bytes,
                    file_name="learning_report_modules.csv",
                    mime="text/csv",
                )

            excel_bytes = _prepare_learning_report_excel(export_tables)
            if excel_bytes:
                st.download_button(
                    "学習レポートをExcelでダウンロード",
                    data=excel_bytes,
                    file_name="learning_report.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                )

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
