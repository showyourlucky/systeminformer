#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
第一阶段本地查看页面服务。

仅监听 127.0.0.1，用于查看分析概览、文件进度、字符串记录、规则和待复核项。
"""

from __future__ import annotations

import argparse
import json
import sys
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse


TRANSLATE_DIR = Path(__file__).resolve().parents[1]
ROOT = TRANSLATE_DIR.parents[1]
VIEWER_DIR = TRANSLATE_DIR / "viewer"
SCRIPTS_DIR = TRANSLATE_DIR / "scripts"
CODEX_DIR = TRANSLATE_DIR / "codex"
RULES_DIR = TRANSLATE_DIR / "rules"
OUTPUT_DIR = TRANSLATE_DIR / "output"
ANALYSIS_RECORDS_PATH = CODEX_DIR / "analysis_records.json"
FILE_PROGRESS_PATH = CODEX_DIR / "file_progress.json"
ANALYSIS_REPORT_PATH = OUTPUT_DIR / "analysis_report.json"
CERTAIN_I18N_PATH = OUTPUT_DIR / "certain_i18n.json"

# 复用分析脚本的规则匹配语义，确保 viewer 查询结果和 analyze 分类结果一致。
sys.path.insert(0, str(SCRIPTS_DIR))
from common import (  # noqa: E402 - 需要先把 scripts 目录加入 sys.path
    LoadedRule,
    _rule_matches_context,
    first_matching_exclude_rule,
    load_analysis_records,
    load_exclude_rules,
    load_i18n_rules,
)


def read_json(path: Path, default: object) -> object:
    """读取 JSON，缺失时返回默认值，方便页面第一次打开。"""

    if not path.exists():
        return default

    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: object) -> None:
    """写入 UTF-8 JSON，供页面复核操作持久化。"""

    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _truthy_query_value(value: str) -> bool:
    """解析 URL 查询参数中的布尔值，默认前端传 1 表示开启。"""

    return value.strip().lower() not in {"0", "false", "no", "off", "否"}


def _rule_to_payload(rule: LoadedRule) -> dict[str, object]:
    """把运行时规则对象转换为可返回给页面的 JSON 数据。"""

    return {
        "id": rule.id,
        "name": rule.name,
        "type": rule.category,
        "file_types": list(rule.file_types),
        "pattern": rule.pattern,
        "path_pattern": rule.path_pattern,
        "source_line_pattern": rule.source_line_pattern,
        "description": rule.description,
        "reason": rule.reason,
        "enabled": rule.enabled,
    }


def _record_matches_rule(record: dict[str, object], rule: LoadedRule) -> bool:
    """按单条规则检查记录，覆盖文本、文件类型、路径和源码行约束。"""

    relative_path = str(record.get("file", ""))
    suffix = str(record.get("file_type", "")) or Path(relative_path).suffix.lower()
    source_line_text = str(record.get("source_line", ""))
    value = str(record.get("source", ""))
    return _rule_matches_context(rule, value, suffix, relative_path, source_line_text)


def _first_exclude_rule_for_record(
    record: dict[str, object],
    exclude_rules: list[LoadedRule],
) -> LoadedRule | None:
    """查找记录会命中的首条排除规则，用于模拟分析流程里的排除优先级。"""

    relative_path = str(record.get("file", ""))
    suffix = str(record.get("file_type", "")) or Path(relative_path).suffix.lower()
    source_line_text = str(record.get("source_line", ""))
    value = str(record.get("source", ""))
    return first_matching_exclude_rule(value, suffix, exclude_rules, relative_path, source_line_text)


def query_rule_matches(rule_id: str, rule_kind: str, use_exclude_rules: bool) -> dict[str, object]:
    """查询指定规则匹配的全部字符串记录。

    待汉化规则默认套用排除规则过滤，便于查看最终会进入汉化流程的文本；
    排除规则自身不再被其它排除规则过滤，避免把用户正在查看的命中结果藏掉。
    """

    i18n_rules = load_i18n_rules()
    exclude_rules = load_exclude_rules()
    rule_groups = {
        "i18n": i18n_rules,
        "exclude": exclude_rules,
    }
    rules = rule_groups.get(rule_kind)

    if rules is None:
        raise ValueError("未知规则类型。")

    rule = next((item for item in rules if item.id == rule_id), None)
    if rule is None:
        raise LookupError("规则不存在。")

    records = load_analysis_records()
    matches: list[dict[str, object]] = []
    skipped_by_exclude = 0

    for record in records:
        if not _record_matches_rule(record, rule):
            continue

        if rule_kind == "i18n" and use_exclude_rules:
            exclude_rule = _first_exclude_rule_for_record(record, exclude_rules)
            if exclude_rule:
                skipped_by_exclude += 1
                continue

        matches.append(record)

    return {
        "rule": _rule_to_payload(rule),
        "records": matches,
        "total": len(matches),
        "skipped_by_exclude": skipped_by_exclude,
        "use_exclude_rules": use_exclude_rules,
    }


def rebuild_progress_and_report(records: list[dict[str, object]]) -> None:
    """人工复核后重算文件进度和概览统计，保持页面数字同步。"""

    file_map: dict[str, list[dict[str, object]]] = {}

    for record in records:
        file_map.setdefault(str(record.get("file", "")), []).append(record)

    files = []
    for file_path, file_records in sorted(file_map.items()):
        status_counts: dict[str, int] = {}
        for record in file_records:
            status = str(record.get("status", ""))
            status_counts[status] = status_counts.get(status, 0) + 1
        files.append(
            {
                "file": file_path,
                "file_type": str(file_records[0].get("file_type", "")) if file_records else "",
                "module": str(file_records[0].get("module", "")) if file_records else "",
                "analysis_status": "已完成",
                "string_count": len(file_records),
                "i18n_count": status_counts.get("待汉化", 0),
                "excluded_count": status_counts.get("已排除", 0),
                "review_count": status_counts.get("待复核", 0),
                "uncovered_count": status_counts.get("待复核", 0),
            }
        )

    status_counts: dict[str, int] = {}
    for record in records:
        status = str(record.get("status", ""))
        status_counts[status] = status_counts.get(status, 0) + 1

    total = len(records)
    covered = status_counts.get("待汉化", 0) + status_counts.get("已排除", 0)
    report = {
        "version": 1,
        "project": "System Informer",
        "summary": {
            "total_files": len(files),
            "analyzed_files": len(files),
            "total_strings": total,
            "i18n_count": status_counts.get("待汉化", 0),
            "excluded_count": status_counts.get("已排除", 0),
            "review_count": status_counts.get("待复核", 0),
            "confirmed_count": covered,
            "uncovered_count": status_counts.get("待复核", 0),
            "i18n_rule_covered": sum(1 for record in records if record.get("i18n_rule_id")),
            "exclude_rule_covered": sum(1 for record in records if record.get("exclude_rule_id")),
            "coverage": round(covered / total, 4) if total else 1,
        },
    }
    write_json(FILE_PROGRESS_PATH, {"version": 1, "project": "System Informer", "files": files})
    write_json(ANALYSIS_REPORT_PATH, report)


def append_certain_i18n_records(targets: list[dict[str, object]]) -> list[str]:
    """把人工确认记录追加到 certain_i18n.json，保持和 confirm_one.py 行为一致。"""

    certain = read_json(CERTAIN_I18N_PATH, {"records": []})
    if not isinstance(certain, dict):
        certain = {"records": []}
    certain_records = certain.get("records", [])
    existing_ids = {str(record.get("id", "")) for record in certain_records}
    appended_ids: list[str] = []

    for target in targets:
        record_id = str(target.get("id", ""))
        if not record_id or record_id in existing_ids:
            continue
        certain_records.append(target)
        existing_ids.add(record_id)
        appended_ids.append(record_id)

    if appended_ids:
        certain["records"] = certain_records
        certain["total"] = len(certain_records)
        write_json(CERTAIN_I18N_PATH, certain)

    return appended_ids


def apply_review_action(target: dict[str, object], action: str, note: str | None) -> None:
    """按人工复核动作更新单条记录，供单选和批量操作复用。"""

    if action == "i18n":
        # 与 scripts/confirm_one.py 对齐：确认动作只标记高置信确认，不重写规则归因。
        target["confirmed"] = True
        target["reason"] = "人工审核确认该字符串需要汉化。"
    elif action == "exclude":
        target["status"] = "已排除"
        target["user_visible"] = "否"
        target["i18n_rule_id"] = ""
        target["exclude_rule_id"] = "EXCLUDE-MANUAL-REVIEW"
        target["reason"] = "人工复核确认该字符串不需要汉化。"
    elif action == "review":
        target["status"] = "待复核"
        target["user_visible"] = "待确认"
        target["i18n_rule_id"] = ""
        target["exclude_rule_id"] = ""
        target["reason"] = "人工暂不处理，保留待复核状态。"
    else:
        raise ValueError("不支持的复核操作。")

    if note is not None:
        target["note"] = note


class TranslateViewerHandler(SimpleHTTPRequestHandler):
    """本地查看页面 HTTP Handler。"""

    def __init__(self, *args: object, **kwargs: object) -> None:
        super().__init__(*args, directory=str(VIEWER_DIR), **kwargs)

    def _json_response(self, payload: object, status: int = 200) -> None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self) -> None:  # noqa: N802 - http.server 约定方法名
        parsed = urlparse(self.path)

        if parsed.path == "/api/overview":
            self._json_response(
                {
                    "analysis_report": read_json(OUTPUT_DIR / "analysis_report.json", {}),
                    "file_progress": read_json(CODEX_DIR / "file_progress.json", {"files": []}),
                }
            )
            return

        if parsed.path == "/api/records":
            self._json_response(read_json(CODEX_DIR / "analysis_records.json", {"records": []}))
            return

        if parsed.path == "/api/rules":
            self._json_response(
                {
                    "i18n_rules": read_json(RULES_DIR / "i18n_rules.json", {"rules": []}),
                    "exclude_rules": read_json(RULES_DIR / "exclude_rules.json", {"rules": []}),
                }
            )
            return

        if parsed.path == "/api/rule-matches":
            query = parse_qs(parsed.query)
            rule_id = query.get("id", [""])[0]
            rule_kind = query.get("kind", [""])[0]
            use_exclude_rules = _truthy_query_value(query.get("use_exclude_rules", ["1"])[0])

            if not rule_id:
                self._json_response({"error": "请选择需要查询的规则。"}, status=400)
                return

            try:
                self._json_response(query_rule_matches(rule_id, rule_kind, use_exclude_rules))
            except ValueError as exc:
                self._json_response({"error": str(exc)}, status=400)
            except LookupError as exc:
                self._json_response({"error": str(exc)}, status=404)
            return

        if parsed.path == "/api/output":
            self._json_response(
                {
                    "untranslated": read_json(OUTPUT_DIR / "untranslated.json", []),
                    "certain_i18n": read_json(OUTPUT_DIR / "certain_i18n.json", {"records": []}),
                    "translated": read_json(OUTPUT_DIR / "translated.json", []),
                    "review_required": read_json(OUTPUT_DIR / "review_required.json", []),
                    "excluded": read_json(OUTPUT_DIR / "excluded.json", []),
                    "check_report": read_json(OUTPUT_DIR / "check_report.json", {}),
                    "apply_report": read_json(OUTPUT_DIR / "apply_report.json", {}),
                }
            )
            return

        if parsed.path == "/api/source":
            query = parse_qs(parsed.query)
            relative_file = query.get("file", [""])[0]
            line = int(query.get("line", ["0"])[0] or 0)
            radius = int(query.get("context", ["4"])[0] or 4)
            source_path = (ROOT / relative_file).resolve()

            try:
                source_path.relative_to(ROOT)
            except ValueError:
                self._json_response({"error": "路径不在项目根目录内。"}, status=400)
                return

            if not source_path.exists():
                self._json_response({"error": "源码文件不存在。"}, status=404)
                return

            lines = source_path.read_text(encoding="utf-8", errors="replace").splitlines()
            start = max(1, line - radius)
            end = min(len(lines), line + radius)
            self._json_response(
                {
                    "file": relative_file,
                    "line": line,
                    "source": [
                        {"line": index, "text": lines[index - 1], "target": index == line}
                        for index in range(start, end + 1)
                    ],
                }
            )
            return

        super().do_GET()

    def do_POST(self) -> None:  # noqa: N802 - http.server 约定方法名
        parsed = urlparse(self.path)

        if parsed.path != "/api/record-status":
            self._json_response({"error": "未知接口。"}, status=404)
            return

        length = int(self.headers.get("Content-Length", "0") or 0)
        payload = json.loads(self.rfile.read(length).decode("utf-8"))
        ids_payload = payload.get("ids")
        if isinstance(ids_payload, list):
            record_ids = [str(item) for item in ids_payload if item is not None and str(item)]
        else:
            record_id = str(payload.get("id", ""))
            record_ids = [record_id] if record_id else []

        action = str(payload.get("action", ""))
        note = str(payload.get("note", "")) if "note" in payload else None
        data = read_json(ANALYSIS_RECORDS_PATH, {"version": 1, "project": "System Informer", "records": []})
        records = data.get("records", []) if isinstance(data, dict) else []
        record_id_set = set(record_ids)
        targets = [record for record in records if record.get("id") in record_id_set]

        if not record_ids:
            self._json_response({"error": "请选择需要复核的记录。"}, status=400)
            return

        if len(targets) != len(record_id_set):
            self._json_response({"error": "记录不存在。"}, status=404)
            return

        try:
            for target in targets:
                apply_review_action(target, action, note)
        except ValueError:
            self._json_response({"error": "不支持的复核操作。"}, status=400)
            return

        write_json(ANALYSIS_RECORDS_PATH, data)
        appended_certain_ids = append_certain_i18n_records(targets) if action == "i18n" else []
        rebuild_progress_and_report(records)
        target_by_id = {str(record.get("id", "")): record for record in targets}
        ordered_targets = [target_by_id[record_id] for record_id in record_ids if record_id in target_by_id]
        self._json_response(
            {
                "ok": True,
                "record": ordered_targets[0],
                "records": ordered_targets,
                "confirmed_ids": record_ids if action == "i18n" else [],
                "appended_certain_ids": appended_certain_ids,
                "updated_count": len(ordered_targets),
            }
        )


def main() -> None:
    """启动本地服务。"""

    parser = argparse.ArgumentParser(description="启动 System Informer 汉化分析查看页面。")
    parser.add_argument("--port", type=int, default=8765, help="监听端口，默认 8765。")
    args = parser.parse_args()

    server = ThreadingHTTPServer(("127.0.0.1", args.port), TranslateViewerHandler)
    print(f"汉化分析查看页面: http://127.0.0.1:{args.port}")
    server.serve_forever()


if __name__ == "__main__":
    main()
