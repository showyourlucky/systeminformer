#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
导出“十分肯定需要汉化”的文本记录。

本脚本只从已经被规则判定为“待汉化”的记录中，按明确 UI 上下文再做一次保守筛选。
它不会修改规则，也不会把不确定文本强行标记为可翻译。
"""

from __future__ import annotations

import argparse
import re
from collections import Counter
from pathlib import Path
from typing import Any

from common import ANALYSIS_RECORDS_PATH, OUTPUT_DIR, read_json, write_json


OUTPUT_PATH = OUTPUT_DIR / "certain_i18n.json"

# 这些规则/调用点直接对应菜单、按钮、列、分组、属性页、对话框等用户界面。
CERTAIN_RULE_PREFIXES = (
    "I18N-RC-",
    "I18N-C-COLUMN-",
    "I18N-C-MENU-",
    "I18N-C-DIALOG-",
    "I18N-C-TASKDIALOG-",
    "I18N-C-PROPERTY-",
    "I18N-C-LISTVIEW-",
    "I18N-C-TREEVIEW-",
)

CERTAIN_CALL_PATTERNS = (
    r"\bPhShow(?:Error|Warning|Information|ContinueStatus|Status)\b",
    r"\bTaskDialog(?:Indirect)?\b",
    r"\bMessageBox(?:W)?\b",
    r"\bPhCreateEMenuItem\b",
    r"\bPhPluginCreateEMenuItem\b",
    r"\bPhAdd(?:TreeNew|ListView)Column\b",
    r"\bTreeNew_AddColumn\b",
    r"\bPhListView_AddGroup",
    r"\bPhAddPropPageLayoutItem\b",
    r"\bCreatePropertySheetPage\b",
)

# 即使当前状态是待汉化，以下形态也不进入“十分肯定”清单，避免把专名/格式片段写成高置信样本。
UNCERTAIN_SOURCE_PATTERNS = (
    r"^\s*$",
    r"^%[-+#0-9 .*hlIztj]*[A-Za-z]\s*$",
    r"^[A-Z0-9_./:-]{1,12}$",
    r"^0x[0-9A-Fa-f]+$",
    r"^[A-Z][A-Za-z0-9]+(?:\.[A-Za-z0-9]+)+$",
)


def _source_is_uncertain(source: str) -> bool:
    """过滤格式片段、短技术 token 和路径/字段样式文本。"""

    value = source.strip()
    return any(re.search(pattern, value) for pattern in UNCERTAIN_SOURCE_PATTERNS)


def _has_certain_rule(record: dict[str, Any]) -> bool:
    """判断记录是否命中明确 UI 规则。"""

    rule_id = record.get("i18n_rule_id") or record.get("rule") or ""
    return rule_id.startswith(CERTAIN_RULE_PREFIXES)


def _has_certain_call(record: dict[str, Any]) -> bool:
    """判断源码行是否包含明确 UI 调用点。"""

    source_line = record.get("source_line", "")
    return any(re.search(pattern, source_line) for pattern in CERTAIN_CALL_PATTERNS)


def is_certain_i18n(record: dict[str, Any]) -> bool:
    """保守判断一条记录是否可进入"十分肯定需要汉化"清单。

    判定策略：
    1. 规则前缀匹配（如 I18N-RC-、I18N-C-COLUMN- 等）直接判定为确定，
       不经过不确定形态过滤，避免短文本（如 OK、I/O）被误伤。
    2. 调用点匹配（如 PhShowError、PhCreateEMenuItem 等）需要经过
       不确定形态过滤，避免技术 token 和格式片段进入高置信清单。
    """

    if record.get("status") != "待汉化":
        return False

    # 规则前缀匹配直接判定为确定，不经过不确定形态过滤
    if _has_certain_rule(record):
        return True

    # 调用点匹配需要经过不确定形态过滤
    source = record.get("source", "")
    if _source_is_uncertain(source):
        return False

    return _has_certain_call(record)




def build_output(records: list[dict[str, Any]]) -> dict[str, Any]:
    """构建稳定 JSON 输出，便于后续人工复核和 diff。"""

    selected = [record for record in records if is_certain_i18n(record)]
    selected.sort(key=lambda item: (item.get("file", ""), item.get("line", 0), item.get("source", "")))

    rule_counter = Counter(record.get("i18n_rule_id") or record.get("rule") or "" for record in selected)
    file_counter = Counter(record.get("file", "") for record in selected)

    return {
        "version": 1,
        "description": "十分肯定需要汉化的文本记录；仅用于辅助人工翻译优先级，不改变规则判定。",
        "criteria": {
            "required_status": "待汉化",
            "included_rule_prefixes": list(CERTAIN_RULE_PREFIXES),
            "included_call_patterns": list(CERTAIN_CALL_PATTERNS),
            "excluded_source_patterns": list(UNCERTAIN_SOURCE_PATTERNS),
        },
        "total": len(selected),
        "by_rule": [{"rule": rule, "count": count} for rule, count in rule_counter.most_common()],
        "by_file": [{"file": file, "count": count} for file, count in file_counter.most_common()],
        "records": [
            {
                "id": record.get("id"),
                "source": record.get("source"),
                "file": record.get("file"),
                "line": record.get("line"),
                "i18n_rule_id": record.get("i18n_rule_id") or record.get("rule"),
                "reason": record.get("reason", ""),
                "source_line": record.get("source_line", ""),
            }
            for record in selected
        ],
    }


def export_certain_i18n(output_path: Path = OUTPUT_PATH) -> dict[str, Any]:
    """读取分析记录并写出确定待汉化清单。"""

    data = read_json(ANALYSIS_RECORDS_PATH, {"records": []})
    records = data.get("records", [])
    output = build_output(records)
    write_json(output_path, output)
    return output


def main() -> None:
    """命令行入口。"""

    parser = argparse.ArgumentParser(description="导出十分肯定需要汉化的文本记录。")
    parser.add_argument(
        "--output",
        type=Path,
        default=OUTPUT_PATH,
        help="输出路径，默认 tools/translate/output/certain_i18n.json。",
    )
    args = parser.parse_args()

    output = export_certain_i18n(args.output)
    print(f"已导出十分肯定需要汉化文本: {args.output}")
    print(f"记录数: {output['total']}")


if __name__ == "__main__":
    main()
