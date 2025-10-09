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


def _inject_dashboard_styles() -> None:
    if st.session_state.get("_dashboard_styles_injected"):
        return

    st.markdown(
        """
        <style>
        [data-testid="stAppViewContainer"] {
            background: linear-gradient(180deg, #f3f6fb 0%, #ffffff 45%);
        }
        .block-container {
            padding-top: 1.2rem;
            padding-bottom: 3rem;
            max-width: 1100px;
        }
        .metric-row {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(210px, 1fr));
            gap: 1rem;
            margin-top: 1rem;
        }
        .metric-card {
            position: relative;
            border-radius: 18px;
            padding: 1.4rem;
            color: #0f172a;
            background: linear-gradient(135deg, rgba(255,255,255,0.95), rgba(241,245,249,0.95));
            border: 1px solid rgba(148, 163, 184, 0.35);
            box-shadow: 0 16px 30px rgba(15, 23, 42, 0.12);
        }
        .metric-card::after {
            content: "";
            position: absolute;
            inset: 1px;
            border-radius: 16px;
            border: 1px solid rgba(255,255,255,0.5);
        }
        .metric-card .metric-label {
            font-size: 0.9rem;
            font-weight: 600;
            color: #475569;
            letter-spacing: 0.04em;
            text-transform: uppercase;
        }
        .metric-card .metric-value {
            font-size: 2rem;
            font-weight: 700;
            margin: 0.4rem 0;
        }
        .metric-card .metric-desc {
            font-size: 0.85rem;
            color: #64748b;
            margin: 0;
        }
        .metric-card.indigo {
            background: linear-gradient(135deg, #2740ff, #4f74ff);
            color: #f8fafc;
        }
        .metric-card.indigo .metric-label,
        .metric-card.indigo .metric-desc {
            color: rgba(248, 250, 252, 0.85);
        }
        .metric-card.emerald {
            background: linear-gradient(135deg, #00b894, #4ade80);
            color: #0f172a;
        }
        .metric-card.orange {
            background: linear-gradient(135deg, #ff8a4c, #ffb347);
            color: #0f172a;
        }
        .metric-card.sky {
            background: linear-gradient(135deg, #38bdf8, #60a5fa);
            color: #0f172a;
        }
        .insight-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(250px, 1fr));
            gap: 1rem;
            margin: 1.5rem 0 0;
        }
        .insight-card {
            display: flex;
            gap: 1rem;
            align-items: center;
            border-radius: 18px;
            padding: 1.2rem 1.4rem;
            background: #ffffff;
            border: 1px solid rgba(148, 163, 184, 0.28);
            box-shadow: 0 20px 32px rgba(15, 23, 42, 0.12);
        }
        .insight-icon {
            font-size: 1.8rem;
        }
        .insight-title {
            font-weight: 600;
            margin: 0;
            color: #475569;
        }
        .insight-value {
            font-size: 1.35rem;
            font-weight: 700;
            margin: 0.2rem 0 0.3rem;
            color: #0f172a;
        }
        .insight-desc {
            font-size: 0.85rem;
            margin: 0;
            color: #64748b;
        }
        .action-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
            gap: 1rem;
            margin-top: 1rem;
        }
        .action-card {
            border-radius: 16px;
            padding: 1.2rem 1.3rem;
            background: linear-gradient(135deg, rgba(37,99,235,0.08), rgba(14,165,233,0.08));
            border: 1px solid rgba(148, 163, 184, 0.3);
            box-shadow: 0 12px 24px rgba(15, 23, 42, 0.08);
        }
        .action-card strong {
            display: block;
            font-size: 1.05rem;
            margin-bottom: 0.4rem;
            color: #1e293b;
        }
        .action-card p {
            margin: 0;
            font-size: 0.88rem;
            color: #475569;
        }
        .table-card {
            border-radius: 18px;
            padding: 1.2rem 1rem 0.6rem;
            background: rgba(255, 255, 255, 0.95);
            border: 1px solid rgba(226, 232, 240, 0.7);
            box-shadow: 0 10px 20px rgba(15, 23, 42, 0.08);
        }
        .stTabs [data-baseweb="tab-list"] {
            gap: 0.6rem;
            padding: 0.4rem;
            background: rgba(226, 232, 240, 0.5);
            border-radius: 999px;
        }
        .stTabs [data-baseweb="tab"] {
            border-radius: 999px;
            padding: 0.4rem 1.4rem;
            background: rgba(255,255,255,0.7);
            border: 1px solid transparent;
        }
        .stTabs [aria-selected="true"] {
            background: rgba(37, 99, 235, 0.14) !important;
            border-color: rgba(59, 130, 246, 0.4) !important;
            color: #1d4ed8 !important;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )
    st.session_state["_dashboard_styles_injected"] = True


def _format_datetime_label(value: datetime | str | None) -> str:
    if isinstance(value, datetime):
        return value.strftime("%Y年%m月%d日")
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value)
            return parsed.strftime("%Y年%m月%d日")
        except ValueError:
            return value
    return "記録なし"


def _format_duration_minutes(total_minutes: int) -> str:
    hours, minutes = divmod(total_minutes, 60)
    if hours and minutes:
        return f"{hours}時間{minutes}分"
    if hours:
        return f"{hours}時間"
    return f"{minutes}分"


def dashboard_page(user: Dict) -> None:
    _inject_dashboard_styles()

    st.title("ホームダッシュボード")
    st.caption("学習状況のサマリと機能へのショートカット")

    attempts = database.list_attempts(user_id=user["id"])
    total_attempts = len(attempts)
    total_score = sum(row["total_score"] or 0 for row in attempts)
    total_max = sum(row["total_max_score"] or 0 for row in attempts)
    average_score = round(total_score / total_attempts, 1) if total_attempts else 0
    completion_rate = (total_score / total_max * 100) if total_max else 0

    stats = database.aggregate_statistics(user["id"])
    total_learning_minutes = sum((row["duration_seconds"] or 0) for row in attempts) // 60

    best_case_label = None
    best_case_rate = 0.0
    if stats:
        case_ratios = [
            (case_label, (values["avg_score"] / values["avg_max"] * 100) if values["avg_max"] else 0)
            for case_label, values in stats.items()
        ]
        if case_ratios:
            best_case_label, best_case_rate = max(case_ratios, key=lambda item: item[1])

    metric_cards = [
        {
            "label": "演習回数",
            "value": f"{total_attempts}回",
            "desc": "これまで解いたケースの累計",
            "class": "indigo",
        },
        {
            "label": "平均得点",
            "value": f"{average_score}点",
            "desc": "全演習の平均スコア",
            "class": "sky",
        },
        {
            "label": "得点達成率",
            "value": f"{completion_rate:.0f}%",
            "desc": "満点に対する平均達成度",
            "class": "emerald",
        },
        {
            "label": "得意な事例",
            "value": best_case_label or "記録なし",
            "desc": f"平均達成率 {best_case_rate:.0f}%" if best_case_label else "データが蓄積されると表示されます",
            "class": "orange",
        },
    ]

    st.markdown(
        """
        <div class="metric-row">
        """
        + "\n".join(
            f"""
            <div class="metric-card {card['class']}">
                <div class="metric-label">{card['label']}</div>
                <div class="metric-value">{card['value']}</div>
                <p class="metric-desc">{card['desc']}</p>
            </div>
            """
            for card in metric_cards
        )
        + "\n</div>",
        unsafe_allow_html=True,
    )

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
            st.markdown('<div class="table-card">', unsafe_allow_html=True)
            st.data_editor(
                summary_df,
                use_container_width=True,
                hide_index=True,
                disabled=True,
            )
            st.markdown('</div>', unsafe_allow_html=True)
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
            df["達成率"] = df.apply(
                lambda row: row["得点"] / row["満点"] * 100 if row["満点"] else 0,
                axis=1,
            )
            st.subheader("事例別平均達成率")
            color_scale = alt.Scale(
                range=["#4f46e5", "#2563eb", "#0ea5e9", "#10b981", "#f97316", "#ec4899"],
            )
            bar = (
                alt.Chart(df)
                .mark_bar(cornerRadiusTopRight=8, cornerRadiusBottomRight=8)
                .encode(
                    y=alt.Y("事例:N", sort="-x", title=None),
                    x=alt.X("達成率:Q", scale=alt.Scale(domain=[0, 100]), title="平均達成率 (%)"),
                    color=alt.Color("事例:N", scale=color_scale, legend=None),
                    tooltip=["事例", "得点", "満点", alt.Tooltip("達成率:Q", format=".1f")],
                )
            )
            target_line = (
                alt.Chart(pd.DataFrame({"ベンチマーク": [60]}))
                .mark_rule(color="#f97316", strokeDash=[6, 4])
                .encode(x="ベンチマーク:Q")
            )
            st.altair_chart(bar + target_line, use_container_width=True)
        else:
            st.info("演習データが蓄積すると事例別の分析が表示されます。")

    latest_attempt = attempts[0] if attempts else None
    next_focus_card = {
        "icon": "🎯",
        "title": "次に集中すべき事例",
        "value": "最初の演習を始めましょう",
        "desc": "演習を完了すると優先度が表示されます。",
    }
    if stats:
        focus_case_label = None
        focus_rate = None
        for case_label, values in stats.items():
            if not values["avg_max"]:
                continue
            ratio = values["avg_score"] / values["avg_max"] * 100
            if focus_rate is None or ratio < focus_rate:
                focus_rate = ratio
                focus_case_label = case_label
        if focus_case_label:
            next_focus_card = {
                "icon": "🎯",
                "title": "次に集中すべき事例",
                "value": focus_case_label,
                "desc": f"平均達成率 {focus_rate:.0f}%。重点復習で底上げしましょう。",
            }

    learning_time_card = {
        "icon": "⏱️",
        "title": "累計学習時間",
        "value": _format_duration_minutes(total_learning_minutes),
        "desc": "記録された演習・模試の回答時間の合計",
    }
    if total_learning_minutes == 0:
        learning_time_card["value"] = "0分"
        learning_time_card["desc"] = "初回の演習で学習時間を記録しましょう。"

    latest_result_card = {
        "icon": "📈",
        "title": "直近の結果",
        "value": "データなし",
        "desc": "演習を完了すると最新結果が表示されます。",
    }
    if latest_attempt:
        latest_score = latest_attempt["total_score"] or 0
        latest_max = latest_attempt["total_max_score"] or 0
        latest_ratio = (latest_score / latest_max * 100) if latest_max else 0
        latest_result_card = {
            "icon": "📈",
            "title": "直近の結果",
            "value": f"{latest_score:.0f} / {latest_max:.0f}点 ({latest_ratio:.0f}%)",
            "desc": f"{_format_datetime_label(latest_attempt['submitted_at'])} 実施",
        }

    st.markdown(
        """
        <div class="insight-grid">
        """
        + "\n".join(
            f"""
            <div class="insight-card">
                <div class="insight-icon">{card['icon']}</div>
                <div>
                    <p class="insight-title">{card['title']}</p>
                    <p class="insight-value">{card['value']}</p>
                    <p class="insight-desc">{card['desc']}</p>
                </div>
            </div>
            """
            for card in [next_focus_card, learning_time_card, latest_result_card]
        )
        + "\n</div>",
        unsafe_allow_html=True,
    )

    st.markdown(
        """
        ### 次のアクション
        <div class="action-grid">
            <div class="action-card">
                <strong>過去問演習</strong>
                <p>年度・事例を指定して弱点補強の演習を行いましょう。</p>
            </div>
            <div class="action-card">
                <strong>模擬試験</strong>
                <p>タイマー付きの本番形式で得点力とタイムマネジメントを鍛えます。</p>
            </div>
            <div class="action-card">
                <strong>学習履歴</strong>
                <p>得点推移を可視化し、改善の兆しや課題を振り返りましょう。</p>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
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
