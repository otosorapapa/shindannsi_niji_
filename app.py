from __future__ import annotations

from collections import Counter, defaultdict
import copy
from datetime import date as dt_date, datetime, time as dt_time, timedelta, timezone
from pathlib import Path
from textwrap import dedent
from typing import Any, Dict, Iterable, List, Mapping, Optional, Pattern, Sequence, Set, Tuple
from uuid import uuid4
from urllib.parse import urlencode
import logging

import html
import hashlib
import difflib
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


def _extract_component_value(
    component_value: Any, *, key: Optional[str] = None
) -> Optional[str]:
    """Return the raw value emitted by a Streamlit component, if available."""

    if isinstance(component_value, str) and component_value:
        return component_value

    if key:
        state_value = st.session_state.get(key)
        if isinstance(state_value, str) and state_value:
            return state_value

    maybe_value = getattr(component_value, "value", None)
    if isinstance(maybe_value, str) and maybe_value:
        return maybe_value

    return None


NAVIGATION_REDIRECT_KEY = "_navigation_redirect"


def _request_navigation(target: str) -> None:
    """Schedule a navigation change for the next rerun."""

    if not target:
        return
    st.session_state[NAVIGATION_REDIRECT_KEY] = target
    st.session_state["page"] = target


import committee_analysis
import database
import export_utils
import keyword_analysis
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
CASE_ICON_MAP = {
    "事例I": "Ⅰ",
    "事例II": "Ⅱ",
    "事例III": "Ⅲ",
    "事例IV": "Ⅳ",
}


PROBLEM_TABLE_KEY_LABELS = {
    "balance_sheet": "貸借対照表",
    "income_statement": "損益計算書",
    "cash_flow": "キャッシュフロー計算書",
    "cash_flow_statement": "キャッシュフロー計算書",
    "manufacturing_cost": "製造原価報告書",
    "supplement": "補足資料",
    "supplementary": "補足資料",
    "supplemental": "補足資料",
}


GLOBAL_STYLESHEET_PATH = Path(__file__).parent / "assets" / "app.css"
HOME_DASHBOARD_HTML_PATH = Path(__file__).parent / "frontend" / "home_dashboard.html"


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
            "label": "7S",
            "snippet": "【7S視点】戦略: 市場・競争環境に適応した方向性を示す。組織: 権限配置と部門連携を再設計する。制度: 評価・報酬・ガバナンスを整える。人材: 採用・配置・育成で人材力を底上げする。スキル: 技術・暗黙知を体系化し共有する。スタイル: 風土とリーダーシップを協働型へ転換する。共有価値: 理念と強みを浸透させ一体感を醸成する。",
            "description": "ハード・ソフト両面から組織変革を網羅する基本枠組み。",
        },
        {
            "label": "VRIO",
            "snippet": "【VRIO分析】Value: 顧客価値を高める資源か。Rarity: 他社にない希少性があるか。Imitability: 模倣困難な仕組み・知見か。Organization: 活かす仕組みと人材配置が整っているか。→ 強みの活用と弱点補完の施策を導く。",
            "description": "自社資源の競争優位性と活用方針を整理する。",
        },
        {
            "label": "人事4機能",
            "snippet": "【人事4機能】採用: 求める人材像とチャネルを明確化。配置: 適所適材で強みを活かす。育成: OJT・研修・キャリアで能力向上を支援。評価・報酬: 目標管理と承認で納得性を高め定着を促す。",
            "description": "採用・配置・育成・評価報酬を連動させる視点。",
        },
        {
            "label": "モチベーション理論",
            "snippet": "【モチベーション理論】衛生要因を整備し不満を除去した上で、動機づけ要因（成長機会・承認・裁量）を強化する。期待理論では目標明確化・達成手段の提示・成果と報酬連動を設計する。",
            "description": "職務充実と評価・報酬の連動で意欲を高める。",
        },
    ],
    "事例II": [
        {
            "label": "3C/4P/4C",
            "snippet": "【3C/4P/4C】Customer/Customer Value: ターゲットのニーズ・価値期待を把握する。Competitor/Competition: 競合の強み・チャネル・価格を比較し差別化要素を決める。Company/Product: 自社資源を活かした提供価値・品揃えを整える。Price/Cost: 価値に見合う価格と負担感を設計。Place/Convenience: チャネル導線と利便性を最適化。Promotion/Communication: デジタルとリアルを統合し想起を高める。",
            "description": "顧客・競合・自社の分析から4P/4C施策へ落とし込む。",
        },
        {
            "label": "顧客価値",
            "snippet": "【顧客価値向上】機能価値: 品質・利便性を高める。情緒価値: 体験・ブランドストーリーで共感を喚起。経済価値: コスト削減やお得感を訴求。社会価値: 地域貢献・サステナビリティで信頼を獲得。",
            "description": "多面的な価値提供でロイヤルティを高める視点。",
        },
        {
            "label": "AIDMA/SIPS",
            "snippet": "【AIDMA/SIPS】AIDMA: Attention→Interest→Desire→Memory→Actionで購買導線を設計。SIPS: Sympathize→Identify→Participate→Shareで共感と共有を促す。オンラインとオフラインを組み合わせ顧客体験を設計する。",
            "description": "購買プロセスと共感拡散の両面から施策を構築。",
        },
    ],
    "事例III": [
        {
            "label": "QCD",
            "snippet": "【QCD改善】Quality: 不良要因の特定と標準化・教育で再発防止。Cost: 段取り短縮や歩留まり向上で原価圧縮。Delivery: 生産計画とリードタイム短縮で納期遵守。→ 改善サイクルを回し現場力を底上げする。",
            "description": "品質・コスト・納期の三要素で課題と施策を整理。",
        },
        {
            "label": "4M/5M",
            "snippet": "【4M/5M】Man: 人員・技能・教育体制。Machine: 設備稼働・保全。Material: 資材・在庫・調達。Method: 手順・標準化・段取り。必要に応じMeasurementを加えて管理指標を確認。",
            "description": "工程要因を網羅しボトルネックを抽出する。",
        },
        {
            "label": "IE/ECRS",
            "snippet": "【IE/ECRS】Eliminate: ムダ工程を排除。Combine: 工程統合・セル化。Rearrange: 動線・配置を最適化。Simplify: 手順を簡素化。データ計測と見える化で改善を定着させる。",
            "description": "工程分析から改善施策を導く定番フレーム。",
        },
        {
            "label": "5S",
            "snippet": "【5S】整理: 要不要を判別。整頓: 置き場と表示を整える。清掃: 異常を早期発見。清潔: ルール化・点検で維持。しつけ: 習慣化と教育で定着。→ 安全・品質・生産性を高める職場づくり。",
            "description": "現場改善の土台となる基本施策。",
        },
    ],
    "事例IV": [
        {
            "label": "財務比率",
            "snippet": "【財務比率】安全性: 流動比率・当座比率で短期支払能力を確認。効率性: 売上債権・棚卸資産・固定資産回転率で資産効率を測定。収益性: 売上高利益率・ROA・ROEで収益力を評価し改善策へつなげる。",
            "description": "主要指標の診断から改善提案まで整理できる。",
        },
        {
            "label": "CVP/NPV",
            "snippet": "【CVP/NPV】限界利益率と固定費で損益分岐点・安全余裕率を算出し、価格・数量・原価の打ち手を示す。投資案はキャッシュフローを見積もりNPVで採算性を評価、前提と感度を併せて提示する。",
            "description": "損益構造と投資採算を同時に整理する枠組み。",
        },
        {
            "label": "IRR・投資評価",
            "snippet": "【IRR・投資評価】内部収益率(IRR)を資本コストと比較し投資の妥当性を判断。回収期間や感度分析でリスクを補足し、キャッシュフロー改善策と合わせて提案する。",
            "description": "投資意思決定を数値根拠付きで説明する。",
        },
    ],
}
CASE_CAUSAL_TEMPLATES = {
    "事例I": [
        {
            "label": "組織連鎖",
            "diagram": "外部環境変化 → 組織・人材課題 → 施策(7S連動) → 効果",
            "snippet": "【組織連鎖】外部環境変化（例: 市場縮小・デジタル化）→ 組織・人材課題（権限集中・人材定着難）→ 施策（権限移譲と情報共有、評価・報酬再設計、育成強化）→ 効果（意思決定迅速化・モチベーション向上・離職率低下）。",
        },
        {
            "label": "人事サイクル",
            "diagram": "採用 → 配置 → 育成 → 評価/報酬 → 定着",
            "snippet": "【人事サイクル】採用で理念共感人材を獲得→ 適所配置で強みを活かす→ OJTと研修で能力開発→ 目標管理・多面評価と納得性ある報酬→ 成果承認とキャリア提示で定着・エンゲージメント向上。",
        },
    ],
    "事例II": [
        {
            "label": "顧客-競合-自社",
            "diagram": "顧客期待 ↔ 自社価値提案 ↔ 競合動向",
            "snippet": "【顧客-競合-自社】顧客期待（例: 体験価値・即時性）↔ 自社価値提案（差別化機能・ブランドストーリー）↔ 競合動向（低価格・デジタル施策）を対比し、価値訴求とチャネル施策を設計する。",
        },
        {
            "label": "チャネル連携",
            "diagram": "認知 → 来店/訪問 → 体験 → 購買 → 継続",
            "snippet": "【チャネル連携】認知（SNS・PR）→ 来店/訪問導線（イベント・広告）→ 体験価値（試用・接客）→ 購買（EC/店舗連携で利便性）→ 継続（会員・CRM・口コミ拡散）を一貫設計する。",
        },
    ],
    "事例III": [
        {
            "label": "4M因果",
            "diagram": "人(Man) ↔ 機械(Machine) ↔ 材料(Material) ↔ 方法(Method)",
            "snippet": "【4M因果】人(技能不足・教育遅れ)→ 方法(標準作業未整備)→ 機械(段取り長期・保全不足)→ 材料(在庫滞留)→ QCD悪化。多能工化・標準化・保全強化・在庫適正化でスループット向上。",
        },
        {
            "label": "ボトルネック解除",
            "diagram": "需要変動 → 制約工程負荷増 → 在庫/遅延 → 改善策",
            "snippet": "【ボトルネック解除】需要変動で制約工程の負荷が上昇→ 仕掛在庫・遅延発生→ 外段取り化・ラインバランス調整・かんばん導入で平準化→ リードタイム短縮と納期遵守。",
        },
    ],
    "事例IV": [
        {
            "label": "資金循環",
            "diagram": "売上計画 → キャッシュフロー → 運転資金 → 投資/返済",
            "snippet": "【資金循環】売上計画と粗利確保→ キャッシュフロー把握→ 運転資金管理（回収・支払・在庫の回転短縮）→ 投資・返済計画を整備し資金繰りを安定化する。",
        },
        {
            "label": "収益改善",
            "diagram": "売上拡大策 + 原価低減策 → 利益改善 → 再投資",
            "snippet": "【収益改善】売上拡大（単価向上・数量増・新チャネル）と原価低減（歩留まり改善・間接費削減）を同時に実施→ 利益改善→ 成長投資・借入返済に再投資するサイクルを描く。",
        },
    ],
}


SELF_EVALUATION_DEFAULT = "未評価"
SELF_EVALUATION_OPTIONS = [
    ("手応えあり", 0.0),
    ("概ねOK", 0.25),
    ("やや不安", 0.6),
    ("難しかった", 0.85),
]
SELF_EVALUATION_LABELS = [SELF_EVALUATION_DEFAULT] + [label for label, _ in SELF_EVALUATION_OPTIONS]
SELF_EVALUATION_SCORE_MAP = {label: score for label, score in SELF_EVALUATION_OPTIONS}


def _self_evaluation_score(label: Optional[str]) -> Optional[float]:
    if not label:
        return None
    return SELF_EVALUATION_SCORE_MAP.get(label)


def _self_evaluation_label(score: Optional[float]) -> str:
    if score is None:
        return SELF_EVALUATION_DEFAULT
    for label, threshold in reversed(SELF_EVALUATION_OPTIONS):
        if score >= threshold - 1e-6:
            return label
    return SELF_EVALUATION_OPTIONS[0][0]


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
    elif name_lower.endswith(".json"):
        try:
            text = file_bytes.decode("utf-8")
        except UnicodeDecodeError:
            text = file_bytes.decode("utf-8", errors="ignore")
        payload = json.loads(text or "{}")
        if isinstance(payload, list):
            df = pd.DataFrame(payload)
        elif isinstance(payload, dict):
            for key in ("records", "entries", "items", "questions"):
                if key in payload and isinstance(payload[key], list):
                    df = pd.DataFrame(payload[key])
                    break
            else:
                df = pd.DataFrame([payload])
        else:
            raise ValueError("JSONの形式を解釈できませんでした。配列または records/items キーを持つオブジェクトを指定してください。")
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


def _normalize_problem_tables(raw: Any) -> List[Dict[str, str]]:
    normalized: List[Dict[str, str]] = []
    seen_texts: Set[str] = set()

    def _first_content_line(text: str) -> str:
        for line in text.splitlines():
            candidate = line.strip()
            if not candidate:
                continue
            if candidate.startswith(("(", "（")):
                continue
            return candidate
        return ""

    def _label_from_key(key: Optional[str], text: str, index: int) -> str:
        base_key = (str(key or "").strip().lower())
        label = PROBLEM_TABLE_KEY_LABELS.get(base_key)
        if not label and key:
            label = str(key).replace("_", " ").title()
        if not label:
            label = f"資料{index + 1}"
        first_line = _first_content_line(text)
        if first_line and len(first_line) <= 32:
            return first_line
        return label

    def _append_entry(label: str, text: str) -> None:
        trimmed = text.strip()
        if not trimmed:
            return
        signature = trimmed
        if signature in seen_texts:
            return
        seen_texts.add(signature)
        normalized.append({"label": label, "text": trimmed})

    def _walk(value: Any, *, key: Optional[str] = None) -> None:
        if isinstance(value, dict):
            for sub_key, sub_value in value.items():
                _walk(sub_value, key=str(sub_key))
            return
        if isinstance(value, (list, tuple, set)):
            for item in value:
                _walk(item, key=key)
            return
        text = _normalize_text_block(value)
        if not text:
            return
        label = _label_from_key(key, text, len(normalized))
        _append_entry(label, text)

    _walk(raw)
    return normalized


def _render_problem_tables(tables: Sequence[Mapping[str, str]]) -> None:
    if not tables:
        return

    st.markdown("##### 添付資料")
    st.caption("財務諸表などの表形式データをテキストで確認できます。")
    for index, table in enumerate(tables, start=1):
        label = table.get("label") or f"資料{index}"
        text = table.get("text") or ""
        with st.expander(str(label), expanded=False):
            st.code(str(text), language="text")


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


def _render_practice_timer(
    problem_id: Optional[int], *, default_minutes: int = 80, confirm_on_start: bool = False
) -> Dict[str, Any]:
    """Render a countdown timer for記述式演習 with start/pause controls."""

    if problem_id is None:
        st.caption("タイマーは問題選択後に利用できます。")
        return {}

    state_key = f"practice_timer::{problem_id}"
    state = st.session_state.setdefault(
        state_key,
        {
            "duration_seconds": int(default_minutes * 60),
            "running": False,
            "start_timestamp": None,
            "accumulated_seconds": 0.0,
            "expired": False,
        },
    )

    duration_key = f"{state_key}::duration"
    current_minutes = max(10, int(state["duration_seconds"] // 60)) if state["duration_seconds"] else default_minutes
    selected_minutes = int(
        st.number_input(
            "制限時間 (分)",
            min_value=10,
            max_value=120,
            step=5,
            value=current_minutes,
            key=duration_key,
            help="演習時間を設定するとカウントダウンが始められます。80分の本試験形式が基本です。",
        )
    )
    if selected_minutes * 60 != state["duration_seconds"]:
        state["duration_seconds"] = selected_minutes * 60
        state["accumulated_seconds"] = 0.0
        state["start_timestamp"] = None
        state["running"] = False
        state["expired"] = False

    control_cols = st.columns([0.34, 0.33, 0.33])
    confirm_state_key = f"{state_key}::confirm"
    pending_start = False
    if confirm_on_start:
        if control_cols[0].button("タイマー開始", key=f"{state_key}::start"):
            st.session_state[confirm_state_key] = True
    else:
        if control_cols[0].button("タイマー開始", key=f"{state_key}::start"):
            pending_start = True
    if pending_start:
        state["start_timestamp"] = datetime.now(timezone.utc).timestamp()
        state["running"] = True
        state["expired"] = False
    if control_cols[1].button("一時停止", key=f"{state_key}::pause"):
        if state["running"] and state.get("start_timestamp") is not None:
            now_ts = datetime.now(timezone.utc).timestamp()
            state["accumulated_seconds"] = min(
                state["duration_seconds"],
                state["accumulated_seconds"] + max(0.0, now_ts - state["start_timestamp"]),
            )
        state["running"] = False
        state["start_timestamp"] = None
    if control_cols[2].button("リセット", key=f"{state_key}::reset"):
        state["running"] = False
        state["start_timestamp"] = None
        state["accumulated_seconds"] = 0.0
        state["expired"] = False

    confirm_payload = None
    if confirm_on_start and st.session_state.get(confirm_state_key):
        confirm_html = dedent(
            """
            <script>
            (function() {
                if (window.case1TimerConfirm) {
                    return;
                }
                window.case1TimerConfirm = true;
                const confirmed = window.confirm('タイマーを開始しますか？\n開始後はカウントダウンがスタートします。');
                if (!window.Streamlit) {
                    window.Streamlit = { setComponentValue: () => {}, setComponentReady: () => {}, setFrameHeight: () => {} };
                }
                if (window.Streamlit.setComponentReady) {
                    window.Streamlit.setComponentReady();
                }
                if (window.Streamlit.setFrameHeight) {
                    window.Streamlit.setFrameHeight(0);
                }
                if (window.Streamlit.setComponentValue) {
                    window.Streamlit.setComponentValue(JSON.stringify({
                        type: 'timer-confirm',
                        confirmed: confirmed
                    }));
                }
                window.case1TimerConfirm = false;
            })();
            </script>
            """
        ).strip()
        confirm_component = components.html(confirm_html, height=0)
        confirm_payload = _extract_component_value(
            confirm_component, key=f"{confirm_state_key}::payload"
        )

    if confirm_payload:
        st.session_state.pop(confirm_state_key, None)
        try:
            parsed = json.loads(confirm_payload)
        except json.JSONDecodeError:
            parsed = None
        if isinstance(parsed, dict) and parsed.get("type") == "timer-confirm":
            if parsed.get("confirmed"):
                state["start_timestamp"] = datetime.now(timezone.utc).timestamp()
                state["running"] = True
                state["expired"] = False
            else:
                state["running"] = False
                state["start_timestamp"] = None

    elapsed = state["accumulated_seconds"]
    if state["running"] and state.get("start_timestamp") is not None:
        now_ts = datetime.now(timezone.utc).timestamp()
        elapsed = min(
            state["duration_seconds"],
            state["accumulated_seconds"] + max(0.0, now_ts - state["start_timestamp"]),
        )

    remaining = max(state["duration_seconds"] - elapsed, 0.0)
    if state["running"] and remaining <= 0:
        state["running"] = False
        state["expired"] = True
        state["accumulated_seconds"] = float(state["duration_seconds"])

    minutes = int(remaining // 60)
    seconds = int(remaining % 60)
    formatted_remaining = f"{minutes:02d}:{seconds:02d}"
    progress_ratio = (
        elapsed / state["duration_seconds"] if state["duration_seconds"] else 0.0
    )
    progress_ratio = max(0.0, min(progress_ratio, 1.0))

    html_id = f"timer-{problem_id}-{uuid.uuid4().hex}"
    timer_html = dedent(
        f"""
        <div id="{html_id}" data-duration="{state['duration_seconds']}" data-running="{str(state['running']).lower()}"
             data-start="{state.get('start_timestamp') or ''}" data-accumulated="{state['accumulated_seconds']}"
             data-expired="{str(state['expired']).lower()}" data-remaining="{remaining}">
            <div class="timer-wrapper">
                <div class="timer-display">{formatted_remaining}</div>
                <div class="timer-progress"><div class="timer-progress__bar" style="width: {progress_ratio * 100:.1f}%"></div></div>
                <div class="timer-status">{'計測中' if state['running'] else ('時間切れ' if state['expired'] else '待機中')}</div>
            </div>
        </div>
        <style>
            .timer-wrapper {{
                border-radius: 16px;
                padding: 0.85rem 1rem;
                background: linear-gradient(135deg, rgba(59,130,246,0.08), rgba(37,99,235,0.18));
                box-shadow: inset 0 0 0 1px rgba(59,130,246,0.18);
            }}
            .timer-display {{
                font-size: 2rem;
                font-weight: 700;
                color: #1f2937;
                text-align: center;
                letter-spacing: 0.04em;
            }}
            .timer-progress {{
                margin-top: 0.6rem;
                height: 8px;
                border-radius: 999px;
                background: rgba(148,163,184,0.25);
                overflow: hidden;
            }}
            .timer-progress__bar {{
                height: 100%;
                background: linear-gradient(90deg, #2563eb, #22d3ee);
            }}
            .timer-status {{
                margin-top: 0.4rem;
                font-size: 0.85rem;
                text-align: center;
                color: #475569;
            }}
        </style>
        <script>
            (function() {{
                const root = document.getElementById("{html_id}");
                if (!root) {{
                    return;
                }}
                const duration = parseFloat(root.dataset.duration) || 0;
                const accumulated = parseFloat(root.dataset.accumulated) || 0;
                const startTimestamp = parseFloat(root.dataset.start) || null;
                const running = root.dataset.running === "true";
                const expired = root.dataset.expired === "true";
                const initialRemaining = parseFloat(root.dataset.remaining) || 0;
                const display = root.querySelector('.timer-display');
                const bar = root.querySelector('.timer-progress__bar');
                const status = root.querySelector('.timer-status');

                const formatNumber = (value) => value.toString().padStart(2, '0');
                const formatTime = (seconds) => {{
                    const mins = Math.floor(seconds / 60);
                    const secs = Math.floor(seconds % 60);
                    return `${{formatNumber(mins)}}:${{formatNumber(secs)}}`;
                }};

                if (!window.Streamlit) {{
                    window.Streamlit = {{ setComponentValue: () => {{}}, setFrameHeight: () => {{}}, setComponentReady: () => {{}} }};
                }}
                if (window.Streamlit.setFrameHeight) {{
                    window.Streamlit.setFrameHeight();
                }}
                if (window.Streamlit.setComponentReady) {{
                    window.Streamlit.setComponentReady();
                }}

                const tick = () => {{
                    const now = Date.now() / 1000;
                    let elapsed = accumulated;
                    if (running && startTimestamp) {{
                        elapsed += Math.max(0, now - startTimestamp);
                    }}
                    let remaining = Math.max(0, duration - elapsed);
                    display.textContent = formatTime(remaining);
                    if (bar) {{
                        const ratio = duration ? Math.min(1, Math.max(0, elapsed / duration)) : 0;
                        const ratioPercent = Math.max(0, Math.min(100, ratio * 100));
                        bar.style.width = `${{ratioPercent.toFixed(1)}}%`;
                    }}
                    if (status) {{
                        status.textContent = running ? '計測中' : (expired || remaining <= 0 ? '時間切れ' : '待機中');
                    }}
                    if (!expired && remaining <= 0.01) {{
                        if (window.Streamlit.setComponentValue) {{
                            window.Streamlit.setComponentValue(JSON.stringify({{
                                type: 'timer',
                                status: 'expired',
                                timestamp: new Date().toISOString()
                            }}));
                        }}
                        clearInterval(timerId);
                    }}
                }};

                if (running || (!running && !expired && initialRemaining !== duration)) {{
                    const timerId = window.setInterval(tick, 1000);
                    tick();
                }} else {{
                    display.textContent = formatTime(initialRemaining);
                }}
            }})();
        </script>
        """
    )

    component_value = components.html(
        timer_html,
        height=160,
    )

    payload_raw = _extract_component_value(component_value)
    if payload_raw:
        try:
            payload = json.loads(payload_raw)
        except json.JSONDecodeError:
            payload = None
        else:
            if (
                isinstance(payload, dict)
                and payload.get("type") == "timer"
                and payload.get("status") == "expired"
            ):
                state["running"] = False
                state["expired"] = True
                state["accumulated_seconds"] = float(state["duration_seconds"])

    if state.get("expired"):
        st.error("時間切れです。本番同様の制限で復習モードに切り替えましょう。", icon="⏰")

    return state


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
    st.session_state.setdefault("question_activity", {})
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
    st.session_state.setdefault("_global_styles_injected", False)
    st.session_state.setdefault("_intent_card_styles_injected", False)
    st.session_state.setdefault("_question_card_styles_injected", False)
    st.session_state.setdefault("_timeline_styles_injected", False)
    st.session_state.setdefault("_practice_question_styles_injected", False)
    st.session_state.setdefault("_tag_styles_injected", False)
    st.session_state.setdefault("model_answer_slots", {})
    st.session_state.setdefault("history_focus_attempt", None)
    st.session_state.setdefault("history_focus_from_notification", False)

    for state_key in list(st.session_state.keys()):
        if state_key.endswith("_styles_injected"):
            st.session_state[state_key] = False

    query_params = st.query_params
    nav_targets = query_params.get("nav")
    attempt_targets = query_params.get("attempt")
    processed_query = False
    if nav_targets:
        nav_value = nav_targets[0]
        if nav_value == "history":
            _request_navigation("学習履歴")
            st.session_state["history_focus_from_notification"] = True
            if attempt_targets:
                attempt_token = attempt_targets[0]
                try:
                    st.session_state["history_focus_attempt"] = int(attempt_token)
                except (TypeError, ValueError):
                    st.session_state["history_focus_attempt"] = None
            processed_query = True
    if attempt_targets and not processed_query:
        try:
            st.session_state["history_focus_attempt"] = int(attempt_targets[0])
            processed_query = True
        except (TypeError, ValueError):
            st.session_state["history_focus_attempt"] = None

    if processed_query:
        for key in ("nav", "attempt"):
            if key in st.query_params:
                del st.query_params[key]


def _guideline_visibility_key(problem_id: int, question_id: int) -> str:
    return f"guideline_visible::{problem_id}::{question_id}"


def _inject_global_styles() -> None:
    digest_key = "_global_styles_digest"

    try:
        css = GLOBAL_STYLESHEET_PATH.read_text(encoding="utf-8")
    except FileNotFoundError:
        logging.getLogger(__name__).warning(
            "Global stylesheet %s not found; skipping injection", GLOBAL_STYLESHEET_PATH
        )
        st.session_state.pop(digest_key, None)
        return

    css_digest = hashlib.sha256(css.encode("utf-8")).hexdigest()
    if st.session_state.get(digest_key) == css_digest:
        return

    st.markdown(f"<style>{css}</style>", unsafe_allow_html=True)
    st.session_state[digest_key] = css_digest


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
                text-decoration: none;
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
            .practice-answer-section {
                scroll-margin-top: 110px;
            }
            .answer-panel-label,
            .support-panel-label {
                font-size: 0.82rem;
                letter-spacing: 0.08em;
                font-weight: 700;
                text-transform: uppercase;
                color: var(--practice-text-muted);
                margin: 0;
            }
            .autosave-indicator {
                display: inline-flex;
                align-items: center;
                gap: 0.4rem;
                padding: 0.35rem 0.75rem;
                border-radius: 999px;
                border: 1px solid rgba(148, 163, 184, 0.45);
                background: rgba(248, 250, 252, 0.92);
                font-size: 0.78rem;
                color: var(--practice-text-muted);
                justify-content: flex-end;
            }
            .autosave-indicator__toggle {
                font-weight: 700;
                color: var(--practice-text-strong);
                letter-spacing: 0.04em;
            }
            .autosave-indicator__status {
                display: inline-flex;
                align-items: baseline;
                gap: 0.2rem;
            }
            .autosave-indicator__time {
                font-variant-numeric: tabular-nums;
                font-weight: 600;
                color: var(--practice-text-strong);
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


def _inject_tag_styles() -> None:
    if st.session_state.get("_tag_styles_injected"):
        return

    st.markdown(
        dedent(
            """
            <style>
            .tag-pill-group {
                display: flex;
                flex-wrap: wrap;
                gap: 0.4rem;
                margin: 0.25rem 0 0.5rem;
            }
            .tag-pill {
                display: inline-flex;
                align-items: center;
                padding: 0.15rem 0.55rem 0.2rem;
                border-radius: 999px;
                font-size: 0.82rem;
                font-weight: 600;
                background: rgba(59, 130, 246, 0.12);
                color: #1d4ed8;
                border: 1px solid rgba(59, 130, 246, 0.18);
                letter-spacing: 0.01em;
            }
            .tag-pill[data-tone="warn"] {
                background: rgba(248, 113, 113, 0.16);
                color: #b91c1c;
                border-color: rgba(248, 113, 113, 0.32);
            }
            .beta-badge {
                display: inline-flex;
                align-items: center;
                justify-content: center;
                padding: 0.1rem 0.45rem;
                margin-left: 0.4rem;
                font-size: 0.68rem;
                font-weight: 700;
                border-radius: 999px;
                background: rgba(37, 99, 235, 0.16);
                color: #1d4ed8;
                border: 1px solid rgba(37, 99, 235, 0.32);
                text-transform: uppercase;
                letter-spacing: 0.08em;
            }
            </style>
            """
        ),
        unsafe_allow_html=True,
    )
    st.session_state["_tag_styles_injected"] = True


def _render_tag_pills(tags: Iterable[str], *, tone: str = "default") -> None:
    cleaned: List[str] = [str(tag).strip() for tag in tags if str(tag).strip()]
    if not cleaned:
        return

    _inject_tag_styles()

    def _tag_span(label: str) -> str:
        safe_label = html.escape(label)
        tone_attr = " data-tone=\"warn\"" if tone == "warn" else ""
        return f"<span class='tag-pill'{tone_attr} role='listitem'>{safe_label}</span>"

    tag_html = "".join(_tag_span(label) for label in cleaned)
    st.markdown(
        f"<div class='tag-pill-group' role='list'>{tag_html}</div>",
        unsafe_allow_html=True,
    )


def _compact_text(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _format_preview_text(text: str, max_length: int = 72) -> str:
    compact = _compact_text(text)
    if len(compact) <= max_length:
        return compact
    return compact[: max_length - 1].rstrip(" 、。.,;・") + "…"


def _queue_textarea_update(textarea_state_key: str, new_text: str) -> None:
    if not textarea_state_key:
        return

    pending_updates = st.session_state.setdefault("_pending_textarea_updates", {})
    pending_updates[textarea_state_key] = new_text


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
    _queue_textarea_update(textarea_state_key, new_text)


def _normalize_intent_card_list(raw_cards: Any) -> List[Dict[str, str]]:
    normalized: List[Dict[str, str]] = []

    def _walk(value: Any) -> None:
        if isinstance(value, dict):
            label = value.get("label")
            example = value.get("example")
            if label and example:
                normalized.append({"label": str(label), "example": str(example)})
        elif isinstance(value, (list, tuple)):
            for item in value:
                _walk(item)

    _walk(raw_cards)
    return normalized


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
            a[title="Manage app"] {
                position: fixed;
                right: 1.5rem !important;
                bottom: calc(env(safe-area-inset-bottom, 0px) + 1.5rem) !important;
                z-index: 90 !important;
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
                a[title="Manage app"] {
                    bottom: calc(env(safe-area-inset-bottom, 0px) + 0.75rem) !important;
                    right: 1rem !important;
                }
            }
            </style>
            """
        ),
        unsafe_allow_html=True,
    )
    st.session_state["_context_panel_styles_injected_v3"] = True


def _inject_context_panel_behavior() -> None:
    if st.session_state.get("_context_panel_behavior_injected_v2"):
        return

    script = dedent(
        """
        <script>
        (() => {
            const parentWin = window.parent && window.parent.document ? window.parent : window;
            let parentDoc = null;
            try {
                parentDoc = parentWin.document;
            } catch (error) {
                parentDoc = window.document;
            }
            if (!parentDoc) {
                return;
            }

            const setupContextPanel = () => {
                const doc = parentDoc;
                const win = parentWin;
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
                    const rootStyles = win.getComputedStyle(doc.documentElement);
                    const rawOffset = rootStyles.getPropertyValue('--context-panel-offset');
                    const parsed = parseFloat(rawOffset);
                    return Number.isFinite(parsed) ? parsed : 72;
                };

                const updateScrollbarCompensation = () => {
                    if (!panel || !scrollArea) {
                        return;
                    }}
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
                    }}
                    column.style.removeProperty('--context-column-min-height');
                    const media = mq || win.matchMedia('(max-width: 900px)');
                    if (media.matches) {
                        return;
                    }
                    const offset = getPanelOffset();
                    const viewportHeight = Math.max(0, win.innerHeight - offset - 16);
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
                        win.requestAnimationFrame(updateScrollbarCompensation);
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

                const mediaQuery = win.matchMedia('(max-width: 900px)');
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
                    win.addEventListener(
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

            if (parentDoc.readyState === 'loading') {
                parentDoc.addEventListener('DOMContentLoaded', setupContextPanel, { once: true });
            } else {
                setupContextPanel();
            }
        })();
        </script>
        """
    )
    components.html(script, height=0, width=0)
    st.session_state["_context_panel_behavior_injected_v2"] = True


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
            .practice-sidebar-nav {
                margin-top: 1.4rem;
                display: flex;
                flex-direction: column;
                gap: 0.45rem;
                padding: 0.8rem 1rem 1rem;
                border-radius: 18px;
                border: 1px solid rgba(148, 163, 184, 0.35);
                background: rgba(248, 250, 252, 0.95);
                box-shadow: 0 12px 24px rgba(15, 23, 42, 0.08);
            }
            .practice-sidebar-nav__title {
                font-size: 0.82rem;
                letter-spacing: 0.08em;
                font-weight: 700;
                text-transform: uppercase;
                color: #1d4ed8;
                margin: 0;
            }
            .practice-sidebar-nav__caption {
                font-size: 0.75rem;
                color: #475569;
                margin: 0 0 0.35rem;
            }
            .practice-sidebar-nav__list {
                list-style: none;
                margin: 0;
                padding: 0;
                display: flex;
                flex-direction: column;
                gap: 0.45rem;
            }
            .practice-sidebar-nav__link {
                display: flex;
                align-items: flex-start;
                gap: 0.5rem;
                padding: 0.45rem 0.6rem;
                border-radius: 12px;
                text-decoration: none;
                border: 1px solid transparent;
                color: #1f2937;
                font-weight: 600;
                transition: background 0.2s ease, border-color 0.2s ease, color 0.2s ease;
            }
            .practice-sidebar-nav__link:hover {
                background: rgba(219, 234, 254, 0.55);
                border-color: rgba(59, 130, 246, 0.35);
                color: #1d4ed8;
            }
            .practice-sidebar-nav__link.is-active,
            .practice-sidebar-nav__link[aria-current="location"] {
                background: rgba(59, 130, 246, 0.12);
                border-color: rgba(59, 130, 246, 0.45);
                color: #1d4ed8;
                box-shadow: 0 6px 16px rgba(59, 130, 246, 0.18);
            }
            .practice-sidebar-nav__index {
                font-size: 0.78rem;
                color: #2563eb;
                min-width: 3.1rem;
            }
            .practice-sidebar-nav__text {
                font-size: 0.78rem;
                color: #475569;
                flex: 1 1 auto;
                line-height: 1.45;
            }
            @media (max-width: 960px) {
                .practice-sidebar-nav {
                    display: none;
                }
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
                .practice-sidebar-nav {
                    background: rgba(17, 24, 39, 0.9);
                    border-color: rgba(148, 163, 184, 0.35);
                    box-shadow: 0 12px 32px rgba(2, 6, 23, 0.55);
                }
                .practice-sidebar-nav__caption {
                    color: rgba(226, 232, 240, 0.7);
                }
                .practice-sidebar-nav__title {
                    color: #93c5fd;
                }
                .practice-sidebar-nav__link {
                    color: #e2e8f0;
                    border-color: rgba(148, 163, 184, 0.2);
                }
                .practice-sidebar-nav__link:hover {
                    background: rgba(59, 130, 246, 0.25);
                    border-color: rgba(96, 165, 250, 0.45);
                    color: #bfdbfe;
                }
                .practice-sidebar-nav__link.is-active,
                .practice-sidebar-nav__link[aria-current="location"] {
                    background: rgba(59, 130, 246, 0.35);
                    border-color: rgba(96, 165, 250, 0.6);
                    color: #bfdbfe;
                }
                .practice-sidebar-nav__text {
                    color: rgba(203, 213, 225, 0.88);
                }
                .practice-sidebar-nav__index {
                    color: #93c5fd;
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


def _render_practice_sidebar_shortcuts(entries: Sequence[Mapping[str, str]]) -> None:
    if not entries:
        return

    nav_parts: List[str] = []
    for entry in entries:
        anchor = html.escape(entry.get("anchor", ""))
        title = html.escape(entry.get("title", ""), quote=True)
        label_text = html.escape(entry.get("label", ""))
        preview_text = html.escape(entry.get("preview", ""))
        nav_parts.append(
            (
                "<li class=\"practice-sidebar-nav__item\">"
                f"<a class=\"practice-sidebar-nav__link\" data-anchor=\"{anchor}\" "
                f"href=\"#{anchor}\" title=\"{title}\">"
                f"<span class=\"practice-sidebar-nav__index\">{label_text}</span>"
                f"<span class=\"practice-sidebar-nav__text\">{preview_text}</span>"
                "</a></li>"
            )
        )
    nav_items = "".join(nav_parts)

    sidebar_html = dedent(
        f"""
        <nav class="practice-sidebar-nav" aria-label="設問ショートカット">
            <p class="practice-sidebar-nav__title">設問ショートカット</p>
            <p class="practice-sidebar-nav__caption">クリックすると該当の設問にジャンプします。</p>
            <ul class="practice-sidebar-nav__list" role="list">{nav_items}</ul>
        </nav>
        """
    )
    st.sidebar.markdown(sidebar_html, unsafe_allow_html=True)


def _inject_practice_navigation_script() -> None:
    st.markdown(
        dedent(
            """
            <script>
            (() => {
                let win = window;
                let doc = window.document;
                try {
                    if (window.parent && window.parent !== window && window.parent.document) {
                        win = window.parent;
                        doc = win.document;
                    }
                } catch (error) {
                    win = window;
                    doc = window.document;
                }
                if (!doc) {
                    return;
                }

                const sections = Array.from(doc.querySelectorAll('.practice-question-block'));
                const navLinks = Array.from(
                    doc.querySelectorAll('.practice-toc-link, .practice-tab-link, .practice-sidebar-nav__link')
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
    context_text: str,
    search_query: Optional[str] = None,
    *,
    snapshot_key: Optional[str] = None,
    auto_palette: bool = False,
    auto_save: bool = False,
    compact_controls: bool = False,
) -> Tuple[int, Optional[Dict[str, Any]]]:
    normalized = _normalize_text_block(context_text)
    if not normalized:
        return 0, None

    paragraphs: List[str] = []
    for raw_block in normalized.replace("\r\n", "\n").replace("\r", "\n").split("\n\n"):
        paragraph = raw_block.strip()
        if paragraph:
            paragraphs.append(paragraph)

    if not paragraphs:
        return 0, None

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
        return total_matches, None

    element_id = f"problem-context-{uuid.uuid4().hex}"
    toolbar_id = f"{element_id}-toolbar"
    total_lines = sum(block.count("<br/>") + 1 for block in blocks)
    estimated_height = max(620, min(1200, 260 + total_lines * 30))

    palette_classes = ["marker-palette"]
    if auto_palette:
        palette_classes.append("is-collapsed")
    palette_class_attr = " ".join(palette_classes)

    if compact_controls:
        clear_button_html = (
            f"<button type=\"button\" class=\"toolbar-button clear icon-only\" "
            f"data-action=\"clear-all\" data-target=\"{element_id}\" "
            "aria-label=\"マーカーを全て解除\"><span class=\"icon\">🗑️</span></button>"
        )
    else:
        clear_button_html = (
            f"<button type=\"button\" class=\"toolbar-button clear\" data-action=\"clear-all\" "
            f"data-target=\"{element_id}\">マーカーを全て解除</button>"
        )

    if auto_save:
        capture_button_html = ""
        hint_text = "テキストを選択し色をクリックすると、ハイライトが即時に適用・保存されます。"
    else:
        capture_button_html = (
            f"<button type=\"button\" class=\"toolbar-button save\" data-action=\"capture\" "
            f"data-target=\"{element_id}\">ハイライトを保存</button>"
        )
        hint_text = "テキストをドラッグして蛍光マーカーを適用できます。"

    highlight_html = dedent(
        f"""
        <div class="problem-context-root">
            <div class="context-toolbar" id="{toolbar_id}">
                <div class="toolbar-actions">
                    <button type="button" class="toolbar-button toggle" data-action="highlight" data-target="{element_id}" aria-pressed="false" data-default-color="gold">
                        選択範囲にマーカー
                    </button>
                    <div class="{palette_class_attr}" role="group" aria-label="マーカー色">
                        <button type="button" class="marker-color selected" data-action="set-color" data-color="gold" aria-label="ゴールドマーカー"></button>
                        <button type="button" class="marker-color" data-action="set-color" data-color="violet" aria-label="バイオレットマーカー"></button>
                        <button type="button" class="marker-color" data-action="set-color" data-color="cerulean" aria-label="セルリアンマーカー"></button>
                        <button type="button" class="marker-color" data-action="set-color" data-color="teal" aria-label="ティールマーカー"></button>
                    </div>
                    <div class="search-navigation" data-target="{element_id}" aria-label="検索結果ナビゲーション">
                        <button type="button" class="toolbar-button search" data-action="search-prev" aria-label="前の検索結果" disabled>
                            前へ
                        </button>
                        <span class="search-navigation__status" aria-live="polite">0 / 0</span>
                        <button type="button" class="toolbar-button search" data-action="search-next" aria-label="次の検索結果" disabled>
                            次へ
                        </button>
                    </div>
                    <button type="button" class="toolbar-button undo" data-action="undo" aria-disabled="true" disabled>
                        直前の操作を取り消す
                    </button>
                    {clear_button_html}
                    {capture_button_html}
                </div>
                <span class="toolbar-hint">{html.escape(hint_text)}</span>
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
            .toolbar-button.icon-only {{
                width: 2.3rem;
                height: 2.3rem;
                padding: 0;
                display: inline-flex;
                align-items: center;
                justify-content: center;
            }}
            .toolbar-button.icon-only .icon {{
                font-size: 1rem;
                line-height: 1;
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
            .marker-palette.is-collapsed {{
                display: none;
            }}
            .marker-palette.is-active {{
                display: inline-flex;
            }}
            .search-navigation {{
                display: inline-flex;
                align-items: center;
                gap: 0.45rem;
                margin-left: auto;
                padding: 0.25rem 0.6rem;
                border-radius: 999px;
                background: rgba(255, 255, 255, 0.75);
                box-shadow: inset 0 0 0 1px rgba(148, 163, 184, 0.25);
            }}
            .search-navigation__status {{
                font-size: 0.78rem;
                font-weight: 600;
                color: #1d4ed8;
                min-width: 3.2rem;
                text-align: center;
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
            .toolbar-button.search {{
                background: rgba(59, 130, 246, 0.12);
                color: #1d4ed8;
                box-shadow: inset 0 0 0 1px rgba(37, 99, 235, 0.28);
                padding: 0.3rem 0.75rem;
            }}
            .toolbar-button.search:disabled {{
                background: rgba(226, 232, 240, 0.85);
                color: rgba(100, 116, 139, 0.75);
                box-shadow: inset 0 0 0 1px rgba(148, 163, 184, 0.28);
                cursor: not-allowed;
                opacity: 0.9;
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
            .problem-context-block mark.context-search-hit.is-active {{
                background: linear-gradient(transparent 35%, rgba(59, 130, 246, 0.85) 35%);
                box-shadow: 0 0 0 1px rgba(29, 78, 216, 0.4);
                color: #0f172a;
            }}
            @media (prefers-color-scheme: dark) {{
                .search-navigation {{
                    background: rgba(30, 41, 59, 0.7);
                    box-shadow: inset 0 0 0 1px rgba(148, 163, 184, 0.35);
                }}
                .search-navigation__status {{
                    color: #bfdbfe;
                }}
                .toolbar-button.search {{
                    background: rgba(59, 130, 246, 0.2);
                    color: #bfdbfe;
                }}
                .toolbar-button.search:disabled {{
                    background: rgba(71, 85, 105, 0.6);
                    color: rgba(148, 163, 184, 0.85);
                    box-shadow: inset 0 0 0 1px rgba(71, 85, 105, 0.6);
                }}
                .problem-context-block mark.context-search-hit.is-active {{
                    background: linear-gradient(transparent 35%, rgba(59, 130, 246, 0.6) 35%);
                    color: #e2e8f0;
                }}
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
                const captureButton = toolbar.querySelector('[data-action="capture"]');
                const colorButtons = Array.from(toolbar.querySelectorAll('[data-action="set-color"]'));
                const searchPrevButton = toolbar.querySelector('[data-action="search-prev"]');
                const searchNextButton = toolbar.querySelector('[data-action="search-next"]');
                const searchStatus = toolbar.querySelector('.search-navigation__status');
                const palette = toolbar.querySelector('.marker-palette');
                const autoPalette = {json.dumps(auto_palette)};
                const autoSave = {json.dumps(auto_save)};

                let highlightMode = false;
                let activeColor = (highlightButton && highlightButton.dataset.defaultColor) || (colorButtons[0] && colorButtons[0].dataset.color) || "gold";
                const history = [];
                const maxHistory = 30;
                const collectSearchMarks = () => Array.from(container.querySelectorAll('mark.context-search-hit'));
                let activeSearchIndex = -1;

                const showPalette = () => {{
                    if (!palette) {{
                        return;
                    }}
                    palette.classList.add('is-active');
                    palette.classList.remove('is-collapsed');
                }};

                const setSearchControlsDisabled = (disabled) => {{
                    [searchPrevButton, searchNextButton].forEach((button) => {{
                        if (!button) {{
                            return;
                        }}
                        button.disabled = disabled;
                        button.setAttribute('aria-disabled', disabled ? 'true' : 'false');
                    }});
                }};

                const updateSearchNavigation = (direction = 0) => {{
                    if (!searchStatus) {{
                        return;
                    }}
                    const marks = collectSearchMarks();
                    const total = marks.length;
                    if (!total) {{
                        activeSearchIndex = -1;
                        setSearchControlsDisabled(true);
                        searchStatus.textContent = '0 / 0';
                        marks.forEach((mark) => mark.classList.remove('is-active'));
                        return;
                    }}
                    if (direction !== 0) {{
                        activeSearchIndex = (activeSearchIndex + direction + total) % total;
                    }} else if (activeSearchIndex < 0 || activeSearchIndex >= total) {{
                        activeSearchIndex = 0;
                    }}
                    setSearchControlsDisabled(false);
                    marks.forEach((mark, index) => {{
                        mark.classList.toggle('is-active', index === activeSearchIndex);
                    }});
                    searchStatus.textContent = `${{activeSearchIndex + 1}} / ${{total}}`;
                    const target = marks[activeSearchIndex];
                    if (target && typeof target.scrollIntoView === 'function') {{
                        target.scrollIntoView({{ behavior: 'smooth', block: 'center' }});
                    }}
                }};

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
                updateSearchNavigation();

                if (searchPrevButton) {{
                    searchPrevButton.addEventListener('click', () => updateSearchNavigation(-1));
                }}
                if (searchNextButton) {{
                    searchNextButton.addEventListener('click', () => updateSearchNavigation(1));
                }}

                const setHighlightMode = (value) => {{
                    highlightMode = Boolean(value);
                    if (highlightButton) {{
                        highlightButton.classList.toggle("active", highlightMode);
                        highlightButton.setAttribute("aria-pressed", highlightMode ? "true" : "false");
                    }}
                    if (highlightMode && autoPalette) {{
                        showPalette();
                    }}
                }};

                const highlightSelection = (color) => {{
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
                    const appliedColor = color || activeColor || 'gold';
                    mark.className = "fluorescent-marker color-" + appliedColor;
                    mark.appendChild(range.extractContents());
                    range.insertNode(mark);
                    container.normalize();
                    selection.removeAllRanges();
                    pushHistory(snapshot);
                    if (autoSave) {{
                        emitSnapshot();
                    }}
                    return true;
                }};

                const applyHighlight = () => highlightSelection(activeColor);

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
                    if (autoSave) {{
                        emitSnapshot();
                    }}
                    return true;
                }};

                const serializeHighlights = () => {{
                    const marks = Array.from(container.querySelectorAll("mark.fluorescent-marker"));
                    const entries = marks.map((mark) => {{
                        const classes = Array.from(mark.classList || []);
                        const colorClass = classes.find((cls) => cls.startsWith("color-")) || "color-gold";
                        return {{
                            text: mark.textContent || "",
                            color: colorClass.replace("color-", ""),
                        }};
                    }});
                    return {{
                        type: 'highlightSnapshot',
                        html: container.innerHTML,
                        marks: entries,
                        plain_text: container.innerText || container.textContent || "",
                        timestamp: new Date().toISOString(),
                    }};
                }};

                const emitSnapshot = () => {{
                    const payload = serializeHighlights();
                    if (window.Streamlit && window.Streamlit.setComponentValue) {{
                        window.Streamlit.setComponentValue(JSON.stringify(payload));
                    }}
                }};

                const scheduleAutoHighlight = () => {{
                    if (!highlightMode) {{
                        return;
                    }}
                    requestAnimationFrame(() => {{
                        if (applyHighlight()) {{
                            if (autoPalette) {{
                                showPalette();
                            }}
                        }}
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

                if (captureButton) {{
                    captureButton.addEventListener("click", () => {{
                        emitSnapshot();
                        captureButton.classList.add("saved");
                        window.setTimeout(() => captureButton.classList.remove("saved"), 1200);
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
                            const highlighted = highlightSelection(nextColor);
                            if (!highlighted && highlightMode) {{
                                requestAnimationFrame(() => {{
                                    applyHighlight();
                                }});
                            }}
                            if (autoPalette) {{
                                showPalette();
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

                if (autoPalette) {{
                    document.addEventListener('selectionchange', () => {{
                        const selection = document.getSelection();
                        if (!selection || selection.rangeCount === 0) {{
                            return;
                        }}
                        const range = selection.getRangeAt(0);
                        if (range.collapsed) {{
                            return;
                        }}
                        if (!container.contains(range.commonAncestorContainer)) {{
                            return;
                        }}
                        showPalette();
                    }});
                }}

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

    component_value = components.html(
        highlight_html,
        height=estimated_height,
        scrolling=True,
    )

    snapshot: Optional[Dict[str, Any]] = None
    payload_raw = _extract_component_value(component_value)
    if payload_raw:
        try:
            payload = json.loads(payload_raw)
        except json.JSONDecodeError:
            payload = None
        else:
            if isinstance(payload, dict) and payload.get("type") == "highlightSnapshot":
                snapshot = payload

    return total_matches, snapshot


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
    cards = _normalize_intent_card_list(question.get("intent_cards"))
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
                    width="stretch",
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
    available_cases = [label for label in ("事例I", "事例II", "事例III", "事例IV") if CASE_FRAME_SHORTCUTS.get(label)]
    if not available_cases:
        return

    if case_label and case_label in available_cases:
        ordered_cases = [case_label] + [label for label in available_cases if label != case_label]
    else:
        ordered_cases = available_cases

    st.markdown(
        "<div class='mock-right-panel-spacer'></div>",
        unsafe_allow_html=True,
    )

    tabs = st.tabs(ordered_cases)
    for tab, label in zip(tabs, ordered_cases):
        frames = CASE_FRAME_SHORTCUTS.get(label, [])
        icon = CASE_ICON_MAP.get(label, "")
        heading = f"{icon} {label}".strip()
        with tab:
            st.markdown(f"#### {heading} 頻出フレーム", unsafe_allow_html=False)
            if not frames:
                st.info("登録されているフレームがありません。")
                continue
            if label == case_label:
                st.caption("事例別に定番の切り口をカード形式でまとめました。クリックで挿入できます。")
            else:
                st.caption(f"{label} の代表的なフレーム集です。参考として活用してください。")

            for index, frame in enumerate(frames):
                snippet = frame.get("snippet") or ""
                description = frame.get("description") or ""
                card_html = dedent(
                    """
                    <div class='mock-frame-card'>
                        <h5>{title}</h5>
                        <p>{description}</p>
                        <pre>{snippet}</pre>
                    </div>
                    """
                ).format(
                    title=html.escape(frame.get("label") or f"フレーム{index + 1}"),
                    description=html.escape(description),
                    snippet=html.escape(snippet),
                )
                st.markdown(card_html, unsafe_allow_html=True)
                if st.button(
                    "このテンプレートを挿入",
                    key=f"case-frame-insert::{draft_key}::{label}::{index}",
                    use_container_width=True,
                ):
                    _insert_template_snippet(draft_key, textarea_state_key, snippet)
                    st.session_state["_case_frame_notice"] = {
                        "draft_key": draft_key,
                        "label": frame.get("label"),
                    }


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

    analysis_text = "\n".join(analysis_lines)
    draft_state_key = f"{prefix}_draft"
    st.session_state[draft_state_key] = analysis_text

    st.markdown("**④ 示唆ドラフト**")
    st.caption("計算結果を要約した文章をコピーして答案骨子に活用できます。必要に応じてテキストとして保存も可能です。")
    st.text_area(
        "ドラフト (自動生成)",
        value=st.session_state[draft_state_key],
        height=140,
        key=draft_state_key,
        disabled=True,
    )
    if analysis_text.strip():
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        st.download_button(
            "ドラフトをテキストでダウンロード",
            data=analysis_text.encode("utf-8"),
            file_name=f"cvp_draft_{timestamp}.txt",
            mime="text/plain",
            key=f"{prefix}_draft_download",
            help="計算メモをローカルに保存し、答案作成や復習時に再利用できます。",
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

def main_view() -> None:
    user = st.session_state.user

    _inject_global_styles()
    _inject_tag_styles()

    navigation_items = {
        "ホーム": dashboard_page,
        "過去問演習": practice_page,
        "模擬試験": mock_exam_page,
        "学習履歴": history_page,
        "設定": settings_page,
    }
    navigation_icons = {
        "ホーム": "🏠",
        "過去問演習": "📝",
        "模擬試験": "🎯",
        "学習履歴": "📊",
        "設定": "⚙️",
    }

    navigation_key = "navigation_selection"
    redirect_target = st.session_state.pop(NAVIGATION_REDIRECT_KEY, None)
    if redirect_target in navigation_items:
        st.session_state[navigation_key] = redirect_target
        st.session_state["page"] = redirect_target

    st.sidebar.title("ナビゲーション")
    st.sidebar.markdown(
        dedent(
            """
            <style>
            section[data-testid="stSidebar"] div[role="radiogroup"] > label[data-baseweb="radio"] {
                margin-bottom: 0.45rem;
            }
            section[data-testid="stSidebar"] div[role="radiogroup"] > label[data-baseweb="radio"] > div:first-child {
                display: none;
            }
            section[data-testid="stSidebar"] div[role="radiogroup"] > label[data-baseweb="radio"] > div:last-child {
                width: 100%;
                padding: 0.65rem 0.85rem;
                border-radius: 0.9rem;
                border: 1px solid transparent;
                background: rgba(15, 23, 42, 0.03);
                transition: background-color 0.2s ease, border-color 0.2s ease, color 0.2s ease, transform 0.2s ease;
            }
            section[data-testid="stSidebar"] div[role="radiogroup"] > label[data-baseweb="radio"] > div:last-child:hover {
                border-color: rgba(37, 99, 235, 0.3);
                background-color: rgba(37, 99, 235, 0.12);
                transform: translateX(2px);
            }
            section[data-testid="stSidebar"] div[role="radiogroup"] > label[data-baseweb="radio"] > input:checked + div {
                background-color: rgba(37, 99, 235, 0.2);
                border-color: rgba(37, 99, 235, 0.45);
                color: #1d4ed8;
                box-shadow: inset 0 0 0 1px rgba(255, 255, 255, 0.45);
                font-weight: 700;
            }
            section[data-testid="stSidebar"] div[role="radiogroup"] > label[data-baseweb="radio"] > input:checked + div p {
                color: #1d4ed8;
            }
            @media (max-width: 960px) {
                section[data-testid="stSidebar"] {
                    display: none !important;
                }
                [data-testid="stAppViewContainer"] > .main {
                    padding-left: 0 !important;
                }
                .block-container {
                    padding: calc(3.6rem + env(safe-area-inset-top, 0px)) 1rem 2.75rem;
                    max-width: 100%;
                }
            }
            </style>
            """
        ).strip(),
        unsafe_allow_html=True,
    )

    nav_labels = list(navigation_items.keys())
    current_page = st.session_state.get("page")
    if current_page not in navigation_items:
        current_page = nav_labels[0]
    st.session_state.page = current_page

    if navigation_key not in st.session_state:
        st.session_state[navigation_key] = current_page
    elif st.session_state[navigation_key] not in navigation_items:
        st.session_state[navigation_key] = current_page

    selected_page = st.sidebar.radio(
        "ページを選択",
        nav_labels,
        key=navigation_key,
        format_func=lambda label: f"{navigation_icons.get(label, '•')} {label}",
    )

    st.session_state.page = selected_page

    st.sidebar.divider()
    st.sidebar.info(f"利用者: {user['name']} ({user['plan']}プラン)")
    st.sidebar.caption(
        "必要な情報にすぐアクセスできるよう、ページ別にコンテンツを整理しています。"
    )
    st.sidebar.markdown("---")
    with st.sidebar.expander("ヘルプとお問い合わせ", expanded=False):
        st.markdown(
            "- 📘 [クイックスタートガイド](#)\n"
            "- 💬 サポート: support@example.com\n"
            "- ❓ よくある質問はホームのヘルプから確認できます。"
        )

    page = st.session_state.get(navigation_key)
    if page not in navigation_items:
        page = nav_labels[0]
        st.session_state[navigation_key] = page
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
                --brand: #2563eb;
                --brand-strong: #1d4ed8;
                --accent-green: #0f766e;
                --accent-amber: #b45309;
                --pastel-blue: #e7f0ff;
                --pastel-green: #e3f6f1;
                --pastel-yellow: #fff5e0;
                --pastel-pink: #ffe8f2;
                --text-body: #111827;
                --text-muted: #4b5563;
                --text-faint: #6b7280;
                --border-soft: rgba(148, 163, 184, 0.32);
                --border-strong: rgba(71, 85, 105, 0.58);
                --shadow-card: 0 18px 32px rgba(15, 23, 42, 0.1);
            }
            .answer-editor {
                border: 2px dashed rgba(37, 99, 235, 0.24);
                border-radius: 20px;
                padding: 0.85rem 1rem 0.9rem;
                background: rgba(219, 234, 254, 0.18);
                margin: 0.85rem 0 0.75rem;
                transition: border-color 0.2s ease, box-shadow 0.2s ease, background 0.2s ease;
            }
            .answer-editor:focus-within {
                border-color: rgba(37, 99, 235, 0.55);
                box-shadow: 0 0 0 4px rgba(191, 219, 254, 0.45);
                background: rgba(219, 234, 254, 0.32);
            }
            .answer-editor .stTextArea textarea {
                border-radius: 16px;
                border: 1px solid rgba(148, 163, 184, 0.48);
                background: rgba(255, 255, 255, 0.98);
                color: #0f172a;
                box-shadow: inset 0 2px 6px rgba(15, 23, 42, 0.08);
            }
            .answer-editor .stTextArea textarea:focus-visible {
                border-color: rgba(37, 99, 235, 0.65);
                box-shadow: 0 0 0 2px rgba(191, 219, 254, 0.45);
            }
            .answer-editor .stTextArea textarea::placeholder {
                color: rgba(51, 65, 85, 0.7);
            }
            .answer-editor.answer-editor--note {
                background: rgba(240, 249, 255, 0.45);
                border-style: solid;
                border-color: rgba(59, 130, 246, 0.3);
            }
            .answer-editor.answer-editor--note .stTextArea textarea {
                min-height: 180px;
            }
            .retrieval-bullet-preview {
                margin: 0.4rem 0 0.1rem;
                padding-left: 1.1rem;
                color: #1f2937;
            }
            .retrieval-bullet-preview li {
                margin: 0.1rem 0;
                font-size: 0.86rem;
            }
            @media (prefers-color-scheme: dark) {
                .answer-editor {
                    border-color: rgba(59, 130, 246, 0.38);
                    background: rgba(30, 41, 59, 0.38);
                }
                .answer-editor:focus-within {
                    border-color: rgba(147, 197, 253, 0.65);
                    box-shadow: 0 0 0 3px rgba(59, 130, 246, 0.45);
                    background: rgba(30, 41, 59, 0.55);
                }
                .answer-editor .stTextArea textarea {
                    background: rgba(15, 23, 42, 0.92);
                    color: #e2e8f0;
                    border-color: rgba(100, 116, 139, 0.55);
                }
                .answer-editor .stTextArea textarea:focus-visible {
                    box-shadow: 0 0 0 2px rgba(59, 130, 246, 0.45);
                }
                .answer-editor .stTextArea textarea::placeholder {
                    color: rgba(203, 213, 225, 0.7);
                }
                .answer-editor.answer-editor--note {
                    background: rgba(30, 41, 59, 0.46);
                    border-color: rgba(59, 130, 246, 0.45);
                }
                .retrieval-bullet-preview {
                    color: rgba(226, 232, 240, 0.9);
                }
                .retrieval-bullet-preview li {
                    color: inherit;
                }
            }
            body,
            [data-testid="stAppViewContainer"] * {
                font-family: "Noto Sans JP", "Hiragino Sans", "Yu Gothic", sans-serif;
                color: var(--text-body);
                letter-spacing: 0.01em;
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
            .dashboard-lane__eyebrow {
                display: flex;
                align-items: center;
                gap: 0.6rem;
                font-size: 0.78rem;
                color: var(--text-muted);
                margin: 0 0 0.35rem;
                flex-wrap: wrap;
            }
            .lane-badge {
                display: inline-flex;
                align-items: center;
                gap: 0.25rem;
                padding: 0.2rem 0.65rem;
                border-radius: 999px;
                background: rgba(37, 99, 235, 0.12);
                color: var(--brand-strong);
                font-weight: 600;
                letter-spacing: 0.05em;
                text-transform: uppercase;
            }
            .lane-badge--beta::before {
                content: "β";
                font-size: 0.75em;
            }
            .lane-badge__link {
                color: var(--brand-strong);
                text-decoration: underline;
                text-underline-offset: 0.2em;
            }
            .dashboard-lane__header {
                display: flex;
                flex-direction: column;
                gap: 0.15rem;
            }
            .dashboard-lane__title {
                font-size: clamp(1.35rem, 2vw, 1.65rem);
                font-weight: 700;
                color: var(--text-body);
                margin: 0;
                letter-spacing: 0.01em;
            }
            .dashboard-lane__subtitle {
                font-size: 0.92rem;
                color: var(--text-faint);
                margin: 0;
            }
            .dashboard-card {
                border-radius: 20px;
                padding: clamp(1rem, 1.6vw, 1.35rem) clamp(1.05rem, 1.8vw, 1.55rem);
                background: #ffffff;
                border: 1px solid var(--border-soft);
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
                background: linear-gradient(180deg, rgba(226, 240, 254, 0.92), rgba(255, 255, 255, 0.96));
            }
            .dashboard-card.card--tone-green {
                background: linear-gradient(180deg, rgba(222, 247, 238, 0.9), rgba(255, 255, 255, 0.96));
            }
            .dashboard-card.card--tone-yellow {
                background: linear-gradient(180deg, rgba(255, 248, 229, 0.9), rgba(255, 255, 255, 0.96));
            }
            .dashboard-card.card--tone-pink {
                background: linear-gradient(180deg, rgba(254, 236, 244, 0.9), rgba(255, 255, 255, 0.96));
            }
            .dashboard-card.card--tone-purple {
                background: linear-gradient(180deg, rgba(240, 236, 255, 0.9), rgba(255, 255, 255, 0.96));
            }
            .dashboard-card.card--tone-sand {
                background: linear-gradient(180deg, rgba(248, 250, 252, 0.85), rgba(255, 255, 255, 0.98));
            }
            .dashboard-card:focus-within {
                box-shadow: 0 0 0 2px rgba(37, 99, 235, 0.32), var(--shadow-card);
            }
            .summary-card-grid {
                display: grid;
                grid-template-columns: repeat(auto-fit, minmax(190px, 1fr));
                gap: clamp(0.9rem, 1.8vw, 1.3rem);
            }
            .summary-card {
                padding: 1.15rem 1.25rem 1.1rem;
                border-radius: 16px;
                background: rgba(255, 255, 255, 0.92);
                border: 1px solid rgba(148, 163, 184, 0.28);
                box-shadow: 0 14px 26px rgba(15, 23, 42, 0.08);
                display: flex;
                flex-direction: column;
                gap: 0.4rem;
            }
            .summary-card__label {
                margin: 0;
                font-size: 0.85rem;
                font-weight: 600;
                color: var(--text-muted);
                letter-spacing: 0.05em;
                text-transform: uppercase;
            }
            .summary-card__value {
                margin: 0;
                font-size: clamp(1.65rem, 2.6vw, 2.05rem);
                font-weight: 700;
                color: var(--text-body);
                letter-spacing: -0.01em;
            }
            .summary-card__meta {
                margin: 0;
                font-size: 0.88rem;
                color: var(--text-faint);
            }
            .summary-cta-card {
                display: flex;
                flex-direction: column;
                gap: 1.35rem;
            }
            .summary-cta-card__item {
                background: rgba(255, 255, 255, 0.78);
                border-radius: 18px;
                padding: 1.2rem 1.3rem 1.1rem;
                border: 1px solid rgba(148, 163, 184, 0.32);
                box-shadow: 0 12px 24px rgba(15, 23, 42, 0.08);
                display: flex;
                flex-direction: column;
                gap: 0.75rem;
                height: 100%;
            }
            .summary-cta-card__eyebrow {
                font-size: 0.78rem;
                font-weight: 700;
                letter-spacing: 0.08em;
                text-transform: uppercase;
                color: rgba(37, 99, 235, 0.75);
                margin: 0;
            }
            .summary-cta-card__title {
                margin: 0;
                font-size: clamp(1.1rem, 2vw, 1.35rem);
                font-weight: 700;
                color: #1e293b;
                line-height: 1.35;
            }
            .summary-cta-card__meta {
                margin: 0;
                font-size: 0.9rem;
                color: var(--text-muted);
                line-height: 1.5;
            }
            .summary-cta-card__preview {
                display: block;
                margin-top: 0.4rem;
                font-size: 0.82rem;
                color: rgba(30, 41, 59, 0.72);
            }
            .summary-cta-card__item [data-testid="stButton"] {
                margin-top: auto;
            }
            .summary-cta-card__item [data-testid="stButton"] button {
                border-radius: 999px;
                padding: 0.65rem 1.1rem;
                font-weight: 600;
                font-size: 0.95rem;
                background: linear-gradient(90deg, rgba(37, 99, 235, 0.95), rgba(59, 130, 246, 0.95));
                color: #fff;
                border: none;
                box-shadow: 0 14px 26px rgba(37, 99, 235, 0.25);
            }
            .summary-cta-card__item [data-testid="stButton"] button:disabled {
                background: rgba(148, 163, 184, 0.45);
                box-shadow: none;
            }
            .summary-analytics-card {
                display: flex;
                flex-direction: column;
                gap: 1.25rem;
            }
            .summary-analytics-card [data-testid="stExpander"] {
                border: 1px solid rgba(148, 163, 184, 0.28);
                border-radius: 16px;
                background: rgba(255, 255, 255, 0.85);
            }
            .summary-analytics-card [data-testid="stExpander"] > details {
                padding: 0.3rem 0.35rem;
            }
            .summary-analytics-card [data-testid="stExpander"] > details > summary {
                font-weight: 600;
                color: var(--text-muted);
            }
            .summary-analytics-card [data-testid="stExpander"] .stMultiSelect,
            .summary-analytics-card [data-testid="stExpander"] .stTextInput {
                margin-top: 0.55rem;
            }
            .summary-analytics-card .stColumn > div {
                height: 100%;
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
            .progress-grid {
                display: grid;
                grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
                gap: clamp(1rem, 1.6vw, 1.4rem);
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
                background: linear-gradient(90deg, rgba(37, 99, 235, 0.7), rgba(29, 78, 216, 0.85));
                transition: width 600ms ease;
            }
            .progress-bar__value {
                font-size: 0.85rem;
                color: var(--text-body);
            }
            .progress-bar[data-tone="green"] .progress-bar__fill {
                background: linear-gradient(90deg, rgba(15, 118, 110, 0.7), rgba(13, 148, 136, 0.85));
            }
            .progress-bar[data-tone="yellow"] .progress-bar__fill {
                background: linear-gradient(90deg, rgba(244, 187, 68, 0.7), rgba(234, 179, 8, 0.82));
            }
            .study-notification-card {
                display: flex;
                flex-direction: column;
                gap: 1.1rem;
            }
            .study-progress-meter {
                display: flex;
                flex-direction: column;
                gap: 0.55rem;
            }
            .study-progress-meter__header {
                display: flex;
                justify-content: space-between;
                align-items: center;
                font-weight: 600;
                font-size: 0.92rem;
                color: var(--text-body);
            }
            .study-progress-meter__track {
                position: relative;
                height: 12px;
                border-radius: 999px;
                background: rgba(37, 99, 235, 0.18);
                overflow: hidden;
            }
            .study-progress-meter__fill {
                position: absolute;
                inset: 0;
                width: var(--progress, 0%);
                background: linear-gradient(90deg, #2563eb, #0ea5e9);
                border-radius: inherit;
                transition: width 600ms ease;
            }
            .study-progress-meter__footer {
                display: flex;
                justify-content: space-between;
                font-size: 0.82rem;
                color: var(--text-muted);
            }
            .notification-group {
                display: flex;
                flex-direction: column;
                gap: 0.6rem;
                padding: 0.85rem 1rem;
                border-radius: 16px;
                border: 1px solid rgba(37, 99, 235, 0.18);
                background: rgba(37, 99, 235, 0.04);
            }
            .notification-group[data-tone="alert"] {
                border-color: rgba(239, 68, 68, 0.28);
                background: rgba(239, 68, 68, 0.08);
            }
            .notification-group[data-tone="info"] {
                border-color: rgba(14, 116, 144, 0.28);
                background: rgba(14, 116, 144, 0.08);
            }
            .notification-group[data-tone="success"] {
                border-color: rgba(34, 197, 94, 0.28);
                background: rgba(34, 197, 94, 0.08);
            }
            .notification-group__title {
                font-weight: 700;
                font-size: 0.9rem;
                color: var(--text-body);
            }
            .notification-list {
                list-style: none;
                margin: 0;
                padding: 0;
                display: flex;
                flex-direction: column;
                gap: 0.75rem;
            }
            .notification-item {
                display: grid;
                grid-template-columns: auto 1fr;
                gap: 0.75rem;
                align-items: flex-start;
            }
            .notification-item__badge {
                display: inline-flex;
                align-items: center;
                padding: 0.25rem 0.65rem;
                border-radius: 999px;
                font-size: 0.75rem;
                font-weight: 700;
                letter-spacing: 0.05em;
                text-transform: uppercase;
                background: rgba(37, 99, 235, 0.18);
                color: var(--brand-strong);
            }
            .notification-item__badge[data-tone="alert"] {
                background: rgba(239, 68, 68, 0.18);
                color: #b91c1c;
            }
            .notification-item__badge[data-tone="info"] {
                background: rgba(14, 116, 144, 0.18);
                color: #0f766e;
            }
            .notification-item__badge[data-tone="success"] {
                background: rgba(34, 197, 94, 0.18);
                color: #047857;
            }
            .notification-item__body {
                display: flex;
                flex-direction: column;
                gap: 0.15rem;
            }
            .notification-item__title {
                font-weight: 600;
                font-size: 0.95rem;
                color: var(--text-body);
            }
            .notification-item__subtitle {
                font-size: 0.84rem;
                color: var(--text-muted);
            }
            .notification-item__meta {
                font-size: 0.8rem;
                color: var(--text-faint);
            }
            .notification-empty {
                font-size: 0.85rem;
                color: var(--text-muted);
                margin: 0;
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
                font-size: 0.82rem;
                color: var(--text-faint);
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
                border: 1px solid rgba(37, 99, 235, 0.28);
                background: linear-gradient(180deg, rgba(231, 240, 255, 0.9), rgba(255, 255, 255, 0.96));
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
            .insight-card-link {
                display: block;
                text-decoration: none;
                color: inherit;
                border-radius: 18px;
            }
            .insight-card-link:focus-visible {
                outline: none;
                box-shadow: 0 0 0 3px rgba(37, 99, 235, 0.3);
            }
            .insight-card {
                display: grid;
                grid-template-columns: auto 1fr;
                gap: 0.8rem;
                align-items: center;
                padding: 0.85rem 0.95rem;
                border-radius: 18px;
                border: 1px solid rgba(148, 163, 184, 0.32);
                background: rgba(255, 255, 255, 0.82);
                box-shadow: 0 12px 24px rgba(15, 23, 42, 0.08);
                transition: transform 160ms ease, box-shadow 160ms ease, border-color 160ms ease;
            }
            .insight-card[data-clickable="true"] {
                cursor: pointer;
            }
            .insight-card-link:hover .insight-card,
            .insight-card-link:focus-visible .insight-card {
                border-color: rgba(37, 99, 235, 0.45);
                box-shadow: 0 18px 36px rgba(37, 99, 235, 0.16);
                transform: translateY(-2px);
            }
            .insight-icon {
                display: inline-flex;
                flex-direction: column;
                align-items: center;
                justify-content: center;
                gap: 0.3rem;
                min-width: 54px;
                min-height: 54px;
                padding: 0.5rem 0.6rem;
                border-radius: 16px;
                background: linear-gradient(135deg, rgba(37, 99, 235, 0.15), rgba(37, 99, 235, 0.26));
                color: var(--brand-strong);
                box-shadow: 0 10px 18px rgba(37, 99, 235, 0.16);
                text-align: center;
            }
            .insight-icon[data-accent="teal"] {
                background: linear-gradient(135deg, rgba(15, 118, 110, 0.15), rgba(13, 148, 136, 0.25));
                color: var(--accent-green);
                box-shadow: 0 10px 18px rgba(15, 118, 110, 0.16);
            }
            .insight-icon[data-accent="slate"] {
                background: linear-gradient(135deg, rgba(71, 85, 105, 0.14), rgba(71, 85, 105, 0.24));
                color: #1f2937;
                box-shadow: 0 10px 18px rgba(30, 41, 59, 0.14);
            }
            .insight-icon__glyph {
                display: inline-flex;
                align-items: center;
                justify-content: center;
            }
            .insight-icon__glyph svg {
                width: 26px;
                height: 26px;
            }
            .insight-icon__label {
                font-size: 0.7rem;
                font-weight: 600;
                letter-spacing: 0.03em;
                line-height: 1.1;
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
            .analysis-visual-card,
            .heatmap-card {
                overflow-x: auto;
            }
            .analysis-visual-card .vega-embed,
            .heatmap-card .vega-embed {
                width: 100% !important;
            }
            .analysis-visual-card canvas,
            .heatmap-card canvas {
                max-width: 100% !important;
                height: auto !important;
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
                .block-container {
                    padding: 1.1rem 1.2rem 2.4rem;
                }
                .dashboard-toc {
                    justify-content: flex-start;
                    gap: 0.5rem;
                }
                .dashboard-toc__link {
                    flex: 1 1 45%;
                    justify-content: center;
                }
                .dashboard-card {
                    padding: 1rem 1.1rem 1.25rem;
                }
                .kpi-tiles,
                .progress-grid,
                .metric-grid,
                .insight-grid {
                    grid-template-columns: 1fr;
                }
                .achievement-timeline::before {
                    left: 0.45rem;
                }
                .achievement-timeline__item::before {
                    left: -1.15rem;
                }
            }
            @media (max-width: 600px) {
                .dashboard-toc__link {
                    flex-basis: 100%;
                }
                .dashboard-lane__title {
                    font-size: 1.25rem;
                }
                .dashboard-lane__subtitle {
                    font-size: 0.88rem;
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


def _inject_help_tooltip_styles() -> None:
    if st.session_state.get("_help_tooltip_styles_injected"):
        return

    st.markdown(
        dedent(
            """
            <style>
            .help-label {
                position: relative;
                display: inline-flex;
                align-items: center;
                gap: 0.45rem;
                color: #0f172a;
            }
            .help-label--block {
                display: flex;
            }
            .help-label--heading {
                margin: 1.25rem 0 0.5rem;
                gap: 0.6rem;
            }
            .help-label--subheading {
                margin: 0.85rem 0 0.4rem;
            }
            .help-label--form {
                margin-bottom: 0.25rem;
            }
            .help-label__text {
                margin: 0;
                font-weight: 600;
                color: inherit;
            }
            .help-label--heading .help-label__text {
                font-size: clamp(1.08rem, 2.4vw, 1.3rem);
                font-weight: 700;
            }
            .help-label--subheading .help-label__text {
                font-size: clamp(0.96rem, 2vw, 1.1rem);
            }
            .help-label__icon {
                display: inline-flex;
                align-items: center;
                justify-content: center;
                width: 1.55rem;
                height: 1.55rem;
                border-radius: 50%;
                border: 1px solid rgba(37, 99, 235, 0.45);
                background: rgba(219, 234, 254, 0.72);
                color: rgba(37, 99, 235, 0.95);
                font-weight: 700;
                font-size: 0.9rem;
                cursor: help;
                padding: 0;
                transition: transform 0.15s ease, box-shadow 0.15s ease, background 0.15s ease;
            }
            .help-label__icon:hover,
            .help-label__icon:focus-visible {
                transform: translateY(-1px);
                background: rgba(191, 219, 254, 0.95);
                box-shadow: 0 6px 12px rgba(37, 99, 235, 0.25);
                outline: none;
            }
            .help-label__icon:focus-visible {
                box-shadow: 0 0 0 3px rgba(191, 219, 254, 0.75), 0 6px 12px rgba(37, 99, 235, 0.25);
            }
            .help-label__bubble {
                position: absolute;
                top: calc(100% + 0.6rem);
                right: 0;
                min-width: 220px;
                max-width: min(340px, 80vw);
                padding: 0.65rem 0.75rem;
                border-radius: 12px;
                background: rgba(15, 23, 42, 0.95);
                color: rgba(241, 245, 249, 0.98);
                font-size: 0.78rem;
                line-height: 1.55;
                box-shadow: 0 16px 28px rgba(15, 23, 42, 0.24);
                opacity: 0;
                transform: translateY(-6px);
                pointer-events: none;
                transition: opacity 0.18s ease, transform 0.18s ease;
                z-index: 1600;
            }
            .help-label__bubble::before {
                content: "";
                position: absolute;
                top: -6px;
                right: 16px;
                border-width: 0 6px 6px 6px;
                border-style: solid;
                border-color: transparent transparent rgba(15, 23, 42, 0.95) transparent;
            }
            .help-label:focus-within .help-label__bubble,
            .help-label:hover .help-label__bubble {
                opacity: 1;
                transform: translateY(0);
            }
            .help-label__bubble[hidden] {
                display: none;
            }
            .help-label__icon span {
                pointer-events: none;
            }
            @media (prefers-reduced-motion: reduce) {
                .help-label__icon,
                .help-label__bubble {
                    transition: none;
                }
            }
            @media (prefers-color-scheme: dark) {
                .help-label {
                    color: #e2e8f0;
                }
                .help-label__icon {
                    border-color: rgba(147, 197, 253, 0.6);
                    background: rgba(30, 41, 59, 0.9);
                    color: rgba(191, 219, 254, 0.95);
                }
                .help-label__icon:hover,
                .help-label__icon:focus-visible {
                    background: rgba(59, 130, 246, 0.32);
                }
                .help-label__bubble {
                    background: rgba(15, 23, 42, 0.98);
                    color: rgba(226, 232, 240, 0.95);
                }
                .help-label__bubble::before {
                    border-color: transparent transparent rgba(15, 23, 42, 0.98) transparent;
                }
            }
            </style>
            """
        ),
        unsafe_allow_html=True,
    )
    st.session_state["_help_tooltip_styles_injected"] = True


def _render_help_label(
    label: str,
    description: str,
    *,
    level: Optional[int] = None,
    variant: str = "form",
) -> None:
    _inject_help_tooltip_styles()
    tooltip_id = f"help-tip-{uuid.uuid4().hex}"
    safe_label = html.escape(label)
    safe_desc = html.escape(description)
    wrapper_classes = ["help-label"]
    if variant == "form":
        wrapper_classes.append("help-label--form")
        wrapper_classes.append("help-label--block")
    elif variant == "heading":
        wrapper_classes.append("help-label--heading")
    elif variant == "subheading":
        wrapper_classes.append("help-label--subheading")
        wrapper_classes.append("help-label--block")
    else:
        wrapper_classes.append("help-label--block")

    if level is not None:
        heading_level = max(1, min(int(level), 6))
        text_tag = f"h{heading_level}"
        wrapper_classes.append("help-label--heading")
    else:
        text_tag = "span"

    markup = dedent(
        f"""
        <div class="{' '.join(wrapper_classes)}">
            <{text_tag} class="help-label__text">{safe_label}</{text_tag}>
            <button type="button" class="help-label__icon" aria-describedby="{tooltip_id}" aria-label="{safe_label}の説明">
                <span aria-hidden="true">？</span>
            </button>
            <span class="help-label__bubble" role="tooltip" id="{tooltip_id}">{safe_desc}</span>
        </div>
        """
    ).strip()
    st.markdown(markup, unsafe_allow_html=True)




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


def _summarize_feedback_text(feedback: Optional[str], *, limit: int = 60) -> str:
    if not feedback:
        return ""
    normalized = re.sub(r"\s+", " ", str(feedback)).strip()
    if not normalized:
        return ""
    if len(normalized) <= limit:
        return normalized
    if limit <= 1:
        return "…"
    return normalized[: limit - 1] + "…"


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
    now_stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
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


def _derive_question_type(entry: Dict[str, Any]) -> str:
    """Return a representative question type label from a summary entry."""

    for key in ("skill_tags", "topics", "tendencies"):
        tags = entry.get(key)
        if isinstance(tags, list) and tags:
            label = str(tags[0]).strip()
            if label:
                return label
    return "未分類"


def _categorize_score_band(avg_ratio: Optional[float]) -> str:
    if avg_ratio is None:
        return "未計測"
    try:
        ratio = float(avg_ratio)
    except (TypeError, ValueError):
        return "未計測"
    ratio *= 100 if ratio <= 1 else 1
    if ratio >= 80:
        return "80%以上"
    if ratio >= 60:
        return "60〜79%"
    if ratio >= 40:
        return "40〜59%"
    return "40%未満"


def _build_dashboard_summary_df(summary: Sequence[Dict[str, Any]]) -> pd.DataFrame:
    if not summary:
        return pd.DataFrame(
            columns=[
                "question_id",
                "year",
                "case_label",
                "question_order",
                "avg_ratio",
                "last_attempt_at",
                "question_type",
                "score_band",
                "themes",
                "attempt_count",
            ]
        )

    records: List[Dict[str, Any]] = []
    for entry in summary:
        record = {
            "question_id": entry.get("question_id"),
            "year": entry.get("year"),
            "case_label": entry.get("case_label"),
            "question_order": entry.get("question_order"),
            "avg_ratio": entry.get("avg_ratio"),
            "last_attempt_at": _parse_iso_datetime(entry.get("last_attempt_at")),
            "question_type": _derive_question_type(entry),
            "score_band": _categorize_score_band(entry.get("avg_ratio")),
            "themes": entry.get("themes") or [],
            "attempt_count": entry.get("attempt_count", 0),
        }
        records.append(record)

    df = pd.DataFrame.from_records(records)
    if not df.empty and "last_attempt_at" in df.columns:
        df["last_attempt_at"] = pd.to_datetime(df["last_attempt_at"])
    return df


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
    st.markdown(
        "### スタディプランナー <span class='beta-badge' aria-label='ベータ版機能'>Beta</span>",
        unsafe_allow_html=True,
    )
    st.caption("週間・月間の学習目標を設定し、進捗と予定を一括で管理できます。")
    st.caption("※ベータ版機能のため、想定外の挙動は『設定 > サポート』からご報告ください。")
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
        practice_presets = list(range(0, 11)) + [int(default_practice)]
        practice_options = sorted(set(practice_presets))
        practice_target = st.select_slider(
            "演習回数目標 (回)",
            options=practice_options,
            value=int(default_practice),
            format_func=lambda x: f"{x}回",
        )

        study_hour_base = [i * 0.5 for i in range(0, 21)]
        study_hour_presets = study_hour_base + [float(default_hours)]
        study_hour_options = sorted(set(round(value, 1) for value in study_hour_presets))
        study_hours = st.select_slider(
            "学習時間目標 (時間)",
            options=study_hour_options,
            value=round(float(default_hours), 1),
            format_func=lambda x: f"{x:.1f}時間",
        )

        score_presets = [40.0, 45.0, 50.0, 55.0, 60.0, 65.0, 70.0, 75.0, 80.0, 85.0, 90.0, float(default_score)]
        score_options = sorted(set(round(value, 1) for value in score_presets))
        score_target = st.select_slider(
            "平均得点目標 (点)",
            options=score_options,
            value=round(float(default_score), 1),
            format_func=lambda x: f"{x:.0f}点" if x.is_integer() else f"{x:.1f}点",
        )

        preferred_time = st.time_input(
            "学習開始時間",
            value=default_time or dt_time(20, 0),
            step=timedelta(minutes=15),
        )
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
        st.rerun()

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
        st.data_editor(session_df, hide_index=True, disabled=True, width="stretch")

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


def _insight_icon_asset(name: str) -> Tuple[str, str]:
    icon_map: Dict[str, Tuple[str, str]] = {
        "target": (
            dedent(
                """
                <svg viewBox="0 0 24 24" aria-hidden="true" focusable="false">
                    <circle cx="12" cy="12" r="9" fill="none" stroke="currentColor" stroke-width="1.6" />
                    <circle cx="12" cy="12" r="4.5" fill="none" stroke="currentColor" stroke-width="1.6" />
                    <path d="M12 7v5l3 1" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" />
                </svg>
                """
            ).strip(),
            "注力目標",
        ),
        "clock": (
            dedent(
                """
                <svg viewBox="0 0 24 24" aria-hidden="true" focusable="false">
                    <circle cx="12" cy="12" r="9" fill="none" stroke="currentColor" stroke-width="1.6" />
                    <path d="M12 7v5.2l3 2.3" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" />
                </svg>
                """
            ).strip(),
            "学習時間",
        ),
        "trend": (
            dedent(
                """
                <svg viewBox="0 0 24 24" aria-hidden="true" focusable="false">
                    <path d="M4 16.5 9.2 11l3.1 3.1 7.7-7.7" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" />
                    <polyline points="18 6.4 18 10.8 13.6 10.8" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" />
                </svg>
                """
            ).strip(),
            "スコア推移",
        ),
        "bell": (
            dedent(
                """
                <svg viewBox="0 0 24 24" aria-hidden="true" focusable="false">
                    <path d="M18 15c-1.1-1.3-2-2.5-2-5.5A4 4 0 0 0 12 5a4 4 0 0 0-4 4.5c0 3-0.9 4.2-2 5.5" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" />
                    <path d="M5 15h14" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" />
                    <path d="M10 18a2 2 0 0 0 4 0" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" />
                </svg>
                """
            ).strip(),
            "通知",
        ),
    }
    return icon_map.get(name, icon_map["target"])


def _parse_attempt_datetime(value: Any) -> Optional[datetime]:
    if isinstance(value, datetime):
        return value
    if isinstance(value, str) and value:
        try:
            return datetime.fromisoformat(value)
        except ValueError:
            return None
    return None


def _build_accuracy_trend_df(attempts: Sequence[Mapping[str, Any]]) -> pd.DataFrame:
    records: List[Dict[str, Any]] = []
    for attempt in attempts:
        timestamp = _parse_attempt_datetime(
            attempt.get("submitted_at") or attempt.get("started_at")
        )
        total_score = attempt.get("total_score")
        total_max = attempt.get("total_max_score")
        if timestamp is None or total_score is None or not total_max:
            continue
        try:
            ratio = float(total_score) / float(total_max) * 100
        except (TypeError, ZeroDivisionError, ValueError):
            continue
        records.append(
            {
                "attempt_id": attempt.get("id"),
                "submitted_at": timestamp,
                "score_ratio": ratio,
                "case_label": attempt.get("case_label") or "",
                "title": attempt.get("title") or "",
            }
        )

    if not records:
        return pd.DataFrame()

    df = pd.DataFrame(records)
    df.sort_values("submitted_at", inplace=True)
    df.reset_index(drop=True, inplace=True)
    df["attempt_index"] = df.index + 1
    df["rolling_avg"] = df["score_ratio"].rolling(window=3, min_periods=1).mean()
    return df


def _build_case_performance_df(attempts: Sequence[Mapping[str, Any]]) -> pd.DataFrame:
    records: List[Dict[str, Any]] = []
    for attempt in attempts:
        case_label = attempt.get("case_label") or "未分類"
        total_score = attempt.get("total_score")
        total_max = attempt.get("total_max_score")
        timestamp = _parse_attempt_datetime(
            attempt.get("submitted_at") or attempt.get("started_at")
        )
        if total_score is None or not total_max:
            continue
        try:
            ratio = float(total_score) / float(total_max) * 100
        except (TypeError, ZeroDivisionError, ValueError):
            continue
        records.append(
            {
                "case_label": case_label,
                "score_ratio": ratio,
                "submitted_at": timestamp,
            }
        )

    if not records:
        return pd.DataFrame()

    df = pd.DataFrame(records)
    summary = (
        df.groupby("case_label")
        .agg(
            avg_ratio=("score_ratio", "mean"),
            attempt_count=("score_ratio", "count"),
            last_practiced=("submitted_at", "max"),
        )
        .reset_index()
    )
    summary.sort_values("avg_ratio", ascending=False, inplace=True)
    summary["attempt_label"] = summary["attempt_count"].apply(lambda count: f"{int(count)}回")
    return summary


def dashboard_page(user: Dict) -> None:
    _inject_dashboard_styles()

    try:
        attempts = database.list_attempts(user_id=user["id"])
    except Exception:
        logger.exception("Failed to load attempts for dashboard view")
        attempts = []

    try:
        stats = database.aggregate_statistics(user["id"])
    except Exception:
        logger.exception("Failed to aggregate statistics for dashboard")
        stats = {}

    try:
        keyword_records = database.fetch_keyword_performance(user["id"])
    except Exception:
        logger.exception("Failed to load keyword performance for dashboard")
        keyword_records = []

    try:
        question_progress = database.get_question_progress_summary(user["id"], recent_limit=5)
    except Exception:
        logger.exception("Failed to load question progress summary for dashboard")
        question_progress = {
            "recent_questions": [],
            "total_questions": 0,
            "studied_questions": 0,
            "progress_ratio": 0.0,
        }

    try:
        personalized_bundle = personalized_recommendation.generate_personalised_learning_plan(
            user_id=user["id"],
            attempts=attempts,
            problem_catalog=database.list_problems(),
            keyword_resource_map=KEYWORD_RESOURCE_MAP,
            default_resources=DEFAULT_KEYWORD_RESOURCES,
        )
    except Exception:
        logger.exception("Failed to generate personalised recommendations for dashboard")
        personalized_bundle = {}

    question_recs: List[Dict[str, Any]] = personalized_bundle.get("question_recommendations") or []

    JST = timezone(timedelta(hours=9))

    def _ensure_utc(value: Any) -> Optional[datetime]:
        if isinstance(value, datetime):
            dt = value
        else:
            dt = _parse_attempt_datetime(value)
        if dt is None:
            return None
        if dt.tzinfo is None:
            return dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)

    def _to_jst(value: Any) -> Optional[datetime]:
        dt = _ensure_utc(value)
        if dt is None:
            return None
        return dt.astimezone(JST)

    def _format_short_datetime(value: Any) -> str:
        dt = _to_jst(value)
        if dt is None:
            return "記録なし"
        return f"{dt.month}/{dt.day} {dt.hour:02d}:{dt.minute:02d}"

    def _format_short_date(value: Any) -> str:
        dt = _to_jst(value)
        if dt is None:
            return "未設定"
        return f"{dt.year}/{dt.month:02d}/{dt.day:02d}"

    attempt_datetimes: List[datetime] = []
    total_score = 0.0
    total_max = 0.0
    total_duration_seconds = 0

    for attempt in attempts:
        dt = _ensure_utc(attempt.get("submitted_at") or attempt.get("started_at"))
        if dt is not None:
            attempt_datetimes.append(dt)
        try:
            total_score += float(attempt.get("total_score") or 0)
        except (TypeError, ValueError):
            pass
        try:
            total_max += float(attempt.get("total_max_score") or 0)
        except (TypeError, ValueError):
            pass
        duration_seconds = attempt.get("duration_seconds")
        if duration_seconds is not None:
            try:
                total_duration_seconds += int(duration_seconds)
            except (TypeError, ValueError):
                continue

    total_attempts = len(attempts)
    average_score = round(total_score / total_attempts, 1) if total_attempts else 0.0
    completion_rate = (total_score / total_max * 100) if total_max else 0.0
    total_learning_minutes = total_duration_seconds // 60

    now_utc = datetime.now(timezone.utc)
    recent_attempt_count = sum(1 for dt in attempt_datetimes if dt and dt >= now_utc - timedelta(days=30))

    def _calculate_streak(datetimes: Sequence[datetime]) -> int:
        if not datetimes:
            return 0
        active_days = {
            dt.astimezone(JST).date()
            for dt in datetimes
            if isinstance(dt, datetime)
        }
        if not active_days:
            return 0
        today = datetime.now(JST).date()
        streak = 0
        while today - timedelta(days=streak) in active_days:
            streak += 1
        return streak

    streak_days = _calculate_streak(attempt_datetimes)
    latest_attempt_dt = max(attempt_datetimes) if attempt_datetimes else None

    best_case_label: Optional[str] = None
    best_case_ratio: Optional[float] = None
    worst_case_label: Optional[str] = None
    worst_case_ratio: Optional[float] = None
    for case_label, values in stats.items():
        avg_max = values.get("avg_max") or 0.0
        avg_score = values.get("avg_score") or 0.0
        try:
            avg_max_value = float(avg_max)
            avg_score_value = float(avg_score)
        except (TypeError, ValueError):
            continue
        if not avg_max_value:
            continue
        ratio = avg_score_value / avg_max_value * 100
        if best_case_ratio is None or ratio > best_case_ratio:
            best_case_ratio = ratio
            best_case_label = case_label
        if worst_case_ratio is None or ratio < worst_case_ratio:
            worst_case_ratio = ratio
            worst_case_label = case_label

    has_attempts = total_attempts > 0

    keyword_miss_counter: Counter[str] = Counter()
    for record in keyword_records:
        keyword_hits = record.get("keyword_hits") or {}
        for keyword, hit in keyword_hits.items():
            if keyword and not hit:
                keyword_miss_counter[keyword] += 1

    top_missed_keywords = [keyword for keyword, _count in keyword_miss_counter.most_common(5)]

    summary_cards: List[Dict[str, Any]]
    if has_attempts:
        summary_cards = [
            {
                "icon": "bx bx-calendar-check",
                "title": "総学習回数",
                "value": f"{total_attempts} 回",
                "meta": f"直近30日 {recent_attempt_count} 回学習" if recent_attempt_count else "直近30日の学習記録を作成しましょう",
                "state": "",
            },
            {
                "icon": "bx bx-medal",
                "title": "平均得点",
                "value": f"{average_score:.1f} 点" if total_attempts else "-",
                "meta": (
                    f"ベスト: {best_case_ratio:.0f}% ({best_case_label})"
                    if best_case_label and best_case_ratio is not None
                    else "得点データを蓄積すると傾向が表示されます"
                ),
                "state": "" if total_attempts else "empty",
            },
            {
                "icon": "bx bx-target-lock",
                "title": "達成率",
                "value": f"{completion_rate:.0f}%" if total_max else "0%",
                "meta": (
                    f"累計学習時間 {_format_duration_minutes(total_learning_minutes)}"
                    if total_learning_minutes
                    else "演習後に所要時間を記録すると進捗率が分かります"
                ),
                "state": "warning" if completion_rate and completion_rate < 60 else "",
            },
        ]
    else:
        summary_cards = [
            {
                "icon": "bx bx-rocket",
                "title": "STEP 1",
                "value": "過去問演習を始める",
                "meta": "左の『過去問演習』ページで初回チャレンジを登録しましょう。",
                "state": "empty",
            },
            {
                "icon": "bx bx-target-lock",
                "title": "STEP 2",
                "value": "解答を提出して自己分析",
                "meta": "回答を登録すると得点率とキーワード分析が自動表示されます。",
                "state": "empty",
            },
            {
                "icon": "bx bx-lightbulb",
                "title": "STEP 3",
                "value": "弱点キーワードを復習",
                "meta": "間違えたキーワードからおすすめ学習パスが提示されます。",
                "state": "empty",
            },
        ]

    monthly_metrics: Dict[Tuple[int, int], Dict[str, float]] = defaultdict(
        lambda: {
            "score_sum": 0.0,
            "score_count": 0,
            "coverage_sum": 0.0,
            "coverage_count": 0,
            "time_sum": 0.0,
            "time_count": 0,
        }
    )

    for attempt in attempts:
        dt = _ensure_utc(attempt.get("submitted_at") or attempt.get("started_at"))
        if dt is None:
            continue
        key = (dt.year, dt.month)
        total_score_value = attempt.get("total_score")
        total_max_value = attempt.get("total_max_score")
        score_ratio = None
        if total_score_value is not None and total_max_value:
            try:
                score_ratio = float(total_score_value) / float(total_max_value) * 100
            except (TypeError, ValueError, ZeroDivisionError):
                score_ratio = None
        if score_ratio is not None:
            monthly_metrics[key]["score_sum"] += score_ratio
            monthly_metrics[key]["score_count"] += 1
        duration_seconds = attempt.get("duration_seconds")
        if duration_seconds is not None:
            try:
                minutes = float(duration_seconds) / 60.0
            except (TypeError, ValueError):
                minutes = None
            if minutes is not None:
                monthly_metrics[key]["time_sum"] += minutes
                monthly_metrics[key]["time_count"] += 1

    for record in keyword_records:
        q_dt = _ensure_utc(record.get("submitted_at"))
        if q_dt is None:
            continue
        key = (q_dt.year, q_dt.month)
        coverage = record.get("keyword_coverage")
        if coverage is None:
            keyword_hits = record.get("keyword_hits") or {}
            total_keywords = len(keyword_hits)
            if total_keywords:
                coverage = sum(1 for hit in keyword_hits.values() if hit) / total_keywords
        if coverage is not None:
            try:
                coverage_pct = float(coverage) * 100
            except (TypeError, ValueError):
                continue
            monthly_metrics[key]["coverage_sum"] += coverage_pct
            monthly_metrics[key]["coverage_count"] += 1

    sorted_month_keys = sorted(monthly_metrics.keys())
    if len(sorted_month_keys) > 12:
        sorted_month_keys = sorted_month_keys[-12:]

    labels: List[str] = []
    score_series: List[Optional[float]] = []
    coverage_series: List[Optional[float]] = []
    time_series: List[Optional[float]] = []
    for year, month in sorted_month_keys:
        label = f"{year}/{month:02d}"
        labels.append(label)
        stats_row = monthly_metrics[(year, month)]
        score_value = (
            round(stats_row["score_sum"] / stats_row["score_count"], 1)
            if stats_row["score_count"]
            else None
        )
        coverage_value = (
            round(stats_row["coverage_sum"] / stats_row["coverage_count"], 1)
            if stats_row["coverage_count"]
            else None
        )
        time_value = (
            round(stats_row["time_sum"] / stats_row["time_count"], 1)
            if stats_row["time_count"]
            else None
        )
        score_series.append(score_value)
        coverage_series.append(coverage_value)
        time_series.append(time_value)

    has_score_data = any(value is not None for value in score_series)
    has_coverage_data = any(value is not None for value in coverage_series)
    has_time_data = any(value is not None for value in time_series)

    if not labels:
        labels = []

    chart_config = {
        "labels": labels,
        "datasets": {
            "score": {
                "label": "平均得点",
                "borderColor": "#3057d5",
                "backgroundColor": "rgba(48, 87, 213, 0.18)",
                "data": score_series,
                "tension": 0.34,
                "fill": True,
                "yAxisID": "y",
            },
            "keyword": {
                "label": "キーワード網羅率",
                "borderColor": "#21a179",
                "backgroundColor": "rgba(33, 161, 121, 0.18)",
                "data": coverage_series,
                "tension": 0.32,
                "fill": True,
                "yAxisID": "y",
            },
            "time": {
                "label": "平均解答時間 (分)",
                "borderColor": "#f59f48",
                "backgroundColor": "rgba(245, 159, 72, 0.22)",
                "data": time_series,
                "tension": 0.26,
                "fill": True,
                "yAxisID": "y",
            },
        },
        "emptyMessage": "演習を記録すると進捗グラフが表示されます。まずは『過去問演習を始める』から学習を登録しましょう。",
    }

    if has_score_data:
        chart_config["initialKey"] = "score"
    elif has_coverage_data:
        chart_config["initialKey"] = "keyword"
    elif has_time_data:
        chart_config["initialKey"] = "time"
    else:
        chart_config["initialKey"] = None

    chart_facts: List[Tuple[str, str]] = []
    latest_label = labels[-1] if labels else "データ未登録"
    chart_facts.append(("bx bx-calendar", f"最新: {latest_label}"))
    recent_scores = [value for value in score_series if value is not None]
    if recent_scores:
        trailing = recent_scores[-3:]
        chart_facts.append(("bx bx-trending-up", f"直近平均: {sum(trailing) / len(trailing):.1f} 点"))
    else:
        chart_facts.append(("bx bx-trending-up", "直近データなし"))
    if best_case_label and best_case_ratio is not None:
        chart_facts.append(("bx bx-rocket", f"得意: {best_case_label} ({best_case_ratio:.0f}%)"))
    else:
        chart_facts.append(("bx bx-rocket", "得意事例は分析中です"))
    if worst_case_label and worst_case_ratio is not None:
        chart_facts.append(("bx bx-bulb", f"伸びしろ: {worst_case_label} ({worst_case_ratio:.0f}%)"))
    else:
        chart_facts.append(("bx bx-bulb", "伸びしろ分析にはデータが必要です"))

    def _truncate(text: Optional[str], limit: int = 36) -> str:
        if not text:
            return ""
        normalized = str(text).strip()
        if len(normalized) <= limit:
            return normalized
        if limit <= 1:
            return normalized[:limit]
        return normalized[: limit - 1] + "…"

    question_metadata: Dict[int, Dict[str, Any]] = {}
    for record in keyword_records:
        question_id = record.get("question_id")
        if not question_id:
            continue
        submitted_at = _ensure_utc(record.get("submitted_at"))
        metadata = question_metadata.setdefault(question_id, {})
        if submitted_at and (
            metadata.get("submitted_at") is None or submitted_at > metadata.get("submitted_at")
        ):
            metadata.update(
                {
                    "submitted_at": submitted_at,
                    "score": record.get("score"),
                    "max_score": record.get("max_score"),
                    "keyword_coverage": record.get("keyword_coverage"),
                    "keyword_hits": record.get("keyword_hits"),
                    "prompt": record.get("prompt"),
                    "case_label": record.get("case_label"),
                    "year": record.get("year"),
                    "title": record.get("title"),
                    "question_order": record.get("question_order"),
                }
            )
            duration_seconds = record.get("duration_seconds")
            if duration_seconds is not None:
                try:
                    metadata["duration_minutes"] = float(duration_seconds) / 60.0
                except (TypeError, ValueError):
                    metadata["duration_minutes"] = None

    recent_questions: List[Dict[str, Any]] = question_progress.get("recent_questions", [])
    for entry in recent_questions:
        question_id = entry.get("question_id")
        if not question_id:
            continue
        metadata = question_metadata.setdefault(question_id, {})
        metadata.setdefault("case_label", entry.get("case_label"))
        metadata.setdefault("year", entry.get("year"))
        metadata.setdefault("title", entry.get("title"))
        metadata.setdefault("question_order", entry.get("question_order"))
        metadata.setdefault("prompt", entry.get("prompt"))
        metadata["problem_id"] = entry.get("problem_id")
        metadata["last_practiced_at"] = _ensure_utc(entry.get("last_practiced_at"))
        metadata["due_at"] = _ensure_utc(entry.get("due_at"))

    def _build_summary_cards_html() -> str:
        parts: List[str] = []
        for card in summary_cards:
            state_class = f" summary-card--{card['state']}" if card.get("state") else ""
            meta_text = card.get("meta")
            meta_html = (
                f"<p class='summary-card__meta'>{html.escape(meta_text)}</p>"
                if meta_text
                else ""
            )
            parts.append(
                dedent(
                    f"""
                    <article class="summary-card{state_class}">
                      <div class="icon-wrapper"><i class="{card['icon']}"></i></div>
                      <h3>{html.escape(card['title'])}</h3>
                      <strong>{html.escape(card['value'])}</strong>
                      {meta_html}
                    </article>
                    """
                ).strip()
            )
        if parts:
            return "\n".join(parts)
        return "<div class='empty-state'>初回演習を登録すると学習サマリーが表示されます。まずは『過去問演習』ページからチャレンジしてください。</div>"

    summary_cards_html = _build_summary_cards_html()

    def _build_keyword_alerts_html() -> str:
        if top_missed_keywords:
            chips = []
            for keyword in top_missed_keywords:
                keyword_label = html.escape(keyword)
                chips.append(f"<span class='keyword-chip'>{keyword_label}</span>")
            return "".join(chips)
        return (
            "<span class='keyword-chip keyword-chip--empty'>演習で間違えたキーワードが表示されます。まずは1問解いてみましょう。</span>"
        )

    keyword_alerts_html = _build_keyword_alerts_html()

    problem_recs = personalized_bundle.get("problem_recommendations") or []
    resource_recs = personalized_bundle.get("resource_recommendations") or []

    learning_path_steps: List[Tuple[str, str]] = []
    for entry in problem_recs[:3]:
        label_parts = [
            str(entry.get("year") or ""),
            str(entry.get("case_label") or ""),
            str(entry.get("title") or ""),
        ]
        label = " ".join(part for part in label_parts if part and part != "None").strip()
        if not label:
            label = "重点演習"
        reason = entry.get("reason") or "復習から着手しましょう"
        learning_path_steps.append((label, reason))

    if len(learning_path_steps) < 3:
        for entry in question_recs:
            label_parts = [
                str(entry.get("year") or ""),
                str(entry.get("case_label") or ""),
            ]
            prompt = entry.get("prompt")
            label = " ".join(part for part in label_parts if part and part != "None").strip()
            if prompt:
                label = f"{label} {prompt}".strip()
            reason = entry.get("reason") or "キーワード復習を優先しましょう"
            learning_path_steps.append((label or "優先問題", reason))
            if len(learning_path_steps) >= 3:
                break

    if len(learning_path_steps) < 3:
        for entry in resource_recs:
            label = entry.get("label") or entry.get("keyword") or "学習リソース"
            reason = entry.get("reason") or "関連資料を確認しましょう"
            learning_path_steps.append((label, reason))
            if len(learning_path_steps) >= 3:
                break

    def _build_learning_path_html() -> str:
        if learning_path_steps:
            items: List[str] = []
            for index, (label, reason) in enumerate(learning_path_steps, start=1):
                items.append(
                    dedent(
                        f"""
                        <li>
                          <span class="step-index">{index}</span>
                          <div>
                            <strong>{html.escape(label)}</strong>
                            <p>{html.escape(reason)}</p>
                          </div>
                        </li>
                        """
                    ).strip()
                )
            return f"<ol class='learning-path'>{''.join(items)}</ol>"
        return (
            "<div class='empty-state empty-state--inline'>演習履歴を登録するとおすすめ学習パスが表示されます。直近で解いた問題を振り返ってみましょう。</div>"
        )

    learning_path_html = _build_learning_path_html()

    def _build_weakness_report_html() -> str:
        if top_missed_keywords:
            rows: List[str] = []
            for keyword in top_missed_keywords[:3]:
                resources = KEYWORD_RESOURCE_MAP.get(keyword) or DEFAULT_KEYWORD_RESOURCES
                resource_links = []
                for resource in resources[:2]:
                    label = html.escape(resource.get("label") or "外部資料")
                    url = html.escape(resource.get("url") or "#")
                    resource_links.append(f"<a href='{url}' target='_blank' rel='noopener'>{label}</a>")
                resources_html = "".join(resource_links)
                rows.append(
                    dedent(
                        f"""
                        <div class="weakness-item">
                          <div class="weakness-item__keyword">{html.escape(keyword)}</div>
                          <div class="weakness-item__actions">{resources_html or '復習ノートを作成しましょう'}</div>
                        </div>
                        """
                    ).strip()
                )
            return "".join(rows)
        return (
            "<div class='empty-state empty-state--inline'>演習後に間違えたキーワードがこちらに並び、復習リンクが表示されます。</div>"
        )

    weakness_report_html = _build_weakness_report_html()

    progress_highlights: List[str] = []
    progress_highlights.append(
        f"最新の演習日: {_format_short_date(latest_attempt_dt) if latest_attempt_dt else '未実施'}"
    )
    if streak_days:
        progress_highlights.append(f"連続学習 {streak_days} 日継続中")
    else:
        progress_highlights.append("学習習慣づくりを今日から始めましょう")
    if total_learning_minutes:
        progress_highlights.append(f"累計学習時間 {_format_duration_minutes(total_learning_minutes)}")
    else:
        progress_highlights.append("演習後に所要時間を入力すると進捗が追跡できます")

    progress_highlights_html = "".join(
        f"<li><i class='bx bx-check-circle'></i>{html.escape(text)}</li>" for text in progress_highlights
    )

    chart_facts_html = "\n".join(
        f"<span><i class=\"{icon}\"></i> {html.escape(text)}</span>" for icon, text in chart_facts
    )
    if not chart_facts_html:
        chart_facts_html = "<span>演習データを追加すると要点が表示されます。まずは1問解いてみましょう。</span>"

    has_export_data = has_attempts or bool(question_progress.get("recent_questions"))
    if has_export_data:
        export_button_html = "<a href='#' class='cta' data-action='export-dashboard'><i class='bx bx-export'></i>CSV エクスポート</a>"
    else:
        export_button_html = "<span class='cta disabled' aria-disabled='true'><i class='bx bx-export'></i>CSV エクスポート</span>"

    recent_items: List[str] = []
    for item in recent_questions:
        question_id = item.get("question_id")
        metadata = question_metadata.get(question_id, {})
        year_label = item.get("year") or metadata.get("year") or "―"
        case_label = item.get("case_label") or metadata.get("case_label") or "事例"
        question_number = item.get("question_order") or metadata.get("question_order")
        header_label = f"{year_label} 年度 {case_label}"
        if question_number:
            header_label += f" 第 {question_number} 問"
        tag_label = "最新記録"
        due_at = metadata.get("due_at")
        if due_at:
            if due_at <= now_utc:
                tag_label = "復習期限"
            else:
                tag_label = "復習予定"
        score_value = metadata.get("score")
        max_score_value = metadata.get("max_score")
        score_icon = "bx bx-timer"
        score_tone = "info"
        score_text = "未採点"
        if score_value is not None and max_score_value:
            try:
                ratio = float(score_value) / float(max_score_value) * 100
            except (TypeError, ValueError, ZeroDivisionError):
                ratio = None
            if ratio is not None:
                score_text = f"{float(score_value):.0f} / {float(max_score_value):.0f} 点"
                if ratio >= 60:
                    score_icon = "bx bx-trophy"
                else:
                    score_icon = "bx bx-low-vision"
                    score_tone = "warning"
        elif score_value is not None:
            score_text = f"{float(score_value):.0f} 点"
        score_chip_html = (
            f"<span class='score-chip' data-tone='{score_tone}'><i class='{score_icon}'></i> {html.escape(score_text)}</span>"
        )
        meta_parts = [score_chip_html]
        meta_parts.append(
            f"<span><i class='bx bx-time-five'></i> {_format_short_datetime(metadata.get('last_practiced_at'))}</span>"
        )
        keyword_coverage = metadata.get("keyword_coverage")
        if keyword_coverage is not None:
            try:
                coverage_pct = float(keyword_coverage) * 100
            except (TypeError, ValueError):
                coverage_pct = None
            if coverage_pct is not None:
                meta_parts.append(
                    f"<span><i class='bx bx-brain'></i> 網羅 {coverage_pct:.1f}%</span>"
                )
        prompt_preview = _truncate(metadata.get("prompt"), limit=40)
        if prompt_preview:
            meta_parts.append(
                f"<span><i class='bx bx-book-open'></i> {html.escape(prompt_preview)}</span>"
            )
        due_label = ""
        if due_at:
            status = "期限超過" if due_at <= now_utc else "次回復習"
            due_label = f"<span><i class='bx bx-bell'></i> {status}: {_format_short_date(due_at)}</span>"
        else:
            due_label = (
                f"<span><i class='bx bx-history'></i> {_format_short_datetime(metadata.get('last_practiced_at'))}</span>"
            )
        practice_payload = {
            "case_label": case_label,
            "year": year_label,
            "question_id": question_id,
        }
        if None in practice_payload.values():
            action_html = "<span><i class='bx bx-link'></i> 問題データ未連携</span>"
        else:
            payload_attr = html.escape(json.dumps(practice_payload, ensure_ascii=False), quote=True)
            action_html = (
                f"<a href='#' data-action='open-practice' data-payload='{payload_attr}'><i class='bx bx-link-external'></i>問題へ移動</a>"
            )
        recent_items.append(
            dedent(
                f"""
                <article class="card-item">
                  <h3>
                    {html.escape(header_label)}
                    <span class="tag">{html.escape(tag_label)}</span>
                  </h3>
                  <div class="meta-line">
                    {'\n                    '.join(meta_parts)}
                  </div>
                  <div class="card-actions">
                    {due_label}
                    {action_html}
                  </div>
                </article>
                """
            ).strip()
        )

    if recent_items:
        recent_items_html = "\n".join(recent_items)
    else:
        recent_items_html = (
            "<div class='empty-state'>最近の記録がまだありません。「過去問演習を始める」ボタンから初回の解答を登録しましょう。</div>"
        )

    recommended_items: List[str] = []
    for entry in question_recs:
        question_id = entry.get("question_id")
        metadata = question_metadata.get(question_id, {})
        year_label = entry.get("year") or metadata.get("year") or "―"
        case_label = entry.get("case_label") or metadata.get("case_label") or "事例"
        question_number = metadata.get("question_order")
        header_label = f"{year_label} 年度 {case_label}"
        if question_number:
            header_label += f" 第 {question_number} 問"
        missing_keywords = entry.get("missing_keywords") or []
        if missing_keywords:
            tag_label = f"要強化: {missing_keywords[0]}"
        else:
            tag_label = "AI 推薦"
        score_ratio = entry.get("score_ratio")
        if score_ratio is not None:
            try:
                score_pct = float(score_ratio) * 100
            except (TypeError, ValueError):
                score_pct = None
        else:
            score_pct = None
        if score_pct is not None:
            if score_pct >= 60:
                score_chip_html = (
                    f"<span class='score-chip'><i class='bx bx-trophy'></i> 得点率 {score_pct:.0f}%</span>"
                )
            else:
                score_chip_html = (
                    f"<span class='score-chip' data-tone='warning'><i class='bx bx-low-vision'></i> 得点率 {score_pct:.0f}%</span>"
                )
        else:
            score_chip_html = "<span class='score-chip' data-tone='info'><i class='bx bx-joystick'></i> 未挑戦</span>"
        duration_minutes = entry.get("duration_minutes")
        duration_label = (
            f"想定 {duration_minutes:.0f} 分"
            if isinstance(duration_minutes, (int, float)) and duration_minutes > 0
            else "想定 40 分"
        )
        meta_parts = [score_chip_html]
        meta_parts.append(f"<span><i class='bx bx-time'></i> {duration_label}</span>")
        if missing_keywords:
            meta_parts.append(
                f"<span><i class='bx bx-target-lock'></i> 欠落 {html.escape(', '.join(missing_keywords[:2]))}</span>"
            )
        reason_text = entry.get("reason") or "復習推奨"
        practice_payload = {
            "case_label": case_label,
            "year": year_label,
            "question_id": question_id,
        }
        if None in practice_payload.values():
            action_html = "<span><i class='bx bx-link'></i> 問題データ未連携</span>"
        else:
            payload_attr = html.escape(json.dumps(practice_payload, ensure_ascii=False), quote=True)
            action_html = (
                f"<a href='#' data-action='open-practice' data-payload='{payload_attr}'><i class='bx bx-play-circle'></i>演習を開始</a>"
            )
        recommended_items.append(
            dedent(
                f"""
                <article class="card-item">
                  <h3>
                    {html.escape(header_label)}
                    <span class="tag">{html.escape(tag_label)}</span>
                  </h3>
                  <div class="meta-line">
                    {'\n                    '.join(meta_parts)}
                  </div>
                  <div class="card-actions">
                    <span><i class='bx bx-bulb'></i> {html.escape(reason_text)}</span>
                    {action_html}
                  </div>
                </article>
                """
            ).strip()
        )

    if recommended_items:
        recommended_items_html = "\n".join(recommended_items)
    else:
        recommended_items_html = (
            "<div class='empty-state'>おすすめ問題は現在ありません。演習を数件解くと弱点に基づいた提案がここに表示されます。</div>"
        )

    template = HOME_DASHBOARD_HTML_PATH.read_text(encoding="utf-8")
    replacements = {
        "{{SUMMARY_CARDS}}": summary_cards_html,
        "{{CHART_FACTS}}": chart_facts_html,
        "{{RECENT_ITEMS}}": recent_items_html,
        "{{RECOMMENDED_ITEMS}}": recommended_items_html,
        "{{KEYWORD_ALERTS}}": keyword_alerts_html,
        "{{LEARNING_PATH}}": learning_path_html,
        "{{WEAKNESS_REPORT}}": weakness_report_html,
        "{{PROGRESS_HIGHLIGHTS}}": progress_highlights_html,
        "{{EXPORT_BUTTON}}": export_button_html,
        "{{CHART_CONFIG}}": json.dumps(chart_config, ensure_ascii=False),
    }
    for placeholder, value in replacements.items():
        template = template.replace(placeholder, value)

    component_value = components.html(
        template,
        height=1040,
        scrolling=True,
    )

    event_raw = _extract_component_value(component_value)
    if event_raw:
        try:
            event = json.loads(event_raw)
        except json.JSONDecodeError:
            event = None
        else:
            if event:
                action = event.get("action")
                payload = event.get("payload") or {}
                if action == "open-practice":
                    case_label = payload.get("case_label")
                    year = payload.get("year")
                    question_id = payload.get("question_id")
                    if case_label and year and question_id:
                        _request_navigation("過去問演習")
                        st.session_state["practice_focus"] = {
                            "case_label": case_label,
                            "year": year,
                            "question_id": question_id,
                        }
                        st.rerun()
                elif action == "start-practice":
                    _request_navigation("過去問演習")
                    st.rerun()
                elif action in {"open-history", "open-recommendation-settings"}:
                    _request_navigation("学習履歴")
                    st.rerun()

    return
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
        .char-remaining-badge {
            display: inline-flex;
            align-items: center;
            gap: 0.25rem;
            padding: 0.2rem 0.55rem;
            border-radius: 999px;
            font-size: 0.78rem;
            margin: 0.15rem 0 0.35rem;
            background: #e2e8f0;
            color: #0f172a;
            font-weight: 600;
        }
        .char-remaining-badge.warn {
            background: #fde68a;
            color: #7c2d12;
        }
        .char-remaining-badge.over {
            background: #fecaca;
            color: #7f1d1d;
        }
        .char-remaining-badge.ok {
            background: #bfdbfe;
            color: #1e3a8a;
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


def _ensure_answer_quality_meter_styles() -> None:
    if st.session_state.get("_answer_quality_meter_styles"):
        return
    st.markdown(
        dedent(
            """
            <style>
            .answer-quality-meter {
                position: relative;
                width: 100%;
                height: 1rem;
                border-radius: 999px;
                background: rgba(226, 232, 240, 0.9);
                overflow: hidden;
                margin: 0.35rem 0 0.25rem;
                box-shadow: inset 0 1px 2px rgba(15, 23, 42, 0.08);
            }
            .answer-quality-meter__char {
                position: absolute;
                top: 0;
                left: 0;
                bottom: 0;
                background: linear-gradient(90deg, #38bdf8 0%, #2563eb 100%);
                border-radius: inherit;
                transition: width 0.3s ease;
            }
            .answer-quality-meter__keyword {
                position: absolute;
                left: 0;
                height: 40%;
                top: 30%;
                border-radius: 999px;
                background: rgba(14, 165, 233, 0.85);
                transition: width 0.3s ease;
            }
            .answer-quality-meter[data-coverage="warn"] .answer-quality-meter__keyword {
                background: rgba(250, 204, 21, 0.9);
            }
            .answer-quality-meter[data-coverage="empty"] .answer-quality-meter__keyword {
                display: none;
            }
            .answer-quality-meter[data-state="over"] .answer-quality-meter__char {
                background: linear-gradient(90deg, #ef4444 0%, #f97316 100%);
            }
            .answer-quality-meter[data-state="warn"] .answer-quality-meter__char {
                background: linear-gradient(90deg, #f59e0b 0%, #f97316 100%);
            }
            .answer-quality-meter__labels {
                display: flex;
                justify-content: space-between;
                font-size: 0.78rem;
                color: #334155;
                margin-bottom: 0.2rem;
            }
            .answer-quality-meter__labels span {
                font-weight: 600;
            }
            </style>
            """
        ),
        unsafe_allow_html=True,
    )
    st.session_state["_answer_quality_meter_styles"] = True


def _render_answer_quality_meter(
    text: str,
    limit: Optional[int],
    keyword_hits: Mapping[str, bool],
    *,
    keywords_registered: int,
) -> None:
    _ensure_answer_quality_meter_styles()
    fullwidth_length = _compute_fullwidth_length(text)
    char_ratio = 0.0
    remaining_text = f"現在 {_format_fullwidth_length(fullwidth_length)}字"
    remaining_state = "ok"

    if limit and limit > 0:
        char_ratio = min(fullwidth_length / limit, 1.0)
        remaining = limit - fullwidth_length
        if remaining < 0:
            remaining_state = "over"
            remaining_text = f"{_format_fullwidth_length(abs(remaining))}字オーバー"
        elif remaining <= 20:
            remaining_state = "warn"
            remaining_text = f"残り {_format_fullwidth_length(max(remaining, 0))}字"
        else:
            remaining_text = f"残り {_format_fullwidth_length(remaining)}字"
    else:
        baseline = max(fullwidth_length, 160)
        char_ratio = min(fullwidth_length / baseline, 1.0)
        remaining_state = "ok"

    total_keywords = keywords_registered or len(keyword_hits)
    matched_keywords = sum(1 for hit in keyword_hits.values() if hit)
    coverage_ratio = (
        matched_keywords / total_keywords if total_keywords else 0.0
    )
    coverage_width = min(max(coverage_ratio, 0.0), 1.0) * 100
    coverage_state = "empty"
    coverage_label = "要点カバー率 -"
    if total_keywords:
        coverage_label = (
            f"要点カバー率 {coverage_ratio * 100:.0f}% ({matched_keywords}/{total_keywords})"
        )
        if coverage_ratio >= 0.7:
            coverage_state = "ok"
        elif coverage_ratio > 0.0:
            coverage_state = "warn"
        else:
            coverage_state = "empty"

    meter_html = dedent(
        """
        <div class='answer-quality-meter' data-state='{state}' data-coverage='{coverage_state}'>
            <div class='answer-quality-meter__char' style='width: {char_width:.1f}%;'></div>
            <div class='answer-quality-meter__keyword' style='width: {keyword_width:.1f}%;'></div>
        </div>
        <div class='answer-quality-meter__labels'>
            <span>{char_label}</span>
            <span>{coverage_label}</span>
        </div>
        """
    ).format(
        state=remaining_state,
        coverage_state=coverage_state,
        char_width=min(char_ratio * 100, 100),
        keyword_width=coverage_width,
        char_label=html.escape(remaining_text),
        coverage_label=html.escape(coverage_label),
    )
    st.markdown(meter_html, unsafe_allow_html=True)

    if limit and limit > 0:
        st.caption(
            f"現在の文字数: {_format_fullwidth_length(fullwidth_length)} / {limit}字"
        )
        if fullwidth_length > limit:
            st.error("文字数が上限を超えています。要点を絞って調整しましょう。")
        elif fullwidth_length >= 120 and limit > 120:
            st.warning("120字を超えると冗長になりやすいので、主語と因果を整理しましょう。")
    else:
        st.caption(
            f"現在の文字数: {_format_fullwidth_length(fullwidth_length)}字"
        )


def _render_keyword_analysis_panel(keyword_hits: Mapping[str, bool]) -> None:
    if not keyword_hits:
        st.caption("まだ要点カバー率を算出できません。キーワードを入力してみましょう。")
        return

    matched = sum(1 for hit in keyword_hits.values() if hit)
    total = len(keyword_hits)
    missed_keywords = [kw for kw, hit in keyword_hits.items() if not hit]

    summary = _summarize_keyword_categories(keyword_hits)
    categories = [
        (label, summary.get(label, {"hit": 0, "miss": 0}))
        for label in ("名詞", "述語", "その他")
    ]
    available_categories = [
        (label, counts)
        for label, counts in categories
        if (counts.get("hit", 0) + counts.get("miss", 0)) > 0
    ]
    if available_categories:
        cols = st.columns(len(available_categories))
        for column, (label, counts) in zip(cols, available_categories):
            total_count = counts["hit"] + counts["miss"]
            coverage_pct = (
                counts["hit"] / total_count * 100 if total_count else 0.0
            )
            column.metric(
                label,
                f"{counts['hit']}/{total_count}",
                delta=f"{coverage_pct:.0f}%",
            )

    if missed_keywords:
        st.markdown("**未カバーキーワード**")
        st.write("、".join(missed_keywords))
    else:
        st.success("登録済みのキーワードをすべて押さえています。", icon="✅")

    st.caption(
        f"要点カバー率: {matched}/{total} キーワード"
    )


def _render_character_remaining_badge(current: float, limit: Optional[int]) -> None:
    _ensure_character_meter_styles()
    if limit is None:
        st.markdown(
            "<div class='char-remaining-badge ok' role='status' aria-live='polite'>✍️ 目安は100字前後です</div>",
            unsafe_allow_html=True,
        )
        return

    remaining = limit - current
    if remaining < 0:
        tone = "over"
        icon = "⚠️"
        label = f"{_format_fullwidth_length(abs(remaining))}字オーバー"
    elif remaining <= 20:
        tone = "warn"
        icon = "⏱️"
        label = f"残り {_format_fullwidth_length(max(remaining, 0))}字"
    else:
        tone = "ok"
        icon = "✍️"
        label = f"残り {_format_fullwidth_length(remaining)}字"
    st.markdown(
        f"<div class='char-remaining-badge {tone}' role='status' aria-live='polite'>{icon} {label}</div>",
        unsafe_allow_html=True,
    )


def _render_character_counter(text: str, limit: Optional[int]) -> None:
    fullwidth_length = _compute_fullwidth_length(text)
    if limit is None:
        _render_character_remaining_badge(fullwidth_length, None)
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
    _render_character_remaining_badge(fullwidth_length, limit)
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


def _ensure_keyword_feedback_styles() -> None:
    if st.session_state.get("_keyword_feedback_styles_injected"):
        return
    st.markdown(
        """
        <style>
        .coverage-pill {
            display: inline-flex;
            align-items: center;
            gap: 0.35rem;
            padding: 0.35rem 0.75rem;
            border-radius: 999px;
            font-weight: 600;
            font-size: 0.82rem;
        }
        .coverage-pill.good {
            background: rgba(134, 239, 172, 0.55);
            color: #166534;
        }
        .coverage-pill.warn {
            background: rgba(253, 230, 138, 0.7);
            color: #92400e;
        }
        .coverage-breakdown {
            margin: 0.35rem 0 0.5rem;
            display: flex;
            flex-direction: column;
            gap: 0.25rem;
        }
        .coverage-row {
            display: grid;
            grid-template-columns: 4.5rem 1fr auto;
            align-items: center;
            gap: 0.4rem;
            font-size: 0.78rem;
        }
        .coverage-row__label {
            font-weight: 600;
            color: #1f2937;
        }
        .coverage-row__bar {
            position: relative;
            height: 0.55rem;
            border-radius: 999px;
            overflow: hidden;
            background: #e2e8f0;
        }
        .coverage-row__fill {
            position: absolute;
            left: 0;
            top: 0;
            bottom: 0;
        }
        .coverage-row__fill.good {
            background: rgba(134, 239, 172, 0.85);
        }
        .coverage-row__fill.warn {
            background: rgba(253, 230, 138, 0.85);
        }
        .coverage-row__meta {
            color: #475569;
        }
        .keyword-highlight {
            background: rgba(125, 211, 252, 0.25);
            padding: 0.05rem 0.2rem;
            border-radius: 0.4rem;
            font-weight: 600;
        }
        .keyword-highlight.hit {
            background: rgba(134, 239, 172, 0.55);
            color: #065f46;
        }
        .keyword-highlight.miss {
            background: rgba(254, 202, 202, 0.65);
            color: #7f1d1d;
        }
        .answer-compare-grid {
            display: grid;
            gap: 1rem;
            grid-template-columns: repeat(auto-fit, minmax(240px, 1fr));
        }
        .answer-compare-block {
            padding: 0.75rem 0.9rem;
            border-radius: 12px;
            background: rgba(248, 250, 252, 0.9);
            border: 1px solid rgba(148, 163, 184, 0.35);
        }
        .answer-compare-block pre {
            white-space: pre-wrap;
            font-family: "Noto Sans JP", "Yu Gothic", sans-serif;
            font-size: 0.85rem;
            line-height: 1.65;
        }
        .answer-compare-heading {
            margin: 0 0 0.5rem;
            font-size: 0.9rem;
            font-weight: 600;
            color: #0f172a;
        }
        .answer-snapshot-actions {
            display: flex;
            flex-wrap: wrap;
            gap: 0.5rem;
        }
        .connector-pill {
            display: inline-flex;
            align-items: center;
            gap: 0.35rem;
            padding: 0.35rem 0.75rem;
            border-radius: 999px;
            font-weight: 600;
            font-size: 0.82rem;
        }
        .connector-pill.good {
            background: rgba(167, 243, 208, 0.7);
            color: #065f46;
        }
        .connector-pill.warn {
            background: rgba(254, 240, 138, 0.85);
            color: #92400e;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )
    st.session_state["_keyword_feedback_styles_injected"] = True


_ACTION_SUFFIXES = [
    "する",
    "化",
    "向上",
    "改善",
    "強化",
    "促進",
    "導入",
    "実施",
    "最適化",
    "短縮",
    "低減",
    "育成",
    "連携",
]


def _categorize_keyword(keyword: str) -> str:
    keyword = str(keyword).strip()
    if not keyword:
        return "その他"
    if any(keyword.endswith(suffix) for suffix in _ACTION_SUFFIXES):
        return "述語"
    return "名詞"


def _summarize_keyword_categories(keyword_hits: Mapping[str, bool]) -> Dict[str, Dict[str, int]]:
    summary: Dict[str, Dict[str, int]] = {
        "名詞": {"hit": 0, "miss": 0},
        "述語": {"hit": 0, "miss": 0},
        "その他": {"hit": 0, "miss": 0},
    }
    for keyword, hit in keyword_hits.items():
        category = _categorize_keyword(keyword)
        bucket = summary.setdefault(category, {"hit": 0, "miss": 0})
        if hit:
            bucket["hit"] += 1
        else:
            bucket["miss"] += 1
    return summary


def _render_keyword_coverage_meter(text: str, keywords: Iterable[str]) -> Mapping[str, bool]:
    """Render the keyword coverage meter and return the hit map."""

    cleaned = [str(keyword).strip() for keyword in keywords if str(keyword).strip()]
    if not cleaned:
        return {}
    hits = scoring.keyword_match_score(text, cleaned)
    return hits


def _render_keyword_coverage_from_hits(keyword_hits: Mapping[str, bool]) -> None:
    if not keyword_hits:
        return
    _ensure_keyword_feedback_styles()
    total = len(keyword_hits)
    matched = sum(1 for hit in keyword_hits.values() if hit)
    ratio = matched / max(total, 1)
    tone = "good" if ratio >= 0.7 else "warn"
    pill_html = (
        f"<div class='coverage-pill {tone}'>要点被覆率 {ratio * 100:.0f}%"
        f" <span>({matched} / {total})</span></div>"
    )
    st.markdown(pill_html, unsafe_allow_html=True)

    category_summary = _summarize_keyword_categories(keyword_hits)
    rows: List[str] = []
    for label in ("名詞", "述語", "その他"):
        counts = category_summary.get(label) or {"hit": 0, "miss": 0}
        total_category = counts["hit"] + counts["miss"]
        if total_category == 0:
            continue
        coverage = counts["hit"] / total_category
        bar_tone = "good" if coverage >= 0.7 else "warn"
        rows.append(
            dedent(
                """
                <div class='coverage-row'>
                    <span class='coverage-row__label'>{label}</span>
                    <div class='coverage-row__bar'>
                        <div class='coverage-row__fill {tone}' style='width: {width:.0f}%;'></div>
                    </div>
                    <span class='coverage-row__meta'>{hit} / {total}</span>
                </div>
                """
            ).format(
                label=html.escape(label),
                tone=bar_tone,
                width=coverage * 100,
                hit=counts["hit"],
                total=total_category,
            )
        )
    if rows:
        st.markdown("<div class='coverage-breakdown'>" + "".join(rows) + "</div>", unsafe_allow_html=True)


def _render_causal_connector_indicator(
    text: str,
    *,
    stats: Optional[Dict[str, object]] = None,
    show_breakdown: bool = False,
) -> Dict[str, object]:
    if stats is None:
        stats = scoring.analyze_causal_connectors(text)
    if not text.strip():
        return stats
    _ensure_keyword_feedback_styles()
    total = int(stats.get("total_hits", 0) or 0)
    sentence_count = int(stats.get("sentence_count", 0) or 0) or 1
    tone = "good" if total >= 1 else "warn"
    pill_html = (
        f"<div class='connector-pill {tone}'>因果チェッカー: 接続語 {total} 件 / {sentence_count} 文</div>"
    )
    st.markdown(pill_html, unsafe_allow_html=True)
    if tone == "warn":
        st.caption("『その結果』『よって』などの接続詞で因果の骨格を明示しましょう。")
    elif total >= sentence_count:
        st.caption("因果の接続が明確です。この調子で骨格を保ちましょう。")
    if show_breakdown:
        counts: Dict[str, int] = stats.get("counts") or {}
        if counts:
            ordered = sorted(counts.items(), key=lambda item: (-item[1], item[0]))
            detail = " / ".join(f"{connector}×{count}" for connector, count in ordered)
            st.caption(f"検出された接続詞: {detail}")
        else:
            st.caption("接続詞が検出されませんでした。結論→理由の順で接続語を挿入しましょう。")
    return stats


def _render_model_answer_diff(learner_answer: str, model_answer: str) -> None:
    """Render an HTML diff table comparing learnerと模範解答."""

    if "_diff_css_injected" not in st.session_state:
        st.markdown(
            dedent(
                """
                <style>
                    table.diff { width: 100%; border-collapse: collapse; }
                    .diff_header { background: #e2e8f0; font-weight: 600; padding: 0.25rem 0.5rem; }
                    .diff_next { background: #f8fafc; }
                    .diff_add { background: #dcfce7; }
                    .diff_chg { background: #fef3c7; }
                    .diff_sub { background: #fee2e2; }
                    table.diff td { padding: 0.2rem 0.4rem; font-size: 0.85rem; vertical-align: top; }
                </style>
                """
            ),
            unsafe_allow_html=True,
        )
        st.session_state["_diff_css_injected"] = True

    if not model_answer:
        st.caption("模範解答が未登録のため差分を表示できません。")
        return
    if not learner_answer.strip():
        st.caption("解答が未入力のため差分を表示できません。")
        return

    diff_html = difflib.HtmlDiff(wrapcolumn=42).make_table(
        learner_answer.splitlines(),
        model_answer.splitlines(),
        fromdesc="あなたの解答",
        todesc="模範解答",
        context=True,
        numlines=2,
    )
    st.markdown(f"<div class='diff-wrapper'>{diff_html}</div>", unsafe_allow_html=True)


def _resolve_question_keywords(question: Mapping[str, Any]) -> List[str]:
    raw = question.get("keywords") or question.get("キーワード")
    if raw is None:
        return []
    if isinstance(raw, str):
        parts = re.split(r"[、,;\n]", raw)
        return [part.strip() for part in parts if part.strip()]
    if isinstance(raw, Iterable):
        return [str(item).strip() for item in raw if str(item).strip()]
    return []


def _resolve_question_skill_tags(question: Mapping[str, Any]) -> List[str]:
    raw = question.get("skill_tags") or question.get("skills")
    if raw is None:
        return []
    if isinstance(raw, str):
        parts = re.split(r"[、,;\n]", raw)
        return [part.strip() for part in parts if part.strip()]
    if isinstance(raw, Iterable):
        return [str(item).strip() for item in raw if str(item).strip()]
    return []


def _classify_difficulty_label(
    metadata_label: Optional[str], avg_ratio: Optional[float]
) -> str:
    label = (metadata_label or "").strip()
    if label:
        return label
    if avg_ratio is None:
        return "未分類"
    try:
        ratio = float(avg_ratio)
    except (TypeError, ValueError):
        return "未分類"
    if ratio >= 0.7:
        return "易しい"
    if ratio >= 0.5:
        return "標準"
    return "難しい"


def _format_difficulty_hint(avg_ratio: Optional[float]) -> str:
    if avg_ratio is None:
        return "平均データなし"
    try:
        ratio = float(avg_ratio)
    except (TypeError, ValueError):
        return "平均データなし"
    return f"平均得点率 {ratio * 100:.0f}%"


def _get_saved_answer_payload(key: str) -> Dict[str, Any]:
    storage = st.session_state.setdefault("saved_answers", {})
    payload = storage.get(key)
    if isinstance(payload, dict):
        payload.setdefault("autosave", "")
        payload.setdefault("snapshots", [])
        return payload
    if isinstance(payload, str):
        payload_dict = {"autosave": payload, "snapshots": []}
    else:
        payload_dict = {"autosave": "", "snapshots": []}
    storage[key] = payload_dict
    return payload_dict


def _update_autosaved_answer(key: str, text: str) -> None:
    payload = _get_saved_answer_payload(key)
    payload["autosave"] = text
    st.session_state.saved_answers[key] = payload


def _save_answer_snapshot(key: str, text: str, *, label: Optional[str] = None) -> Dict[str, Any]:
    payload = _get_saved_answer_payload(key)
    snapshots: List[Dict[str, Any]] = payload.setdefault("snapshots", [])
    snapshot_id = uuid.uuid4().hex
    timestamp = datetime.now(timezone.utc).isoformat()
    normalized_label = label.strip() if label else ""
    if not normalized_label:
        normalized_label = f"案{len(snapshots) + 1}"
    entry = {
        "id": snapshot_id,
        "label": normalized_label,
        "text": text,
        "created_at": timestamp,
    }
    snapshots.append(entry)
    # Keep only the latest 10 snapshots per question to avoid bloating session state.
    if len(snapshots) > 10:
        del snapshots[:-10]
    st.session_state.saved_answers[key] = payload
    return entry


def _delete_answer_snapshot(key: str, snapshot_id: str) -> None:
    payload = _get_saved_answer_payload(key)
    snapshots: List[Dict[str, Any]] = payload.get("snapshots", [])
    payload["snapshots"] = [snap for snap in snapshots if snap.get("id") != snapshot_id]
    st.session_state.saved_answers[key] = payload


def _format_snapshot_label(entry: Mapping[str, Any]) -> str:
    label = str(entry.get("label") or "案")
    timestamp = entry.get("created_at")
    display_time = ""
    if isinstance(timestamp, str) and timestamp:
        try:
            dt = datetime.fromisoformat(timestamp)
            display_time = dt.strftime("%m/%d %H:%M")
        except ValueError:
            display_time = ""
    if display_time:
        return f"{label} ({display_time})"
    return label


def _highlight_keywords_in_text(
    text: str, keyword_hits: Mapping[str, bool], *, include_missing: bool = False
) -> str:
    if not text:
        return ""
    escaped = html.escape(text)
    if not keyword_hits:
        return escaped

    ordered_keywords = sorted(
        [(kw, hit) for kw, hit in keyword_hits.items() if kw],
        key=lambda item: len(item[0]),
        reverse=True,
    )

    for keyword, hit in ordered_keywords:
        if not include_missing and not hit:
            continue
        pattern = re.escape(keyword)

        def _repl(match: re.Match[str]) -> str:
            return (
                f"<span class='keyword-highlight {'hit' if hit else 'miss'}'>"
                f"{html.escape(match.group(0))}</span>"
            )

        escaped = re.sub(pattern, _repl, escaped)
    return escaped


def _summarize_strengths_and_gaps(
    keyword_hits: Mapping[str, bool],
    connector_stats: Optional[Mapping[str, Any]],
    analysis: Optional[Mapping[str, Any]],
) -> Tuple[List[str], List[str]]:
    strengths: List[str] = []
    improvements: List[str] = []

    if keyword_hits:
        matched = [kw for kw, hit in keyword_hits.items() if hit]
        missed = [kw for kw, hit in keyword_hits.items() if not hit]
        if matched:
            strengths.append("キーワード: " + "、".join(matched[:5]))
            if len(matched) > 5:
                strengths[-1] += " ほか"
        if missed:
            improvements.append("未使用キーワード: " + "、".join(missed[:5]))
            if len(missed) > 5:
                improvements[-1] += " ほか"

    if connector_stats:
        total_hits = int(connector_stats.get("total_hits") or 0)
        per_sentence = float(connector_stats.get("per_sentence") or 0.0)
        if total_hits >= 1:
            strengths.append(f"因果接続語: {total_hits}件検出")
        if per_sentence < 0.6:
            improvements.append("接続語が少ないため、因→果の橋渡し語を追加")

    if analysis:
        duplicates = analysis.get("duplicates", [])
        synonyms = analysis.get("synonyms", [])
        enumerations = analysis.get("enumerations", [])
        suggestions = analysis.get("suggestions", [])
        if not (duplicates or synonyms or enumerations):
            strengths.append("構成の重複は見当たりません")
        else:
            if duplicates:
                improvements.append("重複語: " + "、".join(duplicates[:3]))
            if synonyms:
                improvements.append("言い換えの重複: " + "、".join(synonyms[:3]))
            if enumerations:
                improvements.append("列挙の整理余地あり")
        for hint in suggestions[:2]:
            improvements.append(hint)

    if not strengths:
        strengths.append("答案の骨子を言語化できています")
    if not improvements:
        improvements.append("細部の表現を磨くとより伝わります")

    return strengths, improvements


def _classify_practice_status(stat: Optional[Mapping[str, Any]]) -> str:
    if not stat or int(stat.get("attempt_count") or 0) == 0:
        return "未実施"
    last_ratio = stat.get("last_ratio")
    if isinstance(last_ratio, (int, float)) and last_ratio < 0.6:
        return "要復習"
    return "安定"


def _split_sentences(text: str) -> List[str]:
    if not text:
        return []
    normalized = str(text).replace("\r\n", "\n").replace("\r", "\n")
    segments = re.findall(r"[^。！？!?\n]+[。！？!?]?", normalized)
    sentences: List[str] = []
    for segment in segments:
        stripped = segment.strip()
        if stripped:
            sentences.append(stripped)
    return sentences


def _extract_context_citations(
    answer_text: str,
    context_text: Optional[str],
    *,
    limit: int = 4,
) -> List[Dict[str, Any]]:
    if not answer_text.strip() or not context_text:
        return []

    answer_sentences = _split_sentences(answer_text)
    context_sentences = _split_sentences(context_text)
    if not answer_sentences or not context_sentences:
        return []

    citations: List[Dict[str, Any]] = []
    for answer_sentence in answer_sentences:
        matcher_best: Optional[difflib.Match] = None
        best_ratio = 0.0
        best_context: Optional[str] = None
        for ctx in context_sentences:
            matcher = difflib.SequenceMatcher(None, answer_sentence, ctx)
            ratio = matcher.ratio()
            match = matcher.find_longest_match(0, len(answer_sentence), 0, len(ctx))
            if match.size < 6:
                continue
            if ratio > best_ratio:
                best_ratio = ratio
                best_context = ctx
                matcher_best = match
        if best_context and matcher_best and best_ratio >= 0.25:
            start = matcher_best.b
            end = matcher_best.b + matcher_best.size
            highlighted = (
                html.escape(best_context[:start])
                + "<mark>"
                + html.escape(best_context[start:end])
                + "</mark>"
                + html.escape(best_context[end:])
            )
            citations.append(
                {
                    "answer": answer_sentence,
                    "context": best_context,
                    "context_html": highlighted,
                    "score": best_ratio,
                }
            )

    citations.sort(key=lambda item: item["score"], reverse=True)
    return citations[:limit]


def _track_question_activity(draft_key: str, text: str) -> Dict[str, Any]:
    activity = st.session_state.setdefault("question_activity", {})
    now = datetime.now(timezone.utc)
    record = activity.setdefault(
        draft_key,
        {
            "opened_at": now,
            "last_text": None,
            "revision_count": 0,
            "edit_history": [],
        },
    )
    record.setdefault("opened_at", now)
    record.setdefault("revision_count", 0)
    record.setdefault("edit_history", [])
    previous_text = record.get("last_text")
    trimmed_previous = (previous_text or "").strip()
    trimmed_current = text.strip()
    if previous_text is None:
        record["last_text"] = text
    if text != previous_text:
        if trimmed_current and record.get("first_input_at") is None:
            record["first_input_at"] = now
        elif trimmed_current and (trimmed_previous or record.get("first_input_at")):
            record["revision_count"] = int(record.get("revision_count", 0)) + 1
        record.setdefault("edit_history", []).append(
            {"timestamp": now.isoformat(), "length": len(trimmed_current)}
        )
        record["last_updated_at"] = now
    record["last_text"] = text
    record["last_seen_at"] = now
    return record


def _serialise_activity_record(record: Mapping[str, Any], submitted_at: datetime) -> Dict[str, Any]:
    def _to_datetime(value: Any) -> Optional[datetime]:
        if isinstance(value, datetime):
            return value
        if isinstance(value, str) and value:
            try:
                return datetime.fromisoformat(value)
            except ValueError:
                return None
        return None

    opened_dt = _to_datetime(record.get("opened_at"))
    first_input_dt = _to_datetime(record.get("first_input_at"))
    last_updated_dt = _to_datetime(record.get("last_updated_at"))
    base_dt = first_input_dt or opened_dt
    total_duration = None
    if base_dt and submitted_at >= base_dt:
        total_duration = int((submitted_at - base_dt).total_seconds())

    return {
        "opened_at": opened_dt.isoformat() if opened_dt else None,
        "first_input_at": first_input_dt.isoformat() if first_input_dt else None,
        "last_updated_at": (last_updated_dt or base_dt or submitted_at).isoformat(),
        "total_duration_seconds": total_duration,
        "revision_count": int(record.get("revision_count", 0) or 0),
        "edit_history": list(record.get("edit_history", [])),
    }


def _summarise_question_activity(problem: Mapping[str, Any], submitted_at: datetime) -> Dict[int, Dict[str, Any]]:
    activity = st.session_state.get("question_activity", {}) or {}
    summary: Dict[int, Dict[str, Any]] = {}
    questions = problem.get("questions") or []
    for question in questions:
        qid = question.get("id")
        if qid is None:
            continue
        key = _draft_key(problem.get("id"), qid)
        record = activity.get(key)
        if not record:
            continue
        summary[qid] = _serialise_activity_record(record, submitted_at)
    return summary


def _question_anchor_id(
    question: Mapping[str, Any], *, question_index: Optional[int] = None
) -> Optional[str]:
    anchor_source = (
        question_index
        if question_index is not None
        else question.get("order")
        or question.get("設問番号")
        or question.get("prompt")
        or question.get("id")
    )
    if anchor_source is None:
        return None
    anchor_slug = re.sub(r"[^0-9a-zA-Z]+", "-", str(anchor_source)).strip("-")
    if not anchor_slug:
        anchor_slug = str(question.get("id") or "question")
    return f"question-q{anchor_slug}"


def _emit_scroll_script(target_id: str, *, focus_selector: Optional[str] = None) -> None:
    """Inject a small script that scrolls the page to the given element."""

    if not target_id:
        return

    focus_selector_json = json.dumps(focus_selector) if focus_selector else "null"
    script = dedent(
        f"""
        <script>
        const targetId = {json.dumps(target_id)};
        const focusSelector = {focus_selector_json};
        const scrollIntoView = () => {{
            const root = window.parent?.document ?? document;
            let anchor = root.getElementById(targetId);
            if (!anchor) {{
                anchor = root.querySelector(`[data-anchor-id="${{targetId}}"]`);
            }}
            if (anchor) {{
                anchor.scrollIntoView({{ behavior: "smooth", block: "start" }});
                if (focusSelector) {{
                    const focusTarget = anchor.querySelector(focusSelector) || root.querySelector(focusSelector);
                    if (focusTarget) {{
                        focusTarget.focus({{ preventScroll: true }});
                    }}
                }}
            }} else {{
                setTimeout(scrollIntoView, 200);
            }}
        }};
        setTimeout(scrollIntoView, 120);
        </script>
        """
    ).strip()
    components.html(script, height=0)


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
    saved_payload = _get_saved_answer_payload(key)
    if key not in st.session_state.drafts:
        st.session_state.drafts[key] = saved_payload.get("autosave", "")

    textarea_state_key = f"{widget_prefix}{key}"

    pending_updates = st.session_state.get("_pending_textarea_updates")
    if pending_updates and textarea_state_key in pending_updates:
        st.session_state[textarea_state_key] = pending_updates.pop(textarea_state_key)
        if not pending_updates:
            st.session_state.pop("_pending_textarea_updates", None)

    if not anchor_id:
        anchor_id = _question_anchor_id(question, question_index=question_index)
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

    autosave_state = st.session_state.setdefault("_autosave_status", {})
    value = st.session_state.drafts.get(key, "")
    help_text = f"文字数目安: {question['character_limit']}字" if question["character_limit"] else ""
    placeholder_hint = "ここに解答を入力してください。重要語を箇条書きにしてから文章化すると構成が整います。"
    limit_value: Optional[int] = None
    raw_limit = question.get("character_limit")
    if raw_limit:
        try:
            limit_value = int(raw_limit)
            placeholder_hint = (
                f"ここに解答を入力してください（目安: {limit_value}字）。"
                " 重要語を箇条書きにしてから文章化すると構成が整います。"
            )
        except (TypeError, ValueError):
            limit_value = None

    container_id = f"answer-section-{key}"
    st.markdown(
        f"<div id=\"{container_id}\" class=\"practice-answer-section\">",
        unsafe_allow_html=True,
    )

    keywords = [kw for kw in _resolve_question_keywords(question) if str(kw).strip()]
    keyword_hits: Mapping[str, bool] = {}
    connector_stats: Dict[str, Any] = {}
    analysis: Dict[str, Any] = {}

    with st.expander("📝 解答入力パネル", expanded=True):
        st.markdown(
            "<p class=\"practice-autosave-caption\">入力内容は自動保存され、ページ移動後も復元できます。</p>",
            unsafe_allow_html=True,
        )
        answer_col, support_col = st.columns([0.64, 0.36], gap="large")

        with answer_col:
            header_cols = st.columns([0.68, 0.32], gap="small")
            header_cols[0].markdown(
                "<p class=\"answer-panel-label\">解答入力</p>",
                unsafe_allow_html=True,
            )
            autosave_placeholder = header_cols[1].empty()

            st.markdown(
                "<div class='answer-editor' role='group' aria-label='解答入力欄'>",
                unsafe_allow_html=True,
            )
            text = st.text_area(
                label=question["prompt"],
                key=textarea_state_key,
                value=value,
                height=220,
                help=help_text,
                placeholder=placeholder_hint,
                disabled=disabled,
            )
            st.markdown("</div>", unsafe_allow_html=True)
            _track_question_activity(key, text)

            if keywords:
                keyword_hits = _render_keyword_coverage_meter(text, keywords)
            _render_answer_quality_meter(
                text,
                limit_value,
                keyword_hits,
                keywords_registered=len(keywords),
            )

            analysis_toggle_key = f"mock_keyword_analysis::{key}"
            analysis_visible = st.session_state.get(analysis_toggle_key, False)
            toggle_label = "語句分析を閉じる" if analysis_visible else "語句分析を開く"
            if st.button(toggle_label, key=f"{analysis_toggle_key}::button"):
                st.session_state[analysis_toggle_key] = not analysis_visible
                analysis_visible = not analysis_visible

            if analysis_visible:
                if keyword_hits:
                    _render_keyword_analysis_panel(keyword_hits)
                elif keywords:
                    st.caption("入力するとキーワードのヒット状況が表示されます。")
                else:
                    st.caption("キーワードが未登録の設問です。必要な要点を自分で整理しましょう。")
            elif not keywords:
                st.caption("キーワードはまだ登録されていません。与件から重要語を抜き出しましょう。")

            connector_stats = _render_causal_connector_indicator(text)
            analysis = _render_mece_status_labels(text)
            with st.expander("MECE/因果スキャナ", expanded=bool(text.strip())):
                _render_mece_causal_scanner(text, analysis=analysis)

            st.session_state.drafts[key] = text
            _update_autosaved_answer(key, text)
            now_display = datetime.now().strftime("%H:%M:%S")
            autosave_state[key] = {"saved_at": now_display, "hash": hashlib.sha1(text.encode("utf-8")).hexdigest()}
            autosave_placeholder.markdown(
                dedent(
                    f"""
                    <div class="autosave-indicator autosave-indicator--saved" aria-live="polite">
                        <span class="autosave-indicator__toggle">自動保存</span>
                        <span class="autosave-indicator__status">保存済み <span class="autosave-indicator__time">{now_display}</span></span>
                    </div>
                    """
                ).strip(),
                unsafe_allow_html=True,
            )

            status_placeholder = st.empty()
            saved_text = saved_payload.get("autosave", "")
            restore_disabled = not saved_text
            if restore_disabled:
                status_placeholder.caption("復元できる下書きはまだありません。")
            if st.button(
                "下書きを復元",
                key=f"restore_{key}",
                disabled=restore_disabled,
            ):
                st.session_state.drafts[key] = saved_text
                _queue_textarea_update(textarea_state_key, saved_text)
                status_placeholder.info("保存済みの下書きを復元しました。")

        with support_col:
            st.markdown("<p class=\"support-panel-label\">ヒント・テンプレート</p>", unsafe_allow_html=True)
            _render_intent_cards(question, key, textarea_state_key)
            _render_case_frame_shortcuts(case_label, key, textarea_state_key)

    pending_focus_id = st.session_state.get("_pending_focus_question")
    if st.session_state.get("_practice_scroll_requested") and pending_focus_id == question.get("id"):
        _emit_scroll_script(container_id, focus_selector=f"#{container_id} textarea")
        st.session_state["_practice_scroll_requested"] = False
        st.session_state.pop("_pending_focus_question", None)


    with st.expander("保存済みの案と模範解答比較", expanded=False):
        snapshot_label_key = f"snapshot_label::{key}"
        default_label = st.session_state.get(snapshot_label_key, "")
        snapshot_label = st.text_input(
            "案のラベル",
            key=snapshot_label_key,
            value=default_label,
            placeholder="例: 第1案 / フレーム修正案",
            help="現在の答案を任意の名前で保存し、後から比較・復元できます。",
        )
        if st.button(
            "現在の内容を案として保存",
            key=f"save_snapshot_{key}",
            disabled=not text.strip(),
        ):
            entry = _save_answer_snapshot(key, text, label=snapshot_label)
            st.session_state[snapshot_label_key] = ""
            st.success(f"「{entry['label']}」を保存しました。", icon="💾")
            saved_payload = _get_saved_answer_payload(key)

        snapshots = saved_payload.get("snapshots", [])
        if snapshots:
            snapshot_options = [snap["id"] for snap in snapshots]
            snapshot_select_key = f"snapshot_select::{key}"
            selected_snapshot_id = st.selectbox(
                "保存済みの案",
                options=snapshot_options,
                key=snapshot_select_key,
                format_func=lambda sid: _format_snapshot_label(
                    next((snap for snap in snapshots if snap["id"] == sid), {})
                ),
            )
            selected_snapshot = next(
                (snap for snap in snapshots if snap["id"] == selected_snapshot_id),
                None,
            )
            action_cols = st.columns([0.4, 0.3, 0.3])
            with action_cols[0]:
                if st.button(
                    "この案をエディタに読み込む",
                    key=f"load_snapshot_{key}",
                    disabled=selected_snapshot is None,
                ) and selected_snapshot:
                    st.session_state.drafts[key] = selected_snapshot.get("text", "")
                    _queue_textarea_update(
                        textarea_state_key, selected_snapshot.get("text", "")
                    )
                    st.success(f"「{selected_snapshot.get('label', '案')}」を復元しました。", icon="📄")
            with action_cols[1]:
                comparison_choice_key = f"snapshot_compare_choice::{key}"
                compare_with_snapshot = st.checkbox(
                    "この案と比較",
                    key=comparison_choice_key,
                    value=st.session_state.get(comparison_choice_key, False),
                    help="チェックを入れると下の比較ビューでこの案を参照します。",
                )
            with action_cols[2]:
                if st.button(
                    "案を削除",
                    key=f"delete_snapshot_{key}",
                    disabled=selected_snapshot is None,
                ) and selected_snapshot:
                    _delete_answer_snapshot(key, selected_snapshot_id)
                    st.warning("選択した案を削除しました。", icon="🗑️")
                    saved_payload = _get_saved_answer_payload(key)
                    snapshots = saved_payload.get("snapshots", [])
                    if snapshots:
                        st.session_state[snapshot_select_key] = snapshots[-1]["id"]
                    else:
                        st.session_state.pop(snapshot_select_key, None)

            comparison_text = text
            comparison_label = "現在の答案"
            if snapshots and compare_with_snapshot:
                selected_snapshot = next(
                    (snap for snap in snapshots if snap["id"] == st.session_state.get(snapshot_select_key)),
                    selected_snapshot,
                )
                if selected_snapshot:
                    comparison_text = selected_snapshot.get("text", "")
                    comparison_label = f"保存案: {selected_snapshot.get('label', '案')}"
            model_answer = _normalize_text_block(question.get("model_answer")) or ""
            if model_answer:
                st.markdown("---")
                st.markdown("**模範解答との比較ビュー**")
                _ensure_keyword_feedback_styles()
                user_highlight = _highlight_keywords_in_text(
                    comparison_text,
                    keyword_hits,
                )
                model_highlight = _highlight_keywords_in_text(
                    model_answer,
                    keyword_hits,
                    include_missing=True,
                )
                compare_cols = st.columns(2)
                with compare_cols[0]:
                    st.markdown(f"<p class='answer-compare-heading'>{html.escape(comparison_label)}</p>", unsafe_allow_html=True)
                    st.markdown(
                        f"<div class='answer-compare-block'><pre>{user_highlight}</pre></div>",
                        unsafe_allow_html=True,
                    )
                with compare_cols[1]:
                    st.markdown(
                        "<p class='answer-compare-heading'>模範解答</p>",
                        unsafe_allow_html=True,
                    )
                    st.markdown(
                        f"<div class='answer-compare-block'><pre>{model_highlight}</pre></div>",
                        unsafe_allow_html=True,
                    )
                strengths, improvements = _summarize_strengths_and_gaps(
                    keyword_hits,
                    connector_stats,
                    analysis,
                )
                summary_cols = st.columns(2)
                with summary_cols[0]:
                    st.markdown("**強み**")
                    for point in strengths:
                        st.write(f"- {point}")
                with summary_cols[1]:
                    st.markdown("**次に改善すべき点**")
                    for point in improvements:
                        st.write(f"- {point}")
            else:
                st.info("模範解答が未登録のため、比較ビューは利用できません。", icon="ℹ️")
        else:
            st.caption("保存済みの案はまだありません。案として保存すると比較・復元が行えます。")

    st.markdown("</div>", unsafe_allow_html=True)
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

    _render_help_label(
        "リトリーバル・プラクティス",
        "回答前に重要キーワードを記憶から書き出して想起率を測る練習モードです。自動採点で覚えている語句を確認できます。",
        level=3,
        variant="heading",
    )
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

        st.markdown(
            "<div class='answer-editor answer-editor--note' role='group' aria-label='キーワード想起メモ欄'>",
            unsafe_allow_html=True,
        )
        guess_text = st.text_area(
            "思い出したキーワードを箇条書きで入力",
            key=guess_state_key,
            height=180,
            placeholder="例: SWOT分析\nブランド認知向上\n外注管理",
            help="Enterキーで改行し、思い出した単語を一行ずつ入力してください。",
        )
        guess_lines = [
            re.sub(r"^[\-・\s]+", "", line).strip()
            for line in guess_text.splitlines()
            if line.strip()
        ]
        if guess_lines:
            items = "".join(f"<li>{html.escape(item)}</li>" for item in guess_lines)
            st.markdown(
                f"<ul class='retrieval-bullet-preview' role='list'>{items}</ul>",
                unsafe_allow_html=True,
            )
            st.caption(f"入力したキーワード: {len(guess_lines)}件")
        else:
            st.caption("答えを見る前に、自分の言葉でキーワードを書き出してみましょう。")
        st.markdown("</div>", unsafe_allow_html=True)

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


def _prepare_history_log_export(history_df: pd.DataFrame) -> pd.DataFrame:
    export_df = history_df.copy()
    if "日付" in export_df.columns:
        export_df["日付"] = pd.to_datetime(export_df["日付"], errors="coerce")
    score_rate: List[Optional[float]] = []
    if "得点" in export_df.columns and "満点" in export_df.columns:
        scores = pd.to_numeric(export_df["得点"], errors="coerce")
        max_scores = pd.to_numeric(export_df["満点"], errors="coerce")
        for score_value, max_value in zip(scores, max_scores):
            if pd.isna(score_value) or pd.isna(max_value) or not max_value:
                score_rate.append(None)
            else:
                try:
                    rate_value = round(float(score_value) / float(max_value) * 100, 1)
                except ZeroDivisionError:
                    rate_value = None
                score_rate.append(rate_value)
        if score_rate:
            export_df["得点率(%)"] = score_rate
    if "学習時間(分)" in export_df.columns:
        export_df["学習時間(分)"] = export_df["学習時間(分)"].map(
            lambda v: round(float(v), 1) if pd.notna(v) else v
        )
    if "日付" in export_df.columns:
        export_df.sort_values("日付", inplace=True)
        export_df["日付"] = export_df["日付"].dt.strftime("%Y-%m-%d %H:%M:%S")
    preferred_columns = [
        "attempt_id",
        "日付",
        "年度",
        "事例",
        "タイトル",
        "得点",
        "満点",
        "得点率(%)",
        "学習時間(分)",
        "モード",
    ]
    ordered_columns = [col for col in preferred_columns if col in export_df.columns]
    remaining_columns = [col for col in export_df.columns if col not in ordered_columns]
    export_df = export_df[ordered_columns + remaining_columns]
    return export_df


def _prepare_answer_log_export(keyword_records: List[Dict[str, Any]]) -> pd.DataFrame:
    rows: List[Dict[str, Any]] = []
    for record in keyword_records:
        keyword_hits = record.get("keyword_hits") or {}
        matched_keywords = [kw for kw, hit in keyword_hits.items() if hit]
        missing_keywords = [kw for kw, hit in keyword_hits.items() if not hit]
        score = record.get("score")
        max_score = record.get("max_score")
        score_ratio = None
        if score is not None and max_score:
            try:
                score_ratio = round(float(score) / float(max_score) * 100, 1)
            except ZeroDivisionError:
                score_ratio = None
        keyword_coverage = record.get("keyword_coverage")
        coverage_pct = None
        if keyword_coverage is not None:
            try:
                coverage_pct = round(float(keyword_coverage) * 100, 1)
            except (TypeError, ValueError):
                coverage_pct = None
        duration_seconds = record.get("duration_seconds")
        duration_minutes = None
        if duration_seconds is not None:
            try:
                duration_minutes = round(float(duration_seconds) / 60.0, 1)
            except (TypeError, ValueError):
                duration_minutes = None
        mode_label = "模試" if record.get("mode") == "mock" else "演習"
        rows.append(
            {
                "attempt_id": record.get("attempt_id"),
                "日付": record.get("submitted_at"),
                "年度": record.get("year"),
                "事例": record.get("case_label"),
                "タイトル": record.get("title"),
                "設問": record.get("question_order"),
                "問題文": record.get("prompt"),
                "解答": record.get("answer_text"),
                "得点": score,
                "満点": max_score,
                "得点率(%)": score_ratio,
                "自己評価": record.get("self_evaluation"),
                "モード": mode_label,
                "所要時間(分)": duration_minutes,
                "キーワード網羅率(%)": coverage_pct,
                "含まれたキーワード": "、".join(matched_keywords) if matched_keywords else "-",
                "不足キーワード": "、".join(missing_keywords) if missing_keywords else "-",
                "フィードバック": record.get("feedback"),
            }
        )
    export_df = pd.DataFrame(rows)
    if export_df.empty:
        return export_df
    export_df["日付"] = pd.to_datetime(export_df["日付"], errors="coerce")
    export_df.sort_values(["日付", "年度", "事例", "設問"], inplace=True)
    export_df["日付"] = export_df["日付"].dt.strftime("%Y-%m-%d %H:%M:%S")
    export_df["設問"] = pd.to_numeric(export_df["設問"], errors="coerce")
    preferred_columns = [
        "attempt_id",
        "日付",
        "年度",
        "事例",
        "タイトル",
        "設問",
        "問題文",
        "解答",
        "得点",
        "満点",
        "得点率(%)",
        "キーワード網羅率(%)",
        "自己評価",
        "所要時間(分)",
        "モード",
        "含まれたキーワード",
        "不足キーワード",
        "フィードバック",
    ]
    ordered_columns = [col for col in preferred_columns if col in export_df.columns]
    remaining_columns = [col for col in export_df.columns if col not in ordered_columns]
    export_df = export_df[ordered_columns + remaining_columns]
    return export_df


def _build_learning_log_archive(score_csv: bytes, answer_csv: Optional[bytes]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("score_history.csv", score_csv)
        if answer_csv is not None:
            archive.writestr("answer_history.csv", answer_csv)
    buffer.seek(0)
    return buffer.read()


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
        weekly_processed = weekly_summary.copy()
        if "モジュール" not in weekly_processed.columns:
            if "事例" in weekly_processed.columns:
                weekly_processed = weekly_processed.rename(columns={"事例": "モジュール"})
            else:
                weekly_processed = pd.DataFrame()
        if not weekly_processed.empty and "期間開始" not in weekly_processed.columns:
            if "週" in weekly_processed.columns:
                weekly_processed["期間開始"] = pd.to_datetime(
                    weekly_processed["週"], errors="coerce"
                )
            elif "期間" in weekly_processed.columns:
                weekly_processed["期間開始"] = pd.to_datetime(
                    weekly_processed["期間"], errors="coerce"
                )
        weekly_sorted = pd.DataFrame()
        if not weekly_processed.empty and {"モジュール", "期間開始"}.issubset(
            weekly_processed.columns
        ):
            weekly_sorted = weekly_processed.sort_values(["モジュール", "期間開始"])
        if not weekly_sorted.empty:
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
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
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

        duration_seconds = record.get("duration_seconds")
        try:
            duration_minutes = (
                float(duration_seconds) / 60.0 if duration_seconds is not None else None
            )
        except (TypeError, ValueError):
            duration_minutes = None

        self_eval_label = record.get("self_evaluation") or SELF_EVALUATION_DEFAULT
        self_eval_score = _self_evaluation_score(record.get("self_evaluation"))

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
                "自己評価": self_eval_label,
                "所要時間(分)": duration_minutes,
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
                    "durations": [],
                    "self_eval_scores": [],
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
            stat["durations"].append(duration_minutes)
            if self_eval_score is not None:
                stat["self_eval_scores"].append(self_eval_score)

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

    def _mean(values: Iterable[Optional[float]]) -> Optional[float]:
        filtered = [float(v) for v in values if v is not None]
        if not filtered:
            return None
        return sum(filtered) / len(filtered)

    for keyword, stat in keyword_stats.items():
        attempts = stat["attempts"]
        hits = stat["hits"]
        hit_rate = hits / attempts if attempts else 0.0
        avg_duration = _mean(stat.get("durations", []))
        avg_eval_score = _mean(stat.get("self_eval_scores", []))
        summary_rows.append(
            {
                "キーワード": keyword,
                "出題数": attempts,
                "達成率(%)": hit_rate * 100,
                "主な事例": "、".join(sorted(stat["cases"])) if stat["cases"] else "-",
                "出題年度": "、".join(sorted(stat["years"])) if stat["years"] else "-",
                "平均所要時間(分)": round(avg_duration, 1) if avg_duration is not None else None,
                "自己評価傾向": _self_evaluation_label(avg_eval_score),
            }
        )

        reasons: List[str] = []
        needs_focus = False
        if attempts >= 1 and hit_rate < 0.6:
            needs_focus = True
            reasons.append("キーワード達成率が60%未満")
        if avg_eval_score is not None and avg_eval_score >= 0.6:
            needs_focus = True
            reasons.append("自己評価が不安寄り")
        if avg_duration is not None and avg_duration >= 8:
            needs_focus = True
            reasons.append(f"平均所要時間 {avg_duration:.1f}分")

        if needs_focus:
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
                    "reason": " / ".join(reasons) if reasons else None,
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


def _format_question_summary_label(
    question: Mapping[str, Any],
    *,
    case_label: Optional[str],
    year: Optional[str],
) -> str:
    prompt = _normalize_text_block(
        _select_first(
            question,
            ["prompt", "設問文", "問題文", "question_text", "body"],
        )
    ) or ""
    preview = prompt.splitlines()[0] if prompt else ""
    if len(preview) > 24:
        preview = preview[:24] + "…"
    order = (
        question.get("order")
        or question.get("question_order")
        or question.get("question_index")
    )
    order_label = f"設問{order}" if order else "設問"
    label_year = _format_reiwa_label(year or "") if year else ""
    parts = [part for part in [label_year, case_label, order_label] if part]
    head = " ".join(parts) if parts else order_label
    if preview:
        return f"{head}: {preview}"
    return head


def _case1_selected_question_key(problem_id: Optional[int]) -> str:
    if problem_id is None:
        return "case1_selected_question::default"
    return f"case1_selected_question::{problem_id}"


def _case1_problem_identifier(problem: Mapping[str, Any]) -> str:
    return str(
        problem.get("id")
        or problem.get("slug")
        or problem.get("title")
        or "default"
    )


def _case1_question_identifier(
    question: Mapping[str, Any], question_index: int
) -> str:
    question_id = question.get("id")
    if question_id is None:
        return f"index-{question_index}"
    return str(question_id)


def _case1_highlight_state_key(
    problem_identifier: str, question_identifier: str
) -> str:
    return f"case1-highlight::{problem_identifier}::{question_identifier}"


def _case1_guidance_store() -> Dict[str, Dict[str, str]]:
    return st.session_state.setdefault("case1_step_guidance", {})


def _case1_step_state_key(draft_key: str) -> str:
    return f"case1_step_state::{draft_key}"


def _case1_support_visit_key(draft_key: str, tab_name: str) -> str:
    return f"{draft_key}::{tab_name}"


def _case1_resolve_draft_key(
    problem: Mapping[str, Any], question: Mapping[str, Any], question_index: int
) -> str:
    problem_id = problem.get("id")
    try:
        return _draft_key(int(problem_id), int(question.get("id")))
    except (TypeError, ValueError, AttributeError):
        return _draft_key(int(problem_id or 0), int(-(question_index + 1)))


def _case1_question_status(
    problem: Mapping[str, Any], question: Mapping[str, Any], question_index: int
) -> Tuple[str, str]:
    draft_key = _case1_resolve_draft_key(problem, question, question_index)
    text = st.session_state.get("drafts", {}).get(draft_key, "")
    if not text.strip():
        return "未回答", "empty"

    fullwidth_length = _compute_fullwidth_length(text)
    limit_value: Optional[int] = None
    raw_limit = question.get("character_limit") or question.get("制限字数")
    try:
        if raw_limit not in (None, ""):
            limit_value = int(raw_limit)
    except (TypeError, ValueError):
        limit_value = None

    keyword_store: Mapping[str, Mapping[str, bool]] = st.session_state.get(
        "_case1_keyword_hits", {}
    )
    keyword_hits = keyword_store.get(draft_key) if isinstance(keyword_store, Mapping) else {}
    coverage_ratio = 0.0
    if keyword_hits:
        total = len(keyword_hits)
        if total:
            matched = sum(1 for value in keyword_hits.values() if value)
            coverage_ratio = matched / total

    completion_length = (
        int(limit_value * 0.85)
        if limit_value is not None
        else 200
    )
    if fullwidth_length >= completion_length and coverage_ratio >= 0.6:
        return "完了", "done"
    return "下書き", "draft"


def _guide_case1_to_step(
    draft_key: str,
    step_label: str,
    *,
    tab_state_key: Optional[str],
    highlight_state_key: Optional[str],
) -> None:
    message = ""
    if "設問確認" in step_label:
        message = "設問一覧カードから対象設問を選び、配点と要求を確認しましょう。"
    elif "与件文" in step_label:
        if highlight_state_key:
            st.session_state[highlight_state_key] = True
        message = "与件文ハイライトを開き、重要箇所にマーカーを付けましょう。"
    elif "答案作成" in step_label:
        message = "答案作成ステップです。回答欄に骨子と結論を入力しましょう。"
    elif "自己分析" in step_label:
        if tab_state_key:
            st.session_state[tab_state_key] = "構造解析"
        message = "構造解析タブでMECE/因果を確認し、抜け漏れをチェックしましょう。"
    elif "模範解答" in step_label:
        if tab_state_key:
            st.session_state[tab_state_key] = "模範解答"
        message = "模範解答タブを開き、自分の答案と比較して改善点を洗い出しましょう。"
    elif "メモ" in step_label:
        if tab_state_key:
            st.session_state[tab_state_key] = "復習メモ"
        message = "復習メモタブで気づきを記録し、次回の改善に活かしましょう。"

    guidance_store = _case1_guidance_store()
    if message:
        guidance_store[draft_key] = {"label": step_label, "message": message}
    else:
        guidance_store.pop(draft_key, None)


def _render_case1_stepper(
    step_state: Mapping[str, bool],
    *,
    draft_key: str,
    tab_state_key: Optional[str],
    highlight_state_key: Optional[str],
) -> None:
    steps = [
        {"label": "①設問確認", "done": bool(step_state.get("question"))},
        {"label": "②与件文ハイライト", "done": bool(step_state.get("highlight"))},
        {"label": "③答案作成", "done": bool(step_state.get("answer"))},
        {"label": "④自己分析", "done": bool(step_state.get("analysis"))},
        {"label": "⑤模範解答比較", "done": bool(step_state.get("model"))},
        {"label": "⑥メモ保存", "done": bool(step_state.get("memo"))},
    ]

    total_steps = len(steps)
    completed = sum(1 for step in steps if step["done"])
    progress_percent = int((completed / total_steps) * 100) if total_steps else 0
    try:
        next_pending = next(idx for idx, step in enumerate(steps) if not step["done"])
    except StopIteration:
        next_pending = total_steps - 1

    segments_html: List[str] = []
    for idx, step in enumerate(steps):
        classes = ["case1-step"]
        if step["done"]:
            classes.append("is-done")
        elif idx == next_pending:
            classes.append("is-current")
        else:
            classes.append("is-pending")
        status = "完了" if step["done"] else ("進行中" if idx == next_pending else "待機")
        segments_html.append(
            "<div class='{cls}'><span class='case1-step-label'>{label}</span>"
            "<span class='case1-step-status'>{status}</span></div>".format(
                cls=" ".join(classes),
                label=html.escape(step["label"]),
                status=html.escape(status),
            )
        )

    stepper_html = (
        "<div class='case1-stepper'>"
        "<div class='case1-stepper-progress'><div class='case1-stepper-progress-bar' style='width:{width}%;'></div></div>"
        "<div class='case1-stepper-steps'>{segments}</div>"
        "</div>"
    ).format(width=progress_percent, segments="".join(segments_html))
    st.markdown(stepper_html, unsafe_allow_html=True)

    guidance_store = _case1_guidance_store()
    guidance = guidance_store.get(draft_key)
    if guidance:
        for step in steps:
            if step["label"] == guidance.get("label") and step["done"]:
                guidance_store.pop(draft_key, None)
                guidance = None
                break
    if guidance:
        st.info(guidance.get("message", "次のステップに進みましょう。"), icon="➡️")

    if completed < total_steps:
        next_step = steps[next_pending]
        if st.button(
            f"次のステップへ進む（{next_step['label']}）",
            key=f"case1-stepper-next::{draft_key}",
            use_container_width=True,
        ):
            _guide_case1_to_step(
                draft_key,
                next_step["label"],
                tab_state_key=tab_state_key,
                highlight_state_key=highlight_state_key,
            )
            st.rerun()


def _render_case1_question_cards(
    problem: Mapping[str, Any],
    question_entries: Sequence[Mapping[str, Any]],
    *,
    selected_index: int,
    selected_key: str,
) -> None:
    questions = problem.get("questions", [])
    if not questions:
        return

    st.markdown("<div class='case1-card-grid'>", unsafe_allow_html=True)
    per_row = 3
    problem_id = problem.get("id")
    for start in range(0, len(question_entries), per_row):
        stop = min(start + per_row, len(question_entries))
        row_entries = list(enumerate(question_entries[start:stop], start=start))
        columns = st.columns(len(row_entries))
        for col, (idx, entry) in zip(columns, row_entries):
            if idx >= len(questions):
                continue
            question = questions[idx]
            draft_key = _case1_resolve_draft_key(problem, question, idx)
            status_label, status_class = _case1_question_status(problem, question, idx)
            score = question.get("max_score")
            score_label = (
                f"{int(score)}点" if isinstance(score, (int, float)) else (f"{score}点" if score else "配点-")
            )
            icon_map = {"done": "✅", "draft": "✍️", "empty": "⬜️"}
            status_icon = icon_map.get(status_class, "✍️")
            label_lines = [
                f"設問{idx + 1}｜{score_label}",
                entry.get("preview") or "概要未登録",
                f"{status_icon} {status_label}",
            ]
            button_key = f"case1-nav::{problem_id}::{idx}"
            with col:
                st.markdown("<div class='case1-question-card'>", unsafe_allow_html=True)
                clicked = st.button(
                    "\n".join(label_lines),
                    key=button_key,
                    use_container_width=True,
                    type="primary" if idx == selected_index else "secondary",
                    help=entry.get("title") or entry.get("preview") or "設問全文を表示",
                )
                st.markdown("</div>", unsafe_allow_html=True)
                if clicked:
                    st.session_state[selected_key] = idx
                    st.rerun()
    st.markdown("</div>", unsafe_allow_html=True)


def _render_case1_integrated_monitor(
    *,
    length: int,
    limit_value: Optional[int],
    coverage_ratio: Optional[float],
    matched_keywords: Optional[int],
    total_keywords: Optional[int],
    noun_count: int,
    verb_count: int,
) -> None:
    if limit_value and limit_value > 0:
        remaining = limit_value - length
        char_ratio = min(max(length / limit_value, 0.0), 1.6)
        if remaining < 0:
            char_status = "alert"
            char_detail = f"{abs(remaining)}字オーバー"
        elif remaining <= max(int(limit_value * 0.1), 10):
            char_status = "warn"
            char_detail = f"残り {remaining}字"
        else:
            char_status = "ok"
            char_detail = f"残り {remaining}字"
    else:
        baseline = 240
        remaining = baseline - length
        char_ratio = min(max(length / baseline, 0.0), 1.6)
        if remaining < 0:
            char_status = "warn"
            char_detail = f"{length}字（目安超）"
        else:
            char_status = "neutral"
            char_detail = f"{length}字"

    if total_keywords:
        matched = matched_keywords or 0
        coverage_ratio = coverage_ratio or 0.0
        coverage_percent = coverage_ratio * 100
        if coverage_ratio >= 0.8:
            coverage_status = "ok"
        elif coverage_ratio >= 0.5:
            coverage_status = "warn"
        else:
            coverage_status = "alert"
        coverage_detail = f"{matched}/{total_keywords} ({coverage_percent:.0f}%)"
        coverage_value = min(max(coverage_ratio, 0.0), 1.0)
    else:
        coverage_status = "neutral"
        coverage_detail = "-"
        coverage_value = 0.2

    if verb_count >= 3:
        structure_status = "ok"
    elif verb_count >= 2:
        structure_status = "warn"
    else:
        structure_status = "alert"
    structure_ratio = min(max(verb_count / 3.0, 0.0), 1.0)
    structure_detail = f"名詞{noun_count} / 述語{verb_count}"

    segments = [
        {
            "label": "残字数",
            "detail": char_detail,
            "status": char_status,
            "ratio": char_ratio,
        },
        {
            "label": "要点",
            "detail": coverage_detail,
            "status": coverage_status,
            "ratio": coverage_value,
        },
        {
            "label": "名詞/述語",
            "detail": structure_detail,
            "status": structure_status,
            "ratio": structure_ratio,
        },
    ]

    segment_html = []
    for segment in segments:
        flex_value = 1.0 + segment["ratio"] * 1.5
        segment_html.append(
            "<div class='case1-monitor-segment {status}' style='flex:{flex};'>"
            "<span class='case1-monitor-label'>{label}</span>"
            "<span class='case1-monitor-detail'>{detail}</span>"
            "</div>".format(
                status=html.escape(segment["status"]),
                flex=f"{flex_value:.2f}",
                label=html.escape(segment["label"]),
                detail=html.escape(segment["detail"]),
            )
        )

    st.markdown(
        "<div class='case1-monitor'>"
        "<div class='case1-monitor-bar'>{segments}</div>"
        "</div>".format(segments="".join(segment_html)),
        unsafe_allow_html=True,
    )


def _render_case1_support_panel(
    problem: Mapping[str, Any],
    question: Mapping[str, Any],
    *,
    question_index: int,
    problem_context: Optional[str],
    draft_key: str,
    textarea_key: str,
    answer_context: Mapping[str, Any],
) -> Mapping[str, bool]:
    support_state = {
        "highlight_done": False,
        "analysis_done": False,
        "model_done": False,
        "memo_saved": False,
    }

    st.markdown("<div class='case1-support-pane'>", unsafe_allow_html=True)

    problem_identifier = _case1_problem_identifier(problem)
    question_identifier = _case1_question_identifier(question, question_index)
    highlight_state_key = _case1_highlight_state_key(
        problem_identifier, question_identifier
    )

    if problem_context:
        expanded_default = st.session_state.get(highlight_state_key, False)
        if highlight_state_key not in st.session_state:
            st.session_state[highlight_state_key] = expanded_default
        with st.expander("与件文ハイライト", expanded=expanded_default):
            search_key = f"case1-search-{problem_identifier}::{question_identifier}"
            search_query = st.text_input(
                "与件文内検索",
                key=search_key,
                placeholder="キーワードを入力",
            )
            match_count, highlight_snapshot = _render_problem_context_block(
                problem_context,
                search_query,
                snapshot_key=str(problem_identifier),
                auto_palette=True,
                auto_save=True,
                compact_controls=True,
            )
            if highlight_snapshot:
                highlight_store = st.session_state.setdefault("context_highlights", {})
                highlight_store[str(problem_identifier)] = highlight_snapshot
            highlight_store = st.session_state.get("context_highlights", {})
            if highlight_store.get(str(problem_identifier)):
                support_state["highlight_done"] = True
                st.session_state[highlight_state_key] = True
            if search_query:
                if match_count:
                    st.caption(f"該当箇所: {match_count}件")
                else:
                    st.caption("該当箇所は見つかりませんでした。")
                st.session_state[highlight_state_key] = True
            else:
                st.caption("ハイライトは自動保存されます。次回アクセス時も復元されます。")
    else:
        st.info("与件文が未登録のため、ハイライトツールは利用できません。設定ページで与件文を追加してください。", icon="ℹ")

    _render_case_frame_shortcuts(problem.get("case_label"), draft_key, textarea_key)

    tab_state_key = f"case1-support-tab::{draft_key}"
    visited_map = st.session_state.setdefault("case1_support_visits", {})
    previous_selected = st.session_state.get(tab_state_key)
    if previous_selected:
        visited_map[_case1_support_visit_key(draft_key, previous_selected)] = True

    support_tabs = ["模範解答", "採点ガイドライン", "キーワード評価", "構造解析", "復習メモ"]

    def _tab_label(name: str) -> str:
        visited = visited_map.get(_case1_support_visit_key(draft_key, name))
        icon = "✅" if visited else "⬜️"
        return f"{icon} {name}"

    selected_tab = st.radio(
        "補助タブ",
        options=support_tabs,
        key=tab_state_key,
        format_func=_tab_label,
        horizontal=True,
        label_visibility="collapsed",
    )
    visited_map[_case1_support_visit_key(draft_key, selected_tab)] = True

    support_state["tab_state_key"] = tab_state_key
    support_state["highlight_state_key"] = highlight_state_key
    support_state["problem_identifier"] = problem_identifier
    support_state["question_identifier"] = question_identifier

    support_state["analysis_done"] = visited_map.get(
        _case1_support_visit_key(draft_key, "構造解析"),
        False,
    )
    support_state["model_done"] = visited_map.get(
        _case1_support_visit_key(draft_key, "模範解答"),
        False,
    )

    st.caption("タブを切り替えて模範解答や構造分析を確認しましょう。閲覧済みのタブにはチェックが付きます。")

    keyword_hits: Mapping[str, bool] = answer_context.get("keyword_hits") or {}
    model_answer_text = _normalize_text_block(question.get("model_answer"))

    if selected_tab == "模範解答":
        if model_answer_text:
            st.markdown("**模範解答（抜粋）**")
            points = _extract_case1_model_points(model_answer_text)
            if points:
                items = "".join(f"<li>{html.escape(point)}</li>" for point in points)
                st.markdown(f"<ul class='case1-model-points'>{items}</ul>", unsafe_allow_html=True)
            with st.expander("模範解答全文", expanded=False):
                st.write(model_answer_text)
        else:
            st.info("模範解答が未登録です。設定ページで追加すると比較しやすくなります。", icon="ℹ")

    elif selected_tab == "採点ガイドライン":
        aim_text = _normalize_text_block(
            question.get("question_aim")
            or question.get("uploaded_question_aim")
            or question.get("設問の狙い")
            or question.get("狙い")
        )
        if aim_text:
            st.markdown("**設問の狙い**")
            st.write(aim_text)
        explanation_text = _normalize_text_block(
            question.get("explanation")
            or question.get("detailed_explanation")
            or question.get("解説")
        )
        if explanation_text:
            st.markdown("**解説ポイント**")
            st.write(explanation_text)
        if model_answer_text and not answer_context.get("model_points_rendered"):
            points = _extract_case1_model_points(model_answer_text)
            if points:
                st.markdown("**評価観点の要約**")
                items = "".join(f"<li>{html.escape(point)}</li>" for point in points)
                st.markdown(f"<ul class='case1-model-points'>{items}</ul>", unsafe_allow_html=True)

    elif selected_tab == "キーワード評価":
        keywords = _resolve_question_keywords(question)
        if keywords:
            matched = [kw for kw in keywords if keyword_hits.get(kw)]
            missing = [kw for kw in keywords if not keyword_hits.get(kw)]
            st.markdown("**評価キーワード**")
            if matched:
                st.success("含まれたキーワード: " + "、".join(matched), icon="✅")
            if missing:
                st.warning("不足キーワード: " + "、".join(missing), icon="🔍")
        else:
            st.info("評価キーワードが未登録です。設定ページで登録すると自動チェックが可能です。", icon="ℹ")

    elif selected_tab == "構造解析":
        text = answer_context.get("text", "")
        analysis = answer_context.get("analysis")
        analysis = analysis or (_analyze_mece_causal(text) if text.strip() else None)
        _render_mece_status_labels(text)
        _render_mece_causal_scanner(text, analysis=analysis)

        templates = CASE_CAUSAL_TEMPLATES.get(problem.get("case_label"), [])
        if templates:
            template_key = f"case1-causal-template::{draft_key}"
            default_index = st.session_state.get(template_key, 0)
            indices = list(range(len(templates)))
            selected_index = st.selectbox(
                "因果テンプレートを選択",
                indices,
                index=min(default_index, len(templates) - 1),
                format_func=lambda idx: templates[idx]["label"],
                key=template_key,
            )
            template = templates[selected_index]
            st.markdown(
                f"<div class='case1-structure-diagram'>{html.escape(template['diagram'])}</div>",
                unsafe_allow_html=True,
            )
            st.markdown(
                f"<div class='case1-structure-snippet'>{html.escape(template['snippet'])}</div>",
                unsafe_allow_html=True,
            )
            if st.button(
                "因果テンプレを挿入",
                key=f"case1-causal-insert::{draft_key}::{selected_index}",
                use_container_width=True,
            ):
                _insert_template_snippet(draft_key, textarea_key, template["snippet"])
        else:
            st.caption("この事例のテンプレートは未登録です。必要に応じてメモ欄に独自テンプレートを残しましょう。")

    else:  # 復習メモ
        memo_store = st.session_state.setdefault("case1_memos", {})
        memo_key = f"case1-memo::{draft_key}"
        memo_text = memo_store.get(draft_key, "")
        new_text = st.text_area(
            "復習メモを残す",
            value=memo_text,
            height=120,
            placeholder="気づきや次回への改善ポイントを記録しましょう。",
            key=memo_key,
        )
        if st.button(
            "メモを保存",
            key=f"case1-memo-save::{draft_key}",
            use_container_width=True,
        ):
            memo_store[draft_key] = new_text
            st.success("メモを保存しました。", icon="💾")

    memo_store = st.session_state.get("case1_memos", {})
    support_state["memo_saved"] = bool(memo_store.get(draft_key))

    st.markdown("</div>", unsafe_allow_html=True)

    return support_state
def _ensure_case1_styles() -> None:
    if st.session_state.get("_case1_styles_injected"):
        return

    st.markdown(
        dedent(
            """
            <style>
            .case1-header {
                padding: 0.6rem 0 0.4rem;
            }
            .case1-header__title {
                font-size: 1.45rem;
                font-weight: 700;
                color: #0f172a;
                margin-bottom: 0.2rem;
            }
            .case1-header__subtitle {
                font-size: 0.95rem;
                color: #475569;
                margin: 0;
            }
            .case1-toolbar__status {
                display: inline-flex;
                align-items: center;
                justify-content: center;
                padding: 0.45rem 0.75rem;
                border-radius: 999px;
                background: rgba(34, 197, 94, 0.12);
                color: #166534;
                font-weight: 600;
                margin-top: 0.35rem;
            }
            .case1-context-pane,
            .case1-main-pane {
                padding: 0.95rem 1.1rem;
                background: rgba(248, 250, 252, 0.95);
                border: 1px solid rgba(148, 163, 184, 0.25);
                border-radius: 18px;
                box-shadow: 0 16px 30px rgba(15, 23, 42, 0.08);
            }
            .case1-context-pane {
                min-height: 620px;
                display: flex;
                flex-direction: column;
                gap: 0.6rem;
            }
            .case1-context__intro {
                font-weight: 600;
                color: #1f2937;
                margin: 0;
            }
            .case1-main-pane {
                display: flex;
                flex-direction: column;
                gap: 0.8rem;
            }
            .case1-question-prompt {
                font-size: 1.05rem;
                font-weight: 600;
                color: #0f172a;
                margin: 0.2rem 0 0.4rem;
            }
            .case1-nav-table {
                margin-top: 0.6rem;
            }
            .case1-nav-table .stDataFrame div[data-testid="stDataFrame"] {
                border-radius: 12px;
                border: 1px solid rgba(148, 163, 184, 0.25);
            }
            .case1-bottom-section {
                margin-top: 1.6rem;
                padding: 1.1rem 1.2rem;
                border-radius: 18px;
                background: rgba(15, 23, 42, 0.04);
                border: 1px solid rgba(148, 163, 184, 0.25);
            }
            @media (max-width: 1024px) {
                .case1-context-pane,
                .case1-main-pane {
                    padding: 0.85rem 0.9rem;
                }
            }
            @media (max-width: 860px) {
                .case1-toolbar__status {
                    width: 100%;
                    margin-top: 0.75rem;
                }
            }
            .case1-answer-toolbar {
                display: grid;
                grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
                gap: 0.75rem;
                margin: 0.5rem 0 0.25rem;
            }
            .case1-metrics-badge {
                background: rgba(59, 130, 246, 0.1);
                border: 1px solid rgba(59, 130, 246, 0.35);
                border-radius: 12px;
                padding: 0.45rem 0.75rem;
                font-size: 0.86rem;
                color: #1f2937;
                font-weight: 600;
            }
            .case1-progress-caption {
                font-size: 0.85rem;
                color: #475569;
                margin-top: 0.2rem;
            }
            .case1-model-points {
                margin: 0.35rem 0 0;
                padding-left: 1.1rem;
                color: #1f2937;
            }
            .case1-model-points li {
                margin-bottom: 0.25rem;
                line-height: 1.65;
            }
            .case1-stepper {
                margin: 1rem 0 1.2rem;
                padding: 0.85rem 1rem;
                background: rgba(248, 250, 252, 0.95);
                border: 1px solid rgba(148, 163, 184, 0.3);
                border-radius: 18px;
                box-shadow: 0 12px 24px rgba(15, 23, 42, 0.06);
            }
            .case1-stepper-progress {
                position: relative;
                height: 6px;
                border-radius: 999px;
                background: rgba(203, 213, 225, 0.6);
                overflow: hidden;
                margin-bottom: 0.75rem;
            }
            .case1-stepper-progress-bar {
                position: absolute;
                top: 0;
                left: 0;
                bottom: 0;
                background: linear-gradient(90deg, #3b82f6, #22c55e);
                border-radius: inherit;
                transition: width 0.4s ease;
            }
            .case1-stepper-steps {
                display: grid;
                grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
                gap: 0.6rem;
            }
            .case1-step {
                border-radius: 14px;
                padding: 0.55rem 0.75rem;
                display: flex;
                flex-direction: column;
                gap: 0.2rem;
                background: rgba(226, 232, 240, 0.55);
                color: #334155;
                border: 1px solid transparent;
            }
            .case1-step-label {
                font-size: 0.88rem;
                font-weight: 600;
            }
            .case1-step-status {
                font-size: 0.78rem;
                font-weight: 500;
            }
            .case1-step.is-done {
                background: rgba(134, 239, 172, 0.35);
                color: #14532d;
                border-color: rgba(34, 197, 94, 0.45);
            }
            .case1-step.is-current {
                background: rgba(191, 219, 254, 0.55);
                color: #1d4ed8;
                border-color: rgba(59, 130, 246, 0.55);
            }
            .case1-step.is-pending {
                background: rgba(226, 232, 240, 0.55);
                color: #475569;
                border-color: rgba(148, 163, 184, 0.35);
            }
            .case1-card-grid {
                margin: 1rem 0 1.4rem;
            }
            .case1-question-card {
                padding: 0.25rem 0.15rem;
            }
            .case1-question-card button[kind="secondary"],
            .case1-question-card button[kind="primary"] {
                text-align: left;
                white-space: pre-wrap;
                height: 100%;
                border-radius: 16px;
                padding: 0.75rem 0.9rem;
                line-height: 1.45;
                font-size: 0.9rem;
            }
            .case1-question-card button[kind="secondary"] {
                border: 1px solid rgba(148, 163, 184, 0.45);
                background: rgba(248, 250, 252, 0.75);
            }
            .case1-question-card button[kind="primary"] {
                background: linear-gradient(135deg, rgba(59, 130, 246, 0.9), rgba(79, 70, 229, 0.85));
                border: 1px solid rgba(59, 130, 246, 0.6);
            }
            .case1-monitor {
                margin: 0.9rem 0 0.6rem;
            }
            .case1-monitor-bar {
                display: flex;
                gap: 0.7rem;
                align-items: stretch;
            }
            .case1-monitor-segment {
                padding: 0.6rem 0.7rem;
                border-radius: 14px;
                background: rgba(226, 232, 240, 0.55);
                display: flex;
                flex-direction: column;
                gap: 0.2rem;
                min-width: 160px;
            }
            .case1-monitor-segment.ok {
                background: rgba(134, 239, 172, 0.35);
                color: #14532d;
            }
            .case1-monitor-segment.warn {
                background: rgba(253, 230, 138, 0.45);
                color: #92400e;
            }
            .case1-monitor-segment.alert {
                background: rgba(248, 113, 113, 0.45);
                color: #991b1b;
            }
            .case1-monitor-segment.neutral {
                background: rgba(226, 232, 240, 0.55);
                color: #334155;
            }
            .case1-monitor-label {
                font-size: 0.82rem;
                font-weight: 600;
            }
            .case1-monitor-detail {
                font-size: 0.76rem;
                font-weight: 500;
            }
            .case1-support-pane {
                padding: 0.9rem 1rem;
                background: rgba(248, 250, 252, 0.95);
                border-radius: 18px;
                border: 1px solid rgba(148, 163, 184, 0.25);
                box-shadow: 0 18px 30px rgba(15, 23, 42, 0.08);
                display: flex;
                flex-direction: column;
                gap: 1.1rem;
            }
            .case1-frame-library {
                padding: 0.75rem 0.9rem 0.9rem;
                background: rgba(241, 245, 249, 0.75);
                border-radius: 16px;
                border: 1px solid rgba(148, 163, 184, 0.25);
            }
            .case1-frame-title {
                font-size: 1rem;
                font-weight: 700;
                margin-bottom: 0.35rem;
            }
            .case1-frame-desc {
                font-size: 0.9rem;
                color: #1f2937;
                margin-bottom: 0.5rem;
            }
            .case1-frame-snippet {
                background: rgba(59, 130, 246, 0.08);
                border: 1px solid rgba(59, 130, 246, 0.18);
                border-radius: 14px;
                padding: 0.6rem 0.7rem;
                font-size: 0.88rem;
                line-height: 1.6;
                white-space: pre-wrap;
            }
            .case1-structure-diagram {
                font-weight: 600;
                font-size: 0.9rem;
                margin: 0.6rem 0 0.2rem;
            }
            .case1-structure-snippet {
                background: rgba(45, 212, 191, 0.12);
                border-radius: 12px;
                padding: 0.6rem 0.7rem;
                border: 1px solid rgba(13, 148, 136, 0.25);
                line-height: 1.6;
                font-size: 0.86rem;
                white-space: pre-wrap;
                margin-bottom: 0.4rem;
            }
            div[data-baseweb="tab-list"] > div {
                font-size: 0.92rem;
                font-weight: 600;
            }
            .case1-support-pane .stRadio [role="radiogroup"] > div {
                gap: 0.6rem;
                flex-wrap: wrap;
            }
            .case1-support-pane .stRadio [role="radio"] > div {
                border-radius: 999px;
                border: 1px solid rgba(148, 163, 184, 0.45);
                padding: 0.45rem 0.85rem;
                background: rgba(255, 255, 255, 0.85);
            }
            .case1-support-pane .stRadio [role="radio"][aria-checked="true"] > div {
                background: rgba(59, 130, 246, 0.15);
                border-color: rgba(59, 130, 246, 0.45);
            }
            .case1-flashcard-progress {
                margin: 0.6rem 0;
            }
            .case1-flashcard-steps p {
                margin: 0.25rem 0;
                color: #334155;
            }
            .case1-flashcard-modal {
                font-family: "Noto Sans JP", "Yu Gothic", sans-serif;
                background: rgba(15, 23, 42, 0.85);
                color: #f8fafc;
                padding: 1.2rem;
                border-radius: 20px;
            }
            .case1-flashcard-modal h3 {
                margin-top: 0;
            }
            .case1-flashcard-modal ul {
                margin: 0.8rem 0 1rem;
                padding-left: 1.2rem;
            }
            .case1-flashcard-modal button {
                padding: 0.45rem 1.1rem;
                border-radius: 999px;
                border: none;
                background: rgba(59, 130, 246, 0.9);
                color: #fff;
                font-weight: 600;
                cursor: pointer;
            }
            </style>
            """
        ),
        unsafe_allow_html=True,
    )
    st.session_state["_case1_styles_injected"] = True


def _extract_case1_model_points(
    model_answer: Optional[str], *, limit: int = 3
) -> List[str]:
    text = _normalize_text_block(model_answer)
    if not text:
        return []

    sentences: List[str] = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        fragments = re.split(r"[。！？?!]\s*", line)
        for fragment in fragments:
            cleaned = fragment.strip("・-‐— 　")
            if not cleaned:
                continue
            sentences.append(cleaned)
            if len(sentences) >= limit:
                break
        if len(sentences) >= limit:
            break

    if not sentences:
        sentences.append(text[:80].strip())

    return sentences[:limit]


def _render_case1_nav_tab(
    problem: Mapping[str, Any],
    question_entries: Sequence[Mapping[str, Any]],
    *,
    selected_index: int,
    selected_key: str,
) -> int:
    st.markdown("**STEP 1: 設問を選択**")
    if not question_entries:
        st.info("設問が登録されていません。設定ページで問題データを更新してください。", icon="ℹ")
        return 0

    options = list(range(len(question_entries)))
    labels = [entry.get("stepper") or entry.get("label") or f"設問{idx + 1}" for idx, entry in enumerate(question_entries)]
    choice = st.radio(
        "回答する設問を選択",
        options=options,
        index=min(max(selected_index, 0), len(options) - 1),
        format_func=lambda idx: labels[idx] if 0 <= idx < len(labels) else "設問",
        key=f"{selected_key}::nav",
    )

    rows: List[Dict[str, object]] = []
    keyword_store: Mapping[str, Mapping[str, bool]] = st.session_state.get("_case1_keyword_hits", {})
    question_specs: List[QuestionSpec] = [
        QuestionSpec(
            id=q.get("id"),
            prompt=q.get("prompt"),
            max_score=q.get("max_score"),
            model_answer=q.get("model_answer"),
            keywords=q.get("keywords"),
        )
        for q in problem.get("questions", [])
    ]

    missing_numbers = [
        idx
        for idx, q in enumerate(problem.get("questions", []), start=1)
        if q.get("id") is None
    ]

    if not st.session_state.practice_started:
        st.session_state.practice_started = datetime.now(timezone.utc)

    problem_id = problem.get("id")
    for idx, entry in enumerate(question_entries):
        question = problem.get("questions", [])[idx]
        try:
            draft_key = _draft_key(int(problem_id), int(question.get("id")))
        except (TypeError, ValueError, AttributeError):
            fallback_id = -(idx + 1)
            draft_key = _draft_key(int(problem_id or 0), int(fallback_id))
        text = st.session_state.drafts.get(draft_key, "") if hasattr(st.session_state, "drafts") else ""
        length_value = _compute_fullwidth_length(text)
        limit_value = None
        raw_limit = question.get("character_limit") if isinstance(question, Mapping) else None
        try:
            if raw_limit not in (None, ""):
                limit_value = int(raw_limit)
        except (TypeError, ValueError):
            limit_value = None
        hits = keyword_store.get(draft_key) if isinstance(keyword_store, Mapping) else None
        matched_count = None
        total_keywords = None
        if hits:
            total_keywords = len(hits)
            matched_count = sum(1 for value in hits.values() if value)
        rows.append(
            {
                "設問": entry.get("label") or f"設問{idx + 1}",
                "文字数": _format_fullwidth_length(length_value),
                "目安": limit_value if limit_value is not None else "-",
                "要点被覆": f"{matched_count}/{total_keywords}" if matched_count is not None and total_keywords else "-",
            }
        )

    if rows:
        nav_df = pd.DataFrame(rows)
        st.dataframe(nav_df, hide_index=True, width="stretch")

    return int(choice)


def _render_case1_answer_panel(
    problem: Mapping[str, Any],
    question: Mapping[str, Any],
    *,
    question_index: int,
    draft_key: str,
    textarea_key: str,
) -> Dict[str, Any]:
    prompt_text = _normalize_text_block(
        question.get("prompt") or question.get("設問見出し") or question.get("title")
    )
    if prompt_text:
        st.markdown(
            f"<p class='case1-question-prompt'>{html.escape(prompt_text)}</p>",
            unsafe_allow_html=True,
        )

    body_text = _normalize_text_block(
        _select_first(question, ["設問文", "問題文", "question_text", "body"])
    )
    if body_text:
        st.caption(body_text)

    saved_payload = _get_saved_answer_payload(draft_key)
    if hasattr(st.session_state, "drafts"):
        st.session_state.drafts.setdefault(draft_key, saved_payload.get("autosave", ""))
    else:
        st.session_state.drafts = {draft_key: saved_payload.get("autosave", "")}

    limit_hint = question.get("character_limit")
    placeholder = "ここに解答を入力してください。キーワードを散りばめ、因果でつなぎましょう。"
    if limit_hint not in (None, ""):
        try:
            limit_hint_int = int(limit_hint)
        except (TypeError, ValueError):
            limit_hint_int = None
        else:
            placeholder = f"ここに解答を入力してください（目安: {limit_hint_int}字）。重要語を明示し、因果で結びましょう。"

    st.markdown(
        "<p class='practice-autosave-caption'>入力内容は自動保存されます。</p>",
        unsafe_allow_html=True,
    )
    text = st.text_area(
        "回答入力",
        key=textarea_key,
        value=st.session_state.drafts.get(draft_key, ""),
        height=240,
        label_visibility="collapsed",
        placeholder=placeholder,
    )
    st.session_state.drafts[draft_key] = text
    _track_question_activity(draft_key, text)

    fullwidth_length = _compute_fullwidth_length(text)
    limit_value = None
    try:
        if limit_hint not in (None, ""):
            limit_value = int(limit_hint)
    except (TypeError, ValueError):
        limit_value = None

    keywords = _resolve_question_keywords(question)
    keyword_hits: Mapping[str, bool] = {}
    matched = 0
    total = 0
    coverage_ratio = None
    if keywords:
        cleaned_keywords = [keyword for keyword in keywords if keyword]
        if cleaned_keywords:
            keyword_hits = scoring.keyword_match_score(text, cleaned_keywords)
            total = len(keyword_hits)
            matched = sum(1 for value in keyword_hits.values() if value)
            coverage_ratio = matched / total if total else 0.0
            missing = [kw for kw, hit in keyword_hits.items() if not hit]
            if missing:
                st.caption("不足キーワード: " + "、".join(missing))
        else:
            st.caption("キーワードは未登録です。与件文から重要語を抽出しましょう。")
    else:
        st.caption("キーワードは未登録です。設定ページで登録すると進捗メーターが活用できます。")

    keyword_store = st.session_state.setdefault("_case1_keyword_hits", {})
    keyword_store[draft_key] = keyword_hits

    noun_count, verb_count = _count_case3_pos(text)
    _render_case1_integrated_monitor(
        length=fullwidth_length,
        limit_value=limit_value,
        coverage_ratio=coverage_ratio,
        matched_keywords=matched,
        total_keywords=total,
        noun_count=noun_count,
        verb_count=verb_count,
    )

    analysis = _analyze_mece_causal(text) if text.strip() else None

    _render_intent_cards(question, draft_key, textarea_key)

    return {
        "text": text,
        "keyword_hits": keyword_hits,
        "limit_value": limit_value,
        "fullwidth_length": fullwidth_length,
        "coverage_ratio": coverage_ratio,
        "matched_keywords": matched,
        "total_keywords": total,
        "noun_count": noun_count,
        "verb_count": verb_count,
        "analysis": analysis,
    }


def _render_case1_guideline_panel(
    question: Mapping[str, Any], keyword_hits: Mapping[str, bool]
) -> None:
    st.markdown("**STEP 3: 採点ガイドを確認**")

    keywords = _resolve_question_keywords(question)
    if keywords:
        st.markdown("**評価キーワード**")
        matched = [kw for kw in keywords if keyword_hits.get(kw)] if keyword_hits else []
        missing = [kw for kw in keywords if not keyword_hits.get(kw)] if keyword_hits else keywords
        if matched:
            st.success("含まれたキーワード: " + "、".join(matched), icon="✅")
        if missing:
            st.warning("不足キーワード: " + "、".join(missing), icon="🔍")
    else:
        st.info("評価キーワードが未登録です。", icon="ℹ")

    aim_text = _normalize_text_block(
        question.get("question_aim")
        or question.get("設問の狙い")
        or question.get("狙い")
    )
    if aim_text:
        st.markdown("**設問の狙い**")
        st.write(aim_text)

    explanation_text = _normalize_text_block(question.get("explanation") or question.get("解説"))
    if explanation_text:
        st.markdown("**解説ポイント**")
        st.write(explanation_text)

    model_answer_text = _normalize_text_block(question.get("model_answer"))
    if model_answer_text:
        points = _extract_case1_model_points(model_answer_text)
        st.markdown("**模範解答の要点**")
        if points:
            items = "".join(f"<li>{html.escape(point)}</li>" for point in points)
            st.markdown(f"<ul class='case1-model-points'>{items}</ul>", unsafe_allow_html=True)
        with st.expander("模範解答全文を表示", expanded=False):
            st.write(model_answer_text)


def _render_case1_flashcard_modal(
    problem_id: int, flashcards: Sequence[Mapping[str, Any]], modal_key: str
) -> None:
    modal_state = st.session_state.get(modal_key)
    if not modal_state:
        return

    card_index = int(modal_state.get("card_index", 0))
    if card_index < 0 or card_index >= len(flashcards):
        st.session_state.pop(modal_key, None)
        return

    card = flashcards[card_index]
    keywords = card.get("keywords", [])
    keyword_items = "".join(f"<li>{html.escape(str(keyword))}</li>" for keyword in keywords)
    prompt_text = html.escape(_normalize_text_block(card.get("prompt")) or "")
    title_text = html.escape(card.get("title") or "キーワード")

    modal_html = dedent(
        f"""
        <div class="case1-flashcard-modal">
            <h3>{title_text}</h3>
            <p>{prompt_text}</p>
            <h4>重要キーワード</h4>
            <ul>{keyword_items}</ul>
            <button type="button" id="case1-flashcard-close">閉じる</button>
        </div>
        <script>
        (function() {{
            const closeButton = document.getElementById('case1-flashcard-close');
            if (!window.Streamlit) {{
                window.Streamlit = {{ setComponentValue: () => {{}}, setFrameHeight: () => {{}}, setComponentReady: () => {{}} }};
            }}
            if (window.Streamlit.setComponentReady) {{
                window.Streamlit.setComponentReady();
            }}
            if (window.Streamlit.setFrameHeight) {{
                window.Streamlit.setFrameHeight(document.body.scrollHeight);
            }}
            if (closeButton) {{
                closeButton.addEventListener('click', () => {{
                    if (window.Streamlit.setComponentValue) {{
                        window.Streamlit.setComponentValue(JSON.stringify({{
                            type: 'case1FlashcardModal',
                            action: 'close'
                        }}));
                    }}
                }});
            }}
        }})();
        </script>
        """
    )

    component_value = components.html(modal_html, height=340)
    payload_raw = _extract_component_value(component_value)
    if payload_raw:
        try:
            payload = json.loads(payload_raw)
        except json.JSONDecodeError:
            payload = None
        if isinstance(payload, dict) and payload.get("type") == "case1FlashcardModal":
            st.session_state.pop(modal_key, None)


def _render_case1_retrieval_flashcards(problem: Mapping[str, Any]) -> None:
    flashcards: List[Dict[str, Any]] = []
    for index, question in enumerate(problem.get("questions", [])):
        keywords = [kw for kw in question.get("keywords", []) if kw]
        if not keywords:
            continue
        flashcards.append(
            {
                "title": f"設問{index + 1}: キーワード想起", 
                "prompt": question.get("prompt", ""),
                "keywords": keywords,
            }
        )

    if not flashcards:
        st.info("この問題ではキーワードが登録されていないため、リトリーバル・プラクティスを実施できません。", icon="ℹ")
        return

    st.markdown("### リトリーバル・プラクティス")
    st.markdown(
        "<div class='case1-flashcard-steps'>"
        "<p>① カードを開き、設問の狙いとキーワードを確認します。</p>"
        "<p>② 閉じた状態で思い出した語句を書き出し、想起力を可視化します。</p>"
        "<p>③ 次のカードへ進み、進捗バーで定着度を追跡します。</p>"
        "</div>",
        unsafe_allow_html=True,
    )

    problem_id = int(problem.get("id") or 0)
    state = _get_flashcard_state(problem_id, len(flashcards))
    modal_key = f"case1_flashcard_modal::{problem_id}"

    revealed = bool(state.get("revealed"))
    progress_ratio = (state.get("index", 0) + (1 if revealed else 0)) / max(len(flashcards), 1)
    st.progress(progress_ratio, text=f"カード {state.get('index', 0) + 1} / {len(flashcards)}")

    control_cols = st.columns([1, 1, 1])
    show_clicked = control_cols[0].button("カードを表示", key=f"case1_flashcard_show_{problem_id}")
    next_clicked = control_cols[1].button("次のカードへ", key=f"case1_flashcard_next_{problem_id}")
    shuffle_clicked = control_cols[2].button("シャッフル", key=f"case1_flashcard_shuffle_{problem_id}")

    if shuffle_clicked:
        state = _reset_flashcard_state(problem_id, len(flashcards))
    else:
        if show_clicked:
            state["revealed"] = True
            current_index = state.get("index", 0)
            order = state.get("order", list(range(len(flashcards))))
            target = order[current_index] if order else 0
            st.session_state[modal_key] = {"card_index": target}
        if next_clicked:
            state["index"] = (state.get("index", 0) + 1) % max(len(state.get("order", [])), 1)
            state["revealed"] = False

    st.session_state.flashcard_states[str(problem_id)] = state

    order = state.get("order", list(range(len(flashcards))))
    current_position = state.get("index", 0)
    card_index = order[current_position] if order else 0
    card = flashcards[card_index]

    guess_key = f"case1_flashcard_guess::{problem_id}::{card_index}"
    guess_text = st.text_area(
        "思い出したキーワード", key=guess_key, height=140, placeholder="例: 組織文化\n権限移譲\n評価制度" 
    )

    evaluation_key = f"case1_flashcard_eval::{problem_id}::{card_index}"
    evaluation = st.session_state.get(evaluation_key)
    if state.get("revealed") and guess_text.strip():
        evaluation = _evaluate_flashcard_guess(problem_id, card_index, card["keywords"], guess_text)
        st.session_state[evaluation_key] = evaluation

    if evaluation:
        accuracy = evaluation.get("accuracy", 0.0)
        st.progress(accuracy, text=f"想起率 {accuracy * 100:.0f}% ({evaluation.get('matched_count', 0)} / {evaluation.get('total_keywords', 0)})")
        if evaluation.get("matched"):
            st.success("想起できた語句: " + "、".join(evaluation["matched"]), icon="🧠")
        if evaluation.get("missed"):
            st.warning("思い出せなかった語句: " + "、".join(evaluation["missed"]), icon="🔁")
        if evaluation.get("extras"):
            st.caption("リストにない入力: " + "、".join(evaluation["extras"]))

    if st.session_state.get(modal_key):
        _render_case1_flashcard_modal(problem_id, flashcards, modal_key)


def _handle_case1_submission(
    problem: Mapping[str, Any],
    user: Mapping[str, Any],
    question_specs: Sequence[QuestionSpec],
    missing_numbers: Sequence[int],
) -> None:
    if missing_numbers:
        formatted = "、".join(f"設問{num}" for num in missing_numbers)
        st.error(
            f"{formatted} のIDが未登録のため、採点結果を保存できません。設定ページからデータを更新して再度お試しください。",
            icon="⚠️",
        )
        return

    submitted_at = datetime.now(timezone.utc)
    activity_summary = _summarise_question_activity(problem, submitted_at)
    answers: List[RecordedAnswer] = []
    problem_id = problem.get("id")
    for idx, (question, spec) in enumerate(zip(problem.get("questions", []), question_specs)):
        try:
            draft_key = _draft_key(int(problem_id), int(question.get("id")))
        except (TypeError, ValueError, AttributeError):
            draft_key = _draft_key(int(problem_id or 0), int(-(idx + 1)))
        text = st.session_state.drafts.get(draft_key, "")
        result = scoring.score_answer(text, spec)
        answers.append(
            RecordedAnswer(
                question_id=question.get("id"),
                answer_text=text,
                score=result.score,
                feedback=result.feedback,
                keyword_hits=result.keyword_hits,
                axis_breakdown=result.axis_breakdown,
                activity=activity_summary.get(question.get("id")),
            )
        )

    started_at = st.session_state.practice_started or submitted_at
    duration = int((submitted_at - started_at).total_seconds())
    total_score = sum(answer.score for answer in answers)
    total_max = sum(question.get("max_score") for question in problem.get("questions", []))
    score_ratio = (total_score / total_max) if total_max else 0.0

    attempt_id = database.record_attempt(
        user_id=user.get("id"),
        problem_id=problem_id,
        mode="practice",
        answers=answers,
        started_at=started_at,
        submitted_at=submitted_at,
        duration_seconds=duration,
    )
    database.update_spaced_review(
        user_id=user.get("id"),
        problem_id=problem_id,
        score_ratio=score_ratio,
        reviewed_at=submitted_at,
    )
    st.session_state.practice_started = None
    st.session_state.question_activity = {}

    st.success("採点が完了しました。結果を確認してください。")
    render_attempt_results(attempt_id)


def _render_case1_workspace(
    problem: Mapping[str, Any],
    user: Mapping[str, Any],
    *,
    problem_context: Optional[str],
) -> None:
    if problem.get("case_label") == "事例III":
        _render_case3_workspace(problem, user, problem_context=problem_context)
        return

    _ensure_case1_styles()

    question_entries: List[Dict[str, Any]] = []
    for idx, q in enumerate(problem.get("questions", []), start=1):
        raw_prompt = _normalize_text_block(q.get("prompt") or q.get("設問見出し") or "")
        preview_text = _format_preview_text(raw_prompt, 28) if raw_prompt else "概要未登録"
        question_entries.append(
            {
                "label": f"設問{idx}",
                "title": raw_prompt or f"設問{idx}",
                "preview": preview_text,
                "stepper": f"設問{idx}：{preview_text}" if preview_text else f"設問{idx}",
            }
        )

    if not question_entries:
        st.warning("設問が登録されていません。設定ページで問題データを更新してください。", icon="⚠️")
        return

    question_specs: List[QuestionSpec] = [
        QuestionSpec(
            id=q.get("id"),
            prompt=q.get("prompt"),
            max_score=q.get("max_score"),
            model_answer=q.get("model_answer"),
            keywords=q.get("keywords"),
        )
        for q in problem.get("questions", [])
    ]

    missing_numbers = [
        idx
        for idx, q in enumerate(problem.get("questions", []), start=1)
        if q.get("id") is None
    ]

    selected_key = _case1_selected_question_key(problem.get("id"))
    if selected_key not in st.session_state or st.session_state[selected_key] >= len(question_entries):
        st.session_state[selected_key] = 0

    if not st.session_state.practice_started:
        st.session_state.practice_started = datetime.now(timezone.utc)

    title = problem.get("title") or problem.get("name") or "過去問演習"
    st.markdown(
        f"<div class='case1-header'><div class='case1-header__title'>{html.escape(str(title))}</div>"
        "<p class='case1-header__subtitle'>与件文・回答・採点ガイドを1画面で操作できます。</p></div>",
        unsafe_allow_html=True,
    )

    toolbar_cols = st.columns([0.6, 0.2, 0.2])
    with toolbar_cols[0]:
        _render_practice_timer(problem.get("id"), confirm_on_start=True)
    with toolbar_cols[1]:
        st.markdown("<div class='case1-toolbar__status'>保存: 自動保存中</div>", unsafe_allow_html=True)
    with toolbar_cols[2]:
        if st.button("設定", key=f"case1-settings-{problem.get('id')}"):
            _request_navigation("設定")

    stepper_placeholder = st.empty()

    selected_index = st.session_state[selected_key]
    _render_case1_question_cards(
        problem,
        question_entries,
        selected_index=selected_index,
        selected_key=selected_key,
    )

    selected_index = st.session_state[selected_key]
    questions = problem.get("questions", [])
    if not questions:
        st.warning("設問データが見つかりません。設定ページを確認してください。", icon="⚠️")
        return
    question = questions[selected_index]

    draft_key = _case1_resolve_draft_key(problem, question, selected_index)
    textarea_key = f"case1::{draft_key}"

    answer_col, support_col = st.columns([0.62, 0.38], gap="large")

    with answer_col:
        st.markdown("<div class='case1-main-pane'>", unsafe_allow_html=True)
        answer_context = _render_case1_answer_panel(
            problem,
            question,
            question_index=selected_index,
            draft_key=draft_key,
            textarea_key=textarea_key,
        )

        if missing_numbers:
            formatted_numbers = "、".join(f"設問{num}" for num in missing_numbers)
            st.warning(
                f"{formatted_numbers} のIDが未登録のため、採点結果を保存できません。設定ページでデータを更新してください。",
                icon="⚠️",
            )

        submit = st.button(
            "AI採点に送信",
            type="primary",
            key=f"case1-submit-{problem.get('id')}",
            use_container_width=True,
        )
        if submit:
            _handle_case1_submission(problem, user, question_specs, missing_numbers)
        st.markdown("</div>", unsafe_allow_html=True)

    with support_col:
        support_state = _render_case1_support_panel(
            problem,
            question,
            question_index=selected_index,
            problem_context=problem_context,
            draft_key=draft_key,
            textarea_key=textarea_key,
            answer_context=answer_context,
        )

    step_state_key = _case1_step_state_key(draft_key)
    step_state = st.session_state.setdefault(step_state_key, {})
    step_state["question"] = True
    step_state["highlight"] = bool(support_state.get("highlight_done"))
    step_state["answer"] = bool((answer_context.get("text") or "").strip())
    step_state["analysis"] = bool(support_state.get("analysis_done"))
    step_state["model"] = bool(support_state.get("model_done"))
    step_state["memo"] = bool(support_state.get("memo_saved"))
    st.session_state[step_state_key] = step_state

    tab_state_key = support_state.get("tab_state_key")
    highlight_state_key = support_state.get("highlight_state_key")

    with stepper_placeholder.container():
        _render_case1_stepper(
            step_state,
            draft_key=draft_key,
            tab_state_key=tab_state_key,
            highlight_state_key=highlight_state_key,
        )

    st.markdown("<div class='case1-bottom-section'>", unsafe_allow_html=True)
    _render_case1_retrieval_flashcards(problem)
    st.markdown("</div>", unsafe_allow_html=True)


def _render_case3_workspace(
    problem: Mapping[str, Any],
    user: Mapping[str, Any],
    *,
    problem_context: Optional[str],
) -> None:
    _ensure_case1_styles()
    _ensure_case3_styles()

    question_entries: List[Dict[str, Any]] = []
    for idx, q in enumerate(problem.get("questions", []), start=1):
        raw_prompt = _normalize_text_block(q.get("prompt") or q.get("設問見出し") or "")
        preview_text = _format_preview_text(raw_prompt, 32) if raw_prompt else "概要未登録"
        question_entries.append(
            {
                "label": f"設問{idx}",
                "title": raw_prompt or f"設問{idx}",
                "preview": preview_text,
                "max_score": q.get("max_score"),
            }
        )

    if not question_entries:
        st.warning("設問が登録されていません。設定ページで問題データを更新してください。", icon="⚠️")
        return

    problem_id = problem.get("id")
    selected_key = _case1_selected_question_key(problem_id)
    if selected_key not in st.session_state:
        st.session_state[selected_key] = 0
    selected_index = st.session_state[selected_key]
    selected_index = max(0, min(selected_index, len(question_entries) - 1))
    st.session_state[selected_key] = selected_index

    header_cols = st.columns([0.6, 0.4])
    with header_cols[0]:
        title = problem.get("title") or problem.get("name") or "過去問演習"
        st.markdown(
            f"<div class='case3-header'><h1>{html.escape(str(title))}</h1></div>",
            unsafe_allow_html=True,
        )
    with header_cols[1]:
        limit_hint = None
        if problem.get("questions"):
            limit_hint = _normalize_text_block(
                problem.get("questions", [])[selected_index].get("character_limit")
            )
        limit_label = f"目安文字数: {limit_hint}字" if limit_hint else "80字目安"
        st.markdown(
            f"<div class='case3-limit-indicator'>{html.escape(limit_label)}</div>",
            unsafe_allow_html=True,
        )

    toolbar_cols = st.columns([0.5, 0.25, 0.25])
    with toolbar_cols[0]:
        _render_practice_timer(problem.get("id"), confirm_on_start=True)
    with toolbar_cols[1]:
        st.markdown("<div class='case1-toolbar__status'>保存: 自動保存中</div>", unsafe_allow_html=True)
    with toolbar_cols[2]:
        if st.button("設定", key=f"case3-settings-{problem.get('id')}"):
            _request_navigation("設定")

    nav_col, answer_col, support_col = st.columns([0.22, 0.48, 0.30], gap="large")

    with nav_col:
        st.markdown("<div class='case3-nav-pane'>", unsafe_allow_html=True)
        st.markdown("<h3>設問ショートカット</h3>", unsafe_allow_html=True)
        for idx, entry in enumerate(question_entries):
            question = problem.get("questions", [])[idx]
            max_score = entry.get("max_score")
            score_label = f"{max_score}点" if max_score not in (None, "") else "配点不明"
            try:
                draft_key = _draft_key(int(problem_id), int(question.get("id")))
            except (TypeError, ValueError, AttributeError):
                draft_key = _draft_key(int(problem_id or 0), int(-(idx + 1)))
            text_value = st.session_state.get("drafts", {}).get(draft_key, "")
            answered = bool(text_value.strip())
            active = idx == selected_index
            card_label = "\n".join(
                [
                    f"設問{idx + 1}｜{score_label}",
                    entry.get("preview") or "詳細未登録",
                    "✅ 回答済" if answered else "⏺ 未回答",
                ]
            )
            button_key = f"case3-nav::{problem_id}::{idx}"
            if st.button(
                card_label,
                key=button_key,
                use_container_width=True,
                type="primary" if active else "secondary",
                help=entry.get("title") or entry.get("preview") or "",
            ):
                st.session_state[selected_key] = idx
                st.rerun()
        st.markdown("</div>", unsafe_allow_html=True)

    current_index = st.session_state[selected_key]
    question = problem.get("questions", [])[current_index]

    with answer_col:
        _render_case3_answer_area(
            problem,
            question,
            question_index=current_index,
            problem_context=problem_context,
        )
        st.markdown("<div class='case3-submit-area'>", unsafe_allow_html=True)
        if missing_numbers:
            formatted_numbers = "、".join(f"設問{num}" for num in missing_numbers)
            st.warning(
                f"{formatted_numbers} のIDが未登録のため、採点結果を保存できません。設定ページでデータを更新してください。",
                icon="⚠️",
            )
        submit = st.button(
            "AI採点に送信",
            type="primary",
            key=f"case3-submit-{problem.get('id')}",
            use_container_width=True,
        )
        if submit:
            _handle_case1_submission(problem, user, question_specs, missing_numbers)
        st.markdown("</div>", unsafe_allow_html=True)

    with support_col:
        tab_key = f"case3-panel-tab::{problem_id}"
        default_tab = st.session_state.get(tab_key, "頻出フレーム")
        try:
            selected_tab = st.radio(
                "分析・補助パネル",
                ["頻出フレーム", "模範解答・採点基準", "MECE/因果図"],
                horizontal=True,
                label_visibility="collapsed",
                key=tab_key,
            )
        except TypeError:
            if tab_key not in st.session_state:
                st.session_state[tab_key] = default_tab
            selected_tab = st.radio(
                "分析・補助パネル",
                ["頻出フレーム", "模範解答・採点基準", "MECE/因果図"],
                key=tab_key,
            )

        if selected_tab == "頻出フレーム":
            _render_case3_frame_templates(problem, question, question_index=current_index)
        elif selected_tab == "模範解答・採点基準":
            _render_case3_guideline_panel(problem, question, question_index=current_index)
        else:
            _render_case3_mece_panel(problem, question, question_index=current_index)

    st.markdown("<div class='case1-bottom-section'>", unsafe_allow_html=True)
    _render_case1_retrieval_flashcards(problem)
    st.markdown("</div>", unsafe_allow_html=True)


def _render_case3_answer_area(
    problem: Mapping[str, Any],
    question: Mapping[str, Any],
    *,
    question_index: int,
    problem_context: Optional[str],
) -> None:
    st.markdown("<div class='case3-answer-pane'>", unsafe_allow_html=True)

    prompt_text = _normalize_text_block(
        question.get("prompt") or question.get("設問見出し") or question.get("title")
    )
    st.markdown(
        f"<div class='case3-question-heading'><span class='case3-question-number'>設問{question_index + 1}</span><span class='case3-question-title'>{html.escape(prompt_text or '設問')}</span></div>",
        unsafe_allow_html=True,
    )

    body_text = _normalize_text_block(
        _select_first(question, ["設問文", "問題文", "question_text", "body"])
    )
    if body_text:
        st.caption(body_text)

    if problem_context:
        with st.expander("与件文を参照", expanded=False):
            problem_identifier = problem.get("id") or problem.get("title") or "default"
            search_key = f"case3-search-{problem_identifier}::{question.get('id')}"
            search_query = st.text_input(
                "与件文内検索",
                key=search_key,
                placeholder="キーワードで絞り込み",
            )
            match_count, highlight_snapshot = _render_problem_context_block(
                problem_context,
                search_query,
                snapshot_key=str(problem_identifier),
                auto_palette=True,
                auto_save=True,
                compact_controls=True,
            )
            if highlight_snapshot:
                highlight_store = st.session_state.setdefault("context_highlights", {})
                highlight_store[str(problem_identifier)] = highlight_snapshot
            normalized_query = (search_query or "").strip()
            if normalized_query:
                if match_count:
                    st.caption(f"該当箇所: {match_count}件")
                else:
                    st.caption("該当箇所は見つかりませんでした。")
            else:
                st.caption("ハイライトは選択と同時に自動保存されます。")

    problem_id = problem.get("id")
    draft_key = _case3_resolve_draft_key(problem, question, question_index)

    saved_payload = _get_saved_answer_payload(draft_key)
    if hasattr(st.session_state, "drafts"):
        st.session_state.drafts.setdefault(draft_key, saved_payload.get("autosave", ""))
    else:
        st.session_state.drafts = {draft_key: saved_payload.get("autosave", "")}

    textarea_key = f"case3::{draft_key}"
    placeholder = "ここに解答を入力してください。QCD・4Mなどのフレームで整理しましょう。"
    limit_hint = question.get("character_limit")
    limit_value: Optional[int] = None
    if limit_hint not in (None, ""):
        try:
            limit_value = int(limit_hint)
        except (TypeError, ValueError):
            limit_value = None
        else:
            placeholder = (
                f"ここに解答を入力してください（目安: {limit_value}字）。"
                "QCD・4M視点で因果を明示しましょう。"
            )

    text = st.text_area(
        "回答入力",
        key=textarea_key,
        value=st.session_state.drafts.get(draft_key, ""),
        height=260,
        label_visibility="collapsed",
        placeholder=placeholder,
    )
    st.session_state.drafts[draft_key] = text
    _track_question_activity(draft_key, text)

    keyword_hits = _render_case3_progress_cluster(text, question, limit_value=limit_value)
    st.markdown("<div class='case3-progress-spacer'></div>", unsafe_allow_html=True)

    modal_button_key = f"case3-guideline-button::{problem_id}::{question_index}"
    tab_key = f"case3-panel-tab::{problem_id}"
    if st.button(
        "模範解答・採点ガイドを表示",
        key=modal_button_key,
        use_container_width=True,
    ):
        st.session_state[tab_key] = "模範解答・採点基準"
        st.rerun()

    st.markdown("</div>", unsafe_allow_html=True)

    keyword_store = st.session_state.setdefault("_case1_keyword_hits", {})
    keyword_store[draft_key] = keyword_hits


def _render_case3_progress_cluster(
    text: str,
    question: Mapping[str, Any],
    *,
    limit_value: Optional[int],
) -> Mapping[str, bool]:
    fullwidth_length = _compute_fullwidth_length(text)
    effective_limit = limit_value or 240
    used_ratio = min(fullwidth_length / effective_limit, 1.0) if effective_limit else 0.0
    remaining = max(effective_limit - fullwidth_length, 0)

    keywords = _resolve_question_keywords(question)
    keyword_hits: Mapping[str, bool] = {}
    coverage_ratio = 0.0
    matched = 0
    total_keywords = 0
    if keywords:
        cleaned_keywords = [kw for kw in keywords if kw]
        if cleaned_keywords:
            keyword_hits = scoring.keyword_match_score(text, cleaned_keywords)
            matched = sum(1 for value in keyword_hits.values() if value)
            total_keywords = len(keyword_hits)
            coverage_ratio = matched / total_keywords if total_keywords else 0.0

    noun_count, verb_count = _count_case3_pos(text)
    structure_target = 8
    structure_ratio = (
        min((noun_count + verb_count) / structure_target, 1.0)
        if structure_target
        else 0.0
    )

    st.markdown("<div class='case3-progress-cluster'>", unsafe_allow_html=True)
    if coverage_ratio >= 0.6:
        coverage_color = "#1971c2"
    elif coverage_ratio >= 0.3:
        coverage_color = "#f59f00"
    else:
        coverage_color = "#e03131"

    if verb_count and noun_count:
        structure_color = "#5f3dc4"
    elif verb_count >= 2:
        structure_color = "#f59f00"
    else:
        structure_color = "#e03131"

    char_color = "#2f9e44" if used_ratio < 0.9 else "#d9480f"

    segments = [
        {
            "label": f"残字 {remaining}字",
            "ratio": used_ratio,
            "color": char_color,
        },
        {
            "label": f"要点 {int(coverage_ratio * 100)}% ({matched}/{total_keywords or '-'})",
            "ratio": coverage_ratio,
            "color": coverage_color,
        },
        {
            "label": f"構造 名詞{noun_count}/述語{verb_count}",
            "ratio": structure_ratio,
            "color": structure_color,
        },
    ]

    bar_html = "<div class='case3-progress-bar'>"
    for segment in segments:
        width = max(segment["ratio"] * 100, 4)
        bar_html += (
            f"<div class='case3-progress-segment' style='width:{width}%;background:{segment['color']}'>"
            f"<span>{escape(segment['label'])}</span></div>"
        )
    bar_html += "</div>"
    st.markdown(bar_html, unsafe_allow_html=True)
    st.markdown("</div>", unsafe_allow_html=True)

    return keyword_hits


def _render_case3_frame_templates(
    problem: Mapping[str, Any],
    question: Mapping[str, Any],
    *,
    question_index: int,
) -> None:
    st.markdown("<h4>事例Ⅲ頻出フレーム</h4>", unsafe_allow_html=True)
    frames = _case3_frame_definitions()
    frame_names = [frame["label"] for frame in frames]
    frame_key = (
        f"case3-frame-select::{problem.get('id')}::{question.get('id')}::{question_index}"
    )
    selected_label = st.selectbox(
        "フレームを選択",
        frame_names,
        key=frame_key,
    )

    selected_frame = next((frame for frame in frames if frame["label"] == selected_label), frames[0])
    st.info(selected_frame["description"], icon="🧭")
    st.markdown("<div class='case3-template-preview'>", unsafe_allow_html=True)
    st.code(selected_frame["template"], language="markdown")
    st.markdown("</div>", unsafe_allow_html=True)

    if st.button(
        f"このフレーズを回答欄に挿入（{selected_frame['label']}）",
        key=(
            f"case3-insert-frame::{problem.get('id')}::{question.get('id')}::{question_index}"
        ),
        use_container_width=True,
    ):
        _insert_case3_template(
            problem,
            question,
            selected_frame["template"],
            question_index=question_index,
        )


def _render_case3_guideline_panel(
    problem: Mapping[str, Any],
    question: Mapping[str, Any],
    *,
    question_index: int,
) -> None:
    st.markdown("<h4>模範解答・採点基準</h4>", unsafe_allow_html=True)
    model_answer = _normalize_text_block(question.get("model_answer"))
    keywords = _resolve_question_keywords(question)
    draft_key = _case3_resolve_draft_key(problem, question, question_index)
    keyword_hits = st.session_state.get("_case1_keyword_hits", {}).get(draft_key, {})
    if keyword_hits:
        matched = sum(1 for value in keyword_hits.values() if value)
        total = len(keyword_hits)
        coverage_ratio = matched / total if total else 0.0
        st.progress(coverage_ratio, text=f"要点被覆率 {coverage_ratio * 100:.0f}%")
        missing = [kw for kw, hit in keyword_hits.items() if not hit]
        if missing:
            st.caption("不足キーワード: " + "、".join(missing))

    with st.expander("模範解答", expanded=True):
        if model_answer:
            st.markdown(model_answer)
        else:
            st.caption("模範解答が未登録です。設定ページで更新してください。")

    with st.expander("キーワード評価", expanded=False):
        if keywords:
            st.write("評価対象キーワード")
            st.markdown("・" + "\n・".join(keywords))
        else:
            st.caption("評価キーワードが未登録です。")

    with st.expander("構造評価", expanded=False):
        axis = _normalize_text_block(question.get("axis"))
        if axis:
            st.markdown(axis)
        else:
            st.caption("構造評価の観点が未登録です。")

    with st.expander("採点ガイドライン", expanded=False):
        guideline = _normalize_text_block(
            question.get("grading_guideline") or question.get("guideline")
        )
        if guideline:
            st.markdown(guideline)
        else:
            st.caption("採点ガイドラインが未登録です。")


def _render_case3_mece_panel(
    problem: Mapping[str, Any],
    question: Mapping[str, Any],
    *,
    question_index: int,
) -> None:
    st.markdown("<h4>MECE/因果図ツール</h4>", unsafe_allow_html=True)
    draft_text = _case3_current_text(problem, question, question_index=question_index)
    analysis = _render_mece_status_labels(draft_text)
    st.markdown("<div class='case3-mece-report'>", unsafe_allow_html=True)
    _render_mece_causal_scanner(draft_text, analysis=analysis)
    st.markdown("</div>", unsafe_allow_html=True)

    st.markdown("---")
    st.markdown("<h5>設備・人員・素材・情報の因果整理</h5>", unsafe_allow_html=True)
    categories = ["設備", "人員", "素材", "情報"]
    inputs: Dict[str, str] = {}
    for category in categories:
        inputs[category] = st.text_input(
            f"{category}の課題／強み",
            key=(
                f"case3-causal::{problem.get('id')}::{question.get('id')}::{question_index}::{category}"
            ),
            placeholder=f"{category}の現状や課題を入力",
        )
    desired_effect = st.text_input(
        "期待する効果",
        key=(
            f"case3-causal-effect::{problem.get('id')}::{question.get('id')}::{question_index}"
        ),
        placeholder="例: 生産リードタイム短縮、歩留まり向上",
    )

    if any(inputs.values()) or desired_effect:
        graph_lines = ["```mermaid", "graph TD"]
        effect_node = "Effect"
        for category, value in inputs.items():
            node_id = hashlib.md5(f"{category}:{value}".encode("utf-8")).hexdigest()[:6]
            label = escape(value or category)
            graph_lines.append(f"    {node_id}[{category}: {label}]")
            graph_lines.append(f"    {node_id} --> {effect_node}")
        if desired_effect:
            graph_lines.append(f"    {effect_node}[成果: {escape(desired_effect)}]")
        else:
            graph_lines.append(f"    {effect_node}[成果: 改善効果]")
        graph_lines.append("```")
        st.markdown("\n".join(graph_lines))

    if st.button(
        "因果フレーズを回答欄に挿入",
        key=(
            f"case3-insert-causal::{problem.get('id')}::{question.get('id')}::{question_index}"
        ),
        use_container_width=True,
    ):
        fragments = [
            f"【{category}】{inputs[category]}" for category in categories if inputs.get(category)
        ]
        if desired_effect:
            fragments.append(f"⇒ {desired_effect}")
        template = (
            " / ".join(fragments) if fragments else "設備・人員・素材・情報を整理しよう"
        )
        _insert_case3_template(
            problem,
            question,
            template,
            question_index=question_index,
        )


def _case3_resolve_draft_key(
    problem: Mapping[str, Any],
    question: Mapping[str, Any],
    question_index: int,
) -> str:
    problem_id = problem.get("id")
    try:
        return _draft_key(int(problem_id), int(question.get("id")))
    except (TypeError, ValueError, AttributeError):
        return _draft_key(int(problem_id or 0), int(-(question_index + 1)))


def _case3_current_text(
    problem: Mapping[str, Any],
    question: Mapping[str, Any],
    *,
    question_index: int,
) -> str:
    draft_key = _case3_resolve_draft_key(problem, question, question_index)
    return st.session_state.get("drafts", {}).get(draft_key, "")


def _case3_frame_definitions() -> List[Dict[str, str]]:
    return [
        {
            "label": "QCD",
            "description": "品質(Q)、コスト(C)、納期(D)の観点で課題と改善策を整理します。",
            "template": "Q: 品質課題は〜。/ C: コスト面では〜。/ D: 納期は〜。→ 生産性向上につなげる。",
        },
        {
            "label": "4M",
            "description": "Man・Machine・Material・Methodの視点で原因を網羅します。",
            "template": "Man: 人員の課題は〜。/ Machine: 設備は〜。/ Material: 材料は〜。/ Method: 手順は〜。",
        },
        {
            "label": "4M/5M",
            "description": "Measurementを含めて管理面の抜け漏れを点検します。",
            "template": "Man〜、Machine〜、Material〜、Method〜、Measurement〜を整備し再発防止。",
        },
        {
            "label": "ECRS",
            "description": "Eliminate・Combine・Rearrange・Simplifyの順で業務改善を検討します。",
            "template": "E: 無駄工程を削除。/ C: 工程を統合。/ R: レイアウトを再配置。/ S: 手順を簡素化。",
        },
        {
            "label": "5S",
            "description": "整理・整頓・清掃・清潔・躾で現場力を高めます。",
            "template": "整理: 不要物除去。整頓: 置き場明確化。清掃: 点検を兼ねる。清潔: 標準維持。躾: ルール徹底。",
        },
        {
            "label": "IE",
            "description": "Industrial Engineeringで工程分析・ラインバランスを明確化します。",
            "template": "工程分析でムダを特定→ラインバランス調整→標準時間設定→見える化・改善定着。",
        },
    ]


def _insert_case3_template(
    problem: Mapping[str, Any],
    question: Mapping[str, Any],
    template: str,
    *,
    question_index: int,
) -> None:
    draft_key = _case3_resolve_draft_key(problem, question, question_index)
    textarea_key = f"case3::{draft_key}"
    current_text = st.session_state.get("drafts", {}).get(draft_key, "")
    appended = (current_text + "\n" + template).strip()
    st.session_state.setdefault("drafts", {})[draft_key] = appended
    _queue_textarea_update(textarea_key, appended)
    st.rerun()


def _count_case3_pos(text: str) -> Tuple[int, int]:
    kanji_blocks = re.findall(r"[一-龠々〆ヵヶ]+", text)
    verb_patterns = re.findall(
        r"[ぁ-んァ-ヶー]{1,8}(する|した|して|させる|できる|となる|向上|改善|短縮|増加|削減)",
        text,
    )
    noun_count = len(kanji_blocks)
    verb_count = len(verb_patterns)
    return noun_count, verb_count


def _ensure_case3_styles() -> None:
    if st.session_state.get("_case3_style_loaded"):
        return
    st.markdown(
        """
        <style>
        .case3-header h1 {
            margin-bottom: 0.3rem;
        }
        .case3-limit-indicator {
            text-align: right;
            font-weight: 600;
            padding: 0.8rem 1rem;
            background: var(--secondary-background-color,#f1f3f5);
            border-radius: 0.75rem;
        }
        .case3-nav-pane h3 {
            margin-bottom: 0.6rem;
        }
        .case3-answer-pane {
            position: relative;
            padding: 0.5rem 0;
        }
        .case3-question-heading {
            display: flex;
            gap: 0.75rem;
            align-items: baseline;
            margin-bottom: 0.4rem;
        }
        .case3-question-number {
            font-size: 1.2rem;
            font-weight: 700;
            color: #1864ab;
        }
        .case3-question-title {
            font-size: 1.05rem;
            font-weight: 600;
        }
        .case3-progress-cluster {
            margin-top: 0.4rem;
        }
        .case3-progress-bar {
            display: flex;
            gap: 0.4rem;
            align-items: stretch;
        }
        .case3-progress-segment {
            flex: 1 1 auto;
            min-width: 20%;
            border-radius: 0.6rem;
            color: white;
            padding: 0.35rem 0.45rem;
            font-size: 0.75rem;
            display: flex;
            align-items: center;
            justify-content: center;
            text-align: center;
            line-height: 1.2;
        }
        .case3-progress-segment span {
            font-weight: 600;
        }
        .case3-progress-spacer {
            height: 0.4rem;
        }
        .case3-template-preview {
            margin-bottom: 0.5rem;
        }
        .case3-nav-pane button[kind="secondary"],
        .case3-nav-pane button[kind="primary"] {
            text-align: left;
            white-space: pre-wrap;
            height: auto;
            padding: 0.75rem 0.85rem;
            border-radius: 0.9rem;
        }
        .case3-submit-area {
            margin-top: 1.2rem;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )
    st.session_state["_case3_style_loaded"] = True


def practice_page(user: Dict) -> None:
    st.title("過去問演習")
    st.caption("年度と事例を選択して記述式演習を行います。与件ハイライトと詳細解説で復習効果を高めましょう。")

    loading_placeholder = st.empty()
    progress_bar = None
    show_loading = not st.session_state.get("_practice_loading_ready", False)
    if show_loading:
        with loading_placeholder.container():
            st.markdown("#### 画面を準備中…")
            st.caption("ネットワーク状況により数秒かかる場合があります。読み込み完了までお待ちください。")
            progress_bar = st.progress(5)

    def _complete_loading() -> None:
        if progress_bar:
            progress_bar.progress(100)
        loading_placeholder.empty()
        st.session_state["_practice_loading_ready"] = True

    _inject_practice_navigation_styles()

    past_data_df = st.session_state.get("past_data")
    signature = _problem_data_signature()
    index = _load_problem_index(signature)
    if progress_bar:
        progress_bar.progress(30)

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
        _complete_loading()
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
        _complete_loading()
        return

    try:
        attempts = database.list_attempts(user_id=user["id"])
    except Exception:
        logger.exception("Failed to load attempts for practice view")
        attempts = []
    if progress_bar:
        progress_bar.progress(45)

    if not has_database_data:
        st.warning("問題データが登録されていません。seed_problems.jsonを確認してください。")
        _complete_loading()
        return

    case_map: Dict[str, Dict[str, int]] = defaultdict(dict)
    for entry in index:
        case_map[entry["case_label"]][entry["year"]] = entry["id"]

    focus_state = st.session_state.pop("practice_focus", None)
    if isinstance(focus_state, dict):
        focus_case = focus_state.get("case_label")
        focus_year = focus_state.get("year")
        focus_question_id = focus_state.get("question_id")
        if focus_case in case_map and focus_year is not None and focus_question_id:
            year_map = case_map[focus_case]
            normalized_year_key: Optional[str | int] = None
            for year_key in year_map.keys():
                if year_key == focus_year or str(year_key) == str(focus_year):
                    normalized_year_key = year_key
                    break
            if normalized_year_key is not None:
                st.session_state["practice_tree_case"] = focus_case
                year_key = f"practice_tree_year_{focus_case}"
                st.session_state[year_key] = normalized_year_key
                problem_id = year_map[normalized_year_key]
                question_key = f"practice_tree_question_{problem_id}"
                st.session_state[question_key] = focus_question_id

    fetch_practice_stats = getattr(database, "fetch_question_practice_stats", None)
    if fetch_practice_stats is None:
        logger.warning("database module missing fetch_question_practice_stats; defaulting to empty stats")
        question_stats = {}
    else:
        try:
            question_stats = fetch_practice_stats(user["id"])
        except Exception:
            logger.exception("Failed to fetch question practice stats for user %s", user.get("id"))
            question_stats = {}
    if progress_bar:
        progress_bar.progress(65)

    try:
        master_stats = database.fetch_question_master_stats()
    except Exception:
        logger.exception("Failed to load global question metrics")
        master_stats = {}
    if progress_bar:
        progress_bar.progress(80)

    case_options = sorted(
        case_map.keys(),
        key=lambda label: (
            CASE_ORDER.index(label) if label in CASE_ORDER else len(CASE_ORDER),
            label,
        ),
    )

    if not case_options:
        st.warning("事例が登録されていません。データを追加してください。")
        _complete_loading()
        return

    st.markdown(
        dedent(
            """
            <style>
            .practice-tree .tree-level {
                margin-bottom: 0.75rem;
            }
            .practice-tree .tree-level .stSelectbox > label {
                font-weight: 600;
                font-size: 0.95rem;
            }
            .practice-tree .tree-level .stSelectbox [data-baseweb="select"] {
                border-radius: 0.75rem;
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
    question_lookup: Dict[int, Dict[str, Any]] = {}
    question_options: List[int] = []
    problem_id: Optional[int] = None

    tree_col, insight_col = st.columns([0.42, 0.58], gap="large")

    with tree_col:
        st.markdown('<div class="practice-tree">', unsafe_allow_html=True)
        st.markdown("#### 出題ナビゲーション")
        st.caption("ドロップダウンから年度と設問を選択すると、右側に要点が即時表示されます。")

        case_key = "practice_tree_case"
        if case_key not in st.session_state or st.session_state[case_key] not in case_options:
            st.session_state[case_key] = case_options[0]
        st.markdown('<div class="tree-level tree-level-case">', unsafe_allow_html=True)
        selected_case = st.selectbox(
            "事例I〜IV",
            case_options,
            key=case_key,
        )
        st.markdown("</div>", unsafe_allow_html=True)

        year_options = sorted(
            case_map[selected_case].keys(),
            key=_year_sort_key,
            reverse=True,
        )
        year_key = f"practice_tree_year_{selected_case}"
        problem_id: Optional[int] = None
        question_lookup: Dict[int, Dict[str, Any]] = {}
        question_options: List[int] = []

        if not year_options:
            st.warning("選択した事例の年度が登録されていません。", icon="⚠️")
        else:
            if year_key not in st.session_state or st.session_state[year_key] not in year_options:
                st.session_state[year_key] = year_options[0]
            st.markdown('<div class="tree-level tree-level-year">', unsafe_allow_html=True)
            selected_year = st.selectbox(
                "↳ 年度 (R6/R5/R4…)",
                year_options,
                key=year_key,
                format_func=_format_reiwa_label,
                label_visibility="collapsed",
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
            status_map = {
                qid: _classify_practice_status(question_stats.get(qid))
                for qid in question_options
            }
            difficulty_map: Dict[int, str] = {}
            for qid in question_options:
                question_meta = question_lookup.get(qid) or {}
                meta_label = question_meta.get("difficulty")
                if not meta_label and problem:
                    meta_label = problem.get("difficulty")
                master_entry = master_stats.get(qid) if master_stats else None
                avg_ratio = master_entry.get("avg_ratio") if master_entry else None
                difficulty_map[qid] = _classify_difficulty_label(meta_label, avg_ratio)
            search_key = f"practice_tree_search::{selected_case}::{selected_year}"
            sort_key = f"practice_tree_sort::{selected_case}::{selected_year}"
            status_filter_key = f"practice_tree_status::{selected_case}::{selected_year}"
            st.markdown('<div class="tree-level tree-level-filter">', unsafe_allow_html=True)
            filter_cols = st.columns([0.6, 0.4], gap="small")
            with filter_cols[0]:
                search_query = st.text_input(
                    "設問検索",
                    key=search_key,
                    placeholder="キーワード・年号・配点で絞り込み",
                )
            with filter_cols[1]:
                sort_option = st.selectbox(
                    "並べ替え",
                    ["設問順", "重要度（配点高→低）", "出題頻度（多→少）"],
                    key=sort_key,
                )
            st.markdown("</div>", unsafe_allow_html=True)

            status_choices = ["未実施", "要復習", "安定"]
            default_statuses = st.session_state.get(status_filter_key, status_choices)
            st.markdown('<div class="tree-level tree-level-filter">', unsafe_allow_html=True)
            _render_help_label(
                "ステータスフィルタ",
                "未実施／要復習／安定の進捗ステータスで設問を絞り込みます。自分の解答履歴から自動判定されます。",
            )
            selected_statuses = st.multiselect(
                "ステータスフィルタ",
                status_choices,
                default=default_statuses,
                key=status_filter_key,
                label_visibility="collapsed",
            )
            st.markdown("</div>", unsafe_allow_html=True)

            score_values: List[int] = []
            for qid in question_options:
                question = question_lookup.get(qid) or {}
                try:
                    numeric = int(float(question.get("max_score")))
                except (TypeError, ValueError):
                    continue
                score_values.append(numeric)

            score_range: Optional[Tuple[int, int]] = None
            selected_topics: List[str] = []
            selected_difficulties: List[str] = []
            topic_counter: Counter[str] = Counter()
            for qid in question_options:
                question = question_lookup.get(qid) or {}
                for keyword in _resolve_question_keywords(question):
                    topic_counter[keyword] += 1
                for tag in _resolve_question_skill_tags(question):
                    topic_counter[tag] += 1

            topic_options = [kw for kw, _count in topic_counter.most_common(30)]
            st.markdown('<div class="tree-level tree-level-filter">', unsafe_allow_html=True)
            filter_cols = st.columns([0.34, 0.33, 0.33], gap="small")
            with filter_cols[0]:
                if score_values:
                    min_score = min(score_values)
                    max_score = max(score_values)
                    score_filter_key = f"practice_tree_score::{selected_case}::{selected_year}"
                    if min_score == max_score:
                        score_range = (min_score, max_score)
                        st.caption(f"配点はすべて{min_score}点です。")
                    else:
                        score_range = st.slider(
                            "配点レンジ",
                            min_value=min_score,
                            max_value=max_score,
                            value=(min_score, max_score),
                            step=1,
                            key=score_filter_key,
                            help="狙いたい配点帯で設問を絞り込みます。",
                        )
            with filter_cols[1]:
                if topic_options:
                    topic_filter_key = f"practice_tree_topics::{selected_case}::{selected_year}"
                    selected_topics = st.multiselect(
                        "論点タグ",
                        topic_options,
                        key=topic_filter_key,
                        help="SWOT分析やマーケティング戦略など、押さえたい論点で抽出します。",
                    )
            with filter_cols[2]:
                difficulty_options = sorted({label for label in difficulty_map.values() if label})
                if not difficulty_options:
                    difficulty_options = ["未分類"]
                difficulty_filter_key = f"practice_tree_difficulty::{selected_case}::{selected_year}"
                selected_difficulties = st.multiselect(
                    "難易度",
                    difficulty_options,
                    default=difficulty_options,
                    key=difficulty_filter_key,
                    help="平均正答率や付与メタデータから推定した難易度で絞り込みます。",
                )
            st.markdown("</div>", unsafe_allow_html=True)

            normalized_query = (search_query or "").strip().lower()
            filtered_question_ids: List[int] = []
            for qid in question_options:
                question = question_lookup.get(qid)
                if not question:
                    continue
                if score_range:
                    try:
                        numeric_score = float(question.get("max_score"))
                    except (TypeError, ValueError):
                        numeric_score = None
                    if numeric_score is None:
                        numeric_score = 0.0
                    if numeric_score < score_range[0] or numeric_score > score_range[1]:
                        continue
                if selected_topics:
                    question_topics = set(_resolve_question_keywords(question)) | set(
                        _resolve_question_skill_tags(question)
                    )
                    if not question_topics or not set(selected_topics).issubset(question_topics):
                        continue
                difficulty_label = difficulty_map.get(qid, "未分類")
                if selected_difficulties and difficulty_label not in selected_difficulties:
                    continue
                status_label = status_map.get(qid, "未実施")
                if selected_statuses and status_label not in selected_statuses:
                    continue
                if normalized_query:
                    haystacks: List[str] = []
                    prompt = _normalize_text_block(
                        _select_first(
                            question,
                            ["prompt", "設問文", "問題文", "question_text", "body"],
                        )
                    ) or ""
                    haystacks.append(prompt)
                    haystacks.append(status_label)
                    haystacks.append(str(question.get("order") or ""))
                    haystacks.append(str(question.get("max_score") or ""))
                    haystacks.append(str(selected_case))
                    haystacks.append(str(selected_year))
                    keywords_text = "、".join(_resolve_question_keywords(question))
                    haystacks.append(keywords_text)
                    if not any(normalized_query in str(value).lower() for value in haystacks if value):
                        continue
                filtered_question_ids.append(qid)

            if sort_option == "重要度（配点高→低）":
                filtered_question_ids.sort(
                    key=lambda qid: (
                        float(question_lookup.get(qid, {}).get("max_score") or 0.0),
                        int(question_lookup.get(qid, {}).get("order") or 0),
                    ),
                    reverse=True,
                )
            elif sort_option == "出題頻度（多→少）":
                filtered_question_ids.sort(
                    key=lambda qid: (
                        int(question_stats.get(qid, {}).get("attempt_count", 0)),
                        int(question_lookup.get(qid, {}).get("order") or 0),
                    ),
                    reverse=True,
                )
            else:
                filtered_question_ids.sort(
                    key=lambda qid: (
                        int(question_lookup.get(qid, {}).get("order") or 0),
                        qid,
                    )
                )

            if not filtered_question_ids:
                st.info("条件に一致する設問がありません。フィルタを調整してください。", icon="🔍")
            else:
                if (
                    question_key not in st.session_state
                    or st.session_state[question_key] not in filtered_question_ids
                ):
                    st.session_state[question_key] = filtered_question_ids[0]

                def _format_question_option(question_id: int) -> str:
                    question = question_lookup.get(question_id)
                    if not question:
                        return "設問"
                    prompt = _normalize_text_block(
                        _select_first(
                            question,
                            ["prompt", "設問文", "問題文", "question_text", "body"],
                        )
                    ) or ""
                    preview = prompt.splitlines()[0] if prompt else ""
                    if len(preview) > 24:
                        preview = preview[:24] + "…"
                    label_year = _format_reiwa_label(selected_year) if selected_year else ""
                    parts = [
                        part
                        for part in [label_year, selected_case, f"設問{question['order']}"]
                        if part
                    ]
                    meta_parts: List[str] = []
                    status_label = status_map.get(question_id)
                    if status_label:
                        meta_parts.append(status_label)
                    difficulty_label = difficulty_map.get(question_id)
                    if difficulty_label and difficulty_label != "未分類":
                        meta_parts.append(difficulty_label)
                    attempts = question_stats.get(question_id, {}).get("attempt_count", 0)
                    if attempts:
                        meta_parts.append(f"{attempts}回")
                    master_entry = master_stats.get(question_id) if master_stats else None
                    if master_entry and master_entry.get("attempt_count"):
                        avg_ratio = master_entry.get("avg_ratio")
                        if isinstance(avg_ratio, (int, float)):
                            meta_parts.append(f"平均{avg_ratio * 100:.0f}%")
                    meta = f" [{' / '.join(meta_parts)}]" if meta_parts else ""
                    if preview:
                        return f"{' '.join(parts)}：{preview}{meta}"
                    return f"{' '.join(parts)}{meta}"

                st.markdown('<div class="tree-level tree-level-question">', unsafe_allow_html=True)
                selected_question_id = st.selectbox(
                    "↳ 設問1〜",
                    filtered_question_ids,
                    key=question_key,
                    format_func=_format_question_option,
                    label_visibility="collapsed",
                )
                st.markdown("</div>", unsafe_allow_html=True)
                selected_question = question_lookup.get(selected_question_id)
                previous_selection = st.session_state.get("_practice_last_selection")
                current_selection = (selected_case, selected_year, selected_question_id)
                if previous_selection != current_selection:
                    st.session_state["_practice_last_selection"] = current_selection
                    st.session_state["_practice_scroll_requested"] = True
                    st.session_state["_pending_focus_question"] = selected_question_id
        elif selected_year:
            st.info("この事例の設問データが見つかりません。設定ページから追加してください。", icon="ℹ️")

        st.markdown("</div>", unsafe_allow_html=True)

    with insight_col:
        st.markdown("#### 設問ビュー")
        if selected_case and selected_year:
            st.markdown(f"**{selected_case} / {_format_reiwa_label(selected_year)}**")
        if problem:
            st.caption(problem["title"])
            meta_chunks: List[str] = []
            if problem.get("difficulty"):
                meta_chunks.append(f"難易度: {problem['difficulty']}")
            if problem.get("themes"):
                meta_chunks.append("テーマ: " + "、".join(str(item) for item in problem.get("themes", [])))
            if problem.get("tendencies"):
                meta_chunks.append("出題傾向: " + "、".join(str(item) for item in problem.get("tendencies", [])))
            if problem.get("tags"):
                meta_chunks.append("タグ: " + "、".join(str(item) for item in problem.get("tags", [])))
            if meta_chunks:
                st.caption(" / ".join(meta_chunks))

        short_year = _format_reiwa_label(selected_year or "")
        notice = EXAM_YEAR_NOTICE.get(short_year)
        if notice:
            notes_text = "\n".join(f"・{item}" for item in notice["notes"])
            st.info(
                f"試験時間: {notice['time']}\n{notes_text}",
                icon="📝",
            )

        if selected_question:
            question_id = selected_question.get("id")
            user_stat = question_stats.get(question_id or 0, {}) if question_stats else {}
            master_entry = master_stats.get(question_id) if master_stats else None
            difficulty_label = _classify_difficulty_label(
                selected_question.get("difficulty") or problem.get("difficulty"),
                master_entry.get("avg_ratio") if master_entry else None,
            )
            stats_lines: List[str] = []
            if difficulty_label:
                stats_lines.append(f"**想定難易度:** {difficulty_label}")
            if master_entry and master_entry.get("avg_ratio") is not None:
                avg_ratio = float(master_entry.get("avg_ratio"))
                stats_lines.append(
                    f"**全受験者平均:** {avg_ratio * 100:.0f}%（サンプル{int(master_entry.get('attempt_count') or 0)}件）"
                )
            if user_stat and user_stat.get("avg_ratio") is not None:
                learner_ratio = float(user_stat.get("avg_ratio"))
                stats_lines.append(
                    f"**あなたの平均:** {learner_ratio * 100:.0f}%（{int(user_stat.get('attempt_count') or 0)}回）"
                )
            if stats_lines:
                st.markdown("<div class='question-stats-block'>" + "<br/>".join(stats_lines) + "</div>", unsafe_allow_html=True)
            st.markdown(
                f"**設問{selected_question['order']}：{selected_question['prompt']}**"
            )
            insight_tab, answer_tab = st.tabs(["インサイト", "模範解答"])

            with insight_tab:
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
                _render_help_label(
                    "定番解法プロンプト",
                    "高得点答案で多用される表現や構成のヒントを簡潔にまとめています。答案骨子づくりの出発点に活用してください。",
                    level=5,
                    variant="subheading",
                )
                st.write(_suggest_solution_prompt(selected_question))

            with answer_tab:
                if selected_question.get("keywords"):
                    st.markdown("##### キーワード評価")
                    st.write("、".join(selected_question["keywords"]))
                model_answer_text = _normalize_text_block(
                    selected_question.get("model_answer")
                )
                if model_answer_text:
                    model_answer_length_value = _compute_fullwidth_length(
                        model_answer_text.replace("\n", "")
                    )
                    model_answer_length = _format_fullwidth_length(
                        model_answer_length_value
                    )
                    st.markdown("##### 模範解答")
                    st.caption(f"想定文字数: {model_answer_length}字")
                    st.write(model_answer_text)
                else:
                    st.caption("模範解答が登録されていません。")

                explanation_text = _normalize_text_block(
                    selected_question.get("explanation")
                    or selected_question.get("解説")
                )
                if explanation_text:
                    st.markdown("##### 解説")
                    st.write(explanation_text)
        else:
            st.caption("設問を選択すると狙いや解法テンプレートを表示します。")

    if not problem:
        st.error("問題を取得できませんでした。")
        _complete_loading()
        return

    st.markdown('<div id="practice-top"></div>', unsafe_allow_html=True)

    if selected_year and selected_case:
        st.subheader(f"{selected_year} {selected_case}『{problem['title']}』")
    else:
        st.subheader(problem["title"])
    st.write(problem["overview"])

    problem_context = _collect_problem_context_text(problem)
    problem_tables = _normalize_problem_tables(problem.get("tables_raw"))
    if problem.get("case_label") == "事例I":
        _render_case1_workspace(problem, user, problem_context=problem_context)
        _complete_loading()
        return

    layout_container = st.container()
    tables_rendered_in_context = False
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

            match_count, highlight_snapshot = _render_problem_context_block(
                problem_context,
                search_query,
                snapshot_key=str(problem_identifier),
            )
            if highlight_snapshot:
                highlight_store = st.session_state.setdefault("context_highlights", {})
                highlight_store[str(problem_identifier)] = highlight_snapshot
                st.success("ハイライトを保存しました。", icon="💾")

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
            if problem_tables:
                _render_problem_tables(problem_tables)
                tables_rendered_in_context = True
    else:
        main_col = layout_container

    answers: List[RecordedAnswer] = []
    question_specs: List[QuestionSpec] = []
    missing_question_numbers: List[int] = []
    submitted = False

    with main_col:
        if problem_tables and not tables_rendered_in_context:
            _render_problem_tables(problem_tables)
        st.markdown('<div class="practice-main-column">', unsafe_allow_html=True)
        current_problem_id = problem.get("id") if problem else None
        _render_practice_timer(current_problem_id)
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
            _render_practice_sidebar_shortcuts(question_entries)
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
                        <a href=\"#context-panel\" class=\"practice-return-button practice-return-context-button\" aria-label=\"与件文に戻る\">
                            <span class=\"practice-return-button-icon\" aria-hidden=\"true\">
                                <svg viewBox=\"0 0 24 24\" focusable=\"false\" aria-hidden=\"true\">
                                    <path d=\"M5.5 4A2.5 2.5 0 0 1 8 1.5h6a1 1 0 0 1 1 1V19l-2.7-1.35a3.5 3.5 0 0 0-3.12 0L6.5 19H6a2 2 0 0 1-2-2V5.5A1.5 1.5 0 0 1 5.5 4z\" fill=\"currentColor\" />
                                    <path d=\"M19 1.5a1 1 0 0 1 1 1V19a2 2 0 0 1-2 2h-.5l-3.38-1.69a1.5 1.5 0 0 1-.82-1.34V2.5a1 1 0 0 1 1-1H19z\" fill=\"currentColor\" />
                                </svg>
                            </span>
                            <span class=\"practice-return-button-text\">与件文に戻る</span>
                        </a>
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
                    "評価したい力": (
                        "・".join(
                            card["label"]
                            for card in _normalize_intent_card_list(q.get("intent_cards"))
                        )
                        or "-"
                    ),
                }
                for idx, q in enumerate(problem["questions"])
            ]
        )
        st.data_editor(
            question_overview,
            hide_index=True,
            width="stretch",
            disabled=True,
            column_config={
                "キーワード": st.column_config.TextColumn(help="採点で評価される重要ポイント"),
                "評価したい力": st.column_config.TextColumn(help="設問趣旨から読み取れる評価観点"),
            },
        )
        st.caption("採点の観点を事前に確認してから回答に取り組みましょう。")

        _render_retrieval_flashcards(problem)

        if not st.session_state.practice_started:
            st.session_state.practice_started = datetime.now(timezone.utc)

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
            if question.get("id") is None:
                missing_question_numbers.append(idx)
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

        if missing_question_numbers:
            formatted_numbers = "、".join(f"設問{num}" for num in missing_question_numbers)
            st.warning(
                f"{formatted_numbers} のIDが未登録のため、採点結果を保存できません。設定ページからデータを更新してから再度お試しください。",
                icon="⚠️",
            )

        submitted = st.button("AI採点に送信", type="primary")

        st.markdown('</div>', unsafe_allow_html=True)

    if submitted:
        if missing_question_numbers:
            formatted_numbers = "、".join(f"設問{num}" for num in missing_question_numbers)
            problem_year = _normalize_text_block(problem.get("year")) or ""
            problem_case = _normalize_text_block(
                problem.get("case_label") or problem.get("case")
            )
            logger.error(
                "Aborting practice submission for problem %s (year=%s, case=%s) due to missing question IDs: %s",
                problem.get("id"),
                problem_year,
                problem_case,
                formatted_numbers,
            )
            st.error(
                "設問IDが登録されていないため採点結果を保存できません。設定ページでデータを再登録し、再度お試しください。",
                icon="⚠️",
            )
            _complete_loading()
            return

        submitted_at = datetime.now(timezone.utc)
        activity_summary = _summarise_question_activity(problem, submitted_at)
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
                    activity=activity_summary.get(question["id"]),
                )
            )

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
        st.session_state.question_activity = {}

        st.success("採点が完了しました。結果を確認してください。")
        render_attempt_results(attempt_id)

    _complete_loading()


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
            _render_help_label(
                "定番解法プロンプト",
                "過去の良回答で頻出したフレーズや切り口を抽出したテンプレートです。骨子作成や表現確認に役立ててください。",
                level=5,
                variant="subheading",
            )
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
            width="stretch",
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
    placeholder_uploaded = "ここに解答を入力してください。段落ごとに改行すると自己レビューしやすくなります。"
    if max_chars:
        placeholder_uploaded = (
            f"ここに解答を入力してください（目安: {max_chars}字）。"
            " 段落ごとに改行し、重要語は箇条書きにして整理してみましょう。"
        )
    st.markdown("<div class='answer-editor' role='group' aria-label='解答入力欄'>", unsafe_allow_html=True)
    user_answer = st.text_area(
        "回答を入力",
        key=answer_key,
        height=200,
        placeholder=placeholder_uploaded,
    )
    _render_character_counter(user_answer, max_chars)
    st.markdown("</div>", unsafe_allow_html=True)

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
        if video_col and pd.notna(selected_question.get(video_col)):
            video_url = str(selected_question.get(video_col))
        _render_model_answer_section(
            model_answer=selected_question.get("模範解答"),
            explanation=selected_question.get("解説"),
            video_url=video_url,
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


_WEAKNESS_CASE_PATTERNS: Dict[str, List[Dict[str, Any]]] = {
    "事例I": [
        {"tag": "人材育成", "patterns": ["育成", "教育", "研修", "技能伝承"]},
        {"tag": "権限設計", "patterns": ["権限", "委譲", "組織", "情報共有"]},
    ],
    "事例II": [
        {"tag": "ターゲティング", "patterns": ["ターゲ", "顧客", "客層", "セグメント"]},
        {"tag": "チャネル", "patterns": ["チャネル", "販路", "SNS", "オンライン", "店舗"]},
    ],
    "事例III": [
        {"tag": "QCD", "patterns": ["QCD", "品質", "コスト", "納期"]},
        {"tag": "段取り短縮", "patterns": ["段取", "段取り", "リードタイム", "準備", "外段取り"]},
    ],
    "事例IV": [
        {"tag": "CVP", "patterns": ["CVP", "損益分岐", "限界利益"]},
        {"tag": "NPV", "patterns": ["NPV", "現在価値", "投資", "キャッシュフロー"]},
    ],
}

_WEAKNESS_DRILL_MESSAGES: Dict[str, str] = {
    "人材育成": "人材マネジメント（採用→育成→評価）を整理するドリルで表現を磨きましょう。",
    "権限設計": "組織体制と権限委譲のケース演習で意思決定の流れを補強しましょう。",
    "ターゲティング": "ターゲットペルソナ設計のドリルで顧客像を描き直してください。",
    "チャネル": "チャネル戦略ドリルでオンライン／オフライン施策を整理しましょう。",
    "QCD": "QCDバランスを問う演習で品質・コスト・納期の優先度を再確認しましょう。",
    "段取り短縮": "段取り替えの定石を扱うドリルで工程設計を再トレースしましょう。",
    "CVP": "損益分岐分析の演習で数式と因果の結び付けを押さえ直してください。",
    "NPV": "投資評価（NPV）のドリルでキャッシュフローの算出手順を復習しましょう。",
    "因果構成": "接続詞挿入トレーニングで結論→理由の骨格を瞬時に描けるようにしましょう。",
}


def _render_time_allocation_heatmap(
    attempt: Mapping[str, Any], activities: List[Dict[str, Any]]
) -> None:
    if not activities:
        return

    start_dt = _parse_iso_datetime(attempt.get("started_at") if attempt else None)
    submitted_dt = _parse_iso_datetime(attempt.get("submitted_at") if attempt else None)

    rows: List[Dict[str, Any]] = []
    for entry in activities:
        question_order = entry.get("question_order")
        label = f"設問{question_order}" if question_order is not None else f"Q{entry.get('question_id')}"
        opened_dt = _parse_iso_datetime(entry.get("opened_at"))
        first_input_dt = _parse_iso_datetime(entry.get("first_input_at"))
        last_updated_dt = _parse_iso_datetime(entry.get("last_updated_at"))
        base_dt = first_input_dt or opened_dt
        start_offset = None
        if start_dt and base_dt:
            start_offset = (base_dt - start_dt).total_seconds() / 60
        duration_seconds = entry.get("total_duration_seconds")
        elapsed_minutes = None
        if isinstance(duration_seconds, (int, float)):
            elapsed_minutes = float(duration_seconds) / 60
        revision_count = int(entry.get("revision_count") or 0)
        rows.append(
            {
                "設問": label,
                "着手(分)": start_offset,
                "経過(分)": elapsed_minutes,
                "見直し回数": revision_count,
                "着手時刻": base_dt.strftime("%H:%M:%S") if base_dt else "-",
                "最終更新": (last_updated_dt or base_dt or submitted_dt).strftime("%H:%M:%S")
                if (last_updated_dt or base_dt or submitted_dt)
                else "-",
            }
        )

    if not rows:
        return

    df = pd.DataFrame(rows)
    heat_df = (
        df.melt(
            id_vars=["設問"],
            value_vars=["着手(分)", "経過(分)", "見直し回数"],
            var_name="指標",
            value_name="値",
        )
        .dropna(subset=["値"])
    )

    st.markdown("#### 時間配分ヒートマップ")
    st.caption("設問ごとの着手タイミング・経過時間・見直し回数を俯瞰できます。")
    if not heat_df.empty:
        chart = (
            alt.Chart(heat_df)
            .mark_rect()
            .encode(
                x=alt.X("設問:N", title=None),
                y=alt.Y("指標:N", sort=["着手(分)", "経過(分)", "見直し回数"], title=None),
                color=alt.Color("値:Q", scale=alt.Scale(scheme="tealblues"), title="値"),
                tooltip=[
                    alt.Tooltip("設問:N", title="設問"),
                    alt.Tooltip("指標:N", title="指標"),
                    alt.Tooltip("値:Q", title="値", format=".2f"),
                ],
            )
            .properties(height=150)
        )
        st.altair_chart(chart, use_container_width=True)
    display_df = df.copy()
    display_df["経過(分)"] = display_df["経過(分)"].map(
        lambda value: round(float(value), 1) if isinstance(value, (int, float)) else value
    )
    st.data_editor(
        display_df[["設問", "着手時刻", "経過(分)", "見直し回数", "最終更新"]],
        hide_index=True,
        width="stretch",
        disabled=True,
    )


def _build_weakness_drill_items(summaries: List[Dict[str, Any]]) -> List[Dict[str, str]]:
    collected: Dict[Tuple[str, str], Set[str]] = {}
    for summary in summaries:
        case_label = summary.get("case_label") or ""
        keyword_hits = summary.get("keyword_hits") or {}
        missing_keywords = [kw for kw, hit in keyword_hits.items() if not hit]
        for entry in _WEAKNESS_CASE_PATTERNS.get(case_label or "", []):
            tag = entry.get("tag")
            patterns = entry.get("patterns", [])
            for keyword in missing_keywords:
                if any(pattern in keyword for pattern in patterns):
                    collected.setdefault((tag, case_label), set()).add(f"「{keyword}」が不足")
        connector_stats = summary.get("connector_stats") or {}
        answer_text = summary.get("answer_text", "")
        if answer_text and connector_stats.get("total_hits", 0) == 0:
            collected.setdefault(("因果構成", case_label), set()).add("接続詞が検出されませんでした")

    items: List[Dict[str, str]] = []
    for (tag, case_label), reasons in collected.items():
        suggestion = _WEAKNESS_DRILL_MESSAGES.get(tag, "関連分野のドリルを復習しましょう。")
        label = case_label or "全体"
        items.append(
            {
                "tag": tag,
                "case_label": label,
                "reason": "、".join(sorted(reasons)),
                "suggestion": suggestion,
            }
        )
    items.sort(key=lambda item: (item["tag"], item["case_label"]))
    return items


def _render_weakness_drill_section(summaries: List[Dict[str, Any]]) -> None:
    drill_items = _build_weakness_drill_items(summaries)
    if not drill_items:
        return
    st.markdown("#### 弱点ドリル提案")
    st.caption("不足タグに対応したドリルで重点復習のプランを組み立てましょう。")
    for item in drill_items:
        st.markdown(
            f"- **{item['tag']}**（{item['case_label']}）: {item['reason']} → {item['suggestion']}"
        )


def render_attempt_results(attempt_id: int) -> None:
    detail = database.fetch_attempt_detail(attempt_id)
    attempt = detail["attempt"]
    answers = detail["answers"]

    problem = database.fetch_problem(attempt["problem_id"])
    problem_context_text = _collect_problem_context_text(problem) if problem else None
    question_context_map: Dict[int, str] = {}
    if problem:
        for question in problem.get("questions", []):
            qid = question.get("id")
            if qid is None:
                continue
            for candidate in _iter_question_context_candidates(question):
                normalized = _normalize_text_block(candidate)
                if normalized:
                    question_context_map[qid] = normalized
                    break
    highlight_snapshot = None
    if problem:
        highlight_store = st.session_state.get("context_highlights") or {}
        identifier = (
            problem.get("id")
            or problem.get("slug")
            or problem.get("title")
            or "default"
        )
        highlight_snapshot = highlight_store.get(str(identifier))

    export_payload = export_utils.build_attempt_export_payload(
        attempt,
        answers,
        problem or {},
        highlight_snapshot=highlight_snapshot,
    )
    attempt_csv_data = export_utils.attempt_csv_bytes(export_payload)
    attempt_json_data = export_utils.attempt_json_bytes(export_payload)
    attempt_pdf_data = export_utils.attempt_pdf_bytes(export_payload)
    printable_html = export_utils.build_printable_html(export_payload)
    scoring_logs = database.fetch_scoring_logs_for_attempts([attempt_id])
    scoring_csv_data = (
        export_utils.scoring_logs_csv_bytes(scoring_logs) if scoring_logs else None
    )
    scoring_json_data = (
        export_utils.scoring_logs_json_bytes(scoring_logs) if scoring_logs else None
    )
    scoring_pdf_data = (
        export_utils.scoring_logs_pdf_bytes(scoring_logs) if scoring_logs else None
    )

    def _handle_self_eval_update(log_id: Optional[int], state_key: str) -> None:
        if not log_id:
            return
        selected = st.session_state.get(state_key, SELF_EVALUATION_DEFAULT)
        if selected == SELF_EVALUATION_DEFAULT:
            database.update_scoring_log_self_evaluation(log_id, None)
        else:
            database.update_scoring_log_self_evaluation(log_id, selected)
        st.session_state[f"{state_key}_saved"] = selected

    def _handle_review_note_update(log_id: Optional[int], state_key: str) -> None:
        if not log_id:
            return
        note_text = st.session_state.get(state_key, "")
        database.update_scoring_log_notes(log_id, note_text)
        st.session_state[f"{state_key}_saved_at"] = datetime.now(timezone.utc).isoformat()

    st.subheader("採点結果")
    total_score = attempt["total_score"] or 0
    total_max = attempt["total_max_score"] or 0
    st.metric("総合得点", f"{total_score:.1f} / {total_max:.1f}")
    review_plan = database.get_spaced_review(attempt["user_id"], attempt["problem_id"])
    if review_plan:
        due_at = review_plan["due_at"]
        interval = review_plan["interval_days"]
        recommendation_label = (
            f"推奨: 類題{review_plan['recommended_items']}問 / 約{review_plan['recommended_minutes']}分"
        )
        if due_at <= datetime.now(timezone.utc):
            st.warning(
                f"この事例の復習期限が到来しています。次回目安 {due_at.strftime('%Y-%m-%d %H:%M')}"
                f" (間隔 {interval}日, {recommendation_label})",
                icon="🔁",
            )
        else:
            st.info(
                f"次回の復習目安は {due_at.strftime('%Y-%m-%d %H:%M')} ごろです"
                f" (推奨間隔 {interval}日, {recommendation_label})",
                icon="🔁",
            )
    if attempt["mode"] == "mock" and total_max:
        ratio = total_score / total_max
        if ratio >= 0.7:
            st.success("模擬試験クリア！称号『模試コンプリート』を獲得しました。")
            st.balloons()

    def _classify_score_ratio(ratio: Optional[float]) -> str:
        if ratio is None:
            return "採点待ち"
        if ratio >= 0.8:
            return "得意ゾーン"
        if ratio >= 0.5:
            return "伸びしろ"
        return "要強化"

    summary_rows: List[Dict[str, Any]] = []
    question_records: List[Dict[str, Any]] = []
    for idx, answer in enumerate(answers, start=1):
        score = float(answer.get("score") or 0.0)
        max_score = float(answer.get("max_score") or 0.0)
        ratio = None
        if max_score:
            ratio = max(min(score / max_score, 1.0), 0.0)
        keyword_hits = answer.get("keyword_hits") or {}
        keyword_coverage = answer.get("keyword_coverage")
        if keyword_coverage is None and keyword_hits:
            total_keywords = len(keyword_hits)
            if total_keywords:
                keyword_coverage = sum(1 for hit in keyword_hits.values() if hit) / total_keywords
        keyword_label = ", ".join([kw for kw, hit in keyword_hits.items() if hit]) or "-"
        keyword_pct = (
            round(keyword_coverage * 100, 1) if keyword_coverage is not None else None
        )
        status_label = _classify_score_ratio(ratio)
        year_label = str(answer.get("year") or "").strip()
        case_label = str(answer.get("case_label") or "").strip() or "未分類"
        question_label_parts = [part for part in [year_label, case_label, f"設問{idx}"] if part]
        question_label = " ".join(question_label_parts)
        summary_rows.append(
            {
                "設問": idx,
                "得点": score,
                "満点": max_score,
                "得点率(%)": round(ratio * 100, 1) if ratio is not None else None,
                "評価": status_label,
                "キーワード達成": keyword_label,
                "キーワード網羅率(%)": keyword_pct,
            }
        )
        question_records.append(
            {
                "question_order": idx,
                "question_label": question_label or f"設問{idx}",
                "score": score,
                "max_score": max_score,
                "score_ratio": ratio,
                "status": status_label,
                "case_label": case_label,
                "keyword_rate": keyword_coverage,
            }
        )

    if summary_rows:
        st.data_editor(
            pd.DataFrame(summary_rows),
            hide_index=True,
            width="stretch",
            disabled=True,
        )
        st.caption(
            "各設問の得点率・キーワード網羅率・評価カテゴリを一覧化しました。弱点分析に活用してください。"
        )

    if question_records:
        st.markdown("#### 設問別パフォーマンスの可視化")
        chart_df = pd.DataFrame(question_records)
        chart_df["status"].fillna("採点待ち", inplace=True)
        chart_df["case_label"].fillna("未分類", inplace=True)
        status_options = list(chart_df["status"].unique())
        case_options = sorted(chart_df["case_label"].unique())
        filter_col1, filter_col2 = st.columns(2)
        selected_status = filter_col1.multiselect(
            "注目レベル",
            status_options,
            default=status_options,
            key=f"question_status_filter_{attempt_id}",
            help="得意ゾーン／要強化などのカテゴリで絞り込みます。",
        )
        selected_cases = filter_col2.multiselect(
            "事例フィルタ",
            case_options,
            default=case_options,
            key=f"question_case_filter_{attempt_id}",
            help="対象とする事例（分野）を選択してください。",
        )
        if not selected_status:
            selected_status = status_options
        if not selected_cases:
            selected_cases = case_options
        filtered_df = chart_df[
            chart_df["status"].isin(selected_status)
            & chart_df["case_label"].isin(selected_cases)
        ]
        ratio_df = filtered_df.dropna(subset=["score_ratio"]).copy()
        if not ratio_df.empty:
            color_scale = alt.Scale(
                domain=["要強化", "伸びしろ", "得意ゾーン", "採点待ち"],
                range=["#d14343", "#f2a73b", "#2a7f62", "#9ca3af"],
            )
            bar_chart = (
                alt.Chart(ratio_df)
                .mark_bar(cornerRadius=6)
                .encode(
                    x=alt.X("question_label:N", title="設問", sort=None),
                    y=alt.Y(
                        "score_ratio:Q",
                        title="得点率",
                        axis=alt.Axis(format="%"),
                        scale=alt.Scale(domain=[0, 1]),
                    ),
                    color=alt.Color("status:N", title="評価", scale=color_scale),
                    tooltip=[
                        alt.Tooltip("question_label:N", title="設問"),
                        alt.Tooltip("score:Q", title="得点", format=".1f"),
                        alt.Tooltip("max_score:Q", title="満点", format=".1f"),
                        alt.Tooltip("score_ratio:Q", title="得点率", format=".0%"),
                        alt.Tooltip(
                            "keyword_rate:Q",
                            title="キーワード網羅率",
                            format=".0%",
                        ),
                        alt.Tooltip("status:N", title="評価"),
                    ],
                )
                .properties(height=280)
            )
            st.altair_chart(bar_chart, use_container_width=True)
        else:
            st.info("選択条件に該当する設問の得点率データがありません。")

        weakness_df = filtered_df[filtered_df["status"] == "要強化"].dropna(
            subset=["score_ratio"]
        )
        strength_df = filtered_df[filtered_df["status"] == "得意ゾーン"].dropna(
            subset=["score_ratio"]
        )
        if not weakness_df.empty:
            st.warning(
                "要強化カテゴリの設問があります。反復練習の優先度を上げましょう。",
                icon="📌",
            )
            for row in weakness_df.sort_values("score_ratio").itertuples():
                keyword_hint = (
                    f" / キーワード網羅率 {row.keyword_rate:.0%}"
                    if row.keyword_rate is not None
                    else ""
                )
                st.markdown(
                    f"- **{row.question_label}**: 得点率 {row.score_ratio:.0%}{keyword_hint}"
                )
        if not strength_df.empty:
            st.success("得意ゾーンの設問です。自信を維持しつつ応用問題に挑戦しましょう。", icon="💪")
            for row in strength_df.sort_values("score_ratio", ascending=False).itertuples():
                keyword_hint = (
                    f" / キーワード網羅率 {row.keyword_rate:.0%}"
                    if row.keyword_rate is not None
                    else ""
                )
                st.markdown(
                    f"- **{row.question_label}**: 得点率 {row.score_ratio:.0%}{keyword_hint}"
                )

        history_records = database.fetch_user_question_scores(attempt["user_id"])
        if history_records:
            history_df = pd.DataFrame(history_records)
            history_df["case_label"].fillna("未分類", inplace=True)
            history_df["score_ratio"] = history_df.apply(
                lambda row: (row["score"] / row["max_score"]) if row["max_score"] else None,
                axis=1,
            )
            history_df["status"] = history_df["score_ratio"].apply(_classify_score_ratio)
            history_df["question_label"] = history_df.apply(
                lambda row: " ".join(
                    part
                    for part in [
                        str(row.get("year") or "").strip(),
                        str(row.get("case_label") or "未分類").strip(),
                        f"設問{int(row.get('question_order') or 0)}",
                    ]
                    if part
                ),
                axis=1,
            )
            st.markdown("##### スコア履歴ヒストグラム")
            hist_status = st.multiselect(
                "履歴の評価カテゴリ",
                status_options,
                default=status_options,
                key=f"history_status_filter_{attempt_id}",
            )
            hist_cases = st.multiselect(
                "履歴の事例フィルタ",
                sorted(history_df["case_label"].unique()),
                default=selected_cases,
                key=f"history_case_filter_{attempt_id}",
            )
            hist_questions = st.multiselect(
                "設問の選択",
                sorted(history_df["question_label"].unique()),
                default=sorted(set(chart_df["question_label"].unique())),
                key=f"history_question_filter_{attempt_id}",
            )
            if not hist_status:
                hist_status = status_options
            if not hist_cases:
                hist_cases = sorted(history_df["case_label"].unique())
            if not hist_questions:
                hist_questions = sorted(history_df["question_label"].unique())

            hist_filtered = history_df[
                history_df["status"].isin(hist_status)
                & history_df["case_label"].isin(hist_cases)
                & history_df["question_label"].isin(hist_questions)
            ]
            hist_filtered = hist_filtered.dropna(subset=["score_ratio"])
            if not hist_filtered.empty:
                hist_chart = (
                    alt.Chart(hist_filtered)
                    .mark_bar(opacity=0.8)
                    .encode(
                        x=alt.X(
                            "score_ratio:Q",
                            bin=alt.Bin(maxbins=12),
                            title="得点率",
                            axis=alt.Axis(format="%"),
                        ),
                        y=alt.Y("count():Q", title="回数"),
                        color=alt.Color(
                            "question_label:N",
                            title="設問",
                            legend=alt.Legend(title="設問"),
                        ),
                        tooltip=[
                            alt.Tooltip("question_label:N", title="設問"),
                            alt.Tooltip("count():Q", title="回数"),
                        ],
                    )
                    .properties(height=260)
                )
                st.altair_chart(hist_chart, use_container_width=True)
                st.caption("選択した設問の得点率分布です。ヒストグラムの山が左寄りなら優先的に復習しましょう。")
            else:
                st.info("条件に合致する履歴データがありません。演習を重ねるとヒストグラムが生成されます。")

    st.divider()

    export_col1, export_col2, export_col3 = st.columns(3)
    with export_col1:
        st.download_button(
            "答案をCSVでダウンロード",
            data=attempt_csv_data,
            file_name=f"attempt_{attempt_id}_answers.csv",
            mime="text/csv",
        )
    with export_col2:
        st.download_button(
            "答案をJSONでダウンロード",
            data=attempt_json_data,
            file_name=f"attempt_{attempt_id}_answers.json",
            mime="application/json",
        )
    with export_col3:
        st.download_button(
            "答案をPDFでダウンロード",
            data=attempt_pdf_data,
            file_name=f"attempt_{attempt_id}_summary.pdf",
            mime="application/pdf",
        )
    st.caption("PDF/CSV/JSONで答案と講評を保存し、外部共有やポートフォリオ作成に活用できます。")

    if scoring_logs:
        log_col1, log_col2, log_col3 = st.columns(3)
        with log_col1:
            st.download_button(
                "採点ログCSV",
                data=scoring_csv_data,
                file_name=f"attempt_{attempt_id}_scoring_logs.csv",
                mime="text/csv",
            )
        with log_col2:
            st.download_button(
                "採点ログJSON",
                data=scoring_json_data,
                file_name=f"attempt_{attempt_id}_scoring_logs.json",
                mime="application/json",
            )
        with log_col3:
            st.download_button(
                "採点ログPDF",
                data=scoring_pdf_data,
                file_name=f"attempt_{attempt_id}_scoring_logs.pdf",
                mime="application/pdf",
            )
        log_rows = []
        for entry in scoring_logs:
            duration_minutes = None
            if entry.get("duration_seconds") is not None:
                try:
                    duration_minutes = float(entry.get("duration_seconds")) / 60.0
                except (TypeError, ValueError):
                    duration_minutes = None
            coverage_pct = (
                entry.get("keyword_coverage") * 100 if entry.get("keyword_coverage") is not None else None
            )
            log_rows.append(
                {
                    "設問": entry.get("question_order"),
                    "得点": entry.get("score"),
                    "満点": entry.get("max_score"),
                    "キーワード網羅率(%)": round(coverage_pct, 1) if coverage_pct is not None else None,
                    "所要時間(分)": round(duration_minutes, 1) if duration_minutes is not None else None,
                    "自己評価": entry.get("self_evaluation") or SELF_EVALUATION_DEFAULT,
                }
            )
        log_df = pd.DataFrame(log_rows)
        st.data_editor(log_df, hide_index=True, width="stretch", disabled=True)
        st.caption("採点ログは時系列に蓄積され、復習提案の精度向上に利用されます。CSV/JSON/PDFでのバックアップも可能です。")

    with st.expander("印刷ビュー（与件＋解答＋講評を1ページに集約）", expanded=False):
        components.html(printable_html, height=900, scrolling=True)

    activities = database.fetch_attempt_activity(attempt_id)
    if activities:
        _render_time_allocation_heatmap(attempt, activities)

    case_label = answers[0].get("case_label") if answers else None
    bundle_evaluation = scoring.evaluate_case_bundle(case_label=case_label, answers=answers)
    if bundle_evaluation:
        _render_case_bundle_feedback(bundle_evaluation)

    drill_inputs: List[Dict[str, Any]] = []
    for idx, answer in enumerate(answers, start=1):
        with st.expander(f"設問{idx}の結果", expanded=True):
            st.write(f"**得点:** {answer['score']} / {answer['max_score']}")
            duration_minutes = None
            if answer.get("duration_seconds") is not None:
                try:
                    duration_minutes = float(answer.get("duration_seconds")) / 60.0
                except (TypeError, ValueError):
                    duration_minutes = None
            duration_label = (
                f"{duration_minutes:.1f}分" if duration_minutes is not None else "-"
            )
            st.write(f"**所要時間:** {duration_label}")
            st.write(f"**自己評価:** {answer.get('self_evaluation') or SELF_EVALUATION_DEFAULT}")
            st.write("**フィードバック**")
            st.markdown(f"<pre>{answer['feedback']}</pre>", unsafe_allow_html=True)
            keyword_hits = answer.get("keyword_hits") or {}
            if keyword_hits:
                _render_keyword_coverage_from_hits(keyword_hits)
                missing_keywords = [kw for kw, hit in keyword_hits.items() if not hit]
                if missing_keywords:
                    st.markdown("**不足キーワード**")
                    st.write("、".join(missing_keywords))
            else:
                st.caption("キーワード採点は設定されていません。")
            answer_text = str(answer.get("answer_text", ""))
            connector_stats = _render_causal_connector_indicator(
                answer_text, show_breakdown=True
            )
            analysis = _render_mece_status_labels(answer_text)
            strengths, improvements = _summarize_strengths_and_gaps(
                keyword_hits,
                connector_stats,
                analysis,
            )
            if answer_text.strip():
                summary_cols = st.columns(2)
                with summary_cols[0]:
                    st.markdown("**強み**")
                    for point in strengths:
                        st.write(f"- {point}")
                with summary_cols[1]:
                    st.markdown("**次に改善すべき点**")
                    for point in improvements:
                        st.write(f"- {point}")
            axis_breakdown = answer.get("axis_breakdown") or {}
            if keyword_hits:
                keyword_df = pd.DataFrame(
                    [[kw, "○" if hit else "×"] for kw, hit in keyword_hits.items()],
                    columns=["キーワード", "判定"],
                )
                st.table(keyword_df)
            context_source = question_context_map.get(answer.get("question_id")) or problem_context_text
            citations = _extract_context_citations(answer_text, context_source)
            with st.expander("構造分析・引用ハイライト", expanded=False):
                _render_mece_causal_scanner(answer_text, analysis=analysis)
                if citations:
                    st.markdown("**与件引用マップ**")
                    for item in citations:
                        st.markdown(
                            "<p><strong>答案</strong>: {answer}<br/><strong>与件</strong>: {context}</p>".format(
                                answer=html.escape(item["answer"]),
                                context=item["context_html"],
                            ),
                            unsafe_allow_html=True,
                        )
                else:
                    st.caption(
                        "与件との対応関係は検出されませんでした。根拠となる記述を引用しながら書きましょう。"
                    )
            with st.expander("模範解答との差分ハイライト", expanded=False):
                _render_model_answer_diff(answer_text, answer.get("model_answer") or "")
            log_id = answer.get("scoring_log_id")
            if log_id:
                state_key = f"self_eval_select_{attempt_id}_{log_id}"
                if state_key not in st.session_state:
                    st.session_state[state_key] = answer.get("self_evaluation") or SELF_EVALUATION_DEFAULT
                st.selectbox(
                    "自己評価を記録",
                    SELF_EVALUATION_LABELS,
                    key=state_key,
                    on_change=_handle_self_eval_update,
                    args=(log_id, state_key),
                    help="選択した手応えは採点ログに保存され、次回の提案調整に活用されます。",
                )
                saved_value = st.session_state.get(f"{state_key}_saved", st.session_state[state_key])
                st.caption(f"保存済みの評価: {saved_value}")
                note_key = f"review_note_{attempt_id}_{log_id}"
                if note_key not in st.session_state:
                    st.session_state[note_key] = answer.get("review_note") or ""
                st.text_area(
                    "復習メモを残す",
                    key=note_key,
                    height=120,
                    placeholder="気づきや次回の改善ポイントをメモしましょう。",
                    on_change=_handle_review_note_update,
                    args=(log_id, note_key),
                )
                answer["review_note"] = st.session_state.get(note_key, "")
                note_saved = st.session_state.get(f"{note_key}_saved_at")
                if note_saved:
                    st.caption(f"メモ保存: {note_saved}")
            else:
                st.caption("自己評価ログはこの設問でまだ作成されていません。")
                st.text_area(
                    "復習メモを残す",
                    value=answer.get("review_note") or "",
                    height=120,
                    disabled=True,
                    help="採点ログが生成されるとメモを保存できるようになります。",
                )
            with st.expander("模範解答と解説", expanded=False):
                model_answer_text = _normalize_text_block(answer["model_answer"])
                if answer_text.strip() and model_answer_text:
                    st.markdown("**答案比較ビュー**")
                    _ensure_keyword_feedback_styles()
                    user_highlight = _highlight_keywords_in_text(
                        answer_text,
                        keyword_hits,
                    )
                    model_highlight = _highlight_keywords_in_text(
                        model_answer_text,
                        keyword_hits,
                        include_missing=True,
                    )
                    compare_cols = st.columns(2)
                    with compare_cols[0]:
                        st.markdown("<p class='answer-compare-heading'>あなたの答案</p>", unsafe_allow_html=True)
                        st.markdown(
                            f"<div class='answer-compare-block'><pre>{user_highlight}</pre></div>",
                            unsafe_allow_html=True,
                        )
                    with compare_cols[1]:
                        st.markdown("<p class='answer-compare-heading'>模範解答</p>", unsafe_allow_html=True)
                        st.markdown(
                            f"<div class='answer-compare-block'><pre>{model_highlight}</pre></div>",
                            unsafe_allow_html=True,
                        )
                if axis_breakdown:
                    st.markdown("**観点別スコアの内訳**")
                    _render_axis_breakdown(axis_breakdown)
                st.caption(
                    "Evidence Based Educationのガイドラインに沿って、比較ビューと観点別スコアを同じセクションで確認できるようにしました。"
                )
                _render_model_answer_section(
                    model_answer=answer["model_answer"],
                    explanation=answer["explanation"],
                    video_url=answer.get("video_url"),
                    context_id=f"attempt-{attempt_id}-q{idx}",
                    year=answer.get("year"),
                    case_label=answer.get("case_label"),
                    question_number=_normalize_question_number(answer.get("question_order")),
                    detailed_explanation=answer.get("detailed_explanation"),
                )
                st.caption("採点基準: 模範解答の論点とキーワードが盛り込まれているかを中心に評価しています。")
            drill_inputs.append(
                {
                    "case_label": answer.get("case_label"),
                    "keyword_hits": keyword_hits,
                    "answer_text": answer_text,
                    "connector_stats": connector_stats,
                }
            )

    if drill_inputs:
        _render_weakness_drill_section(drill_inputs)

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
    st.dataframe(detail_df, hide_index=True, width="stretch")
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


def _ensure_mock_exam_layout_styles() -> None:
    if st.session_state.get("_mock_exam_layout_styles"):
        return

    st.markdown(
        dedent(
            """
            <style>
            .mock-header-anchor + div[data-testid="stHorizontalBlock"] {
                background: linear-gradient(135deg, #f8fafc 0%, #eef2ff 100%);
                border: 1px solid #e2e8f0;
                border-radius: 18px;
                padding: 0.85rem 1.2rem;
                box-shadow: 0 6px 18px rgba(15, 23, 42, 0.08);
                position: sticky;
                top: 0.5rem;
                z-index: 40;
            }
            .mock-header-anchor + div[data-testid="stHorizontalBlock"] div[data-testid="column"] {
                padding: 0.25rem 0.65rem;
            }
            .mock-header-title {
                font-size: 1.15rem;
                font-weight: 700;
                color: #1e293b;
                margin-bottom: 0.35rem;
            }
            .mock-progress-root {
                width: 100%;
                height: 0.75rem;
                border-radius: 999px;
                background: rgba(148, 163, 184, 0.28);
                overflow: hidden;
                position: relative;
            }
            .mock-progress-fill {
                height: 100%;
                background: linear-gradient(90deg, #2563eb 0%, #38bdf8 100%);
                border-radius: 999px;
                transition: width 0.3s ease;
            }
            .mock-progress-caption {
                font-size: 0.82rem;
                color: #334155;
                margin-top: 0.35rem;
                margin-bottom: 0;
                font-weight: 600;
            }
            .mock-timer-value {
                font-family: "Fira Mono", "SFMono-Regular", monospace;
                font-size: 1.4rem;
                font-weight: 700;
                text-align: right;
                margin-bottom: 0.35rem;
                color: #0f172a;
            }
            .mock-timer-value[data-state="warn"] {
                color: #b45309;
            }
            .mock-timer-value[data-state="critical"] {
                color: #dc2626;
            }
            .mock-timer-value[data-state="paused"] {
                color: #2563eb;
            }
            .mock-question-panel-spacer + div[data-testid="stVerticalBlock"] {
                background: #f8fafc;
                border: 1px solid #e2e8f0;
                border-radius: 16px;
                padding: 0.85rem 0.75rem 1.25rem;
                box-shadow: inset 0 1px 0 rgba(148, 163, 184, 0.25);
            }
            .mock-question-panel-spacer + div[data-testid="stVerticalBlock"] .mock-question-case-label {
                font-weight: 700;
                color: #1f2937;
                margin: 0.35rem 0 0.5rem;
            }
            .mock-question-panel-spacer + div[data-testid="stVerticalBlock"] div[data-testid="stButton"] > button {
                width: 100%;
                border-radius: 12px;
                border: 1px solid transparent;
                background: rgba(59, 130, 246, 0.08);
                color: #1d4ed8;
                font-weight: 600;
                text-align: left;
                padding: 0.55rem 0.75rem;
            }
            .mock-question-panel-spacer + div[data-testid="stVerticalBlock"] div[data-testid="stButton"] > button:hover {
                border-color: rgba(59, 130, 246, 0.35);
                background: rgba(59, 130, 246, 0.12);
            }
            .mock-question-panel-spacer + div[data-testid="stVerticalBlock"] div[data-testid="stButton"]:focus-within {
                outline: 2px solid rgba(59, 130, 246, 0.35);
                outline-offset: 2px;
                border-radius: 14px;
            }
            .mock-question-divider {
                height: 1px;
                background: rgba(148, 163, 184, 0.35);
                margin: 0.6rem 0;
            }
            .mock-question-status-line {
                font-size: 0.78rem;
                color: #475569;
                margin-top: -0.35rem;
                margin-bottom: 0.35rem;
            }
            .mock-question-memo-preview {
                font-size: 0.78rem;
                background: rgba(226, 232, 240, 0.6);
                padding: 0.3rem 0.45rem;
                border-radius: 8px;
                color: #0f172a;
                margin-bottom: 0.4rem;
            }
            .mock-question-summary {
                margin-top: 0.8rem;
                font-size: 0.8rem;
                font-weight: 600;
                color: #1f2937;
            }
            .mock-info-panel-expander > summary {
                font-weight: 600;
                color: #1d4ed8;
            }
            .mock-info-panel-expander {
                border-radius: 12px !important;
                border: 1px solid rgba(59, 130, 246, 0.25) !important;
                background: rgba(191, 219, 254, 0.25) !important;
            }
            .mock-right-panel-spacer + div[data-testid="stVerticalBlock"] {
                background: #ffffff;
                border: 1px solid #e2e8f0;
                border-radius: 16px;
                padding: 0.85rem 0.85rem 1.2rem;
                box-shadow: 0 4px 14px rgba(15, 23, 42, 0.06);
            }
            .mock-right-panel-spacer + div[data-testid="stVerticalBlock"] .stTabs [data-baseweb="tab-list"] {
                gap: 0.35rem;
            }
            .mock-right-panel-spacer + div[data-testid="stVerticalBlock"] .stTabs [data-baseweb="tab"] {
                padding: 0.4rem 0.85rem;
                border-radius: 999px;
                background: rgba(226, 232, 240, 0.7);
                color: #1e293b;
            }
            .mock-right-panel-spacer + div[data-testid="stVerticalBlock"] .stTabs [data-baseweb="tab"][aria-selected="true"] {
                background: rgba(59, 130, 246, 0.18);
                color: #1d4ed8;
            }
            .mock-frame-card {
                border: 1px solid rgba(148, 163, 184, 0.45);
                border-radius: 14px;
                padding: 0.65rem 0.75rem;
                margin-bottom: 0.65rem;
                background: #f8fafc;
            }
            .mock-frame-card h5 {
                font-size: 0.9rem;
                margin-bottom: 0.35rem;
                color: #1e293b;
            }
            .mock-frame-card p {
                font-size: 0.8rem;
                color: #475569;
            }
            </style>
            """
        ),
        unsafe_allow_html=True,
    )
    st.session_state["_mock_exam_layout_styles"] = True


MOCK_QUESTION_STATUS_ICONS = {
    "pending": "⬜️",
    "answered": "✅",
    "flagged": "🚩",
}

MOCK_QUESTION_STATUS_LABELS = {
    "pending": "未回答",
    "answered": "回答済",
    "flagged": "要確認",
}


def _format_mmss(total_seconds: int) -> str:
    seconds = max(int(total_seconds), 0)
    minutes, sec = divmod(seconds, 60)
    return f"{minutes:02d}:{sec:02d}"


def _mock_timer_stats(session: Mapping[str, Any]) -> Tuple[int, int, int]:
    duration_minutes = int(session.get("duration_minutes") or 80)
    total_seconds = max(duration_minutes, 1) * 60
    start_time = session.get("start")
    if not isinstance(start_time, datetime):
        return 0, total_seconds, total_seconds

    paused = bool(session.get("paused"))
    paused_at = session.get("paused_at")
    pause_accum = float(session.get("pause_accum", 0.0) or 0.0)
    reference_time = (
        paused_at
        if paused and isinstance(paused_at, datetime)
        else datetime.now(timezone.utc)
    )
    elapsed = (reference_time - start_time).total_seconds() - pause_accum
    elapsed = max(int(elapsed), 0)
    remaining = max(int(total_seconds - elapsed), 0)
    return elapsed, remaining, int(total_seconds)


def _toggle_mock_timer(session: Dict[str, Any]) -> None:
    now = datetime.now(timezone.utc)
    if session.get("paused"):
        paused_at = session.get("paused_at")
        if isinstance(paused_at, datetime):
            session["pause_accum"] = float(session.get("pause_accum", 0.0) or 0.0) + max(
                (now - paused_at).total_seconds(), 0.0
            )
        session["paused"] = False
        session["paused_at"] = None
    else:
        session["paused"] = True
        session["paused_at"] = now


def _collect_mock_question_registry(
    exam: mock_exam.MockExam, signature: str
) -> Tuple[List[Dict[str, Any]], Dict[int, Dict[str, Any]], Dict[Tuple[int, Any], str]]:
    registry: List[Dict[str, Any]] = []
    problem_cache: Dict[int, Dict[str, Any]] = {}
    anchor_map: Dict[Tuple[int, Any], str] = {}

    for problem_index, problem_id in enumerate(exam.problem_ids, start=1):
        problem = _apply_uploaded_text_overrides(
            _load_problem_detail(problem_id, signature)
        )
        if not problem:
            continue
        problem_cache[problem_id] = problem
        case_label = problem.get("case_label") or problem.get("case") or "事例"
        for question_index, question in enumerate(problem.get("questions", []), start=1):
            question_id = question.get("id")
            anchor_id = _question_anchor_id(
                question,
                question_index=question_index,
            )
            if anchor_id and question_id is not None:
                anchor_map[(problem_id, question_id)] = anchor_id
            registry.append(
                {
                    "problem_id": problem_id,
                    "question_id": question_id,
                    "case_label": case_label,
                    "index": question_index,
                    "prompt": question.get("prompt") or f"設問{question_index}",
                    "max_score": question.get("max_score"),
                    "anchor_id": anchor_id,
                    "draft_key": _draft_key(problem_id, question_id),
                }
            )

    return registry, problem_cache, anchor_map


def _render_mock_exam_header(
    exam: mock_exam.MockExam,
    session: Dict[str, Any],
    *,
    total_questions: int,
    answered_questions: int,
) -> None:
    _ensure_mock_exam_layout_styles()
    elapsed, remaining, total_seconds = _mock_timer_stats(session)
    progress_ratio = answered_questions / max(total_questions, 1)
    progress_pct = int(progress_ratio * 100)
    timer_state = "paused" if session.get("paused") else "ok"
    if not session.get("paused"):
        if remaining <= 300:
            timer_state = "critical"
        elif remaining <= 900:
            timer_state = "warn"

    with st.container():
        st.markdown("<div class='mock-header-anchor'></div>", unsafe_allow_html=True)
        left_col, center_col, right_col = st.columns([2.8, 3.2, 1.8])
        with left_col:
            st.markdown(
                f"<p class='mock-header-title'>{html.escape(exam.title)}</p>",
                unsafe_allow_html=True,
            )
            st.caption(
                f"全{total_questions}設問中 {answered_questions} 設問に入力済み"
            )
        with center_col:
            width = max(min(progress_pct, 100), 0)
            progress_html = dedent(
                """
                <div class='mock-progress-root' role='progressbar' aria-valuemin='0' aria-valuemax='100' aria-valuenow='{value}'>
                    <div class='mock-progress-fill' style='width: {width:.1f}%;'></div>
                </div>
                <p class='mock-progress-caption'>全体進捗 {value}%</p>
                """
            ).format(value=progress_pct, width=width)
            st.markdown(progress_html, unsafe_allow_html=True)
        with right_col:
            st.markdown(
                f"<div class='mock-timer-value' data-state='{timer_state}'>{_format_mmss(remaining)}</div>",
                unsafe_allow_html=True,
            )
            st.caption(
                f"経過 {_format_mmss(elapsed)} / 合計 {_format_mmss(total_seconds)}"
            )
            button_label = "▶️ 再開" if session.get("paused") else "⏸️ 一時停止"
            if st.button(button_label, key="mock_timer_toggle", use_container_width=True):
                _toggle_mock_timer(session)
                st.session_state.mock_session = session
                st.rerun()
            st.caption("タイマーが動かない場合はページを再読み込みしてください。")


def _render_mock_question_panel(
    question_registry: Sequence[Dict[str, Any]],
    exam: mock_exam.MockExam,
    *,
    progress_ratio: float,
    remaining_seconds: int,
) -> None:
    _ensure_mock_exam_layout_styles()
    flags: Dict[str, bool] = st.session_state.setdefault("mock_flags", {})
    memos: Dict[str, str] = st.session_state.setdefault("mock_memos", {})
    active_question = st.session_state.get("mock_active_question")

    grouped: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for entry in question_registry:
        grouped[entry.get("case_label") or "事例"].append(entry)

    with st.container():
        st.markdown("<div class='mock-question-panel-spacer'></div>", unsafe_allow_html=True)
        for case_label, entries in grouped.items():
            st.markdown(
                f"<p class='mock-question-case-label'>{html.escape(case_label)}</p>",
                unsafe_allow_html=True,
            )
            for entry in entries:
                question_id = entry.get("question_id")
                draft_key = entry.get("draft_key")
                draft_text = ""
                if draft_key and hasattr(st.session_state, "drafts"):
                    draft_text = st.session_state.drafts.get(draft_key, "")
                answered = bool(str(draft_text).strip())
                flag_key = str(question_id)
                status = "flagged" if flags.get(flag_key) else ("answered" if answered else "pending")
                status_icon = MOCK_QUESTION_STATUS_ICONS.get(status, "⬜️")
                status_label = MOCK_QUESTION_STATUS_LABELS.get(status, "未回答")
                label = f"{status_icon} 設問{entry['index']}"
                max_score = entry.get("max_score")
                if max_score:
                    label += f"（{max_score}点）"
                if question_id == active_question:
                    label = "👉 " + label
                button_key = f"mock-nav-{entry['problem_id']}-{question_id}"
                if st.button(label, key=button_key, use_container_width=True):
                    st.session_state["mock_active_question"] = question_id
                    anchor_id = entry.get("anchor_id")
                    if anchor_id:
                        st.session_state["_mock_scroll_target"] = anchor_id
                st.markdown(
                    f"<p class='mock-question-status-line'>{status_label} / 設問{entry['index']}を確認中</p>",
                    unsafe_allow_html=True,
                )
                memo_preview = memos.get(flag_key)
                if memo_preview:
                    preview_text = _format_preview_text(memo_preview, 40)
                    st.markdown(
                        f"<div class='mock-question-memo-preview'>📝 {html.escape(preview_text)}</div>",
                        unsafe_allow_html=True,
                    )
                action_cols = st.columns(2)
                with action_cols[0]:
                    flag_label = "🚩 フラグ解除" if flags.get(flag_key) else "🚩 フラグを付ける"
                    if st.button(
                        flag_label,
                        key=f"mock-flag-{entry['problem_id']}-{question_id}",
                        use_container_width=True,
                    ):
                        if flags.get(flag_key):
                            flags.pop(flag_key, None)
                        else:
                            flags[flag_key] = True
                        st.session_state.mock_flags = flags
                with action_cols[1]:
                    if st.button(
                        "📝 メモを追加",
                        key=f"mock-memo-{entry['problem_id']}-{question_id}",
                        use_container_width=True,
                    ):
                        st.session_state["mock_memo_target"] = question_id
                st.markdown("<div class='mock-question-divider'></div>", unsafe_allow_html=True)

        progress_pct = int(progress_ratio * 100)
        st.markdown(
            f"<p class='mock-question-summary'>全体進捗 {progress_pct}% ／ 残り時間 {_format_mmss(remaining_seconds)}</p>",
            unsafe_allow_html=True,
        )

        memo_target = st.session_state.get("mock_memo_target")
        if memo_target is not None:
            memo_key = str(memo_target)
            memo_widget_key = f"mock-memo-input::{memo_key}"
            default_value = memos.get(memo_key, "")
            memo_text = st.text_area(
                "選択中の設問メモ",
                value=default_value,
                key=memo_widget_key,
                height=100,
                placeholder="気づきや後で見直すポイントをメモできます。",
            )
            memos[memo_key] = memo_text
            st.session_state.mock_memos = memos

        if exam.notices:
            with st.expander(
                "試験注意事項", expanded=False
            ) as exp:
                exp.markdown("\n".join(f"- {note}" for note in exam.notices))


def _apply_mock_scroll_target() -> None:
    target = st.session_state.pop("_mock_scroll_target", None)
    if not target:
        return
    components.html(
        f"""
        <script>
        const targetId = {json.dumps(target)};
        const parentDoc = window.parent.document;
        const el = parentDoc.getElementById(targetId);
        if (el) {{
            el.scrollIntoView({{behavior: 'smooth', block: 'start'}});
        }}
        </script>
        """,
        height=0,
    )


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
        st.caption("試験概要を確認し、解きたい模試セットを選んでください。準備チェックが完了すると開始できます。")

        exams = mock_exam.available_mock_exams()
        exam_options = {exam.title: exam for exam in exams}
        exam_options["ランダム演習セット"] = mock_exam.random_mock_exam()

        selected_title = st.selectbox("模試セット", list(exam_options.keys()))
        selected_exam = exam_options[selected_title]

        case_summaries: List[str] = []
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

        st.markdown("### 試験開始前の準備")
        step1_checked = st.checkbox("STEP1 説明を確認しました", key="mock_step_desc")
        with st.expander("模試モードの進め方", expanded=step1_checked):
            st.write("- 80分のカウントダウンで事例I～IVをまとめて解きます。")
            st.write("- 左パネルで設問を一覧し、フラグやメモで見直し対象を管理できます。")
            st.write("- 回答欄下部のメーターで残字数と要点カバー率を同時に確認できます。")

        step2_checked = st.checkbox(
            "STEP2 注意事項を確認しました",
            key="mock_step_notice",
            disabled=not step1_checked,
        )
        with st.expander("試験注意事項", expanded=bool(step2_checked)):
            notices = selected_exam.notices or MOCK_NOTICE_ITEMS
            st.markdown("\n".join(f"- {note}" for note in notices))
            _render_mock_exam_overview(selected_exam, container=st)

        ready_to_start = step1_checked and step2_checked
        if ready_to_start:
            st.success("準備が整いました。下のボタンから試験を開始できます。")

        if st.button("試験を開始", type="primary", disabled=not ready_to_start):
            st.session_state.mock_session = {
                "exam": selected_exam,
                "start": datetime.now(timezone.utc),
                "answers": {},
                "duration_minutes": 80,
                "pause_accum": 0.0,
                "paused": False,
                "paused_at": None,
            }
            st.session_state.pop("mock_flags", None)
            st.session_state.pop("mock_memos", None)
            st.session_state.pop("mock_memo_target", None)
            st.session_state.pop("mock_active_question", None)
            st.session_state.pop("mock_step_desc", None)
            st.session_state.pop("mock_step_notice", None)
            st.rerun()
        return

    exam = session["exam"]
    start_time = session["start"]
    session.setdefault("duration_minutes", 80)
    session.setdefault("pause_accum", 0.0)
    session.setdefault("paused", False)
    session.setdefault("paused_at", None)

    registry, problem_cache, anchor_map = _collect_mock_question_registry(
        exam, signature
    )
    valid_entries = [entry for entry in registry if entry.get("question_id") is not None]
    total_questions = len(valid_entries) if valid_entries else len(registry)
    answered_questions = 0
    for entry in valid_entries:
        draft_key = entry.get("draft_key")
        if draft_key and hasattr(st.session_state, "drafts"):
            draft_value = st.session_state.drafts.get(draft_key, "")
            if str(draft_value).strip():
                answered_questions += 1
    progress_ratio = answered_questions / max(total_questions, 1)
    _, remaining_seconds, _ = _mock_timer_stats(session)

    st.session_state.setdefault("mock_flags", {})
    st.session_state.setdefault("mock_memos", {})
    st.session_state.setdefault("mock_memo_target", None)

    if valid_entries and st.session_state.get("mock_active_question") is None:
        st.session_state["mock_active_question"] = valid_entries[0]["question_id"]

    _render_mock_exam_header(
        exam,
        session,
        total_questions=max(total_questions, 1),
        answered_questions=answered_questions,
    )

    left_col, center_col, right_col = st.columns([1.15, 2.6, 1.6])

    with left_col:
        _render_mock_question_panel(
            registry,
            exam,
            progress_ratio=progress_ratio,
            remaining_seconds=remaining_seconds,
        )

    with center_col:
        tab_labels: List[str] = []
        for idx, problem_id in enumerate(exam.problem_ids):
            problem = problem_cache.get(problem_id)
            if not problem:
                problem = _apply_uploaded_text_overrides(
                    _load_problem_detail(problem_id, signature)
                )
            case_label = problem.get("case_label") if problem else "不明"
            tab_labels.append(f"{idx + 1}. {case_label}")

        tabs = st.tabs(tab_labels)
        for tab, problem_id in zip(tabs, exam.problem_ids):
            with tab:
                problem = problem_cache.get(problem_id)
                if not problem:
                    problem = _apply_uploaded_text_overrides(
                        _load_problem_detail(problem_id, signature)
                    )
                if not problem:
                    st.error("問題の読み込みに失敗しました。")
                    continue
                st.subheader(problem["title"])
                st.write(problem["overview"])
                question_total = len(problem.get("questions", []))
                for idx, question in enumerate(problem.get("questions", []), start=1):
                    tone = _practice_tone_for_index(idx)
                    st.markdown(
                        f'<section class="practice-question-block" data-tone="{tone}">',
                        unsafe_allow_html=True,
                    )
                    anchor_id = anchor_map.get((problem_id, question.get("id")))
                    _question_input(
                        problem_id,
                        question,
                        widget_prefix="mock_textarea_",
                        case_label=problem.get("case_label") or problem.get("case"),
                        question_index=idx,
                        anchor_id=anchor_id,
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
                missing_question_numbers = [
                    idx
                    for idx, question in enumerate(problem["questions"], start=1)
                    if question.get("id") is None
                ]
                if missing_question_numbers:
                    formatted_numbers = "、".join(
                        f"設問{num}" for num in missing_question_numbers
                    )
                    problem_year = _normalize_text_block(problem.get("year")) or ""
                    problem_case = _normalize_text_block(
                        problem.get("case_label") or problem.get("case")
                    )
                    logger.error(
                        "Skipping mock attempt for problem %s (year=%s, case=%s) due to missing question IDs: %s",
                        problem_id,
                        problem_year,
                        problem_case,
                        formatted_numbers,
                    )
                    st.error(
                        f"{problem_year} {problem_case} の {formatted_numbers} に設問ID登録されていないため採点結果を保存できません。",
                        icon="⚠️",
                    )
                    continue
                for question in problem["questions"]:
                    text = st.session_state.drafts.get(
                        _draft_key(problem_id, question["id"]), ""
                    )
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
                    case_question_results.append(
                        {"question": question, "answer": text, "result": result}
                    )
                submitted_at = datetime.now(timezone.utc)
                activity_summary = _summarise_question_activity(problem, submitted_at)
                for answer in answers:
                    if answer.question_id in activity_summary:
                        answer.activity = activity_summary[answer.question_id]
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
            st.session_state.question_activity = {}
            _remove_mock_notice_overlay()
            st.success("模擬試験の採点が完了しました。結果を確認してください。")
            for problem, attempt_id, weakness_tags in overall_results:
                st.markdown(f"### {problem['year']} {problem['case_label']} {problem['title']}")
                render_attempt_results(attempt_id)
                st.markdown("**弱点タグ**")
                if weakness_tags:
                    _render_tag_pills(weakness_tags, tone="warn")
                else:
                    st.caption("特筆すべき弱点は検出されませんでした。")

    with right_col:
        st.markdown("<div class='mock-right-panel-spacer'></div>", unsafe_allow_html=True)
        sidebar_tabs = st.tabs(["メモ・フラグ", "注意事項", "参考資料"])
        flags = st.session_state.get("mock_flags", {})
        memos = st.session_state.get("mock_memos", {})

        with sidebar_tabs[0]:
            flagged_entries = [
                entry
                for entry in registry
                if flags.get(str(entry.get("question_id")))
            ]
            memo_entries = [
                (entry, memos.get(str(entry.get("question_id"))))
                for entry in registry
                if memos.get(str(entry.get("question_id")))
            ]

            if flagged_entries:
                st.markdown("**フラグ付き設問**")
                for entry in flagged_entries:
                    question_id = entry.get("question_id")
                    label = f"設問{entry['index']}（{entry.get('case_label')}）"
                    if st.button(
                        f"移動: {label}",
                        key=f"mock-flag-jump::{question_id}",
                    ):
                        st.session_state["mock_active_question"] = question_id
                        anchor_id = entry.get("anchor_id")
                        if anchor_id:
                            st.session_state["_mock_scroll_target"] = anchor_id
            else:
                st.caption("フラグはまだ設定されていません。")

            if memo_entries:
                st.markdown("**メモ一覧**")
                for entry, memo_text in memo_entries:
                    preview = _format_preview_text(memo_text, 70)
                    st.markdown(
                        f"- 設問{entry['index']}（{entry.get('case_label')}）: {preview}"
                    )
            else:
                st.caption("メモはまだ登録されていません。")

        with sidebar_tabs[1]:
            if exam.timetable:
                st.markdown("**本番時間割**")
                for slot in exam.timetable:
                    detail = slot.get("detail")
                    detail_text = f"（{detail}）" if detail else ""
                    st.markdown(
                        f"- **{slot.get('slot', '')}**: {slot.get('time', '')}{detail_text}"
                    )
            notices = exam.notices or MOCK_NOTICE_ITEMS
            st.markdown("**注意事項**")
            st.markdown("\n".join(f"- {note}" for note in notices))

        with sidebar_tabs[2]:
            st.markdown("**参考リンク**")
            for resource in DEFAULT_KEYWORD_RESOURCES:
                st.markdown(
                    f"- [{resource['label']}]({resource['url']})",
                    unsafe_allow_html=False,
                )
            st.caption("参考資料は別タブで開きます。")

    _apply_mock_scroll_target()

    return

def history_page(user: Dict) -> None:
    """Render the revamped learning history experience."""

    # Reset trial overlay state when entering the history page.
    for state_key in ("mock_notice_toggle", "mock_session", "mock_overlay_state"):
        st.session_state.pop(state_key, None)
    _remove_mock_notice_overlay()

    st.session_state.setdefault("history_selected_attempt", None)

    st.title("学習履歴")
    st.caption("演習ログ・グラフ・分析・エクスポートをこのページで完結できます。")

    data_errors: Dict[str, str] = {}

    try:
        history_records = database.fetch_learning_history(user["id"])
    except Exception as exc:  # pragma: no cover - defensive guard
        history_records = []
        data_errors["history"] = str(exc)

    try:
        keyword_records = database.fetch_keyword_performance(user["id"])
    except Exception as exc:  # pragma: no cover
        keyword_records = []
        data_errors["keyword"] = str(exc)

    try:
        question_history_summary = database.fetch_user_question_history_summary(user["id"]) or []
    except Exception as exc:  # pragma: no cover
        question_history_summary = []
        data_errors["question"] = str(exc)

    try:
        global_question_metrics = database.fetch_question_master_stats() or {}
    except Exception as exc:  # pragma: no cover
        global_question_metrics = {}
        data_errors["master"] = str(exc)

    history_df = pd.DataFrame(history_records)
    if not history_df.empty:
        history_df["日付"] = pd.to_datetime(history_df["日付"], errors="coerce")
        history_df.sort_values("日付", inplace=True)
        for column in ("得点", "満点", "平均得点", "設問数", "学習時間(分)"):
            history_df[column] = pd.to_numeric(history_df[column], errors="coerce")
        history_df["得点率(%)"] = history_df.apply(
            lambda row: round(row["得点"] / row["満点"] * 100, 1)
            if pd.notnull(row["得点"]) and pd.notnull(row["満点"]) and row["満点"]
            else None,
            axis=1,
        )

    available_years = (
        history_df["年度"].dropna().astype(str).sort_values().unique().tolist()
        if "年度" in history_df
        else []
    )
    available_cases = (
        history_df["事例"].dropna().astype(str).unique().tolist()
        if "事例" in history_df
        else []
    )
    available_cases.sort(
        key=lambda label: CASE_ORDER.index(label) if label in CASE_ORDER else len(CASE_ORDER)
    )

    tag_candidates: Set[str] = set()
    for record in keyword_records:
        for keyword in (record.get("keyword_hits") or {}).keys():
            if keyword:
                tag_candidates.add(keyword)
    for summary in question_history_summary:
        for column in ("themes", "tendencies", "topics", "skill_tags"):
            values = summary.get(column) or []
            if isinstance(values, list):
                tag_candidates.update(tag for tag in values if tag)
    available_tags = sorted(tag_candidates)

    header_container = st.container()
    with header_container:
        title_col, action_col = st.columns([3, 2])
        with title_col:
            st.markdown("<h2 style='margin-bottom:0;'>学習履歴</h2>", unsafe_allow_html=True)
            st.caption("フィルターとショートカットで素早く目的のデータに到達できます。")
        with action_col:
            if st.button("試験モード終了", type="primary", use_container_width=True):
                st.session_state.pop("mock_session", None)
                st.session_state.pop("mock_notice_toggle", None)
                _remove_mock_notice_overlay()
                st.success("試験モードを終了しました。")

    with st.container():
        col_year, col_case, col_tag = st.columns(3)
        selected_years = col_year.multiselect("年度", options=available_years, key="history_filter_years")
        selected_cases = col_case.multiselect("事例", options=available_cases, key="history_filter_cases")
        selected_tags = col_tag.multiselect("タグ", options=available_tags, key="history_filter_tags")

    if not history_df.empty:
        period_min = history_df["日付"].min().to_pydatetime()
        period_max = history_df["日付"].max().to_pydatetime()
    else:
        now = datetime.now()
        period_min = now - timedelta(days=90)
        period_max = now

    if "history_period_range" not in st.session_state:
        st.session_state["history_period_range"] = (period_min, period_max)

    with st.container():
        default_start, default_end = st.session_state["history_period_range"]
        default_start = max(default_start, period_min)
        default_end = min(default_end, period_max)
        period_range = st.slider(
            "表示期間",
            min_value=period_min,
            max_value=period_max,
            value=(default_start, default_end),
            format="%Y/%m/%d",
            key="history_period_slider",
        )
        st.session_state["history_period_range"] = period_range

    shortcut_event = components.html(
        """
        <script>
        (function() {
            const parentDoc = window.parent.document;
            if (parentDoc.getElementById('history-shortcut-listener')) {
                return;
            }
            const marker = parentDoc.createElement('span');
            marker.id = 'history-shortcut-listener';
            marker.style.display = 'none';
            parentDoc.body.appendChild(marker);
            const tabMap = {"1": "一覧", "2": "グラフ", "3": "分析レポート", "4": "キーワード分析", "5": "設問別分析", "6": "エクスポート"};
            parentDoc.addEventListener('keydown', (event) => {
                if (event.altKey && tabMap[event.key]) {
                    const buttons = parentDoc.querySelectorAll('[data-baseweb="tab"] button, div[role="tablist"] button');
                    buttons.forEach((btn) => {
                        const label = (btn.innerText || '').trim();
                        if (label.startsWith(tabMap[event.key])) {
                            btn.click();
                        }
                    });
                } else if (!event.altKey && (event.key === '[' || event.key === ']')) {
                    window.parent.postMessage({isStreamlitMessage: true, type: 'streamlit:setComponentValue', value: event.key}, '*');
                }
            });
        })();
        </script>
        """,
        height=0,
    )

    if shortcut_event in ("[", "]") and not history_df.empty:
        shift = timedelta(days=7)
        current_start, current_end = st.session_state["history_period_range"]
        if shortcut_event == "[":
            new_start = max(period_min, current_start - shift)
            new_end = max(new_start, current_end - shift)
        else:
            new_end = min(period_max, current_end + shift)
            new_start = min(new_end, current_start + shift)
        st.session_state["history_period_range"] = (new_start, new_end)
        st.rerun()

    active_badges = []
    if selected_years:
        active_badges.extend([f"年度: {year}" for year in selected_years])
    if selected_cases:
        active_badges.extend([f"事例: {case}" for case in selected_cases])
    if selected_tags:
        active_badges.extend([f"タグ: {tag}" for tag in selected_tags])
    range_start, range_end = st.session_state["history_period_range"]
    active_badges.append(
        f"期間: {range_start.strftime('%Y/%m/%d')} - {range_end.strftime('%Y/%m/%d')}"
    )
    badges_html = "".join(
        f"<span style='background:#E7F1FB;color:#0B4D78;padding:4px 10px;border-radius:12px;margin-right:6px;font-size:0.85rem;'>" +
        f"{escape(text)}</span>" for text in active_badges
    )
    st.markdown(f"<div style='margin-bottom:0.5rem;'>{badges_html}</div>", unsafe_allow_html=True)

    filtered_history = history_df.copy()
    if selected_years:
        filtered_history = filtered_history[
            filtered_history["年度"].astype(str).isin(selected_years)
        ]
    if selected_cases:
        filtered_history = filtered_history[
            filtered_history["事例"].astype(str).isin(selected_cases)
        ]

    attempt_tag_map: Dict[int, Set[str]] = {}
    for record in keyword_records:
        attempt_id = record.get("attempt_id")
        if attempt_id is None:
            continue
        attempt_tags = attempt_tag_map.setdefault(int(attempt_id), set())
        for keyword in (record.get("keyword_hits") or {}).keys():
            if keyword:
                attempt_tags.add(keyword)
        for attr in ("themes", "tendencies", "topics", "skill_tags"):
            values = record.get(attr)
            if isinstance(values, list):
                attempt_tags.update(tag for tag in values if tag)

    if selected_tags:
        allowed_ids = {
            attempt_id
            for attempt_id, tags in attempt_tag_map.items()
            if set(selected_tags).issubset(tags)
        }
        filtered_history = filtered_history[
            filtered_history["attempt_id"].isin(allowed_ids)
        ]

    if not filtered_history.empty:
        filtered_history = filtered_history[
            (filtered_history["日付"] >= pd.to_datetime(range_start))
            & (filtered_history["日付"] <= pd.to_datetime(range_end))
        ]

    filtered_keyword_records = [
        record
        for record in keyword_records
        if not selected_tags
        or set(selected_tags).issubset(
            attempt_tag_map.get(int(record.get("attempt_id") or 0), set())
        )
    ]

    tabs = st.tabs([
        "一覧",
        "グラフ",
        "分析レポート",
        "キーワード分析",
        "設問別分析",
        "エクスポート",
    ])

    with tabs[0]:
        st.write("一覧タブでは左側に表、右側に答案と講評を表示します。Alt+1で戻れます。")
        if "history" in data_errors:
            st.error(f"履歴データの取得に失敗しました: {data_errors['history']}")
            filtered_history = filtered_history.iloc[0:0]
        if filtered_history.empty:
            st.info("データなし。フィルタや期間を調整してください。")
        else:
            summary_expander = st.expander("集計サマリ", expanded=True)
            with summary_expander:
                total_sessions = len(filtered_history)
                avg_score = filtered_history["得点"].dropna().mean()
                avg_ratio = filtered_history["得点率(%)"].dropna().mean()
                total_minutes = filtered_history["学習時間(分)"].dropna().sum()
                col_a, col_b, col_c, col_d = st.columns(4)
                with col_a:
                    st.metric("演習回数", f"{total_sessions}回")
                with col_b:
                    st.metric("平均得点", f"{avg_score:.1f}" if pd.notnull(avg_score) else "-")
                with col_c:
                    st.metric("平均得点率", f"{avg_ratio:.1f}%" if pd.notnull(avg_ratio) else "-")
                with col_d:
                    st.metric("総学習時間", f"{total_minutes:.1f}分")

            table_col, detail_col = st.columns([1.25, 1])
            display_df = filtered_history.copy()
            display_df["日付表示"] = display_df["日付"].dt.strftime("%Y-%m-%d %H:%M")
            display_df["得点率表示"] = display_df["得点率(%)"].map(
                lambda v: f"{v:.1f}" if pd.notnull(v) else "-"
            )
            display_df["学習時間表示"] = display_df["学習時間(分)"].map(
                lambda v: f"{v:.1f}" if pd.notnull(v) else "-"
            )

            selected_attempt = st.session_state.get("history_selected_attempt")
            focus_attempt = st.session_state.get("history_focus_attempt")
            highlight_from_notification = st.session_state.get("history_focus_from_notification")
            available_attempts = display_df["attempt_id"].astype(int).tolist()
            if focus_attempt and focus_attempt in available_attempts:
                selected_attempt = focus_attempt
                if highlight_from_notification:
                    st.success("通知センターで選択した演習を表示しています。", icon="🔔")
                    st.session_state["history_focus_from_notification"] = False
            if selected_attempt not in available_attempts and available_attempts:
                selected_attempt = available_attempts[-1]
            st.session_state["history_selected_attempt"] = selected_attempt

            with table_col:
                table_records = [
                    {
                        "attempt_id": row["attempt_id"],
                        "日付": row["日付表示"],
                        "年度": row["年度"],
                        "事例": row["事例"],
                        "タイトル": row["タイトル"],
                        "得点": row["得点"],
                        "得点率(%)": row["得点率表示"],
                        "学習時間(分)": row["学習時間表示"],
                        "モード": row["モード"],
                        "設問数": row["設問数"],
                    }
                    for _, row in display_df.iterrows()
                ]
                table_json = json.dumps(table_records, ensure_ascii=False)
                selected_json = json.dumps(selected_attempt)
                table_template = dedent("""
                <div id="history-table" style="border:1px solid #d0d7de;border-radius:8px;overflow:auto;max-height:520px;">
                  <table style="width:100%;border-collapse:collapse;font-size:0.9rem;">
                    <thead style="position:sticky;top:0;background:#f5f7fa;">
                      <tr>
                        <th style="text-align:left;padding:8px;">日付</th>
                        <th style="text-align:left;padding:8px;">年度</th>
                        <th style="text-align:left;padding:8px;">事例</th>
                        <th style="text-align:left;padding:8px;">タイトル</th>
                        <th style="text-align:right;padding:8px;">得点</th>
                        <th style="text-align:right;padding:8px;">得点率(%)</th>
                        <th style="text-align:right;padding:8px;">学習時間(分)</th>
                        <th style="text-align:center;padding:8px;">モード</th>
                        <th style="text-align:center;padding:8px;">設問数</th>
                      </tr>
                    </thead>
                    <tbody></tbody>
                  </table>
                </div>
                <script>
                  (function() {{
                    const doc = window.document;
                    const container = doc.getElementById('history-table');
                    if (!container) {{
                      return;
                    }}
                    const table = container.querySelector('table');
                    const tbody = table.querySelector('tbody');
                    const data = {table_json};
                    const selected = {selected_id};
                    tbody.innerHTML = '';
                    data.forEach((row) => {{
                      const tr = doc.createElement('tr');
                      tr.setAttribute('data-attempt', row.attempt_id);
                      const isSelected = selected && Number(selected) === Number(row.attempt_id);
                      tr.style.cursor = 'pointer';
                      tr.style.background = isSelected ? '#E6F2FF' : 'transparent';
                      const values = [
                        row['日付'] || '-',
                        row['年度'] || '-',
                        row['事例'] || '-',
                        row['タイトル'] || '-',
                        row['得点'] ?? '-',
                        row['得点率(%)'] ?? '-',
                        row['学習時間(分)'] ?? '-',
                        row['モード'] || '-',
                        row['設問数'] ?? '-'
                      ];
                      values.forEach((value, idx) => {{
                        const td = doc.createElement('td');
                        td.style.padding = '8px';
                        td.style.borderBottom = '1px solid #edf1f5';
                        if (idx >= 4 && idx <= 6) {{
                          td.style.textAlign = 'right';
                        }} else if (idx >= 7) {{
                          td.style.textAlign = 'center';
                        }} else {{
                          td.style.textAlign = 'left';
                        }}
                        td.textContent = value === null ? '-' : value;
                        tr.appendChild(td);
                      }});
                      tr.addEventListener('click', () => {{
                        window.parent.postMessage({{isStreamlitMessage: true, type: 'streamlit:setComponentValue', value: row.attempt_id}}, '*');
                      }});
                      tr.addEventListener('mouseover', () => {{
                        if (Number(row.attempt_id) !== Number(selected)) {{
                          tr.style.background = '#F0F4F8';
                        }}
                      }});
                      tr.addEventListener('mouseout', () => {{
                        if (Number(row.attempt_id) !== Number(selected)) {{
                          tr.style.background = 'transparent';
                        }}
                      }});
                      tbody.appendChild(tr);
                    }});
                  }})();
                </script>
                """)
                table_html = table_template.format(
                    table_json=table_json,
                    selected_id=selected_json,
                )
                table_event = components.html(table_html, height=360)
                if table_event is not None:
                    try:
                        st.session_state["history_selected_attempt"] = int(table_event)
                    except (TypeError, ValueError):
                        pass

            with detail_col:
                selected_attempt_id = st.session_state.get("history_selected_attempt")
                if selected_attempt_id is None:
                    st.info("表示する演習を選択してください。")
                else:
                    try:
                        detail_payload = database.fetch_attempt_detail(int(selected_attempt_id))
                    except Exception as exc:  # pragma: no cover
                        st.error(f"答案詳細を取得できませんでした: {exc}")
                    else:
                        answers = detail_payload["answers"]
                        st.markdown("#### 字数カウンタ")
                        total_chars = sum(len(ans.get("answer_text") or "") for ans in answers)
                        st.metric("総文字数", f"{total_chars}字")
                        st.caption("構成ガイド: 序論→課題整理／本論→提案／結論→効果・リスクを明確に。")
                        for answer in answers:
                            order = answer.get("question_order")
                            st.markdown(f"##### 第{order}問")
                            char_count = len(answer.get("answer_text") or "")
                            coverage = answer.get("keyword_coverage")
                            coverage_pct = (
                                f"{float(coverage) * 100:.1f}%" if coverage is not None else "-"
                            )
                            answer_cols = st.columns([2.5, 1.5, 1.2])
                            with answer_cols[0]:
                                st.markdown("**回答文**")
                                st.write(answer.get("answer_text") or "-")
                                st.caption(f"字数: {char_count}字")
                            with answer_cols[1]:
                                st.markdown("**講評**")
                                st.write(answer.get("feedback") or "講評データなし")
                            with answer_cols[2]:
                                st.markdown("**キーワード達成率**")
                                if coverage is not None:
                                    st.progress(min(max(float(coverage), 0.0), 1.0))
                                st.caption(f"網羅率: {coverage_pct}")
                                keyword_hits = answer.get("keyword_hits") or {}
                                if keyword_hits:
                                    matched = [kw for kw, hit in keyword_hits.items() if hit]
                                    missing = [kw for kw, hit in keyword_hits.items() if not hit]
                                    st.markdown(
                                        "<div style='font-size:0.85rem;'><strong>達成</strong>: "
                                        + ("、".join(map(escape, matched)) if matched else "-")
                                        + "<br><strong>不足</strong>: "
                                        + ("、".join(map(escape, missing)) if missing else "-")
                                        + "</div>",
                                        unsafe_allow_html=True,
                                    )
                                else:
                                    st.caption("キーワード情報なし")

    with tabs[1]:
        st.write("グラフタブ (Alt+2) ではホバーで数値を確認し、期間スライダーと連動します。")
        if filtered_history.empty:
            st.info("データなし。")
        else:
            chart_df = filtered_history.copy().sort_values("日付")
            chart_df["日付表示"] = chart_df["日付"].dt.strftime("%Y-%m-%d")
            with st.expander("得点と得点率の推移", expanded=True):
                score_chart = (
                    alt.Chart(chart_df)
                    .mark_line(point=True)
                    .encode(
                        x=alt.X("日付:T", title="日付"),
                        y=alt.Y("得点:Q", title="得点"),
                        color=alt.Color("事例:N", title="事例"),
                        tooltip=["日付表示", "得点", "得点率(%)", "タイトル", "モード"],
                    )
                    .properties(height=320)
                )
                ratio_chart = (
                    alt.Chart(chart_df)
                    .mark_area(opacity=0.3)
                    .encode(
                        x=alt.X("日付:T", title="日付"),
                        y=alt.Y("得点率(%)", title="得点率(%)"),
                        color=alt.Color("事例:N", legend=None),
                        tooltip=["日付表示", "得点率(%)", "タイトル"],
                    )
                    .properties(height=160)
                )
                st.altair_chart(score_chart, use_container_width=True)
                st.altair_chart(ratio_chart, use_container_width=True)
            with st.expander("モジュール別学習時間", expanded=False):
                if chart_df["学習時間(分)"].dropna().empty:
                    st.info("学習時間データなし")
                else:
                    time_df = chart_df.groupby("事例")["学習時間(分)"].sum().reset_index()
                    time_chart = (
                        alt.Chart(time_df)
                        .mark_bar()
                        .encode(
                            x=alt.X("学習時間(分):Q", title="学習時間(分)"),
                            y=alt.Y("事例:N", sort="-x"),
                            tooltip=["事例", alt.Tooltip("学習時間(分):Q", format=".1f")],
                        )
                        .properties(height=max(200, 40 * len(time_df)))
                    )
                    st.altair_chart(time_chart, use_container_width=True)
                    st.caption("棒にホバーすると該当モジュールの総学習時間を表示します。")

    with tabs[2]:
        st.write("分析レポート (Alt+3) ではPDCAカードとトレンドを確認します。")
        if filtered_history.empty:
            st.info("データなし。")
        else:
            working_df = filtered_history.copy()
            working_df["月"] = working_df["日付"].dt.to_period("M").dt.to_timestamp()
            working_df["週"] = working_df["日付"].dt.to_period("W").dt.start_time
            module_summary = working_df.groupby("事例").agg(
                演習回数=("attempt_id", "count"),
                平均得点率=("得点率(%)", "mean"),
                平均得点=("得点", "mean"),
                総学習時間=("学習時間(分)", "sum"),
            ).reset_index()
            module_summary["平均得点率"] = module_summary["平均得点率"].round(1)
            weekly_summary = (
                working_df.groupby(["週", "事例"])
                .agg(
                    平均得点率=("得点率(%)", "mean"),
                    平均得点=("得点", "mean"),
                )
                .reset_index()
            )
            insights = _generate_pdca_insights(module_summary, weekly_summary, working_df)
            with st.expander("PDCAハイライト", expanded=True):
                pdca_cols = st.columns(4)
                for col, (label, message) in zip(
                    pdca_cols,
                    [
                        ("Plan", insights.get("plan")),
                        ("Do", insights.get("do")),
                        ("Check", insights.get("check")),
                        ("Act", insights.get("act")),
                    ],
                ):
                    with col:
                        st.markdown(f"**{label}**")
                        st.write(message or "十分なデータがありません。")
            with st.expander("モジュール別サマリ", expanded=True):
                st.dataframe(
                    module_summary.rename(columns={"事例": "モジュール"}),
                    hide_index=True,
                    use_container_width=True,
                )
            layout_col1, layout_col2 = st.columns(2)
            with layout_col1:
                with st.expander("月次トレンド", expanded=False):
                    monthly = (
                        working_df.groupby(["月", "事例"])["得点率(%)"].mean().reset_index()
                    )
                    if monthly.empty:
                        st.info("月次データなし")
                    else:
                        monthly_chart = (
                            alt.Chart(monthly)
                            .mark_line(point=True)
                            .encode(
                                x=alt.X("月:T", title="月"),
                                y=alt.Y("得点率(%)", title="平均得点率"),
                                color="事例:N",
                                tooltip=["月", "事例", alt.Tooltip("得点率(%)", format=".1f")],
                            )
                        )
                        st.altair_chart(monthly_chart, use_container_width=True)
            with layout_col2:
                with st.expander("週次トレンド", expanded=False):
                    if weekly_summary.empty:
                        st.info("週次データなし")
                    else:
                        weekly_chart = (
                            alt.Chart(weekly_summary)
                            .mark_line(point=True)
                            .encode(
                                x=alt.X("週:T", title="週"),
                                y=alt.Y("平均得点率:Q", title="平均得点率"),
                                color="事例:N",
                                tooltip=["週", "事例", alt.Tooltip("平均得点率", format=".1f")],
                            )
                        )
                        st.altair_chart(weekly_chart, use_container_width=True)

    with tabs[3]:
        st.write("キーワード分析 (Alt+4) で網羅率と重要度を確認します。")
        if not filtered_keyword_records:
            if "keyword" in data_errors:
                st.error(f"キーワードデータの取得に失敗しました: {data_errors['keyword']}")
            else:
                st.info("データなし。")
        else:
            keyword_rows: List[Dict[str, Any]] = []
            for record in filtered_keyword_records:
                score = record.get("score")
                max_score = record.get("max_score")
                ratio = None
                if score is not None and max_score:
                    try:
                        ratio = float(score) / float(max_score)
                    except (TypeError, ValueError, ZeroDivisionError):
                        ratio = None
                keyword_hits = record.get("keyword_hits") or {}
                for keyword, hit in keyword_hits.items():
                    keyword_rows.append(
                        {
                            "keyword": keyword,
                            "hit": 1 if hit else 0,
                            "attempt_id": record.get("attempt_id"),
                            "score_ratio": ratio,
                            "case_label": record.get("case_label"),
                        }
                    )
            keyword_df = pd.DataFrame(keyword_rows)
            if keyword_df.empty:
                st.info("キーワード指標を算出できませんでした。")
            else:
                summary_df = (
                    keyword_df.groupby("keyword")
                    .agg(
                        出題回数=("attempt_id", "nunique"),
                        達成率=("hit", "mean"),
                        平均得点率=("score_ratio", "mean"),
                    )
                    .reset_index()
                )
                summary_df["重要度"] = summary_df["出題回数"] * summary_df["達成率"].fillna(0)
                scatter = (
                    alt.Chart(summary_df)
                    .mark_circle(size=120)
                    .encode(
                        x=alt.X("達成率:Q", title="達成率", scale=alt.Scale(domain=[0, 1])),
                        y=alt.Y("平均得点率:Q", title="平均得点率", scale=alt.Scale(domain=[0, 1])),
                        color=alt.Color("重要度:Q", scale=alt.Scale(scheme="blues")),
                        tooltip=[
                            "keyword",
                            alt.Tooltip("出題回数:Q", title="出題回数"),
                            alt.Tooltip("達成率:Q", title="達成率", format=".2f"),
                            alt.Tooltip("平均得点率:Q", title="平均得点率", format=".2f"),
                        ],
                    )
                    .properties(height=360)
                )
                st.altair_chart(scatter, use_container_width=True)
                st.dataframe(
                    summary_df.rename(columns={"keyword": "キーワード"}),
                    hide_index=True,
                    use_container_width=True,
                )
                focus_candidates = summary_df.sort_values("達成率").head(8)
                if not focus_candidates.empty:
                    cards = []
                    for _, row in focus_candidates.iterrows():
                        avg_ratio = row["平均得点率"]
                        cards.append(
                            f"<div style='min-width:180px;padding:12px;border-radius:12px;background:#f8fafc;border:1px solid #dde3ea;'>"
                            f"<strong>{escape(str(row['keyword']))}</strong><br>"
                            f"達成率: {row['達成率'] * 100:.1f}%<br>"
                            f"平均得点率: {avg_ratio * 100:.1f}%<br>"
                            "優先復習候補"
                            "</div>"
                        )
                    carousel_html = "<div style='display:flex;gap:12px;overflow-x:auto;padding-bottom:8px;'>" + "".join(cards) + "</div>"
                    st.markdown("#### 優先復習テーマ")
                    st.markdown(carousel_html, unsafe_allow_html=True)

    with tabs[4]:
        st.write("設問別分析 (Alt+5) で年度・タグ別の傾向を確認します。")
        if not question_history_summary:
            if "question" in data_errors:
                st.error(f"設問データの取得に失敗しました: {data_errors['question']}")
            else:
                st.info("データなし。")
        else:
            summary_df = pd.DataFrame(question_history_summary)
            summary_df["last_attempt_at"] = pd.to_datetime(summary_df["last_attempt_at"], errors="coerce")
            for column in ("themes", "tendencies", "topics", "skill_tags"):
                summary_df[column] = summary_df[column].apply(
                    lambda value: value if isinstance(value, list) else []
                )
            if selected_years:
                summary_df = summary_df[summary_df["year"].astype(str).isin(selected_years)]
            if selected_cases:
                summary_df = summary_df[summary_df["case_label"].astype(str).isin(selected_cases)]
            if selected_tags:
                summary_df = summary_df[
                    summary_df.apply(
                        lambda row: set(selected_tags).issubset(
                            set(row.get("themes", []))
                            | set(row.get("tendencies", []))
                            | set(row.get("topics", []))
                            | set(row.get("skill_tags", []))
                        ),
                        axis=1,
                    )
                ]
            if summary_df.empty:
                st.info("条件に一致する設問データがありません。")
            else:
                ratio_map = {
                    qid: metrics.get("avg_ratio")
                    for qid, metrics in global_question_metrics.items()
                }
                summary_df["平均得点率(%)"] = summary_df["avg_ratio"].map(
                    lambda v: f"{float(v) * 100:.1f}" if pd.notnull(v) else "-"
                )
                summary_df["平均得点"] = summary_df["avg_score"].map(
                    lambda v: f"{float(v):.1f}" if pd.notnull(v) else "-"
                )
                summary_df["全体平均得点率(%)"] = summary_df["question_id"].map(
                    lambda qid: f"{ratio_map.get(qid) * 100:.1f}" if ratio_map.get(qid) is not None else "-"
                )
                summary_df["直近実施日"] = summary_df["last_attempt_at"].dt.strftime("%Y-%m-%d")
                table_columns = [
                    "year",
                    "case_label",
                    "question_order",
                    "平均得点",
                    "平均得点率(%)",
                    "全体平均得点率(%)",
                    "best_score",
                    "attempt_count",
                    "直近実施日",
                ]
                st.dataframe(
                    summary_df[table_columns].rename(
                        columns={"year": "年度", "case_label": "事例", "question_order": "設問", "best_score": "最高得点", "attempt_count": "実施回数"}
                    ),
                    hide_index=True,
                    use_container_width=True,
                )
                st.caption("ヘッダーで並び替え可能。平均値が低い設問から重点復習を検討しましょう。")

    with tabs[5]:
        st.write("エクスポート (Alt+6) でCSV/PDFを取得します。")
        if filtered_history.empty:
            st.info("出力対象のデータがありません。")
        else:
            export_history = _prepare_history_log_export(filtered_history)
            answer_export = _prepare_answer_log_export(filtered_keyword_records)
            score_csv = export_history.to_csv(index=False).encode("utf-8-sig")
            answer_csv = (
                answer_export.to_csv(index=False).encode("utf-8-sig")
                if not answer_export.empty
                else None
            )
            archive_bytes = _build_learning_log_archive(score_csv, answer_csv)
            col_a, col_b, col_c = st.columns(3)
            with col_a:
                st.download_button(
                    "得点履歴CSV",
                    data=score_csv,
                    file_name="learning_history.csv",
                    mime="text/csv",
                )
            with col_b:
                if answer_csv is not None:
                    st.download_button(
                        "回答ログCSV",
                        data=answer_csv,
                        file_name="answer_history.csv",
                        mime="text/csv",
                    )
            with col_c:
                st.download_button(
                    "ZIP一括ダウンロード",
                    data=archive_bytes,
                    file_name="learning_history_bundle.zip",
                    mime="application/zip",
                )
            selected_attempt_id = st.session_state.get("history_selected_attempt")
            if selected_attempt_id:
                try:
                    attempt_detail = database.fetch_attempt_detail(int(selected_attempt_id))
                    attempt = attempt_detail["attempt"]
                    answers = attempt_detail["answers"]
                    problem = database.fetch_problem(attempt["problem_id"])
                    export_payload = export_utils.build_attempt_export_payload(
                        attempt,
                        answers,
                        problem or {},
                    )
                    pdf_bytes = export_utils.attempt_pdf_bytes(export_payload)
                    csv_bytes = export_utils.attempt_csv_bytes(export_payload)
                except Exception as exc:  # pragma: no cover
                    st.warning(f"選択演習のエクスポートに失敗しました: {exc}")
                else:
                    download_col1, download_col2 = st.columns(2)
                    with download_col1:
                        st.download_button(
                            "選択演習PDF",
                            data=pdf_bytes,
                            file_name=f"attempt_{selected_attempt_id}.pdf",
                            mime="application/pdf",
                        )
                    with download_col2:
                        st.download_button(
                            "選択演習CSV",
                            data=csv_bytes,
                            file_name=f"attempt_{selected_attempt_id}.csv",
                            mime="text/csv",
                        )
            if data_errors:
                with st.expander("取得時の警告", expanded=False):
                    for key, message in data_errors.items():
                        st.write(f"{key}: {message}")


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
        st.dataframe(plan_features, width="stretch", hide_index=True)

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
                - 不具合報告: support@example.com 宛に件名「バグ報告」でご連絡ください。再現手順やスクリーンショットの共有にご協力ください。
                - 利用規約: 準備中
                - 退会をご希望の場合はサポートまでご連絡ください。
                """
            ).strip()
        )
        st.caption("サポート窓口へのご連絡で24時間以内の返信を目安としています。")

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
            "過去問データファイルをアップロード (CSV/Excel/PDF/JSON)",
            type=["csv", "xlsx", "xls", "pdf", "json"],
            key="past_exam_uploader",
        )
        st.caption(
            "R6/R5 事例III原紙テンプレートを同梱し、自動分解の精度を高めています。PDFとJSONアップロードにも対応しています。"
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
                st.dataframe(preview_df, width="stretch", hide_index=True)

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
            st.dataframe(past_df.head(), width="stretch")
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
                    st.dataframe(summary_df, width="stretch", hide_index=True)
                    st.caption("年度・事例ごとの登録状況です。詳細解説や動画リンクの有無を確認できます。")
            tables = st.session_state.get("past_data_tables") or []
            if tables:
                with st.expander("抽出された数表", expanded=False):
                    for idx, table in enumerate(tables, start=1):
                        st.markdown(f"**数表 {idx}**")
                        st.dataframe(table, width="stretch")
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
                st.dataframe(context_df, width="stretch", hide_index=True)
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
                st.dataframe(question_df, width="stretch", hide_index=True)
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
            st.dataframe(pd.DataFrame(summary_rows), width="stretch", hide_index=True)
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
