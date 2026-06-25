#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
从待审核文件(review_required.json)中提取指定数量的记录，提取后从原文件中删除。

用法：
  python tools/translate/scripts/filter_pending_review.py --limit 50
  python tools/translate/scripts/filter_pending_review.py -n 100
  python tools/translate/scripts/filter_pending_review.py -n 50 -o my_list.json
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from common import REVIEW_REQUIRED_PATH, OUTPUT_DIR


def filter_pending(limit: int, input_path: Path = REVIEW_REQUIRED_PATH, output_path: Path | None = None) -> dict:
    """从待审核文件中提取指定数量的记录，提取后从原文件中删除。"""

    if not input_path.exists():
        print(f"错误: 输入文件不存在: {input_path}")
        return {"total": 0, "extracted": 0, "remaining": 0, "output": ""}

    records = json.loads(input_path.read_text(encoding="utf-8"))
    total = len(records)

    if limit <= 0 or limit >= total:
        extracted = records
        remaining_records = []
    else:
        extracted = records[:limit]
        remaining_records = records[limit:]

    # 默认输出路径
    if output_path is None:
        output_path = OUTPUT_DIR / f"pending_review.json"

    # 写入提取结果
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(extracted, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    # 从原文件中移除已提取的记录
    input_path.write_text(
        json.dumps(remaining_records, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    return {
        "total": total,
        "extracted": len(extracted),
        "remaining": len(remaining_records),
        "output": str(output_path).replace("\\", "/"),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="从待审核文件中提取指定数量的记录，提取后从原文件中删除。")
    parser.add_argument("-n", "--limit", type=int, default=20, help="提取条数，默认 20")
    parser.add_argument("-i", "--input", type=str, default=str(REVIEW_REQUIRED_PATH), help="输入文件路径")
    parser.add_argument("-o", "--output", type=str, default=None, help="输出文件路径（默认自动生成）")
    args = parser.parse_args()

    input_path = Path(args.input)
    output_path = Path(args.output) if args.output else None

    result = filter_pending(args.limit, input_path, output_path)
    print(f"待审核总数: {result['total']}")
    print(f"本次提取: {result['extracted']}")
    print(f"剩余数量: {result['remaining']}")
    print(f"输出文件: {result['output']}")


if __name__ == "__main__":
    main()
