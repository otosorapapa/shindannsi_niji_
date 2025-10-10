"""Utilities for scanning text for MECE and causal structure issues.

This module provides lightweight heuristics to highlight redundant wording,
synonymous repetitions, and flat enumerations while proposing causal
connective insertions. It intentionally avoids heavy NLP dependencies and
instead relies on simple pattern matching tailored for Japanese business
writing.
"""

from __future__ import annotations

import html
import re
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Sequence, Set, Tuple


WORD_PATTERN = re.compile(r"[一-龥々〆ヵヶぁ-ゖァ-ヶーA-Za-z0-9]+")

STOPWORDS: Set[str] = {
    "こと",
    "もの",
    "ため",
    "よう",
    "これ",
    "それ",
    "そして",
    "しかし",
    "ので",
    "また",
    "する",
    "なる",
    "いる",
    "ある",
}

SYNONYM_GROUPS: Sequence[Set[str]] = [
    {"課題", "問題", "懸念", "ボトルネック"},
    {"強み", "優位性", "差別化", "独自性"},
    {"弱み", "欠点", "リスク", "脆弱性"},
    {"施策", "対策", "打ち手", "アクション"},
    {"顧客", "クライアント", "利用者", "ユーザー"},
    {"成長", "拡大", "伸長"},
    {"改善", "向上", "強化"},
]

CONNECTOR_WORDS: Set[str] = {
    "だから",
    "結果として",
    "したがって",
    "従って",
    "そのため",
    "よって",
    "ゆえに",
}

CAUSE_KEYWORDS: Set[str] = {
    "原因",
    "課題",
    "要因",
    "背景",
    "理由",
    "現状",
    "問題",
    "不足",
    "停滞",
    "遅れ",
    "ボトルネック",
}

EFFECT_KEYWORDS: Set[str] = {
    "結果",
    "影響",
    "効果",
    "改善",
    "期待",
    "必要",
    "求められる",
    "べき",
    "求め",
    "増加",
    "減少",
    "伸長",
    "強化",
    "定着",
    "解消",
}

RESULT_KEYWORDS: Set[str] = {
    "結果",
    "影響",
    "効果",
    "成果",
    "改善",
    "増加",
    "減少",
    "伸長",
    "定着",
}


@dataclass
class ScannerResult:
    highlighted_html: str
    duplicates: List[Dict[str, Any]]
    synonym_groups: List[Dict[str, Any]]
    enumerations: List[Dict[str, Any]]
    connector_suggestions: List[Dict[str, str]]


def _tokenize(text: str) -> List[Tuple[str, int, int]]:
    tokens: List[Tuple[str, int, int]] = []
    for match in WORD_PATTERN.finditer(text):
        tokens.append((match.group(), match.start(), match.end()))
    return tokens


def _build_highlighted_html(text: str, annotations: Sequence[Dict[str, object]]) -> str:
    if not text:
        return ""

    char_labels: List[Set[str]] = [set() for _ in range(len(text))]
    for annotation in annotations:
        start = max(0, min(len(text), int(annotation["start"])))
        end = max(0, min(len(text), int(annotation["end"])))
        labels = set(annotation.get("labels", []))
        for index in range(start, end):
            char_labels[index].update(labels)

    parts: List[str] = []
    current_labels: Set[str] = set()
    buffer: List[str] = []

    def flush() -> None:
        nonlocal buffer, current_labels
        if not buffer:
            return
        segment = "".join(buffer)
        escaped = html.escape(segment)
        escaped = escaped.replace("\n", "<br>")
        escaped = escaped.replace(" ", "&nbsp;")
        escaped = escaped.replace("　", "&nbsp;&nbsp;")
        if current_labels:
            class_names = " ".join(sorted(f"highlight-{label}" for label in current_labels))
            parts.append(f'<span class="{class_names}">{escaped}</span>')
        else:
            parts.append(escaped)
        buffer = []

    for index, char in enumerate(text):
        labels = char_labels[index]
        if labels != current_labels:
            flush()
            current_labels = labels
        buffer.append(char)

    flush()
    return "".join(parts)


def _collect_duplicates(tokens: Sequence[Tuple[str, int, int]]) -> Tuple[List[Dict[str, Any]], List[Dict[str, object]]]:
    positions: Dict[str, List[Tuple[int, int]]] = {}
    for token, start, end in tokens:
        positions.setdefault(token, []).append((start, end))

    duplicates: List[Dict[str, Any]] = []
    annotations: List[Dict[str, object]] = []
    for word, ranges in positions.items():
        if len(ranges) < 2:
            continue
        if word in STOPWORDS or len(word) <= 1:
            continue
        duplicates.append({"word": word, "count": len(ranges)})
        for start, end in ranges:
            annotations.append({"start": start, "end": end, "labels": {"duplicate"}})
    duplicates.sort(key=lambda item: (-item["count"], item["word"]))
    return duplicates, annotations


def _collect_synonyms(
    tokens: Sequence[Tuple[str, int, int]]
) -> Tuple[List[Dict[str, Any]], List[Dict[str, object]]]:
    positions: Dict[str, List[Tuple[int, int]]] = {}
    for token, start, end in tokens:
        positions.setdefault(token, []).append((start, end))

    synonym_results: List[Dict[str, Any]] = []
    annotations: List[Dict[str, object]] = []

    for group in SYNONYM_GROUPS:
        found_tokens: List[Tuple[str, Tuple[int, int]]] = []
        for word in group:
            for occurrence in positions.get(word, []):
                found_tokens.append((word, occurrence))

        unique_words = {word for word, _ in found_tokens}
        if len(unique_words) < 2:
            continue
        synonym_results.append({"label": "・".join(sorted(unique_words)), "words": sorted(unique_words)})
        for _, (start, end) in found_tokens:
            annotations.append({"start": start, "end": end, "labels": {"synonym"}})

    synonym_results.sort(key=lambda item: item["label"])
    return synonym_results, annotations


def _collect_sentences(text: str) -> List[Tuple[str, int, int]]:
    sentences: List[Tuple[str, int, int]] = []
    for match in re.finditer(r"[^。！？]+[。！？]?", text):
        sentence = match.group()
        if sentence and sentence.strip():
            sentences.append((sentence.strip(), match.start(), match.end()))
    return sentences


def _collect_enumerations(sentences: Sequence[Tuple[str, int, int]]) -> Tuple[List[Dict[str, Any]], List[Dict[str, object]]]:
    enumerations: List[Dict[str, Any]] = []
    annotations: List[Dict[str, object]] = []

    for sentence, start, end in sentences:
        items = [item.strip() for item in sentence.rstrip("。！？").split("、") if item.strip()]
        if len(items) < 3:
            continue
        if any(connector in sentence for connector in CONNECTOR_WORDS):
            continue
        enumerations.append({"sentence": sentence, "items": items})
        annotations.append({"start": start, "end": end, "labels": {"enumeration"}})

    return enumerations, annotations


def _connector_suggestions(sentences: Sequence[Tuple[str, int, int]]) -> List[Dict[str, str]]:
    suggestions: List[Dict[str, str]] = []
    for (prev_sentence, _, _), (current_sentence, _, _) in zip(sentences, sentences[1:]):
        if any(connector in current_sentence for connector in CONNECTOR_WORDS):
            continue
        if not any(cause in prev_sentence for cause in CAUSE_KEYWORDS):
            continue
        if not any(effect in current_sentence for effect in EFFECT_KEYWORDS):
            continue
        connector = "結果として" if any(word in current_sentence for word in RESULT_KEYWORDS) else "だから"
        rewritten = f"{connector}{current_sentence}"
        suggestions.append(
            {
                "connector": connector,
                "target": current_sentence,
                "proposal": rewritten,
            }
        )
    return suggestions


def analyze_text(text: str) -> ScannerResult:
    tokens = _tokenize(text)
    sentences = _collect_sentences(text)

    duplicate_stats, duplicate_annotations = _collect_duplicates(tokens)
    synonym_stats, synonym_annotations = _collect_synonyms(tokens)
    enumeration_stats, enumeration_annotations = _collect_enumerations(sentences)
    suggestions = _connector_suggestions(sentences)

    annotations = duplicate_annotations + synonym_annotations + enumeration_annotations

    highlighted_html = _build_highlighted_html(text, annotations)

    return ScannerResult(
        highlighted_html=highlighted_html,
        duplicates=duplicate_stats,
        synonym_groups=synonym_stats,
        enumerations=enumeration_stats,
        connector_suggestions=suggestions,
    )

