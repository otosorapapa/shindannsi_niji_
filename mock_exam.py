"""Utilities for building mock exam sessions."""
from __future__ import annotations

import random
from dataclasses import dataclass
from datetime import datetime
from typing import Dict, List

import database


@dataclass
class MockExam:
    id: str
    title: str
    problem_ids: List[int]
    created_at: datetime


def available_mock_exams() -> List[MockExam]:
    """Return predefined mock exam options."""
    problems = database.list_problems()
    grouped: Dict[str, List[int]] = {}
    for problem in problems:
        key = f"{problem['year']}-{problem['case_label']}"
        grouped.setdefault(key, []).append(problem["id"])

    mock_sets = []
    if grouped:
        # Combine most recent four distinct cases if available.
        most_recent_ids = [row["id"] for row in problems[:4]]
        mock_sets.append(
            MockExam(
                id="full_recent",
                title="直近年度セット(事例I～IV)",
                problem_ids=most_recent_ids,
                created_at=datetime.utcnow(),
            )
        )

    return mock_sets


def random_mock_exam(size: int = 4) -> MockExam:
    problems = database.list_problems()
    problem_ids = [row["id"] for row in problems]
    selected = random.sample(problem_ids, min(size, len(problem_ids)))
    return MockExam(
        id="random",
        title="ランダム演習セット",
        problem_ids=selected,
        created_at=datetime.utcnow(),
    )
