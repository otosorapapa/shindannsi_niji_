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

    feedback = _build_feedback(
        answer=answer,
        similarity=similarity,
        keyword_ratio=keyword_ratio,
        missing_keywords=missing_keywords,
        question=question,
    )
    return ScoreResult(score=score, feedback=feedback, keyword_hits=keyword_hits)


def _normalize(text: str) -> str:
    text = text.lower()
    text = re.sub(r"\s+", "", text)
    return text


def _build_feedback(
    *,
    answer: str,
    similarity: float,
    keyword_ratio: float,
    missing_keywords: List[str],
    question: QuestionSpec,
) -> str:
    """Assemble multi-faceted feedback based on scoring metrics."""

    richness_label = _label_from_ratio(similarity, [0.35, 0.65], ("要改善", "おおむね良好", "優れています"))
    keyword_label = _label_from_ratio(
        keyword_ratio, [0.5, 0.85], ("不足気味", "概ね達成", "十分達成")
    )
    length_ratio = min(len(answer) / max(len(question.model_answer), 1), 1.0)
    length_label = _label_from_ratio(
        length_ratio, [0.55, 0.85], ("ボリューム不足", "適量", "十分な分量")
    )

    summary_section = [
        "【評価サマリー】",
        f"・内容の深さ: {richness_label} (類似度 {similarity:.2f})",
        f"・キーワード達成: {keyword_label} (網羅率 {keyword_ratio:.2f})",
        f"・文章量: {length_label} (参考文字数比 {length_ratio:.2f})",
    ]

    improvement_section = ["【改善アドバイス】"]
    if missing_keywords:
        improvement_section.append(
            "・以下のキーワードを盛り込み、論点を明確にしましょう: "
            + ", ".join(missing_keywords)
        )
    if similarity < 0.6:
        improvement_section.append(
            "・模範解答の構成を参考に、課題→施策→効果の順で整理すると論理性が高まります。"
        )
    if length_ratio < 0.55:
        improvement_section.append(
            "・根拠や具体例を1つ追加し、設問の要求文字数に近づけると評価が安定します。"
        )
    if not missing_keywords and similarity >= 0.6:
        improvement_section.append(
            "・主要論点は押さえられています。具体的な数値や事例を補うとさらに説得力が高まります。"
        )
    if len(improvement_section) == 1:
        improvement_section.append("・評価基準を十分に満たしています。この調子で練習を重ねましょう。")

    reference_points = _extract_reference_points(question.model_answer)
    reference_section = ["【参考回答の要点】"]
    reference_section.extend(reference_points)
    if len(reference_points) == 0:
        reference_section.append("・模範解答の要点は採点結果画面の解説をご確認ください。")

    return "\n".join(summary_section + [""] + improvement_section + [""] + reference_section)


def _label_from_ratio(value: float, thresholds: List[float], labels: Iterable[str]) -> str:
    """Return qualitative label for numeric value based on thresholds."""

    low, medium = thresholds
    low_label, medium_label, high_label = tuple(labels)
    if value < low:
        return low_label
    if value < medium:
        return medium_label
    return high_label


def _extract_reference_points(model_answer: str) -> List[str]:
    """Extract bullet style highlights from the reference answer."""

    candidates = re.split(r"[。．]\s*", model_answer)
    cleaned = [sentence.strip() for sentence in candidates if sentence.strip()]
    points = [f"・{sentence}。" for sentence in cleaned[:3]]
    return points
