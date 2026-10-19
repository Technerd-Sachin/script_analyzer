"""The analysis report: the contract shared by the pipeline, API, UI and tests."""

from typing import Any, Literal

from pydantic import BaseModel, Field

from bsa.domain.enums import (
    ArcShape,
    CliffTechnique,
    ContinuityType,
    DepictionMode,
    Emotion,
    FactorName,
    Impact,
    LocIssueType,
    LowMedHigh,
    Momentum,
    PairResult,
    RatingBand,
    RatingCategory,
    Severity,
    Status,
    SubstanceKind,
    SuggestionCategory,
    Treatment,
)
from bsa.domain.ir import Element
from bsa.domain.options import AnalysisOptions


class Section(BaseModel):
    status: Status = "ok"
    notes: list[str] = Field(default_factory=list)


# ---- story ----------------------------------------------------------------------------------
class Character(BaseModel):
    name: str
    want: str
    obstacle: str
    line_ids: list[str]


class GroundedText(BaseModel):
    text: str
    line_ids: list[str]


class Beat(BaseModel):
    id: str
    label: str
    line_ids: list[str]


class StoryMap(Section):
    is_script: bool = True
    logline: str = ""
    characters: list[Character] = Field(default_factory=list)
    central_conflict: GroundedText | None = None
    stakes: GroundedText | None = None
    beats: list[Beat] = Field(default_factory=list)
    premise_tags: list[str] = Field(default_factory=list)
    devanagari_language: str = "none"


class SceneTension(BaseModel):
    scene_id: str
    tension: int


class EpisodeReport(BaseModel):
    number: int
    one_line_summary: str
    scene_tension: list[SceneTension]
    ending_line_ids: list[str]
    ending_hook_strength: int
    ending_rationale: str
    cliffhanger_candidate_line_id: str | None = None


class EpisodesReport(Section):
    items: list[EpisodeReport] = Field(default_factory=list)


class Summary(Section):
    text: str = ""
    line_ids: list[str] = Field(default_factory=list)


class EmotionPoint(BaseModel):
    beat_id: str
    line_ids: list[str]
    emotion: Emotion
    secondary: Emotion | None = None
    valence: float
    intensity: float


class DominantEmotion(BaseModel):
    emotion: Emotion
    share: float


class EmotionReport(Section):
    dominant: list[DominantEmotion] = Field(default_factory=list)
    arc: list[EmotionPoint] = Field(default_factory=list)
    arc_shape: ArcShape | None = None
    narrative: str = ""


class FactorScore(BaseModel):
    name: FactorName
    evidence_line_ids: list[str]
    weakness: str = ""
    rationale: str
    score: float  # median across runs
    weight: float
    run_scores: list[int] = Field(default_factory=list)


class EngagementReport(Section):
    factors: list[FactorScore] = Field(default_factory=list)
    overall: float | None = None
    confidence: float | None = None
    runs: int = 0
    per_run_overall: list[float] = Field(default_factory=list)


class Cliffhanger(Section):
    line_id: str | None = None
    quote: str = ""
    technique: CliffTechnique | None = None
    why_it_works: str = ""
    strength: int | None = None


class Suggestion(BaseModel):
    id: str
    category: SuggestionCategory
    linked_factor: FactorName
    target_line_ids: list[str]
    issue: str
    fix: str
    example_rewrite: str
    impact: Impact


class SuggestionsReport(Section):
    items: list[Suggestion] = Field(default_factory=list)


# ---- analytics and continuity ---------------------------------------------------------------
class SpeakerShare(BaseModel):
    speaker: str
    lines: int
    words: int
    share: float


class Edge(BaseModel):
    a: str
    b: str
    weight: int


class Analytics(Section):
    runtime_s_by_episode: dict[str, dict[str, float]] = Field(
        default_factory=dict
    )  # ep -> page_based/word_based
    runtime_s_total: dict[str, float] = Field(default_factory=dict)
    dialogue_share: list[SpeakerShare] = Field(default_factory=list)
    network_nodes: list[str] = Field(default_factory=list)
    network_edges: list[Edge] = Field(default_factory=list)
    scene_stats: dict[str, float] = Field(default_factory=dict)
    time_to_first_conflict_s: float | None = None


class ContinuityIssue(BaseModel):
    type: ContinuityType
    line_ids: list[str]
    explanation: str
    severity: LowMedHigh


class ContinuityReport(Section):
    issues: list[ContinuityIssue] = Field(default_factory=list)
    name_variant_candidates: list[list[str]] = Field(default_factory=list)


# ---- feature A: alternatives ----------------------------------------------------------------
class AltElement(BaseModel):
    id: str
    kind: str
    speaker: str | None = None
    text: str


class AltVariant(BaseModel):
    id: str
    strategy: str
    elements: list[AltElement]
    replaces_line_ids: list[str]
    pays_off_line_ids: list[str] = Field(default_factory=list)
    rationale: str
    pairwise: PairResult | None = None
    judge_votes: list[str] = Field(default_factory=list)
    score_before: float | None = None
    score_after: float | None = None
    delta: float | None = None
    coherence_ok: bool | None = None
    coherence_reason: str = ""
    language_preserved: bool | None = None
    length_ok: bool | None = None
    ids_ok: bool | None = None


class AltTarget(BaseModel):
    id: str
    kind: Literal["opening", "ending", "mid_ending"]
    episode: int
    factor: FactorName
    replaces_line_ids: list[str]
    variants: list[AltVariant] = Field(default_factory=list)
    dropped: list[str] = Field(default_factory=list)  # variants that broke a hard constraint


class AlternativesReport(Section):
    targets: list[AltTarget] = Field(default_factory=list)


# ---- feature B: rating ----------------------------------------------------------------------
class RatingFinding(BaseModel):
    category: RatingCategory
    severity: Severity
    mode: DepictionMode
    treatment: Treatment
    substance: SubstanceKind = "none"
    line_ids: list[str]
    rationale: str
    band: RatingBand | None = None


class Notice(BaseModel):
    rule_id: str
    source: str
    required_text: list[str]
    requirements: list[str] = Field(default_factory=list)
    placement: str
    trigger_line_ids: list[str]
    trigger_scenes: list[str] = Field(default_factory=list)


class LegalFlag(BaseModel):
    flag_id: str
    name: str
    severity: str
    line_ids: list[str]
    rationale: str


class LowerEdit(BaseModel):
    driver: str
    line_ids: list[str]
    edit: str
    rewrite: str


class RatingReport(Section):
    rating: RatingBand | None = None
    descriptors: list[str] = Field(default_factory=list)
    findings: list[RatingFinding] = Field(default_factory=list)
    rating_drivers: list[int] = Field(default_factory=list)  # indices into findings
    access_controls: list[str] = Field(default_factory=list)
    notices: list[Notice] = Field(default_factory=list)
    legal_risk_flags: list[LegalFlag] = Field(default_factory=list)
    lower_rating_edits: list[LowerEdit] = Field(default_factory=list)
    lower_rating_band: RatingBand | None = None
    prescan: dict[str, list[str]] = Field(default_factory=dict)  # lexicon category -> line ids
    disclaimer: str = (
        "Estimate to support editors. Not a certification and not legal advice. "
        "Knowledge files are unverified until reviewed."
    )


# ---- feature C: localization ----------------------------------------------------------------
class LocIssue(BaseModel):
    line_ids: list[str]
    type: LocIssueType
    severity: LowMedHigh
    explanation: str
    adaptation: str


class Transcreation(BaseModel):
    line_id: str
    source_text: str
    target_text: str
    back_translation: str
    notes: str
    subtitle_flags: list[str] = Field(default_factory=list)


class TargetFit(BaseModel):
    lang: str
    status: Literal["ok", "partial", "unavailable"] = "ok"
    fit_score: int | None = None
    fit_rationale: str = ""
    issues: list[LocIssue] = Field(default_factory=list)
    transcreations: list[Transcreation] = Field(default_factory=list)


class LocalizationReport(Section):
    source_languages: dict[str, float] = Field(default_factory=dict)
    code_mix_ratio: float | None = None
    source_subtitle_flags: list[dict[str, Any]] = Field(default_factory=list)
    targets: list[TargetFit] = Field(default_factory=list)
    disclaimer: str = "Machine transcreation. Native-speaker review required."


# ---- market ---------------------------------------------------------------------------------
class Comp(BaseModel):
    title: str
    year: int | None = None
    language: str | None = None
    rating: float | None = None
    votes: int | None = None
    similarity: float
    why_similar: str = ""
    differentiator: str = ""
    near_identical: bool = False
    source_url: str = ""


class TropeTag(BaseModel):
    trope_id: str
    name: str
    line_ids: list[str]
    rationale: str
    confidence: float
    momentum: Momentum = "unknown"
    as_of: str | None = None
    stale: bool = False


class MarketReport(Section):
    comps: list[Comp] = Field(default_factory=list)
    originality_flag: bool = False
    originality_note: str = ""
    tropes: list[TropeTag] = Field(default_factory=list)
    trend_snapshot_as_of: str | None = None


# ---- meta and report ------------------------------------------------------------------------
class NodeCall(BaseModel):
    node: str
    model: str
    prompt_tokens: int = 0  # tokens evaluated by Ollama for the prompt (lower when the prefix is reused)
    completion_tokens: int = 0
    latency_ms: int = 0
    prompt_eval_ms: int = 0  # prefill time; drops sharply when Ollama reuses the cached prefix
    repaired: bool = False
    stop_reason: str = ""


class Meta(BaseModel):
    models_by_node: dict[str, str] = Field(default_factory=dict)
    prompt_versions: dict[str, str] = Field(default_factory=dict)
    knowledge_version: str = ""
    tokens: dict[str, int] = Field(default_factory=dict)
    cost_usd: float = 0.0
    latency_ms_by_node: dict[str, int] = Field(default_factory=dict)
    total_latency_ms: int = 0
    calls: list[NodeCall] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    refusals: list[str] = Field(default_factory=list)
    created_at: str = ""


class AnalysisReport(BaseModel):
    doc_id: str
    cache_key: str = ""
    title: str | None = None
    options: AnalysisOptions
    ir_stats: dict[str, Any] = Field(default_factory=dict)
    story_map: StoryMap = Field(default_factory=StoryMap)
    summary: Summary = Field(default_factory=Summary)
    episodes: EpisodesReport = Field(default_factory=EpisodesReport)
    emotion: EmotionReport = Field(default_factory=EmotionReport)
    engagement: EngagementReport = Field(default_factory=EngagementReport)
    cliffhanger: Cliffhanger = Field(default_factory=Cliffhanger)
    suggestions: SuggestionsReport = Field(default_factory=SuggestionsReport)
    analytics: Analytics = Field(default_factory=Analytics)
    continuity: ContinuityReport = Field(default_factory=ContinuityReport)
    alternatives: AlternativesReport = Field(default_factory=AlternativesReport)
    rating: RatingReport = Field(default_factory=RatingReport)
    localization: LocalizationReport = Field(default_factory=LocalizationReport)
    market: MarketReport = Field(default_factory=MarketReport)
    meta: Meta = Field(default_factory=Meta)
    elements: list[Element] = Field(default_factory=list)  # the parsed script, for the viewer
