"""Scoring utilities for the Streamlit application."""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Dict, Iterable, List, Literal

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


FeedbackLevel = Literal["high", "medium", "low"]


@dataclass
class FeedbackItem:
    """Structured feedback entry with an importance level."""

    message: str
    level: FeedbackLevel

    def to_dict(self) -> Dict[str, str]:
        return {"message": self.message, "level": self.level}


@dataclass
class ScoreResult:
    score: float
    feedback_summary: str
    keyword_hits: Dict[str, bool]
    keyword_counts: Dict[str, int]
    positives: List[FeedbackItem]
    negatives: List[FeedbackItem]
    advice: List[FeedbackItem]
    metrics: Dict[str, float]

    def to_payload(self) -> Dict:
        keywords = {}
        for kw in self.keyword_hits:
            keywords[kw] = {
                "hit": self.keyword_hits.get(kw, False),
                "count": self.keyword_counts.get(kw, 0),
            }
        for kw in self.keyword_counts:
            if kw not in keywords:
                keywords[kw] = {
                    "hit": self.keyword_hits.get(kw, False),
                    "count": self.keyword_counts.get(kw, 0),
                }
        return {
            "score": self.score,
            "summary": self.feedback_summary,
            "keywords": keywords,
            "positives": [item.to_dict() for item in self.positives],
            "negatives": [item.to_dict() for item in self.negatives],
            "advice": [item.to_dict() for item in self.advice],
            "metrics": self.metrics,
        }


def keyword_match_score(answer: str, keywords: Iterable[str]) -> Dict[str, Dict[str, int | bool]]:
    """Return a dictionary with hit flag and occurrence counts for each keyword."""

    stats: Dict[str, Dict[str, int | bool]] = {}
    normalized_answer = _normalize(answer)
    for keyword in keywords:
        pattern = _normalize(keyword)
        hit = pattern in normalized_answer
        count = normalized_answer.count(pattern) if pattern else 0
        stats[keyword] = {"hit": hit, "count": count}
    return stats


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
        keywords = list(question.keywords)
        keyword_hits = {kw: False for kw in keywords}
        keyword_counts = {kw: 0 for kw in keywords}
        return ScoreResult(
            score=0.0,
            feedback_summary="回答が入力されていません。",
            keyword_hits=keyword_hits,
            keyword_counts=keyword_counts,
            positives=[],
            negatives=[FeedbackItem(message="回答が入力されていません。", level="high")],
            advice=[FeedbackItem(message="設問要求に沿って骨子を作成し、まずは回答を入力しましょう。", level="high")],
            metrics={"similarity": 0.0, "keyword_coverage": 0.0},
        )

    keyword_stats = keyword_match_score(answer, question.keywords)
    keyword_hits = {kw: values["hit"] for kw, values in keyword_stats.items()}
    keyword_counts = {kw: values["count"] for kw, values in keyword_stats.items()}
    keyword_ratio = sum(keyword_hits.values()) / max(len(keyword_hits), 1)

    similarity = cosine_similarity_score(answer, question.model_answer)

    # Combine keyword ratio and similarity with simple weighting.
    raw_score = (0.6 * keyword_ratio + 0.4 * similarity) * question.max_score
    score = round(min(question.max_score, max(0.0, raw_score)), 2)

    missing_keywords = [kw for kw, hit in keyword_hits.items() if not hit]
    positives: List[FeedbackItem] = []
    negatives: List[FeedbackItem] = []
    advice: List[FeedbackItem] = []

    if keyword_ratio >= 0.8 and keyword_hits:
        positives.append(
            FeedbackItem(
                message=f"重要キーワードのうち {round(keyword_ratio * 100)}% をカバーできています。",
                level="high",
            )
        )
    elif keyword_ratio >= 0.5 and keyword_hits:
        positives.append(
            FeedbackItem(
                message="複数の重要キーワードに触れられています。", level="medium"
            )
        )
    elif keyword_hits:
        negatives.append(
            FeedbackItem(
                message="重要キーワードの網羅率が不足しています。", level="high"
            )
        )

    if similarity >= 0.7:
        positives.append(
            FeedbackItem(
                message="模範解答との論点一致度が高いです。", level="medium"
            )
        )
    elif similarity < 0.4:
        negatives.append(
            FeedbackItem(
                message="記述の方向性が模範解答とずれています。", level="medium"
            )
        )

    if score >= question.max_score * 0.8:
        positives.append(
            FeedbackItem(
                message="総合的に高得点帯に到達しています。", level="medium"
            )
        )
    elif score <= question.max_score * 0.4:
        negatives.append(
            FeedbackItem(
                message="得点が伸びていないため論点補強が必要です。", level="medium"
            )
        )

    if keyword_hits and missing_keywords:
        negatives.append(
            FeedbackItem(
                message="不足キーワード: " + "、".join(missing_keywords), level="high"
            )
        )
        for keyword in missing_keywords:
            advice.append(
                FeedbackItem(
                    message=f"『{keyword}』に関する施策や効果を明確に盛り込みましょう。",
                    level="high",
                )
            )
    elif keyword_hits:
        advice.append(
            FeedbackItem(
                message="主要キーワードはカバーできています。この調子で表現を磨きましょう。",
                level="low",
            )
        )

    if similarity < 0.6:
        advice.append(
            FeedbackItem(
                message="模範解答の構成を参考に、因果関係を明示すると説得力が高まります。",
                level="medium",
            )
        )

    comments: List[str] = [
        f"類似度: {similarity:.2f} / キーワード網羅率: {keyword_ratio:.2f}"
    ]
    if keyword_hits:
        if missing_keywords:
            comments.append("不足キーワード: " + ", ".join(missing_keywords))
        else:
            comments.append("主要キーワードをすべて含めています。")
    else:
        comments.append("キーワード設定がない設問のため、記述内容全体で評価しています。")

    metrics = {
        "similarity": round(similarity, 2),
        "keyword_coverage": round(keyword_ratio, 2),
    }

    feedback_summary = "\n".join(comments)
    return ScoreResult(
        score=score,
        feedback_summary=feedback_summary,
        keyword_hits=keyword_hits,
        keyword_counts=keyword_counts,
        positives=positives,
        negatives=negatives,
        advice=advice,
        metrics=metrics,
    )


def _normalize(text: str) -> str:
    text = text.lower()
    text = re.sub(r"\s+", "", text)
    return text
