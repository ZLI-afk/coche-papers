# COCHE Paper Tracker → Google Sheets 同步（原型）

一次性把 GitHub 上的 `coche_pubmed.json` 单向同步到 Google Sheets：
- 用 **PMID** 做唯一主键
- **只更新「原始数据列」**，团队手动标注的列永不触碰
- 每周一自动运行（可选）

---

## 原理

```
GitHub Actions 每周提交 coche_pubmed.json（权威源，保持不变）
        │
        ▼
Google Apps Script 定时读取 raw URL
        │  按 PMID 匹配每一行
        ▼
Google Sheets —— 只覆盖「原始列」，保留「标注列」
```

## 目前的字段映射

| Sheet 列 | 来源字段 | 说明 |
|----------|----------|------|
| **Key** | DOI→PMID→标题哈希 | **唯一主键（不要改），见下方说明** |
| PMID | `p.pmid` | 可能为空（gs_only 论文） |
| Title | `p.title` | |
| DOI | `p.doi` | |
| First Published | `pub_year/month/day` | `format_date()` 原样 |
| Journal | `p.journal` | |
| All Authors | `author_list` | 通讯作者标 `*` |
| COCHE Authors | `coche_authors` | |
| InnoHK Status | `source` | 与 Excel 完全一致 |
| ITC Year | `pub_year`（Dec 归次年） | |
| Link | `doi` 或 `pmid` | |
| （空列） | — | **预留的「标注」列，脚本永不写入** |

> **主键说明：** 准确讲不是单纯用 PMID，而是「DOI 优先 → PMID 次之 → 标题哈希兜底」。原因是数据里有 134/464 篇 PMID 为空（主要是 gs_only 论文）、36 篇 DOI 和 PMID 都为空。若硬用 PMID 当主键，这 134 篇会撞到空字符串而互相覆盖。脚本还做了去重合并（见下文）。

---

## 安装步骤（5 分钟）

1. 打开 [sheets.new](https://sheets.new) 新建一个 Google Sheets。
2. 菜单 → **扩展程序 → Apps Script**。
3. 删掉默认内容，把本目录的 `Code.gs` 全文粘贴进去（替换整个文件）。
4. 顶部确认只有两个地方要改（其实默认已填好你的仓库）：
   - `GITHUB_RAW_URL`：默认指向 `ZLI-afk/coche-papers/main/coche_pubmed.json`
   - `RAW_COLUMNS`：如需调整列 / 中文表头，改这里
5. 点 **保存**（Ctrl/Cmd+S），给项目起名如 `COCHE Sync`。
6. 首次运行需授权：在函数下拉选 `syncFromGitHub` → 点 **运行** → 允许权限。
7. （可选）点 `onOpen` 运行一次，或刷新 Sheet 页面，顶部会多出 **「COCHE Sync」** 菜单。

> ⚠️ 首次授权会提示「此应用未经 Google 验证」，点 **高级 → 前往（不安全）→ 允许**。这是个人脚本的正常提示。

---

## 定时自动运行

- **方式 A（推荐）**：Apps Script 里运行 `installWeeklyTrigger` 一次，之后每周一 10:00 自动同步。
- **方式 B**：Apps Script 编辑器左侧 → 时钟图标 → 添加触发器 → `syncFromGitHub` → 时间驱动 → 每周。

## 主键：为什么不是单纯 PMID

数据里有几个实际问题，脚本已内置处理：

1. **134/464 篇 PMID 为空**（主要是 `gs_only` 论文，Google Scholar 抓取未匹配 PubMed）。
2. **36 篇 DOI 和 PMID 都为空**。
3. **1 个 DOI 重复**（`10.1126/sciadv.aee2009`，两条记录其实是同一篇，一条带 PMID+InnoHK、一条带 affiliation 标志）。

脚本策略：
- **主键**：`doi:`（规范化）→ `pmid:` → `title:<哈希>`，保证每篇都能落一行，绝不静默丢弃。
- **去重合并**：同 key 的多条记录会合并，`source` 标志取并集、`coche_authors` 去重，优先保留有 PMID 的记录，避免丢失任何标志。

---

## 已完成的对齐（无需你再确认）

脚本中的字段映射、日期格式、ITC 年份、发表作者标记、InnoHK 状态判定，现已**完全对齐 `scripts/generate_outputs.py` 的逻辑**：

- **InnoHK 状态**：`innohk_acknowledgement ∈ source` = Channel B；`affiliation ∈ source` = Channel A；两者兼有 → `⭐ InnoHK`；仅 B → `🏷 InnoHK-only`；仅 A → `COCHE affiliation`；并追加 `innohk_snippet`（同 Excel 的 ` | ` 分隔）。
- **通讯作者标记 `*`**：`author_list[].is_corresponding`；若无显式标记，则按作者数量回退：≤5 人标最后 1 位、≥6 人标最后 2 位。
- **日期**：`format_date()` 原样（年月日 / 年月 / 仅年，不虚构 01-01）。
- **ITC 年份**：Dec 归次年（Dec 1–Nov 30 周期）。
- **主键**：PMID（每篇唯一且非空）。

---

## 附：直接从 Excel 生成对齐用的 CSV（可选）

如果对方团队更想要「CSV 落盘」而不是直接读 JSON，我也可以在 `generate_outputs.py` 里加一个 `generate_csv()`，让 GitHub Actions 每周多产出一个 `COCHE_Papers.csv`（列名与 Excel 完全一致），然后 Apps Script 改读这个 CSV。**要的话告诉我，我一并加上。**
