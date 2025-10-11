from __future__ import annotations

import html
import json
from datetime import datetime
from io import BytesIO
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence

import pandas as pd
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.pdfgen import canvas
from reportlab.lib.utils import simpleSplit


_PDF_FONT_REGISTERED = False


def _ensure_pdf_font() -> str:
    global _PDF_FONT_REGISTERED
    font_name = "HeiseiMin-W3"
    if not _PDF_FONT_REGISTERED:
        pdfmetrics.registerFont(UnicodeCIDFont(font_name))
        _PDF_FONT_REGISTERED = True
    return font_name


def _safe_minutes(seconds: Optional[Any]) -> Optional[float]:
    try:
        if seconds is None:
            return None
        seconds_value = float(seconds)
    except (TypeError, ValueError):
        return None
    if seconds_value < 0:
        return None
    return round(seconds_value / 60.0, 2)


def _format_keyword_hits(keyword_hits: Mapping[str, bool]) -> Dict[str, List[str]]:
    matched = [kw for kw, hit in keyword_hits.items() if hit]
    missing = [kw for kw, hit in keyword_hits.items() if not hit]
    return {"matched": matched, "missing": missing}


def build_attempt_export_payload(
    attempt: Mapping[str, Any],
    answers: Sequence[Mapping[str, Any]],
    problem: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    problem = problem or {}
    sorted_answers = sorted(
        answers,
        key=lambda entry: entry.get("question_order") or 0,
    )

    prepared_answers: List[Dict[str, Any]] = []
    for entry in sorted_answers:
        keyword_hits = entry.get("keyword_hits") or {}
        coverage = entry.get("keyword_coverage")
        if coverage is None and keyword_hits:
            coverage = sum(1 for hit in keyword_hits.values() if hit) / len(keyword_hits)
        prepared_answers.append(
            {
                "question_order": entry.get("question_order"),
                "prompt": entry.get("prompt"),
                "answer": entry.get("answer_text"),
                "score": entry.get("score"),
                "max_score": entry.get("max_score"),
                "feedback": entry.get("feedback"),
                "keyword_hits": keyword_hits,
                "keyword_summary": _format_keyword_hits(keyword_hits),
                "keyword_coverage": coverage,
                "axis_breakdown": entry.get("axis_breakdown") or entry.get("checkpoint_log", {}).get("axes", {}),
                "self_evaluation": entry.get("self_evaluation"),
                "duration_seconds": entry.get("duration_seconds"),
                "duration_minutes": _safe_minutes(entry.get("duration_seconds")),
            }
        )

    context_text = (
        problem.get("context_text")
        or problem.get("context")
        or problem.get("overview")
        or ""
    )
    if context_text and len(str(context_text)) > 1600:
        context_text = str(context_text)[:1600].rstrip() + "…"

    payload = {
        "attempt": {
            "id": attempt.get("id"),
            "user_id": attempt.get("user_id"),
            "mode": attempt.get("mode"),
            "started_at": attempt.get("started_at"),
            "submitted_at": attempt.get("submitted_at"),
            "duration_seconds": attempt.get("duration_seconds"),
            "total_score": attempt.get("total_score"),
            "total_max_score": attempt.get("total_max_score"),
        },
        "problem": {
            "id": attempt.get("problem_id"),
            "year": problem.get("year"),
            "case_label": problem.get("case_label"),
            "title": problem.get("title"),
            "overview": problem.get("overview"),
            "context": context_text,
        },
        "answers": prepared_answers,
    }
    return payload


def attempt_csv_bytes(payload: Mapping[str, Any]) -> bytes:
    rows: List[Dict[str, Any]] = []
    for answer in payload.get("answers", []):
        keyword_summary = answer.get("keyword_summary") or {}
        matched = "、".join(keyword_summary.get("matched", [])) or "-"
        missing = "、".join(keyword_summary.get("missing", [])) or "-"
        rows.append(
            {
                "設問番号": answer.get("question_order"),
                "問題文": answer.get("prompt"),
                "解答": answer.get("answer"),
                "得点": answer.get("score"),
                "満点": answer.get("max_score"),
                "自己評価": answer.get("self_evaluation") or "未評価",
                "所要時間(分)": answer.get("duration_minutes"),
                "キーワード網羅率": (
                    round(float(answer.get("keyword_coverage")) * 100, 1)
                    if answer.get("keyword_coverage") is not None
                    else None
                ),
                "含まれたキーワード": matched,
                "不足キーワード": missing,
                "フィードバック": answer.get("feedback"),
            }
        )
    df = pd.DataFrame(rows)
    if not df.empty:
        df.sort_values("設問番号", inplace=True)
    return df.to_csv(index=False).encode("utf-8-sig")


def attempt_json_bytes(payload: Mapping[str, Any]) -> bytes:
    return json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8-sig")


def attempt_pdf_bytes(payload: Mapping[str, Any]) -> bytes:
    buffer = BytesIO()
    font_name = _ensure_pdf_font()
    c = canvas.Canvas(buffer, pagesize=A4)
    width, height = A4
    margin_x = 12 * mm
    margin_y = 15 * mm
    text_width = width - margin_x * 2

    c.setTitle("Exam Attempt Summary")

    y = height - margin_y
    c.setFont(font_name, 13)
    problem = payload.get("problem") or {}
    title_parts = [problem.get("year"), problem.get("case_label"), problem.get("title")]
    title = " ".join(str(part) for part in title_parts if part)
    if not title:
        title = "演習結果"
    c.drawString(margin_x, y, title)
    y -= 16

    attempt = payload.get("attempt") or {}
    submitted_at = attempt.get("submitted_at")
    if submitted_at:
        try:
            submitted_display = datetime.fromisoformat(str(submitted_at)).strftime("%Y-%m-%d %H:%M")
        except ValueError:
            submitted_display = str(submitted_at)
    else:
        submitted_display = "-"

    score_text = f"総合得点: {attempt.get('total_score', '-')}/{attempt.get('total_max_score', '-')}"
    meta_text = f"回答日時: {submitted_display} / モード: {attempt.get('mode', '-') }"
    c.setFont(font_name, 10)
    c.drawString(margin_x, y, score_text)
    y -= 13
    c.drawString(margin_x, y, meta_text)
    y -= 18

    context = problem.get("context") or ""
    if context:
        c.setFont(font_name, 11)
        c.drawString(margin_x, y, "与件文サマリ")
        y -= 14
        c.setFont(font_name, 9.5)
        for line in simpleSplit(str(context), font_name, 9.5, text_width):
            if y < margin_y:
                c.showPage()
                y = height - margin_y
                c.setFont(font_name, 9.5)
            c.drawString(margin_x, y, line)
            y -= 12
        y -= 6

    answers = payload.get("answers") or []
    for answer in answers:
        if y < margin_y + 80:
            c.showPage()
            y = height - margin_y
            c.setFont(font_name, 9.5)
        c.setFont(font_name, 11)
        header = f"設問{answer.get('question_order')}  得点 {answer.get('score')}/{answer.get('max_score')}"
        c.drawString(margin_x, y, header)
        y -= 14
        c.setFont(font_name, 9.5)
        prompt = answer.get("prompt") or ""
        for line in simpleSplit(str(prompt), font_name, 9.5, text_width):
            c.drawString(margin_x, y, line)
            y -= 12
        y -= 4
        answer_text = answer.get("answer") or ""
        if answer_text:
            c.setFont(font_name, 9)
            for line in simpleSplit(str(answer_text), font_name, 9, text_width):
                c.drawString(margin_x + 4, y, line)
                y -= 11
        feedback = answer.get("feedback") or ""
        if feedback:
            c.setFont(font_name, 9)
            c.drawString(margin_x, y, "講評")
            y -= 11
            for line in simpleSplit(str(feedback), font_name, 9, text_width):
                c.drawString(margin_x + 4, y, line)
                y -= 11
        keyword_summary = answer.get("keyword_summary") or {}
        matched = "、".join(keyword_summary.get("matched", [])) or "-"
        missing = "、".join(keyword_summary.get("missing", [])) or "-"
        info_line = (
            f"キーワード網羅率: {answer.get('keyword_coverage') and round(answer['keyword_coverage'] * 100, 1)}%"
            if answer.get("keyword_coverage") is not None
            else "キーワード網羅率: -"
        )
        eval_line = f"自己評価: {answer.get('self_evaluation') or '未評価'} / 所要時間(分): {answer.get('duration_minutes') or '-'}"
        c.setFont(font_name, 9)
        c.drawString(margin_x, y, info_line)
        y -= 11
        c.drawString(margin_x, y, eval_line)
        y -= 11
        c.drawString(margin_x, y, f"含まれたキーワード: {matched}")
        y -= 11
        c.drawString(margin_x, y, f"不足キーワード: {missing}")
        y -= 14

    c.showPage()
    c.save()
    buffer.seek(0)
    return buffer.read()


def build_printable_html(payload: Mapping[str, Any]) -> str:
    attempt = payload.get("attempt") or {}
    problem = payload.get("problem") or {}
    answers = payload.get("answers") or []
    score_text = f"{attempt.get('total_score', '-')}/{attempt.get('total_max_score', '-')}"
    submitted_at = attempt.get("submitted_at")
    if submitted_at:
        try:
            submitted_display = datetime.fromisoformat(str(submitted_at)).strftime("%Y-%m-%d %H:%M")
        except ValueError:
            submitted_display = html.escape(str(submitted_at))
    else:
        submitted_display = "-"

    answer_html: List[str] = []
    for answer in answers:
        keyword_summary = answer.get("keyword_summary") or {}
        matched = "、".join(keyword_summary.get("matched", [])) or "-"
        missing = "、".join(keyword_summary.get("missing", [])) or "-"
        coverage = (
            f"{round(answer.get('keyword_coverage') * 100, 1)}%"
            if answer.get("keyword_coverage") is not None
            else "-"
        )
        answer_html.append(
            """
            <section class="answer-card">
              <header>
                <h3>設問{order}</h3>
                <div class="answer-meta">
                  <span>得点: {score}/{max_score}</span>
                  <span>自己評価: {self_eval}</span>
                  <span>所要時間: {duration}分</span>
                </div>
              </header>
              <p class="prompt">{prompt}</p>
              <div class="answer-body"><strong>解答</strong><p>{answer_text}</p></div>
              <div class="answer-body"><strong>講評</strong><p>{feedback}</p></div>
              <ul class="keyword-list">
                <li>キーワード網羅率: {coverage}</li>
                <li>含まれたキーワード: {matched}</li>
                <li>不足キーワード: {missing}</li>
              </ul>
            </section>
            """.format(
                order=html.escape(str(answer.get("question_order") or "-")),
                score=html.escape(str(answer.get("score") or "-")),
                max_score=html.escape(str(answer.get("max_score") or "-")),
                self_eval=html.escape(answer.get("self_evaluation") or "未評価"),
                duration=html.escape(str(answer.get("duration_minutes") or "-")),
                prompt=html.escape(str(answer.get("prompt") or "")),
                answer_text=html.escape(str(answer.get("answer") or "-")),
                feedback=html.escape(str(answer.get("feedback") or "-")),
                coverage=html.escape(coverage),
                matched=html.escape(matched),
                missing=html.escape(missing),
            )
        )

    context = html.escape(str(problem.get("context") or problem.get("overview") or "-"))

    title_parts = [problem.get("year"), problem.get("case_label"), problem.get("title")]
    title = " ".join(str(part) for part in title_parts if part) or "演習結果"

    html_text = """
    <style>
      :root {
        color-scheme: light;
      }
      body { font-family: 'Noto Sans JP', 'Hiragino Sans', sans-serif; margin: 0; }
      .print-wrapper { padding: 16px 32px; }
      .print-header { display: flex; justify-content: space-between; align-items: baseline; margin-bottom: 12px; }
      .print-header h1 { font-size: 20px; margin: 0; }
      .meta-list { list-style: none; padding: 0; margin: 0; display: flex; gap: 12px; font-size: 12px; }
      .columns { display: grid; grid-template-columns: 1.1fr 1fr; gap: 18px; }
      .context-card { border: 1px solid #ddd; padding: 12px; border-radius: 8px; background: #fafafa; font-size: 12px; line-height: 1.5; }
      .answer-stack { display: flex; flex-direction: column; gap: 12px; }
      .answer-card { border: 1px solid #ddd; border-radius: 8px; padding: 12px; font-size: 12px; }
      .answer-card header { display: flex; justify-content: space-between; align-items: baseline; margin-bottom: 8px; }
      .answer-card h3 { margin: 0; font-size: 14px; }
      .answer-card .answer-meta { display: flex; gap: 10px; font-size: 11px; color: #555; }
      .answer-card .prompt { font-weight: 600; margin: 0 0 6px; }
      .answer-body { margin-bottom: 6px; }
      .answer-body p { margin: 4px 0; white-space: pre-wrap; }
      .keyword-list { list-style: none; padding: 0; margin: 6px 0 0; font-size: 11px; }
      .keyword-list li { margin-bottom: 2px; }
      .print-action { text-align: right; margin-bottom: 12px; }
      .print-button { padding: 6px 12px; border: 1px solid #444; background: #fff; cursor: pointer; border-radius: 6px; }
      @media print {
        .print-action { display: none; }
        body { margin: 0; }
        .print-wrapper { padding: 8mm 12mm; }
        .columns { grid-template-columns: 1fr 1fr; gap: 10px; }
        .answer-card, .context-card { page-break-inside: avoid; }
      }
    </style>
    <div class="print-wrapper">
      <div class="print-action"><button class="print-button" onclick="window.print()">印刷</button></div>
      <header class="print-header">
        <h1>{title}</h1>
        <ul class="meta-list">
          <li>得点: {score}</li>
          <li>回答日時: {submitted}</li>
          <li>モード: {mode}</li>
        </ul>
      </header>
      <section class="columns">
        <article class="context-card">
          <h2>与件サマリ</h2>
          <p>{context}</p>
        </article>
        <article class="answer-stack">
          {answers}
        </article>
      </section>
    </div>
    """.format(
        title=html.escape(title),
        score=html.escape(score_text),
        submitted=submitted_display,
        mode=html.escape(attempt.get("mode", "-") or "-"),
        context=context,
        answers="\n".join(answer_html),
    )
    return html_text


def scoring_logs_csv_bytes(log_rows: Iterable[Mapping[str, Any]]) -> bytes:
    rows: List[Dict[str, Any]] = []
    for log in log_rows:
        checkpoints = log.get("checkpoints") or {}
        keywords = checkpoints.get("keywords") or {}
        matched = "、".join(kw for kw, hit in keywords.items() if hit) or "-"
        missing = "、".join(kw for kw, hit in keywords.items() if not hit) or "-"
        rows.append(
            {
                "attempt_id": log.get("attempt_id"),
                "年度": log.get("year"),
                "事例": log.get("case_label"),
                "設問番号": log.get("question_order"),
                "得点": log.get("score"),
                "満点": log.get("max_score"),
                "キーワード網羅率": (
                    round(float(log.get("keyword_coverage")) * 100, 1)
                    if log.get("keyword_coverage") is not None
                    else None
                ),
                "自己評価": log.get("self_evaluation") or "未評価",
                "所要時間(分)": _safe_minutes(log.get("duration_seconds")),
                "含まれたキーワード": matched,
                "不足キーワード": missing,
                "回答日時": log.get("logged_at"),
            }
        )
    df = pd.DataFrame(rows)
    if not df.empty:
        df.sort_values(["回答日時", "attempt_id", "設問番号"], inplace=True)
    return df.to_csv(index=False).encode("utf-8-sig")


def scoring_logs_json_bytes(log_rows: Iterable[Mapping[str, Any]]) -> bytes:
    normalized: List[Dict[str, Any]] = []
    for log in log_rows:
        normalized.append(
            {
                "log_id": log.get("log_id"),
                "attempt_id": log.get("attempt_id"),
                "question_id": log.get("question_id"),
                "question_order": log.get("question_order"),
                "logged_at": log.get("logged_at"),
                "score": log.get("score"),
                "max_score": log.get("max_score"),
                "keyword_coverage": log.get("keyword_coverage"),
                "duration_seconds": log.get("duration_seconds"),
                "self_evaluation": log.get("self_evaluation"),
                "year": log.get("year"),
                "case_label": log.get("case_label"),
                "title": log.get("title"),
                "prompt": log.get("prompt"),
                "mode": log.get("mode"),
                "checkpoints": log.get("checkpoints"),
                "axis_breakdown": log.get("axis_breakdown"),
            }
        )
    return json.dumps(normalized, ensure_ascii=False, indent=2).encode("utf-8-sig")


def scoring_logs_pdf_bytes(log_rows: Sequence[Mapping[str, Any]]) -> bytes:
    buffer = BytesIO()
    font_name = _ensure_pdf_font()
    c = canvas.Canvas(buffer, pagesize=A4)
    width, height = A4
    margin_x = 12 * mm
    margin_y = 15 * mm
    c.setTitle("Scoring Log Summary")

    y = height - margin_y
    c.setFont(font_name, 13)
    c.drawString(margin_x, y, "採点ログサマリ")
    y -= 18
    c.setFont(font_name, 9.5)

    grouped: Dict[Any, List[Mapping[str, Any]]] = {}
    for log in log_rows:
        key = (log.get("year"), log.get("case_label"), log.get("attempt_id"))
        grouped.setdefault(key, []).append(log)

    for key, items in grouped.items():
        if y < margin_y + 60:
            c.showPage()
            y = height - margin_y
            c.setFont(font_name, 9.5)
        year, case_label, attempt_id = key
        header = f"{year or '-'} {case_label or '-'} / Attempt {attempt_id}"
        c.setFont(font_name, 10.5)
        c.drawString(margin_x, y, header)
        y -= 14
        c.setFont(font_name, 9.5)
        for item in sorted(items, key=lambda row: row.get("question_order") or 0):
            info = (
                f"設問{item.get('question_order')}: {item.get('score')}/{item.get('max_score')}点"
                f" / キーワード網羅率 {item.get('keyword_coverage') and round(item.get('keyword_coverage') * 100, 1)}%"
            )
            c.drawString(margin_x + 4, y, info)
            y -= 12
            checkpoints = item.get("checkpoints") or {}
            keywords = checkpoints.get("keywords") or {}
            matched = "、".join(kw for kw, hit in keywords.items() if hit) or "-"
            missing = "、".join(kw for kw, hit in keywords.items() if not hit) or "-"
            detail = (
                f"自己評価: {item.get('self_evaluation') or '未評価'} / 所要時間: {_safe_minutes(item.get('duration_seconds')) or '-'}分"
            )
            c.drawString(margin_x + 8, y, detail)
            y -= 12
            c.drawString(margin_x + 8, y, f"含まれた: {matched}")
            y -= 12
            c.drawString(margin_x + 8, y, f"不足: {missing}")
            y -= 14
        y -= 6

    c.showPage()
    c.save()
    buffer.seek(0)
    return buffer.read()
