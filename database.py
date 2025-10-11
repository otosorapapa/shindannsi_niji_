"""Database utilities for the 中小企業診断士二次試験対策アプリ.

This module wraps the SQLite storage that backs the Streamlit application.
It provides helper functions to initialise the schema, seed the database with
sample problems and interact with persisted learning data such as attempts and
scores.
"""
from __future__ import annotations

import json
import logging
import re
import sqlite3
import zlib
from dataclasses import dataclass
from datetime import date as dt_date, datetime, time as dt_time, timedelta
from functools import lru_cache
from pathlib import Path
from threading import Lock
from typing import Any, Dict, Iterable, List, Optional, Tuple, Union

DB_PATH = Path("data/app.db")
SEED_PATH = Path("data/seed_problems.json")

_INITIALIZE_LOCK = Lock()
_DATABASE_INITIALISED = False


logger = logging.getLogger(__name__)


_SEED_ONLY_ID_LOOKUP: Dict[int, Tuple[str, str]] = {}


def _clear_problem_caches() -> None:
    """Reset memoized problem lookups after mutations or seeding."""

    _SEED_ONLY_ID_LOOKUP.clear()

    for func_name in (
        "list_problems",
        "list_problem_years",
        "list_problem_cases",
        "fetch_problem",
        "fetch_problem_by_year_case",
    ):
        func = globals().get(func_name)
        if func is not None and hasattr(func, "cache_clear"):
            func.cache_clear()  # type: ignore[call-arg]

    for helper in (
        _list_problems_impl,
        _fetch_problem_impl,
        _fetch_problem_by_year_case_impl,
        _load_seed_problem_lookup_cached,
    ):
        if hasattr(helper, "cache_clear"):
            helper.cache_clear()  # type: ignore[call-arg]


def _seed_file_signature() -> float:
    """Return a timestamp signature for the seed problem file."""

    try:
        return SEED_PATH.stat().st_mtime
    except FileNotFoundError:
        return 0.0


def _load_seed_file_payload() -> Optional[Dict[str, Any]]:
    """Return the normalised seed payload from disk if available."""

    if not SEED_PATH.exists():
        return None

    raw_text = SEED_PATH.read_text(encoding="utf-8")
    cleaned_lines: List[str] = []
    for line in raw_text.splitlines():
        stripped = line.lstrip()
        if stripped.startswith("//"):
            continue
        cleaned_lines.append(line)

    cleaned_text = "\n".join(cleaned_lines).strip()
    if not cleaned_text:
        return {}

    try:
        payload = json.loads(cleaned_text)
    except json.JSONDecodeError as exc:
        logger.warning("Failed to parse seed file %s: %s", SEED_PATH, exc)
        return None

    return _normalise_seed_payload(payload)


@lru_cache(maxsize=1)
def _load_seed_problem_lookup_cached(signature: float) -> Dict[Tuple[str, str], Dict[str, Any]]:
    """Return seed problem data keyed by ``(year, case_label)``."""

    payload = _load_seed_file_payload()
    if not payload:
        return {}

    normalised = payload
    lookup: Dict[Tuple[str, str], Dict[str, Any]] = {}

    for problem in normalised.get("problems", []):
        year = problem.get("year")
        case_label = problem.get("case") or problem.get("case_label")
        if not (isinstance(year, str) and isinstance(case_label, str)):
            continue

        questions: List[Dict[str, Any]] = []
        for order, question in enumerate(problem.get("questions", []), start=1):
            normalised_question = dict(question)
            normalised_question.setdefault("prompt", "")
            normalised_question.setdefault("character_limit", None)
            normalised_question.setdefault("max_score", 0)
            normalised_question.setdefault("model_answer", "")
            normalised_question.setdefault("explanation", "")
            normalised_question.setdefault("keywords", [])
            normalised_question.setdefault("intent_cards", [])
            normalised_question.setdefault("video_url", None)
            normalised_question.setdefault("diagram_path", None)
            normalised_question.setdefault("diagram_caption", None)
            normalised_question["order"] = order
            normalised_question["question_order"] = order
            questions.append(normalised_question)

        lookup[(year, case_label)] = {
            "year": year,
            "case_label": case_label,
            "title": problem.get("title", ""),
            "overview": problem.get("overview", ""),
            "context": problem.get("context") or problem.get("context_text"),
            "questions": questions,
        }

    return lookup


def _load_seed_problem_lookup(signature: Optional[float] = None) -> Dict[Tuple[str, str], Dict[str, Any]]:
    """Convenience wrapper that injects the current seed file signature."""

    if signature is None:
        signature = _seed_file_signature()
    return _load_seed_problem_lookup_cached(signature)


def _make_seed_problem_id(year: str, case_label: str) -> int:
    """Return a stable negative identifier for seed-only problems."""

    key_bytes = f"{year}::{case_label}".encode("utf-8")
    # crc32 returns unsigned int, ensure negative identifier and avoid zero
    return -(zlib.crc32(key_bytes) + 1)


def _register_seed_only_problem(year: str, case_label: str) -> int:
    """Return a deterministic ID for the given seed problem and cache the mapping."""

    seed_id = _make_seed_problem_id(year, case_label)
    _SEED_ONLY_ID_LOOKUP[seed_id] = (year, case_label)
    return seed_id


def _resolve_seed_problem_by_id(
    problem_id: int, seed_lookup: Dict[Tuple[str, str], Dict[str, Any]]
) -> Optional[Tuple[str, str, Dict[str, Any]]]:
    """Return the seed problem metadata for the given identifier if available."""

    mapping = _SEED_ONLY_ID_LOOKUP.get(problem_id)
    if mapping:
        year, case_label = mapping
        seed_problem = seed_lookup.get((year, case_label))
        if seed_problem:
            return year, case_label, seed_problem

    for (year, case_label), seed_problem in seed_lookup.items():
        if _make_seed_problem_id(year, case_label) == problem_id:
            _SEED_ONLY_ID_LOOKUP[problem_id] = (year, case_label)
            return year, case_label, seed_problem

    return None


def _build_problem_from_seed(
    *, problem_id: int, year: str, case_label: str, seed_problem: Dict[str, Any]
) -> Dict[str, Any]:
    """Return a problem dictionary using only seed data."""

    context_text = seed_problem.get("context") or seed_problem.get("context_text")
    title = seed_problem.get("title", "")
    overview = seed_problem.get("overview", "")

    questions: List[Dict[str, Any]] = []
    for idx, seed_question in enumerate(seed_problem.get("questions", []), start=1):
        order = (
            seed_question.get("order")
            or seed_question.get("question_order")
            or seed_question.get("設問番号")
            or idx
        )
        keywords = seed_question.get("keywords") or []
        if not isinstance(keywords, list):
            keywords = [str(keywords)]
        keywords = [str(item) for item in keywords]

        intent_cards = seed_question.get("intent_cards") or []
        normalized_cards: List[Dict[str, Any]] = []
        if isinstance(intent_cards, list):
            for card in intent_cards:
                if isinstance(card, dict):
                    normalized_cards.append(dict(card))
                elif card is not None:
                    normalized_cards.append({"label": str(card)})

        question_entry: Dict[str, Any] = {
            "id": None,
            "prompt": seed_question.get("prompt", ""),
            "character_limit": seed_question.get("character_limit"),
            "max_score": seed_question.get("max_score"),
            "model_answer": seed_question.get("model_answer", ""),
            "explanation": seed_question.get("explanation", ""),
            "keywords": keywords,
            "order": order,
            "question_order": order,
            "intent_cards": normalized_cards,
            "video_url": seed_question.get("video_url"),
            "diagram_path": seed_question.get("diagram_path"),
            "diagram_caption": seed_question.get("diagram_caption"),
        }

        for extra_key in (
            "question_text",
            "body",
            "detailed_explanation",
            "question_intent",
            "問題文",
            "設問文",
        ):
            if seed_question.get(extra_key):
                question_entry[extra_key] = seed_question[extra_key]

        questions.append(question_entry)

    return {
        "id": problem_id,
        "year": year,
        "case_label": case_label,
        "title": title,
        "overview": overview,
        "context_text": context_text,
        "context": context_text,
        "questions": questions,
    }


def get_connection() -> sqlite3.Connection:
    """Return a SQLite connection with row factory configured."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def initialize_database(*, force: bool = False) -> None:
    """Create the SQLite database (if necessary) and seed master data."""

    global _DATABASE_INITIALISED

    if _DATABASE_INITIALISED and not force:
        return

    with _INITIALIZE_LOCK:
        if _DATABASE_INITIALISED and not force:
            return

        DB_PATH.parent.mkdir(parents=True, exist_ok=True)

        conn = get_connection()
        try:
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
            overview TEXT NOT NULL,
            context_text TEXT
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
            keywords_json TEXT NOT NULL,
            video_url TEXT,
            diagram_path TEXT,
            diagram_caption TEXT
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
            keyword_hits_json TEXT,
            axis_breakdown_json TEXT
        );

        CREATE TABLE IF NOT EXISTS reminders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            cadence TEXT NOT NULL,
            interval_days INTEGER NOT NULL,
            preferred_channels_json TEXT NOT NULL,
            reminder_time TEXT NOT NULL,
            next_trigger_at TEXT NOT NULL,
            last_notified_at TEXT
        );

        CREATE TABLE IF NOT EXISTS spaced_reviews (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            problem_id INTEGER NOT NULL REFERENCES problems(id) ON DELETE CASCADE,
            interval_days INTEGER NOT NULL,
            due_at TEXT NOT NULL,
            last_reviewed_at TEXT NOT NULL,
            last_score_ratio REAL,
            streak INTEGER NOT NULL DEFAULT 0,
            UNIQUE(user_id, problem_id)
        );

        CREATE TABLE IF NOT EXISTS study_goals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            period_type TEXT NOT NULL,
            start_date TEXT NOT NULL,
            end_date TEXT NOT NULL,
            target_practice_count INTEGER NOT NULL,
            target_study_minutes INTEGER NOT NULL,
            target_score REAL NOT NULL,
            preferred_start_time TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE(user_id, period_type, start_date)
        );

        CREATE TABLE IF NOT EXISTS study_sessions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            goal_id INTEGER NOT NULL REFERENCES study_goals(id) ON DELETE CASCADE,
            session_date TEXT NOT NULL,
            start_time TEXT NOT NULL,
            duration_minutes INTEGER NOT NULL,
            description TEXT,
            created_at TEXT NOT NULL,
            UNIQUE(goal_id, session_date, start_time)
        );
        """
            )

            conn.commit()

            if not SEED_PATH.exists():
                seed_payload = _default_seed_payload()
                SEED_PATH.write_text(
                    json.dumps(seed_payload, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
                seed_payload = _normalise_seed_payload(seed_payload)
            else:
                seed_payload = _load_seed_file_payload()
                if not seed_payload:
                    logger.warning(
                        "Falling back to bundled seed payload because %s could not be parsed.",
                        SEED_PATH,
                    )
                    seed_payload = _normalise_seed_payload(_default_seed_payload())

            _ensure_question_multimedia_columns(conn)
            _ensure_problem_context_columns(conn)
            _ensure_attempt_answer_axis_column(conn)

            _seed_problems(conn, seed_payload)
        finally:
            conn.close()

        _clear_problem_caches()
        _DATABASE_INITIALISED = True


def _seed_problems(conn: sqlite3.Connection, payload: Dict) -> None:
    """Insert seed problems only when they are not already present."""
    cursor = conn.cursor()
    for problem in payload.get("problems", []):
        cursor.execute(
            "SELECT id FROM problems WHERE year = ? AND case_label = ?",
            (problem["year"], problem["case"]),
        )
        row = cursor.fetchone()
        context_text = problem.get("context")

        if row:
            problem_id = row["id"]
            cursor.execute(
                "UPDATE problems SET title = ?, overview = ?, context_text = ? WHERE id = ?",
                (problem["title"], problem["overview"], context_text, problem_id),
            )
        else:
            cursor.execute(
                "INSERT INTO problems (year, case_label, title, overview, context_text) VALUES (?, ?, ?, ?, ?)",
                (
                    problem["year"],
                    problem["case"],
                    problem["title"],
                    problem["overview"],
                    context_text,
                ),
            )
            problem_id = cursor.lastrowid

        for order, question in enumerate(problem.get("questions", []), start=1):
            cursor.execute(
                "SELECT id FROM questions WHERE problem_id = ? AND question_order = ?",
                (problem_id, order),
            )
            existing_question = cursor.fetchone()
            payload_values = (
                question["prompt"],
                question.get("character_limit"),
                question["max_score"],
                question["model_answer"],
                question["explanation"],
                json.dumps(question.get("keywords", []), ensure_ascii=False),
                json.dumps(question.get("intent_cards", []), ensure_ascii=False),
                question.get("video_url"),
                question.get("diagram_path"),
                question.get("diagram_caption"),
            )

            if existing_question:
                cursor.execute(
                    """
                    UPDATE questions
                    SET prompt = ?, character_limit = ?, max_score = ?, model_answer = ?,
                        explanation = ?, keywords_json = ?, intent_cards_json = ?, video_url = ?,
                        diagram_path = ?, diagram_caption = ?
                    WHERE id = ?
                    """,
                    (*payload_values, existing_question["id"]),
                )
            else:
                cursor.execute(
                    """
                    INSERT INTO questions (
                        problem_id, question_order, prompt, character_limit, max_score,
                        model_answer, explanation, keywords_json, intent_cards_json, video_url,
                        diagram_path, diagram_caption
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        problem_id,
                        order,
                        *payload_values,
                    ),
                )

    conn.commit()


def _normalise_seed_payload(payload: Any) -> Dict[str, Any]:
    """Return seed data in the canonical structure used by the seeder.

    Historically the project stored the problem seeds as a flat list of
    question records. Modern versions expect a dictionary with a top-level
    ``"problems"`` key containing problem dictionaries, each with a nested
    ``"questions"`` list. When the legacy shape is detected we convert it into
    the new representation so that migrations remain backward compatible.
    """

    if isinstance(payload, dict) and "problems" in payload:
        return payload

    if not isinstance(payload, list):
        raise TypeError("Seed payload must be a dict or list of question records")

    problems: Dict[tuple[str, str], Dict[str, Any]] = {}

    def _normalise_keywords(raw: Any) -> List[str]:
        if isinstance(raw, list):
            return [str(keyword).strip() for keyword in raw if str(keyword).strip()]
        if isinstance(raw, str):
            return [
                keyword.strip()
                for keyword in re.split(r"[|,]", raw)
                if keyword.strip()
            ]
        return []

    def _normalise_intent_cards(raw: Any) -> List[Dict[str, Any]]:
        if isinstance(raw, list):
            return [card for card in raw if isinstance(card, dict)]
        if isinstance(raw, str) and raw.strip():
            cards: List[Dict[str, Any]] = []
            for chunk in raw.split("|"):
                chunk = chunk.strip()
                if not chunk:
                    continue
                try:
                    cards.append(json.loads(chunk))
                except json.JSONDecodeError:
                    # Fallback: attempt to interpret ``label:example`` patterns.
                    if ":" in chunk:
                        label, example = chunk.split(":", 1)
                        cards.append({"label": label.strip(), "example": example.strip()})
            return cards
        return []

    for entry in payload:
        if not isinstance(entry, dict):
            continue

        year = entry.get("year")
        case_label = entry.get("case")
        title = entry.get("title")
        overview = entry.get("overview")

        if not (year and case_label and title and overview):
            continue

        problem_key = (year, case_label)
        problem = problems.setdefault(
            problem_key,
            {
                "year": year,
                "case": case_label,
                "title": title,
                "overview": overview,
                "questions": [],
            },
        )

        for context_key in ("context", "context_text", "与件文全体", "与件文", "context_body"):
            context_value = entry.get(context_key)
            if isinstance(context_value, str) and context_value.strip():
                problem.setdefault("context", context_value.strip())
                break

        question = {
            "prompt": entry.get("prompt", ""),
            "character_limit": entry.get("character_limit"),
            "max_score": entry.get("max_score", 0),
            "model_answer": entry.get("model_answer", ""),
            "explanation": entry.get("explanation", ""),
            "keywords": _normalise_keywords(entry.get("keywords")),
            "intent_cards": _normalise_intent_cards(entry.get("intent_cards")),
            "video_url": entry.get("video_url"),
            "diagram_path": entry.get("diagram_path"),
            "diagram_caption": entry.get("diagram_caption"),
            "_order_hint": entry.get("question_index"),
        }

        problem["questions"].append(question)

    normalised_problems: List[Dict[str, Any]] = []
    def _question_order_key(question: Dict[str, Any]) -> Tuple[int, int, Union[float, str]]:
        """Return a sortable key for question ordering hints."""

        hint = question.get("_order_hint")
        if hint is None:
            return (1, 2, 0)

        if isinstance(hint, (int, float)):
            return (0, 0, float(hint))

        if isinstance(hint, str):
            stripped = hint.strip()
            if stripped:
                try:
                    return (0, 0, float(stripped))
                except ValueError:
                    return (0, 1, stripped)
            return (0, 1, "")

        return (0, 1, str(hint))

    for problem in problems.values():
        questions = problem["questions"]
        questions.sort(key=_question_order_key)
        for question in questions:
            question.pop("_order_hint", None)
        normalised_problems.append(
            {
                "year": problem["year"],
                "case": problem["case"],
                "title": problem["title"],
                "overview": problem["overview"],
                "context": problem.get("context"),
                "questions": questions,
            }
        )

    return {"problems": normalised_problems}


def _ensure_question_multimedia_columns(conn: sqlite3.Connection) -> None:
    """Add multimedia-related columns to the questions table when missing."""

    cursor = conn.cursor()
    cursor.execute("PRAGMA table_info(questions)")
    columns = {row[1] for row in cursor.fetchall()}

    alterations = []
    if "video_url" not in columns:
        alterations.append("ALTER TABLE questions ADD COLUMN video_url TEXT")
    if "diagram_path" not in columns:
        alterations.append("ALTER TABLE questions ADD COLUMN diagram_path TEXT")
    if "diagram_caption" not in columns:
        alterations.append("ALTER TABLE questions ADD COLUMN diagram_caption TEXT")
    if "intent_cards_json" not in columns:
        alterations.append(
            "ALTER TABLE questions ADD COLUMN intent_cards_json TEXT DEFAULT '[]'"
        )

    for statement in alterations:
        cursor.execute(statement)

    if alterations:
        conn.commit()


def _ensure_problem_context_columns(conn: sqlite3.Connection) -> None:
    """Ensure problems table has columns required for storing context text."""

    cursor = conn.cursor()
    cursor.execute("PRAGMA table_info(problems)")
    columns = {row[1] for row in cursor.fetchall()}

    if "context_text" not in columns:
        cursor.execute("ALTER TABLE problems ADD COLUMN context_text TEXT")
        conn.commit()


def _ensure_attempt_answer_axis_column(conn: sqlite3.Connection) -> None:
    """Ensure attempt_answers table can store観点別スコアの詳細。"""

    cursor = conn.cursor()
    cursor.execute("PRAGMA table_info(attempt_answers)")
    columns = {row[1] for row in cursor.fetchall()}

    if "axis_breakdown_json" not in columns:
        cursor.execute("ALTER TABLE attempt_answers ADD COLUMN axis_breakdown_json TEXT")
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


def list_problems() -> List[Dict[str, Any]]:
    return _list_problems_impl(_seed_file_signature())


@lru_cache(maxsize=1)
def _list_problems_impl(seed_signature: float) -> List[Dict[str, Any]]:
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT * FROM problems ORDER BY year DESC, case_label ASC")
    rows = [dict(row) for row in cur.fetchall()]
    conn.close()

    seed_lookup = _load_seed_problem_lookup_cached(seed_signature)
    existing_keys = set()
    for row in rows:
        seed_problem = seed_lookup.get((row["year"], row["case_label"]))
        existing_keys.add((row["year"], row["case_label"]))
        if not seed_problem:
            continue
        if seed_problem.get("title"):
            row["title"] = seed_problem["title"]
        if seed_problem.get("overview"):
            row["overview"] = seed_problem["overview"]
        context_text = seed_problem.get("context")
        if context_text:
            row["context_text"] = context_text

    _SEED_ONLY_ID_LOOKUP.clear()
    for (year, case_label), seed_problem in seed_lookup.items():
        seed_id = _register_seed_only_problem(year, case_label)
        if (year, case_label) in existing_keys:
            continue
        rows.append(
            {
                "id": seed_id,
                "year": year,
                "case_label": case_label,
                "title": seed_problem.get("title", ""),
                "overview": seed_problem.get("overview", ""),
                "context_text": seed_problem.get("context")
                or seed_problem.get("context_text"),
            }
        )

    rows.sort(key=lambda item: item.get("case_label", ""))
    rows.sort(key=lambda item: item.get("year", ""), reverse=True)
    return rows


@lru_cache(maxsize=1)
def list_problem_years() -> List[str]:
    return _list_problem_years_impl(_seed_file_signature())


@lru_cache(maxsize=1)
def _list_problem_years_impl(seed_signature: float) -> List[str]:
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT DISTINCT year FROM problems ORDER BY year DESC")
    years = [row[0] for row in cur.fetchall()]
    conn.close()
    seed_years = {year for (year, _case) in _load_seed_problem_lookup_cached(seed_signature).keys()}
    merged_years = sorted(set(years) | seed_years, reverse=True)
    return merged_years


def list_problem_cases(year: str) -> List[str]:
    return _list_problem_cases_impl(year, _seed_file_signature())


@lru_cache(maxsize=None)
def _list_problem_cases_impl(year: str, seed_signature: float) -> List[str]:
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        "SELECT DISTINCT case_label FROM problems WHERE year = ? ORDER BY case_label",
        (year,),
    )
    cases = [row[0] for row in cur.fetchall()]
    conn.close()
    seed_lookup = _load_seed_problem_lookup_cached(seed_signature)
    seed_cases = [
        case_label
        for seed_year, case_label in seed_lookup.keys()
        if seed_year == year
    ]
    merged_cases = sorted(set(cases) | set(seed_cases))
    return merged_cases


def fetch_problem(problem_id: int) -> Optional[Dict]:
    return _fetch_problem_impl(problem_id, _seed_file_signature())


@lru_cache(maxsize=None)
def _fetch_problem_impl(problem_id: int, seed_signature: float) -> Optional[Dict]:
    if problem_id <= 0:
        seed_lookup = _load_seed_problem_lookup_cached(seed_signature)
        resolved = _resolve_seed_problem_by_id(problem_id, seed_lookup)
        if not resolved:
            return None
        year, case_label, seed_problem = resolved
        return _build_problem_from_seed(
            problem_id=problem_id,
            year=year,
            case_label=case_label,
            seed_problem=seed_problem,
        )

    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT * FROM problems WHERE id = ?", (problem_id,))
    problem_row = cur.fetchone()
    if not problem_row:
        conn.close()
        seed_lookup = _load_seed_problem_lookup_cached(seed_signature)
        resolved = _resolve_seed_problem_by_id(problem_id, seed_lookup)
        if not resolved:
            return None
        year, case_label, seed_problem = resolved
        return _build_problem_from_seed(
            problem_id=problem_id,
            year=year,
            case_label=case_label,
            seed_problem=seed_problem,
        )

    cur.execute(
        "SELECT * FROM questions WHERE problem_id = ? ORDER BY question_order",
        (problem_id,),
    )
    question_rows = cur.fetchall()
    conn.close()

    seed_lookup = _load_seed_problem_lookup_cached(seed_signature)
    seed_problem = seed_lookup.get((problem_row["year"], problem_row["case_label"]))
    seed_questions: Dict[int, Dict[str, Any]] = {}
    if seed_problem:
        for idx, question in enumerate(seed_problem.get("questions", []), start=1):
            seed_questions[idx] = question

    questions: List[Dict[str, Any]] = []
    for question in question_rows:
        order = question["question_order"]
        seed_question = seed_questions.get(order)
        keywords = json.loads(question["keywords_json"])
        intent_cards = (
            json.loads(question["intent_cards_json"])
            if question["intent_cards_json"]
            else []
        )

        merged_question = {
            "id": question["id"],
            "prompt": question["prompt"],
            "character_limit": question["character_limit"],
            "max_score": question["max_score"],
            "model_answer": question["model_answer"],
            "explanation": question["explanation"],
            "keywords": keywords,
            "order": order,
            "intent_cards": intent_cards,
            "video_url": question["video_url"],
            "diagram_path": question["diagram_path"],
            "diagram_caption": question["diagram_caption"],
        }

        if seed_question:
            merged_question["prompt"] = seed_question.get("prompt", merged_question["prompt"])
            if seed_question.get("character_limit") is not None:
                merged_question["character_limit"] = seed_question.get("character_limit")
            if seed_question.get("max_score") is not None:
                merged_question["max_score"] = seed_question.get("max_score")
            merged_question["model_answer"] = seed_question.get(
                "model_answer", merged_question["model_answer"]
            )
            merged_question["explanation"] = seed_question.get(
                "explanation", merged_question["explanation"]
            )
            keywords_override = seed_question.get("keywords")
            if isinstance(keywords_override, list):
                merged_question["keywords"] = [str(item) for item in keywords_override]
            intent_override = seed_question.get("intent_cards")
            if isinstance(intent_override, list):
                normalized_cards: List[Dict[str, Any]] = []
                for card in intent_override:
                    if isinstance(card, dict):
                        normalized_cards.append(dict(card))
                    elif card is not None:
                        normalized_cards.append({"label": str(card)})
                merged_question["intent_cards"] = normalized_cards
            if seed_question.get("video_url"):
                merged_question["video_url"] = seed_question.get("video_url")
            if seed_question.get("diagram_path"):
                merged_question["diagram_path"] = seed_question.get("diagram_path")
            if seed_question.get("diagram_caption"):
                merged_question["diagram_caption"] = seed_question.get("diagram_caption")
            for extra_key in (
                "question_text",
                "body",
                "detailed_explanation",
                "question_intent",
                "問題文",
                "設問文",
            ):
                if extra_key in seed_question and seed_question[extra_key]:
                    merged_question[extra_key] = seed_question[extra_key]

        questions.append(merged_question)

    context_text = problem_row["context_text"]

    problem_dict = {
        "id": problem_row["id"],
        "year": problem_row["year"],
        "case_label": problem_row["case_label"],
        "title": problem_row["title"],
        "overview": problem_row["overview"],
        "questions": questions,
    }

    if seed_problem:
        if seed_problem.get("title"):
            problem_dict["title"] = seed_problem["title"]
        if seed_problem.get("overview"):
            problem_dict["overview"] = seed_problem["overview"]
        if seed_problem.get("context"):
            context_text = seed_problem.get("context")

    if context_text:
        problem_dict.update(
            {
                "context": context_text,
                "context_text": context_text,
                "context_body": context_text,
                "与件文": context_text,
                "与件文全体": context_text,
            }
        )

    return problem_dict


def fetch_problem_by_year_case(year: str, case_label: str) -> Optional[Dict]:
    return _fetch_problem_by_year_case_impl(year, case_label, _seed_file_signature())


@lru_cache(maxsize=None)
def _fetch_problem_by_year_case_impl(
    year: str, case_label: str, seed_signature: float
) -> Optional[Dict]:
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        "SELECT id FROM problems WHERE year = ? AND case_label = ?",
        (year, case_label),
    )
    row = cur.fetchone()
    conn.close()
    if row:
        return _fetch_problem_impl(row["id"], seed_signature)

    seed_lookup = _load_seed_problem_lookup_cached(seed_signature)
    seed_problem = seed_lookup.get((year, case_label))
    if not seed_problem:
        return None
    seed_id = _register_seed_only_problem(year, case_label)
    return _build_problem_from_seed(
        problem_id=seed_id,
        year=year,
        case_label=case_label,
        seed_problem=seed_problem,
    )


@dataclass
class RecordedAnswer:
    question_id: int
    answer_text: str
    score: float
    feedback: str
    keyword_hits: Dict[str, bool]
    axis_breakdown: Dict[str, Dict[str, object]]


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
                attempt_id, question_id, answer_text, score, feedback,
                keyword_hits_json, axis_breakdown_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                attempt_id,
                answer.question_id,
                answer.answer_text,
                answer.score,
                answer.feedback,
                json.dumps(answer.keyword_hits, ensure_ascii=False),
                json.dumps(answer.axis_breakdown, ensure_ascii=False),
            ),
        )

    conn.commit()
    conn.close()
    return attempt_id


def _next_review_interval(
    *, previous_interval: Optional[int], score_ratio: float
) -> tuple[int, int]:
    """Return (interval_days, streak_increment) for spaced repetition scheduling."""

    try:
        score_ratio = float(score_ratio)
    except (TypeError, ValueError):  # pragma: no cover - defensive conversion
        score_ratio = 0.0
    score_ratio = max(0.0, min(score_ratio, 1.0))
    previous_interval = previous_interval or 0

    if score_ratio >= 0.85:
        base = previous_interval if previous_interval else 3
        next_interval = max(base * 2, base + 1)
        streak_increment = 1
    elif score_ratio >= 0.6:
        base = previous_interval if previous_interval else 2
        next_interval = max(int(round(base * 1.5)), base + 1, 2)
        streak_increment = 0
    else:
        next_interval = 1
        streak_increment = 0

    next_interval = int(max(1, min(next_interval, 45)))
    return next_interval, streak_increment


def update_spaced_review(
    user_id: int,
    problem_id: int,
    *,
    score_ratio: float,
    reviewed_at: datetime,
) -> None:
    """Create or update spaced repetition schedule for a problem."""

    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        "SELECT * FROM spaced_reviews WHERE user_id = ? AND problem_id = ?",
        (user_id, problem_id),
    )
    row = cur.fetchone()

    previous_interval = row["interval_days"] if row else None
    previous_streak = row["streak"] if row else 0

    interval_days, streak_increment = _next_review_interval(
        previous_interval=previous_interval, score_ratio=score_ratio
    )
    next_due = reviewed_at + timedelta(days=interval_days)

    if row:
        new_streak = previous_streak + streak_increment if streak_increment else 0
        cur.execute(
            """
            UPDATE spaced_reviews
            SET interval_days = ?, due_at = ?, last_reviewed_at = ?,
                last_score_ratio = ?, streak = ?
            WHERE id = ?
            """,
            (
                interval_days,
                next_due.isoformat(),
                reviewed_at.isoformat(),
                score_ratio,
                new_streak,
                row["id"],
            ),
        )
    else:
        new_streak = streak_increment
        cur.execute(
            """
            INSERT INTO spaced_reviews (
                user_id, problem_id, interval_days, due_at,
                last_reviewed_at, last_score_ratio, streak
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                user_id,
                problem_id,
                interval_days,
                next_due.isoformat(),
                reviewed_at.isoformat(),
                score_ratio,
                new_streak,
            ),
        )

    conn.commit()
    conn.close()


def list_due_reviews(
    user_id: int,
    *,
    reference: Optional[datetime] = None,
    limit: int = 5,
) -> List[Dict]:
    """Return review items whose due date is on or before the reference timestamp."""

    reference_dt = reference or datetime.utcnow()
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT sr.*, p.year, p.case_label, p.title
        FROM spaced_reviews sr
        JOIN problems p ON p.id = sr.problem_id
        WHERE sr.user_id = ? AND sr.due_at <= ?
        ORDER BY sr.due_at
        LIMIT ?
        """,
        (user_id, reference_dt.isoformat(), limit),
    )
    rows = cur.fetchall()
    conn.close()

    items: List[Dict] = []
    for row in rows:
        due_at = _parse_iso_datetime(row["due_at"], field="spaced_reviews.due_at")
        if due_at is None:
            continue
        items.append(
            {
                "problem_id": row["problem_id"],
                "year": row["year"],
                "case_label": row["case_label"],
                "title": row["title"],
                "due_at": due_at,
                "interval_days": row["interval_days"],
                "last_score_ratio": row["last_score_ratio"],
                "streak": row["streak"],
            }
        )

    return items


def list_upcoming_reviews(user_id: int, *, limit: int = 6) -> List[Dict]:
    """Return upcoming spaced repetition entries ordered by due date."""

    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT sr.*, p.year, p.case_label, p.title
        FROM spaced_reviews sr
        JOIN problems p ON p.id = sr.problem_id
        WHERE sr.user_id = ?
        ORDER BY sr.due_at
        LIMIT ?
        """,
        (user_id, limit),
    )
    rows = cur.fetchall()
    conn.close()

    items: List[Dict] = []
    for row in rows:
        due_at = _parse_iso_datetime(row["due_at"], field="spaced_reviews.due_at")
        if due_at is None:
            continue
        items.append(
            {
                "problem_id": row["problem_id"],
                "year": row["year"],
                "case_label": row["case_label"],
                "title": row["title"],
                "due_at": due_at,
                "interval_days": row["interval_days"],
                "last_score_ratio": row["last_score_ratio"],
                "streak": row["streak"],
            }
        )

    return items


def count_due_reviews(user_id: int, *, reference: Optional[datetime] = None) -> int:
    """Return the number of spaced reviews whose due date has passed."""

    reference_dt = reference or datetime.utcnow()
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        "SELECT COUNT(*) FROM spaced_reviews WHERE user_id = ? AND due_at <= ?",
        (user_id, reference_dt.isoformat()),
    )
    count = cur.fetchone()[0]
    conn.close()
    return int(count or 0)


def get_spaced_review(user_id: int, problem_id: int) -> Optional[Dict]:
    """Fetch spaced repetition schedule for a particular problem, if it exists."""

    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT sr.*, p.year, p.case_label, p.title
        FROM spaced_reviews sr
        JOIN problems p ON p.id = sr.problem_id
        WHERE sr.user_id = ? AND sr.problem_id = ?
        """,
        (user_id, problem_id),
    )
    row = cur.fetchone()
    conn.close()
    if not row:
        return None

    due_at = _parse_iso_datetime(row["due_at"], field="spaced_reviews.due_at")
    last_reviewed = _parse_iso_datetime(
        row["last_reviewed_at"], field="spaced_reviews.last_reviewed_at"
    )

    if due_at is None or last_reviewed is None:
        logger.warning(
            "Skipping spaced review %s for user %s due to invalid timestamps",
            row["problem_id"],
            user_id,
        )
        return None

    return {
        "problem_id": row["problem_id"],
        "year": row["year"],
        "case_label": row["case_label"],
        "title": row["title"],
        "due_at": due_at,
        "interval_days": row["interval_days"],
        "last_score_ratio": row["last_score_ratio"],
        "streak": row["streak"],
        "last_reviewed_at": last_reviewed,
    }


def upsert_study_goal(
    *,
    user_id: int,
    period_type: str,
    start_date: dt_date,
    end_date: dt_date,
    target_practice_count: int,
    target_study_minutes: int,
    target_score: float,
    preferred_start_time: Optional[dt_time],
) -> int:
    """Create or update a study goal for the specified period."""

    conn = get_connection()
    cur = conn.cursor()
    now = datetime.utcnow().isoformat()
    start_value = start_date.isoformat()
    end_value = end_date.isoformat()
    preferred_value = preferred_start_time.strftime("%H:%M") if preferred_start_time else None

    cur.execute(
        "SELECT id FROM study_goals WHERE user_id = ? AND period_type = ? AND start_date = ?",
        (user_id, period_type, start_value),
    )
    row = cur.fetchone()

    if row:
        goal_id = row["id"]
        cur.execute(
            """
            UPDATE study_goals
            SET end_date = ?,
                target_practice_count = ?,
                target_study_minutes = ?,
                target_score = ?,
                preferred_start_time = ?,
                updated_at = ?
            WHERE id = ?
            """,
            (
                end_value,
                int(target_practice_count),
                int(target_study_minutes),
                float(target_score),
                preferred_value,
                now,
                goal_id,
            ),
        )
    else:
        cur.execute(
            """
            INSERT INTO study_goals (
                user_id, period_type, start_date, end_date,
                target_practice_count, target_study_minutes, target_score,
                preferred_start_time, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                user_id,
                period_type,
                start_value,
                end_value,
                int(target_practice_count),
                int(target_study_minutes),
                float(target_score),
                preferred_value,
                now,
                now,
            ),
        )
        goal_id = cur.lastrowid

    conn.commit()
    conn.close()
    return int(goal_id)


def get_current_study_goal(
    *, user_id: int, period_type: str, reference_date: dt_date
) -> Optional[Dict]:
    """Return the active study goal covering the reference date."""

    conn = get_connection()
    cur = conn.cursor()
    ref_value = reference_date.isoformat()
    cur.execute(
        """
        SELECT *
        FROM study_goals
        WHERE user_id = ?
          AND period_type = ?
          AND start_date <= ?
          AND end_date >= ?
        ORDER BY start_date DESC
        LIMIT 1
        """,
        (user_id, period_type, ref_value, ref_value),
    )
    row = cur.fetchone()
    conn.close()

    if not row:
        return None

    start = dt_date.fromisoformat(row["start_date"])
    end = dt_date.fromisoformat(row["end_date"])
    preferred = row["preferred_start_time"]
    preferred_time = dt_time.fromisoformat(preferred) if preferred else None

    return {
        "id": row["id"],
        "period_type": row["period_type"],
        "start_date": start,
        "end_date": end,
        "target_practice_count": row["target_practice_count"],
        "target_study_minutes": row["target_study_minutes"],
        "target_score": row["target_score"],
        "preferred_start_time": preferred_time,
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def replace_study_sessions(goal_id: int, sessions: Iterable[Dict[str, Any]]) -> None:
    """Replace all sessions associated with a study goal."""

    conn = get_connection()
    cur = conn.cursor()
    cur.execute("DELETE FROM study_sessions WHERE goal_id = ?", (goal_id,))

    now = datetime.utcnow().isoformat()
    for session in sessions:
        session_date: dt_date = session["session_date"]
        start_time: dt_time = session["start_time"]
        duration = int(session.get("duration_minutes", 0))
        description = session.get("description")
        cur.execute(
            """
            INSERT INTO study_sessions (
                goal_id, session_date, start_time, duration_minutes, description, created_at
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                goal_id,
                session_date.isoformat(),
                start_time.strftime("%H:%M"),
                duration,
                description,
                now,
            ),
        )

    conn.commit()
    conn.close()


def list_study_sessions(goal_id: int) -> List[Dict]:
    """Return study sessions associated with a study goal."""

    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT session_date, start_time, duration_minutes, description
        FROM study_sessions
        WHERE goal_id = ?
        ORDER BY session_date
        """,
        (goal_id,),
    )
    rows = cur.fetchall()
    conn.close()

    sessions: List[Dict] = []
    for row in rows:
        sessions.append(
            {
                "session_date": dt_date.fromisoformat(row["session_date"]),
                "start_time": dt_time.fromisoformat(row["start_time"]),
                "duration_minutes": row["duration_minutes"],
                "description": row["description"],
            }
        )

    return sessions


def aggregate_attempts_between(
    *, user_id: int, start_date: dt_date, end_date: dt_date
) -> Dict[str, Any]:
    """Return aggregate attempt statistics within a period."""

    start_dt = datetime.combine(start_date, datetime.min.time())
    end_dt = datetime.combine(end_date + timedelta(days=1), datetime.min.time())

    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT
            COUNT(*) AS practice_count,
            COALESCE(SUM(total_score), 0) AS total_score,
            COALESCE(SUM(total_max_score), 0) AS total_max,
            COALESCE(SUM(duration_seconds), 0) AS total_duration
        FROM attempts
        WHERE user_id = ?
          AND submitted_at IS NOT NULL
          AND submitted_at >= ?
          AND submitted_at < ?
        """,
        (user_id, start_dt.isoformat(), end_dt.isoformat()),
    )
    row = cur.fetchone()
    conn.close()

    practice_count = row["practice_count"] or 0
    total_score = row["total_score"] or 0.0
    total_max = row["total_max"] or 0.0
    total_duration = row["total_duration"] or 0

    average_score = float(total_score) / practice_count if practice_count else 0.0
    completion_rate = float(total_score) / total_max if total_max else 0.0

    return {
        "practice_count": int(practice_count),
        "average_score": average_score,
        "total_duration_minutes": int(total_duration // 60),
        "completion_rate": completion_rate,
    }


def list_attempts(user_id: int) -> List[Dict[str, Any]]:
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
    rows = [dict(row) for row in cur.fetchall()]
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


def get_reminder_settings(user_id: int) -> Optional[Dict]:
    """Return reminder configuration for a user, if it exists."""

    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        "SELECT * FROM reminders WHERE user_id = ?",
        (user_id,),
    )
    row = cur.fetchone()
    conn.close()

    if not row:
        return None

    return {
        "id": row["id"],
        "cadence": row["cadence"],
        "interval_days": row["interval_days"],
        "preferred_channels": json.loads(row["preferred_channels_json"]),
        "reminder_time": row["reminder_time"],
        "next_trigger_at": row["next_trigger_at"],
        "last_notified_at": row["last_notified_at"],
    }


def fetch_keyword_performance(user_id: int) -> List[Dict]:
    """Return answer-level keyword performance for the specified user."""

    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT
            aa.attempt_id,
            aa.answer_text,
            aa.score,
            aa.feedback,
            aa.keyword_hits_json,
            aa.axis_breakdown_json,
            a.mode,
            a.submitted_at,
            p.year,
            p.case_label,
            p.title,
            q.prompt,
            q.max_score
        FROM attempt_answers aa
        JOIN attempts a ON a.id = aa.attempt_id
        JOIN questions q ON q.id = aa.question_id
        JOIN problems p ON p.id = a.problem_id
        WHERE a.user_id = ? AND a.submitted_at IS NOT NULL
        ORDER BY a.submitted_at
        """,
        (user_id,),
    )

    rows = cur.fetchall()
    conn.close()

    keyword_records: List[Dict] = []
    for row in rows:
        keyword_records.append(
            {
                "attempt_id": row["attempt_id"],
                "answer_text": row["answer_text"],
                "score": row["score"],
                "feedback": row["feedback"],
                "keyword_hits": json.loads(row["keyword_hits_json"]) if row["keyword_hits_json"] else {},
                "axis_breakdown": json.loads(row["axis_breakdown_json"]) if row["axis_breakdown_json"] else {},
                "mode": row["mode"],
                "submitted_at": row["submitted_at"],
                "year": row["year"],
                "case_label": row["case_label"],
                "title": row["title"],
                "prompt": row["prompt"],
                "max_score": row["max_score"],
            }
        )

    return keyword_records


def upsert_reminder_settings(
    *,
    user_id: int,
    cadence: str,
    interval_days: int,
    preferred_channels: Iterable[str],
    reminder_time: str,
    next_trigger_at: datetime,
) -> None:
    """Create or update reminder settings for a user."""

    conn = get_connection()
    cur = conn.cursor()
    channels_json = json.dumps(list(preferred_channels), ensure_ascii=False)
    next_trigger_value = next_trigger_at.isoformat()

    cur.execute("SELECT id FROM reminders WHERE user_id = ?", (user_id,))
    row = cur.fetchone()

    if row:
        cur.execute(
            """
            UPDATE reminders
            SET cadence = ?, interval_days = ?, preferred_channels_json = ?,
                reminder_time = ?, next_trigger_at = ?
            WHERE user_id = ?
            """,
            (cadence, interval_days, channels_json, reminder_time, next_trigger_value, user_id),
        )
    else:
        cur.execute(
            """
            INSERT INTO reminders (
                user_id, cadence, interval_days, preferred_channels_json,
                reminder_time, next_trigger_at
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (user_id, cadence, interval_days, channels_json, reminder_time, next_trigger_value),
        )

    conn.commit()
    conn.close()


def mark_reminder_sent(reminder_id: int, *, next_trigger_at: datetime) -> None:
    """Update reminder record when a notification has been (virtually) sent."""

    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        """
        UPDATE reminders
        SET last_notified_at = ?, next_trigger_at = ?
        WHERE id = ?
        """,
        (datetime.utcnow().isoformat(), next_trigger_at.isoformat(), reminder_id),
    )
    conn.commit()
    conn.close()


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
        SELECT aa.*, q.prompt, q.max_score, q.model_answer, q.explanation,
               q.keywords_json, q.intent_cards_json, q.video_url, q.diagram_path,
               q.diagram_caption, q.question_order, p.year, p.case_label
        FROM attempt_answers aa
        JOIN questions q ON q.id = aa.question_id
        JOIN problems p ON p.id = q.problem_id
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
                "prompt": row["prompt"],
                "answer_text": row["answer_text"],
                "score": row["score"],
                "max_score": row["max_score"],
                "feedback": row["feedback"],
                "model_answer": row["model_answer"],
                "explanation": row["explanation"],
                "keyword_hits": json.loads(row["keyword_hits_json"]) if row["keyword_hits_json"] else {},
                "axis_breakdown": json.loads(row["axis_breakdown_json"]) if row["axis_breakdown_json"] else {},
                "intent_cards": json.loads(row["intent_cards_json"]) if row["intent_cards_json"] else [],
                "video_url": row["video_url"],
                "diagram_path": row["diagram_path"],
                "diagram_caption": row["diagram_caption"],
                "question_order": row["question_order"],
                "year": row["year"],
                "case_label": row["case_label"],
            }
        )

    return {
        "attempt": attempt,
        "answers": formatted_answers,
    }


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
                "context": (
                    "創業70年のA社は地方都市で和菓子を製造・卸売している。"
                    "熟練職人が味と意匠を守る一方、若手はEC販促と新商品企画を兼務し忙殺されている。"
                    "\n\n主要百貨店との取引は継続しているが、営業情報の共有不足で提案が属人的になっている。"
                    "人事制度や教育体系の整備が遅れ、部署横断プロジェクトもリーダー不足に陥っている。"
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
                        "intent_cards": [
                            {
                                "label": "強み要約力",
                                "example": "長年培った製造技術と地域顧客との信頼関係を強みとして示す。",
                            },
                            {
                                "label": "価値訴求力",
                                "example": "高付加価値商品の企画・開発力で提供価値を高めると述べる。",
                            },
                        ],
                        "video_url": "https://interactive-examples.mdn.mozilla.net/media/cc0-videos/flower.mp4",
                        "diagram_path": "data/diagrams/case1_q1.svg",
                        "diagram_caption": "A社の強みを構造的に整理した関係図。",
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
                        "intent_cards": [
                            {
                                "label": "課題抽出力",
                                "example": "熟練職人への依存と若手育成の遅れを課題として指摘する。",
                            },
                            {
                                "label": "育成設計力",
                                "example": "技能伝承と評価制度を連動させモチベーション向上策を提示する。",
                            },
                        ],
                        "video_url": "https://samplelib.com/lib/preview/mp4/sample-5s.mp4",
                        "diagram_path": "data/diagrams/case1_q2.svg",
                        "diagram_caption": "技能伝承と評価制度を連動させた改善施策のロードマップ。",
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
                        "intent_cards": [
                            {
                                "label": "ターゲット提言力",
                                "example": "高齢化が進む地域住民を主要顧客として定義する。",
                            },
                            {
                                "label": "提供価値言語化力",
                                "example": "見守りと生活支援を組み合わせ安心を提供する価値を述べる。",
                            },
                        ],
                        "video_url": "https://samplelib.com/lib/preview/mp4/sample-10s.mp4",
                        "diagram_path": "data/diagrams/case2_q1.svg",
                        "diagram_caption": "主要顧客ペルソナと提供価値の対応関係を示すマップ。",
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
                        "intent_cards": [
                            {
                                "label": "協業先の提案力",
                                "example": "地域包括支援センターと連携し紹介導線を築く提案を示す。",
                            },
                            {
                                "label": "販促導線構築力",
                                "example": "イベント出展と紹介キャンペーンで口コミから継続利用につなげる。",
                            },
                        ],
                        "video_url": "https://interactive-examples.mdn.mozilla.net/media/cc0-videos/flower.mp4",
                        "diagram_path": "data/diagrams/case2_q2.svg",
                        "diagram_caption": "連携施策から口コミ創出までの導線を図解したカスタマージャーニー。",
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
                        "intent_cards": [
                            {
                                "label": "指標分析力",
                                "example": "過大な設備投資でROAが低下している点を示す。",
                            },
                            {
                                "label": "改善提案力",
                                "example": "固定資産回転率の改善を課題として提示する。",
                            },
                        ],
                        "video_url": "https://samplelib.com/lib/preview/mp4/sample-5s.mp4",
                        "diagram_path": "data/diagrams/case4_q1.svg",
                        "diagram_caption": "ROAと固定資産回転率の推移を比較したダッシュボードイメージ。",
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
                        "intent_cards": [
                            {
                                "label": "投資根拠説明力",
                                "example": "将来キャッシュフローを現在価値に割り引き投資可否を判断すると述べる。",
                            },
                            {
                                "label": "資本コスト理解力",
                                "example": "資本コストを考慮できる指標としてNPVを採用する理由を示す。",
                            },
                        ],
                        "video_url": "https://samplelib.com/lib/preview/mp4/sample-10s.mp4",
                        "diagram_path": "data/diagrams/case4_q2.svg",
                        "diagram_caption": "NPV計算のステップを示す意思決定フロー。",
                    },
                ],
            },
        ]
    }


def _parse_iso_datetime(value: Any, *, field: str) -> Optional[datetime]:
    """Best-effort parsing of ISO formatted timestamps with graceful fallback."""

    if value is None:
        return None

    if isinstance(value, datetime):
        return value

    text = str(value).strip()
    if not text:
        return None

    candidates = [text]
    if text.endswith("Z"):
        candidates.append(f"{text[:-1]}+00:00")
        candidates.append(text[:-1])
    if "T" not in text and " " in text:
        candidates.append(text.replace(" ", "T", 1))

    for candidate in candidates:
        try:
            return datetime.fromisoformat(candidate)
        except ValueError:
            continue

    logger.warning("Failed to parse %s value '%s' as ISO timestamp", field, text)
    return None
