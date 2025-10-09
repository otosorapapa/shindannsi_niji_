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
    st.session_state.setdefault("mock_session", None)
    st.session_state.setdefault("past_data", None)


def main_view() -> None:
    user = st.session_state.user

    st.sidebar.title("ナビゲーション")
    st.session_state.page = st.sidebar.radio(
        "ページを選択",
        ["ホーム", "過去問演習", "模擬試験", "学習履歴", "設定"],
        index=["ホーム", "過去問演習", "模擬試験", "学習履歴", "設定"].index(st.session_state.page),
    )

    st.sidebar.divider()
    st.sidebar.info(f"利用者: {user['name']} ({user['plan']}プラン)")
    st.sidebar.caption(
        "必要な情報にすぐアクセスできるよう、ページ別にコンテンツを整理しています。"
    )

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
    overview_tab, chart_tab = st.tabs(["進捗サマリ", "事例別分析"])

    with overview_tab:
        if attempts:
            summary_df = pd.DataFrame(
                [
                    {
                        "実施日": row["submitted_at"].strftime("%Y-%m-%d")
                        if isinstance(row["submitted_at"], datetime)
                        else row["submitted_at"],
                        "年度": row["year"],
                        "事例": row["case_label"],
                        "モード": "模試" if row["mode"] == "mock" else "演習",
                        "得点": row["total_score"],
                        "満点": row["total_max_score"],
                    }
                    for row in attempts
                ]
            )
            st.data_editor(
                summary_df,
                use_container_width=True,
                hide_index=True,
                disabled=True,
            )
            st.caption("最近の受験結果を表形式で確認できます。列ヘッダーにマウスを合わせるとソートが可能です。")
        else:
            st.info("まだ演習結果がありません。『過去問演習』から学習を開始しましょう。")

    with chart_tab:
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
            st.info("演習データが蓄積すると事例別の分析が表示されます。")

    st.markdown(
        """
    ### 次のアクション
    - **過去問演習**: 年度・事例を指定して記述式回答を練習
    - **模擬試験**: 本番同様のケースを連続で解き、タイマー付きで実戦感覚を養成
    - **学習履歴**: これまでの得点推移やエクスポートを確認
    """
    )


def _draft_key(problem_id: int, question_id: int) -> str:
    return f"draft_{problem_id}_{question_id}"


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

    st.info(
        "左側のセレクターで年度・事例を切り替え、下部の解答欄から回答を入力してください。"
    )

    past_data_df = st.session_state.get("past_data")
    data_source = "database"
    if past_data_df is not None and not past_data_df.empty:
        source_labels = {"database": "データベース登録問題", "uploaded": "アップロードデータ"}
        data_source = st.radio(
            "利用する出題データ",
            options=list(source_labels.keys()),
            format_func=lambda key: source_labels[key],
        )

    if data_source == "uploaded":
        _practice_with_uploaded_data(past_data_df)
        return

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

    question_overview = pd.DataFrame(
        [
            {
                "設問": idx + 1,
                "配点": q["max_score"],
                "キーワード": "、".join(q["keywords"]) if q["keywords"] else "-",
            }
            for idx, q in enumerate(problem["questions"])
        ]
    )
    st.data_editor(
        question_overview,
        hide_index=True,
        use_container_width=True,
        disabled=True,
        column_config={
            "キーワード": st.column_config.TextColumn(help="採点で評価される重要ポイント"),
        },
    )
    st.caption("採点の観点を事前に確認してから回答に取り組みましょう。")

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
        with st.expander("採点ガイドライン", expanded=False):
            if question["keywords"]:
                st.markdown(
                    "**キーワード評価**:\n" + "、".join(question["keywords"]) + " を含めると加点対象です。"
                )
            st.markdown("**模範解答の背景**")
            st.write(question["model_answer"])
            st.caption(
                "模範解答は構成や論理展開の参考例です。キーワードを押さえつつ自分の言葉で表現しましょう。"
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


def _practice_with_uploaded_data(df: pd.DataFrame) -> None:
    if df is None or df.empty:
        st.info("アップロード済みの過去問データがありません。設定ページからファイルを登録してください。")
        return

    required_cols = {"年度", "事例", "設問番号", "問題文", "配点", "模範解答", "解説"}
    if not required_cols.issubset(df.columns):
        missing = required_cols.difference(set(df.columns))
        st.error(f"必要な列が不足しています: {', '.join(sorted(missing))}")
        return

    year_options = sorted(df["年度"].dropna().unique(), key=lambda x: str(x))
    if not year_options:
        st.warning("年度の値が見つかりませんでした。")
        return
    selected_year = st.selectbox("年度を選択", year_options, format_func=lambda x: str(x))

    case_options = sorted(
        df[df["年度"] == selected_year]["事例"].dropna().unique(),
        key=lambda x: str(x),
    )
    if not case_options:
        st.warning("選択した年度の事例が見つかりませんでした。")
        return
    selected_case = st.selectbox("事例を選択", case_options)

    subset = (
        df[(df["年度"] == selected_year) & (df["事例"] == selected_case)]
        .copy()
        .sort_values("設問番号")
    )

    if subset.empty:
        st.info("該当する設問がありません。")
        return

    for _, row in subset.iterrows():
        st.subheader(f"第{row['設問番号']}問 ({row['配点']}点)")
        st.write(row["問題文"])
        max_chars = 60 if pd.notna(row["配点"]) and row["配点"] <= 25 else 80
        answer_key = f"uploaded_answer_{selected_year}_{selected_case}_{row['設問番号']}"
        user_answer = st.text_area("回答を入力", key=answer_key)
        st.caption(f"現在の文字数: {len(user_answer)} / {max_chars}文字")
        if len(user_answer) > max_chars:
            st.warning("文字数が上限を超えています。")
        with st.expander("模範解答／解説を見る"):
            st.markdown("**模範解答**")
            st.write(row["模範解答"])
            st.markdown("**解説**")
            st.write(row["解説"])


def _handle_past_data_upload(uploaded_file) -> None:
    try:
        filename = uploaded_file.name.lower()
        if filename.endswith(".csv"):
            df = pd.read_csv(uploaded_file)
        elif filename.endswith(".xlsx") or filename.endswith(".xls"):
            df = pd.read_excel(uploaded_file)
        else:
            st.error("対応していないファイル形式です。CSVまたはExcelファイルを選択してください。")
            return
    except Exception as exc:  # pragma: no cover - Streamlit runtime feedback
        st.error(f"ファイルの読み込み中にエラーが発生しました: {exc}")
        return

    required_cols = {"年度", "事例", "設問番号", "問題文", "配点", "模範解答", "解説"}
    if not required_cols.issubset(df.columns):
        missing = required_cols.difference(set(df.columns))
        st.error(f"必要な列が含まれていません。不足列: {', '.join(sorted(missing))}")
        return

    st.session_state.past_data = df
    st.success("過去問データを読み込みました。『過去問演習』ページで利用できます。")


def render_attempt_results(attempt_id: int) -> None:
    detail = database.fetch_attempt_detail(attempt_id)
    attempt = detail["attempt"]
    answers = detail["answers"]

    st.subheader("採点結果")
    total_score = attempt["total_score"] or 0
    total_max = attempt["total_max_score"] or 0
    st.metric("総合得点", f"{total_score:.1f} / {total_max:.1f}")

    summary_rows = []
    for idx, answer in enumerate(answers, start=1):
        summary_rows.append(
            {
                "設問": idx,
                "得点": answer["score"],
                "満点": answer["max_score"],
                "キーワード達成": ", ".join(
                    [kw for kw, hit in (answer["keyword_hits"] or {}).items() if hit]
                )
                or "-",
            }
        )
    if summary_rows:
        st.data_editor(
            pd.DataFrame(summary_rows),
            hide_index=True,
            use_container_width=True,
            disabled=True,
        )
        st.caption("各設問の得点とキーワード達成状況を整理しました。弱点分析に活用してください。")

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
                st.caption("採点基準: 模範解答の論点とキーワードが盛り込まれているかを中心に評価しています。")

    st.info("学習履歴ページから過去の答案をいつでも振り返ることができます。")


def mock_exam_page(user: Dict) -> None:
    st.title("模擬試験モード")
    st.caption("事例I～IVをまとめて演習し、時間管理と一括採点を体験します。")

    session = st.session_state.mock_session

    if not session:
        st.subheader("模試セットを選択")
        exams = mock_exam.available_mock_exams()
        exam_options = {exam.title: exam for exam in exams}
        exam_options["ランダム演習セット"] = mock_exam.random_mock_exam()
        selected_title = st.selectbox("模試セット", list(exam_options.keys()))
        if st.button("模試を開始", type="primary"):
            selected_exam = exam_options[selected_title]
            st.session_state.mock_session = {
                "exam": selected_exam,
                "start": datetime.utcnow(),
                "answers": {},
            }
            st.experimental_rerun()
        return

    exam = session["exam"]
    start_time = session["start"]
    elapsed = datetime.utcnow() - start_time
    st.info(f"模試開始からの経過時間: {elapsed}")

    tabs = st.tabs([f"{idx+1}. {database.fetch_problem(problem_id)['case_label']}" for idx, problem_id in enumerate(exam.problem_ids)])
    for tab, problem_id in zip(tabs, exam.problem_ids):
        with tab:
            problem = database.fetch_problem(problem_id)
            st.subheader(problem["title"])
            st.write(problem["overview"])
            for question in problem["questions"]:
                key = _draft_key(problem_id, question["id"])
                st.session_state.drafts.setdefault(key, "")
                default = st.session_state.drafts[key]
                text = st.text_area(question["prompt"], key=f"mock_{key}", value=default, height=160)
                st.session_state.drafts[key] = text

    if st.button("模試を提出", type="primary"):
        overall_results = []
        for problem_id in exam.problem_ids:
            problem = database.fetch_problem(problem_id)
            answers: List[RecordedAnswer] = []
            for question in problem["questions"]:
                text = st.session_state.drafts.get(_draft_key(problem_id, question["id"]), "")
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
                started_at=start_time,
                submitted_at=datetime.utcnow(),
                duration_seconds=int((datetime.utcnow() - start_time).total_seconds()),
            )
            overall_results.append((problem, attempt_id))

        st.session_state.mock_session = None
        st.success("模擬試験の採点が完了しました。結果を確認してください。")
        for problem, attempt_id in overall_results:
            st.markdown(f"### {problem['year']} {problem['case_label']} {problem['title']}")
            render_attempt_results(attempt_id)


def history_page(user: Dict) -> None:
    st.title("学習履歴")
    st.caption("演習記録・得点推移・エクスポートを確認します。")

    history_records = database.fetch_learning_history(user["id"])
    if not history_records:
        st.info("まだ演習履歴がありません。演習を実施するとここに表示されます。")
        return

    history_df = pd.DataFrame(history_records)
    history_df["日付"] = pd.to_datetime(history_df["日付"], errors="coerce")
    history_df.sort_values("日付", inplace=True)

    unique_years = sorted(history_df["年度"].dropna().unique())
    unique_cases = sorted(history_df["事例"].dropna().unique())
    modes = {"practice": "演習", "mock": "模試"}

    filter_col1, filter_col2, filter_col3 = st.columns(3)
    with filter_col1:
        selected_years = st.multiselect("年度で絞り込む", options=unique_years)
    with filter_col2:
        selected_cases = st.multiselect("事例で絞り込む", options=unique_cases)
    with filter_col3:
        selected_modes = st.multiselect("モード", options=list(modes.keys()), format_func=lambda key: modes[key])

    filtered_df = history_df.copy()
    if selected_years:
        filtered_df = filtered_df[filtered_df["年度"].isin(selected_years)]
    if selected_cases:
        filtered_df = filtered_df[filtered_df["事例"].isin(selected_cases)]
    if selected_modes:
        selected_mode_labels = [modes[key] for key in selected_modes]
        filtered_df = filtered_df[filtered_df["モード"].isin(selected_mode_labels)]

    overview_tab, chart_tab, detail_tab = st.tabs(["一覧", "グラフ", "詳細・エクスポート"])

    with overview_tab:
        display_df = filtered_df.copy()
        display_df["日付"] = display_df["日付"].dt.strftime("%Y-%m-%d %H:%M")
        st.data_editor(
            display_df.drop(columns=["attempt_id"]),
            hide_index=True,
            use_container_width=True,
            disabled=True,
        )
        st.caption("複数条件でフィルタした演習履歴を確認できます。列名をクリックすると並び替えできます。")

    with chart_tab:
        score_history = filtered_df.dropna(subset=["得点", "日付"])
        if score_history.empty:
            st.info("選択した条件に該当する得点推移がありません。")
        else:
            line_chart = (
                alt.Chart(score_history)
                .mark_line(point=True)
                .encode(
                    x="日付:T",
                    y="得点:Q",
                    color="事例:N",
                    tooltip=["日付", "年度", "事例", "得点", "満点", "モード"],
                )
                .properties(height=320)
            )
            st.altair_chart(line_chart, use_container_width=True)

            avg_df = score_history.groupby("事例", as_index=False)["得点"].mean()
            st.subheader("事例別平均点")
            bar_chart = alt.Chart(avg_df).mark_bar().encode(x="事例:N", y="得点:Q")
            st.altair_chart(bar_chart, use_container_width=True)

    with detail_tab:
        csv_export = filtered_df.copy()
        csv_export["日付"] = csv_export["日付"].dt.strftime("%Y-%m-%d %H:%M:%S")
        csv_bytes = csv_export.drop(columns=["attempt_id"]).to_csv(index=False).encode("utf-8-sig")
        st.download_button(
            "CSVをダウンロード",
            data=csv_bytes,
            file_name="history.csv",
            mime="text/csv",
        )

        recent_history = filtered_df.dropna(subset=["日付"]).sort_values("日付", ascending=False)
        if recent_history.empty:
            st.info("詳細表示できる履歴がありません。フィルタ条件を変更してください。")
            return

        options = list(recent_history.index)
        selected_idx = st.selectbox(
            "詳細を確認する演習",
            options=options,
            format_func=lambda idx: f"{recent_history.loc[idx, '日付'].strftime('%Y-%m-%d %H:%M')} {recent_history.loc[idx, '年度']} {recent_history.loc[idx, '事例']}",
        )
        attempt_id = int(recent_history.loc[selected_idx, "attempt_id"])
        render_attempt_results(attempt_id)


def settings_page(user: Dict) -> None:
    st.title("設定・プラン管理")

    st.write(
        f"**ユーザー名:** {user['name']}\n"
        f"**メールアドレス:** {user['email']}\n"
        f"**契約プラン:** {user['plan']}"
    )

    st.subheader("データ管理")

    st.markdown(
        """
        過去問の得点記録をまとめたファイルをアップロードすると、学習履歴に取り込まれます。
        ドラッグ&ドロップまたはボタンからファイルを選択してください。
        """
    )

    st.markdown(
        """
        <style>
            div[data-testid="stFileUploadDropzone"] {
                padding: 3rem 1rem !important;
                border: 2px dashed var(--primary-color) !important;
                border-radius: 1rem !important;
                background-color: #f8fafc !important;
            }
            div[data-testid="stFileUploader"] section>div>div {
                justify-content: center;
            }
        </style>
        """,
        unsafe_allow_html=True,
    )

    helper_col, download_col = st.columns([2, 1])
    with helper_col:
        st.caption("CSV/Excel形式のいずれかに対応しています。1ファイルずつアップロードしてください。")
    with download_col:
        sample_df = pd.DataFrame(
            [
                {
                    "year": 2023,
                    "case": "事例I",
                    "question_id": 1,
                    "question_text": "環境分析に関する設問",
                    "answer": "中小企業の強みと弱みを整理した。",
                    "score": 55,
                    "max_score": 80,
                    "submitted_at": "2023-08-20 13:00",
                },
                {
                    "year": 2023,
                    "case": "事例II",
                    "question_id": 2,
                    "question_text": "ターゲット戦略に関する設問",
                    "answer": "主要顧客層のニーズ整理と差別化策を提案。",
                    "score": 60,
                    "max_score": 80,
                    "submitted_at": "2023-08-27 09:30",
                },
            ]
        )
        st.download_button(
            "サンプルCSVをダウンロード",
            data=sample_df.to_csv(index=False).encode("utf-8-sig"),
            file_name="past_data_sample.csv",
            mime="text/csv",
            help="フォーマット確認用のサンプルデータをダウンロードします。",
        )

    with st.expander("フォーマット例"):
        st.write(
            "各行は1つの設問への回答を表します。最低限、年度(year)、事例(case)、得点(score)、満点(max_score)、提出日時(submitted_at)の列をご用意ください。"
        )
        st.table(
            sample_df.rename(
                columns={
                    "year": "year (年度)",
                    "case": "case (事例)",
                    "question_id": "question_id (設問番号)",
                    "question_text": "question_text (設問内容)",
                    "answer": "answer (回答内容)",
                    "score": "score (得点)",
                    "max_score": "max_score (満点)",
                    "submitted_at": "submitted_at (提出日時)",
                }
            )
        )

    uploaded_file = st.file_uploader(
        "過去問データファイルをアップロード (CSV/Excel)",
        type=["csv", "xlsx"],
    )
    if uploaded_file is not None:
        _handle_past_data_upload(uploaded_file)

    if st.session_state.past_data is not None:
        st.caption(
            f"読み込み済みのレコード数: {len(st.session_state.past_data)}件"
        )
        st.dataframe(st.session_state.past_data.head(), use_container_width=True)
        if st.button("アップロードデータをクリア", key="clear_past_data"):
            st.session_state.past_data = None
            st.info("アップロードデータを削除しました。")

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
