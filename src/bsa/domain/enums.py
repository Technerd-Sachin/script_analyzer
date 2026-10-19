"""Closed vocabularies shared by the LLM schemas, the API, the UI and the tests."""

from typing import Literal

LangCode = Literal["en", "hi", "hi-Latn", "ta", "te", "bn", "mr", "other"]  # hi-Latn = Hinglish
ElementKind = Literal[
    "scene_heading", "action", "dialogue", "parenthetical", "transition", "episode_marker", "other"
]
SourceKind = Literal["text", "fountain", "fdx", "docx", "pdf_digital", "pdf_scanned", "pdf_mixed", "image"]
PageSource = Literal["digital", "ocr", "vision"]
Status = Literal["ok", "partial", "unavailable"]
Feature = Literal["core", "analytics", "alternatives", "rating", "localization", "market"]
ALL_FEATURES: tuple[Feature, ...] = ("core", "analytics", "alternatives", "rating", "localization", "market")

Emotion = Literal["joy", "trust", "fear", "surprise", "sadness", "disgust", "anger", "anticipation"]
ArcShape = Literal["rise", "fall", "fall_rise", "rise_fall", "rise_fall_rise", "fall_rise_fall", "flat"]
FactorName = Literal[
    "opening_hook",
    "central_conflict",
    "tension_escalation",
    "cliffhanger_pull",
    "stakes",
    "character_clarity",
    "dialogue_quality",
    "pacing",
]
FACTORS: tuple[FactorName, ...] = (
    "opening_hook",
    "central_conflict",
    "tension_escalation",
    "cliffhanger_pull",
    "stakes",
    "character_clarity",
    "dialogue_quality",
    "pacing",
)
CliffTechnique = Literal[
    "revelation", "reversal", "threat", "unanswered_question", "arrival", "decision_point", "emotional_shock"
]
SuggestionCategory = Literal[
    "pacing", "conflict", "dialogue", "emotion", "hook", "cliffhanger", "character", "clarity"
]
Impact = Literal["high", "medium", "low"]
ContinuityType = Literal["name", "timeline", "fact", "object", "location"]

RatingBand = Literal["U", "U/A 7+", "U/A 13+", "U/A 16+", "A"]
BANDS: tuple[RatingBand, ...] = ("U", "U/A 7+", "U/A 13+", "U/A 16+", "A")
RatingCategory = Literal[
    "violence", "language", "sex", "nudity", "substances", "imitable_behaviour", "discrimination", "theme"
]
RATING_CATEGORIES: tuple[RatingCategory, ...] = (
    "violence",
    "language",
    "sex",
    "nudity",
    "substances",
    "imitable_behaviour",
    "discrimination",
    "theme",
)
Severity = Literal["none", "mild", "moderate", "strong", "explicit"]
DepictionMode = Literal["depicted", "referenced", "implied"]
Treatment = Literal["condemned", "neutral", "glorified", "instructional"]
SubstanceKind = Literal["none", "tobacco", "alcohol", "narcotics", "other"]

LocIssueType = Literal[
    "culture_bound_reference",
    "festival_ritual",
    "food",
    "idiom_wordplay",
    "humor",
    "honorific_register",
    "name_or_place",
    "religious_caste_sensitivity",
    "regional_stereotype",
    "song_lyric_quote",
    "on_screen_text",
    "dub_sync_risk",
    "subtitle_length",
]
LowMedHigh = Literal["low", "medium", "high"]

OpeningStrategy = Literal[
    "in_medias_res",
    "mystery_question",
    "shock_reveal",
    "flash_forward",
    "conflict_first_line",
    "voiceover_hook",
]
EndingStrategy = Literal[
    "revelation", "reversal", "threat", "unanswered_question", "emotional_gut_punch", "arrival"
]
PairResult = Literal["win", "tie", "loss"]
Momentum = Literal["rising", "stable", "declining", "saturated", "unknown"]
