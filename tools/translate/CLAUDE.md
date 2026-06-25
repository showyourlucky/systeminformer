# tools/translate 目录记忆

## 用途

本目录是 System Informer 汉化规则分析与源码回写流程的当前实现目录。`tools/i18n_rules` 是遗留目录，本任务不读取、不复用、不修改该目录。

## 第一阶段闭环

当前实现遵循 `汉化规则分析与源码回写需求.md` 的第一阶段目标：

1. `scripts/analyze_sources.py` 逐文件扫描源码，生成 `codex/analysis_records.json`、`codex/file_progress.json` 和 `output/analysis_report.json`。
2. `rules/i18n_rules.json` 保存待汉化提取规则，`rules/exclude_rules.json` 保存排除规则。
   - 规则支持按字符串内容 `pattern`、相对路径 `path_pattern`、源码行 `source_line_pattern` 组合约束，便于沉淀文件级数据表和特定源码上下文判断。
3. `scripts/export_translation_files.py` 按 Codex 分析状态分流输出 `output/untranslated.json`、`output/review_required.json`、`output/excluded.json`、`output/translated.json`。
4. `scripts/check_translation.py` 校验人工译文的空值、格式化占位符、转义字符和助记键。
5. `scripts/apply_translation.py` 默认 dry-run 预览回写，传 `--write` 才修改源码，并输出 `output/apply_report.json`。
6. `viewer/server.py` + `viewer/index.html` 提供本地只读查看页面，可查看概览、文件、字符串、规则和待复核内容。
7. `scripts/check_certain_exclude_conflict.py` 检查 `output/certain_i18n.json` 中是否存在被 `rules/exclude_rules.json` 排除规则命中的矛盾记录，输出 `output/conflict_report.json`。

## 统一入口

```powershell
python tools\translate\i18n.py analyze
python tools\translate\i18n.py export
python tools\translate\i18n.py certain
python tools\translate\i18n.py sync
python tools\translate\i18n.py check
python tools\translate\i18n.py conflict
python tools\translate\i18n.py apply
python tools\translate\i18n.py viewer
```

## 关键约束

- 所有 `.py`、`.json`、`.md`、`.html` 文件使用 UTF-8 无 BOM。
- 默认扫描 `SystemInformer`、`phlib`、`phnt`、`plugins`、`tools`、`resources`，但会排除 `tools/i18n_rules`、`tools/translate`、`thirdparty/external`、构建输出目录和低价值生成/SDK 文件（如 `etwguids.txt`、`kphdyn.c`、`d3dkmthk.h`），避免第三方或协议数据污染第一阶段 UI 汉化记录。
- Python 脚本只做确定性扫描、规则匹配、导出、校验和回写；是否待汉化的复杂语义判断由 Codex/人工通过规则、状态和复核记录沉淀。
- 排除规则优先于待汉化规则，避免资源 ID、路径、文件名、注册表路径、NT 对象路径、命令行参数、GUID、URL、产品名等被误译。
- 回写脚本只替换记录行上的原始引号内容，保留 `L` 前缀、`TEXT()` / `_T()` 宏、RC 语法、资源 ID、缩进、逗号和注释。
- 回写脚本遇到空译文、占位符错误、源码文件缺失、路径越界、Git 冲突标记、行号失效或原文无法匹配时会跳过并记录原因。

## 输出文件说明

- `codex/analysis_records.json`：每条字符串的文件、行列、上下文、状态、规则、原因、占位符和助记键信息。
- `codex/file_progress.json`：每个文件的分析状态、字符串数、待汉化数、排除数、待复核数和未覆盖数。
- `output/untranslated.json`：普通待翻译任务，不包含 `output/certain_i18n.json` 中的高置信待汉化记录。
- `output/translated.json`：人工完成译文后用于校验和回写的文件。
- `output/review_required.json`：待审核内容，包含两部分：(1) 匹配了 i18n 规则但未填译文且不在 `certain_i18n.json` 中的记录（状态为"待汉化"）；(2) i18n 规则和排除规则均未命中的记录（状态为"待复核"）。
- `output/excluded.json`：已确认不参与翻译的内容。
- `output/analysis_report.json`：项目整体、按文件类型和按模块的覆盖率统计。
- `output/check_report.json`：译文校验报告。
- `output/apply_report.json`：源码回写预览或执行报告。
- `output/certain_i18n.json`：保守筛出的"十分肯定需要汉化"记录，用户自己维护，不再重复进入 `untranslated.json`。
- `output/reference.json`：外部/AI 翻译参考库，可通过 `python tools\translate\i18n.py sync --dry-run` 预览同步效果。
- `output/conflict_report.json`：`certain_i18n.json` 与 `exclude_rules.json` 的矛盾检查报告，记录同时被标记为"确定汉化"和命中排除规则的条目。
- `待复核文本处理流程.md`：继续处理待复核文本的标准闭环，包含源码分析、规则沉淀、验证、记忆更新和提交流程。
- `codex/extract_untranslated_without_certain.py`：按文件分组导出待汉化记录时，会先读取 `output/certain_i18n.json` 并过滤已存在的记录 ID，输出到 `codex/untranslate_files_without_certain/`；过滤后无数据时不会生成输出目录或空 JSON 文件。
