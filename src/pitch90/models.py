"""Data models shared across extraction, analysis, evidence checks and rendering.

The ``LLM*`` models define exactly what the language model must return; they are
converted to JSON Schema for structured output and validated again on receipt.
Domain models extend them with fields the application owns (origin, citation
checks, flags) so the model can never set those itself.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field

NOT_PROVIDED = "Not provided"


# --------------------------------------------------------------------------- extraction


class UnitContent(BaseModel):
    """One slide (PPTX/PPT) or page (PDF), numbered as in the original file."""

    number: int
    text: str = ""
    notes: str = ""
    tables: list[list[list[str]]] = Field(default_factory=list)
    chart_data: list[str] = Field(default_factory=list)
    ocr_text: str = ""
    image_count: int = 0
    hidden: bool = False
    needs_visual: bool = False
    visual_reason: str | None = None
    warnings: list[str] = Field(default_factory=list)

    @property
    def all_text(self) -> str:
        """Every piece of text from this unit, used for citation checks."""
        parts = [self.text, self.notes, self.ocr_text, *self.chart_data]
        parts += [" | ".join(row) for table in self.tables for row in table]
        return "\n".join(p for p in parts if p)

    @property
    def visible_text(self) -> str:
        parts = [self.text, self.ocr_text, *self.chart_data]
        parts += [" | ".join(row) for table in self.tables for row in table]
        return "\n".join(p for p in parts if p)


class ExtractionWarning(BaseModel):
    severity: Literal["info", "warning", "error"]
    message: str
    units: list[int] = Field(default_factory=list)
    kind: Literal["extraction", "security"] = "extraction"


class ExtractedDeck(BaseModel):
    filename: str
    source_type: Literal["pdf", "pptx", "ppt"]
    unit_label: Literal["slide", "page"]
    units: list[UnitContent]
    warnings: list[ExtractionWarning] = Field(default_factory=list)
    converted_from_ppt: bool = False
    sha256: str = ""
    # In-memory PNG/JPEG renders of units needing visual interpretation.
    # Excluded from JSON exports.
    images: dict[int, bytes] = Field(default_factory=dict, exclude=True, repr=False)

    @property
    def unit_numbers(self) -> set[int]:
        return {u.number for u in self.units}

    def unit(self, number: int) -> UnitContent | None:
        return next((u for u in self.units if u.number == number), None)


# --------------------------------------------------------------------------- facts


class EvidenceStatus(str, Enum):
    STATED = "stated"
    CALCULATED = "calculated"
    INFERRED = "inferred"
    MISSING = "missing"
    CONFLICTING = "conflicting"


class FactCategory(str, Enum):
    COMPANY = "company"
    CUSTOMER_PROBLEM = "customer_problem"
    MARKET_SIZE = "market_size"
    REVENUE = "revenue"
    CUSTOMERS = "customers"
    PILOTS = "pilots"
    TRACTION_OTHER = "traction_other"
    CLINICAL_OR_TECHNICAL = "clinical_or_technical_results"
    PRODUCT = "product"
    BUSINESS_MODEL = "business_model"
    COMPETITION = "competition"
    TEAM = "team"
    CAPITAL_RAISED = "capital_raised"
    FUNDRAISING_TARGET = "fundraising_target"
    VALUATION_TERMS = "valuation_terms"
    USE_OF_FUNDS = "use_of_funds"
    MILESTONES = "milestones"
    EXIT = "exit"
    CONTACT = "contact"
    OTHER = "other"


class Basis(str, Enum):
    ACTUAL = "actual"
    FORECAST = "forecast"
    TARGET = "target"
    NOT_APPLICABLE = "not_applicable"
    UNCLEAR = "unclear"


class Commitment(str, Enum):
    """Distinguishes signed customers from prospects, pilots from deployments,
    and capital raised from capital sought."""

    SIGNED_CUSTOMER = "signed_customer"
    COMMERCIAL_DEPLOYMENT = "commercial_deployment"
    PAID_PILOT = "paid_pilot"
    UNPAID_PILOT = "unpaid_pilot"
    PILOT_UNSPECIFIED = "pilot_unspecified"
    LOI_OR_MOU = "loi_or_mou"
    PROSPECT = "prospect"
    CAPITAL_RAISED = "capital_raised"
    CAPITAL_COMMITTED = "capital_committed"
    CAPITAL_SOUGHT = "capital_sought"
    NOT_APPLICABLE = "not_applicable"
    UNCLEAR = "unclear"


class LLMFact(BaseModel):
    key: str = Field(description="Stable snake_case identifier, e.g. 'arr', 'pilot_customers'. Reuse the same key for the same metric so conflicts can be detected.")
    category: FactCategory
    label: str = Field(description="Short human-readable label.")
    value: str = Field(description="Value exactly as supported by the deck, or 'Not provided'.")
    unit: str | None = Field(default=None, description="Currency or unit, e.g. 'USD', '%', 'customers'.")
    period: str | None = Field(default=None, description="Period or date the value applies to, as stated.")
    basis: Basis
    commitment: Commitment
    source_pages: list[int] = Field(description="Original slide/page numbers where this appears. Empty for missing facts.")
    excerpt: str | None = Field(default=None, description="Verbatim supporting excerpt copied from the cited slide/page (<= 200 chars).")
    status: EvidenceStatus
    formula: str | None = Field(default=None, description="Required when status is 'calculated'. Arithmetic using numbers only, e.g. '120000 * 12 = 1440000'.")
    note: str | None = Field(default=None, description="Definitions, caveats, or why the fact is inferred/conflicting.")


class Origin(str, Enum):
    DECK = "deck"
    USER = "user_provided"


class CitationCheck(str, Enum):
    VERIFIED = "excerpt_verified"
    NOT_FOUND = "excerpt_not_found_on_cited_pages"
    NO_EXCERPT = "no_excerpt"
    NO_CITATION = "no_citation"
    USER = "user_provided"


class Fact(LLMFact):
    id: str = ""
    origin: Origin = Origin.DECK
    citation_check: CitationCheck | None = None
    flags: list[str] = Field(default_factory=list)
    original_value: str | None = None


# --------------------------------------------------------------------------- narrative


class NarrativeElement(str, Enum):
    CUSTOMER_PROBLEM = "customer_problem"
    WHY_NOW = "why_now"
    DESIRED_OUTCOME = "desired_outcome"
    OBSTACLES_CAPABILITIES = "obstacles_capabilities"
    EVIDENCE = "evidence"


class ElementAssessment(BaseModel):
    element: NarrativeElement
    score: int = Field(description="Integer 0-5 per the rubric.")
    rationale: str
    source_pages: list[int]
    missing_or_weak: list[str]
    improvement: str = Field(description="One specific improvement.")


class ObstacleCapability(BaseModel):
    obstacle: str
    capability: str
    source_pages: list[int]


class CitedPoint(BaseModel):
    text: str
    source_pages: list[int]


class Inconsistency(BaseModel):
    description: str
    values: list[str]
    source_pages: list[int]


class ExtractionLimitation(BaseModel):
    pages: list[int]
    limitation: str
    effect_on_evaluation: str


class VisualObservation(BaseModel):
    page: int
    observation: str = Field(description="What the slide/page image shows that text extraction missed.")


class OnePagerSection(BaseModel):
    text: str = Field(description="Investor-facing prose using only deck-supported facts, or 'Not provided'.")
    citations: list[int] = Field(description="Slide/page numbers supporting the text.")


class TeamMember(BaseModel):
    name: str
    role: str
    qualifications: str
    citations: list[int]


class LLMOnePager(BaseModel):
    company_name: str
    website: str = Field(description="As stated in the deck, or 'Not provided'.")
    positioning: OnePagerSection = Field(description="One-sentence positioning statement.")
    problem_why_now: OnePagerSection
    solution_benefit: OnePagerSection
    market_business_model: OnePagerSection
    traction_evidence: OnePagerSection
    differentiation: OnePagerSection
    team: list[TeamMember]
    fundraising_target: OnePagerSection
    terms: OnePagerSection
    use_of_funds: OnePagerSection
    milestones: OnePagerSection
    exit_strategy: OnePagerSection = Field(description="Only if the deck states one; otherwise text 'Not provided'.")
    contact: OnePagerSection = Field(description="Contact details only if provided; otherwise 'Not provided'.")


class LLMAnalysis(BaseModel):
    company_name: str
    facts: list[LLMFact]
    elements: list[ElementAssessment] = Field(description="Exactly one entry per narrative element.")
    obstacle_capability_pairs: list[ObstacleCapability] = Field(description="Up to three.")
    strongest_points: list[CitedPoint] = Field(description="Exactly three.")
    priority_fixes: list[str] = Field(description="Exactly three, highest priority first.")
    inconsistencies: list[Inconsistency]
    information_gaps: list[str]
    extraction_limitations: list[ExtractionLimitation]
    visual_observations: list[VisualObservation]
    pitch_script: str = Field(description="Spoken pitch of 180-210 words using only supported facts.")
    onepager: LLMOnePager


# --------------------------------------------------------------------------- results


class PitchTiming(BaseModel):
    word_count: int
    words_per_minute: int
    seconds: float
    within_target_words: bool


class AnalysisResult(BaseModel):
    """Everything produced by one analysis run, plus later user edits."""

    mode: Literal["api", "demo"]
    model: str | None
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat(timespec="seconds"))
    source_filename: str
    source_sha256: str
    unit_label: Literal["slide", "page"]
    company_name: str
    facts: list[Fact]
    elements: list[ElementAssessment]
    total_score: int
    max_score: int = 25
    percentage: float
    obstacle_capability_pairs: list[ObstacleCapability]
    strongest_points: list[CitedPoint]
    priority_fixes: list[str]
    inconsistencies: list[Inconsistency]
    information_gaps: list[str]
    extraction_limitations: list[ExtractionLimitation]
    extraction_warnings: list[ExtractionWarning]
    visual_observations: list[VisualObservation]
    pitch_script: str
    timing: PitchTiming
    validation_warnings: list[str]
    onepager: LLMOnePager
    onepager_edits: dict[str, Literal["user_edited", "auto_shortened"]] = Field(default_factory=dict)
    disclaimer: str = (
        "Narrative quality assessment only; not an assessment of investment merit or "
        "likelihood of funding. Deck citations show where a claim appears; they do not "
        "independently verify it."
    )
