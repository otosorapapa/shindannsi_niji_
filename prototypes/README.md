# 2ペイン演習UIプロトタイプ

このディレクトリには、診断士二次試験演習ページを左ペインに与件文、右ペインに設問を配置した2カラムUIとして再設計した最小プロトタイプを格納しています。

## ファイル一覧
- `two_pane_exercise.html`: HTML / CSS / JS一体の再現コード。主要な設計意図を日本語コメントとして併記。

## Streamlitへの組み込み手順

`streamlit.components.v1.html` を利用して、プロトタイプHTMLをそのまま挿入できます。以下は `app.py` などから呼び出す例です。

```python
from pathlib import Path
import streamlit as st

prototype_html = Path("prototypes/two_pane_exercise.html").read_text(encoding="utf-8")
st.components.v1.html(prototype_html, height=900, scrolling=True)
```

- `height` は表示領域に応じて調整してください。
- 本実装ではStreamlitウィジェットとの連携が必要なため、実サービスでは `iframe` ではなくネイティブコンポーネント化を検討します。

## アクセプタンスチェック項目

- [ ] 左ペインの与件文がスクロール中も常時表示され、内部のみスクロール可能である。
- [ ] TOCのチップをクリックすると該当設問へスムーススクロールし、カードが約2秒間ハイライトされる。
- [ ] 設問カードが交互パステル＋1px罫線＋24px以上の外側余白で視覚的に分節されている。
- [ ] 各回答欄の字数カウンタがリアルタイム更新され、上限超過時に警告色が表示される。
- [ ] 折りたたみ補助情報の開閉状態がリロード後も保持される。
- [ ] キーボード操作のみでTOC移動や補助情報開閉など全機能にアクセスできる。
- [ ] レイアウト崩れなくレスポンシブ表示され、主要Core Web Vitals目標（LCP<2.5s / INP<200ms / CLS<0.1）を満たす構造である。

