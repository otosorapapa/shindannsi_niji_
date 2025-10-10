"""Utilities for building mock exam sessions."""
from __future__ import annotations

import random
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List

import database


@dataclass
class MockExam:
    id: str
    title: str
    problem_ids: List[int]
    created_at: datetime
    notices: List[str] = field(default_factory=list)
    timetable: List[Dict[str, str]] = field(default_factory=list)
    case_guides: List[Dict[str, object]] = field(default_factory=list)


def available_mock_exams() -> List[MockExam]:
    """Return predefined mock exam options."""
    problems = database.list_problems()
    mock_sets: List[MockExam] = []

    # 本番セット（R6）
    r6_case_refs = [
        ("令和6年", "事例I"),
        ("令和6年", "事例II"),
        ("令和6年", "事例III"),
        ("令和6年", "事例IV"),
    ]
    r6_problem_ids: List[int] = []
    for year, case_label in r6_case_refs:
        problem = database.fetch_problem_by_year_case(year, case_label)
        if not problem:
            break
        r6_problem_ids.append(problem["id"])
    if len(r6_problem_ids) == len(r6_case_refs):
        mock_sets.append(
            MockExam(
                id="r6_full",
                title="本番セット（R6）",
                problem_ids=r6_problem_ids,
                created_at=datetime.utcnow(),
                notices=[
                    "試験時間は各事例80分です。試験監督の指示があるまで問題冊子を開かないでください。",
                    "解答は必ず各設問の解答欄に記入してください。枠外・余白の記述は採点されません。",
                    "問題冊子にはメモを書き込めますが、鉛筆もしくはシャープペンシルで記入し、提出時には机の上を整理してください。",
                ],
                timetable=[
                    {"slot": "事例I（組織・人事）", "time": "9:40～11:00", "detail": "試験時間80分"},
                    {"slot": "休憩", "time": "11:00～11:20", "detail": "答案回収後20分"},
                    {"slot": "事例II（マーケティング）", "time": "11:20～12:40", "detail": "試験時間80分"},
                    {"slot": "昼休憩", "time": "12:40～13:40", "detail": "昼食・移動は静粛に"},
                    {"slot": "事例III（生産・オペレーション）", "time": "13:40～15:00", "detail": "試験時間80分"},
                    {"slot": "休憩", "time": "15:00～15:20", "detail": "答案回収後20分"},
                    {"slot": "事例IV（財務・会計）", "time": "15:20～16:40", "detail": "試験時間80分"},
                ],
                case_guides=[
                    {
                        "case_label": "事例I",
                        "focus": "組織・人事",
                        "format": [
                            "問題冊子は与件文4ページ・設問2ページ構成。",
                            "解答用紙は第1問～第4問の4枠。各枠80字～120字の指定。",
                        ],
                        "notes": [
                            "結論→理由→効果の順で因果を明示する。",
                            "経営戦略と人材活用の整合性を意識し、強み・課題を明確にする。",
                        ],
                    },
                    {
                        "case_label": "事例II",
                        "focus": "マーケティング・流通",
                        "format": [
                            "BtoCサービス事例。顧客ニーズ・チャネル分析を踏まえて80～100字で記述。",
                            "解答欄は第1問～第4問の4枠。",
                        ],
                        "notes": [
                            "ターゲット・提供価値・施策・効果をセットで記述する。",
                            "強みを活かした差別化と実行プロセスまで落とし込む。",
                        ],
                    },
                    {
                        "case_label": "事例III",
                        "focus": "生産・オペレーション",
                        "format": [
                            "現場改善テーマ。設問ごとに60～120字指定。",
                            "ガントチャートと工程図が添付された前提で進捗・負荷を言及。",
                        ],
                        "notes": [
                            "制約条件を踏まえた工程設計・情報共有・人材育成を因果で示す。",
                            "現状分析→課題→対策→効果まで一貫させる。",
                        ],
                    },
                    {
                        "case_label": "事例IV",
                        "focus": "財務・会計",
                        "format": [
                            "計算問題＋記述問題構成。与件の財務諸表は別紙。",
                            "解答欄は数値記入欄と記述欄の混在。指標単位・小数処理に注意。",
                        ],
                        "notes": [
                            "計算過程は答案欄に記入。指標名と判断理由をセットで述べる。",
                            "投資意思決定はNPV・回収期間・感度分析など複数視点で説明。",
                        ],
                    },
                ],
            )
        )

    if problems:
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
