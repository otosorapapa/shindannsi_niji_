"""Database utilities for the 中小企業診断士二次試験対策アプリ.

This module wraps the SQLite storage that backs the Streamlit application.
It provides helper functions to initialise the schema, seed the database with
sample problems and interact with persisted learning data such as attempts and
scores.
"""
from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

DB_PATH = Path("data/app.db")
SEED_PATH = Path("data/seed_problems.json")


def get_connection() -> sqlite3.Connection:
    """Return a SQLite connection with row factory configured."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def initialize_database() -> None:
    """Create the SQLite database (if necessary) and seed master data."""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)

    conn = get_connection()
    cur = conn.cursor()

    cur.executescript(
        """
        PRAGMA foreign_keys = ON;

        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT UNIQUE NOT NULL,
            name TEXT NOT NULL,
            password_hash TEXT,
            plan TEXT NOT NULL DEFAULT 'free',
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS problems (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            year TEXT NOT NULL,
            case_label TEXT NOT NULL,
            title TEXT NOT NULL,
            overview TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS questions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            problem_id INTEGER NOT NULL REFERENCES problems(id) ON DELETE CASCADE,
            question_order INTEGER NOT NULL,
            prompt TEXT NOT NULL,
            character_limit INTEGER,
            max_score REAL NOT NULL,
            model_answer TEXT NOT NULL,
            explanation TEXT NOT NULL,
            keywords_json TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS attempts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            problem_id INTEGER NOT NULL REFERENCES problems(id) ON DELETE CASCADE,
            mode TEXT NOT NULL,
            started_at TEXT NOT NULL,
            submitted_at TEXT,
            duration_seconds INTEGER,
            total_score REAL,
            total_max_score REAL
        );

        CREATE TABLE IF NOT EXISTS attempt_answers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            attempt_id INTEGER NOT NULL REFERENCES attempts(id) ON DELETE CASCADE,
            question_id INTEGER NOT NULL REFERENCES questions(id) ON DELETE CASCADE,
            answer_text TEXT NOT NULL,
            score REAL,
            feedback TEXT,
            keyword_hits_json TEXT
        );

        CREATE TABLE IF NOT EXISTS explanation_library (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            attempt_id INTEGER NOT NULL REFERENCES attempts(id) ON DELETE CASCADE,
            question_id INTEGER NOT NULL REFERENCES questions(id) ON DELETE CASCADE,
            summary TEXT NOT NULL,
            feedback TEXT NOT NULL,
            focus_keywords_json TEXT NOT NULL,
            resources_json TEXT NOT NULL,
            created_at TEXT NOT NULL,
            UNIQUE(attempt_id, question_id)
        );
        """
    )

    conn.commit()

    if not SEED_PATH.exists():
        seed_payload = _default_seed_payload()
        SEED_PATH.write_text(json.dumps(seed_payload, ensure_ascii=False, indent=2), encoding="utf-8")
    else:
        seed_payload = json.loads(SEED_PATH.read_text(encoding="utf-8"))

    _seed_problems(conn, seed_payload)

    conn.close()


def _seed_problems(conn: sqlite3.Connection, payload: Dict) -> None:
    """Insert seed problems only when they are not already present."""
    cursor = conn.cursor()
    for problem in payload.get("problems", []):
        cursor.execute(
            "SELECT id FROM problems WHERE year = ? AND case_label = ?",
            (problem["year"], problem["case"]),
        )
        if cursor.fetchone():
            continue

        cursor.execute(
            "INSERT INTO problems (year, case_label, title, overview) VALUES (?, ?, ?, ?)",
            (
                problem["year"],
                problem["case"],
                problem["title"],
                problem["overview"],
            ),
        )
        problem_id = cursor.lastrowid

        for order, question in enumerate(problem.get("questions", []), start=1):
            cursor.execute(
                """
                INSERT INTO questions (
                    problem_id, question_order, prompt, character_limit, max_score,
                    model_answer, explanation, keywords_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    problem_id,
                    order,
                    question["prompt"],
                    question.get("character_limit"),
                    question["max_score"],
                    question["model_answer"],
                    question["explanation"],
                    json.dumps(question.get("keywords", []), ensure_ascii=False),
                ),
            )

    conn.commit()


def create_user(email: str, name: str, password_hash: Optional[str]) -> int:
    """Create a new user and return the primary key."""
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO users (email, name, password_hash, created_at) VALUES (?, ?, ?, ?)",
        (email, name, password_hash, datetime.utcnow().isoformat()),
    )
    conn.commit()
    user_id = cur.lastrowid
    conn.close()
    return user_id


def get_user_by_email(email: str) -> Optional[sqlite3.Row]:
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT * FROM users WHERE email = ?", (email,))
    row = cur.fetchone()
    conn.close()
    return row


def get_or_create_guest_user() -> sqlite3.Row:
    """Return the shared guest user record, creating it on first use."""
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT * FROM users WHERE email = ?", ("guest@example.com",))
    row = cur.fetchone()
    if row:
        conn.close()
        return row

    cur.execute(
        "INSERT INTO users (email, name, password_hash, created_at) VALUES (?, ?, ?, ?)",
        ("guest@example.com", "ゲストユーザー", None, datetime.utcnow().isoformat()),
    )
    conn.commit()
    cur.execute("SELECT * FROM users WHERE id = ?", (cur.lastrowid,))
    row = cur.fetchone()
    conn.close()
    return row


def update_user_plan(user_id: int, plan: str) -> None:
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("UPDATE users SET plan = ? WHERE id = ?", (plan, user_id))
    conn.commit()
    conn.close()


def list_problems() -> List[sqlite3.Row]:
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT * FROM problems ORDER BY year DESC, case_label ASC")
    rows = cur.fetchall()
    conn.close()
    return rows


def list_problem_years() -> List[str]:
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT DISTINCT year FROM problems ORDER BY year DESC")
    years = [row[0] for row in cur.fetchall()]
    conn.close()
    return years


def list_problem_cases(year: str) -> List[str]:
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT DISTINCT case_label FROM problems WHERE year = ? ORDER BY case_label", (year,))
    cases = [row[0] for row in cur.fetchall()]
    conn.close()
    return cases


def fetch_problem(problem_id: int) -> Optional[Dict]:
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT * FROM problems WHERE id = ?", (problem_id,))
    problem_row = cur.fetchone()
    if not problem_row:
        conn.close()
        return None

    cur.execute(
        "SELECT * FROM questions WHERE problem_id = ? ORDER BY question_order",
        (problem_id,),
    )
    question_rows = cur.fetchall()
    conn.close()

    questions = []
    for question in question_rows:
        questions.append(
            {
                "id": question["id"],
                "prompt": question["prompt"],
                "character_limit": question["character_limit"],
                "max_score": question["max_score"],
                "model_answer": question["model_answer"],
                "explanation": question["explanation"],
                "keywords": json.loads(question["keywords_json"]),
                "order": question["question_order"],
            }
        )

    return {
        "id": problem_row["id"],
        "year": problem_row["year"],
        "case_label": problem_row["case_label"],
        "title": problem_row["title"],
        "overview": problem_row["overview"],
        "questions": questions,
    }


def fetch_problem_by_year_case(year: str, case_label: str) -> Optional[Dict]:
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        "SELECT id FROM problems WHERE year = ? AND case_label = ?",
        (year, case_label),
    )
    row = cur.fetchone()
    conn.close()
    if not row:
        return None
    return fetch_problem(row["id"])


@dataclass
class RecordedAnswer:
    question_id: int
    answer_text: str
    score: float
    feedback: str
    keyword_hits: Dict[str, bool]


def _as_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False)


def record_attempt(
    user_id: int,
    problem_id: int,
    mode: str,
    answers: Iterable[RecordedAnswer],
    started_at: datetime,
    submitted_at: datetime,
    duration_seconds: Optional[int],
) -> int:
    """Persist an attempt with its answers."""
    conn = get_connection()
    cur = conn.cursor()

    total_score = sum(answer.score for answer in answers)

    cur.execute(
        "SELECT SUM(max_score) as total FROM questions WHERE problem_id = ?",
        (problem_id,),
    )
    total_max_score = cur.fetchone()["total"] or 0

    cur.execute(
        """
        INSERT INTO attempts (
            user_id, problem_id, mode, started_at, submitted_at, duration_seconds,
            total_score, total_max_score
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            user_id,
            problem_id,
            mode,
            started_at.isoformat(),
            submitted_at.isoformat(),
            duration_seconds,
            total_score,
            total_max_score,
        ),
    )
    attempt_id = cur.lastrowid

    for answer in answers:
        cur.execute(
            """
            INSERT INTO attempt_answers (
                attempt_id, question_id, answer_text, score, feedback, keyword_hits_json
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                attempt_id,
                answer.question_id,
                answer.answer_text,
                answer.score,
                answer.feedback,
                _as_json(answer.keyword_hits),
            ),
        )

    conn.commit()
    conn.close()
    return attempt_id


def list_attempts(user_id: int) -> List[sqlite3.Row]:
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT a.*, p.year, p.case_label, p.title
        FROM attempts a
        JOIN problems p ON p.id = a.problem_id
        WHERE a.user_id = ?
        ORDER BY a.submitted_at DESC
        """,
        (user_id,),
    )
    rows = cur.fetchall()
    conn.close()
    return rows


def fetch_learning_history(user_id: int) -> List[Dict]:
    """Return simplified attempt records for analytics on the history page."""

    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT
            a.id,
            a.submitted_at,
            a.total_score,
            a.total_max_score,
            a.mode,
            p.year,
            p.case_label,
            p.title
        FROM attempts a
        JOIN problems p ON p.id = a.problem_id
        WHERE a.user_id = ? AND a.submitted_at IS NOT NULL
        ORDER BY a.submitted_at
        """,
        (user_id,),
    )
    rows = cur.fetchall()
    conn.close()

    history: List[Dict] = []
    for row in rows:
        history.append(
            {
                "attempt_id": row["id"],
                "日付": row["submitted_at"],
                "年度": row["year"],
                "事例": row["case_label"],
                "タイトル": row["title"],
                "得点": row["total_score"],
                "満点": row["total_max_score"],
                "モード": "模試" if row["mode"] == "mock" else "演習",
            }
        )

    return history


def fetch_attempt_detail(attempt_id: int) -> Dict:
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT * FROM attempts WHERE id = ?", (attempt_id,))
    attempt = cur.fetchone()
    if not attempt:
        conn.close()
        raise ValueError("Attempt not found")

    cur.execute(
        """
        SELECT aa.*, q.prompt, q.max_score, q.model_answer, q.explanation, q.keywords_json
        FROM attempt_answers aa
        JOIN questions q ON q.id = aa.question_id
        WHERE aa.attempt_id = ?
        ORDER BY q.question_order
        """,
        (attempt_id,),
    )
    answers = cur.fetchall()
    conn.close()

    formatted_answers = []
    for row in answers:
        formatted_answers.append(
            {
                "question_id": row["question_id"],
                "prompt": row["prompt"],
                "answer_text": row["answer_text"],
                "score": row["score"],
                "max_score": row["max_score"],
                "feedback": row["feedback"],
                "model_answer": row["model_answer"],
                "explanation": row["explanation"],
                "keyword_hits": json.loads(row["keyword_hits_json"]) if row["keyword_hits_json"] else {},
            }
        )

    return {
        "attempt": attempt,
        "answers": formatted_answers,
    }


def save_explanation_entries(
    user_id: int,
    attempt_id: int,
    entries: Iterable[Dict[str, Any]],
) -> None:
    entries = list(entries)
    if not entries:
        return

    conn = get_connection()
    cur = conn.cursor()
    for entry in entries:
        cur.execute(
            """
            INSERT OR REPLACE INTO explanation_library (
                user_id, attempt_id, question_id, summary, feedback,
                focus_keywords_json, resources_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                user_id,
                attempt_id,
                entry["question_id"],
                entry["summary"],
                entry["feedback"],
                _as_json(entry.get("focus_keywords", [])),
                _as_json(entry.get("resources", [])),
                datetime.utcnow().isoformat(),
            ),
        )

    conn.commit()
    conn.close()


def fetch_explanations_for_attempt(attempt_id: int) -> List[Dict[str, Any]]:
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT el.*, q.prompt, q.question_order
        FROM explanation_library el
        JOIN questions q ON q.id = el.question_id
        WHERE el.attempt_id = ?
        ORDER BY q.question_order
        """,
        (attempt_id,),
    )
    rows = cur.fetchall()
    conn.close()

    explanations: List[Dict[str, Any]] = []
    for row in rows:
        explanations.append(
            {
                "question_id": row["question_id"],
                "summary": row["summary"],
                "feedback": row["feedback"],
                "focus_keywords": json.loads(row["focus_keywords_json"] or "[]"),
                "resources": json.loads(row["resources_json"] or "[]"),
            }
        )
    return explanations


def list_explanation_library(user_id: int) -> List[Dict[str, Any]]:
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT 
            el.*, p.year, p.case_label, q.prompt, q.question_order,
            a.submitted_at, a.mode
        FROM explanation_library el
        JOIN questions q ON q.id = el.question_id
        JOIN problems p ON p.id = q.problem_id
        JOIN attempts a ON a.id = el.attempt_id
        WHERE el.user_id = ?
        ORDER BY el.created_at DESC
        """,
        (user_id,),
    )
    rows = cur.fetchall()
    conn.close()

    explanations: List[Dict[str, Any]] = []
    for row in rows:
        explanations.append(
            {
                "question_id": row["question_id"],
                "summary": row["summary"],
                "feedback": row["feedback"],
                "focus_keywords": json.loads(row["focus_keywords_json"] or "[]"),
                "resources": json.loads(row["resources_json"] or "[]"),
                "created_at": row["created_at"],
                "year": row["year"],
                "case_label": row["case_label"],
                "prompt": row["prompt"],
                "question_order": row["question_order"],
                "attempt_mode": row["mode"],
                "attempt_submitted_at": row["submitted_at"],
            }
        )
    return explanations


def aggregate_statistics(user_id: int) -> Dict[str, Dict[str, float]]:
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT p.case_label, AVG(a.total_score) AS avg_score, AVG(a.total_max_score) AS avg_max
        FROM attempts a
        JOIN problems p ON p.id = a.problem_id
        WHERE a.user_id = ? AND a.total_score IS NOT NULL
        GROUP BY p.case_label
        """,
        (user_id,),
    )
    rows = cur.fetchall()
    conn.close()

    stats: Dict[str, Dict[str, float]] = {}
    for row in rows:
        stats[row["case_label"]] = {
            "avg_score": row["avg_score"] or 0,
            "avg_max": row["avg_max"] or 0,
        }
    return stats


def _default_seed_payload() -> Dict:
    """Return a minimal seed payload with representative problems."""
    return {
        "problems": [
            {
                "year": "令和3年",
                "case": "事例I",
                "title": "A社: 組織・人事課題の改善",
                "overview": (
                    "老舗和菓子メーカーA社の中期経営計画と人材活用に関するケースです。"
                    "現状の組織課題を分析し、成長戦略に向けた施策を検討します。"
                ),
                "questions": [
                    {
                        "prompt": "第1問(20点) A社の強みを80字以内で述べよ。",
                        "character_limit": 80,
                        "max_score": 20,
                        "model_answer": (
                            "長年培った和菓子製造技術と地域顧客との信頼関係を背景に、"
                            "高付加価値商品の企画・開発力を有している点。"
                        ),
                        "explanation": (
                            "与件文中の技術力・ブランド力に触れ、関係性を構造的に述べる。"
                            "80字以内で要約力が問われる。"
                        ),
                        "keywords": [
                            "製造技術",
                            "信頼関係",
                            "高付加価値",
                            "企画開発",
                        ],
                    },
                    {
                        "prompt": "第2問(30点) A社が抱える人材面の課題と改善策を120字以内で述べよ。",
                        "character_limit": 120,
                        "max_score": 30,
                        "model_answer": (
                            "熟練職人への依存と若手育成の遅れが課題であり、計画的な技能伝承と評価制度"
                            "の見直しによりモチベーションを高め、組織学習を促す体制構築が必要である。"
                        ),
                        "explanation": (
                            "課題→原因→施策の順で整理し、育成制度・評価制度双方に触れると高評価。"
                        ),
                        "keywords": [
                            "熟練",
                            "若手育成",
                            "技能伝承",
                            "評価制度",
                            "モチベーション",
                        ],
                    },
                ],
            },
            {
                "year": "令和2年",
                "case": "事例II",
                "title": "B社: 地域密着型サービスのマーケティング",
                "overview": (
                    "地域顧客向けにサービスを提供するB社のマーケティング戦略に関するケース。"
                ),
                "questions": [
                    {
                        "prompt": "第1問(25点) B社がターゲットとすべき顧客像と提供価値を100字以内で述べよ。",
                        "character_limit": 100,
                        "max_score": 25,
                        "model_answer": (
                            "高齢化が進む地域住民を主要顧客と捉え、見守り・生活支援を組み合わせた"
                            "ワンストップサービスを提供し安心感を高める。"
                        ),
                        "explanation": (
                            "ターゲットセグメントと差別化された提供価値を併記する。"
                        ),
                        "keywords": [
                            "高齢",
                            "地域住民",
                            "見守り",
                            "生活支援",
                            "安心",
                        ],
                    },
                    {
                        "prompt": "第2問(25点) B社が実施すべき販促施策を80字以内で述べよ。",
                        "character_limit": 80,
                        "max_score": 25,
                        "model_answer": (
                            "地域包括支援センターとの連携やイベント出展を通じ口コミを創出し、"
                            "紹介キャンペーンで継続利用を促進する。"
                        ),
                        "explanation": (
                            "連携先と具体的施策を示し、サービス特性と整合する点を押さえる。"
                        ),
                        "keywords": [
                            "連携",
                            "口コミ",
                            "紹介",
                            "継続利用",
                        ],
                    },
                ],
            },
            {
                "year": "令和3年",
                "case": "事例IV",
                "title": "C社: 財務分析と投資意思決定",
                "overview": (
                    "中堅製造業C社の財務諸表を分析し、投資判断と改善策を検討するケース。"
                ),
                "questions": [
                    {
                        "prompt": "第1問(25点) 資本効率の観点からC社の現状を分析し80字以内で述べよ。",
                        "character_limit": 80,
                        "max_score": 25,
                        "model_answer": (
                            "売上高は堅調だが過大な設備投資によりROAが低下し、固定資産回転率の改善"
                            "が必要である。"
                        ),
                        "explanation": (
                            "指標名を具体的に示し、課題と改善方向を因果で述べる。"
                        ),
                        "keywords": [
                            "ROA",
                            "固定資産回転率",
                            "設備投資",
                            "改善",
                        ],
                    },
                    {
                        "prompt": "第2問(25点) 投資判断の指標としてNPVを用いる理由を60字以内で述べよ。",
                        "character_limit": 60,
                        "max_score": 25,
                        "model_answer": (
                            "将来キャッシュフローを現在価値で捉え、資本コストを考慮した投資可否判断"
                            "ができるため。"
                        ),
                        "explanation": (
                            "NPVの概念と意思決定での有効性を端的に述べる。"
                        ),
                        "keywords": [
                            "キャッシュフロー",
                            "現在価値",
                            "資本コスト",
                            "投資判断",
                        ],
                    },
                ],
            },
        ]
    }
