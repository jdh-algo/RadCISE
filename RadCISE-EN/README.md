# RadCISE

RadCISE (Radiology Clinical-Impact Semantic Evaluation) is a framework for evaluating the clinical semantic consistency between a reference radiology report and a generated or candidate report. It focuses on whether clinically meaningful imaging findings are correctly captured, rather than on surface-level text similarity.

This package contains the frozen current RadCISE workflow only. Historical experiments, calibration runs, intermediate development files, and previous-version artifacts are intentionally not included.

## Core idea

RadCISE decomposes the reference and candidate report findings into directly matchable semantic report units (SRUs), builds a shared case-relative concept map, assigns clinical-impact tiers, audits the result with deterministic guards, and computes a dynamic weighted score.

The four tiers are:

- **A1 — core clinical-impact abnormality**: omission, false addition, or core contradiction would materially change the main impression, diagnosis, staging, urgent management, treatment strategy, or follow-up priority.
- **A2 — important secondary abnormality or critical attribute**: clinically meaningful for severity, risk, staging, differential diagnosis, procedure planning, or follow-up quality, but not the highest-priority core axis in the case.
- **A3 — low-clinical-significance abnormality**: real abnormal or incidental finding that improves completeness but usually has limited effect on immediate diagnosis or management.
- **N — normal/negative description**: routine normal findings, ordinary exclusions, and template-like negative statements. Critical negative exclusions may be promoted at most according to their case-specific role.

A report is allowed to have no A1 concept. RadCISE should not force an A1 tier when the case contains no truly core clinical-impact finding.

## Workflow

1. **Reference direct SRU extraction**  
   The reference findings are rewritten into SRUs. Each SRU is a parent finding/process or a clinically meaningful normal/negative assertion. Dependent attributes such as size, margin, enhancement, local edema, local extension, and distribution are kept inside the parent SRU rather than split into separate findings unless they are clinically independent.

2. **Candidate direct SRU extraction**  
   The generated/candidate findings are processed with the same SRU rules.

3. **Joint concept, tier, and match mapping**  
   Reference and candidate SRUs are placed into one shared case-relative concept map. Each concept is assigned A1/A2/A3/N, a match type, and a match quality.

4. **Deterministic guard audit**  
   Rule-based guards check common failure modes, such as ordinary negative statements being promoted to A1, dependent attributes being treated as independent core findings, or low-significance findings dominating the score.

5. **Dynamic weighted scoring**  
   The final RadCISE score is computed by tier-wise match quality and dynamic tier weights. A1 dominates only when true A1 concepts exist. If no A1 exists, the score is driven by the highest clinically relevant available tier.

## Input format

Use JSONL. Each row should include at least:

```json
{
  "name": "case_id",
  "Examined_Area": "chest",
  "Examined_Type": "CT",
  "reference_findings": "reference findings text",
  "generated_findings": "candidate findings text"
}
```

Alternative keys `reference_report` and `generated_report` are also accepted by the pipeline.

## Running

Install dependencies:

```bash
pip install -r requirements.txt
```

Set API environment variables:

```bash
export RADCISE_API_BASE_URL="https://your-llm-provider.example/v1/chat/completions"
export RADCISE_LLM_API_KEY="YOUR_API_KEY"
export RADCISE_MODEL="YOUR_MODEL_NAME"
```

Run:

```bash
python scripts/radcise_pipeline.py   --input-jsonl examples/input_pairs_example.jsonl   --output-dir runs/example_run   --workers 10   --joint-candidates 3
```

Main outputs:

- `outputs/01_reference_direct_sru.jsonl`
- `outputs/02_generated_direct_sru.jsonl`
- `outputs/03_joint_concept_tier_match.jsonl`
- `outputs/04_deterministic_guard_audit.jsonl`
- `outputs/05_scores.jsonl`
- `summary_radcise.json`

## Notes

- Temperature is intentionally omitted unless your API infrastructure requires otherwise.
- Do not place real API keys inside the package.
- For large batches, increase `--workers` according to API rate limits and system capacity.
- For stability-critical studies, run repeated evaluations on a representative subset and inspect both score variance and tier/match consistency.
