"""試験委員プロフィールを分析し、可視化用データを生成するユーティリティ。"""
from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

import json

import pandas as pd


DATA_PATH = Path("data/exam_committee_profiles.json")


def load_committee_dataset(path: Path = DATA_PATH) -> Dict[str, Any]:
    """Load committee profile dataset from JSON."""

    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return payload


def flatten_profiles(dataset: Dict[str, Any]) -> pd.DataFrame:
    """Return a flattened DataFrame of committee mappings."""

    profiles = dataset.get("profiles", [])
    rows: List[Dict[str, Any]] = []
    for profile in profiles:
        mappings = profile.get("mappings", []) or []
        for mapping in mappings:
            rows.append(
                {
                    "委員": profile.get("name", "不明"),
                    "役割": profile.get("role", ""),
                    "所属": profile.get("affiliation", ""),
                    "専門カテゴリ": mapping.get("domain", ""),
                    "事例": mapping.get("case", ""),
                    "重み": float(mapping.get("weight", 1.0)),
                    "テーマ": mapping.get("themes", []) or [],
                    "コメント": mapping.get("comment", ""),
                }
            )
    if not rows:
        return pd.DataFrame(columns=["委員", "役割", "所属", "専門カテゴリ", "事例", "重み", "テーマ", "コメント"])
    return pd.DataFrame(rows)


def aggregate_heatmap(df: pd.DataFrame) -> pd.DataFrame:
    """Aggregate committee mappings for heatmap visualisation."""

    if df.empty:
        return pd.DataFrame(columns=["専門カテゴリ", "事例", "重み", "委員数", "重点テーマ", "コメント"])

    grouped: Dict[tuple[str, str], Dict[str, Any]] = defaultdict(
        lambda: {"weight": 0.0, "members": set(), "themes": [], "comments": []}
    )
    for record in df.to_dict("records"):
        key = (record.get("専門カテゴリ", ""), record.get("事例", ""))
        entry = grouped[key]
        entry["weight"] += float(record.get("重み", 1.0))
        entry["members"].add(record.get("委員"))
        entry["themes"].extend(record.get("テーマ", []))
        comment = record.get("コメント")
        if comment:
            entry["comments"].append(comment)

    summary_rows: List[Dict[str, Any]] = []
    for (domain, case), values in grouped.items():
        themes_text = _summarise_list(values["themes"], limit=3)
        comment_text = _summarise_list(values["comments"], limit=2, separator=" / ")
        summary_rows.append(
            {
                "専門カテゴリ": domain,
                "事例": case,
                "重み": round(values["weight"], 2),
                "委員数": len(values["members"]),
                "重点テーマ": themes_text,
                "コメント": comment_text,
            }
        )

    summary_df = pd.DataFrame(summary_rows)
    summary_df.sort_values(by="重み", ascending=False, inplace=True)
    return summary_df.reset_index(drop=True)


def domain_order(summary_df: pd.DataFrame) -> List[str]:
    """Return ordered list of domains by weight for chart axes."""

    if summary_df.empty:
        return []
    return summary_df.sort_values("重み", ascending=False)["専門カテゴリ"].dropna().unique().tolist()


def focus_recommendations(summary_df: pd.DataFrame, limit: int = 5) -> List[Dict[str, Any]]:
    """Return top focus recommendations from aggregated data."""

    if summary_df.empty:
        return []
    items: List[Dict[str, Any]] = []
    for _, row in summary_df.head(limit).iterrows():
        themes = [theme.strip() for theme in (row.get("重点テーマ") or "").split("/") if theme.strip()]
        items.append(
            {
                "case": row.get("事例", ""),
                "domain": row.get("専門カテゴリ", ""),
                "weight": float(row.get("重み", 0)),
                "themes": themes,
                "comment": row.get("コメント", ""),
            }
        )
    return items


def cross_focus_highlights(dataset: Dict[str, Any], limit: int = 3) -> List[Dict[str, Any]]:
    """Return cross-case focus insights if provided in dataset."""

    entries = dataset.get("cross_focus", []) or []
    formatted: List[Dict[str, Any]] = []
    for entry in entries:
        formatted.append(
            {
                "label": entry.get("label", ""),
                "weight": float(entry.get("weight", 1.0)),
                "cases": entry.get("cases", []) or [],
                "domains": entry.get("domains", []) or [],
                "rationale": entry.get("rationale", ""),
                "study_list": entry.get("study_list", []) or [],
            }
        )
    formatted.sort(key=lambda item: item["weight"], reverse=True)
    return formatted[:limit]


def identify_primary_focus(dataset: Dict[str, Any], summary_df: pd.DataFrame) -> Optional[Dict[str, Any]]:
    """Identify the year's key focus theme from cross-focus or summary data."""

    cross_focus = cross_focus_highlights(dataset, limit=1)
    if cross_focus:
        entry = cross_focus[0]
        return {
            "label": entry["label"],
            "rationale": entry.get("rationale", ""),
            "study_list": entry.get("study_list", []),
            "weight": entry.get("weight", 0.0),
        }

    if summary_df.empty:
        return None

    top_row = summary_df.iloc[0]
    themes = [theme.strip() for theme in (top_row.get("重点テーマ") or "").split("/") if theme.strip()]
    return {
        "label": f"{top_row.get('専門カテゴリ', '')}（{top_row.get('事例', '')}）",
        "rationale": top_row.get("コメント", ""),
        "study_list": themes,
        "weight": float(top_row.get("重み", 0.0)),
    }


def _summarise_list(values: Iterable[str], *, limit: int, separator: str = " / ") -> str:
    unique: List[str] = []
    seen = set()
    for value in values:
        if not value:
            continue
        if value in seen:
            continue
        unique.append(str(value))
        seen.add(value)
        if len(unique) >= limit:
            break
    return separator.join(unique)

