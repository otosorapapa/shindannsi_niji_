from __future__ import annotations

from io import BytesIO
from typing import Iterable

import pandas as pd
import streamlit as st


REQUIRED_COLUMNS: Iterable[str] = (
    "年度",
    "事例",
    "設問番号",
    "問題文",
    "配点",
    "模範解答",
    "解説",
)


def _load_uploaded_file(uploaded_file) -> pd.DataFrame | None:
    try:
        filename = uploaded_file.name.lower()
        if filename.endswith(".csv"):
            return pd.read_csv(uploaded_file)
        if filename.endswith(".xlsx") or filename.endswith(".xls"):
            return pd.read_excel(uploaded_file)
        st.error("対応していないファイル形式です。CSVまたはExcelファイルを選択してください。")
        return None
    except Exception as exc:  # pragma: no cover - Streamlit runtime feedback
        st.error(f"ファイルの読み込み中にエラーが発生しました: {exc}")
        return None


def _validate_columns(df: pd.DataFrame) -> bool:
    missing = set(REQUIRED_COLUMNS) - set(df.columns)
    if missing:
        st.error(f"必要な列が不足しています: {', '.join(sorted(missing))}")
        return False
    return True


def _download_bytes(df: pd.DataFrame, filetype: str) -> tuple[bytes, str]:
    if filetype == "csv":
        return df.to_csv(index=False).encode("utf-8-sig"), "text/csv"
    buffer = BytesIO()
    df.to_excel(buffer, index=False)
    buffer.seek(0)
    return buffer.read(), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def data_management_page() -> None:
    st.title("データ管理")
    st.caption("過去問データのアップロード、編集、ダウンロードを行います。")

    uploaded_file = st.file_uploader(
        "過去問データファイルをアップロード (CSV/Excel)",
        type=["csv", "xlsx", "xls"],
    )

    if uploaded_file is not None:
        df = _load_uploaded_file(uploaded_file)
        if df is not None and _validate_columns(df):
            st.session_state.past_data = df
            st.session_state.past_data_filename = uploaded_file.name
            st.success("過去問データを読み込みました。『過去問演習』ページから利用できます。")

    past_data = st.session_state.get("past_data")
    if past_data is None or past_data.empty:
        st.info("アップロード済みの過去問データがありません。ファイルを読み込んでください。")
        return

    filename = st.session_state.get("past_data_filename")
    suffix = f"（{filename}）" if filename else ""
    st.markdown(f"読み込み済みレコード数: **{len(past_data)}件**{suffix}")

    edited_df = st.data_editor(
        past_data,
        num_rows="dynamic",
        use_container_width=True,
        key="past_data_editor",
    )

    if st.button("編集内容を保存", type="secondary", key="save_past_data"):
        st.session_state.past_data = edited_df
        st.success("編集内容を保存しました。")

    col_csv, col_excel, col_clear = st.columns([1, 1, 1])
    for fmt, column in (("csv", col_csv), ("excel", col_excel)):
        bytes_value, mime = _download_bytes(st.session_state.past_data, fmt)
        filename = st.session_state.get("past_data_filename", f"past_data.{fmt if fmt == 'csv' else 'xlsx'}")
        if fmt == "excel" and filename.lower().endswith(".csv"):
            filename = filename.rsplit(".", 1)[0] + ".xlsx"
        column.download_button(
            label=f"{fmt.upper()}でダウンロード",
            data=bytes_value,
            file_name=filename,
            mime=mime,
        )

    with col_clear:
        if st.button("アップロードデータをクリア", key="clear_past_data"):
            st.session_state.past_data = None
            st.session_state.pop("past_data_filename", None)
            st.info("アップロードデータを削除しました。")
