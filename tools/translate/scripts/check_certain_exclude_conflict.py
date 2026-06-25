#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
检查 certain_i18n.json 中是否存在被 exclude_rules.json 排除规则命中的矛盾记录。

用法：
  python tools/translate/scripts/check_certain_exclude_conflict.py
  python tools/translate/i18n.py conflict
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from common import (
    OUTPUT_DIR,
    load_exclude_rules,
    first_matching_exclude_rule,
    read_json,
    write_json,
)

# certain_i18n.json 的标准路径
CERTAIN_I18N_PATH = OUTPUT_DIR / "certain_i18n.json"
CONFLICT_REPORT_PATH = OUTPUT_DIR / "conflict_report.json"


def check_conflicts() -> dict[str, Any]:
    """检查 certain_i18n.json 与 exclude_rules.json 的矛盾数据。"""

    # 加载 certain_i18n.json
    if not CERTAIN_I18N_PATH.exists():
        print("错误: certain_i18n.json 不存在，请先运行 python tools/translate/i18n.py certain")
        return {"error": "certain_i18n.json 不存在"}

    certain_data = read_json(CERTAIN_I18N_PATH, {})
    certain_records = certain_data.get("records", certain_data) if isinstance(certain_data, dict) else certain_data
    if not isinstance(certain_records, list):
        print("错误: certain_i18n.json 格式异常，期望 records 列表")
        return {"error": "格式异常"}

    # 加载排除规则
    exclude_rules = load_exclude_rules()
    print(f"已加载排除规则: {len(exclude_rules)} 条")
    print(f"已加载 certain 记录: {len(certain_records)} 条")

    # 逐条检查矛盾
    conflicts = []
    for record in certain_records:
        if not isinstance(record, dict):
            continue

        # 跳过已标记为"已排除"的记录（本身就是排除项，不存在矛盾）
        if record.get("status") == "已排除":
            continue

        # 用 source 或 raw_string 作为匹配值
        value = record.get("source", record.get("raw_string", ""))
        if not value:
            continue

        suffix = record.get("file_type", "")
        relative_path = record.get("file", "")
        source_line_text = record.get("source_line", "")

        # 复用 common.py 的排除规则匹配逻辑
        matched_rule = first_matching_exclude_rule(
            value=value,
            suffix=suffix,
            rules=exclude_rules,
            relative_path=relative_path,
            source_line_text=source_line_text,
        )

        if matched_rule:
            conflicts.append({
                "record_id": record.get("id", ""),
                "source": value,
                "file": relative_path,
                "line": record.get("line", 0),
                "column": record.get("column", 0),
                "matched_exclude_rule_id": matched_rule.id,
                "matched_exclude_rule_name": matched_rule.name,
                "matched_exclude_rule_pattern": matched_rule.pattern,
                "matched_exclude_rule_path_pattern": matched_rule.path_pattern,
                "matched_exclude_rule_source_line_pattern": matched_rule.source_line_pattern,
            })

    # 输出报告
    report = {
        "total_certain_records": len(certain_records),
        "total_exclude_rules": len(exclude_rules),
        "conflict_count": len(conflicts),
        "conflicts": conflicts,
    }

    write_json(CONFLICT_REPORT_PATH, report)

    print(f"\n{'='*60}")
    print(f"矛盾记录数: {len(conflicts)} / {len(certain_records)}")
    if conflicts:
        print(f"{'='*60}")
        for c in conflicts:
            print(f"  ID: {c['record_id']}")
            print(f"  原文: {c['source']}")
            print(f"  文件: {c['file']}:{c['line']}:{c['column']}")
            print(f"  命中排除规则: {c['matched_exclude_rule_id']} ({c['matched_exclude_rule_name']})")
            if c['matched_exclude_rule_pattern']:
                print(f"  规则 pattern: {c['matched_exclude_rule_pattern']}")
            if c['matched_exclude_rule_path_pattern']:
                print(f"  规则 path_pattern: {c['matched_exclude_rule_path_pattern']}")
            if c['matched_exclude_rule_source_line_pattern']:
                print(f"  规则 source_line_pattern: {c['matched_exclude_rule_source_line_pattern']}")
            print()
    else:
        print("无矛盾数据，certain_i18n.json 与 exclude_rules.json 一致。")

    print(f"报告已写入: {CONFLICT_REPORT_PATH}")
    return report


def main() -> None:
    """命令行入口。"""
    report = check_conflicts()
    if report.get("error"):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
