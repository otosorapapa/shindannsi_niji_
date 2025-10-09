"""Learning support utilities for 復習サポート."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Iterable, List

# Mapping of important keywords to recommended learning resources.
# These links are illustrative placeholders for the prototype application.
RESOURCE_LIBRARY: Dict[str, List[Dict[str, str]]] = {
    "製造技術": [
        {
            "title": "製造業の強み分析講義", 
            "url": "https://example.com/lecture/manufacturing-strength",
            "description": "製造業のコア技術を棚卸しし、強みとして整理する方法を解説。",
        }
    ],
    "信頼関係": [
        {
            "title": "関係性マーケティング基礎", 
            "url": "https://example.com/lecture/relationship-marketing",
            "description": "顧客との信頼構築プロセスをケースと共に学ぶ講義資料。",
        }
    ],
    "高付加価値": [
        {
            "title": "付加価値向上のフレームワーク", 
            "url": "https://example.com/article/value-add",
            "description": "商品の付加価値を高めるための視点を整理した解説記事。",
        }
    ],
    "企画開発": [
        {
            "title": "新商品企画プロセスの実務", 
            "url": "https://example.com/lecture/product-development",
            "description": "市場調査から開発・評価までのプロセスを体系的に学べる講義。",
        }
    ],
    "熟練": [
        {
            "title": "技能伝承とナレッジマネジメント", 
            "url": "https://example.com/whitepaper/knowledge-transfer",
            "description": "熟練者の技能伝承を仕組み化するポイントをまとめた資料。",
        }
    ],
    "若手育成": [
        {
            "title": "人材育成ロードマップ作成ガイド", 
            "url": "https://example.com/template/hrd-roadmap",
            "description": "若手育成計画の立案に使えるロードマップ作成テンプレート。",
        }
    ],
    "技能伝承": [
        {
            "title": "OJT設計の実践例", 
            "url": "https://example.com/case/ojt-design",
            "description": "中小企業での技能伝承に成功したケーススタディを紹介。",
        }
    ],
    "評価制度": [
        {
            "title": "評価制度見直しのチェックリスト", 
            "url": "https://example.com/checklist/performance-review",
            "description": "評価制度改革の手順と注意点を整理したチェックリスト。",
        }
    ],
    "モチベーション": [
        {
            "title": "モチベーション理論ハンドブック", 
            "url": "https://example.com/ebook/motivation",
            "description": "代表的なモチベーション理論と制度設計への活用例をまとめた電子書籍。",
        }
    ],
    "高齢": [
        {
            "title": "高齢顧客向けサービスの設計ポイント", 
            "url": "https://example.com/seminar/senior-service",
            "description": "シニア向けにサービス提供する際のUXと安心感醸成のコツ。",
        }
    ],
    "地域住民": [
        {
            "title": "地域密着マーケティング戦略", 
            "url": "https://example.com/article/local-marketing",
            "description": "地域住民との関係性を強化するためのマーケティング戦略を整理。",
        }
    ],
    "見守り": [
        {
            "title": "見守りサービスの事業化ケース", 
            "url": "https://example.com/case/monitoring-service",
            "description": "見守りサービスを収益化した企業の成功要因を分析した資料。",
        }
    ],
    "生活支援": [
        {
            "title": "生活支援サービスの提供価値設計", 
            "url": "https://example.com/guide/life-support",
            "description": "生活支援の付加価値を定義し、サービス設計に落とし込む手順。",
        }
    ],
    "安心": [
        {
            "title": "顧客安心感を高めるコミュニケーション術", 
            "url": "https://example.com/video/customer-trust",
            "description": "安心感を醸成するコミュニケーション手法を解説した動画講義。",
        }
    ],
    "連携": [
        {
            "title": "外部連携を活用した販促戦略", 
            "url": "https://example.com/webinar/alliances",
            "description": "行政・地域団体と連携したプロモーション事例を学ぶウェビナー。",
        }
    ],
    "口コミ": [
        {
            "title": "口コミマーケティングの基礎", 
            "url": "https://example.com/lesson/word-of-mouth",
            "description": "口コミを活用した販促のメカニズムと施策設計を解説。",
        }
    ],
    "紹介": [
        {
            "title": "紹介キャンペーン設計テンプレート", 
            "url": "https://example.com/template/referral",
            "description": "紹介インセンティブの設計と運用に役立つテンプレート資料。",
        }
    ],
    "継続利用": [
        {
            "title": "顧客継続率を高めるCRM施策", 
            "url": "https://example.com/ebook/crm-retention",
            "description": "CRMを活用した継続率向上施策とKPI設計をまとめた資料。",
        }
    ],
}

# Generic resources presented when no keyword-specific match is found.
FALLBACK_RESOURCES: List[Dict[str, str]] = [
    {
        "title": "中小企業診断士二次試験 論述力強化講義",
        "url": "https://example.com/course/judgement-writing",
        "description": "答案構成と論理展開のポイントを体系的に整理したeラーニング講座。",
    },
    {
        "title": "フレームワーク早見表",
        "url": "https://example.com/resource/framework-cheatsheet",
        "description": "事例I〜IVで活用する代表的フレームワークの一覧と使いどころをまとめた資料。",
    },
]


@dataclass
class LearningEntry:
    """Structured information stored in the explanation library."""

    question_id: int
    summary: str
    feedback: str
    focus_keywords: List[str]
    resources: List[Dict[str, str]]


def suggest_resources(missing_keywords: Iterable[str]) -> List[Dict[str, str]]:
    """Return a list of recommended resources for the missing keywords."""

    seen_urls = set()
    recommendations: List[Dict[str, str]] = []
    for keyword in missing_keywords:
        for resource in RESOURCE_LIBRARY.get(keyword, []):
            if resource["url"] in seen_urls:
                continue
            recommendations.append(resource)
            seen_urls.add(resource["url"])

    if not recommendations:
        for resource in FALLBACK_RESOURCES:
            if resource["url"] in seen_urls:
                continue
            recommendations.append(resource)
            seen_urls.add(resource["url"])
    return recommendations


def build_summary(explanation: str, missing_keywords: List[str]) -> str:
    """Create a concise learning summary based on missing keywords and explanation."""

    if missing_keywords:
        joined = "、".join(missing_keywords)
        return f"{joined} の観点が弱めです。{explanation}"
    return (
        "主要キーワードを押さえています。この調子で論理構成と表現を磨きましょう。"
        if explanation
        else "主要論点を十分にカバーしています。引き続き答案のブラッシュアップを続けましょう。"
    )


def create_learning_entry(question: Dict[str, str], keyword_hits: Dict[str, bool], feedback: str) -> LearningEntry:
    """Generate a learning entry for the explanation library."""

    missing_keywords = [keyword for keyword, hit in keyword_hits.items() if not hit]
    resources = suggest_resources(missing_keywords)
    summary = build_summary(question.get("explanation", ""), missing_keywords)
    return LearningEntry(
        question_id=question["id"],
        summary=summary,
        feedback=feedback,
        focus_keywords=missing_keywords,
        resources=resources,
    )
