# System Informer 汉化规则分析与源码回写工具

面向 [System Informer](https://github.com/winsiderss/systeminformer) 项目的汉化工程工具链。通过 Codex 逐文件分析源码中的字符串，沉淀待汉化 / 排除规则，再由 Python 脚本完成导出、校验和源码回写，形成一套可重复执行的汉化闭环。

## 工作流程概览

```
Codex 逐文件扫描源码
    ↓
沉淀待汉化规则 (i18n_rules.json) 和排除规则 (exclude_rules.json)
    ↓
生成字符串分析记录 (analysis_records.json)
    ↓
Python 按状态导出翻译工作文件
    ↓
人工填写中文译文 (untranslated.json → translated.json)
    ↓
Python 校验 + dry-run 预览 → 确认后 --write 回写源码
    ↓
生成汉化后的 System Informer 源码
```

## 环境要求

- Python 3.10+
- 无需安装第三方依赖，全部使用标准库
- 所有文件均为 UTF-8 无 BOM 编码

## 快速开始

所有命令均从项目根目录执行：

```powershell
# 1. 逐文件扫描源码，生成分析记录和报告
python tools\translate\i18n.py analyze

# 2. 按分析状态导出翻译工作文件
python tools\translate\i18n.py export

# 3. 校验译文（占位符、转义字符、助记键等）
python tools\translate\i18n.py check

# 4. 预览回写（dry-run，不修改源码）
python tools\translate\i18n.py apply

# 5. 确认无误后实际回写源码
python tools\translate\i18n.py apply --write

# 6. 启动本地查看页面
python tools\translate\i18n.py viewer
```

查看页面默认地址：`http://127.0.0.1:8765`

## 命令详解

### `analyze` — 源码分析

逐文件扫描 `SystemInformer/`、`phlib/`、`phnt/`、`plugins/`、`tools/`、`resources/` 目录下的源码，识别其中的字符串并结合规则判断状态。

```powershell
python tools\translate\i18n.py analyze              # 完整分析
python tools\translate\i18n.py analyze --limit 50   # 只分析前 50 个文件
python tools\translate\i18n.py analyze --verbose     # 输出每个文件耗时
```

输出产物：

| 文件 | 说明 |
|------|------|
| `codex/analysis_records.json` | 每条字符串的文件、行列、上下文、状态、规则、原因等完整记录 |
| `codex/file_progress.json` | 每个文件的分析状态和分类计数 |
| `output/analysis_report.json` | 项目整体、按文件类型和按模块的覆盖率统计 |

### `export` — 导出翻译工作文件

根据 `analysis_records.json` 中的状态分流导出，不做任何语义判断。

```powershell
python tools\translate\i18n.py export
```

输出产物：

| 文件 | 说明 |
|------|------|
| `output/untranslated.json` | 待翻译内容，人工需填写 `translation` 字段 |
| `output/translated.json` | 人工已完成译文，用于校验和回写 |
| `output/review_required.json` | 自动规则无法明确判断的待复核内容 |
| `output/excluded.json` | 已确认不参与翻译的内容 |

### `check` — 译文校验

校验 `translated.json` 中的人工译文，检查项包括：

- 空译文不允许回写
- 格式化占位符（`%s`、`%lu`、`%d`、`%p` 等）数量和类型必须与原文一致
- 转义字符（`\r\n`、`\n`、`\t`）不应被删除
- Windows 助记键（`&`）缺失需要提示

```powershell
python tools\translate\i18n.py check
python tools\translate\i18n.py check path\to\custom_translated.json  # 指定文件
```

输出产物：`output/check_report.json`

### `apply` — 源码回写

读取 `translated.json`，将译文回写到对应源码文件的对应行。

```powershell
python tools\translate\i18n.py apply              # dry-run，只生成预览报告
python tools\translate\i18n.py apply --write       # 实际修改源码
python tools\translate\i18n.py apply --translated path\to\custom.json  # 指定文件
```

回写行为：

- 只替换目标行上原始引号内的内容，保留 `L` 前缀、`TEXT()` / `_T()` 宏、RC 语法、资源 ID、缩进、逗号和注释
- 遇到空译文、占位符错误、源码文件缺失、行号失效或原文无法匹配时跳过并记录原因
- 必须先确认 dry-run 报告无误，再使用 `--write` 执行

输出产物：`output/apply_report.json`

### `viewer` — 本地查看页面

启动本地只读 HTTP 服务，用于查看分析概览、文件进度、字符串记录、规则和待复核内容。

```powershell
python tools\translate\i18n.py viewer              # 默认端口 8765
python tools\translate\i18n.py viewer --port 9000  # 自定义端口
```

页面功能：

- **概览**：项目整体覆盖率、各状态字符串计数
- **文件列表**：按文件查看分析状态，支持按类型和状态筛选
- **字符串列表**：查看每条字符串的来源、状态、规则、上下文
- **规则列表**：查看待汉化规则和排除规则，支持按命中数排序
- **待复核**：查看需要人工确认的字符串及上下文源码

## 翻译工作流程

### 步骤一：运行分析和导出

```powershell
python tools\translate\i18n.py analyze
python tools\translate\i18n.py export
```

### 步骤二：复核单个单词和短字符串

从 `output/review_required.json` 中筛选单个单词和短字符串（长度 ≤ 8），这些记录可能不需要汉化：

- **技术缩写/术语**：如 `RVA`、`PID`、`GPU`、`DLL`、`ERROR` 等，通常保留英文
- **格式化片段**：如 `%lu.%lu`、`%lu (%s)`、`0x%p` 等，不应翻译
- **单字符/标点**：如 `#`、`-`、`U` 等，通常无需翻译
- **短文本**：如 `Yes`、`No`、`Low`、`Ok` 等，需人工确认

复核后：

- 确认不需要汉化的记录 → 通过 `viewer` 页面或修改规则标记为 `已排除`
- 确认需要汉化的记录 → 留在 `待汉化` 状态继续翻译
- 不确定的记录 → 保持 `待复核` 状态，后续再分析

### 步骤三：人工翻译

编辑 `output/untranslated.json`，为每条记录填写 `translation` 字段：

```json
{
  "id": "SI-xxxxxx",
  "source": "Properties",
  "translation": "",
  "file": "SystemInformer/mainwnd.c",
  "line": 128
}
```

填写完成的条目保存到 `output/translated.json`。

### 步骤四：校验与回写

```powershell
python tools\translate\i18n.py check                     # 校验译文
python tools\translate\i18n.py apply                      # 预览回写
# 确认 output/apply_report.json 无误后：
python tools\translate\i18n.py apply --write              # 实际回写
```

### 翻译注意事项

- 格式化占位符（`%s`、`%d`、`%lu`、`%Ix`、`%p` 等）必须保留，数量和顺序不能改变
- 转义字符（`\r\n`、`\n`、`\t`、`\\`）必须保留
- 菜单助记键 `&` 需要保留或重新规划，例如 `&File` → `文件(&F)`
- 产品名 `System Informer` 默认不翻译
- 不确定的内容不放入 `translated.json`，应留在 `review_required.json` 中继续复核

## 规则体系

规则分为两类，均保存在 `rules/` 目录下：

### 待汉化规则 (`i18n_rules.json`)

标注源码中需要翻译为中文的用户可见 UI 文本。覆盖场景包括：

- RC 资源文件的对话框标题、控件文本、菜单项、字符串表
- C 源码中的 `MessageBox`、`TaskDialog`、`PhShow*` 用户提示
- 列名、列表项、分组名、属性页标签、状态说明
- 安装器文本、错误提示、搜索提示、确认对话框

### 排除规则 (`exclude_rules.json`)

排除不应翻译的字符串。排除规则优先级高于待汉化规则。覆盖场景包括：

- 资源 ID（`IDS_*`、`IDC_*`、`IDM_*` 等）
- 注册表路径、NT 对象路径、文件路径、命令行参数
- 服务名、驱动名、对象类型名、Windows 常量名
- GUID、URL、HTTP 头、JSON 键名、API 路径
- 格式化占位符、调试日志、断言说明、代码注释
- 第三方 SDK 头文件中的技术文本

### 规则字段结构

每条规则支持以下约束字段：

| 字段 | 说明 |
|------|------|
| `id` | 唯一标识，如 `I18N-RC-CAPTION` 或 `EXCLUDE-RESOURCE-ID` |
| `pattern` | 正则表达式，匹配字符串内容 |
| `path_pattern` | 正则表达式，限制文件路径 |
| `source_line_pattern` | 正则表达式，限制源码行上下文（如特定 API 调用） |
| `file_types` | 文件扩展名列表，如 `[".rc", ".rc2"]` |
| `description` | 规则用途说明 |
| `reason` | 判断原因 |
| `enabled` | 是否启用 |

组合使用 `pattern`、`path_pattern`、`source_line_pattern` 可以精确收窄规则范围，避免误匹配。

## 文件结构

```
tools/translate/
├── i18n.py                         # 统一命令行入口
├── CLAUDE.md                       # 项目记忆（Codex 维护）
├── README.md                       # 本文档
├── 汉化规则分析与源码回写需求.md     # 原始需求说明
├── 待复核文本处理流程.md            # 待复核文本的标准处理闭环
├── .gitignore
│
├── rules/                          # 规则文件
│   ├── i18n_rules.json             # 待汉化规则（402 条）
│   └── exclude_rules.json          # 排除规则（503 条）
│
├── codex/                          # Codex 分析产物
│   ├── analysis_records.json       # 字符串分析记录（全量）
│   └── file_progress.json          # 文件分析进度
│
├── output/                         # 导出产物
│   ├── untranslated.json           # 待翻译（人工填写 translation）
│   ├── translated.json             # 已翻译（用于校验和回写）
│   ├── review_required.json        # 待复核
│   ├── excluded.json               # 已排除
│   ├── analysis_report.json        # 分析覆盖率统计
│   ├── check_report.json           # 译文校验报告
│   └── apply_report.json           # 回写预览 / 执行报告
│
├── scripts/                        # Python 脚本
│   ├── common.py                   # 共享能力（路径、规则加载、校验等）
│   ├── analyze_sources.py          # 源码扫描与规则匹配
│   ├── export_translation_files.py # 按状态导出翻译文件
│   ├── check_translation.py        # 译文校验
│   └── apply_translation.py        # 源码回写
│
└── viewer/                         # 本地查看页面
    ├── server.py                   # HTTP 服务端
    └── index.html                  # 前端页面
```

## 扫描范围

### 扫描目录

`SystemInformer/`、`phlib/`、`phnt/`、`plugins/`、`tools/`、`resources/`

### 扫描文件类型

`.c`、`.h`、`.rc`、`.rc2`、`.mc`、`.manifest`、`.xml`、`.json`、`.ini`、`.txt`

其中 `.rc`、`.rc2`、`.c`、`.h` 为最高优先级。

### 排除目录

`.git/`、`.vs/`、`bin/`、`obj/`、`build/`、`out/`、`Debug/`、`Release/`、`x64/`、`Win32/`、`packages/`、`thirdparty/`、`external/`、`tools/i18n_rules/`、`tools/translate/`

## 识别的字符串类型

| 类型 | 示例 |
|------|------|
| 普通 C 字符串 | `"Properties"` |
| 宽字符字符串 | `L"Properties"` |
| TEXT / _T 宏 | `TEXT("Properties")` / `_T("Properties")` |
| 多段拼接 | `"Unable to open " "the process."` |
| 格式化字符串 | `"Unable to open process %lu."` |
| RC CAPTION | `CAPTION "Process Properties"` |
| RC 控件文本 | `LTEXT "Process:", IDC_STATIC, 7, 7, 50, 8` |
| RC 菜单项 | `MENUITEM "&Properties", IDM_PROPERTIES` |
| RC STRINGTABLE | `IDS_PROCESS_PROPERTIES "Process Properties"` |
| RC VERSIONINFO | `VALUE "FileDescription", "System Informer"` |

## 重要约束

- **排除规则优先**：排除规则优先级高于待汉化规则，避免资源 ID、路径、协议字段等被误译
- **不做语义判断**：Python 脚本只做确定性扫描、规则匹配、导出、校验和回写；复杂语义判断由 Codex / 人工通过规则和复核记录沉淀
- **回写安全**：默认 dry-run，必须确认 `apply_report.json` 后再使用 `--write`；回写遇到任何异常都会跳过并记录原因
- **规则收窄优先**：新增规则时优先使用 `path_pattern` 和 `source_line_pattern` 收窄范围，避免过宽规则误伤
- **编码统一**：所有 `.py`、`.json`、`.md`、`.html` 文件使用 UTF-8 无 BOM

## 后续维护

- 新增或修改规则后，需重新运行 `analyze` 和 `export` 使产物与规则一致
- 处理待复核文本前，先阅读 [待复核文本处理流程.md](待复核文本处理流程.md) 并按其中闭环执行
- 修改回写逻辑后，必须运行语法检查和 dry-run：

```powershell
python -m py_compile tools\translate\scripts\*.py tools\translate\viewer\server.py tools\translate\i18n.py
python tools\translate\i18n.py apply
```

## 相关文档

- [汉化规则分析与源码回写需求.md](汉化规则分析与源码回写需求.md) — 原始需求说明，包含详细的判断标准、规则示例和验收标准
- [待复核文本处理流程.md](待复核文本处理流程.md) — 待复核文本的标准处理闭环，包含源码分析、规则沉淀和验证流程
- `CLAUDE.md` — 项目记忆文件，记录各批次确认结论和维护边界
