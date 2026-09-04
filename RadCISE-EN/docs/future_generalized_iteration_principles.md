# Future Generalized Iteration Principles

This document defines how RadCISE should be maintained after the current workflow is frozen. The goal is to improve generalizability without overfitting to any calibration set, model family, institution, organ system, or disease label.

## 1. Principle-level changes only

Future prompt or code changes should be based on general clinical-impact principles, not on isolated case-specific fixes. A failed example should first be abstracted into a broader failure mode before any change is made.

Acceptable pattern:

- "A dependent attribute of an already recognized parent lesion should not become an independent A1 unless it independently changes management, staging, or urgency."

Avoid:

- "This exact lesion type in this exact organ should always be A2."

## 2. Do not hard-code disease labels or test-set findings

Avoid rules that assign a fixed tier solely by a specific disease name, anatomical label, or keyword. The same finding may be A1, A2, A3, or N depending on the exam indication, disease context, competing abnormalities, severity, and management relevance.

For example, do not define fixed tiers for specific words such as nodule, effusion, calcification, fracture, embolism, cyst, fatty change, or lymph node. Instead, define the tier by clinical role in the whole case.

## 3. Preserve case-relative tiering

A1/A2/A3/N must remain relative to the combined reference-candidate case. A mild abnormality may be low impact in one case but central in another if it is the main clinically relevant observation. Conversely, a finding that is usually important may be secondary when a more urgent or management-changing process dominates the case.

## 4. Keep A1 compact

A1 should remain limited to true main-conclusion-level clinical-impact abnormalities. Do not force an A1 concept when no such finding exists. Ordinary negative findings, routine normal screens, minor chronic changes, and low-risk incidental abnormalities should not become A1 simply because they are the most visible available statements.

## 5. Separate tier assignment from match quality

A concept can be clinically important but poorly matched, or low impact but fully matched. Do not lower a tier merely because the candidate report missed it. Do not inflate match quality merely because the tier is high. Tier answers "how important is this concept?" Match quality answers "how well did the candidate capture it?"

## 6. Maintain SRU boundary discipline

Before changing tier rules, inspect whether the SRU/concept boundary is correct. Many scoring errors arise from over-splitting attributes or over-merging different clinical axes. Fix boundary principles before adding new tier rules.

## 7. Guards should prevent systematic errors, not replace clinical judgment

Deterministic guards should be broad safety rails. They may flag or correct generic failure modes, but they should not become a keyword-based disease rule base. Guard rules should be auditable, minimal, and explainable.

## 8. Validate on held-out data

Any future change should be tested on data not used to motivate the change. Recommended validation sets include:

- real reports from radiologists of different seniority;
- model-generated reports from multiple model families;
- different body regions and modalities;
- high-score, medium-score, and low-score cases;
- cases with no A1, with only A2/A3/N, and with multiple competing high-impact abnormalities.

## 9. Track both score and intermediate stability

Do not judge a change by average score alone. Also compare:

- A1/A2/A3/N tier stability;
- match-quality stability;
- guard warning ratio;
- repeated-run score range;
- clinically reviewed false-high and false-low examples.

## 10. Document every future release outside the clean package

The distributable workflow package should contain only the adopted workflow. Development notes, failed experiments, and historical calibration artifacts should be stored separately in a research log or version-control system, not inside the released package.
