#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
逐文件分析 System Informer 源码中的字符串。

输出：
- tools/translate/codex/analysis_records.json
- tools/translate/codex/file_progress.json
- tools/translate/output/analysis_report.json
"""

from __future__ import annotations

import argparse
import re
import time
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from common import (
    ANALYSIS_REPORT_PATH,
    FILE_PROGRESS_PATH,
    PROJECT_NAME,
    first_matching_exclude_rule,
    first_matching_i18n_rule,
    get_context,
    has_mnemonic,
    iter_source_files,
    load_exclude_rules,
    load_i18n_rules,
    module_from_path,
    normalize_slashes,
    placeholders,
    read_text,
    rel_path,
    save_analysis_records,
    source_line,
    stable_id,
    unescape_c_string,
    write_json,
)


RC_DISPLAY_RULE_IDS = {
    "I18N-RC-CAPTION",
    "I18N-RC-CONTROL-TEXT",
    "I18N-RC-MENUITEM",
    "I18N-RC-POPUP",
    "I18N-RC-STRINGTABLE",
    "I18N-RC-VERSION-FILEDESCRIPTION",
}

C_UI_CALL_PATTERNS = [
    ("I18N-C-MESSAGEBOX", "MessageBox", re.compile(r"\bMessageBox(?:W|A)?\s*\(", re.IGNORECASE)),
    ("I18N-C-TASKDIALOG", "TaskDialog", re.compile(r"\bTaskDialog(?:Indirect)?\s*\(", re.IGNORECASE)),
    ("I18N-C-SETWINDOWTEXT", "SetWindowText", re.compile(r"\b(?:SetWindowText|PhSetWindowText)(?:W|A)?\s*\(", re.IGNORECASE)),
    ("I18N-C-PH-DIALOG", "PhShow*", re.compile(r"\bPhShow(?:Error|Warning|Information|Confirm|Continue|ContinueStatus|Status|Message)(?:2)?\s*\(", re.IGNORECASE)),
    (
        "I18N-C-COLUMN-TEXT",
        "列名/属性页 UI",
        re.compile(
            r"\b(?:PhAddTreeNewColumn(?:Ex2?)?|TreeNew_AddColumn|PhAddListViewColumn|PhAddListViewItem|"
            r"PhSetListViewSubItem|PhListView_AddGroup(?:Item)?|PhAddPropPageLayoutItem|Ph(?:Plugin)?CreateEMenuItem)\s*\(",
            re.IGNORECASE,
        ),
    ),
    (
        "I18N-C-SMBIOS-VIEW-TEXT",
        "SMBIOS 列表文本",
        re.compile(r"\b(?:SIP|ET_SMBIOS_[A-Z0-9_]+|EtAddSMBIOS[A-Za-z0-9_]*)\s*\(", re.IGNORECASE),
    ),
]

C_STRING_RE = re.compile(r"(?:\bL|\bTEXT\s*\(|\b_T\s*\(|\bPH_STRINGREF_INIT\s*\(|\bRTL_CONSTANT_STRING\s*\()?\"(?P<value>(?:\\.|[^\"\\])*)\"")

RC_STRING_RE = re.compile(r'"(?P<value>(?:""|\\.|[^"\\])*)"')


def _normalize_rc_string(raw: str) -> str:
    """还原 RC 字符串内容；RC 用双引号 "" 表示字符串内的一个引号。"""

    return unescape_c_string(raw.replace('""', '"'))


def _line_has_rule(line: str, suffix: str, rule_map: dict[str, Any]) -> tuple[str, re.Match[str]] | tuple[None, None]:
    """判断单行 RC 资源是否命中待汉化规则。"""

    for rule_id in RC_DISPLAY_RULE_IDS:
        rule = rule_map.get(rule_id)
        if not rule or not rule.enabled or not rule.compiled or not rule.matches_file_type(suffix):
            continue

        match = rule.compiled.search(line)
        if match:
            return rule_id, match

    return None, None


def _resource_id_for_rc_line(rule_id: str, match: re.Match[str], line: str) -> str:
    """从 RC 行里尽量提取资源 ID，页面复核时更容易定位。"""

    if rule_id == "I18N-RC-STRINGTABLE":
        return match.group(1)

    if rule_id == "I18N-RC-VERSION-FILEDESCRIPTION":
        return "FileDescription"

    after = line[match.end() :]
    id_match = re.search(r",\s*([A-Z][A-Z0-9_]+)\b", after)
    return id_match.group(1) if id_match else ""


def _make_record(
    *,
    path: Path,
    line_number: int,
    column: int,
    raw_string: str,
    normalized: str,
    source_type: str,
    context_source: str,
    source_line_text: str,
    resource_id: str = "",
    api: str = "",
    status: str,
    reason: str,
    i18n_rule_id: str = "",
    exclude_rule_id: str = "",
) -> dict[str, Any]:
    """生成一条完整字符串记录，保证状态、原因和规则对应关系不缺字段。"""

    relative_path = rel_path(path)
    suffix = path.suffix.lower()

    return {
        "id": stable_id([relative_path, line_number, column, raw_string, source_type, resource_id, api]),
        "project": PROJECT_NAME,
        "file": relative_path,
        "file_type": suffix,
        "module": module_from_path(relative_path),
        "line": line_number,
        "column": column,
        "raw_string": raw_string,
        "source": normalized,
        "normalized": normalized,
        "source_type": source_type,
        "context": context_source,
        "source_line": source_line_text,
        "resource_id": resource_id,
        "api": api,
        "user_visible": "是" if status == "待汉化" else ("否" if status == "已排除" else "待确认"),
        "status": status,
        "i18n_rule_id": i18n_rule_id,
        "exclude_rule_id": exclude_rule_id,
        "reason": reason,
        "has_placeholders": bool(placeholders(normalized)),
        "placeholders": placeholders(normalized),
        "has_mnemonic": has_mnemonic(normalized),
        "translation": "",
        "note": "",
    }


def _classify_string(
    *,
    value: str,
    suffix: str,
    relative_path: str,
    source_line_text: str,
    i18n_rules: list[Any],
    exclude_rules: list[Any],
    prev_line_text: str = "",
) -> tuple[str, str, str, str]:
    """按排除优先、待汉化其次、待复核兜底的顺序判断字符串状态。

    对于待汉化规则的 source_line_pattern 匹配，如果当前行不命中，
    会用 prev_line_text + source_line_text 拼接做回退匹配，
    以处理跨行函数调用（API 名在上一行、字符串字面量在当前行）。
    排除规则只用当前行匹配，避免上一行无关代码导致误排除。
    """

    exclude_rule = first_matching_exclude_rule(value, suffix, exclude_rules, relative_path, source_line_text)

    if exclude_rule:
        return "已排除", exclude_rule.reason, "", exclude_rule.id

    # 先用当前行尝试匹配待汉化规则
    i18n_rule = first_matching_i18n_rule(value, suffix, i18n_rules, relative_path, source_line_text)

    # 回退：用 前一行+当前行 拼接再试一次（仅在有前一行且当前行未命中时）
    if not i18n_rule and prev_line_text:
        combined_source_line = prev_line_text + "\n" + source_line_text
        i18n_rule = first_matching_i18n_rule(value, suffix, i18n_rules, relative_path, combined_source_line)

    if i18n_rule:
        return "待汉化", i18n_rule.reason, i18n_rule.id, ""

    return "待复核", "未命中明确待汉化或排除规则，需要人工结合上下文确认。", "", ""


def analyze_rc_file(path: Path, i18n_rule_map: dict[str, Any], exclude_rules: list[Any]) -> list[dict[str, Any]]:
    """分析 RC/RC2 文件中的资源字符串。"""

    text = read_text(path)
    lines = text.splitlines()
    suffix = path.suffix.lower()
    relative_path = rel_path(path)
    i18n_rules = list(i18n_rule_map.values())
    records: list[dict[str, Any]] = []

    for line_index, line in enumerate(lines, start=1):
        rule_id, match = _line_has_rule(line, suffix, i18n_rule_map)

        for string_match in RC_STRING_RE.finditer(line):
            raw = string_match.group("value")
            normalized = _normalize_rc_string(raw)
            column = string_match.start("value") + 1

            # 行级 RC 规则只能应用于行内第一个引号对（显示文本）；
            # 后续引号对通常是窗口类名、控件 ID、坐标或样式。
            is_first_quote = bool(match) and string_match.group("value") == match.group(1)

            if rule_id and match and not is_first_quote:
                # 非首引号串直接归为 RC 控件元数据，避免误判为待汉化。
                status = "已排除"
                reason = "RC 控件类名、资源 ID、坐标或样式等元数据，不属于用户可见文本。"
                i18n_rule_id = ""
                exclude_rule_id = "EXCLUDE-RC-NON-DISPLAY-METADATA"
                source_type = "RC 元数据"
                resource_id = ""
            else:
                if rule_id and match:
                    selected_rule = i18n_rule_map[rule_id]
                    # STRINGTABLE 的第一个捕获组是资源 ID，第二个才是文本。
                    if rule_id == "I18N-RC-STRINGTABLE" and string_match.start() < match.start(2):
                        continue

                    source_type = selected_rule.name
                    resource_id = _resource_id_for_rc_line(rule_id, match, line)
                else:
                    source_type = "RC 字符串"
                    resource_id = ""

                # 行级 RC 规则已命中目标字符串：排除规则优先，仍按通用分类器走
                # 排除检查；排除未命中时直接采用 RC 行级规则作为待汉化结论。
                exclude_rule = first_matching_exclude_rule(
                    normalized,
                    suffix,
                    exclude_rules,
                    relative_path,
                    line,
                )
                if exclude_rule:
                    status = "已排除"
                    reason = exclude_rule.reason
                    i18n_rule_id = ""
                    exclude_rule_id = exclude_rule.id
                elif rule_id and match:
                    status = "待汉化"
                    reason = selected_rule.reason
                    i18n_rule_id = selected_rule.id
                    exclude_rule_id = ""
                else:
                    status, reason, i18n_rule_id, exclude_rule_id = _classify_string(
                        value=normalized,
                        suffix=suffix,
                        relative_path=relative_path,
                        source_line_text=line,
                        i18n_rules=i18n_rules,
                        exclude_rules=exclude_rules,
                    )

            records.append(
                _make_record(
                    path=path,
                    line_number=line_index,
                    column=column,
                    raw_string=raw,
                    normalized=normalized,
                    source_type=source_type,
                    context_source=get_context(lines, line_index),
                    source_line_text=source_line(lines, line_index),
                    resource_id=resource_id,
                    api="",
                    status=status,
                    reason=reason,
                    i18n_rule_id=i18n_rule_id,
                    exclude_rule_id=exclude_rule_id,
                )
            )

    return records


def _nearest_c_ui_call(line_prefix: str) -> tuple[str, str, str]:
    """基于同一行字符串前缀推断 C 字符串所在 UI 调用。"""

    last: tuple[int, str, str, str] | None = None

    for rule_id, api, pattern in C_UI_CALL_PATTERNS:
        for match in pattern.finditer(line_prefix):
            current = (match.start(), rule_id, api, match.group(0).strip())
            if last is None or current[0] > last[0]:
                last = current

    if last:
        return last[1], last[2], last[3]

    return "", "", ""


def analyze_c_like_file(path: Path, i18n_rule_map: dict[str, Any], exclude_rules: list[Any]) -> list[dict[str, Any]]:
    """分析 C/H/MC/XML/INI/TXT 等文本文件中的字符串字面量。"""

    text = read_text(path)
    lines = text.splitlines()
    suffix = path.suffix.lower()
    relative_path = rel_path(path)
    i18n_rules = list(i18n_rule_map.values())
    records: list[dict[str, Any]] = []

    for line_number, line_text in enumerate(lines, start=1):
        # 取上一行文本，用于跨行函数调用的 source_line_pattern 回退匹配
        prev_line_text = lines[line_number - 2].rstrip("\r\n") if line_number > 1 else ""

        for match in C_STRING_RE.finditer(line_text):
            raw = match.group("value")
            normalized = unescape_c_string(raw)
            column = match.start("value") + 1
            line_prefix = line_text[: max(0, column - 1)]
            rule_id, api, _api_match_text = _nearest_c_ui_call(line_prefix)

            if rule_id:
                selected_rule = i18n_rule_map[rule_id]
                source_type = selected_rule.name
            else:
                source_type = "C 字符串"

            status, reason, i18n_rule_id, exclude_rule_id = _classify_string(
                value=normalized,
                suffix=suffix,
                relative_path=relative_path,
                source_line_text=line_text,
                i18n_rules=i18n_rules,
                exclude_rules=exclude_rules,
                prev_line_text=prev_line_text,
            )

            records.append(
                _make_record(
                    path=path,
                    line_number=line_number,
                    column=column,
                    raw_string=raw,
                    normalized=normalized,
                    source_type=source_type,
                    context_source=get_context(lines, line_number),
                    source_line_text=line_text,
                    resource_id="",
                    api=api,
                    status=status,
                    reason=reason,
                    i18n_rule_id=i18n_rule_id,
                    exclude_rule_id=exclude_rule_id,
                )
            )

    return records

def build_file_progress(files: list[Path], records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """生成每个文件的分析进度统计。"""

    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)

    for record in records:
        grouped[record["file"]].append(record)

    progress = []

    for path in files:
        relative_path = rel_path(path)
        file_records = grouped.get(relative_path, [])
        counts = Counter(record["status"] for record in file_records)
        uncovered = sum(1 for record in file_records if record["status"] == "待复核")

        progress.append(
            {
                "file": relative_path,
                "file_type": path.suffix.lower(),
                "module": module_from_path(relative_path),
                "analysis_status": "已完成",
                "string_count": len(file_records),
                "i18n_count": counts.get("待汉化", 0),
                "excluded_count": counts.get("已排除", 0),
                "review_count": counts.get("待复核", 0),
                "uncovered_count": uncovered,
            }
        )

    return progress


def build_report(records: list[dict[str, Any]], progress: list[dict[str, Any]]) -> dict[str, Any]:
    """生成总览和分组覆盖率统计。"""

    status_counts = Counter(record["status"] for record in records)
    total = len(records)
    covered = status_counts.get("待汉化", 0) + status_counts.get("已排除", 0)
    i18n_rule_covered = sum(1 for record in records if record.get("i18n_rule_id"))
    exclude_rule_covered = sum(1 for record in records if record.get("exclude_rule_id"))

    by_file_type: dict[str, dict[str, Any]] = {}
    for file_type in sorted({record["file_type"] for record in records}):
        subset = [record for record in records if record["file_type"] == file_type]
        subset_counts = Counter(record["status"] for record in subset)
        subset_total = len(subset)
        subset_covered = subset_counts.get("待汉化", 0) + subset_counts.get("已排除", 0)
        by_file_type[file_type] = {
            "total": subset_total,
            "i18n": subset_counts.get("待汉化", 0),
            "excluded": subset_counts.get("已排除", 0),
            "review": subset_counts.get("待复核", 0),
            "coverage": round(subset_covered / subset_total, 4) if subset_total else 1,
        }

    by_module: dict[str, dict[str, Any]] = {}
    for module in sorted({record["module"] for record in records}):
        subset = [record for record in records if record["module"] == module]
        subset_counts = Counter(record["status"] for record in subset)
        subset_total = len(subset)
        subset_covered = subset_counts.get("待汉化", 0) + subset_counts.get("已排除", 0)
        by_module[module] = {
            "total": subset_total,
            "i18n": subset_counts.get("待汉化", 0),
            "excluded": subset_counts.get("已排除", 0),
            "review": subset_counts.get("待复核", 0),
            "coverage": round(subset_covered / subset_total, 4) if subset_total else 1,
        }

    return {
        "version": 1,
        "project": PROJECT_NAME,
        "summary": {
            "total_files": len(progress),
            "analyzed_files": sum(1 for item in progress if item["analysis_status"] == "已完成"),
            "total_strings": total,
            "i18n_count": status_counts.get("待汉化", 0),
            "excluded_count": status_counts.get("已排除", 0),
            "review_count": status_counts.get("待复核", 0),
            "confirmed_count": covered,
            "uncovered_count": status_counts.get("待复核", 0),
            "i18n_rule_covered": i18n_rule_covered,
            "exclude_rule_covered": exclude_rule_covered,
            "coverage": round(covered / total, 4) if total else 1,
        },
        "by_file_type": by_file_type,
        "by_module": by_module,
    }


def analyze(limit: int = 0, verbose: bool = False) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    """执行完整分析流程。"""

    i18n_rules = load_i18n_rules()
    exclude_rules = load_exclude_rules()
    i18n_rule_map = {rule.id: rule for rule in i18n_rules}
    files = iter_source_files()

    if limit > 0:
        files = files[:limit]

    records: list[dict[str, Any]] = []

    for index, path in enumerate(files, start=1):
        suffix = path.suffix.lower()
        started_at = time.perf_counter()

        if suffix in {".rc", ".rc2"}:
            file_records = analyze_rc_file(path, i18n_rule_map, exclude_rules)
        else:
            file_records = analyze_c_like_file(path, i18n_rule_map, exclude_rules)

        records.extend(file_records)

        if verbose:
            elapsed = time.perf_counter() - started_at
            print(f"[{index}/{len(files)}] {rel_path(path)} 字符串 {len(file_records)} 用时 {elapsed:.3f}s", flush=True)

    progress = build_file_progress(files, records)
    report = build_report(records, progress)
    save_analysis_records(records)
    write_json(FILE_PROGRESS_PATH, {"version": 1, "project": PROJECT_NAME, "files": progress})
    write_json(ANALYSIS_REPORT_PATH, report)
    return records, progress, report


def main() -> None:
    """命令行入口。"""

    parser = argparse.ArgumentParser(description="逐文件分析 System Informer 源码中的待汉化字符串。")
    parser.add_argument("--limit", type=int, default=0, help="只分析前 N 个文件，用于性能定位。")
    parser.add_argument("--verbose", action="store_true", help="输出每个文件的分析耗时。")
    args = parser.parse_args()

    records, progress, report = analyze(limit=args.limit, verbose=args.verbose)
    summary = report["summary"]
    print(f"已分析文件: {summary['analyzed_files']}/{summary['total_files']}")
    print(f"字符串总数: {summary['total_strings']}")
    print(f"待汉化: {summary['i18n_count']}  已排除: {summary['excluded_count']}  待复核: {summary['review_count']}")
    print(f"总覆盖率: {summary['coverage']:.2%}")
    print(f"分析记录: {normalize_slashes('tools/translate/codex/analysis_records.json')}")
    print(f"文件进度: {normalize_slashes('tools/translate/codex/file_progress.json')}")
    print(f"分析报告: {normalize_slashes('tools/translate/output/analysis_report.json')}")


if __name__ == "__main__":
    main()
