"""Schemas the LLM must fill (sent to Ollama as JSON schema).

Field order matters: evidence first, then rationale, then the score or verdict.
Kept small and flat because the model is a 4B instruct model with a 16k context.
"""

from typing import Annotated, Literal

from pydantic import BaseModel, Field

from bsa.domain.enums import (
    ArcShape,
    CliffTechnique,
    ContinuityType,
    DepictionMode,
    ElementKind,
    Emotion,
    FactorName,
    Impact,
    LocIssueType,
    LowMedHigh,
    RatingCategory,
    Severity,
    SubstanceKind,
    SuggestionCategory,
    Treatment,
)

# Bounded lists: Ollama's grammar honours maxItems, which stops small models from looping on ID lists.
Ids3 = Annotated[list[str], Field(max_length=3)]
Ids4 = Annotated[list[str], Field(max_length=4)]
Ids6 = Annotated[list[str], Field(max_length=6)]
Ids12 = Annotated[list[str], Field(max_length=12)]
# Bounded strings: the grammar caps runaway generation (the 4B model looped inside Tamil strings without this).
Short = Annotated[str, Field(max_length=200)]
Text = Annotated[str, Field(max_length=500)]
Long = Annotated[str, Field(max_length=900)]


class CharacterOut(BaseModel):
    name: Short
    line_ids: Ids3
    want: Short
    obstacle: Short


class Grounded(BaseModel):
    line_ids: Ids4
    text: Text


class BeatOut(BaseModel):
    start_line: str
    end_line: str
    label: Short


class StoryMapOut(BaseModel):
    is_script: bool
    logline: Text
    characters: list[CharacterOut] = Field(max_length=6)
    central_conflict: Grounded
    stakes: Grounded
    beats: list[BeatOut] = Field(max_length=60)
    premise_tags: list[str] = Field(max_length=6)
    devanagari_language: Literal["hi", "mr", "none"]


class SceneTensionOut(BaseModel):
    scene_id: str
    tension: int = Field(ge=0, le=10)


class EpisodeOut(BaseModel):
    one_line_summary: Text
    scene_tension: list[SceneTensionOut] = Field(max_length=30)
    ending_line_ids: Ids3
    ending_weakness: Text
    ending_rationale: Text
    ending_hook_strength: int = Field(ge=1, le=5)
    cliffhanger_candidate_line_id: str


class SummaryOut(BaseModel):
    line_ids: Ids6
    text: Long


class EmotionPointOut(BaseModel):
    beat_id: str
    emotion: Emotion
    secondary: Emotion | Literal["none"]
    valence: float = Field(ge=-1, le=1)
    intensity: float = Field(ge=0, le=1)


class DominantOut(BaseModel):
    emotion: Emotion
    share: float = Field(ge=0, le=1)


class EmotionOut(BaseModel):
    arc: list[EmotionPointOut] = Field(max_length=60)
    dominant: list[DominantOut] = Field(max_length=3)
    arc_shape: ArcShape
    narrative: Long


class FactorOut(BaseModel):
    name: FactorName
    evidence_line_ids: Ids3
    weakness: str  # the biggest weakness for this factor, with a line ID
    rationale: Text
    score: int = Field(ge=1, le=5)


class EngagementOut(BaseModel):
    factors: list[FactorOut] = Field(max_length=8)


class SingleFactorOut(BaseModel):
    evidence_line_ids: Ids3
    weakness: Text
    rationale: Text
    score: int = Field(ge=1, le=5)


class CliffhangerOut(BaseModel):
    line_id: str
    quote: Text
    technique: CliffTechnique
    why_it_works: Text
    strength: int = Field(ge=1, le=5)


class ContinuityIssueOut(BaseModel):
    type: ContinuityType
    line_ids: Ids4
    explanation: Text
    severity: LowMedHigh


class ContinuityOut(BaseModel):
    issues: list[ContinuityIssueOut] = Field(max_length=8)


class SuggestionOut(BaseModel):
    category: SuggestionCategory
    linked_factor: FactorName
    target_line_ids: Ids4
    issue: Text
    fix: Text
    example_rewrite: Long
    impact: Impact


class SuggestionsOut(BaseModel):
    suggestions: list[SuggestionOut] = Field(max_length=8)


class FindingOut(BaseModel):
    category: RatingCategory
    line_ids: Ids12
    mode: DepictionMode
    treatment: Treatment
    substance: SubstanceKind
    rationale: Text
    severity: Severity


class LegalFlagOut(BaseModel):
    flag_id: str
    line_ids: Ids4
    rationale: Text


class RatingClassifyOut(BaseModel):
    findings: list[FindingOut] = Field(max_length=16)
    legal_flags: list[LegalFlagOut] = Field(max_length=5)


class LowerEditOut(BaseModel):
    driver: int  # index into the drivers list given in the task
    line_ids: Ids4
    edit: Text
    rewrite: Text


class RatingLowerOut(BaseModel):
    edits: list[LowerEditOut] = Field(max_length=8)


class LocIssueOut(BaseModel):
    line_ids: Ids4
    type: LocIssueType
    explanation: Text
    adaptation: Text
    severity: LowMedHigh


class TranscreationOut(BaseModel):
    line_id: str
    target_text: Text
    back_translation: Text
    notes: Short


class LocalizationOut(BaseModel):
    issues: list[LocIssueOut] = Field(max_length=10)
    fit_rationale: Text
    fit_score: int = Field(ge=1, le=5)
    transcreations: list[TranscreationOut] = Field(max_length=6)


class TropeOut(BaseModel):
    trope_id: str
    line_ids: Ids3
    rationale: Text
    confidence: float = Field(ge=0, le=1)


class TropesOut(BaseModel):
    tropes: list[TropeOut] = Field(max_length=6)


class CompExplainOut(BaseModel):
    candidate: int
    why_similar: Text
    differentiator: Text
    near_identical: bool


class CompsExplainOut(BaseModel):
    comps: list[CompExplainOut] = Field(max_length=5)


class NewElementOut(BaseModel):
    kind: Literal["action", "dialogue", "parenthetical", "transition"]
    speaker: str | None
    text: Text


class VariantOut(BaseModel):
    strategy: Short
    pays_off_line_ids: Ids4
    rationale: Text
    elements: list[NewElementOut] = Field(max_length=10)


class AltGenerateOut(BaseModel):
    variants: list[VariantOut] = Field(max_length=3)


class JudgeOut(BaseModel):
    reasoning: Text
    x_coherent: bool
    y_coherent: bool
    winner: Literal["X", "Y", "tie"]


class LayoutElementOut(BaseModel):
    kind: ElementKind
    speaker: str | None
    text: str


class LayoutOut(BaseModel):
    elements: list[LayoutElementOut]


class EpisodeBoundariesOut(BaseModel):
    episode_start_scene_ids: list[str] = Field(max_length=30)
