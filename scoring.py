"""Scoring utilities for the Streamlit application."""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Dict, Iterable, List

import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer


@dataclass
class QuestionSpec:
    """Representation of a question used for scoring."""

    id: int
    prompt: str
    max_score: float
    model_answer: str
    keywords: Iterable[str]


@dataclass
class ScoreResult:
    score: float
    feedback: str
    keyword_hits: Dict[str, bool]


def keyword_match_score(answer: str, keywords: Iterable[str]) -> Dict[str, bool]:
    """Return a dictionary showing whether each keyword appears in the answer."""
    hits: Dict[str, bool] = {}
    normalized_answer = _normalize(answer)
    for keyword in keywords:
        pattern = _normalize(keyword)
        hits[keyword] = pattern in normalized_answer
    return hits


def cosine_similarity_score(answer: str, reference: str) -> float:
    """Compute cosine similarity between the answer and the model reference."""
    vectorizer = TfidfVectorizer(stop_words=None)
    try:
        tfidf = vectorizer.fit_transform([reference, answer])
    except ValueError:
        return 0.0
    matrix = tfidf.toarray()
    ref_vec, ans_vec = matrix[0], matrix[1]
    numerator = float(np.dot(ref_vec, ans_vec))
    denominator = float(np.linalg.norm(ref_vec) * np.linalg.norm(ans_vec))
    if denominator == 0:
        return 0.0
    return numerator / denominator


def score_answer(answer: str, question: QuestionSpec) -> ScoreResult:
    """Score a single answer using heuristics that mimic the AI workflow."""
    answer = answer.strip()
    if not answer:
        return ScoreResult(score=0.0, feedback="回答が入力されていません。", keyword_hits={})

    keyword_hits = keyword_match_score(answer, question.keywords)
    keyword_ratio = sum(keyword_hits.values()) / max(len(keyword_hits), 1)

    similarity = cosine_similarity_score(answer, question.model_answer)

    # Combine keyword ratio and similarity with simple weighting.
    raw_score = (0.6 * keyword_ratio + 0.4 * similarity) * question.max_score
    score = round(min(question.max_score, max(0.0, raw_score)), 2)

    missing_keywords = [kw for kw, hit in keyword_hits.items() if not hit]
    positive_points: List[str] = []
    if keyword_ratio >= 0.8:
        positive_points.append("主要キーワードをバランス良く押さえています。")
    elif keyword_ratio >= 0.4:
        positive_points.append(
            f"キーワードに{sum(keyword_hits.values())}件触れており、論点を一部捉えています。"
        )

    if similarity >= 0.65:
        positive_points.append("模範解答と主旨が近く、論理展開も概ね整っています。")
    elif similarity >= 0.45:
        positive_points.append("模範解答との方向性は合っています。表現を磨くとさらに良くなります。")

    if not positive_points:
        positive_points.append("自分の言葉で答案をまとめようとしている点は評価できます。")

    improvement_points: List[str] = []
    if missing_keywords:
        improvement_points.append("「" + "、".join(missing_keywords) + "」に触れると加点につながります。")
    if keyword_ratio < 0.4:
        improvement_points.append("解答内に重要キーワードが少ないため、設問要求を再確認しましょう。")
    if similarity < 0.45:
        improvement_points.append("模範解答と論点がずれている可能性があります。因果関係を意識した構成を意識してください。")
    if not improvement_points:
        improvement_points.append("細部の表現を磨くと、より説得力の高い答案になります。")

    if missing_keywords:
        study_keywords = list(missing_keywords)
    else:
        study_keywords = list(question.keywords)

    improvement_suggestion = "設問文から与件企業の課題・強みを抜き出し、キーワードを盛り込んだうえで因果を意識して記述しましょう。"

    feedback_sections = [
        f"【得点サマリー】類似度: {similarity:.2f} / キーワード網羅率: {keyword_ratio:.2f}",
        "【良かった点】\n" + "\n".join(f"- {point}" for point in positive_points),
        "【改善が必要な点】\n" + "\n".join(f"- {point}" for point in improvement_points),
        "【学習すべきキーワード】\n" + "\n".join(f"- {kw}" for kw in study_keywords) if study_keywords else "",
        "【改善のヒント】\n- " + improvement_suggestion,
    ]

    feedback = "\n\n".join(section for section in feedback_sections if section)
    return ScoreResult(score=score, feedback=feedback, keyword_hits=keyword_hits)


def _normalize(text: str) -> str:
    text = text.lower()
    text = re.sub(r"\s+", "", text)
    return text
