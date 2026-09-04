# Input and Output Schema

## Input JSONL

Required fields:

- `name`: unique case identifier.
- `reference_findings` or `reference_report`: reference report findings text.
- `generated_findings` or `generated_report`: candidate/generated report findings text.

Recommended optional fields:

- `Examined_Area`: body region or organ system.
- `Examined_Type`: modality/exam type, such as CT, MR, CTPA, CECT.
- `case_id`, `model`, `repeat_id`, or other metadata. These are propagated when supported.

## Output files

### `01_reference_direct_sru.jsonl`
Reference report SRUs.

### `02_generated_direct_sru.jsonl`
Candidate report SRUs.

### `03_joint_concept_tier_match.jsonl`
Shared concept map with tiers and match qualities.

### `04_deterministic_guard_audit.jsonl`
Guard warnings and deterministic adjustments.

### `05_scores.jsonl`
Per-case RadCISE score and tier-wise scoring details.

### `summary_radcise.json`
Run-level summary including mean, median, min, max, and per-case score rows.
