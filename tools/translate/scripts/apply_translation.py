#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
读取 translated.json，将人工译文安全回写到 System Informer 源码。

默认 dry-run，只生成 apply_report.json；传入 --write 才会修改源码。
"""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from common import (
    APPLY_REPORT_PATH,
    ROOT,
    TRANSLATED_PATH,
    escape_for_source,
    read_text,
    validate_translation_entry,
    write_json,
)


def _load_entries(path: Path) -> list[dict[str, Any]]:
    """读取已翻译文件。"""

    if not path.exists():
        return []

    entries = __import__("json").loads(path.read_text(encoding="utf-8"))
    seen = {}
    for entry in entries:
        eid = entry.get("id", "")
        if eid:
            seen[eid] = entry
    return list(seen.values())


def _replace_on_line(line: str, raw_source: str, source: str, translation: str, file_type: str) -> tuple[str, bool, str]:
    """只在目标行替换原始字符串内容，保留引号、L 前缀、TEXT/_T 宏和 RC 语法。"""

    escaped_translation = escape_for_source(translation, file_type)

    quoted_source = f'"{raw_source}"'
    if quoted_source in line:
        return line.replace(quoted_source, f'"{escaped_translation}"', 1), True, "按原始引号内容匹配成功。"

    # 兜底：部分记录 raw_string 可能已经等于 source，仍只替换引号内部文本。
    # RC files: try unescaping quotes
    if file_type in {'.rc', '.rc2'} and raw_source and '""' in raw_source:
        unescaped = raw_source.replace('""', '"')
        quoted_unescaped = f'"{unescaped}"'
        if quoted_unescaped in line:
            return line.replace(quoted_unescaped, f'"{escaped_translation}"', 1), True, "RC unescape match"
    if source and not raw_source:
        quoted_src = f'"{source}"'
        if quoted_src in line:
            return line.replace(quoted_src, f'"{escaped_translation}"', 1), True, "source match"
    return line, False, "目标行未找到原始字符串，跳过以避免误替换。"


def apply_translations(path: Path = TRANSLATED_PATH, write: bool = False) -> dict[str, Any]:
    """执行回写或预览。"""

    entries = _load_entries(path)
    results = []
    file_cache: dict[Path, list[str]] = {}
    changed_files: set[str] = set()

    for entry in entries:
        entry_issues = validate_translation_entry(entry)
        errors = [issue for issue in entry_issues if issue["level"] == "error"]
        relative_file = str(entry.get("file", ""))
        source_path = (ROOT / relative_file).resolve()
        line_number = int(entry.get("line", 0) or 0)
        raw_source = str(entry.get("raw_string", ""))
        source = str(entry.get("source", ""))
        file_type = str(entry.get("file_type", ""))
        if not file_type and relative_file:
            file_type = Path(relative_file).suffix.lower()
        translation = str(entry.get("translation", ""))

        result = {
            "id": entry.get("id", ""),
            "file": relative_file,
            "line": line_number,
            "raw_string": raw_source,
            "source": source,
            "translation": translation,
            "status": "skipped",
            "reason": "",
            "issues": entry_issues,
        }

        if errors:
            result["reason"] = "译文校验存在错误，未回写。"
            results.append(result)
            continue

        if not source_path.exists():
            result["reason"] = "源码文件不存在，无法回写。"
            results.append(result)
            continue

        try:
            source_path.relative_to(ROOT)
        except ValueError:
            result["reason"] = "源码路径不在项目根目录内，已拒绝回写。"
            results.append(result)
            continue

        if source_path not in file_cache:
            text = read_text(source_path)
            if "<<<<<<<" in text or ">>>>>>>" in text:
                result["reason"] = "源码文件包含 Git 冲突标记，已拒绝回写。"
                results.append(result)
                continue
            file_cache[source_path] = text.splitlines(keepends=True)

        lines = file_cache[source_path]
        if line_number < 1 or line_number > len(lines):
            result["reason"] = "记录行号超出当前源码范围，未回写。"
            results.append(result)
            continue

        original_line = lines[line_number - 1]
        new_line, replaced, reason = _replace_on_line(original_line, raw_source, source, translation, file_type)

        if not replaced:
            result["reason"] = reason
            results.append(result)
            continue

        lines[line_number - 1] = new_line
        changed_files.add(str(source_path.relative_to(ROOT)).replace("\\", "/"))
        result["status"] = "applied" if write else "preview"
        result["reason"] = reason if write else "dry-run 预览成功，未修改源码。"
        results.append(result)

    if write:
        for source_path, lines in file_cache.items():
            relative = str(source_path.relative_to(ROOT)).replace("\\", "/")
            if relative in changed_files:
                source_path.write_text("".join(lines), encoding="utf-8")

    applied = sum(1 for item in results if item["status"] in {"applied", "preview"})
    skipped = len(results) - applied
    report = {
        "write": write,
        "total": len(entries),
        "applied_or_preview": applied,
        "skipped": skipped,
        "changed_files": sorted(changed_files),
        "results": results,
    }
    write_json(APPLY_REPORT_PATH, report)
    return report


def main() -> None:
    """命令行入口。"""

    parser = argparse.ArgumentParser(description="将 tools/translate/output/translated.json 中的译文回写源码。")
    parser.add_argument("--write", action="store_true", help="实际写入源码；默认只生成预览报告。")
    parser.add_argument("--translated", default=str(TRANSLATED_PATH), help="已翻译 JSON 文件路径。")
    args = parser.parse_args()

    report = apply_translations(Path(args.translated), write=args.write)
    print(f"模式: {'写入' if args.write else '预览'}")
    print(f"总条目: {report['total']}  成功/预览: {report['applied_or_preview']}  跳过: {report['skipped']}")
    print("报告: tools/translate/output/apply_report.json")


if __name__ == "__main__":
    main()
