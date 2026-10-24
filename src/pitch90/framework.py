"""Local copy of the narrative framework so analysis never depends on fetching the article.

Source: Andy Raskin, "Your Pitch, 90 Seconds" (The Mission / Firm Narrative, Medium),
https://medium.com/firm-narrative/your-pitch-90-seconds-4b2c473c44b6

The summary below paraphrases the article's five-part structure. The 0-5 scoring
rubric is an application-specific adaptation; it is NOT published in the article.
"""

from __future__ import annotations

from pitch90.models import NarrativeElement

ARTICLE_URL = "https://medium.com/firm-narrative/your-pitch-90-seconds-4b2c473c44b6"

FRAMEWORK_SUMMARY = """\
Andy Raskin argues that a strong startup pitch can be told in about 90 seconds when it
follows a strategic narrative rather than a list of features. Five elements carry it:

1. Customer and problem - Name the specific customer and the force (an obstacle, a
   broken status quo, an adversary) that stops them from reaching a better outcome.
2. Why now - Name the undeniable change in the world (technology, regulation, behaviour,
   economics) that creates urgency: customers who do not adapt will lose out.
3. Desired outcome - Describe the customer's improved future, the "promised land", in
   terms of what they gain rather than what the product does.
4. Obstacles and capabilities - Identify up to three obstacles standing between the
   customer and that outcome, and pair each with the product capability that overcomes it.
5. Evidence - Offer concrete proof the story is real: results, customers, data,
   credible validation that the company can deliver the outcome.
"""

ELEMENT_TITLES: dict[NarrativeElement, str] = {
    NarrativeElement.CUSTOMER_PROBLEM: "Customer and problem",
    NarrativeElement.WHY_NOW: "Why now",
    NarrativeElement.DESIRED_OUTCOME: "Desired outcome",
    NarrativeElement.OBSTACLES_CAPABILITIES: "Obstacles and capabilities",
    NarrativeElement.EVIDENCE: "Evidence",
}

ELEMENT_GUIDANCE: dict[NarrativeElement, str] = {
    NarrativeElement.CUSTOMER_PROBLEM: "Who exactly is the customer, and what force prevents a better outcome?",
    NarrativeElement.WHY_NOW: "What change creates urgency to act now?",
    NarrativeElement.DESIRED_OUTCOME: "What improved future does the customer reach?",
    NarrativeElement.OBSTACLES_CAPABILITIES: "Up to three barriers, each matched with the capability that overcomes it.",
    NarrativeElement.EVIDENCE: "What concrete support backs the company's claims?",
}

RUBRIC = """\
Score each element 0-5 (application-specific rubric, not from the article):
0 - Absent.
1 - Vague assertion.
2 - Partially explained with substantial gaps.
3 - Clear and specific.
4 - Clear, specific, and supported by relevant evidence.
5 - Compelling, concise, and supported by strong, directly relevant evidence.
"""

RUBRIC_LEVELS = {
    0: "Absent",
    1: "Vague assertion",
    2: "Partial, substantial gaps",
    3: "Clear and specific",
    4: "Clear, specific, supported",
    5: "Compelling, strongly supported",
}
