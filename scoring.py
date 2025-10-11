"""Scoring utilities for the Streamlit application."""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Dict, Iterable, List, Mapping, Optional, Sequence

import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer


@dataclass
class QuestionSpec:
    """Representation of a question used for scoring."""

    id: int
    prompt: str
    max_score: float
    model_answer: str
    keywords: Iterable[str]


@dataclass(frozen=True)
class CriterionDefinition:
    """採点観点の定義情報。"""

    key: str
    label: str
    weight: float
    description: str


@dataclass
class ScoreCriterion:
    """個別観点の得点。"""

    key: str
    label: str
    score: float
    weight: float
    description: str


@dataclass
class ScoreAnalysis:
    """単一答案に対する観点別のスコア。"""

    keyword_hits: Dict[str, bool]
    keyword_ratio: float
    similarity: float
    structure_score: float
    clarity_score: float
    criteria: List[ScoreCriterion]

    def metric_map(self) -> Dict[str, float]:
        """Return a mapping of metric identifiers to values."""

        return {
            "keyword_ratio": self.keyword_ratio,
            "similarity": self.similarity,
            "structure_score": self.structure_score,
            "clarity_score": self.clarity_score,
        }


@dataclass
class ScoreResult:
    score: float
    feedback: str
    keyword_hits: Dict[str, bool]
    criteria: List[ScoreCriterion]
    analysis: ScoreAnalysis


@dataclass
class CriterionInsight:
    """観点別のスコアとコメントを保持するデータクラス。"""

    label: str
    score: float  # 0.0〜1.0 のスコア
    weight: float
    commentary: str


@dataclass
class BundleEvaluation:
    """複数設問をまとめて評価した結果。"""

    case_label: str
    overall_score: float  # 0〜100
    criteria: List[CriterionInsight]
    summary: str
    recommendations: List[str]


_CRITERION_DEFINITIONS: Sequence[CriterionDefinition] = (
    CriterionDefinition(
        key="keyword_ratio",
        label="キーワード含有率",
        weight=0.5,
        description="採点対象のキーワードに触れている割合を評価します。",
    ),
    CriterionDefinition(
        key="structure_score",
        label="構成の論理性",
        weight=0.3,
        description="模範解答との類似度や接続語の使い方から論理展開を推定します。",
    ),
    CriterionDefinition(
        key="clarity_score",
        label="表現の明快さ",
        weight=0.2,
        description="文の長さと句読点のバランスから読みやすさを評価します。",
    ),
)

_CRITERION_LOOKUP = {definition.key: definition for definition in _CRITERION_DEFINITIONS}


def criterion_definitions() -> Sequence[CriterionDefinition]:
    """Return the immutable list of scoring criterion definitions."""

    return _CRITERION_DEFINITIONS


def keyword_match_score(answer: str, keywords: Iterable[str]) -> Dict[str, bool]:
    """Return a dictionary showing whether each keyword appears in the answer."""
    hits: Dict[str, bool] = {}
    normalized_answer = _normalize(answer)
    for keyword in keywords:
        pattern = _normalize(keyword)
        hits[keyword] = pattern in normalized_answer
    return hits


def cosine_similarity_score(answer: str, reference: str) -> float:
    """Compute cosine similarity between the answer and the model reference."""
    vectorizer = TfidfVectorizer(stop_words=None)
    try:
        tfidf = vectorizer.fit_transform([reference, answer])
    except ValueError:
        return 0.0
    matrix = tfidf.toarray()
    ref_vec, ans_vec = matrix[0], matrix[1]
    numerator = float(np.dot(ref_vec, ans_vec))
    denominator = float(np.linalg.norm(ref_vec) * np.linalg.norm(ans_vec))
    if denominator == 0:
        return 0.0
    return numerator / denominator


def score_answer(answer: str, question: QuestionSpec) -> ScoreResult:
    """Score a single answer using heuristics that mimic the AI workflow."""
    answer = answer.strip()
    analysis = analyse_answer(answer, question)
    if not answer:
        return ScoreResult(
            score=0.0,
            feedback="回答が入力されていません。",
            keyword_hits=analysis.keyword_hits,
            criteria=analysis.criteria,
            analysis=analysis,
        )

    weight_total = sum(criterion.weight for criterion in analysis.criteria) or 1.0
    combined_ratio = sum(
        criterion.score * criterion.weight for criterion in analysis.criteria
    ) / weight_total
    raw_score = combined_ratio * question.max_score
    score = round(min(question.max_score, max(0.0, raw_score)), 2)

    keyword_hits = analysis.keyword_hits
    missing_keywords = [kw for kw, hit in keyword_hits.items() if not hit]
    positive_points: List[str] = []
    keyword_ratio = analysis.keyword_ratio
    if keyword_ratio >= 0.8:
        positive_points.append("主要キーワードをバランス良く押さえています。")
    elif keyword_ratio >= 0.4:
        positive_points.append(
            f"キーワードに{sum(keyword_hits.values())}件触れており、論点を一部捉えています。"
        )

    similarity = analysis.similarity
    if similarity >= 0.65:
        positive_points.append("模範解答と主旨が近く、論理展開も概ね整っています。")
    elif similarity >= 0.45:
        positive_points.append("模範解答との方向性は合っています。表現を磨くとさらに良くなります。")

    if analysis.clarity_score >= 0.7:
        positive_points.append("文の区切りが適切で、読み手に伝わる表現になっています。")

    if not positive_points:
        positive_points.append("自分の言葉で答案をまとめようとしている点は評価できます。")

    improvement_points: List[str] = []
    if missing_keywords:
        improvement_points.append("「" + "、".join(missing_keywords) + "」に触れると加点につながります。")
    if keyword_ratio < 0.4:
        improvement_points.append("解答内に重要キーワードが少ないため、設問要求を再確認しましょう。")
    if similarity < 0.45:
        improvement_points.append("模範解答と論点がずれている可能性があります。因果関係を意識した構成を意識してください。")
    if analysis.clarity_score < 0.5:
        improvement_points.append("文が長文化している可能性があります。句読点や接続語で段落を整理しましょう。")
    if not improvement_points:
        improvement_points.append("細部の表現を磨くと、より説得力の高い答案になります。")

    if missing_keywords:
        study_keywords = list(missing_keywords)
    else:
        study_keywords = list(question.keywords)

    improvement_suggestion = "設問文から与件企業の課題・強みを抜き出し、キーワードを盛り込んだうえで因果を意識して記述しましょう。"

    feedback_sections = [
        (
            "【得点サマリー】"
            f"キーワード網羅率: {analysis.keyword_ratio:.2f} / "
            f"論理構成指標: {analysis.structure_score:.2f} / "
            f"表現明瞭度: {analysis.clarity_score:.2f} / "
            f"類似度: {analysis.similarity:.2f}"
        ),
        "【良かった点】\n" + "\n".join(f"- {point}" for point in positive_points),
        "【改善が必要な点】\n" + "\n".join(f"- {point}" for point in improvement_points),
        "【学習すべきキーワード】\n" + "\n".join(f"- {kw}" for kw in study_keywords) if study_keywords else "",
        "【改善のヒント】\n- " + improvement_suggestion,
    ]

    feedback = "\n\n".join(section for section in feedback_sections if section)
    return ScoreResult(
        score=score,
        feedback=feedback,
        keyword_hits=keyword_hits,
        criteria=analysis.criteria,
        analysis=analysis,
    )


def analyse_answer(answer: str, question: QuestionSpec) -> ScoreAnalysis:
    """Return the detailed scoring analysis for a single answer."""

    answer = answer.strip()
    keywords = list(question.keywords)
    if not answer:
        keyword_hits = {kw: False for kw in keywords}
        criteria = [
            ScoreCriterion(
                key=definition.key,
                label=definition.label,
                score=0.0,
                weight=definition.weight,
                description=definition.description,
            )
            for definition in _CRITERION_DEFINITIONS
        ]
        return ScoreAnalysis(
            keyword_hits=keyword_hits,
            keyword_ratio=0.0,
            similarity=0.0,
            structure_score=0.0,
            clarity_score=0.0,
            criteria=criteria,
        )

    keyword_hits = keyword_match_score(answer, keywords)
    keyword_ratio = sum(keyword_hits.values()) / max(len(keyword_hits), 1)
    similarity = cosine_similarity_score(answer, question.model_answer)
    structure_score = _normalize_structure_score(similarity)
    clarity_score = _estimate_clarity_score(answer)

    criteria = [
        ScoreCriterion(
            key="keyword_ratio",
            label=_CRITERION_LOOKUP["keyword_ratio"].label,
            score=keyword_ratio,
            weight=_CRITERION_LOOKUP["keyword_ratio"].weight,
            description=_CRITERION_LOOKUP["keyword_ratio"].description,
        ),
        ScoreCriterion(
            key="structure_score",
            label=_CRITERION_LOOKUP["structure_score"].label,
            score=structure_score,
            weight=_CRITERION_LOOKUP["structure_score"].weight,
            description=_CRITERION_LOOKUP["structure_score"].description,
        ),
        ScoreCriterion(
            key="clarity_score",
            label=_CRITERION_LOOKUP["clarity_score"].label,
            score=clarity_score,
            weight=_CRITERION_LOOKUP["clarity_score"].weight,
            description=_CRITERION_LOOKUP["clarity_score"].description,
        ),
    ]

    return ScoreAnalysis(
        keyword_hits=keyword_hits,
        keyword_ratio=keyword_ratio,
        similarity=similarity,
        structure_score=structure_score,
        clarity_score=clarity_score,
        criteria=criteria,
    )


def _normalize_structure_score(similarity: float) -> float:
    """Convert cosine similarity into a 0-1 scale emphasising logical structure."""

    if similarity <= 0:
        return 0.0
    # Similarity above 0.8 is treated as a perfect structural match.
    return min(1.0, similarity / 0.8)


def _estimate_clarity_score(answer: str) -> float:
    """Estimate how clear the prose is based on punctuation and sentence length."""

    text = answer.replace("\n", " ")
    sentences = [
        segment.strip()
        for segment in re.split(r"[。．\.\!\?！？]", text)
        if segment.strip()
    ]
    if not sentences:
        return 0.0

    avg_length = sum(len(sentence) for sentence in sentences) / len(sentences)
    if avg_length <= 28:
        length_score = 1.0
    elif avg_length <= 40:
        length_score = 0.85
    elif avg_length <= 55:
        length_score = 0.65
    else:
        length_score = max(0.0, 1.0 - (avg_length - 55) / 60)

    if avg_length < 12:
        length_score = max(length_score - 0.2, 0.0)

    comma_count = len(re.findall(r"[、,，]", text))
    punctuation_density = comma_count / max(len(sentences), 1)
    punctuation_score = min(1.0, punctuation_density / 2)

    connector_count = len(
        re.findall(
            r"(ため|ので|から|しかし|また|さらに|一方|結果|目的|効果|よって|したがって)",
            answer,
        )
    )
    flow_score = min(1.0, (connector_count / max(len(sentences), 1)) / 1.5 + 0.3)

    clarity = 0.5 * length_score + 0.3 * punctuation_score + 0.2 * flow_score
    return max(0.0, min(1.0, clarity))


def evaluate_case_bundle(
    *, case_label: Optional[str], answers: Sequence[Mapping[str, object]]
) -> Optional[BundleEvaluation]:
    """Evaluate a bundle of answers with additional rubric-based criteria.

    Currently、事例IIの設問群をまとめて提出した際の観点別スコアを返す。
    """

    if not case_label or not answers:
        return None

    if case_label == "事例II":
        return _evaluate_case2_bundle(answers)

    return None


def _evaluate_case2_bundle(answers: Sequence[Mapping[str, object]]) -> Optional[BundleEvaluation]:
    texts = [str(answer.get("answer_text", "")).strip() for answer in answers]
    texts = [text for text in texts if text]
    if not texts:
        return None

    target_keywords = [
        "ターゲット",
        "顧客",
        "客層",
        "既存",
        "新規",
        "リピーター",
        "ファミリー",
        "シニア",
        "訪日",
        "観光客",
        "法人",
        "若年",
    ]
    action_verbs = [
        "強化",
        "拡大",
        "導入",
        "実施",
        "構築",
        "連携",
        "提携",
        "活用",
        "展開",
        "運用",
        "改善",
        "最適化",
        "設計",
        "企画",
        "実装",
        "訴求",
        "提供",
        "育成",
    ]
    channel_terms = [
        "SNS",
        "EC",
        "OMO",
        "イベント",
        "キャンペーン",
        "アプリ",
        "会員",
        "サブスク",
        "メール",
        "DM",
        "LINE",
        "コミュニティ",
        "レビュー",
    ]

    target_coverage = _coverage_ratio(texts, target_keywords)
    segment_ratio = _segment_pattern_ratio(texts)
    target_variety = _variety_ratio(texts, target_keywords, baseline=4)
    target_score = min(1.0, 0.6 * target_coverage + 0.25 * segment_ratio + 0.15 * target_variety)

    verb_density = _density_score(texts, action_verbs)
    channel_density = _density_score(texts, channel_terms)
    numeric_ratio = _numeric_presence_ratio(texts)
    specificity_score = min(1.0, 0.45 * verb_density + 0.3 * channel_density + 0.25 * numeric_ratio)

    matched_keywords = 0
    total_keywords = 0
    for answer in answers:
        keyword_hits = answer.get("keyword_hits") or {}
        if isinstance(keyword_hits, dict):
            matched_keywords += sum(1 for hit in keyword_hits.values() if hit)
            total_keywords += len(keyword_hits)
    evidence_score = matched_keywords / total_keywords if total_keywords else 0.0

    criteria = [
        CriterionInsight(
            label="ターゲットの明確さ",
            score=target_score,
            weight=0.35,
            commentary=_commentary_for_score(
                target_score,
                high="顧客像とセグメントが明確に描写されています。",
                mid="ターゲットの骨子は伝わりますが、セグメントをもう一段細分化できる余地があります。",
                low="ターゲット層の明示が弱いため、誰に届ける施策かを具体化しましょう。",
            ),
        ),
        CriterionInsight(
            label="施策の具体性",
            score=specificity_score,
            weight=0.4,
            commentary=_commentary_for_score(
                specificity_score,
                high="施策がチャネル・行動レベルまで落とし込まれており、提言力が高いです。",
                mid="施策の方向性は妥当です。チャネルやKPIなど実行指標を添えると一層明確になります。",
                low="施策が抽象的です。誰が・どのチャネルで・いつ行うかまで記述しましょう。",
            ),
        ),
        CriterionInsight(
            label="与件根拠の引用率",
            score=evidence_score,
            weight=0.25,
            commentary=_commentary_for_score(
                evidence_score,
                high="与件文の強み・資源をバランスよく踏まえています。",
                mid="主要キーワードは盛り込まれています。もう一語追加できると説得力が高まります。",
                low="与件の強みが十分に反映されていません。特徴語や数字を引用しましょう。",
            ),
        ),
    ]

    total_weight = sum(crit.weight for crit in criteria)
    weighted_score = sum(crit.score * crit.weight for crit in criteria)
    overall = round(weighted_score / total_weight * 100, 1) if total_weight else 0.0

    summary = _overall_summary(overall)
    recommendations = _recommendations_from_criteria(criteria)

    return BundleEvaluation(
        case_label="事例II",
        overall_score=overall,
        criteria=criteria,
        summary=summary,
        recommendations=recommendations,
    )


def _coverage_ratio(texts: Sequence[str], keywords: Sequence[str]) -> float:
    if not texts:
        return 0.0
    hits = 0
    for text in texts:
        if any(keyword in text for keyword in keywords):
            hits += 1
    return hits / len(texts)


def _segment_pattern_ratio(texts: Sequence[str]) -> float:
    if not texts:
        return 0.0
    pattern = re.compile(r"(若年|シニア|富裕|子育て|訪日|地元|常連|法人|観光|学生|高付加価値)[^。]{0,6}(層|客|顧客)")
    hits = sum(1 for text in texts if pattern.search(text))
    return hits / len(texts)


def _variety_ratio(texts: Sequence[str], keywords: Sequence[str], *, baseline: int) -> float:
    if not texts:
        return 0.0
    unique: set[str] = set()
    for text in texts:
        for keyword in keywords:
            if keyword in text:
                unique.add(keyword)
    if not unique:
        return 0.0
    return min(1.0, len(unique) / max(baseline, 1))


def _density_score(texts: Sequence[str], keywords: Sequence[str]) -> float:
    if not texts:
        return 0.0
    total_hits = 0
    for text in texts:
        total_hits += sum(1 for keyword in keywords if keyword in text)
    average_hits = total_hits / len(texts)
    return min(1.0, average_hits / 2)


def _numeric_presence_ratio(texts: Sequence[str]) -> float:
    if not texts:
        return 0.0
    pattern = re.compile(r"\d|％|%|回|件|名|日|週|月|年")
    hits = sum(1 for text in texts if pattern.search(text))
    return hits / len(texts)


def _commentary_for_score(score: float, high: str, mid: str, low: str) -> str:
    if score >= 0.75:
        return high
    if score >= 0.5:
        return mid
    return low


def _overall_summary(score: float) -> str:
    if score >= 75:
        return "提言力は合格水準を上回っています。この調子で改善案の裏付けを厚くしましょう。"
    if score >= 60:
        return "提言の骨子は整っています。ターゲットと根拠の言及をもう一段深めると安定します。"
    return "施策の具体化と根拠の引用を強化すると提言力が大きく伸びます。演習でフレームを確認しましょう。"


def _recommendations_from_criteria(criteria: Sequence[CriterionInsight]) -> List[str]:
    recommendations: List[str] = []
    for criterion in criteria:
        if criterion.score >= 0.7:
            continue
        if criterion.label == "ターゲットの明確さ":
            recommendations.append(
                "ターゲット層を年齢・ライフスタイル・来店目的など二軸以上で具体化し、既存/新規の別を明記しましょう。"
            )
        elif criterion.label == "施策の具体性":
            recommendations.append(
                "施策ごとにチャネル・実行主体・KPI（例: 来店頻度、セット率）をセットで書き出し、提言の骨太さを高めましょう。"
            )
        elif criterion.label == "与件根拠の引用率":
            recommendations.append(
                "与件文から強み・顧客ニーズ・数値を最低2語以上引用し、施策との因果を明文化してください。"
            )
    if not recommendations:
        recommendations.append(
            "演習では80字テンプレートに沿って『ターゲット→課題→施策→効果』の順に因果をチェックしましょう。"
        )
    return recommendations


def _normalize(text: str) -> str:
    text = text.lower()
    text = re.sub(r"\s+", "", text)
    return text
