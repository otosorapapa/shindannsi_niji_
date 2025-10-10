"""Utilities to analyze question type frequencies for recent 中小企業診断士二次試験 cases."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Tuple

import pandas as pd

DATA_PATH = Path(__file__).resolve().parent / "data" / "question_type_history.csv"


@dataclass
class FrequencyResult:
    """Container for frequency analysis outputs."""

    frequency_table: pd.DataFrame
    sequence_counts: pd.DataFrame
    learning_order: Dict[str, List[str]]


def _parse_reiwa_year(year_label: str) -> int:
    """Convert a Japanese era label like '令和5年' into an integer for sorting."""

    if not isinstance(year_label, str):
        raise TypeError("year_label must be a string")
    normalized = year_label.strip().replace("年", "")
    if not normalized.startswith("令和"):
        raise ValueError(f"Unsupported era label: {year_label}")
    return int(normalized.replace("令和", ""))


def load_question_type_history(path: Path | None = None) -> pd.DataFrame:
    """Load the curated question type history dataset."""

    csv_path = path or DATA_PATH
    df = pd.read_csv(csv_path)
    df["year_value"] = df["year"].apply(_parse_reiwa_year)
    df = df.sort_values(["year_value", "case", "question_no"])
    return df


def _filter_recent_years(df: pd.DataFrame, recent_years: int) -> pd.DataFrame:
    recent_order = (
        df[["year", "year_value"]]
        .drop_duplicates()
        .sort_values("year_value", ascending=False)
        .head(recent_years)
    )
    return df[df["year"].isin(recent_order["year"])].copy()


def compute_frequency_table(df: pd.DataFrame, recent_years: int = 3) -> pd.DataFrame:
    """Compute a year-by-case-by-question-type frequency pivot table."""

    df_recent = _filter_recent_years(df, recent_years)
    grouped = (
        df_recent.groupby(["case", "question_type", "year"])
        .size()
        .reset_index(name="count")
    )
    pivot = grouped.pivot_table(
        index=["case", "question_type"],
        columns="year",
        values="count",
        fill_value=0,
        aggfunc="sum",
    )
    pivot["total"] = pivot.sum(axis=1)
    pivot = pivot.sort_values(["case", "total"], ascending=[True, False])
    return pivot


def compute_sequence_counts(df: pd.DataFrame, recent_years: int = 3) -> pd.DataFrame:
    """Count consecutive question-type transitions within each case and year."""

    df_recent = _filter_recent_years(df, recent_years)

    sequence_rows: List[Tuple[str, str, str]] = []
    for (year, case), group in df_recent.groupby(["year", "case"]):
        ordered_types = group.sort_values("question_no")["question_type"].tolist()
        for prev, nxt in zip(ordered_types, ordered_types[1:]):
            sequence_rows.append((case, prev, nxt))

    counts = (
        pd.DataFrame(sequence_rows, columns=["case", "prev_type", "next_type"])
        .value_counts()
        .reset_index(name="count")
        .sort_values("count", ascending=False)
    )
    return counts


def derive_learning_order(
    df: pd.DataFrame,
    recent_years: int = 3,
    min_sequence_count: int = 2,
) -> Dict[str, List[str]]:
    """Derive recommended learning order per case from frequency and sequence signals."""

    df_recent = _filter_recent_years(df, recent_years)
    freq_counts = (
        df_recent.groupby(["case", "question_type"])
        .size()
        .reset_index(name="frequency")
    )
    seq_counts = compute_sequence_counts(df_recent, recent_years)

    orders: Dict[str, List[str]] = {}
    for case, group in freq_counts.groupby("case"):
        sorted_types = group.sort_values("frequency", ascending=False)[
            "question_type"
        ].tolist()

        strong_sequences = seq_counts[
            (seq_counts["case"] == case) & (seq_counts["count"] >= min_sequence_count)
        ]

        for _, row in strong_sequences.iterrows():
            prev_type = row["prev_type"]
            next_type = row["next_type"]
            if prev_type not in sorted_types:
                sorted_types.append(prev_type)
            if next_type not in sorted_types:
                sorted_types.append(next_type)

            prev_idx = sorted_types.index(prev_type)
            next_idx = sorted_types.index(next_type)
            if prev_idx > next_idx:
                sorted_types.insert(next_idx, sorted_types.pop(prev_idx))

        orders[case] = sorted_types

    return orders


def analyze_question_types(recent_years: int = 3) -> FrequencyResult:
    """Run the full pipeline and return structured results."""

    df = load_question_type_history()
    frequency_table = compute_frequency_table(df, recent_years=recent_years)
    sequence_counts = compute_sequence_counts(df, recent_years=recent_years)
    learning_order = derive_learning_order(df, recent_years=recent_years)
    return FrequencyResult(
        frequency_table=frequency_table,
        sequence_counts=sequence_counts,
        learning_order=learning_order,
    )


def _format_learning_order(order_map: Dict[str, List[str]]) -> str:
    lines = []
    for case, types in order_map.items():
        bullet = " → ".join(types)
        lines.append(f"- {case}: {bullet}")
    return "\n".join(lines)


if __name__ == "__main__":
    result = analyze_question_types(recent_years=3)
    print("=== 直近3年×事例×設問タイプ 出現頻度 ===")
    print(result.frequency_table)
    print("\n=== 設問タイプ連鎖頻度 (上位) ===")
    print(result.sequence_counts.head(10))
    print("\n=== 推奨学習順序 ===")
    print(_format_learning_order(result.learning_order))
