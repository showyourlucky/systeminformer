#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
System Informer 汉化规则分析工具统一入口。

常用命令：
  python tools/translate/i18n.py analyze
  python tools/translate/i18n.py export
  python tools/translate/i18n.py certain
  python tools/translate/i18n.py sync
  python tools/translate/i18n.py check
  python tools/translate/i18n.py apply
  python tools/translate/i18n.py viewer
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path


TRANSLATE_DIR = Path(__file__).resolve().parent
SCRIPTS_DIR = TRANSLATE_DIR / "scripts"


def _run_script(script_name: str, *args: str) -> int:
    """用当前 Python 解释器运行子脚本，避免 Windows 环境解释器不一致。"""

    script_path = SCRIPTS_DIR / script_name
    command = [sys.executable, str(script_path), *args]
    env = os.environ.copy()
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    return subprocess.call(command, env=env)


def main() -> None:
    """统一命令行入口。"""

    parser = argparse.ArgumentParser(description="System Informer 汉化规则分析与源码回写工具。")
    subparsers = parser.add_subparsers(dest="command", required=True)

    analyze_parser = subparsers.add_parser("analyze", help="逐文件分析源码并生成 Codex 分析记录。")
    analyze_parser.add_argument("--limit", type=int, default=0, help="只分析前 N 个文件，用于性能定位。")
    analyze_parser.add_argument("--verbose", action="store_true", help="输出每个文件耗时。")
    subparsers.add_parser("export", help="按分析状态导出 untranslated/review/excluded/translated 文件。")
    subparsers.add_parser("certain", help="导出十分肯定需要汉化的文本记录。")

    sync_parser = subparsers.add_parser("sync", help="从 reference.json 同步译文到翻译工作文件。")
    sync_parser.add_argument("--dry-run", action="store_true", help="只预览统计，不写入文件。")
    sync_parser.add_argument("--resolve-conflicts", action="store_true", help="交互式解决相同 source 的不同译文冲突。")
    sync_parser.add_argument("--reference", help="可选：指定 reference.json 路径。")

    check_parser = subparsers.add_parser("check", help="校验 translated.json。")
    subparsers.add_parser("conflict", help="检查 certain_i18n.json 与 exclude_rules.json 的矛盾数据。")
    check_parser.add_argument("translated", nargs="?", help="可选：指定 translated.json 路径。")

    apply_parser = subparsers.add_parser("apply", help="预览或回写 translated.json。")
    apply_parser.add_argument("--write", action="store_true", help="实际写入源码；默认只预览。")
    apply_parser.add_argument("--translated", help="可选：指定 translated.json 路径。")

    viewer_parser = subparsers.add_parser("viewer", help="启动本地查看页面。")
    viewer_parser.add_argument("--port", default="8765", help="监听端口，默认 8765。")

    args = parser.parse_args()

    if args.command == "analyze":
        extra = []
        if args.limit:
            extra.extend(["--limit", str(args.limit)])
        if args.verbose:
            extra.append("--verbose")
        raise SystemExit(_run_script("analyze_sources.py", *extra))
    if args.command == "export":
        raise SystemExit(_run_script("export_translation_files.py"))
    if args.command == "certain":
        raise SystemExit(_run_script("extract_certain_i18n.py"))
    if args.command == "sync":
        extra = []
        if args.dry_run:
            extra.append("--dry-run")
        if args.resolve_conflicts:
            extra.append("--resolve-conflicts")
        if args.reference:
            extra.extend(["--reference", args.reference])
        raise SystemExit(_run_script("sync_reference.py", *extra))
    if args.command == "check":
        extra = [args.translated] if args.translated else []
        raise SystemExit(_run_script("check_translation.py", *extra))
    if args.command == "apply":
        extra = []
        if args.write:
            extra.append("--write")
        if args.translated:
            extra.extend(["--translated", args.translated])
        raise SystemExit(_run_script("apply_translation.py", *extra))
    if args.command == "conflict":
        raise SystemExit(_run_script("check_certain_exclude_conflict.py"))
    if args.command == "viewer":
        env = os.environ.copy()
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        raise SystemExit(subprocess.call([sys.executable, str(TRANSLATE_DIR / "viewer" / "server.py"), "--port", args.port], env=env))


if __name__ == "__main__":
    main()

