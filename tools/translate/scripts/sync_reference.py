#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
从 reference.json 同步译文到 untranslated.json，并将已翻译数据移动到 translated.json。

用法::

    python tools/translate/scripts/sync_reference.py                  # 同步并输出统计
    python tools/translate/scripts/sync_reference.py --dry-run        # 只预览，不写入
    python tools/translate/scripts/sync_reference.py --resolve-conflicts  # 交互式解决冲突
"""

from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from common import (
    OUTPUT_DIR,
    TRANSLATED_PATH,
    UNTRANSLATED_PATH,
    read_json,
    write_json,
)

REFERENCE_PATH = OUTPUT_DIR / "reference.json"


def load_reference_map(path: Path = REFERENCE_PATH) -> dict[str, str]:
    """加载 reference.json，构建 source -> target 映射。相同 source 取第一条。"""
    data = read_json(path, {})
    entries = data.get("entries", [])
    mapping: dict[str, str] = {}
    for entry in entries:
        source = entry.get("source", "")
        translation = entry.get("translation", "")
        if source and translation and source not in mapping:
            mapping[source] = translation
    return mapping


def find_conflicts(path: Path = REFERENCE_PATH) -> dict[str, list[str]]:
    """检测 reference.json 中相同 source 对应不同 target 的冲突。"""
    data = read_json(path, {})
    entries = data.get("entries", [])
    groups: dict[str, set[str]] = defaultdict(set)
    for entry in entries:
        source = entry.get("source", "")
        translation = entry.get("translation", "")
        if source and translation:
            groups[source].add(translation)
    return {src: sorted(targets) for src, targets in groups.items() if len(targets) > 1}


def sync_reference(
    dry_run: bool = False,
    resolve_conflicts: bool = False,
    reference_path: Path = REFERENCE_PATH,
) -> dict[str, Any]:
    """执行同步，返回统计报告。"""
    if not reference_path.exists():
        raise FileNotFoundError(f"reference.json 不存在: {reference_path}")

    # 加载数据
    ref_map = load_reference_map(reference_path)
    untranslated = read_json(UNTRANSLATED_PATH, [])
    translated = read_json(TRANSLATED_PATH, [])

    conflicts = find_conflicts(reference_path)

    # 如果有冲突且启用了交互式解决
    if conflicts and resolve_conflicts:
        print(f"发现 {len(conflicts)} 组冲突:")
        decisions: dict[str, str] = {}
        for source, targets in conflicts.items():
            print(f"\n  \"{source}\":")
            for i, t in enumerate(targets, 1):
                print(f"    {i}. \"{t}\"")
            while True:
                choice = input(f"  选择译文编号 (1-{len(targets)}) 或输入自定义译文: ").strip()
                if choice.isdigit() and 1 <= int(choice) <= len(targets):
                    decisions[source] = targets[int(choice) - 1]
                    break
                elif choice:
                    decisions[source] = choice
                    break
                else:
                    print("  请输入有效选择。")

        # 应用冲突决策到 reference
        ref_data = read_json(reference_path, {})
        for entry in ref_data.get("entries", []):
            src = entry.get("source", "")
            if src in decisions:
                entry["translation"] = decisions[src]
        if not dry_run:
            write_json(reference_path, ref_data)
            print(f"\n已更新 reference.json: {len(decisions)} 组译文统一")

        # 重新加载映射
        ref_map = load_reference_map(reference_path)

    # 同步翻译
    matched = 0
    moved: list[dict[str, Any]] = []
    remaining: list[dict[str, Any]] = []

    for record in untranslated:
        source = record.get("source", "")
        if source in ref_map and not record.get("translation", ""):
            record["translation"] = ref_map[source]
            record["status"] = "已翻译"
            moved.append(record)
            matched += 1
        elif record.get("translation", ""):
            moved.append(record)
        else:
            remaining.append(record)

    # 更新已翻译列表中的旧译文（如有冲突决策）
    if conflicts:
        updated_in_translated = 0
        for record in translated:
            src = record.get("source", "")
            if src in ref_map:
                old = record.get("translation", "")
                new = ref_map[src]
                if old != new:
                    record["translation"] = new
                    updated_in_translated += 1
        if updated_in_translated and not dry_run:
            print(f"translated.json 中更新译文: {updated_in_translated} 条")

    # 合并到 translated
    translated.extend(moved)

    # 写入文件
    if not dry_run:
        write_json(TRANSLATED_PATH, translated)
        write_json(UNTRANSLATED_PATH, remaining)

    return {
        "reference_entries": len(ref_map),
        "conflicts": len(conflicts),
        "matched": matched,
        "translated_total": len(translated),
        "untranslated_total": len(remaining),
        "dry_run": dry_run,
    }


def main() -> None:
    """命令行入口。"""
    parser = argparse.ArgumentParser(
        description="从 reference.json 同步译文到翻译工作文件。"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="只预览统计，不写入文件。",
    )
    parser.add_argument(
        "--resolve-conflicts",
        action="store_true",
        help="交互式解决相同 source 的不同译文冲突。",
    )
    parser.add_argument(
        "--reference",
        type=Path,
        default=REFERENCE_PATH,
        help="reference.json 路径，默认 tools/translate/output/reference.json",
    )
    args = parser.parse_args()

    report = sync_reference(
        dry_run=args.dry_run,
        resolve_conflicts=args.resolve_conflicts,
        reference_path=args.reference,
    )

    mode = "[预览] " if report["dry_run"] else ""
    print(f"\n{mode}同步完成:")
    print(f"  reference 条目: {report['reference_entries']}")
    print(f"  冲突组数: {report['conflicts']}")
    print(f"  本次同步: {report['matched']} 条")
    print(f"  已翻译总计: {report['translated_total']} 条")
    print(f"  仍未翻译: {report['untranslated_total']} 条")


if __name__ == "__main__":
    main()
