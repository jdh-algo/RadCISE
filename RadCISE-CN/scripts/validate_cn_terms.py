#!/usr/bin/env python3
"""Lightweight Chinese terminology coverage audit for RadCISE-CN.

This script does not call any LLM. It scans a gold-standard CSV and/or JSONL
input pairs to verify that common Chinese radiology expressions are represented
in the RadCISE-CN terminology guards. It is intended as a reproducibility aid,
not as a scoring step.
"""
from __future__ import annotations
import argparse, csv, json, re
from pathlib import Path
from collections import Counter

TERM_GROUPS = {
    "positive_observation": ["见", "可见", "显示", "提示", "考虑", "伴", "形成", "呈"],
    "negative_observation": ["未见", "无", "无明显", "未显示", "未发现", "阴性", "正常", "通畅", "无殊"],
    "ctpa_or_vascular": ["肺动脉", "肺动脉CTA", "靶区血管三维重建", "充盈缺损", "肺栓塞", "血栓", "栓塞"],
    "contrast_enhancement": ["注入造影剂", "增强扫描", "增强后", "强化", "明显强化", "不均匀强化", "环形强化"],
    "not_contrast_trap": ["透亮度增强", "透亮度增高"],
    "lesion_core": ["肿块", "占位", "结节", "磨玻璃", "实性", "空洞", "实变", "毛刺", "分叶"],
    "parenchymal_low_or_chronic": ["少许", "少量", "微量", "轻度", "点状", "条索", "索条", "陈旧", "纤维", "钙化", "退变"],
    "fluid_or_complication": ["胸腔积液", "腹水", "气胸", "肺不张", "膨胀不全", "梗阻", "出血", "骨折", "穿孔", "游离气体"],
    "nodal": ["淋巴结", "肿大淋巴结", "淋巴结肿大", "融合", "坏死"],
}

def iter_texts_from_csv(path: Path):
    with path.open(encoding="utf-8-sig") as f:
        for r in csv.DictReader(f):
            yield r.get("检查 ID", ""), "reference_findings", r.get("影像所见", "") or ""
            yield r.get("检查 ID", ""), "reference_diagnosis", r.get("影像诊断", "") or ""

def iter_texts_from_jsonl(path: Path):
    with path.open(encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            r=json.loads(line)
            name=str(r.get("name") or r.get("case_id") or "")
            for k in ["reference_findings","reference_report","generated_findings","generated_report","gen_findings","gen_report"]:
                if r.get(k):
                    yield name, k, str(r[k])

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--csv", type=Path)
    ap.add_argument("--jsonl", type=Path)
    args=ap.parse_args()
    texts=[]
    if args.csv and args.csv.exists():
        texts.extend(iter_texts_from_csv(args.csv))
    if args.jsonl and args.jsonl.exists():
        texts.extend(iter_texts_from_jsonl(args.jsonl))
    group_counts={g:Counter() for g in TERM_GROUPS}
    examples={g:{} for g in TERM_GROUPS}
    for cid,field,txt in texts:
        for g,terms in TERM_GROUPS.items():
            for term in terms:
                n=txt.count(term)
                if n:
                    group_counts[g][term]+=n
                    examples[g].setdefault(term, f"{cid}/{field}: {txt[:120].replace(chr(10),'|')}")
    print(json.dumps({g:dict(c.most_common()) for g,c in group_counts.items()}, ensure_ascii=False, indent=2))
    print("\nEXAMPLES")
    for g in TERM_GROUPS:
        print(f"\n[{g}]")
        for term, ex in list(examples[g].items())[:8]:
            print(f"- {term}: {ex}")

if __name__ == "__main__":
    main()
