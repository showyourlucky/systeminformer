#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
System Informer 汉化工具共享能力。

本模块只做确定性的文件扫描、规则匹配、状态导出和翻译安全校验；
复杂语义判断仍由 Codex/人工通过规则与复核结果沉淀，避免脚本擅自扩大翻译范围。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable


PROJECT_NAME = "System Informer"
ROOT = Path(__file__).resolve().parents[3]
TRANSLATE_DIR = ROOT / "tools" / "translate"
CODEX_DIR = TRANSLATE_DIR / "codex"
RULES_DIR = TRANSLATE_DIR / "rules"
OUTPUT_DIR = TRANSLATE_DIR / "output"

ANALYSIS_RECORDS_PATH = CODEX_DIR / "analysis_records.json"
FILE_PROGRESS_PATH = CODEX_DIR / "file_progress.json"
I18N_RULES_PATH = RULES_DIR / "i18n_rules.json"
EXCLUDE_RULES_PATH = RULES_DIR / "exclude_rules.json"
UNTRANSLATED_PATH = OUTPUT_DIR / "untranslated.json"
TRANSLATED_PATH = OUTPUT_DIR / "translated.json"
REVIEW_REQUIRED_PATH = OUTPUT_DIR / "review_required.json"
EXCLUDED_PATH = OUTPUT_DIR / "excluded.json"
ANALYSIS_REPORT_PATH = OUTPUT_DIR / "analysis_report.json"
APPLY_REPORT_PATH = OUTPUT_DIR / "apply_report.json"

TARGET_EXTENSIONS = {
    ".c",
    ".h",
    ".rc",
    ".rc2",
    ".mc",
    ".manifest",
    ".xml",
    ".json",
    ".ini",
    ".txt",
}

PRIORITY_EXTENSIONS = {".rc", ".rc2", ".c", ".h"}

EXCLUDED_DIR_NAMES = {
    ".git",
    ".vs",
    "bin",
    "obj",
    "build",
    "out",
    "debug",
    "release",
    "x64",
    "win32",
    "packages",
    "thirdparty",
    "3rdparty",
    "third-party",
    "external",
    "externals",
    "__pycache__",
    "delete",
}

SOURCE_ROOTS = [
    "SystemInformer",
    "phlib",
    "phnt",
    "plugins",
    "tools",
    "resources",
]

SKIPPED_FILE_NAMES = {
    # 这些文件主要是自动生成数据、SDK 头或事件 GUID 清单，字符串不是用户界面文案。
    "etwguids.txt",
    "kphdyn.c",
    "kphdyn.h",
    "kphdyndata.h",
    "d3dkmthk.h",
    "xclrdata.h",
}

# C/Win32 格式化占位符。该表达式刻意跳过 %% ，避免把转义百分号误当成参数。
PLACEHOLDER_RE = re.compile(
    r"%(?!%)(?:\d+\$)?[-+#0 ]*(?:\*|\d+)?(?:\.(?:\*|\d+))?"
    r"(?:hh|h|ll|l|I64|I32|I|z|t|j|w)?[diuoxXfFeEgGaAcCsSpn]"
)

# 自定义模板占位符，形如 %1%、%2% 等，常见于 RC 资源文件和自定义格式化。
TEMPLATE_PLACEHOLDER_RE = re.compile(r"(?<!%)%(\d+)%(?!%)")

ESCAPE_RE = re.compile(r"\\(?:r\\n|[nrt\\\"]|x[0-9A-Fa-f]+|u[0-9A-Fa-f]{4})")


def ensure_directories() -> None:
    """确保工具运行需要的目录都存在。"""

    for path in (CODEX_DIR, RULES_DIR, OUTPUT_DIR):
        path.mkdir(parents=True, exist_ok=True)


def read_text(path: Path) -> str:
    """按 UTF-8 读取文本；遇到极少数字节异常时保留可读内容，避免整批扫描中断。"""

    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return path.read_text(encoding="utf-8", errors="replace")


def write_json(path: Path, data: Any) -> None:
    """以 UTF-8 无 BOM 写入稳定格式 JSON，便于人工 diff 和页面读取。"""

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def read_json(path: Path, default: Any) -> Any:
    """读取 JSON；文件不存在时返回默认值，方便第一次运行。"""

    if not path.exists():
        return default

    return json.loads(path.read_text(encoding="utf-8"))


def normalize_slashes(path: Path | str) -> str:
    """把 Windows 路径统一为 /，保证 JSON 记录跨脚本稳定匹配。"""

    return str(path).replace("\\", "/")


def rel_path(path: Path) -> str:
    """生成相对仓库根目录的路径，减少不同机器上的绝对路径差异。"""

    return normalize_slashes(path.resolve().relative_to(ROOT))


def module_from_path(relative_path: str) -> str:
    """根据路径给字符串标注来源模块，页面统计会按该字段聚合。"""

    lower = relative_path.lower()

    if lower.startswith("systeminformer/"):
        return "主程序"
    if lower.startswith("plugins/"):
        return "插件"
    if lower.startswith(("phlib/", "phnt/", "sdk/", "kphlib/")):
        return "公共库"
    if lower.startswith("tools/"):
        return "工具"
    if "thirdparty" in lower or "external" in lower:
        return "第三方代码"

    return "未知"


def stable_id(parts: Iterable[Any]) -> str:
    """基于核心字段生成稳定 ID，避免重复运行后页面状态大面积漂移。"""

    raw = "\x1f".join(str(part) for part in parts)
    return "SI-" + hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16].upper()


def line_col_from_offset(text: str, offset: int) -> tuple[int, int]:
    """根据字符偏移计算 1 基行列号。"""

    line = text.count("\n", 0, offset) + 1
    line_start = text.rfind("\n", 0, offset) + 1
    return line, offset - line_start + 1


def get_context(lines: list[str], line_number: int, radius: int = 2) -> str:
    """取目标行前后少量源码，供 Codex/人工判断上下文。"""

    start = max(1, line_number - radius)
    end = min(len(lines), line_number + radius)
    selected = []

    for index in range(start, end + 1):
        selected.append(f"{index}: {lines[index - 1].rstrip()}")

    return "\n".join(selected)


def source_line(lines: list[str], line_number: int) -> str:
    """安全取得单行源码内容。"""

    if 1 <= line_number <= len(lines):
        return lines[line_number - 1].rstrip("\r\n")

    return ""


def unescape_c_string(value: str) -> str:
    """把源码字符串字面量中的常见转义还原为展示文本，保留无法识别的转义。"""

    result: list[str] = []
    index = 0

    while index < len(value):
        char = value[index]

        if char != "\\" or index + 1 >= len(value):
            result.append(char)
            index += 1
            continue

        nxt = value[index + 1]
        mapping = {
            "n": "\n",
            "r": "\r",
            "t": "\t",
            "\\": "\\",
            '"': '"',
            "b": "\b",
            "a": "\a",
            "f": "\f",
            "v": "\v",
            "0": "\0",
        }

        if nxt in mapping:
            result.append(mapping[nxt])
            index += 2
        else:
            result.append("\\" + nxt)
            index += 2

    return "".join(result)


def escape_for_source(value: str, file_type: str = "") -> str:
    """把人工译文转回源码安全字符串内容，不改变外层引号或宏。"""

    # Convert control chars to C escape sequences
    _CTRL_MAP = {
        '\r\n': '\\r\\n',
        '\r': '\\r',
        '\n': '\\n',
        '\t': '\\t',
        '\x08': '\\b',
        '\x07': '\\a',
        '\x0c': '\\f',
        '\x0b': '\\v',
        '\x00': '\\0',
    }
    for _ctrl, _esc in _CTRL_MAP.items():
        value = value.replace(_ctrl, _esc)
    # Escape bare backslashes (those not already part of escape sequences)
    # Known C escape suffixes after backslash
    _ESC_CHARS = set('nrtbafv\\"' + chr(39) + '0xuU')
    result = []
    i = 0
    while i < len(value):
        ch = value[i]
        if ch == '\\' and i + 1 < len(value) and value[i + 1] in _ESC_CHARS:
            # Known escape sequence, keep as-is
            result.append(ch + value[i + 1])
            i += 2
        elif ch == '\\':
            # Bare backslash, double it
            result.append('\\\\')
            i += 1
        else:
            result.append(ch)
            i += 1
    escaped = ''.join(result)
    if file_type in {".rc", ".rc2"}:
        escaped = escaped.replace('"', '""')
    else:
        escaped = escaped.replace('"', '\\"')
    return escaped


def placeholders(value: str) -> list[str]:
    """提取格式化占位符，用于校验译文是否丢参数。"""

    # 先提取 %N% 模板占位符，再从原文中剥离，避免 %1% 中的第二个 % 被 C 正则误匹配为 "% to" 等。
    template_matches = TEMPLATE_PLACEHOLDER_RE.findall(value)
    stripped = TEMPLATE_PLACEHOLDER_RE.sub("", value)
    c_matches = PLACEHOLDER_RE.findall(stripped)
    # 模板占位符返回 "%N%" 格式，与 C 占位符区分，便于人工复核。
    return [f"%{n}%" for n in template_matches] + c_matches


def escapes(value: str) -> list[str]:
    """提取源码文本里的显式转义片段。"""

    return ESCAPE_RE.findall(value)


def has_mnemonic(value: str) -> bool:
    """判断 Windows 菜单/按钮文本是否包含助记键 &。"""

    return bool(re.search(r"(?<!&)&(?!&)", value))


def default_status_payload(status: str, reason: str, rule_id: str | None) -> dict[str, Any]:
    """组装状态字段，保持每条记录都有原因和对应关系。"""

    return {
        "status": status,
        "reason": reason,
        "i18n_rule_id": rule_id if status == "待汉化" else "",
        "exclude_rule_id": rule_id if status == "已排除" else "",
    }


@dataclass(frozen=True)
class LoadedRule:
    """运行时规则对象。"""

    id: str
    name: str
    category: str
    file_types: tuple[str, ...]
    pattern: str
    path_pattern: str
    source_line_pattern: str
    description: str
    reason: str
    enabled: bool
    compiled: re.Pattern[str] | None
    compiled_path: re.Pattern[str] | None
    compiled_source_line: re.Pattern[str] | None

    def matches_file_type(self, suffix: str) -> bool:
        return not self.file_types or suffix in self.file_types


def _load_rules(path: Path, category: str) -> list[LoadedRule]:
    """从 JSON 规则文件加载规则，并预编译排除规则。"""

    payload = read_json(path, {"version": 1, "rules": []})
    rules = []

    for item in payload.get("rules", []):
        enabled = bool(item.get("enabled", True))
        pattern = str(item.get("pattern", ""))
        path_pattern = str(item.get("path_pattern", ""))
        source_line_pattern = str(item.get("source_line_pattern", ""))
        compiled = re.compile(pattern, re.IGNORECASE) if pattern else None
        compiled_path = re.compile(path_pattern, re.IGNORECASE) if path_pattern else None
        compiled_source_line = re.compile(source_line_pattern, re.IGNORECASE) if source_line_pattern else None
        rules.append(
            LoadedRule(
                id=str(item.get("id", "")),
                name=str(item.get("name", "")),
                category=category,
                file_types=tuple(item.get("file_types", [])),
                pattern=pattern,
                path_pattern=path_pattern,
                source_line_pattern=source_line_pattern,
                description=str(item.get("description", "")),
                reason=str(item.get("reason", item.get("description", ""))),
                enabled=enabled,
                compiled=compiled,
                compiled_path=compiled_path,
                compiled_source_line=compiled_source_line,
            )
        )

    return rules


def load_i18n_rules() -> list[LoadedRule]:
    """加载待汉化规则。"""

    return _load_rules(I18N_RULES_PATH, "待汉化规则")


def load_exclude_rules() -> list[LoadedRule]:
    """加载排除规则。"""

    return _load_rules(EXCLUDE_RULES_PATH, "排除规则")


def _rule_matches_context(
    rule: LoadedRule,
    value: str,
    suffix: str,
    relative_path: str,
    source_line_text: str,
) -> bool:
    """判断规则的文本、路径、源码行约束是否全部命中。"""

    if not rule.enabled or not rule.matches_file_type(suffix):
        return False

    # 规则可以同时约束文本、文件路径和源码行；没有任何约束的人工兜底规则不自动命中。
    has_constraint = bool(rule.compiled or rule.compiled_path or rule.compiled_source_line)
    if not has_constraint:
        return False

    if rule.compiled and not rule.compiled.search(value):
        return False

    if rule.compiled_path and not rule.compiled_path.search(relative_path):
        return False

    if rule.compiled_source_line and not rule.compiled_source_line.search(source_line_text):
        return False

    return True


def first_matching_exclude_rule(
    value: str,
    suffix: str,
    rules: list[LoadedRule],
    relative_path: str = "",
    source_line_text: str = "",
) -> LoadedRule | None:
    """按规则顺序查找第一个排除命中，排除优先级高于待汉化。"""

    for rule in rules:
        if not _rule_matches_context(rule, value, suffix, relative_path, source_line_text):
            continue

        return rule

    return None


def first_matching_i18n_rule(
    value: str,
    suffix: str,
    rules: list[LoadedRule],
    relative_path: str = "",
    source_line_text: str = "",
) -> LoadedRule | None:
    """按规则顺序查找第一个待汉化命中，用于沉淀已人工确认的源码上下文。"""

    for rule in rules:
        if not _rule_matches_context(rule, value, suffix, relative_path, source_line_text):
            continue

        return rule

    return None


def should_skip_path(path: Path) -> bool:
    """判断路径是否属于构建产物、第三方或工具输出目录。"""

    lower_parts = [part.lower() for part in path.parts]
    parts = set(lower_parts)
    lower_name = path.name.lower()

    if parts & EXCLUDED_DIR_NAMES:
        return True

    if any(part in EXCLUDED_DIR_NAMES for part in lower_parts):
        return True

    if lower_name in SKIPPED_FILE_NAMES:
        return True

    # 旧 tools/i18n_rules 是遗留实现，当前任务明确要求不受它影响。
    # 本工具目录也不参与自身扫描，避免规则 JSON、页面 HTML 和报告污染源码分析。
    skipped_roots = [
        ROOT / "tools" / "i18n_rules",
        TRANSLATE_DIR,
    ]

    for skipped_root in skipped_roots:
        try:
            path.relative_to(skipped_root)
            return True
        except ValueError:
            continue

    return False


def iter_source_files(root: Path = ROOT) -> list[Path]:
    """收集需要分析的源码文件，优先返回 .rc/.rc2/.c/.h。"""

    files: list[Path] = []

    for source_root in SOURCE_ROOTS:
        base = root / source_root
        if not base.exists():
            continue

        for path in base.rglob("*"):
            if not path.is_file() or should_skip_path(path):
                continue
            if path.suffix.lower() in TARGET_EXTENSIONS:
                files.append(path)

    return sorted(files, key=lambda item: (item.suffix.lower() not in PRIORITY_EXTENSIONS, rel_path(item).lower()))


def validate_translation_entry(entry: dict[str, Any]) -> list[dict[str, str]]:
    """校验单条译文，返回错误/警告列表。"""

    issues: list[dict[str, str]] = []
    source = str(entry.get("source", ""))
    translation = str(entry.get("translation", entry.get("target", "")))
    raw_source = str(entry.get("raw_string", source))
    file_type = str(entry.get("file_type", ""))
    if not file_type:
        _fp = str(entry.get("file", ""))
        if _fp:
            file_type = Path(_fp).suffix.lower()
    raw_translation = escape_for_source(translation, file_type)

    if not translation:
        issues.append({"level": "error", "code": "empty_translation", "message": "译文为空，不能回写。"})

    if placeholders(source) != placeholders(translation):
        issues.append({"level": "error", "code": "placeholder_mismatch", "message": "译文中的格式化占位符与原文不一致。"})

    if escapes(raw_source) != escapes(raw_translation):
        issues.append({"level": "warning", "code": "escape_changed", "message": "译文显式转义字符与原文不一致，请人工复核。"})

    if has_mnemonic(source) and not has_mnemonic(translation):
        issues.append({"level": "warning", "code": "mnemonic_missing", "message": "原文包含 Windows 助记键 &，译文未保留助记键。"})

    return issues


def load_analysis_records(path: Path = ANALYSIS_RECORDS_PATH) -> list[dict[str, Any]]:
    """读取 Codex 分析记录。"""

    payload = read_json(path, {"version": 1, "records": []})
    return list(payload.get("records", []))


def save_analysis_records(records: list[dict[str, Any]], path: Path = ANALYSIS_RECORDS_PATH) -> None:
    """保存 Codex 分析记录。"""

    write_json(
        path,
        {
            "version": 1,
            "project": PROJECT_NAME,
            "description": "Codex 逐文件分析得到的字符串、状态、规则与原因对应关系。",
            "records": records,
        },
    )


def make_arg_parser(description: str) -> argparse.ArgumentParser:
    """创建统一命令行解析器，保持所有脚本帮助信息风格一致。"""

    parser = argparse.ArgumentParser(description=description)
    parser.add_argument("--project-root", default=str(ROOT), help="项目根目录，默认自动识别当前仓库。")
    return parser
