from __future__ import annotations

from collections import defaultdict
from datetime import date as dt_date, datetime, time as dt_time, timedelta
from textwrap import dedent
from typing import Any, Dict, List, Optional
import logging

import html

import random

import altair as alt
import pandas as pd
import streamlit as st

import database
import mock_exam
import scoring
from database import RecordedAnswer
from scoring import QuestionSpec


DEFAULT_KEYWORD_RESOURCES = [
    {
        "label": "中小企業診断協会: 2次試験過去問題", 
        "url": "https://www.j-smeca.or.jp/contents/0105007000.html",
    },
    {
        "label": "中小企業診断士ポータル: キーワード整理", 
        "url": "https://www.smeca.jp/consultant/exam/keyword.html",
    },
]


KEYWORD_RESOURCE_MAP = {
    "製造技術": [
        {
            "label": "運営管理テキスト 製造工程編",
            "url": "https://www.j-smeca.or.jp/contents/0105005000.html",
        },
    ],
    "信頼関係": [
        {
            "label": "組織・人事: 顧客との関係構築 事例解説",
            "url": "https://www.j-smeca.or.jp/contents/0105003000.html",
        },
    ],
    "高付加価値": [
        {
            "label": "経営戦略: 付加価値向上の施策",
            "url": "https://www.smrj.go.jp/diagnosis/",
        },
    ],
    "企画開発": [
        {
            "label": "新製品開発ロードマップ",
            "url": "https://www.jetro.go.jp/ext_images/jfile/report/07000648/report.pdf",
        },
    ],
    "技能伝承": [
        {
            "label": "技能伝承のポイント (厚労省)",
            "url": "https://www.mhlw.go.jp/stf/seisakunitsuite/bunya/0000084967.html",
        },
    ],
    "評価制度": [
        {
            "label": "人事評価制度設計ガイド",
            "url": "https://www.jil.go.jp/institute/",
        },
    ],
    "モチベーション": [
        {
            "label": "モチベーション理論と組織活性化",
            "url": "https://www.hataraku.metro.tokyo.lg.jp/sodan/itaku/",
        },
    ],
    "連携": [
        {
            "label": "地域連携によるサービス開発事例",
            "url": "https://www.chusho.meti.go.jp/",
        },
    ],
    "口コミ": [
        {
            "label": "マーケティング: 口コミ活用施策",
            "url": "https://www.smrj.go.jp/feature/",
        },
    ],
    "ROA": [
        {
            "label": "財務指標の読み方: ROA",
            "url": "https://www.jcci.or.jp/chusho/finance/",
        },
    ],
    "固定資産回転率": [
        {
            "label": "財務分析: 回転率の捉え方",
            "url": "https://www.jetro.go.jp/world/",
        },
    ],
    "キャッシュフロー": [
        {
            "label": "キャッシュフロー計算書の読み方",
            "url": "https://www.japaneselawtranslation.go.jp/",
        },
    ],
    "資本コスト": [
        {
            "label": "資本コストと投資判断入門",
            "url": "https://www.mof.go.jp/public_relations/finance/",
        },
    ],
}


def _init_session_state() -> None:
    if "user" not in st.session_state:
        guest = database.get_or_create_guest_user()
        st.session_state.user = dict(guest)
    st.session_state.setdefault("page", "ホーム")
    st.session_state.setdefault("drafts", {})
    st.session_state.setdefault("saved_answers", {})
    st.session_state.setdefault("practice_started", None)
    st.session_state.setdefault("mock_session", None)
    st.session_state.setdefault("past_data", None)
    st.session_state.setdefault("flashcard_states", {})


def _guideline_visibility_key(problem_id: int, question_id: int) -> str:
    return f"guideline_visible::{problem_id}::{question_id}"


def _inject_guideline_styles() -> None:
    if st.session_state.get("_guideline_styles_injected"):
        return

    st.markdown(
        """
        <style>
        .guideline-card {
            margin: 0.5rem 0 1.5rem;
            padding: 1.1rem 1.25rem;
            border-radius: 14px;
            border: 1px solid rgba(148, 163, 184, 0.35);
            background: rgba(248, 250, 252, 0.8);
            box-shadow: 0 12px 24px rgba(15, 23, 42, 0.08);
        }
        .guideline-card .guideline-heading {
            font-weight: 700;
            font-size: 0.95rem;
            color: #1f2937;
            margin-bottom: 0.25rem;
        }
        .guideline-card .guideline-body {
            margin: 0 0 0.8rem;
            color: #334155;
            line-height: 1.6;
        }
        .guideline-card .guideline-section + .guideline-section {
            margin-top: 0.6rem;
        }
        .guideline-card .guideline-body:last-child {
            margin-bottom: 0;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )
    st.session_state["_guideline_styles_injected"] = True


def main_view() -> None:
    user = st.session_state.user

    navigation_items = {
        "ホーム": dashboard_page,
        "過去問演習": practice_page,
        "模擬試験": mock_exam_page,
        "学習履歴": history_page,
        "設定": settings_page,
    }

    st.sidebar.title("ナビゲーション")
    st.sidebar.markdown(
        dedent(
            """
            <style>
            section[data-testid="stSidebar"] div[role="radiogroup"] > label[data-baseweb="radio"] {
                margin-bottom: 0.3rem;
            }
            section[data-testid="stSidebar"] div[role="radiogroup"] > label[data-baseweb="radio"] > div:first-child {
                display: none;
            }
            section[data-testid="stSidebar"] div[role="radiogroup"] > label[data-baseweb="radio"] > div:last-child {
                width: 100%;
                padding: 0.5rem 0.75rem;
                border-radius: 0.6rem;
                border: 1px solid transparent;
                transition: background-color 0.2s ease, border-color 0.2s ease, color 0.2s ease;
            }
            section[data-testid="stSidebar"] div[role="radiogroup"] > label[data-baseweb="radio"] > div:last-child:hover {
                border-color: rgba(49, 51, 63, 0.2);
                background-color: rgba(49, 51, 63, 0.05);
            }
            section[data-testid="stSidebar"] div[role="radiogroup"] > label[data-baseweb="radio"] > input:checked + div {
                background-color: rgba(49, 51, 63, 0.06);
                border-color: var(--primary-color);
                color: var(--primary-color);
                box-shadow: 0 0 0 1px var(--primary-color) inset;
                font-weight: 600;
            }
            </style>
            """
        ).strip(),
        unsafe_allow_html=True,
    )

    nav_labels = list(navigation_items.keys())
    if st.session_state.page not in navigation_items:
        st.session_state.page = nav_labels[0]

    selected_index = nav_labels.index(st.session_state.page)
    st.session_state.page = st.sidebar.radio(
        "ページを選択",
        nav_labels,
        index=selected_index,
    )

    st.sidebar.divider()
    st.sidebar.info(f"利用者: {user['name']} ({user['plan']}プラン)")
    st.sidebar.caption(
        "必要な情報にすぐアクセスできるよう、ページ別にコンテンツを整理しています。"
    )

    page = st.session_state.page
    navigation_items[page](user)


def _inject_dashboard_styles() -> None:
    if st.session_state.get("_dashboard_styles_injected"):
        return

    st.markdown(
        dedent(
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
            """
        ).strip(),
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
    gamification = _calculate_gamification(attempts)
    total_attempts = len(attempts)
    total_score = sum(row["total_score"] or 0 for row in attempts)
    total_max = sum(row["total_max_score"] or 0 for row in attempts)
    average_score = round(total_score / total_attempts, 1) if total_attempts else 0
    completion_rate = (total_score / total_max * 100) if total_max else 0

    point_col, streak_col, badge_col = st.columns([1, 1, 2])
    with point_col:
        st.metric("累計ポイント", f"{gamification['points']} pt")
        level_progress = 0.0
        if gamification["level_threshold"]:
            level_progress = gamification["level_progress"] / gamification["level_threshold"]
        st.progress(min(level_progress, 1.0))
        if gamification["points"] == 0:
            st.caption("演習を実施するとポイントが貯まりレベルアップします。")
        else:
            st.caption(
                f"レベル{gamification['level']} / 次のレベルまであと {gamification['points_to_next_level']} pt"
            )
    with streak_col:
        st.metric("連続学習日数", f"{gamification['current_streak']}日")
        if gamification["next_milestone"]:
            progress = gamification["attempts"] / gamification["next_milestone"]
            st.progress(min(progress, 1.0))
            st.caption(
                f"次の称号まであと {max(gamification['next_milestone'] - gamification['attempts'], 0)} 回の演習"
            )
        else:
            st.caption("最高ランクに到達しました！継続おめでとうございます。")
    with badge_col:
        st.subheader("獲得バッジ")
        if gamification["badges"]:
            for badge in gamification["badges"]:
                st.markdown(f"- 🏅 **{badge['title']}** — {badge['description']}")
        else:
            st.caption("バッジはまだありません。演習や模試で獲得を目指しましょう。")

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

    card_blocks = "\n".join(
        dedent(
            f"""
            <div class="metric-card {card['class']}">
                <div class="metric-label">{card['label']}</div>
                <div class="metric-value">{card['value']}</div>
                <p class="metric-desc">{card['desc']}</p>
            </div>
            """
        ).strip()
        for card in metric_cards
    )
    st.markdown(
        dedent(
            f"""
            <div class="metric-row">
            {card_blocks}
            </div>
            """
        ).strip(),
        unsafe_allow_html=True,
    )

    upcoming_reviews = database.list_upcoming_reviews(user_id=user["id"], limit=6)
    due_review_count = database.count_due_reviews(user_id=user["id"])
    st.subheader("復習スケジュール（間隔反復）")
    if upcoming_reviews:
        if due_review_count:
            st.warning(
                f"{due_review_count}件の復習が期限到来または超過しています。優先的に取り組みましょう。",
                icon="⏳",
            )
        schedule_df = pd.DataFrame(
            [
                {
                    "次回予定": review["due_at"].strftime("%Y-%m-%d"),
                    "事例": f"{review['year']} {review['case_label']}",
                    "タイトル": review["title"],
                    "前回達成度": f"{(review['last_score_ratio'] or 0) * 100:.0f}%",
                    "間隔": f"{review['interval_days']}日",
                    "ステータス": "要復習" if review["due_at"] <= datetime.utcnow() else "予定",
                }
                for review in upcoming_reviews
            ]
        )
        st.data_editor(
            schedule_df,
            hide_index=True,
            use_container_width=True,
            disabled=True,
        )
        st.caption("演習結果に応じて次回の復習タイミングを自動で提案します。")
    else:
        st.info("演習データが蓄積されると復習スケジュールがここに表示されます。")

    st.subheader("AI推奨の学習順序")
    recommendations = database.recommend_learning_sequence(user_id=user["id"], limit=6)
    if recommendations:
        recommendation_df = pd.DataFrame(
            [
                {
                    "優先度": idx + 1,
                    "事例": f"{item['year']} {item['case_label']}",
                    "タイトル": item["title"],
                    "目安期限": item["due_at"].strftime("%Y-%m-%d") if item["due_at"] else "ー",
                    "推奨アクション": "復習" if item.get("avg_ratio") is not None else "初回演習",
                    "理由": " / ".join(item["reasons"]),
                }
                for idx, item in enumerate(recommendations)
            ]
        )
        st.data_editor(
            recommendation_df,
            hide_index=True,
            use_container_width=True,
            disabled=True,
        )
        st.caption(
            "得点推移・設問ごとの達成度・復習期限を加味して、次に取り組むと効果的な順序をAIが提案します。"
        )
    else:
        st.info("演習履歴が蓄積されるとAIが優先順を提案します。")

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

    insight_cards = "\n".join(
        dedent(
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
        ).strip()
        for card in [next_focus_card, learning_time_card, latest_result_card]
    )
    st.markdown(
        dedent(
            f"""
            <div class="insight-grid">
            {insight_cards}
            </div>
            """
        ).strip(),
        unsafe_allow_html=True,
    )

    st.markdown(
        dedent(
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
            """
        ).strip(),
        unsafe_allow_html=True,
    )


def _calculate_gamification(attempts: List[Dict]) -> Dict[str, object]:
    if not attempts:
        return {
            "attempts": 0,
            "current_streak": 0,
            "badges": [],
            "next_milestone": 3,
            "points": 0,
            "level": 1,
            "level_progress": 0,
            "level_threshold": 100,
            "points_to_next_level": 100,
        }

    parsed_attempts = []
    for row in attempts:
        submitted_at = row.get("submitted_at")
        if isinstance(submitted_at, datetime):
            parsed_attempts.append(submitted_at)
        elif submitted_at:
            try:
                parsed_attempts.append(datetime.fromisoformat(submitted_at))
            except ValueError:
                continue

    unique_dates = sorted({dt.date() for dt in parsed_attempts}, reverse=True)
    streak = 0
    previous_date = None
    for current in unique_dates:
        if previous_date is None:
            streak = 1
        else:
            gap = (previous_date - current).days
            if gap == 1:
                streak += 1
            elif gap > 1:
                break
        previous_date = current

    best_ratio = 0.0
    mock_clears = 0
    high_mock_scores = 0
    badges: List[Dict[str, str]] = []
    total_attempts = len(attempts)
    points = 0
    level_threshold = 100
    for row in attempts:
        total = row.get("total_score") or 0
        maximum = row.get("total_max_score") or 0
        ratio = (total / maximum) if maximum else 0
        best_ratio = max(best_ratio, ratio)
        mode = row.get("mode")
        if mode == "mock":
            points += 40
            if ratio >= 0.7:
                mock_clears += 1
            if ratio >= 0.85:
                high_mock_scores += 1
        else:
            points += 20
        if ratio >= 0.8:
            points += 10
        elif ratio >= 0.6:
            points += 5

    points += streak * 2

    if total_attempts >= 1:
        badges.append({"title": "スタートダッシュ", "description": "初めての演習を完了しました"})
    if streak >= 3:
        badges.append({"title": "連続学習3日達成", "description": "継続学習のリズムが身についています"})
    if streak >= 7:
        badges.append({"title": "週間皆勤", "description": "7日連続で学習を継続しました"})
    if mock_clears:
        badges.append({"title": "模擬試験クリア", "description": "模擬試験で70%の得点を獲得しました"})
    if best_ratio >= 0.85:
        badges.append({"title": "ハイスコア達人", "description": "高得点を獲得し自信が高まりました"})
    if total_attempts >= 10:
        badges.append({"title": "継続学習バッジ", "description": "演習を積み重ね学習の習慣化が進んでいます"})
    if high_mock_scores:
        badges.append({"title": "優秀回答者バッジ", "description": "模試で高得点を記録しました"})

    milestones = [3, 7, 15, 30]
    next_milestone = None
    for milestone in milestones:
        if total_attempts < milestone:
            next_milestone = milestone
            break

    level = points // level_threshold + 1
    level_progress = points % level_threshold
    points_to_next_level = level_threshold - level_progress if level_progress else level_threshold

    return {
        "attempts": total_attempts,
        "current_streak": streak,
        "badges": badges,
        "next_milestone": next_milestone,
        "points": points,
        "level": level,
        "level_progress": level_progress,
        "level_threshold": level_threshold,
        "points_to_next_level": points_to_next_level,
    }


def _draft_key(problem_id: int, question_id: int) -> str:
    return f"draft_{problem_id}_{question_id}"


def _render_character_counter(current_length: int, limit: Optional[int]) -> None:
    remaining_text: str
    if limit is None:
        st.caption(f"現在の文字数: {current_length}字")
        return

    remaining = limit - current_length
    if remaining >= 0:
        remaining_text = f"残り {remaining}字"
    else:
        remaining_text = f"{abs(remaining)}字オーバー"

    st.caption(f"文字数: {current_length} / {limit}字（{remaining_text}）")
    if remaining < 0:
        st.warning("文字数が上限を超えています。")


def _question_input(problem_id: int, question: Dict, disabled: bool = False) -> str:
    key = _draft_key(problem_id, question["id"])
    if key not in st.session_state.drafts:
        saved_default = st.session_state.saved_answers.get(key, "")
        st.session_state.drafts[key] = saved_default
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
    _render_character_counter(len(text), question.get("character_limit"))
    st.caption("入力内容は自動的に保存され、ページ離脱後も保持されます。必要に応じて下書きを明示的に保存してください。")
    st.session_state.drafts[key] = text
    status_placeholder = st.empty()
    action_save, action_apply = st.columns([1, 1])
    if action_save.button("回答を保存する", key=f"save_{key}"):
        st.session_state.saved_answers[key] = text
        st.session_state.drafts[key] = text
        status_placeholder.success("回答を保存しました。")
    if action_apply.button("保存内容を適用", key=f"apply_{key}"):
        saved_text = st.session_state.saved_answers.get(key)
        if saved_text is None:
            status_placeholder.warning("保存済みの回答がありません。")
        else:
            st.session_state.drafts[key] = saved_text
            st.session_state[f"textarea_{key}"] = saved_text
            status_placeholder.info("保存した回答を入力欄に適用しました。")
    return text


def _reset_flashcard_state(problem_id: int, size: int) -> Dict[str, Any]:
    order = list(range(size))
    random.shuffle(order)
    state = {"order": order, "index": 0, "revealed": False, "size": size}
    st.session_state.flashcard_states[str(problem_id)] = state
    return state


def _get_flashcard_state(problem_id: int, size: int) -> Dict[str, Any]:
    key = str(problem_id)
    state = st.session_state.flashcard_states.get(key)
    if not state or state.get("size") != size:
        state = _reset_flashcard_state(problem_id, size)
    return state


def _render_retrieval_flashcards(problem: Dict) -> None:
    flashcards: List[Dict[str, Any]] = []
    for index, question in enumerate(problem.get("questions", [])):
        keywords = [kw for kw in question.get("keywords", []) if kw]
        if not keywords:
            continue
        flashcards.append(
            {
                "title": f"設問{index + 1}: キーワード想起クイズ",
                "prompt": question.get("prompt", ""),
                "keywords": keywords,
            }
        )

    if not flashcards:
        st.info("この問題ではキーワードが登録されていないため、フラッシュカードを生成できません。")
        return

    st.subheader("リトリーバル・プラクティス")
    st.caption(
        "回答作成の前に、設問の重要キーワードを記憶から呼び起こしましょう。"
        " 思い出しの練習（retrieval practice）は再読よりも記憶定着を高めるとされています。"
    )

    state = _get_flashcard_state(problem["id"], len(flashcards))

    card_placeholder = st.container()
    button_placeholder = st.container()

    with button_placeholder:
        col_reveal, col_next, col_shuffle = st.columns(3)
        reveal_clicked = col_reveal.button("キーワードを表示", key=f"flashcard_reveal_{problem['id']}")
        next_clicked = col_next.button("次のカードへ", key=f"flashcard_next_{problem['id']}")
        shuffle_clicked = col_shuffle.button("カードを再シャッフル", key=f"flashcard_shuffle_{problem['id']}")

    if shuffle_clicked:
        state = _reset_flashcard_state(problem["id"], len(flashcards))
    else:
        if next_clicked:
            state["index"] = (state["index"] + 1) % len(state["order"])
            state["revealed"] = False
        if reveal_clicked:
            state["revealed"] = True

    st.session_state.flashcard_states[str(problem["id"])] = state

    order = state["order"]
    current_position = state["index"]
    card = flashcards[order[current_position]]

    with card_placeholder:
        st.markdown(f"**カード {current_position + 1} / {len(flashcards)}**")
        st.write(card["title"])
        card_html = f"""
        <div style='padding:0.75rem 1rem;border:1px solid #CBD5E1;border-radius:0.75rem;background-color:#F8FAFC;'>
            <p style='margin:0;color:#1E293B;font-weight:600;'>設問の概要</p>
            <p style='margin:0.35rem 0 0;color:#334155;'>{card['prompt']}</p>
            <p style='margin:0.75rem 0 0;color:#64748B;'>キーワードを声に出すか、メモに書き出してみてください。</p>
        </div>
        """
        st.markdown(card_html, unsafe_allow_html=True)
        if state["revealed"]:
            st.success("\n".join(f"・{keyword}" for keyword in card["keywords"]))
        else:
            st.info("キーワードを思い出したら、上のボタンから答え合わせをしましょう。")




def _compute_learning_stats(history_df: pd.DataFrame) -> Dict[str, Any]:
    stats: Dict[str, Any] = {"total_sessions": int(len(history_df))}
    if history_df.empty:
        now = datetime.now()
        stats.update(
            {
                "recent_average": None,
                "best_score": None,
                "streak_days": 0,
                "last_study_at": None,
                "recommended_interval": 3,
                "next_study_at": now + timedelta(days=3),
                "reference_datetime": now,
            }
        )
        return stats

    sorted_dates = history_df.dropna(subset=["日付"]).sort_values("日付")["日付"]
    python_dates = [
        value.to_pydatetime() if hasattr(value, "to_pydatetime") else value for value in sorted_dates
    ]
    last_study_at = python_dates[-1]

    intervals = sorted_dates.diff().dropna()
    intervals_days = intervals.dt.total_seconds() / (60 * 60 * 24)
    intervals_days = intervals_days[intervals_days > 0]
    recommended_interval = int(round(intervals_days.median())) if not intervals_days.empty else 3
    recommended_interval = max(1, recommended_interval)
    next_study_at = last_study_at + timedelta(days=recommended_interval)

    unique_days = sorted({value.date() for value in python_dates})
    streak = 0
    previous_day: Optional[dt_date] = None
    for day in reversed(unique_days):
        if previous_day is None:
            streak = 1
        else:
            if (previous_day - day).days == 1:
                streak += 1
            else:
                break
        previous_day = day

    recent_scores = history_df["得点"].dropna().tail(5)
    recent_average = float(recent_scores.mean()) if not recent_scores.empty else None
    best_score = float(history_df["得点"].dropna().max()) if history_df["得点"].notna().any() else None

    stats.update(
        {
            "recent_average": recent_average,
            "best_score": best_score,
            "streak_days": streak,
            "last_study_at": last_study_at,
            "recommended_interval": recommended_interval,
            "next_study_at": next_study_at,
            "reference_datetime": last_study_at,
        }
    )
    return stats


def _calculate_level(total_experience: float) -> Dict[str, float]:
    level = 1
    xp_needed = 200.0
    xp_floor = 0.0
    xp_remaining = float(total_experience)

    while xp_remaining >= xp_needed:
        xp_remaining -= xp_needed
        xp_floor += xp_needed
        level += 1
        xp_needed = 200.0 + (level - 1) * 120.0

    progress_ratio = 0.0
    if xp_needed > 0:
        progress_ratio = max(0.0, min(1.0, xp_remaining / xp_needed))

    return {
        "level": level,
        "total_experience": total_experience,
        "current_level_floor": xp_floor,
        "next_level_cap": xp_floor + xp_needed,
        "xp_into_level": xp_remaining,
        "xp_to_next_level": max(xp_needed - xp_remaining, 0.0),
        "next_level_requirement": xp_needed,
        "progress_ratio": progress_ratio,
    }


def _compute_progress_overview(history_df: pd.DataFrame) -> Dict[str, Any]:
    problems = database.list_problems()
    total_pairs = {
        (row["year"], row["case_label"])
        for row in problems
        if row["year"] and row["case_label"]
    }

    year_totals: Dict[str, set] = defaultdict(set)
    case_totals: Dict[str, set] = defaultdict(set)
    for row in problems:
        year = row["year"]
        case_label = row["case_label"]
        if not year or not case_label:
            continue
        year_totals[year].add(case_label)
        case_totals[case_label].add(year)

    completed_pairs: set = set()
    pair_bonus_awarded: set = set()
    total_experience = 0.0

    if not history_df.empty:
        for _, record in history_df.iterrows():
            score = record.get("得点")
            max_score = record.get("満点")
            mode_label = record.get("モード")
            year = record.get("年度")
            case_label = record.get("事例")

            base_xp = 120.0 if mode_label == "模試" else 100.0
            ratio = 0.0
            if pd.notna(score) and pd.notna(max_score) and max_score:
                try:
                    ratio = max(0.0, min(1.0, float(score) / float(max_score)))
                except (TypeError, ZeroDivisionError):
                    ratio = 0.0
            total_experience += base_xp + ratio * 100.0

            if isinstance(year, str) and isinstance(case_label, str):
                pair = (year, case_label)
                if pair in total_pairs:
                    completed_pairs.add(pair)
                    if pair not in pair_bonus_awarded:
                        total_experience += 40.0
                        pair_bonus_awarded.add(pair)

    year_progress = []
    for year in sorted(year_totals.keys(), reverse=True):
        total_count = len(year_totals[year])
        completed_count = len({case for (y, case) in completed_pairs if y == year})
        ratio = completed_count / total_count if total_count else 0.0
        year_progress.append(
            {
                "label": year,
                "completed": completed_count,
                "total": total_count,
                "ratio": max(0.0, min(1.0, ratio)),
            }
        )

    case_progress = []
    for case_label in sorted(case_totals.keys()):
        total_count = len(case_totals[case_label])
        completed_count = len({y for (y, c) in completed_pairs if c == case_label})
        ratio = completed_count / total_count if total_count else 0.0
        case_progress.append(
            {
                "label": case_label,
                "completed": completed_count,
                "total": total_count,
                "ratio": max(0.0, min(1.0, ratio)),
            }
        )

    overall_total = len(total_pairs)
    overall_completed = len(completed_pairs)
    overall_ratio = overall_completed / overall_total if overall_total else 0.0

    level_info = _calculate_level(total_experience)

    return {
        "experience": total_experience,
        "level": level_info,
        "years": year_progress,
        "cases": case_progress,
        "overall": {
            "completed": overall_completed,
            "total": overall_total,
            "ratio": max(0.0, min(1.0, overall_ratio)),
        },
    }


def _safe_time_from_string(value: Optional[str]) -> dt_time:
    if not value:
        return dt_time(hour=20, minute=0)
    try:
        hour, minute = value.split(":")[:2]
        return dt_time(hour=int(hour), minute=int(minute))
    except Exception:
        return dt_time(hour=20, minute=0)


def _parse_iso_datetime(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _calculate_next_reminder(reference: datetime, interval_days: int, reminder_time: dt_time) -> datetime:
    interval_days = max(1, interval_days)
    minimum_dt = reference + timedelta(days=interval_days)
    candidate = datetime.combine(minimum_dt.date(), reminder_time)
    if candidate < minimum_dt:
        candidate += timedelta(days=1)

    now = datetime.now()
    if candidate <= now:
        delta = now - candidate
        periods = int(delta.total_seconds() // (interval_days * 24 * 60 * 60)) + 1
        candidate += timedelta(days=interval_days * periods)

    return candidate


def _build_schedule_preview(
    reference: datetime,
    interval_days: int,
    reminder_time: dt_time,
    channels: List[str],
    *,
    first_event: Optional[datetime] = None,
    count: int = 3,
) -> pd.DataFrame:
    interval_days = max(1, interval_days)
    first_event_dt = first_event or _calculate_next_reminder(reference, interval_days, reminder_time)
    events = []
    current = first_event_dt
    for idx in range(count):
        events.append(
            {
                "回次": f"#{idx + 1}",
                "通知予定": current.strftime("%Y-%m-%d %H:%M"),
                "チャネル": "、".join(channels) if channels else "未設定",
            }
        )
        current += timedelta(days=interval_days)

    return pd.DataFrame(events)


def _mode_label(mode: str) -> str:
    return "模試" if mode == "mock" else "演習"


def _analyze_keyword_records(records: List[Dict]) -> Dict[str, Any]:
    if not records:
        return {
            "answers": pd.DataFrame(),
            "summary": pd.DataFrame(),
            "recommendations": [],
        }

    answer_rows: List[Dict[str, Any]] = []
    keyword_stats: Dict[str, Dict[str, Any]] = {}

    for record in records:
        keyword_hits: Dict[str, bool] = record.get("keyword_hits") or {}
        total_keywords = len(keyword_hits)
        if total_keywords == 0:
            coverage_ratio = None
        else:
            coverage_ratio = sum(1 for hit in keyword_hits.values() if hit) / total_keywords
        score_ratio = None
        if record.get("max_score"):
            try:
                score_ratio = (record.get("score") or 0) / record["max_score"]
            except ZeroDivisionError:
                score_ratio = None

        matched_keywords = [kw for kw, hit in keyword_hits.items() if hit]
        missing_keywords = [kw for kw, hit in keyword_hits.items() if not hit]

        answer_rows.append(
            {
                "attempt_id": record["attempt_id"],
                "年度": record["year"],
                "事例": record["case_label"],
                "タイトル": record["title"],
                "設問": record["prompt"],
                "回答日時": record["submitted_at"],
                "キーワード網羅率": coverage_ratio * 100 if coverage_ratio is not None else None,
                "得点率": score_ratio * 100 if score_ratio is not None else None,
                "含まれたキーワード": matched_keywords,
                "不足キーワード": missing_keywords,
                "モード": _mode_label(record.get("mode", "practice")),
            }
        )

        for keyword, hit in keyword_hits.items():
            stat = keyword_stats.setdefault(
                keyword,
                {
                    "attempts": 0,
                    "hits": 0,
                    "cases": set(),
                    "years": set(),
                    "examples": [],
                },
            )
            stat["attempts"] += 1
            if hit:
                stat["hits"] += 1
            stat["cases"].add(record["case_label"])
            stat["years"].add(record["year"])
            if len(stat["examples"]) < 3:
                stat["examples"].append(
                    {
                        "year": record["year"],
                        "case_label": record["case_label"],
                        "title": record["title"],
                        "prompt": record["prompt"],
                        "hit": hit,
                    }
                )

    answers_df = pd.DataFrame(answer_rows)
    if not answers_df.empty:
        answers_df["回答日時"] = pd.to_datetime(answers_df["回答日時"], errors="coerce")
        answers_df["不足キーワード表示"] = answers_df["不足キーワード"].apply(
            lambda keywords: "、".join(keywords) if keywords else "-"
        )
        answers_df["含まれたキーワード表示"] = answers_df["含まれたキーワード"].apply(
            lambda keywords: "、".join(keywords) if keywords else "-"
        )

    summary_rows: List[Dict[str, Any]] = []
    recommendations: List[Dict[str, Any]] = []

    for keyword, stat in keyword_stats.items():
        attempts = stat["attempts"]
        hits = stat["hits"]
        hit_rate = hits / attempts if attempts else 0.0
        summary_rows.append(
            {
                "キーワード": keyword,
                "出題数": attempts,
                "達成率(%)": hit_rate * 100,
                "主な事例": "、".join(sorted(stat["cases"])) if stat["cases"] else "-",
                "出題年度": "、".join(sorted(stat["years"])) if stat["years"] else "-",
            }
        )

        if attempts >= 1 and hit_rate < 0.6:
            example_entry = next((ex for ex in stat["examples"] if not ex["hit"]), None)
            if example_entry is None and stat["examples"]:
                example_entry = stat["examples"][0]
            example_text = None
            if example_entry:
                example_text = (
                    f"{example_entry['year']} {example_entry['case_label']}『{example_entry['title']}』"
                )
            recommendations.append(
                {
                    "keyword": keyword,
                    "hit_rate": hit_rate,
                    "attempts": attempts,
                    "example": example_text,
                }
            )

    summary_df = pd.DataFrame(summary_rows)
    if not summary_df.empty:
        summary_df.sort_values(["出題数", "達成率(%)"], ascending=[False, False], inplace=True)

    recommendations.sort(key=lambda item: (item["hit_rate"], -item["attempts"]))

    return {
        "answers": answers_df,
        "summary": summary_df,
        "recommendations": recommendations,
    }


def practice_page(user: Dict) -> None:
    st.title("過去問演習")
    st.caption("年度と事例を選択して記述式演習を行います。")

    st.info(
        "左側のセレクターで年度・事例を切り替え、下部の解答欄から回答を入力してください。"
    )

    due_reviews = database.list_due_reviews(user["id"], limit=3)
    if due_reviews:
        st.warning(
            "本日復習推奨の事例があります。該当の年度・事例を選択して復習しましょう。",
            icon="⏰",
        )
        for review in due_reviews:
            ratio = review["last_score_ratio"] or 0
            st.markdown(
                f"- **{review['year']} {review['case_label']}** {review['title']}"
                f" — 前回達成度 {ratio * 100:.0f}% / 推奨間隔 {review['interval_days']}日"
            )

    st.markdown(
        dedent(
            """
            <style>
            .practice-quick-nav {
                display: flex;
                gap: 0.75rem;
                flex-wrap: wrap;
                margin-bottom: 0.5rem;
            }
            .practice-quick-nav a {
                text-decoration: none;
            }
            .practice-quick-nav a button {
                padding: 0.45rem 1.2rem;
                border-radius: 0.5rem;
                border: none;
                background-color: #0f62fe;
                color: white;
                font-weight: 600;
                cursor: pointer;
            }
            .practice-quick-nav a button:hover {
                background-color: #0353e9;
            }
            </style>
            """
        ).strip(),
        unsafe_allow_html=True,
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

    st.markdown('<div id="practice-top"></div>', unsafe_allow_html=True)

    st.subheader(problem["title"])
    st.write(problem["overview"])

    st.markdown(
        dedent(
            """
            <div class="practice-quick-nav">
                <a href="#practice-answers"><button type="button">質問へ移動</button></a>
                <a href="#practice-actions"><button type="button">下へスクロール</button></a>
            </div>
            """
        ).strip(),
        unsafe_allow_html=True,
    )

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

    _render_retrieval_flashcards(problem)

    if not st.session_state.practice_started:
        st.session_state.practice_started = datetime.utcnow()

    answers: List[RecordedAnswer] = []
    question_specs: List[QuestionSpec] = []
    st.markdown('<div id="practice-answers"></div>', unsafe_allow_html=True)

    _inject_guideline_styles()

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
        visibility_key = _guideline_visibility_key(problem["id"], question["id"])
        if visibility_key not in st.session_state:
            st.session_state[visibility_key] = True
        show_guideline = st.checkbox(
            "採点ガイドラインを表示",
            key=visibility_key,
            help="採点時に確認されるポイントを必要なときに開閉できます。",
        )
        if show_guideline:
            keywords_html = ""
            if question["keywords"]:
                keywords_text = "、".join(question["keywords"])
                keywords_html = (
                    "<div class=\"guideline-section\">"
                    "<p class=\"guideline-heading\">キーワード評価</p>"
                    f"<p class=\"guideline-body\">{html.escape(keywords_text)} を含めると加点対象です。</p>"
                    "</div>"
                )
            model_answer_html = html.escape(question["model_answer"]).replace("\n", "<br>")
            st.markdown(
                """
                <div class="guideline-card">
                    {keywords}
                    <div class="guideline-section">
                        <p class="guideline-heading">模範解答の背景</p>
                        <p class="guideline-body">{model}</p>
                    </div>
                </div>
                """.format(keywords=keywords_html, model=model_answer_html),
                unsafe_allow_html=True,
            )
            st.caption(
                "模範解答は構成や論理展開の参考例です。キーワードを押さえつつ自分の言葉で表現しましょう。"
            )

    st.markdown('<div id="practice-actions"></div>', unsafe_allow_html=True)

    col_save, col_submit = st.columns([1, 2])
    if col_save.button("下書きを保存"):
        st.success("下書きを保存しました。ブラウザを閉じても維持されます。")

    submitted = col_submit.button("AI採点に送信", type="primary")

    if submitted:
        answers = []
        question_ratios: List[float] = []
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
            max_score = question.get("max_score") or 0
            if max_score:
                question_ratios.append(result.score / max_score)

        submitted_at = datetime.utcnow()
        started_at = st.session_state.practice_started or submitted_at
        duration = int((submitted_at - started_at).total_seconds())
        total_score = sum(answer.score for answer in answers)
        total_max = sum(question["max_score"] for question in problem["questions"])
        score_ratio = (total_score / total_max) if total_max else 0.0

        attempt_id = database.record_attempt(
            user_id=user["id"],
            problem_id=problem["id"],
            mode="practice",
            answers=answers,
            started_at=started_at,
            submitted_at=submitted_at,
            duration_seconds=duration,
        )
        database.update_spaced_review(
            user_id=user["id"],
            problem_id=problem["id"],
            score_ratio=score_ratio,
            reviewed_at=submitted_at,
            question_ratios=question_ratios,
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
        _render_character_counter(len(user_answer), max_chars)
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
    review_plan = database.get_spaced_review(attempt["user_id"], attempt["problem_id"])
    if review_plan:
        due_at = review_plan["due_at"]
        interval = review_plan["interval_days"]
        if due_at <= datetime.utcnow():
            st.warning(
                f"この事例の復習期限が到来しています。推奨: {due_at.strftime('%Y-%m-%d %H:%M')} (間隔 {interval}日)",
                icon="🔁",
            )
        else:
            st.info(
                f"次回の復習目安は {due_at.strftime('%Y-%m-%d %H:%M')} ごろです (推奨間隔 {interval}日)",
                icon="🔁",
            )
    if attempt["mode"] == "mock" and total_max:
        ratio = total_score / total_max
        if ratio >= 0.7:
            st.success("模擬試験クリア！称号『模試コンプリート』を獲得しました。")
            st.balloons()

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
        st.caption("説明を確認し、解きたい模試セットを選んでください。開始ボタンは右側に配置しています。")

        exams = mock_exam.available_mock_exams()
        exam_options = {exam.title: exam for exam in exams}
        exam_options["ランダム演習セット"] = mock_exam.random_mock_exam()

        select_col, start_col = st.columns([3, 1])
        with select_col:
            selected_title = st.selectbox("模試セット", list(exam_options.keys()))

        selected_exam = exam_options[selected_title]

        with start_col:
            st.write("")
            start_clicked = st.button(
                "模試を開始", type="primary", use_container_width=True
            )

        case_summaries = []
        for problem_id in selected_exam.problem_ids:
            problem = database.fetch_problem(problem_id)
            case_summaries.append(
                f"- {problem['year']} {problem['case_label']}：{problem['title']}"
            )
        if case_summaries:
            st.markdown("**セット内容の概要**")
            st.markdown("\n".join(case_summaries))

        if start_clicked:
            st.session_state.mock_session = {
                "exam": selected_exam,
                "start": datetime.utcnow(),
                "answers": {},
            }
            st.rerun()
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
                text = st.text_area(
                    question["prompt"], key=f"mock_{key}", value=default, height=160
                )
                _render_character_counter(len(text), question.get("character_limit"))
                st.session_state.drafts[key] = text

    if st.button("模試を提出", type="primary"):
        overall_results = []
        for problem_id in exam.problem_ids:
            problem = database.fetch_problem(problem_id)
            answers: List[RecordedAnswer] = []
            question_ratios: List[float] = []
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
                max_score = question.get("max_score") or 0
                if max_score:
                    question_ratios.append(result.score / max_score)
            submitted_at = datetime.utcnow()
            attempt_id = database.record_attempt(
                user_id=user["id"],
                problem_id=problem_id,
                mode="mock",
                answers=answers,
                started_at=start_time,
                submitted_at=submitted_at,
                duration_seconds=int((submitted_at - start_time).total_seconds()),
            )
            total_score = sum(answer.score for answer in answers)
            total_max = sum(question["max_score"] for question in problem["questions"])
            score_ratio = (total_score / total_max) if total_max else 0.0
            database.update_spaced_review(
                user_id=user["id"],
                problem_id=problem_id,
                score_ratio=score_ratio,
                reviewed_at=submitted_at,
                question_ratios=question_ratios,
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

    keyword_records = database.fetch_keyword_performance(user["id"])

    stats = _compute_learning_stats(history_df)
    progress_overview = _compute_progress_overview(history_df)
    reminder_settings = database.get_reminder_settings(user["id"])
    review_schedule = database.list_upcoming_reviews(user_id=user["id"], limit=10)
    due_reviews_count = database.count_due_reviews(user_id=user["id"])
    active_interval = (
        reminder_settings["interval_days"] if reminder_settings else stats["recommended_interval"]
    )
    reminder_time_value = _safe_time_from_string(
        reminder_settings["reminder_time"] if reminder_settings else None
    )
    selected_channels = (
        list(reminder_settings["preferred_channels"])
        if reminder_settings
        else ["メール通知"]
    )
    next_trigger_dt = _parse_iso_datetime(
        reminder_settings["next_trigger_at"] if reminder_settings else None
    )
    last_notified_dt = _parse_iso_datetime(
        reminder_settings["last_notified_at"] if reminder_settings else None
    )

    st.subheader("進捗ハイライトとスケジュール")
    summary_col1, summary_col2, summary_col3 = st.columns(3)
    summary_col1.metric("累計演習", f"{stats['total_sessions']}回")
    avg_display = f"{stats['recent_average']:.1f}点" if stats["recent_average"] is not None else "ー"
    summary_col2.metric("直近5回平均", avg_display)
    summary_col3.metric("連続学習日数", f"{stats['streak_days']}日")

    if stats["last_study_at"] is not None:
        st.info(
            f"直近の演習は {stats['last_study_at'].strftime('%Y-%m-%d %H:%M')} 実施。"
            f"推奨間隔 {stats['recommended_interval']}日 → 次回の目安は"
            f" {stats['next_study_at'].strftime('%Y-%m-%d %H:%M')} ごろです。"
        )
    else:
        st.info("これから学習を始めましょう。初期推奨リマインダーは3日おきです。")

    if review_schedule:
        st.markdown("#### 復習予定リスト")
        if due_reviews_count:
            st.warning(
                f"{due_reviews_count}件の復習期限が到来しています。『過去問演習』から優先的に復習しましょう。",
                icon="📌",
            )
        review_df = pd.DataFrame(
            [
                {
                    "次回予定": item["due_at"].strftime("%Y-%m-%d"),
                    "事例": f"{item['year']} {item['case_label']}",
                    "タイトル": item["title"],
                    "達成度": f"{(item['last_score_ratio'] or 0) * 100:.0f}%",
                    "間隔": f"{item['interval_days']}日",
                }
                for item in review_schedule
            ]
        )
        st.dataframe(review_df, use_container_width=True)
    else:
        st.caption("演習完了後に復習予定が自動生成されます。")

    with st.expander("リマインダー設定", expanded=reminder_settings is None):
        st.write("学習リズムに合わせて通知頻度・時刻・チャネルをカスタマイズできます。")
        cadence_labels = {
            "recommended": f"推奨 ({stats['recommended_interval']}日おき)",
            "every_other_day": "隔日 (2日おき)",
            "weekly": "週1回 (7日間隔)",
            "custom": "カスタム設定",
        }
        default_cadence = reminder_settings["cadence"] if reminder_settings else "recommended"
        custom_default = (
            reminder_settings["interval_days"]
            if reminder_settings and reminder_settings["cadence"] == "custom"
            else stats["recommended_interval"]
        )

        with st.form("reminder_form"):
            cadence_choice = st.selectbox(
                "通知頻度",
                options=list(cadence_labels.keys()),
                index=list(cadence_labels.keys()).index(default_cadence)
                if default_cadence in cadence_labels
                else 0,
                format_func=lambda key: cadence_labels[key],
            )
            custom_interval = None
            if cadence_choice == "custom":
                custom_interval = st.number_input(
                    "通知間隔（日）",
                    min_value=1,
                    max_value=30,
                    value=int(custom_default),
                    step=1,
                )
            reminder_time_input = st.time_input("通知時刻", value=reminder_time_value)
            channel_options = ["メール通知", "スマートフォン通知"]
            channels_selection = st.multiselect(
                "通知チャネル",
                options=channel_options,
                default=[c for c in selected_channels if c in channel_options] or channel_options[:1],
            )

            submitted = st.form_submit_button("設定を保存")

            if submitted:
                if not channels_selection:
                    st.warning("通知チャネルを1つ以上選択してください。")
                else:
                    if cadence_choice == "recommended":
                        interval_days = stats["recommended_interval"]
                    elif cadence_choice == "every_other_day":
                        interval_days = 2
                    elif cadence_choice == "weekly":
                        interval_days = 7
                    else:
                        interval_days = int(custom_interval) if custom_interval else 1

                    next_trigger = _calculate_next_reminder(
                        stats["reference_datetime"], interval_days, reminder_time_input
                    )
                    database.upsert_reminder_settings(
                        user_id=user["id"],
                        cadence=cadence_choice,
                        interval_days=interval_days,
                        preferred_channels=channels_selection,
                        reminder_time=reminder_time_input.strftime("%H:%M"),
                        next_trigger_at=next_trigger,
                    )
                    st.success(
                        f"リマインダーを保存しました。次回通知予定: {next_trigger.strftime('%Y-%m-%d %H:%M')}"
                    )
                    reminder_settings = database.get_reminder_settings(user["id"])
                    active_interval = reminder_settings["interval_days"]
                    reminder_time_value = _safe_time_from_string(reminder_settings["reminder_time"])
                    selected_channels = list(reminder_settings["preferred_channels"])
                    next_trigger_dt = _parse_iso_datetime(reminder_settings["next_trigger_at"])
                    last_notified_dt = _parse_iso_datetime(reminder_settings["last_notified_at"])

    if reminder_settings and next_trigger_dt:
        st.success(
            f"次回の通知予定: {next_trigger_dt.strftime('%Y-%m-%d %H:%M')}"
            f" / チャネル: {'、'.join(selected_channels)}"
        )
        if last_notified_dt:
            st.caption(f"前回記録された通知送信: {last_notified_dt.strftime('%Y-%m-%d %H:%M')}")
        if st.button("テスト通知を送信（シミュレーション）"):
            simulated_next = next_trigger_dt + timedelta(days=active_interval)
            database.mark_reminder_sent(
                reminder_settings["id"], next_trigger_at=simulated_next
            )
            st.info(
                f"通知送信を記録しました（ダミー）。次回予定: {simulated_next.strftime('%Y-%m-%d %H:%M')}"
            )
            reminder_settings = database.get_reminder_settings(user["id"])
            active_interval = reminder_settings["interval_days"]
            reminder_time_value = _safe_time_from_string(reminder_settings["reminder_time"])
            selected_channels = list(reminder_settings["preferred_channels"])
            next_trigger_dt = _parse_iso_datetime(reminder_settings["next_trigger_at"])
            last_notified_dt = _parse_iso_datetime(reminder_settings["last_notified_at"])
    else:
        st.info("リマインダーを設定すると、メールやスマートフォン通知と連携した学習習慣づくりをサポートできます。")

    schedule_preview = _build_schedule_preview(
        stats["reference_datetime"],
        active_interval,
        reminder_time_value,
        selected_channels,
        first_event=next_trigger_dt,
    )
    st.dataframe(schedule_preview, use_container_width=True)
    st.caption("今後の通知予定（サンプル）を確認し、リマインダー運用のイメージを掴めます。")

    st.caption(
        "通知APIやワークフロー自動化ツールと連携すると、保存した予定に合わせたメール送信やモバイル通知の運用が可能です。"
    )

    st.subheader("学習レベルと進捗状況")
    level_info = progress_overview["level"]
    level_col, summary_col = st.columns([1, 2])
    with level_col:
        st.metric("現在のレベル", f"Lv.{int(level_info['level'])}")
        st.caption(f"累計経験値: {level_info['total_experience']:.0f} XP")
    with summary_col:
        st.markdown("次のレベルまで")
        st.progress(level_info["progress_ratio"])
        st.caption(
            f"あと {level_info['xp_to_next_level']:.0f} XP でレベル{int(level_info['level']) + 1}"
        )
        overall = progress_overview["overall"]
        st.caption(
            f"年度×事例の進捗: {overall['completed']} / {overall['total']}"
            f" ({overall['ratio'] * 100:.0f}%)"
        )

    year_col, case_col = st.columns(2)
    with year_col:
        st.markdown("##### 年度別進捗")
        if progress_overview["years"]:
            for year_item in progress_overview["years"]:
                st.markdown(
                    f"**{year_item['label']}** {year_item['completed']} / {year_item['total']} 事例"
                )
                st.progress(year_item["ratio"])
        else:
            st.info("問題データが登録されていません。")

    with case_col:
        st.markdown("##### 事例別進捗")
        if progress_overview["cases"]:
            for case_item in progress_overview["cases"]:
                st.markdown(
                    f"**{case_item['label']}** {case_item['completed']} / {case_item['total']} 年度"
                )
                st.progress(case_item["ratio"])
        else:
            st.info("問題データが登録されていません。")

    st.divider()

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

    filtered_keyword_records = keyword_records
    if selected_years:
        filtered_keyword_records = [
            record for record in filtered_keyword_records if record["year"] in selected_years
        ]
    if selected_cases:
        filtered_keyword_records = [
            record for record in filtered_keyword_records if record["case_label"] in selected_cases
        ]
    if selected_modes:
        filtered_keyword_records = [
            record for record in filtered_keyword_records if record["mode"] in selected_modes
        ]

    keyword_analysis = _analyze_keyword_records(filtered_keyword_records)

    overview_tab, chart_tab, keyword_tab, detail_tab = st.tabs(
        ["一覧", "グラフ", "キーワード分析", "詳細・エクスポート"]
    )

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

    with keyword_tab:
        answers_df = keyword_analysis["answers"]
        summary_df = keyword_analysis["summary"]
        recommendations = keyword_analysis["recommendations"]

        if answers_df.empty and summary_df.empty:
            st.info("キーワード採点の記録がまだありません。演習を重ねると分析が表示されます。")
        else:
            if not answers_df.empty:
                scatter_source = answers_df.dropna(subset=["キーワード網羅率", "得点率"])
                if not scatter_source.empty:
                    scatter_chart = (
                        alt.Chart(scatter_source)
                        .mark_circle(size=90, opacity=0.75)
                        .encode(
                            x=alt.X(
                                "キーワード網羅率:Q",
                                title="キーワード網羅率 (%)",
                                scale=alt.Scale(domain=[0, 100]),
                            ),
                            y=alt.Y(
                                "得点率:Q",
                                title="設問得点率 (%)",
                                scale=alt.Scale(domain=[0, 100]),
                            ),
                            color=alt.Color("事例:N"),
                            tooltip=[
                                "年度",
                                "事例",
                                "タイトル",
                                "設問",
                                alt.Tooltip("キーワード網羅率:Q", format=".1f"),
                                alt.Tooltip("得点率:Q", format=".1f"),
                                "不足キーワード表示",
                            ],
                        )
                    )
                    st.subheader("キーワード網羅率と得点率の相関")
                    st.altair_chart(scatter_chart, use_container_width=True)
                    st.caption("左下に位置する設問はキーワード・得点ともに伸びしろがあります。重点的に復習しましょう。")
                else:
                    st.info("スコアとキーワード判定が揃った設問がまだありません。")

            if not summary_df.empty:
                st.markdown("#### 頻出キーワードの達成状況")
                display_summary = summary_df.copy()
                display_summary["達成率(%)"] = display_summary["達成率(%)"].map(
                    lambda v: f"{v:.0f}%"
                )
                st.data_editor(
                    display_summary,
                    hide_index=True,
                    use_container_width=True,
                    disabled=True,
                )
                st.caption("出題頻度が高いキーワードほど上位に表示されます。達成率が低いキーワードは計画的に復習しましょう。")

            if recommendations:
                st.markdown("#### 優先して復習したいテーマ")
                for recommendation in recommendations[:5]:
                    keyword = recommendation["keyword"]
                    hit_rate = recommendation["hit_rate"] * 100
                    attempts = recommendation["attempts"]
                    example = recommendation.get("example")
                    resources = KEYWORD_RESOURCE_MAP.get(keyword, DEFAULT_KEYWORD_RESOURCES)
                    lines = [
                        f"- **{keyword}** — 達成率 {hit_rate:.0f}% / 出題 {attempts}回",
                    ]
                    if example:
                        lines.append(f"    - 出題例: {example}")
                    for resource in resources:
                        lines.append(f"    - [参考資料]({resource['url']}): {resource['label']}")
                    st.markdown("\n".join(lines))

            if not answers_df.empty:
                st.markdown("#### 設問別キーワード判定一覧")
                detail_df = answers_df[
                    [
                        "年度",
                        "事例",
                        "タイトル",
                        "設問",
                        "モード",
                        "キーワード網羅率",
                        "得点率",
                        "含まれたキーワード表示",
                        "不足キーワード表示",
                    ]
                ].copy()
                detail_df["キーワード網羅率"] = detail_df["キーワード網羅率"].map(
                    lambda v: f"{v:.0f}%" if pd.notna(v) else "-"
                )
                detail_df["得点率"] = detail_df["得点率"].map(
                    lambda v: f"{v:.0f}%" if pd.notna(v) else "-"
                )
                st.data_editor(detail_df, hide_index=True, use_container_width=True, disabled=True)
                st.caption("各設問の到達状況と不足キーワードを一覧化しました。学習計画に反映してください。")

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

    st.subheader("プラン一覧")

    plan_features = pd.DataFrame(
        [
            {
                "プラン": "無料プラン",
                "月額料金": "¥0",
                "AI採点": "\u2705 月20回まで",
                "詳細解説": "\u26aa 最新3回分のみ",
                "学習レポート": "\u26aa ハイライトのみ",
            },
            {
                "プラン": "プレミアム",
                "月額料金": "¥1,480",
                "AI採点": "\u2b50\ufe0f 無制限",
                "詳細解説": "\u2b50\ufe0f 全設問を無制限閲覧",
                "学習レポート": "\u2b50\ufe0f 個別アドバイス付き",
            },
        ]
    )
    st.dataframe(plan_features, use_container_width=True, hide_index=True)

    st.caption(
        "\U0001f4a1 プレミアムプランでは AI 採点の上限が解除され、全ての模擬試験・過去問で詳細解説を好きなだけ閲覧できます。"
    )

    st.subheader("アップグレードのメリット")
    col1, col2 = st.columns(2)
    with col1:
        st.markdown(
            """
            - 🧠 **AI採点の無制限化**: 事例演習の回数を気にせずフィードバックを受けられます。
            - 📊 **詳細な学習レポート**: 記述力の伸びや課題を自動分析し、次に取り組むべきテーマを提案します。
            """
        )
    with col2:
        st.markdown(
            """
            - 📚 **詳細解説の読み放題**: 各設問の模範答案・解説を制限なく確認できます。
            - 🕒 **優先サポート**: 24時間以内のメール返信で学習の悩みをサポートします。
            """
        )

    st.subheader("料金とお支払い方法")
    st.markdown(
        """
        - 💳 **月額: 1,480円 (税込)**
        - 🧾 お支払い方法: クレジットカード (Visa / MasterCard / JCB)、デビットカード、主要な電子マネーに対応
        - 🔁 いつでも解約可能。次回更新日までは引き続きプレミアム機能をご利用いただけます。
        """
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
    st.markdown(
        dedent(
            """
            - お問い合わせ: support@example.com
            - 利用規約: coming soon
            - 退会をご希望の場合はサポートまでご連絡ください。
            """
        ).strip()
    )


logger = logging.getLogger(__name__)


if __name__ == "__main__":
    database.initialize_database()
    _init_session_state()
    try:
        main_view()
    except Exception:  # pragma: no cover - defensive UI fallback
        logger.exception("Unhandled exception in main_view")
        st.error("現在システムに不具合が発生しています。時間を置いて再度アクセスしてください。")
        st.caption("お問い合わせ: support@example.com")
