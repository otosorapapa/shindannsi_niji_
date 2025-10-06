"""Scoring utilities for the Streamlit application."""
from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache
from typing import Dict, Iterable, List

import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity as skl_cosine_similarity

_TRANSFORMER_DISABLED = False


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


def semantic_similarity_score(answer: str, reference: str) -> float:
    """Compute semantic similarity with a transformer model when available.

    Falls back to TF-IDF cosine similarity when the optional dependency is
    unavailable or the model cannot be loaded (e.g. offline environment).
    """

    global _TRANSFORMER_DISABLED

    if _TRANSFORMER_DISABLED:
        return cosine_similarity_score(answer, reference)

    try:
        model = _get_sentence_transformer()
    except Exception:
        _TRANSFORMER_DISABLED = True
        return cosine_similarity_score(answer, reference)

    try:
        embeddings = model.encode([reference, answer])
        return float(skl_cosine_similarity([embeddings[0]], [embeddings[1]])[0][0])
    except Exception:
        _TRANSFORMER_DISABLED = True
        return cosine_similarity_score(answer, reference)


def score_answer(answer: str, question: QuestionSpec, *, method: str = "hybrid") -> ScoreResult:
    """Score a single answer using heuristics that mimic the AI workflow."""
    answer = answer.strip()
    if not answer:
        return ScoreResult(score=0.0, feedback="回答が入力されていません。", keyword_hits={})

    keyword_hits = keyword_match_score(answer, question.keywords)
    keyword_ratio = sum(keyword_hits.values()) / max(len(keyword_hits), 1)

    if method == "semantic":
        similarity = semantic_similarity_score(answer, question.model_answer)
        weight_keywords, weight_similarity = 0.4, 0.6
    else:
        similarity = semantic_similarity_score(answer, question.model_answer)
        weight_keywords, weight_similarity = 0.6, 0.4

    # Combine keyword ratio and similarity with simple weighting.
    raw_score = (weight_keywords * keyword_ratio + weight_similarity * similarity) * question.max_score
    score = round(min(question.max_score, max(0.0, raw_score)), 2)

    missing_keywords = [kw for kw, hit in keyword_hits.items() if not hit]
    comments: List[str] = []
    comments.append(f"類似度: {similarity:.2f} / キーワード網羅率: {keyword_ratio:.2f}")
    if missing_keywords:
        comments.append("不足キーワード: " + ", ".join(missing_keywords))
    else:
        comments.append("主要キーワードをすべて含めています。")

    feedback = "\n".join(comments)
    return ScoreResult(score=score, feedback=feedback, keyword_hits=keyword_hits)


def _normalize(text: str) -> str:
    text = text.lower()
    text = re.sub(r"\s+", "", text)
    return text


@lru_cache(maxsize=1)
def _get_sentence_transformer(model_name: str = "sentence-transformers/all-MiniLM-L6-v2"):
    """Lazily load a sentence-transformer model for semantic scoring."""
    from sentence_transformers import SentenceTransformer

    return SentenceTransformer(model_name)
