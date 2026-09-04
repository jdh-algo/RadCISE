# RadCISE

RadCISE is an open-source workflow package for evaluating radiology reports by concept-level clinical importance stratification and risk-weighted scoring.

This repository contains two variants:

- `RadCISE-EN/`: English workflow and prompts.
- `RadCISE-CN/`: Chinese workflow and prompts for Chinese radiology reports.

## What is included

- Workflow code
- Prompts
- Input/output schema documentation
- Usage documentation
- Synthetic demo inputs only
- Configuration templates only

## What is intentionally not included

- No evaluation datasets
- No real radiology reports
- No patient identifiers
- No case IDs or accession numbers
- No run logs or intermediate outputs from real experiments
- No API keys or private endpoint tokens

## Quick start

Each subfolder contains its own README and example input file.

```bash
cd RadCISE-CN  # or RadCISE-EN
pip install -r requirements.txt
cp config/radcise_api_config.env.example .env
# Edit .env or export environment variables for your LLM provider.
python scripts/radcise_pipeline.py   --input-jsonl examples/input_pairs_example.jsonl   --run-dir runs/demo   --workers 2
```

The pipeline expects an OpenAI-compatible chat-completions endpoint. Do not commit real API keys or private data.

## Privacy note

The packaged examples are synthetic and are not derived from patient records. Before using RadCISE on private clinical data, ensure that all data handling complies with local privacy, security, and institutional requirements.

---

# RadCISE 中文说明

RadCISE 是一个用于医学影像报告评价的流程包，核心思想是将报告拆解为可核对的医学概念，并按照临床重要性进行分层与风险加权评分。

本开源包包含两个版本：

- `RadCISE-EN/`：英文流程与英文 prompt。
- `RadCISE-CN/`：中文流程与中文 prompt，适用于中文医学影像报告。

## 包内包含

- 流程代码
- Prompt
- 输入/输出 schema 文档
- 使用说明
- 纯虚构 demo 示例
- 配置模板

## 包内不包含

- 不包含评测集
- 不包含真实影像报告
- 不包含患者隐私信息
- 不包含检查号、影像号、住院号、门诊号等真实 ID
- 不包含真实运行日志或中间结果
- 不包含 API key 或内部 token

## 快速使用

请进入对应子目录查看 README，并根据自己的 LLM 服务配置 `.env` 或环境变量。


## License

This project is licensed under the Apache License 2.0. See `LICENSE` for details.
