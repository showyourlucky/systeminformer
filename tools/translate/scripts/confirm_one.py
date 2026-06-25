#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
确认待汉化记录。

支持三种模式：
  1. 按记录 ID：python confirm_one.py <record_id> [<record_id> ...]
  2. 按规则名：  python confirm_one.py --rule <rule_id>
  3. 确认全部待审核：python confirm_one.py --pending

同时更新 analysis_records.json 和 certain_i18n.json。
"""

import argparse
from pathlib import Path
from common import ANALYSIS_RECORDS_PATH, OUTPUT_DIR, read_json, write_json

# pending_review.json 路径
PENDING_REVIEW_PATH = OUTPUT_DIR / "pending_review.json"


def mark_confirmed(r: dict) -> None:
    """标记单条记录为人工确认待汉化。"""
    r["confirmed"] = True
    r["reason"] = "人工审核确认该字符串需要汉化。"


def main() -> None:
    parser = argparse.ArgumentParser(description="确认待汉化记录。")
    parser.add_argument("record_id", nargs="*", help="一个或多个记录 ID。")
    parser.add_argument("--rule", help="按规则名批量确认所有待汉化记录。")
    parser.add_argument("--pending", action="store_true", help="确认 pending_review.json 中所有记录。")
    args = parser.parse_args()

    if not args.record_id and not args.rule and not args.pending:
        print("用法: python confirm_one.py <record_id> [<record_id> ...]")
        print("      python confirm_one.py --rule <rule_id>")
        print("      python confirm_one.py --pending")
        return

    # 加载数据
    data = read_json(ANALYSIS_RECORDS_PATH, {"records": []})
    records = data.get("records", [])

    # 确认 pending_review.json 中所有记录
    if args.pending:
        if not PENDING_REVIEW_PATH.exists():
            print(f"文件不存在: {PENDING_REVIEW_PATH}")
            return

        pending = read_json(PENDING_REVIEW_PATH, [])
        if not pending:
            print("pending_review.json 中无记录")
            return

        pending_ids = {r.get("id") for r in pending}
        # 在 analysis_records 中查找匹配记录
        matched = [r for r in records if r.get("id") in pending_ids]

        if not matched:
            print("未在 analysis_records.json 中找到匹配记录")
            return

        for r in matched:
            mark_confirmed(r)

        write_json(ANALYSIS_RECORDS_PATH, data)
        print(f"已标记 {len(matched)} 条记录 (来源: pending_review.json)")

        # 更新 certain_i18n.json
        certain_path = OUTPUT_DIR / "certain_i18n.json"
        certain = read_json(certain_path, {"records": []}) if certain_path.exists() else {"records": []}
        existing_ids = {r.get("id") for r in certain.get("records", [])}

        new_records = [r for r in matched if r.get("id") not in existing_ids]
        if new_records:
            certain["records"] = certain.get("records", []) + new_records
            certain["total"] = len(certain["records"])
            write_json(certain_path, certain)
            print(f"已更新: {certain_path}")
        else:
            print("certain_i18n.json 中已存在这些记录")
        return

    # 按规则名批量确认
    if args.rule:
        targets = [
            r for r in records
            if r.get("status") == "待汉化" and r.get("i18n_rule_id") == args.rule
        ]

        if not targets:
            print(f"未找到规则 {args.rule} 的待汉化记录")
            return

        for r in targets:
            mark_confirmed(r)

        write_json(ANALYSIS_RECORDS_PATH, data)
        print(f"已标记 {len(targets)} 条记录 (规则: {args.rule})")

        # 更新 certain_i18n.json
        certain_path = OUTPUT_DIR / "certain_i18n.json"
        certain = read_json(certain_path, {"records": []}) if certain_path.exists() else {"records": []}
        existing_ids = {r.get("id") for r in certain.get("records", [])}

        new_records = [r for r in targets if r.get("id") not in existing_ids]
        if new_records:
            certain["records"] = certain.get("records", []) + new_records
            certain["total"] = len(certain["records"])
            write_json(certain_path, certain)
            print(f"已更新: {certain_path}")
        else:
            print("certain_i18n.json 中已存在这些记录")
        return

    # 按记录 ID 确认（支持多个）
    target_ids = set(args.record_id)
    matched = []
    for r in records:
        if r.get("id") in target_ids:
            mark_confirmed(r)
            matched.append(r)

    if not matched:
        print(f"未找到记录: {', '.join(args.record_id)}")
        return

    write_json(ANALYSIS_RECORDS_PATH, data)
    print(f"已标记 {len(matched)} 条记录")

    # 更新 certain_i18n.json
    certain_path = OUTPUT_DIR / "certain_i18n.json"
    certain = read_json(certain_path, {"records": []}) if certain_path.exists() else {"records": []}
    existing_ids = {r.get("id") for r in certain.get("records", [])}

    new_records = [r for r in matched if r.get("id") not in existing_ids]
    if new_records:
        certain["records"] = certain.get("records", []) + new_records
        certain["total"] = len(certain["records"])
        write_json(certain_path, certain)
        print(f"已更新: {certain_path}")
    else:
        print("certain_i18n.json 中已存在这些记录")


if __name__ == "__main__":
    main()
