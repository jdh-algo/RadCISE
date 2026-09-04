# RadCISE-CN 输入输出格式

## 输入 JSONL

每行一个病例：

```json
{
  "name": "case_id_or_pair_id",
  "Examined_Area": "胸部",
  "Examined_Type": "CT/增强CT/CTPA",
  "reference_findings": "金标准影像所见",
  "generated_findings": "生成报告影像所见",
  "model": "可选：模型名",
  "case_id": "可选：病例 ID"
}
```

必须提供金标准和生成报告文本。可接受的等价字段包括：

- reference_findings / reference_report / ref_findings / ref_report / reference
- generated_findings / generated_report / gen_findings / gen_report / candidate_findings / candidate_report / generated

## 输出

### 01_reference_direct_sru.jsonl / 02_generated_direct_sru.jsonl

每行包含：

- name
- Examined_Area
- Examined_Type
- rewritten_report
- semantic_units

每个 SRU：

- id
- sentence
- core_assertion
- key_attributes
- minor_attributes
- dependent_details
- unit_kind
- merge_rationale

### 03_joint_concept_tier_match.jsonl

每行包含：

- case_summary
- shared_concepts

每个 concept：

- concept_id
- tier: A1/A2/A3/N
- concept_axis
- concept_type: matched/reference_only/generated_only
- ref_ids
- gen_ids
- ref_sentence
- gen_sentence
- clinical_concept
- match_quality
- same_axis_contradiction
- anatomical_relationship
- details_relationship
- parent_concept_id
- boundary_rationale
- tier_rationale
- brief_rationale
- guard_adjustment

### 04_deterministic_guard_audit.jsonl

记录 guard warning 数量、比例和具体原因，用于稳定性和可解释性审计。

### 05_scores.jsonl

包含最终分数和分层得分：

- radcise_score
- raw_score_before_ceiling
- score_ceiling
- tier_scores
- aggregation_weights
- shared_tier_counts
- tier_stats
- scoring_method

## 兼容性说明

RadCISE-CN 的 JSON 字段名和枚举值保持英文，以兼容既有统计和画表脚本。中文化主要发生在 prompt、自由文本医学解释和中文 guard 词表层面。
