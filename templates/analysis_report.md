---
template: analysis_report
version: 1
title: "{{company_name}} – 90-Second Pitch Analysis"
footer: "{{title}}     {{page}}     Compiled on {{date}} by TEN Capital Network"
---
<!--
GENERAL STRUCTURE TEMPLATE - 90-Second Pitch Analysis (internal report)

This file defines the structure, order, headings, fields and line formats of the
internal analysis report the app generates for every deck. It contains no company
data: every value is a {{placeholder}} filled from the analysis at render time.

Syntax (directives are single-line HTML comments, e.g. an HTML comment
containing "section: score_summary")
  # ...                       document title (rendered once)
  ## Heading                  section heading
  section: id                 binds the section to its data
  section: id optional        section is omitted when it has no data
  if-empty: text              text shown when the section's data is empty
  widths: a,b,c               relative column widths for the section's table
  guide: ...                  notes for authors; ignored by the renderer
  {{field}}                   document-level field
  {{item.field}}              repeated once per item of the section's data;
                              consecutive item lines repeat together as a block
  A placeholder holding a list repeats its line once per entry.
  Line styles: "### " sub-heading, "> " note, "- " bullet, "N. " numbered,
  "| ... |" table (header row, separator, then rows), anything else = paragraph.
  **text** renders bold.

Document fields: company_name, source_filename, mode, model, created_at, disclaimer,
  article_url, unit, unit_lower, total_score, max_score, percentage, word_count,
  seconds, words_per_minute, pitch_target_note, pitch_script, date
Footer-only fields: title, page
-->

# {{company_name}} – 90-Second Pitch Analysis

<!-- section: header -->
> Source: {{source_filename}} · Mode: {{mode}} · Model: {{model}} · Generated: {{created_at}}
> INTERNAL – not for distribution to the company or investors. {{disclaimer}}
> Framework: Andy Raskin, "Your Pitch, 90 Seconds" ({{article_url}}). The 0–5 scoring rubric is an application-specific adaptation, not published in the article.

## Narrative score
<!-- section: score_summary -->
<!-- guide: One row per narrative element (customer and problem, why now, desired outcome, obstacles and capabilities, evidence), each scored 0-5: 0 absent, 1 vague assertion, 2 partial with substantial gaps, 3 clear and specific, 4 clear, specific and supported, 5 compelling and strongly supported. Total out of 25 and percentage. -->
<!-- widths: 38,17,30,15 -->
| Element | Score | Level | {{unit}}s |
|---|---|---|---|
| {{item.element_title}} | {{item.score}} / 5 | {{item.rubric_level}} | {{item.source_numbers}} |
| **Total** | **{{total_score}} / {{max_score}} ({{percentage}}%)** | | |
> Narrative scores are separate from extraction confidence; see Extraction limitations.

## Element assessments
<!-- section: element_assessments -->
<!-- guide: For each element: score, supporting slide/page references, concise rationale, missing or weak information, and one specific improvement. -->
### {{item.element_title}} – {{item.score}}/5 ({{item.source_pages}})
{{item.rationale}}
- Missing/weak: {{item.missing_or_weak}}
Improvement: {{item.improvement}}

## Obstacles and capabilities
<!-- section: obstacle_capability_pairs optional -->
<!-- guide: Up to three barriers between the customer and the desired outcome, each paired with the product capability that overcomes it. -->
<!-- widths: 44,44,12 -->
| Obstacle | Capability | {{unit}} |
|---|---|---|
| {{item.obstacle}} | {{item.capability}} | {{item.source_numbers}} |

## Three strongest narrative points
<!-- section: strongest_points -->
<!-- if-empty: None identified. -->
{{item.n}}. {{item.text}} ({{item.source_pages}})

## Three highest-priority fixes
<!-- section: priority_fixes -->
<!-- if-empty: None identified. -->
{{item.n}}. {{item.text}}

## Material numerical inconsistencies
<!-- section: inconsistencies -->
<!-- guide: Contradictory figures are flagged, never resolved by choosing one value. -->
<!-- if-empty: None identified. -->
- {{item.description}} Values: {{item.values}}

## Extraction limitations and their effect
<!-- section: extraction_limitations -->
<!-- guide: Content that could not be fully read (OCR, images, charts, hidden or unreadable slides) and how it may affect the evaluation. -->
<!-- if-empty: No material extraction limitations. -->
- {{item.pages}}: {{item.limitation}} Effect: {{item.effect}}

## Visual interpretation
<!-- section: visual_observations optional -->
- {{unit}} {{item.page}}: {{item.observation}}

## Information gaps
<!-- section: information_gaps -->
<!-- guide: Information the deck does not provide; never filled with invented claims. -->
<!-- if-empty: None identified. -->
- {{item.text}}

## Proposed 90-second pitch
<!-- section: pitch -->
<!-- guide: 180-210 words built only from supported facts, following the five elements. Duration is an estimate at the configured speaking rate. -->
> {{word_count}} words · about {{seconds}} seconds at {{words_per_minute}} words per minute (an estimate; actual delivery varies with pace and pauses){{pitch_target_note}}
{{pitch_script}}

## Evidence register
<!-- section: facts -->
<!-- guide: Every extracted fact with value and unit, period, basis (actual/forecast/target) and commitment (signed customer, pilot, prospect, capital raised/committed/sought), status (stated, calculated, inferred, missing, conflicting), source slide/page or "User-provided", and automated checks. Formulas are shown for calculated values. -->
<!-- widths: 6,15,20,10,13,9,9,18 -->
> Citations show where a claim appears in the deck; they do not independently verify it. User-provided values carry no deck citation.
| ID | Fact | Value | Period | Basis / commitment | Status | Source | Checks |
|---|---|---|---|---|---|---|---|
| {{item.id}} | {{item.label}} | {{item.value_display}} | {{item.period}} | {{item.basis_commitment}} | {{item.status}} | {{item.source}} | {{item.checks}} |

## Automated validation warnings
<!-- section: validation_warnings optional -->
- {{item.text}}

## One-pager fields edited by the user
<!-- section: onepager_edits optional -->
- {{item.field}}: {{item.kind}} (user-provided; not deck-sourced)

## Extraction warnings
<!-- section: extraction_warnings optional -->
- [{{item.severity}}] {{item.message}} ({{item.units}})
