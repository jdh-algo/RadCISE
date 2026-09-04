# RadCISE Workflow Details

## 1. Direct SRU extraction

The SRU extraction prompt asks the LLM to transform a findings section into semantic report units. An SRU should be independently matchable, but it should not be over-fragmented. A lesion and its dependent attributes should usually remain in one SRU.

Examples of dependent attributes that should usually remain attached to the parent finding:

- size, number, margin, density/signal, enhancement pattern;
- morphology, calcification, necrosis, fat or fluid component;
- local edema, local fat stranding, local inflammatory change;
- local mass effect, local extension, local invasion or local obstruction when dependent on a parent lesion;
- distribution and laterality when describing one coherent process.

Independent clinically meaningful axes may be split, such as nodal disease, distant metastasis, major vascular involvement, clinically significant obstruction, clinically significant fluid/gas, hemorrhage, ischemia, perforation, or acute structural injury.

## 2. Joint concept mapping

RadCISE does not tier the reference and candidate separately. Instead, it reads both reports together and builds one shared concept map. This is important because the importance of a finding is relative to the whole case.

Each concept records:

- reference SRU ids;
- candidate SRU ids;
- concept type: matched, reference_only, generated_only;
- clinical-impact tier: A1, A2, A3, or N;
- match quality: full, substantial, attribute_conflict, limited, core_conflict, or none;
- rationale for concept boundary and tier assignment.

## 3. Match quality

- **full**: same clinical assertion with essentially equivalent clinically relevant attributes.
- **substantial**: same core finding; only minor or acceptable attribute differences.
- **attribute_conflict**: same core finding exists, but important attributes differ materially.
- **limited**: partial overlap only; clinically incomplete capture.
- **core_conflict**: same clinical axis but the core judgment is contradictory or substantially misleading.
- **none**: no corresponding concept.

## 4. Guard audit

The deterministic guard layer is not a disease-specific rule base. It is intended to prevent broad systematic errors, such as:

- ordinary normal/negative assertions being treated as A1;
- low-significance incidental findings dominating the total score;
- dependent attributes being split into standalone core concepts;
- broad same-organ overlap receiving too much credit when the dominant abnormality is actually missed or contradicted.

Warnings are written to `outputs/04_deterministic_guard_audit.jsonl` for transparency.

## 5. Scoring

RadCISE calculates tier-specific scores and then applies dynamic weights. A1 has high weight only when a true A1 concept exists. If a case contains no A1, weights are redistributed toward the highest existing clinically meaningful tier. A3 and N are intentionally low-weight when higher-impact abnormalities exist.
