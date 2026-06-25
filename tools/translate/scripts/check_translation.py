#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
校验 translated.json 中的人工译文。

校验项：
- 空译文不能回写
- 格式化占位符必须一致
- 转义字符变更需要提示
- Windows 助记键缺失需要提示
"""

from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path
from typing import Any

from common import TRANSLATED_PATH, validate_translation_entry, write_json


def check_translation(path: Path = TRANSLATED_PATH) -> dict[str, Any]:
    """校验翻译文件并生成报告。"""

    if not path.exists():
        report = {
            "ok": True,
            "checked": 0,
            "errors": 0,
            "warnings": 0,
            "issues": [],
            "message": "translated.json 不存在，当前没有可校验译文。",
        }
        write_json(path.parent / "check_report.json", report)
        return report

    entries = __import__("json").loads(path.read_text(encoding="utf-8"))
    issues = []

    for entry in entries:
        for issue in validate_translation_entry(entry):
            issues.append(
                {
                    "id": entry.get("id", ""),
                    "file": entry.get("file", ""),
                    "line": entry.get("line", 0),
                    "source": entry.get("source", ""),
                    "translation": entry.get("translation", ""),
                    **issue,
                }
            )

    counts = Counter(issue["level"] for issue in issues)
    report = {
        "ok": counts.get("error", 0) == 0,
        "checked": len(entries),
        "errors": counts.get("error", 0),
        "warnings": counts.get("warning", 0),
        "issues": issues,
    }
    write_json(path.parent / "check_report.json", report)
    return report


def main() -> None:
    """命令行入口，存在错误时返回非 0。"""

    path = Path(sys.argv[1]) if len(sys.argv) > 1 else TRANSLATED_PATH
    report = check_translation(path)
    print(f"校验条目: {report['checked']}")
    print(f"错误: {report['errors']}  警告: {report['warnings']}")
    print("报告: tools/translate/output/check_report.json")

    if not report["ok"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
