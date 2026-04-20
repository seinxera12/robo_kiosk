"""
Intent classifier for query routing.

Classifies each user query into one of three intents:
  BUILDING  — building navigation, rooms, floors, facilities
  SEARCH    — current events, weather, news, real-time info
  GENERAL   — chitchat, general knowledge, math, anything else

Uses a two-tier approach:
  1. Keyword rules  — zero latency, handles clear-cut cases
  2. Embedding similarity — resolves ambiguous cases using the
     same sentence-transformer already loaded for RAG

The classifier is intentionally lightweight — no extra LLM call,
no network round-trip. Target latency: <15ms.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from enum import Enum
from typing import Optional

logger = logging.getLogger(__name__)


class Intent(str, Enum):
    BUILDING = "building"
    SEARCH   = "search"
    GENERAL  = "general"


@dataclass
class ClassificationResult:
    intent: Intent
    confidence: float          # 0.0 – 1.0
    method: str                # "keyword" | "embedding" | "default"
    matched_keywords: list[str]


# ---------------------------------------------------------------------------
# Keyword rule sets
# ---------------------------------------------------------------------------

_BUILDING_KEYWORDS: set[str] = {
    # Navigation
    "floor", "floors", "level", "levels", "room", "rooms", "office",
    "elevator", "elevators", "lift", "lifts", "stairs", "staircase",
    "escalator", "exit", "exits", "entrance", "lobby", "reception",
    # Facilities
    "cafeteria", "canteen", "restaurant", "cafe", "coffee",
    "toilet", "restroom", "bathroom", "washroom", "wc",
    "conference", "meeting room", "boardroom", "auditorium",
    "parking", "car park", "garage",
    "gym", "fitness", "medical", "clinic", "pharmacy",
    "atm", "bank", "shop", "store", "retail",
    "rooftop", "terrace", "garden",
    # Navigation phrases
    "where is", "how do i get", "how to get", "directions to",
    "located", "location of", "find the", "nearest", "closest",
    "which floor", "what floor", "on the",
    # Japanese Navigation
    "階", "フロア", "部屋", "オフィス", "事務所",
    "エレベーター", "エレベータ", "階段", "エスカレーター",
    "出口", "入口", "ロビー", "受付",
    # Japanese Facilities
    "カフェテリア", "食堂", "レストラン", "カフェ", "コーヒー",
    "トイレ", "お手洗い", "化粧室", "洗面所",
    "会議室", "ミーティングルーム", "講堂", "オーディトリアム",
    "駐車場", "パーキング", "ガレージ",
    "ジム", "フィットネス", "医務室", "クリニック", "薬局",
    "atm", "銀行", "ショップ", "店舗", "売店",
    "屋上", "テラス", "庭園",
    # Japanese Navigation phrases
    "どこ", "どこです", "どこにあります", "どこですか",
    "行き方", "道順", "場所", "位置",
    "最寄り", "一番近い", "何階", "どの階",
}

_SEARCH_KEYWORDS: set[str] = {
    # Time-sensitive
    "today", "tonight", "tomorrow", "yesterday", "this week",
    "current", "currently", "right now", "latest", "recent",
    "news", "breaking", "update", "updates",
    # Real-world data
    "weather", "temperature", "forecast", "rain", "sunny",
    "price", "prices", "cost", "stock", "market", "exchange rate",
    "score", "result", "match", "game", "sports",
    "election", "vote", "president", "prime minister",
    "covid", "pandemic", "virus",
    # Year references (current or near-future)
    "2024", "2025", "2026", "2027",
    # Explicit search intent
    "search for", "look up", "find out", "what is the latest",
    "who won", "what happened",
    # Japanese Time-sensitive
    "今日", "今夜", "明日", "昨日", "今週",
    "現在", "今", "最新", "最近",
    "ニュース", "速報", "更新", "アップデート",
    # Japanese Real-world data
    "天気", "気温", "予報", "雨", "晴れ",
    "価格", "値段", "料金", "株価", "市場", "為替",
    "スコア", "結果", "試合", "ゲーム", "スポーツ",
    "選挙", "投票", "大統領", "首相",
    "コロナ", "パンデミック", "ウイルス",
    # Japanese Explicit search intent
    "検索", "調べて", "探して", "最新の",
    "誰が勝った", "何が起こった", "どうなった",
}

# Phrases that strongly indicate BUILDING even if other words present
_BUILDING_OVERRIDE_PHRASES: list[str] = [
    "in this building", "in the building", "on this floor",
    "in this office", "at this location",
    # Japanese equivalents
    "この建物", "この階", "このオフィス", "この場所",
]


# ---------------------------------------------------------------------------
# Embedding-based fallback (optional, uses RAG embedder if available)
# ---------------------------------------------------------------------------

# Anchor phrases per intent — used for cosine similarity fallback
_BUILDING_ANCHORS = [
    "where is the conference room",
    "how do I get to the cafeteria",
    "which floor is the gym on",
    "find the nearest toilet",
    # Japanese anchors
    "会議室はどこですか",
    "カフェテリアへの行き方を教えて",
    "ジムは何階にありますか",
    "一番近いトイレを探して",
]

_SEARCH_ANCHORS = [
    "what is the weather today",
    "latest news about",
    "current stock price",
    "who won the match",
    # Japanese anchors
    "今日の天気はどうですか",
    "最新のニュースを教えて",
    "現在の株価は",
    "試合の結果は誰が勝った",
]

_GENERAL_ANCHORS = [
    "tell me a joke",
    "what is the capital of France",
    "how do I write a Python function",
    "explain quantum computing",
    # Japanese anchors
    "ジョークを教えて",
    "フランスの首都は何ですか",
    "Python関数の書き方を教えて",
    "量子コンピューティングを説明して",
]


class IntentClassifier:
    """
    Lightweight intent classifier.

    Usage:
        classifier = IntentClassifier()
        result = classifier.classify("where is the cafeteria?")
        # result.intent == Intent.BUILDING
    """

    def __init__(self, embedder=None):
        """
        Args:
            embedder: Optional sentence-transformer Embedder instance.
                      If provided, used as fallback for ambiguous queries.
                      Pass the same instance already loaded for RAG to avoid
                      loading a second model.
        """
        self._embedder = embedder
        self._anchor_embeddings: Optional[dict] = None

        if embedder is not None:
            self._precompute_anchors()

        logger.info("IntentClassifier initialized")

    def _precompute_anchors(self):
        """Pre-compute anchor embeddings once at startup."""
        try:
            all_anchors = _BUILDING_ANCHORS + _SEARCH_ANCHORS + _GENERAL_ANCHORS
            embeddings = self._embedder.encode(all_anchors)
            n_b = len(_BUILDING_ANCHORS)
            n_s = len(_SEARCH_ANCHORS)
            self._anchor_embeddings = {
                Intent.BUILDING: embeddings[:n_b],
                Intent.SEARCH:   embeddings[n_b:n_b + n_s],
                Intent.GENERAL:  embeddings[n_b + n_s:],
            }
            logger.info("Intent anchor embeddings pre-computed")
        except Exception as e:
            logger.warning(f"Failed to pre-compute intent anchors: {e}")
            self._anchor_embeddings = None

    # ------------------------------------------------------------------

    def classify(self, text: str, history: list[dict] | None = None) -> ClassificationResult:
        """
        Classify the intent of a user query.

        Args:
            text:    Current user query
            history: Recent conversation history (used to resolve follow-ups)

        Returns:
            ClassificationResult with intent, confidence, and debug info
        """
        text_lower = text.lower().strip()

        # --- Tier 1: keyword rules ---
        result = self._keyword_classify(text_lower)
        if result.confidence >= 0.7:
            logger.debug(
                f"Intent (keyword): {result.intent.value} "
                f"conf={result.confidence:.2f} matched={result.matched_keywords}"
            )
            return result

        # --- Tier 1b: check conversation history for context carry-over ---
        # e.g. "what about the ground floor?" after a building question
        if history:
            history_intent = self._infer_from_history(history)
            if history_intent is not None:
                logger.debug(f"Intent (history carry-over): {history_intent.value}")
                return ClassificationResult(
                    intent=history_intent,
                    confidence=0.75,
                    method="history",
                    matched_keywords=[],
                )

        # --- Tier 2: embedding similarity (if available) ---
        if self._anchor_embeddings is not None:
            emb_result = self._embedding_classify(text)
            if emb_result.confidence >= 0.6:
                logger.debug(
                    f"Intent (embedding): {emb_result.intent.value} "
                    f"conf={emb_result.confidence:.2f}"
                )
                return emb_result

        # --- Default: GENERAL ---
        logger.debug("Intent: GENERAL (default)")
        return ClassificationResult(
            intent=Intent.GENERAL,
            confidence=0.5,
            method="default",
            matched_keywords=[],
        )

    # ------------------------------------------------------------------

    def _keyword_classify(self, text_lower: str) -> ClassificationResult:
        # Check building override phrases first
        for phrase in _BUILDING_OVERRIDE_PHRASES:
            if phrase in text_lower:
                return ClassificationResult(
                    intent=Intent.BUILDING,
                    confidence=0.95,
                    method="keyword",
                    matched_keywords=[phrase],
                )

        # Count keyword hits per intent
        building_hits = [kw for kw in _BUILDING_KEYWORDS if kw in text_lower]
        search_hits   = [kw for kw in _SEARCH_KEYWORDS   if kw in text_lower]

        building_score = len(building_hits)
        search_score   = len(search_hits)

        if building_score == 0 and search_score == 0:
            return ClassificationResult(
                intent=Intent.GENERAL,
                confidence=0.4,
                method="keyword",
                matched_keywords=[],
            )

        if building_score > search_score:
            conf = min(0.6 + building_score * 0.1, 0.95)
            return ClassificationResult(
                intent=Intent.BUILDING,
                confidence=conf,
                method="keyword",
                matched_keywords=building_hits[:5],
            )

        if search_score > building_score:
            conf = min(0.6 + search_score * 0.1, 0.95)
            return ClassificationResult(
                intent=Intent.SEARCH,
                confidence=conf,
                method="keyword",
                matched_keywords=search_hits[:5],
            )

        # Tie — slight preference for BUILDING (kiosk context)
        return ClassificationResult(
            intent=Intent.BUILDING,
            confidence=0.55,
            method="keyword",
            matched_keywords=building_hits[:3],
        )

    def _infer_from_history(self, history: list[dict]) -> Optional[Intent]:
        """
        If the last assistant turn was a building/search response,
        carry that intent forward for short follow-up queries.
        """
        # Only apply to short follow-up queries (resolved by caller)
        # Look at the last user message's classified intent via keywords
        for turn in reversed(history[-4:]):
            if turn.get("role") == "user":
                content = turn.get("content", "").lower()
                building_hits = [kw for kw in _BUILDING_KEYWORDS if kw in content]
                if building_hits:
                    return Intent.BUILDING
                search_hits = [kw for kw in _SEARCH_KEYWORDS if kw in content]
                if search_hits:
                    return Intent.SEARCH
        return None

    def _embedding_classify(self, text: str) -> ClassificationResult:
        """Cosine similarity against pre-computed anchor embeddings."""
        import numpy as np

        try:
            query_emb = self._embedder.encode([text])[0]
            query_emb = query_emb / (np.linalg.norm(query_emb) + 1e-9)

            best_intent = Intent.GENERAL
            best_score  = 0.0

            for intent, anchors in self._anchor_embeddings.items():
                # Normalise anchors
                norms = np.linalg.norm(anchors, axis=1, keepdims=True) + 1e-9
                normed = anchors / norms
                scores = normed @ query_emb
                score  = float(scores.max())
                if score > best_score:
                    best_score  = score
                    best_intent = intent

            return ClassificationResult(
                intent=best_intent,
                confidence=best_score,
                method="embedding",
                matched_keywords=[],
            )
        except Exception as e:
            logger.warning(f"Embedding classification failed: {e}")
            return ClassificationResult(
                intent=Intent.GENERAL,
                confidence=0.4,
                method="embedding_error",
                matched_keywords=[],
            )
