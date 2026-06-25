# -*- coding: utf-8 -*-
"""
从 analysis_records.json 中提取待汉化内容，并排除 certain_i18n.json 中已确认的记录。

输出会按源码文件分组写入 untranslate_files_without_certain 目录；如果过滤后没有任何
待写入记录，则不会创建输出目录或空 JSON 文件。
"""

import json
import os
from collections import defaultdict
from pathlib import Path

# 路径配置：使用脚本位置反推项目根目录，避免工作目录变化导致读取失败。
PROJECT_ROOT = Path(__file__).resolve().parents[3]
INPUT_FILE = PROJECT_ROOT / "tools" / "translate" / "codex" / "analysis_records.json"
CERTAIN_FILE = PROJECT_ROOT / "tools" / "translate" / "output" / "certain_i18n.json"
OUTPUT_DIR = PROJECT_ROOT / "tools" / "translate" / "codex" / "untranslate_files_without_certain"
UNTRANSLATED_STATUSES = {"待汉化", "未汉化"}


def load_json(filepath):
    """加载 JSON 文件，并在文件不存在时给出中文错误。"""
    if not filepath.exists():
        raise FileNotFoundError(f"找不到 JSON 文件: {filepath}")

    with open(filepath, "r", encoding="utf-8") as f:
        return json.load(f)


def normalize_records(data):
    """兼容数组、records/items 对象以及单键对象结构。"""
    if isinstance(data, list):
        return data

    if not isinstance(data, dict):
        raise ValueError("无法识别的 JSON 结构：根节点既不是数组也不是对象")

    records = data.get("records") or data.get("items")
    if isinstance(records, list):
        return records

    # 兼容旧脚本中的“单个根字段保存记录数组”结构。
    for value in data.values():
        if isinstance(value, list):
            return value

    raise ValueError("无法识别的 JSON 结构：对象中没有记录数组")


def load_certain_ids(filepath):
    """读取已确认待汉化记录 ID，用于后续过滤。"""
    records = normalize_records(load_json(filepath))
    certain_ids = set()

    for record in records:
        if not isinstance(record, dict):
            continue

        record_id = record.get("id") or record.get("ID")
        if record_id:
            certain_ids.add(record_id)

    return certain_ids


def group_by_file(records, certain_ids):
    """按 file 字段分组，仅保留待汉化且未进入 certain_i18n 的记录。"""
    grouped = defaultdict(list)
    skipped_certain_count = 0

    for record in records:
        if not isinstance(record, dict):
            continue

        status = record.get("status") or record.get("Status", "")
        if status not in UNTRANSLATED_STATUSES:
            continue

        record_id = record.get("id") or record.get("ID")
        if record_id in certain_ids:
            skipped_certain_count += 1
            continue

        # 支持多种可能的字段名，保持与原脚本兼容。
        file_path = record.get("file") or record.get("File") or record.get("source_file", "unknown")
        grouped[file_path].append(record)

    return grouped, skipped_certain_count


def save_grouped_files(grouped_data, output_dir):
    """将分组数据写入文件；无数据时不创建目录和空文件。"""
    if not grouped_data:
        print("[信息] 过滤后没有待写入记录，不生成输出文件。")
        return 0

    os.makedirs(output_dir, exist_ok=True)
    written_count = 0

    for file_path, records in grouped_data.items():
        if not records:
            continue

        # 从文件路径生成输出文件名，例如 plugins/.../ExtendedTools.rc -> ExtendedTools.rc.json。
        filename = Path(file_path).name + ".json"
        output_path = output_dir / filename

        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(records, f, ensure_ascii=False, indent=2)

        written_count += 1
        print(f"[完成] 写入: {filename} ({len(records)} 条记录)")

    return written_count


def main():
    try:
        print("[步骤] 读取 analysis_records.json...")
        data = load_json(INPUT_FILE)
        records = normalize_records(data)
        print(f"[统计] 总记录数: {len(records)}")

        print("[步骤] 读取 certain_i18n.json...")
        certain_ids = load_certain_ids(CERTAIN_FILE)
        print(f"[统计] 已确认记录数: {len(certain_ids)}")

        grouped, skipped_certain_count = group_by_file(records, certain_ids)
        pending_count = sum(len(items) for items in grouped.values())
        print(f"[统计] 已过滤确认记录数: {skipped_certain_count}")
        print(f"[统计] 过滤后待汉化文件数: {len(grouped)}")
        print(f"[统计] 过滤后待汉化记录数: {pending_count}")

        print("\n[步骤] 写入文件...")
        written_count = save_grouped_files(grouped, OUTPUT_DIR)

        if written_count:
            print(f"\n[完成] 输出目录: {OUTPUT_DIR}")
        else:
            print("\n[完成] 本次没有生成文件。")
    except (OSError, json.JSONDecodeError, ValueError) as error:
        print(f"[错误] 提取待汉化内容失败: {error}")
        raise


if __name__ == "__main__":
    main()
