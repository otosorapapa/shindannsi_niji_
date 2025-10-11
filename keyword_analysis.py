"""Utilities for natural language keyword analysis of past exam texts.

The module aggregates past question documents, tokenises Japanese text
with a lightweight regex-based segmenter, and surfaces keyword clouds
and frequently emphasised themes.  Outputs are returned as pandas
DataFrames so that Streamlit pages can visualise them flexibly.
"""
from __future__ import annotations

from collections import Counter
from functools import lru_cache
import math
import re
from typing import Dict, List, Optional

import numpy as np
import pandas as pd
from sklearn.feature_extraction.text import TfidfVectorizer

import database


_TOKEN_PATTERN = re.compile(r"[ぁ-んァ-ヶー一-龠A-Za-z0-9]+")
_WHITESPACE_PATTERN = re.compile(r"[\s\u3000]+")
_STOPWORDS = {
    "こと",
    "よう",
    "ため",
    "など",
    "もの",
    "これ",
    "それ",
    "あれ",
    "ので",
    "から",
    "そして",
    "しかし",
    "また",
    "一方",
    "今回",
    "企業",
    "顧客",
    "市場",
    "事例",
    "分析",
    "対応",
    "活用",
    "実施",
    "実現",
    "検討",
    "必要",
    "可能",
    "重要",
    "効果",
    "課題",
    "現状",
}


def _normalise_text(value: Optional[str]) -> str:
    if not value:
        return ""
    text = _WHITESPACE_PATTERN.sub(" ", str(value))
    return text.strip()


def _tokenise(text: str) -> List[str]:
    """Return keyword-sized tokens using a permissive regex."""

    if not text:
        return []
    tokens = [token for token in _TOKEN_PATTERN.findall(text) if len(token) >= 2]
    filtered = [token for token in tokens if token not in _STOPWORDS]
    return filtered


def _tokeniser_for_vectoriser(text: str) -> List[str]:
    return _tokenise(text)


def _safe_order(value: Optional[str]) -> float:
    if value is None:
        return -math.inf
    label = str(value).strip()
    if not label:
        return -math.inf
    label = label.replace("年度", "").replace("年", "")
    if label.startswith("令和"):
        tail = label.replace("令和", "")
        if tail == "元":
            numeric = 1
        else:
            try:
                numeric = int(tail)
            except ValueError:
                return -math.inf
        return 2018 + numeric
    if label.startswith("平成"):
        tail = label.replace("平成", "")
        if tail == "元":
            numeric = 1
        else:
            try:
                numeric = int(tail)
            except ValueError:
                return -math.inf
        return 1988 + numeric
    try:
        return float(label)
    except ValueError:
        return -math.inf


@lru_cache(maxsize=1)
def _load_question_corpus_cached() -> pd.DataFrame:
    problems = database.list_problems()
    rows: List[Dict[str, object]] = []
    for problem in problems:
        problem_id = problem.get("id")
        detail = database.fetch_problem(problem_id) if problem_id is not None else None
        payload = detail or problem
        if not payload:
            continue
        year = payload.get("year")
        case_label = payload.get("case_label")
        base_parts = [
            _normalise_text(payload.get("overview")),
            _normalise_text(payload.get("context_text") or payload.get("context")),
        ]
        base_text = " ".join(part for part in base_parts if part)
        questions = payload.get("questions") or []
        for question in questions:
            question_order = question.get("order") or question.get("question_order")
            text_parts = [
                base_text,
                _normalise_text(question.get("question_text")),
                _normalise_text(question.get("prompt")),
                _normalise_text(question.get("model_answer")),
                _normalise_text(question.get("explanation")),
                _normalise_text(question.get("detailed_explanation")),
                _normalise_text(question.get("question_intent")),
            ]
            combined = " ".join(part for part in text_parts if part)
            combined = _normalise_text(combined)
            if not combined:
                continue
            rows.append(
                {
                    "year": str(year) if year is not None else "",
                    "case_label": str(case_label) if case_label is not None else "",
                    "problem_id": problem_id,
                    "question_id": question.get("id"),
                    "question_order": question_order,
                    "text": combined,
                }
            )
    if not rows:
        return pd.DataFrame(columns=["year", "case_label", "problem_id", "question_id", "question_order", "text"])
    corpus = pd.DataFrame(rows)
    corpus.drop_duplicates(subset=["year", "case_label", "problem_id", "question_order"], inplace=True)
    corpus.reset_index(drop=True, inplace=True)
    return corpus


def load_question_corpus() -> pd.DataFrame:
    """Return a copy of the cached question corpus for analysis."""

    return _load_question_corpus_cached().copy()


def list_available_years(corpus: Optional[pd.DataFrame] = None) -> List[str]:
    """Return year labels sorted in descending order."""

    corpus = corpus.copy() if corpus is not None else load_question_corpus()
    if corpus.empty:
        return []
    working = corpus[["year"]].dropna().drop_duplicates()
    working["_order"] = working["year"].map(_safe_order)
    working.sort_values("_order", ascending=False, inplace=True)
    return working["year"].tolist()


def generate_keyword_cloud(
    corpus: pd.DataFrame,
    *,
    case_label: Optional[str] = None,
    top_n: int = 40,
    min_occurrence: int = 2,
) -> pd.DataFrame:
    """Return keyword frequencies suitable for word-cloud style charts."""

    if corpus.empty:
        return pd.DataFrame(columns=["keyword", "count", "weight", "case_label"])

    if case_label:
        working = corpus[corpus["case_label"] == case_label]
    else:
        working = corpus

    tokens = Counter()
    for text in working["text"]:
        tokens.update(_tokenise(text))

    if min_occurrence > 1:
        tokens = Counter({token: count for token, count in tokens.items() if count >= min_occurrence})

    if not tokens:
        return pd.DataFrame(columns=["keyword", "count", "weight", "case_label"])

    most_common = tokens.most_common(top_n)
    max_count = most_common[0][1] if most_common else 0
    rows = [
        {
            "keyword": keyword,
            "count": count,
            "weight": (count / max_count) if max_count else 0.0,
            "case_label": case_label or "全体",
        }
        for keyword, count in most_common
    ]
    return pd.DataFrame(rows)


def prepare_cloud_layout(cloud_df: pd.DataFrame, columns: int = 6) -> pd.DataFrame:
    """Add grid coordinates for visualising keyword clouds with Altair."""

    if cloud_df.empty:
        return cloud_df.copy()
    working = cloud_df.copy()
    working = working.sort_values("count", ascending=False).reset_index(drop=True)
    working["rank"] = working.index
    working["col"] = working["rank"] % columns
    working["row"] = working["rank"] // columns
    return working


def _compute_theme_summary(corpus: pd.DataFrame, top_n: int) -> Dict[str, pd.DataFrame]:
    if corpus.empty:
        empty = pd.DataFrame(columns=["keyword", "score"])
        return {"overall": empty, "by_case": {}}

    corpus = corpus.reset_index(drop=True)

    vectoriser = TfidfVectorizer(tokenizer=_tokeniser_for_vectoriser, token_pattern=None, lowercase=False)
    matrix = vectoriser.fit_transform(corpus["text"])
    feature_names = vectoriser.get_feature_names_out()

    overall_scores = np.asarray(matrix.mean(axis=0)).ravel()
    overall_indices = np.argsort(overall_scores)[::-1]

    overall_rows: List[Dict[str, object]] = []
    for idx in overall_indices[:top_n]:
        score = float(overall_scores[idx])
        if score <= 0:
            continue
        overall_rows.append({"keyword": feature_names[idx], "score": score})
    overall_df = pd.DataFrame(overall_rows, columns=["keyword", "score"])

    by_case: Dict[str, pd.DataFrame] = {}
    for case_label, group_indices in corpus.groupby("case_label").groups.items():
        if group_indices.empty:
            continue
        case_positions = group_indices.to_numpy(dtype=int, copy=False)
        case_matrix = matrix[case_positions]
        case_scores = np.asarray(case_matrix.mean(axis=0)).ravel()
        case_indices = np.argsort(case_scores)[::-1]
        case_rows: List[Dict[str, object]] = []
        for idx in case_indices[:top_n]:
            score = float(case_scores[idx])
            if score <= 0:
                continue
            case_rows.append(
                {
                    "keyword": feature_names[idx],
                    "score": score,
                    "case_label": case_label,
                }
            )
        if case_rows:
            by_case[case_label] = pd.DataFrame(case_rows, columns=["keyword", "score", "case_label"])

    return {"overall": overall_df, "by_case": by_case}


def generate_keyword_insights(
    *,
    corpus: Optional[pd.DataFrame] = None,
    recent_years: Optional[int] = None,
    top_n: int = 40,
    min_occurrence: int = 2,
    theme_top_n: int = 8,
) -> Dict[str, object]:
    """Return keyword cloud and theme summaries for the requested slice."""

    base_corpus = corpus.copy() if corpus is not None else load_question_corpus()
    available_years = list_available_years(base_corpus)

    selected_years: List[str]
    if recent_years and available_years:
        clamped = max(1, min(recent_years, len(available_years)))
        selected_years = available_years[:clamped]
    else:
        selected_years = available_years

    if selected_years:
        filtered = base_corpus[base_corpus["year"].isin(selected_years)].copy()
    else:
        filtered = base_corpus.copy()

    if filtered.empty:
        return {
            "cloud_overall": pd.DataFrame(columns=["keyword", "count", "weight", "case_label"]),
            "cloud_by_case": {},
            "themes_overall": pd.DataFrame(columns=["keyword", "score"]),
            "themes_by_case": {},
            "case_labels": [],
            "available_years": available_years,
            "selected_years": selected_years,
            "document_count": 0,
        }

    case_labels = (
        filtered["case_label"].dropna().astype(str).replace({"": None}).dropna().unique().tolist()
    )
    case_labels.sort()

    overall_cloud = generate_keyword_cloud(
        filtered,
        case_label=None,
        top_n=top_n,
        min_occurrence=min_occurrence,
    )
    case_clouds = {
        case: generate_keyword_cloud(
            filtered[filtered["case_label"] == case],
            case_label=case,
            top_n=top_n,
            min_occurrence=min_occurrence,
        )
        for case in case_labels
    }

    theme_summary = _compute_theme_summary(filtered, theme_top_n)

    return {
        "cloud_overall": overall_cloud,
        "cloud_by_case": case_clouds,
        "themes_overall": theme_summary["overall"],
        "themes_by_case": theme_summary["by_case"],
        "case_labels": case_labels,
        "available_years": available_years,
        "selected_years": selected_years,
        "document_count": int(filtered.shape[0]),
    }
