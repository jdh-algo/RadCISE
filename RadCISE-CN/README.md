# RadCISE-CN

RadCISE-CN（Radiology Clinical-Impact Semantic Evaluation，中文医学影像报告临床影响语义评估）是 RadCISE 的中文化分支，用于评估中文金标准影像报告与中文生成/候选报告之间的临床语义一致性。

本分支保留 RadCISE 当前主线的评分框架、JSON schema、字段名和代码接口，重点中文化：

- SRU 拆解 prompt；
- joint concept / tier / match prompt；
- A1/A2/A3/N 的中文医学定义；
- 中文影像术语和否定/阳性表达的确定性 guard；
- 中文使用说明和后续迭代原则。

## 核心思想

RadCISE-CN 不比较表面文字相似度，而是比较报告是否捕捉到真正有临床意义的影像发现。流程会先把报告所见拆成 SRU（Semantic Report Unit，语义报告单元），再把金标准和生成报告放在一起建立共享 concept map，最后根据全病例语境把 concept 分为 A1/A2/A3/N 四层并动态加权评分。

四个层级：

- **A1 — 核心临床影响异常**：漏写、误写或核心矛盾会明显改变主要诊断、分期、急诊处理、治疗策略或重要随访优先级。
- **A2 — 重要次级异常或核心发现关键属性**：会影响严重程度、风险判断、鉴别诊断、分期质量、随访质量或操作计划，但通常不是本病例最高优先级核心轴。
- **A3 — 低临床意义异常**：真实异常或偶发发现，影响报告完整性，但通常不改变主要诊断或处理策略。
- **N — 正常/阴性/技术性描述**：常规正常结构、普通阴性排除和检查质量/技术描述。检查核心相关的关键阴性最多可为 A2，普通模板化阴性仍为 N。

允许一个病例没有 A1。RadCISE-CN 不会强行把“最显眼的轻微异常”提升为 A1。

## 工作流

1. **金标准报告 SRU 拆解**：将 reference findings 拆成中文 SRU。父病灶的大小、边界、密度、强化、局部效应等作为属性保留在同一 SRU 内。
2. **生成报告 SRU 拆解**：用完全相同规则处理 candidate / generated findings。
3. **联合 concept、分层与匹配**：把金标准与生成报告放在一起判断，建立二者共用的一套相对 A1/A2/A3/N 分层，并给出 match_quality。
4. **确定性 guard 审核**：代码层面检查中文和英文术语中的常见异常、否定、轻微/严重程度、局部效应、低风险异常等，减少不稳定分层。
5. **动态加权评分**：按该病例实际存在的层级动态分配权重。A1 存在时 A1 主导；无 A1 时最高存在异常层级成为主要评分对象。

## 输入格式

JSONL，每行至少包含：

```json
{
  "name": "case_id",
  "Examined_Area": "胸部",
  "Examined_Type": "CT",
  "reference_findings": "金标准影像所见文本",
  "generated_findings": "生成/候选报告影像所见文本"
}
```

也兼容 `reference_report`、`generated_report`、`ref_findings`、`gen_findings` 等字段。

## 运行方式

```bash
pip install -r requirements.txt

export RADCISE_API_BASE_URL="https://your-llm-provider.example/v1/chat/completions"
export RADCISE_LLM_API_KEY="YOUR_API_KEY"
export RADCISE_MODEL="YOUR_MODEL_NAME"

python scripts/radcise_pipeline.py \
  --input-jsonl examples/input_pairs_example.jsonl \
  --output-dir runs/example_run \
  --workers 10 \
  --joint-candidates 3
```

输出文件：

- `outputs/01_reference_direct_sru.jsonl`
- `outputs/02_generated_direct_sru.jsonl`
- `outputs/03_joint_concept_tier_match.jsonl`
- `outputs/04_deterministic_guard_audit.jsonl`
- `outputs/05_scores.jsonl`
- `summary_radcise.json`

## 中文化边界

- prompt、医学定义、说明文档使用中文。
- JSON 字段名、枚举值、代码函数名保持英文，便于兼容统计脚本和论文表格。
- 代码 guard 已加入中文医学关键词、否定词、阳性提示词、轻微/严重程度词、CTPA/充盈缺损等相关表达。
- 本分支不针对任何具体病例或模型特调；所有规则均按泛化临床原则编写。
