#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
根据 Codex 分析结果导出翻译工作文件。

脚本只按照 analysis_records.json 中的状态执行分流，不重新判断字符串是否需要汉化。
"""

from __future__ import annotations

from collections import Counter
from typing import Any

from common import (
    ANALYSIS_REPORT_PATH,
    EXCLUDED_PATH,
    OUTPUT_DIR,
    REVIEW_REQUIRED_PATH,
    TRANSLATED_PATH,
    UNTRANSLATED_PATH,
    load_analysis_records,
    read_json,
    write_json,
)

CERTAIN_I18N_PATH = OUTPUT_DIR / "certain_i18n.json"


def _translation_value(record: dict[str, Any]) -> str:
    """兼容 translation/target 字段，便于人工文件往返。"""
    return str(record.get("translation", record.get("target", "")))


def _export_record(record: dict[str, Any], status: str) -> dict[str, Any]:
    """生成面向人工翻译/复核的精简记录，同时保留回写所需定位字段。"""
    return {
        "id": record["id"],
        "source": record["source"],
        "translation": _translation_value(record),
        "file": record["file"],
        "line": record["line"],
        "column": record["column"],
        "type": record["source_type"],
        "resource_id": record.get("resource_id", ""),
        "api": record.get("api", ""),
        "context": record.get("context", ""),
        "source_line": record.get("source_line", ""),
        "raw_string": record.get("raw_string", record["source"]),
        "file_type": record.get("file_type", ""),
        "rule": record.get("i18n_rule_id") or record.get("exclude_rule_id") or "",
        "reason": record.get("reason", ""),
        "status": status,
        "note": record.get("note", ""),
        "has_placeholders": record.get("has_placeholders", False),
        "placeholders": record.get("placeholders", []),
        "has_mnemonic": record.get("has_mnemonic", False),
    }


def export_translation_files() -> dict[str, Any]:
    """执行导出，返回统计报告。"""

    records = load_analysis_records()
    untranslated = []
    translated = []
    excluded = []
    review_pending = []

    for record in records:
        status = record.get("status")
        translation = _translation_value(record)

        if status == "待汉化" and translation:
            translated.append(_export_record(record, "已翻译"))
        elif status == "待汉化":
            untranslated.append(_export_record(record, "未翻译"))
        elif status == "已排除":
            excluded.append(_export_record(record, "已排除"))
        elif status == "待复核":
            review_pending.append(_export_record(record, "待复核"))

    write_json(UNTRANSLATED_PATH, untranslated)

    # translated.json: 如果人工已维护则不覆盖，分析记录中带译文时才重写
    if translated or not TRANSLATED_PATH.exists():
        write_json(TRANSLATED_PATH, translated)

    write_json(EXCLUDED_PATH, excluded)

    # 待审核 = 待汉化中排除 certain_i18n.json 中已确认的记录
    certain_ids = set()
    certain_sources = set()
    if CERTAIN_I18N_PATH.exists():
        certain_data = read_json(CERTAIN_I18N_PATH, {})
        certain_records = certain_data.get("records", certain_data) if isinstance(certain_data, dict) else certain_data
        if isinstance(certain_records, list):
            for r in certain_records:
                if isinstance(r, dict):
                    rid = r.get("id", "")
                    if rid:
                        certain_ids.add(rid)
                    rsource = r.get("source", "")
                    if rsource:
                        certain_sources.add(rsource)

    review_list = [
        r for r in untranslated
        if r.get("id", "") not in certain_ids and r.get("source", "") not in certain_sources
    ]
    # 合并：未确认的待汉化记录 + 规则全未命中且不在 certain_i18n 中的待复核记录
    review_list.extend(
        r for r in review_pending
        if r.get("id", "") not in certain_ids and r.get("source", "") not in certain_sources
    )
    write_json(REVIEW_REQUIRED_PATH, review_list)

    previous_report = read_json(ANALYSIS_REPORT_PATH, {"summary": {}})
    counts = Counter(record.get("status", "未知") for record in records)
    export_report = {
        "total_records": len(records),
        "untranslated": len(untranslated),
        "translated": len(translated) if translated else len(read_json(TRANSLATED_PATH, [])),
        "review_required": len(review_list),
        "excluded": len(excluded),
        "source_status_counts": dict(counts),
        "analysis_summary": previous_report.get("summary", {}),
        "outputs": {
            "untranslated": str(UNTRANSLATED_PATH.relative_to(OUTPUT_DIR.parent.parent)).replace("\\", "/"),
            "translated": str(TRANSLATED_PATH.relative_to(OUTPUT_DIR.parent.parent)).replace("\\", "/"),
            "review_required": str(REVIEW_REQUIRED_PATH.relative_to(OUTPUT_DIR.parent.parent)).replace("\\", "/"),
            "excluded": str(EXCLUDED_PATH.relative_to(OUTPUT_DIR.parent.parent)).replace("\\", "/"),
        },
    }
    return export_report


def main() -> None:
    """命令行入口。"""
    report = export_translation_files()
    print(f"未翻译: {report['untranslated']}")
    print(f"已翻译: {report['translated']}")
    print(f"待审核: {report['review_required']}")
    print(f"已排除: {report['excluded']}")
    print("输出目录: tools/translate/output")


if __name__ == "__main__":
    main()
