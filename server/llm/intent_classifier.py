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
    "escalator", "exit", "exits", "entrance", "lobby",
    # Facilities
    "cafeteria", "canteen",
    "toilet", "restroom", "bathroom", "washroom", "wc",
    "conference", "meeting room", "boardroom", "auditorium",
    "parking", "car park", "garage",
    "gym", "fitness", "medical", "clinic", "pharmacy",
    "atm",
    "rooftop",
    # Navigation phrases
    "where is", "directions to",
    "location of",
    "which floor", "what floor",
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
    "election", "vote", "president", "prime minister", "minister",
    "covid", "pandemic", "virus",
    # Government and politics
    "government", "parliament", "congress", "senate", "cabinet",
    "leader", "ruler", "chief", "head of state", "head of government",
    "political", "politics", "policy", "law", "legislation",
    # Countries and world events
    "nepal", "nepalese", "kathmandu", "china", "chinese", "beijing",
    "india", "indian", "delhi", "japan", "japanese", "tokyo",
    "usa", "america", "american", "washington", "europe", "european",
    # Current events indicators - be more specific to avoid math questions
    "who is the", "who was the", "who became", "who won", "who lost",
    "what is the current", "what is the latest", "what happened", "what's happening",
    "when did", "when will", "where is the", "how much does", "how many people",
    # Year references (current or near-future)
    "2024", "2025", "2026", "2027",
    # Explicit search intent
    "search for", "look up", "find out", "what is the latest",
    "who won", "what happened", "tell me about", "information about",
    # Japanese Time-sensitive
    "今日", "今夜", "明日", "昨日", "今週",
    "現在", "今", "最新", "最近",
    "ニュース", "速報", "更新", "アップデート",
    # Japanese Real-world data
    "天気", "気温", "予報", "雨", "晴れ",
    "価格", "値段", "料金", "株価", "市場", "為替",
    "スコア", "結果", "試合", "ゲーム", "スポーツ",
    "選挙", "投票", "大統領", "首相", "総理", "大臣",
    "コロナ", "パンデミック", "ウイルス",
    # Japanese Countries and politics
    "ネパール", "中国", "インド", "日本", "アメリカ",
    "政府", "政治", "国会", "議会", "内閣",
    "リーダー", "指導者", "元首", "政治家",
    # Japanese question words
    "誰", "誰が", "誰は", "何", "何が", "何は",
    "いつ", "どこ", "どう", "どのように",
    # Japanese Explicit search intent
    "検索", "調べて", "探して", "最新の",
    "誰が勝った", "何が起こった", "どうなった", "について教えて",
}

# Phrases that strongly indicate BUILDING even if other words present
_BUILDING_OVERRIDE_PHRASES: list[str] = [
    "in this building", "in the building", "on this floor",
    "in this office", "at this location",
    # Japanese equivalents
    "この建物", "この階", "このオフィス", "この場所",
]

# ---------------------------------------------------------------------------
# Context-requiring patterns for ambiguous building words
# ---------------------------------------------------------------------------

# Unambiguous building context anchors used in context patterns
_BUILDING_CONTEXT_WORDS = (
    r"floor|level|building|lobby|office|room|wing|block|site|"
    r"cafeteria|canteen|toilet|restroom|bathroom|washroom|gym|fitness|"
    r"clinic|pharmacy|conference|meeting|parking|elevator|lift|stairs|"
    r"entrance|exit|rooftop|auditorium|atm|"
    r"階|フロア|部屋|建物|ここ|この"
)

# Patterns that rescue ambiguous words when they appear in a building context.
# Each pattern requires the ambiguous word to co-occur with a building context word.
_BUILDING_CONTEXT_PATTERNS: list[re.Pattern] = [
    # "restaurant on floor 3", "coffee in this building", "shop here"
    re.compile(
        r"\b(?:restaurant|cafe|coffee|shop|store|bank|garden|terrace|retail|reception)\b"
        r".{0,30}"
        r"\b(?:" + _BUILDING_CONTEXT_WORDS + r")\b",
        re.IGNORECASE,
    ),
    # "floor 2 restaurant", "building cafe", "this shop"
    re.compile(
        r"\b(?:" + _BUILDING_CONTEXT_WORDS + r")\b"
        r".{0,30}"
        r"\b(?:restaurant|cafe|coffee|shop|store|bank|garden|terrace|retail|reception)\b",
        re.IGNORECASE,
    ),
    # "nearest toilet", "closest restroom", "located near the cafeteria"
    re.compile(
        r"\b(?:nearest|closest|located)\b"
        r".{0,20}"
        r"\b(?:toilet|restroom|bathroom|washroom|cafeteria|canteen|gym|fitness|"
        r"clinic|pharmacy|conference|meeting|parking|elevator|lift|stairs|"
        r"entrance|exit|lobby|atm|トイレ|お手洗い|化粧室|カフェテリア|ジム)\b",
        re.IGNORECASE,
    ),
    # "find the cafeteria", "how to get to the toilet", "how do i get to the gym"
    re.compile(
        r"\b(?:find the|how to get|how do i get)\b"
        r".{0,30}"
        r"\b(?:toilet|restroom|bathroom|washroom|cafeteria|canteen|gym|fitness|"
        r"clinic|pharmacy|conference|meeting|parking|elevator|lift|stairs|"
        r"entrance|exit|lobby|atm|トイレ|お手洗い|化粧室|カフェテリア|ジム)\b",
        re.IGNORECASE,
    ),
]


_CONVERSATIONAL_INPUTS: set[str] = {
    # English greetings
    "hello", "hi", "hey", "howdy", "greetings", "sup", "yo",
    "good morning", "good afternoon", "good evening", "good night",
    # English acknowledgements
    "thanks", "thank you", "okay", "ok", "sure", "yes", "no",
    "got it", "understood", "alright", "cool", "great", "nice",
    # Japanese greetings
    "こんにちは", "おはよう", "おはようございます", "こんばんは",
    "やあ", "どうも",
    # Japanese acknowledgements
    "ありがとう", "ありがとうございます", "わかりました", "はい",
    "いいえ", "なるほど", "そうですか", "了解",
}


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
    # Short greeting-like phrases (secondary defense for embedding tier)
    "hello",
    "hi there",
    "good morning",
    "thanks",
    "okay",
    "sure",
    "こんにちは",
    "ありがとう",
    "はい",
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

        # --- Tier 0: conversational guard ---
        # Intercept known greetings and acknowledgements before keyword/embedding stages
        if self._is_conversational(text_lower):
            logger.debug(f"Intent (conversational guard): GENERAL for '{text_lower[:20]}'")
            return ClassificationResult(
                intent=Intent.GENERAL,
                confidence=0.95,
                method="conversational_guard",
                matched_keywords=[],
            )

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

    def _is_conversational(self, text_lower: str) -> bool:
        """
        Returns True if the input is a conversational greeting or acknowledgement
        that should be classified as GENERAL without going through keyword or
        embedding tiers.

        Two conditions trigger True:
        1. Exact match in _CONVERSATIONAL_INPUTS (explicit list)
        2. Short phrase (≤ 3 words, ≤ 15 chars) with no keyword hits
           (catches unlisted greeting variants)

        Returns False for all other inputs — including short phrases that DO
        contain a keyword hit (e.g. "天気" must NOT be intercepted).
        """
        # Condition 1: explicit conversational input list
        if text_lower in _CONVERSATIONAL_INPUTS:
            return True

        # Condition 2: short phrase with no keyword hits
        # (catches unlisted greeting variants like "yo there", "hiya", etc.)
        words = text_lower.split()
        word_count = len(words)
        char_count = len(text_lower)

        if word_count <= 3 and char_count <= 15:
            # Only intercept if there are NO keyword hits
            has_building_hit = any(kw in text_lower for kw in _BUILDING_KEYWORDS)
            has_search_hit = any(kw in text_lower for kw in _SEARCH_KEYWORDS)
            if not has_building_hit and not has_search_hit:
                return True

        return False

    # ------------------------------------------------------------------

    def _building_context_match(self, text_lower: str) -> list[str]:
        """
        Returns a list of matched context pattern descriptions for text_lower.
        Returns an empty list if no context patterns match.

        Used by _keyword_classify to rescue ambiguous words (e.g. "restaurant",
        "shop", "find the") when they appear alongside a building context word.
        """
        matched = []
        for i, pattern in enumerate(_BUILDING_CONTEXT_PATTERNS):
            m = pattern.search(text_lower)
            if m:
                matched.append(f"context_pattern_{i}:{m.group(0)[:30]}")
        return matched

    # ------------------------------------------------------------------

    def _keyword_classify(self, text_lower: str) -> ClassificationResult:
        # Check building override phrases first
        for phrase in _BUILDING_OVERRIDE_PHRASES:
            if phrase in text_lower:
                logger.debug(f"Building override phrase matched: '{phrase}'")
                return ClassificationResult(
                    intent=Intent.BUILDING,
                    confidence=0.95,
                    method="keyword",
                    matched_keywords=[phrase],
                )

        # Count keyword hits per intent
        building_hits = [kw for kw in _BUILDING_KEYWORDS if kw in text_lower]
        search_hits   = [kw for kw in _SEARCH_KEYWORDS   if kw in text_lower]

        # Add context pattern hits to building score (rescues ambiguous words in building context)
        context_hits = self._building_context_match(text_lower)
        building_hits = building_hits + context_hits

        building_score = len(building_hits)
        search_score   = len(search_hits)
        
        # Enhanced logging for debugging
        logger.debug(f"Keyword analysis: text='{text_lower[:50]}...'")
        logger.debug(f"Building hits ({building_score}): {building_hits[:5]}")
        logger.debug(f"Search hits ({search_score}): {search_hits[:5]}")

        if building_score == 0 and search_score == 0:
            logger.debug("No keywords matched - defaulting to GENERAL")
            return ClassificationResult(
                intent=Intent.GENERAL,
                confidence=0.4,
                method="keyword",
                matched_keywords=[],
            )

        if building_score > search_score:
            conf = min(0.6 + building_score * 0.1, 0.95)
            logger.debug(f"Building wins: {building_score} > {search_score}, conf={conf:.2f}")
            return ClassificationResult(
                intent=Intent.BUILDING,
                confidence=conf,
                method="keyword",
                matched_keywords=building_hits[:5],
            )

        if search_score > building_score:
            conf = min(0.6 + search_score * 0.1, 0.95)
            logger.debug(f"Search wins: {search_score} > {building_score}, conf={conf:.2f}")
            return ClassificationResult(
                intent=Intent.SEARCH,
                confidence=conf,
                method="keyword",
                matched_keywords=search_hits[:5],
            )

        # Tie — slight preference for BUILDING (kiosk context)
        logger.debug(f"Tie: {building_score} = {search_score}, defaulting to BUILDING")
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
