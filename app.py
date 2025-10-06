from __future__ import annotations

from datetime import datetime
from typing import Dict, List

import altair as alt
import pandas as pd
import streamlit as st

import database
import mock_exam
import scoring
from database import RecordedAnswer
from scoring import QuestionSpec


def _init_session_state() -> None:
    if "user" not in st.session_state:
        guest = database.get_or_create_guest_user()
        st.session_state.user = dict(guest)
    st.session_state.setdefault("page", "ホーム")
    st.session_state.setdefault("drafts", {})
    st.session_state.setdefault("practice_started", None)
    st.session_state.setdefault("mock_queue", None)
    st.session_state.setdefault("mock_current_index", 0)
    st.session_state.setdefault("mock_started_at", None)
    st.session_state.setdefault("mock_selected_exam", None)
    st.session_state.setdefault("mock_answers", {})
    st.session_state.setdefault("mock_recent_results", [])


def main_view() -> None:
    user = st.session_state.user

    st.sidebar.title("ナビゲーション")
    st.session_state.page = st.sidebar.radio(
        "",
        ["ホーム", "過去問演習", "模擬試験", "学習履歴", "設定"],
        index=["ホーム", "過去問演習", "模擬試験", "学習履歴", "設定"].index(st.session_state.page),
    )

    st.sidebar.info(f"利用者: {user['name']} ({user['plan']}プラン)")

    page = st.session_state.page
    if page == "ホーム":
        dashboard_page(user)
    elif page == "過去問演習":
        practice_page(user)
    elif page == "模擬試験":
        mock_exam_page(user)
    elif page == "学習履歴":
        history_page(user)
    elif page == "設定":
        settings_page(user)


def dashboard_page(user: Dict) -> None:
    st.title("ホームダッシュボード")
    st.caption("学習状況のサマリと機能へのショートカット")

    attempts = database.list_attempts(user_id=user["id"])
    total_attempts = len(attempts)
    total_score = sum(row["total_score"] or 0 for row in attempts)
    total_max = sum(row["total_max_score"] or 0 for row in attempts)
    average_score = round(total_score / total_attempts, 1) if total_attempts else 0

    col1, col2, col3 = st.columns(3)
    col1.metric("演習回数", f"{total_attempts}回")
    col2.metric("平均得点", f"{average_score}点")
    completion_rate = (total_score / total_max * 100) if total_max else 0
    col3.metric("得点達成率", f"{completion_rate:.0f}%")

    stats = database.aggregate_statistics(user["id"])
    if stats:
        chart_data = []
        for case_label, values in stats.items():
            chart_data.append(
                {
                    "事例": case_label,
                    "得点": values["avg_score"],
                    "満点": values["avg_max"],
                }
            )
        df = pd.DataFrame(chart_data)
        st.subheader("事例別平均得点")
        chart = (
            alt.Chart(df)
            .transform_calculate(割合="datum.得点 / datum.満点 * 100")
            .mark_bar()
            .encode(x="事例", y="割合:Q", tooltip=["事例", "得点", "満点", "割合"])
        )
        st.altair_chart(chart, use_container_width=True)
    else:
        st.info("まだ演習結果がありません。『過去問演習』から学習を開始しましょう。")

    st.markdown("""
    ### 次のアクション
    - **過去問演習**: 年度・事例を指定して記述式回答を練習
    - **模擬試験**: 本番同様のケースを連続で解き、タイマー付きで実戦感覚を養成
    - **学習履歴**: これまでの得点推移やエクスポートを確認
    """)


def _draft_key(problem_id: int, question_id: int) -> str:
    return f"draft_{problem_id}_{question_id}"


def _reset_mock_exam_state() -> None:
    for key in list(st.session_state.keys()):
        if key.startswith("mock_answer_"):
            del st.session_state[key]
    st.session_state.mock_queue = None
    st.session_state.mock_current_index = 0
    st.session_state.mock_started_at = None
    st.session_state.mock_selected_exam = None
    st.session_state.mock_answers = {}


def _question_input(problem_id: int, question: Dict, disabled: bool = False) -> str:
    key = _draft_key(problem_id, question["id"])
    value = st.session_state.drafts.get(key, "")
    help_text = f"文字数目安: {question['character_limit']}字" if question["character_limit"] else ""
    text = st.text_area(
        label=question["prompt"],
        key=f"textarea_{key}",
        value=value,
        height=160,
        help=help_text,
        disabled=disabled,
    )
    st.caption(f"現在の文字数: {len(text)}字")
    st.session_state.drafts[key] = text
    return text


def practice_page(user: Dict) -> None:
    st.title("過去問演習")
    st.caption("年度と事例を選択して記述式演習を行います。")

    years = database.list_problem_years()
    if not years:
        st.warning("問題データが登録されていません。seed_problems.jsonを確認してください。")
        return
    selected_year = st.selectbox("年度", years)
    cases = database.list_problem_cases(selected_year)
    selected_case = st.selectbox("事例", cases)

    problem = database.fetch_problem_by_year_case(selected_year, selected_case)
    if not problem:
        st.error("問題を取得できませんでした。")
        return

    st.subheader(problem["title"])
    st.write(problem["overview"])

    if not st.session_state.practice_started:
        st.session_state.practice_started = datetime.utcnow()

    answers: List[RecordedAnswer] = []
    question_specs: List[QuestionSpec] = []
    for question in problem["questions"]:
        text = _question_input(problem["id"], question)
        question_specs.append(
            QuestionSpec(
                id=question["id"],
                prompt=question["prompt"],
                max_score=question["max_score"],
                model_answer=question["model_answer"],
                keywords=question["keywords"],
            )
        )

    col_save, col_submit = st.columns([1, 2])
    if col_save.button("下書きを保存"):
        st.success("下書きを保存しました。ブラウザを閉じても維持されます。")

    submitted = col_submit.button("AI採点に送信", type="primary")

    if submitted:
        answers = []
        for question, spec in zip(problem["questions"], question_specs):
            text = st.session_state.drafts.get(_draft_key(problem["id"], question["id"]), "")
            result = scoring.score_answer(text, spec)
            answers.append(
                RecordedAnswer(
                    question_id=question["id"],
                    answer_text=text,
                    score=result.score,
                    feedback=result.feedback,
                    keyword_hits=result.keyword_hits,
                )
            )

        submitted_at = datetime.utcnow()
        started_at = st.session_state.practice_started or submitted_at
        duration = int((submitted_at - started_at).total_seconds())

        attempt_id = database.record_attempt(
            user_id=user["id"],
            problem_id=problem["id"],
            mode="practice",
            answers=answers,
            started_at=started_at,
            submitted_at=submitted_at,
            duration_seconds=duration,
        )
        st.session_state.practice_started = None

        st.success("採点が完了しました。結果を確認してください。")
        render_attempt_results(attempt_id)


def render_attempt_results(attempt_id: int) -> None:
    detail = database.fetch_attempt_detail(attempt_id)
    attempt = detail["attempt"]
    answers = detail["answers"]

    st.subheader("採点結果")
    total_score = attempt["total_score"] or 0
    total_max = attempt["total_max_score"] or 0
    st.metric("総合得点", f"{total_score:.1f} / {total_max:.1f}")

    for idx, answer in enumerate(answers, start=1):
        with st.expander(f"設問{idx}の結果", expanded=True):
            st.write(f"**得点:** {answer['score']} / {answer['max_score']}")
            st.write("**フィードバック**")
            st.markdown(f"<pre>{answer['feedback']}</pre>", unsafe_allow_html=True)
            if answer["keyword_hits"]:
                keyword_df = pd.DataFrame(
                    [[kw, "○" if hit else "×"] for kw, hit in answer["keyword_hits"].items()],
                    columns=["キーワード", "判定"],
                )
                st.table(keyword_df)
            with st.expander("模範解答と解説", expanded=False):
                st.write("**模範解答**")
                st.write(answer["model_answer"])
                st.write("**解説**")
                st.write(answer["explanation"])

    st.info("学習履歴ページから過去の答案をいつでも振り返ることができます。")


def mock_exam_page(user: Dict) -> None:
    st.title("模擬試験モード")
    st.caption("事例I～IVをまとめて演習し、時間管理と一括採点を体験します。")

    queue: List[int] | None = st.session_state.mock_queue
    current_index: int = st.session_state.mock_current_index
    selected_exam = st.session_state.mock_selected_exam

    if not queue:
        if st.session_state.mock_recent_results:
            st.success("模擬試験の採点が完了しました。結果を確認してください。")
            for problem, attempt_id in st.session_state.mock_recent_results:
                st.markdown(
                    f"### {problem['year']} {problem['case_label']} {problem['title']}"
                )
                render_attempt_results(attempt_id)
            if st.button("結果を閉じる"):
                st.session_state.mock_recent_results = []
                st.experimental_rerun()

        st.subheader("模試セットを選択")
        exams = mock_exam.available_mock_exams()
        exam_options = {exam.title: exam for exam in exams}
        exam_options["ランダム演習セット"] = mock_exam.random_mock_exam()
        titles = list(exam_options.keys())
        selected_title = st.selectbox("模試セット", titles)
        if st.button("模試を開始", type="primary"):
            selected_exam = exam_options[selected_title]
            st.session_state.mock_selected_exam = selected_exam
            st.session_state.mock_queue = list(selected_exam.problem_ids)
            st.session_state.mock_current_index = 0
            st.session_state.mock_started_at = datetime.utcnow()
            st.session_state.mock_answers = {}
            st.session_state.mock_recent_results = []
            st.experimental_rerun()
        return

    if not selected_exam:
        st.error("模試情報を取得できませんでした。最初からやり直してください。")
        if st.button("模試をリセット"):
            _reset_mock_exam_state()
            st.session_state.mock_recent_results = []
            st.experimental_rerun()
        return

    started_at = st.session_state.mock_started_at or datetime.utcnow()
    elapsed = datetime.utcnow() - started_at
    st.info(f"模試開始からの経過時間: {elapsed}")

    total_cases = len(queue)
    if current_index < total_cases:
        problem_id = queue[current_index]
        problem = database.fetch_problem(problem_id)
        if not problem:
            st.error("問題データを取得できませんでした。")
            if st.button("模試をリセット"):
                _reset_mock_exam_state()
                st.experimental_rerun()
            return

        st.markdown(
            f"### {current_index + 1} / {total_cases}: {problem['year']}年度 {problem['case_label']}"
        )
        st.subheader(problem["title"])
        st.write(problem["overview"])

        for question in problem["questions"]:
            answer_key = f"mock_answer_{problem_id}_{question['id']}"
            if answer_key not in st.session_state:
                st.session_state[answer_key] = st.session_state.mock_answers.get(
                    answer_key, ""
                )
            text = st.text_area(
                question["prompt"],
                key=answer_key,
                height=160,
                help=f"配点: {question['max_score']}点",
            )
            st.caption(f"現在の文字数: {len(text)}字")
            st.session_state.mock_answers[answer_key] = text

        col_next, col_cancel = st.columns([2, 1])
        next_label = "次の事例へ進む" if current_index < total_cases - 1 else "模試を終了する"
        if col_next.button(next_label, type="primary"):
            st.session_state.mock_current_index += 1
            st.experimental_rerun()
        if col_cancel.button("模試を中断する"):
            _reset_mock_exam_state()
            st.session_state.mock_recent_results = []
            st.experimental_rerun()
        return

    st.success("模擬試験が終了しました。AI採点を実行してください。")
    col_submit, col_reset = st.columns([2, 1])
    if col_submit.button("AI採点を実行", type="primary"):
        overall_results = []
        for problem_id in queue:
            problem = database.fetch_problem(problem_id)
            if not problem:
                continue
            answers: List[RecordedAnswer] = []
            for question in problem["questions"]:
                answer_key = f"mock_answer_{problem_id}_{question['id']}"
                text = st.session_state.mock_answers.get(answer_key, "")
                result = scoring.score_answer(
                    text,
                    QuestionSpec(
                        id=question["id"],
                        prompt=question["prompt"],
                        max_score=question["max_score"],
                        model_answer=question["model_answer"],
                        keywords=question["keywords"],
                    ),
                )
                answers.append(
                    RecordedAnswer(
                        question_id=question["id"],
                        answer_text=text,
                        score=result.score,
                        feedback=result.feedback,
                        keyword_hits=result.keyword_hits,
                    )
                )
            attempt_id = database.record_attempt(
                user_id=user["id"],
                problem_id=problem_id,
                mode="mock",
                answers=answers,
                started_at=started_at,
                submitted_at=datetime.utcnow(),
                duration_seconds=int((datetime.utcnow() - started_at).total_seconds()),
            )
            overall_results.append((problem, attempt_id))

        st.session_state.mock_recent_results = overall_results
        _reset_mock_exam_state()
        st.experimental_rerun()

    if col_reset.button("模試をリセット"):
        _reset_mock_exam_state()
        st.session_state.mock_recent_results = []
        st.experimental_rerun()


def history_page(user: Dict) -> None:
    st.title("学習履歴")
    st.caption("演習記録・得点推移・エクスポートを確認します。")

    attempts = database.list_attempts(user["id"])
    if not attempts:
        st.info("まだ演習履歴がありません。演習を実施するとここに表示されます。")
        return

    df = pd.DataFrame(
        [
            {
                "提出日時": row["submitted_at"],
                "年度": row["year"],
                "事例": row["case_label"],
                "タイトル": row["title"],
                "得点": row["total_score"],
                "満点": row["total_max_score"],
                "モード": "模試" if row["mode"] == "mock" else "演習",
            }
            for row in attempts
        ]
    )

    st.dataframe(df)

    st.subheader("得点推移")
    chart = (
        alt.Chart(df.dropna(subset=["得点"])).mark_line(point=True).encode(
            x="提出日時:T",
            y="得点:Q",
            color="事例:N",
            tooltip=["提出日時", "年度", "事例", "得点", "満点"],
        )
    )
    st.altair_chart(chart, use_container_width=True)

    csv_bytes = df.to_csv(index=False).encode("utf-8-sig")
    st.download_button("CSVとしてエクスポート", data=csv_bytes, file_name="study_history.csv", mime="text/csv")

    selected_attempt = st.selectbox("詳細を確認する演習", options=list(range(len(attempts))), format_func=lambda idx: f"{df.iloc[idx]['提出日時']} {df.iloc[idx]['年度']} {df.iloc[idx]['事例']}")
    attempt_id = attempts[selected_attempt]["id"]
    render_attempt_results(attempt_id)


def settings_page(user: Dict) -> None:
    st.title("設定・プラン管理")

    st.write(
        f"**ユーザー名:** {user['name']}\n"
        f"**メールアドレス:** {user['email']}\n"
        f"**契約プラン:** {user['plan']}"
    )

    st.subheader("プラン変更")
    st.write("AI採点の回数制限を拡張し、詳細解説を無制限に閲覧できる有料プランをご用意しています。")
    if user["plan"] == "free":
        if st.button("有料プランにアップグレードする"):
            database.update_user_plan(user_id=user["id"], plan="premium")
            st.session_state.user = dict(database.get_user_by_email(user["email"]))
            st.success("プレミアムプランに変更しました。")
    else:
        st.info("既にプレミアムプランをご利用中です。")

    st.subheader("サポート")
    st.markdown("""
    - お問い合わせ: support@example.com
    - 利用規約: coming soon
    - 退会をご希望の場合はサポートまでご連絡ください。
    """)


if __name__ == "__main__":
    database.initialize_database()
    _init_session_state()
    main_view()
