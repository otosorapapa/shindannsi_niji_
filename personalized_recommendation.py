"""Utilities to generate personalised learning recommendations.

The module analyses stored attempts and keyword performance to infer
weak areas for each learner.  A lightweight collaborative filtering
approach is used to suggest the next problems to tackle, and question
and reference suggestions are derived from recorded keyword misses.
"""
from __future__ import annotations

import html
import math
from collections import Counter
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence, Tuple

import pandas as pd

import database


@dataclass
class RecommendationContext:
    """Metadata describing how the recommendation set was produced."""

    has_personal_history: bool
    neighbour_count: int
    mode: str
    message: str


def generate_personalised_learning_plan(
    user_id: int,
    *,
    attempts: Sequence[Dict[str, Any]],
    problem_catalog: Optional[Sequence[Dict[str, Any]]] = None,
    keyword_resource_map: Optional[Dict[str, Sequence[Dict[str, str]]]] = None,
    default_resources: Optional[Sequence[Dict[str, str]]] = None,
    top_problem_limit: int = 5,
    top_question_limit: int = 5,
    top_resource_limit: int = 5,
) -> Dict[str, Any]:
    """Return a bundle of personalised learning recommendations.

    Parameters
    ----------
    user_id:
        Identifier of the learner for whom recommendations should be
        generated.
    attempts:
        Attempt rows for the learner, typically obtained from
        :func:`database.list_attempts`.
    problem_catalog:
        Optional list of problem metadata.  When omitted, the catalog is
        fetched via :func:`database.list_problems`.
    keyword_resource_map / default_resources:
        Mapping of important keywords to external references and the
        default list of study resources.  These are used to surface
        supporting materials when weaknesses are detected.
    top_problem_limit / top_question_limit / top_resource_limit:
        Limits for each recommendation bucket.
    """

    problem_catalog = list(problem_catalog or database.list_problems())
    catalog_lookup = {item["id"]: item for item in problem_catalog if "id" in item}

    rating_records = database.fetch_all_attempt_scores()
    keyword_records = database.fetch_keyword_performance(user_id)

    rating_df = _prepare_rating_frame(rating_records)
    user_attempt_df = rating_df[rating_df["user_id"] == user_id]
    has_history = not user_attempt_df.empty

    neighbours: List[Tuple[int, float]] = []
    personalised_candidates: List[Dict[str, Any]] = []
    global_stats = _compute_problem_statistics(rating_df)

    if has_history:
        matrix = _build_user_problem_matrix(rating_df)
        if user_id in matrix.index:
            neighbours = _compute_user_neighbours(matrix, user_id)
            personalised_candidates = _predict_unseen_problems(
                matrix,
                user_id,
                neighbours,
                global_stats,
                catalog_lookup,
                limit=top_problem_limit,
            )

    weak_history_candidates = _extract_weak_attempts(
        attempts,
        global_stats,
        catalog_lookup,
        limit=top_problem_limit,
    )

    problem_recommendations = _merge_problem_recommendations(
        weak_history_candidates,
        personalised_candidates,
        limit=top_problem_limit,
    )

    question_recommendations = _derive_question_recommendations(
        keyword_records, limit=top_question_limit
    )

    resource_recommendations = _derive_resource_recommendations(
        question_recommendations,
        keyword_resource_map=keyword_resource_map or {},
        default_resources=default_resources or [],
        limit=top_resource_limit,
    )

    context = RecommendationContext(
        has_personal_history=has_history,
        neighbour_count=len(neighbours),
        mode="personalised" if has_history else "cold_start",
        message=_build_status_message(has_history, neighbours, len(problem_recommendations)),
    )

    return {
        "problem_recommendations": problem_recommendations,
        "question_recommendations": question_recommendations,
        "resource_recommendations": resource_recommendations,
        "context": context,
    }


def _prepare_rating_frame(records: Sequence[Dict[str, Any]]) -> pd.DataFrame:
    df = pd.DataFrame(records or [])
    if df.empty:
        return pd.DataFrame(
            columns=[
                "user_id",
                "problem_id",
                "total_score",
                "total_max_score",
                "score_ratio",
                "year",
                "case_label",
                "title",
                "submitted_at",
            ]
        )

    df = df.copy()
    df["total_score"] = pd.to_numeric(df.get("total_score"), errors="coerce")
    df["total_max_score"] = pd.to_numeric(df.get("total_max_score"), errors="coerce")
    df["score_ratio"] = df.apply(
        lambda row: (row["total_score"] / row["total_max_score"])
        if row.get("total_max_score")
        else math.nan,
        axis=1,
    )
    df["score_ratio"] = df["score_ratio"].clip(lower=0.0, upper=1.0)
    return df


def _build_user_problem_matrix(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame()
    matrix = df.pivot_table(
        index="user_id",
        columns="problem_id",
        values="score_ratio",
        aggfunc="mean",
    )
    return matrix


def _compute_user_neighbours(
    matrix: pd.DataFrame, user_id: int, *, min_overlap: int = 1
) -> List[Tuple[int, float]]:
    if user_id not in matrix.index:
        return []

    target_row = matrix.loc[user_id]
    target_mean = target_row.mean(skipna=True)
    neighbours: List[Tuple[int, float]] = []

    for other_user, row in matrix.drop(index=user_id, errors="ignore").iterrows():
        mask = target_row.notna() & row.notna()
        if mask.sum() < min_overlap:
            continue
        target_centered = target_row[mask] - target_mean
        other_mean = row.mean(skipna=True)
        other_centered = row[mask] - other_mean
        similarity = _cosine_similarity(target_centered.tolist(), other_centered.tolist())
        if similarity is None or similarity <= 0:
            continue
        neighbours.append((other_user, similarity))

    neighbours.sort(key=lambda item: item[1], reverse=True)
    return neighbours[:20]


def _cosine_similarity(vec_a: Sequence[float], vec_b: Sequence[float]) -> Optional[float]:
    if not vec_a or not vec_b or len(vec_a) != len(vec_b):
        return None
    dot = sum(a * b for a, b in zip(vec_a, vec_b))
    norm_a = math.sqrt(sum(a * a for a in vec_a))
    norm_b = math.sqrt(sum(b * b for b in vec_b))
    if norm_a == 0 or norm_b == 0:
        return None
    return dot / (norm_a * norm_b)


def _compute_problem_statistics(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame(
            columns=["problem_id", "mean_ratio", "attempt_count", "year", "case_label", "title"]
        )
    stats = (
        df.dropna(subset=["score_ratio"])
        .groupby(["problem_id", "year", "case_label", "title"], dropna=False)["score_ratio"]
        .agg(["mean", "count"])
        .reset_index()
    )
    stats.rename(columns={"mean": "mean_ratio", "count": "attempt_count"}, inplace=True)
    return stats


def _predict_unseen_problems(
    matrix: pd.DataFrame,
    user_id: int,
    neighbours: Sequence[Tuple[int, float]],
    global_stats: pd.DataFrame,
    catalog_lookup: Dict[Any, Dict[str, Any]],
    *,
    limit: int,
) -> List[Dict[str, Any]]:
    if user_id not in matrix.index or not neighbours:
        return []

    target_row = matrix.loc[user_id]
    target_mean = target_row.mean(skipna=True)
    if math.isnan(target_mean):
        target_mean = float(global_stats["mean_ratio"].mean()) if not global_stats.empty else 0.0

    problem_means = {
        row["problem_id"]: row["mean_ratio"] for _, row in global_stats.iterrows()
    }

    candidate_ids = [
        problem_id
        for problem_id, value in target_row.items()
        if pd.isna(value)
    ]

    scored: List[Tuple[int, float, float]] = []
    for problem_id in candidate_ids:
        numerator = 0.0
        denominator = 0.0
        for neighbour_id, similarity in neighbours:
            neighbour_value = matrix.at[neighbour_id, problem_id] if problem_id in matrix.columns else math.nan
            if pd.isna(neighbour_value):
                continue
            neighbour_mean = matrix.loc[neighbour_id].mean(skipna=True)
            numerator += similarity * (neighbour_value - neighbour_mean)
            denominator += abs(similarity)

        global_mean = problem_means.get(problem_id, float(global_stats["mean_ratio"].mean()) if not global_stats.empty else 0.0)
        if denominator == 0:
            predicted = (target_mean + global_mean) / 2 if target_mean else global_mean
        else:
            predicted = target_mean + numerator / denominator

        predicted = max(0.0, min(1.0, float(predicted)))
        difficulty = 1.0 - global_mean if global_mean is not None else 0.0
        priority = 0.6 * (1.0 - predicted) + 0.4 * difficulty
        scored.append((problem_id, predicted, priority))

    scored.sort(key=lambda item: item[2], reverse=True)

    recommendations: List[Dict[str, Any]] = []
    for problem_id, predicted, priority in scored[:limit]:
        metadata = catalog_lookup.get(problem_id, {})
        recommendations.append(
            {
                "problem_id": problem_id,
                "year": metadata.get("year"),
                "case_label": metadata.get("case_label"),
                "title": metadata.get("title"),
                "predicted_ratio": predicted,
                "priority": priority,
                "type": "explore",
                "reason": _format_prediction_reason(predicted, global_stats, problem_id),
            }
        )

    return recommendations


def _format_prediction_reason(
    predicted: float, global_stats: pd.DataFrame, problem_id: Any
) -> str:
    if global_stats.empty:
        return f"推定得点率 {predicted * 100:.0f}%"
    row = global_stats.loc[global_stats["problem_id"] == problem_id]
    if row.empty:
        return f"推定得点率 {predicted * 100:.0f}%"
    global_mean = float(row.iloc[0]["mean_ratio"])
    attempt_count = int(row.iloc[0]["attempt_count"])
    return (
        f"推定得点率 {predicted * 100:.0f}% / 全体平均 {global_mean * 100:.0f}%"
        f"（{attempt_count}件の履歴を参照）"
    )


def _extract_weak_attempts(
    attempts: Sequence[Dict[str, Any]],
    global_stats: pd.DataFrame,
    catalog_lookup: Dict[Any, Dict[str, Any]],
    *,
    limit: int,
) -> List[Dict[str, Any]]:
    if not attempts:
        return []

    attempt_entries: List[Tuple[int, float, Dict[str, Any]]] = []
    for attempt in attempts:
        total_score = attempt.get("total_score")
        total_max = attempt.get("total_max_score")
        if not total_max:
            continue
        try:
            ratio = float(total_score or 0) / float(total_max)
        except ZeroDivisionError:
            continue
        if ratio >= 0.7:
            continue
        problem_id = attempt.get("problem_id")
        metadata = catalog_lookup.get(problem_id, {})
        row = global_stats.loc[global_stats["problem_id"] == problem_id]
        global_mean = float(row.iloc[0]["mean_ratio"]) if not row.empty else None
        entry = {
            "problem_id": problem_id,
            "year": attempt.get("year") or metadata.get("year"),
            "case_label": attempt.get("case_label") or metadata.get("case_label"),
            "title": attempt.get("title") or metadata.get("title"),
            "score_ratio": ratio,
            "type": "review",
            "reason": _format_review_reason(ratio, global_mean),
        }
        attempt_entries.append((problem_id, ratio, entry))

    attempt_entries.sort(key=lambda item: item[1])

    recommendations: List[Dict[str, Any]] = []
    seen_problems = set()
    for problem_id, _ratio, entry in attempt_entries:
        if problem_id in seen_problems:
            continue
        recommendations.append(entry)
        seen_problems.add(problem_id)
        if len(recommendations) >= limit:
            break

    return recommendations


def _format_review_reason(ratio: float, global_mean: Optional[float]) -> str:
    base = f"得点率 {ratio * 100:.0f}%"
    if global_mean is None or math.isnan(global_mean):
        return f"復習推奨: {base}"
    return f"復習推奨: {base} / 全体平均 {global_mean * 100:.0f}%"


def _merge_problem_recommendations(
    review_items: Sequence[Dict[str, Any]],
    explore_items: Sequence[Dict[str, Any]],
    *,
    limit: int,
) -> List[Dict[str, Any]]:
    merged: List[Dict[str, Any]] = []
    seen = set()

    for item in review_items:
        key = item.get("problem_id")
        if key in seen:
            continue
        merged.append(item)
        seen.add(key)

    for item in explore_items:
        key = item.get("problem_id")
        if key in seen:
            continue
        merged.append(item)
        seen.add(key)
        if len(merged) >= limit:
            break

    return merged[:limit]


def _derive_question_recommendations(
    keyword_records: Sequence[Dict[str, Any]], *, limit: int
) -> List[Dict[str, Any]]:
    if not keyword_records:
        return []

    candidates: List[Tuple[float, Dict[str, Any]]] = []
    for record in keyword_records:
        max_score = record.get("max_score")
        score = record.get("score")
        if not max_score:
            score_ratio = None
        else:
            try:
                score_ratio = float(score or 0) / float(max_score)
            except ZeroDivisionError:
                score_ratio = None

        keyword_hits = record.get("keyword_hits") or {}
        total_keywords = len(keyword_hits)
        coverage_ratio = None
        if total_keywords:
            coverage_ratio = sum(1 for hit in keyword_hits.values() if hit) / total_keywords

        weakness_score = _calculate_question_weakness(score_ratio, coverage_ratio)
        if weakness_score <= 0:
            continue

        missing_keywords = [kw for kw, hit in keyword_hits.items() if not hit]
        candidates.append(
            (
                weakness_score,
                {
                    "question_id": record.get("question_id"),
                    "year": record.get("year"),
                    "case_label": record.get("case_label"),
                    "prompt": record.get("prompt"),
                    "score_ratio": score_ratio,
                    "coverage_ratio": coverage_ratio,
                    "missing_keywords": missing_keywords,
                    "reason": _format_question_reason(score_ratio, coverage_ratio),
                },
            )
        )

    if not candidates:
        return []

    candidates.sort(key=lambda item: item[0], reverse=True)

    results: List[Dict[str, Any]] = []
    seen_ids = set()
    for _score, entry in candidates:
        key = entry.get("question_id") or (
            entry.get("year"),
            entry.get("case_label"),
            entry.get("prompt"),
        )
        if key in seen_ids:
            continue
        results.append(entry)
        seen_ids.add(key)
        if len(results) >= limit:
            break

    return results


def _calculate_question_weakness(
    score_ratio: Optional[float], coverage_ratio: Optional[float]
) -> float:
    values: List[float] = []
    if score_ratio is not None:
        values.append(1.0 - max(0.0, min(1.0, score_ratio)))
    if coverage_ratio is not None:
        values.append(1.0 - max(0.0, min(1.0, coverage_ratio)))
    if not values:
        return 0.0
    return sum(values) / len(values)


def _format_question_reason(
    score_ratio: Optional[float], coverage_ratio: Optional[float]
) -> str:
    parts: List[str] = []
    if score_ratio is not None:
        parts.append(f"得点率 {score_ratio * 100:.0f}%")
    if coverage_ratio is not None:
        parts.append(f"キーワード網羅 {coverage_ratio * 100:.0f}%")
    return " / ".join(parts) if parts else "復習推奨"


def _derive_resource_recommendations(
    question_recommendations: Sequence[Dict[str, Any]],
    *,
    keyword_resource_map: Dict[str, Sequence[Dict[str, str]]],
    default_resources: Sequence[Dict[str, str]],
    limit: int,
) -> List[Dict[str, Any]]:
    keyword_counter: Counter[str] = Counter()
    for entry in question_recommendations:
        for keyword in entry.get("missing_keywords") or []:
            keyword_counter[keyword] += 1

    resources: List[Dict[str, Any]] = []
    for keyword, frequency in keyword_counter.most_common():
        candidates = keyword_resource_map.get(keyword, [])
        for candidate in candidates:
            resources.append(
                {
                    "keyword": keyword,
                    "label": candidate.get("label"),
                    "url": candidate.get("url"),
                    "reason": f"{keyword}の強化（{frequency}件で不足）",
                }
            )
        if len(resources) >= limit:
            break

    if len(resources) < limit:
        for resource in default_resources:
            key = (resource.get("label"), resource.get("url"))
            if any((item.get("label"), item.get("url")) == key for item in resources):
                continue
            resources.append(
                {
                    "keyword": None,
                    "label": resource.get("label"),
                    "url": resource.get("url"),
                    "reason": "定番リソース",
                }
            )
            if len(resources) >= limit:
                break

    return resources[:limit]


def _build_status_message(
    has_history: bool, neighbours: Sequence[Tuple[int, float]], recommendation_count: int
) -> str:
    if not has_history:
        return "初回学習データを蓄積すると、弱点に基づいた推薦が表示されます。"
    if not neighbours:
        return "学習履歴は分析済みですが類似学習者が少ないため、直近の弱点を中心に提示しています。"
    if recommendation_count == 0:
        return "弱点は見つかりませんでした。最新の演習結果で継続的に更新されます。"
    return "類似学習者の行動を踏まえて次の一手を提案しています。"


def format_recommendation_summary(entry: Dict[str, Any]) -> str:
    """Return a human readable summary for a problem recommendation."""

    year = entry.get("year") or "―"
    case_label = entry.get("case_label") or "―"
    title = entry.get("title") or ""
    label = f"{html.escape(str(year))} {html.escape(str(case_label))}".strip()
    if title:
        label = f"{label} — {html.escape(str(title))}"
    return label

