---
name: feishu-work-planner
description: 飞书长期工作管理台——把「任务描述 + 截止时间 + 紧急程度」结构化后自动写入飞书多维表格（甘特图/日历/看板视图）、飞书日历与飞书任务待办，实现长期任务的规划与跟踪。当用户说「记到飞书」「加个任务/待办」「排进甘特图」「加到日历」「帮我规划这个季度/项目的任务」「同步任务到飞书」「更新任务进度/状态」「看看本周到期/逾期任务」时使用。区别于 feishu-team-platform（从零搭建团队协作平台、扫码拉人、交付物验收），本 skill 面向个人/单人视角的长期工作管理。
agent_created: true
---

# 飞书长期工作管理台

把自然语言任务变成飞书里结构化的一条数据，并按规则分发到三个落点。

## 核心架构：单一真源，多视图呈现

**所有任务都先写进一张多维表格「任务台账」，再按需分发到日历和待办。**
甘特图、日历、看板不是三份数据，而是**同一张表的三个视图**——改一次数据，三处同步，不会出现「甘特图和待办对不上」。

```
                     ┌─ 甘特视图（开始日期→截止日期 时间条）
用户输入 → 结构化 → 任务台账(Base) ─┼─ 日历视图（同字段，按天看交付节点）
  ↓ 规则分发         (唯一真源)     └─ 看板视图（按状态分组）
                     ├─→ 飞书日历日程（P0/P1、有明确时间点、节点类）
                     └─→ 飞书任务待办（需提醒、有执行动作）
```

路由规则与紧急度矩阵见 `references/routing-rules.md`，表/视图/仪表盘蓝图见 `references/board-blueprint.md`。

## 标准工作流

### 步骤 0 — 前置检查（必做，不要跳过）

```bash
export PATH="$PATH:/c/Users/Wyki/.workbuddy/binaries/node/cli-connector-packages"
lark-cli auth status --format json | grep -E '"status"|"tokenStatus"'
```

- `user.status = ready` → 继续。
- `user.status = missing / tokenStatus = expired` → **先告诉用户需要授权**，引导执行 `lark-cli auth login`（脚本会自动检测并中止，不会静默写 bot 身份）。
- 绝大多数写入（个人日历、我的任务、个人 Base）必须用 `--as user`。`--as bot` 只能写应用自己的资源，**不要图省事切 bot**。

首次使用还需确认板块已存在：检查 `config.json` 里是否有 `base_token`。没有就跑 `scripts/init_board.py`（见文末「首次搭建」）。

### 步骤 1 — 结构化

从用户的话里提取：任务名称、所属板块/项目、里程碑、负责人、开始日期、截止日期、紧急度、交付物、备注。
能推断的就推断，推断不出的**默认值 + 标注**，不要连环追问。

```bash
PY="C:/Users/Wyki/.workbuddy/binaries/python/envs/default/Scripts/python.exe"
"$PY" scripts/intake.py --title "完成 BMP390 驱动联调" --deadline "11-06" \
  --priority P0 --project "WindSinger 硬件" --milestone "测试冻结" \
  --owner wyki --tags "驱动,联调" --notes "需配合 H02 的 PCB" --out plan.json
```

批量（多条任务一次录入）用 `--batch tasks.json`（数组，字段同单个任务）。
输出是规范化 JSON：补全 `start_date`、`duration_days`、`reminders`、`routing` 决策与 `parse_warnings`。

### 步骤 2 — 给用户看结构化结果再写（必须）

把 plan.json 用简洁表格呈现（任务/板块/起止/紧急度/落点），**等用户确认**。
`parse_warnings` 非空或 `due_date` 为 null 时，必须先澄清。

### 步骤 3 — 写入

```bash
"$PY" scripts/sync.py --plan plan.json              # dry-run：只打印将执行的命令
"$PY" scripts/sync.py --plan plan.json --apply      # 确认后才真写（必须先跑过 dry-run）
"$PY" scripts/sync.py --plan plan.json --apply --only base   # 只写某一落点
```

脚本默认 **dry-run**，只有 `--apply` 才产生真实写入。日历/任务属于外显动作，写入前用户确认过即可，无需二次确认。

### 步骤 4 — 回报

输出每个任务的：多维表格记录链接、日历日程链接（如创建）、任务链接（如创建），以及被跳过的落点和原因。

## 常用命令速查

```bash
# 查重复（写入前先查，避免同一任务录两遍）
lark-cli base +record-search --base-token <B> --table-id <T> \
  --keyword "BMP390 驱动" --search-field "任务名称" --as user --format json

# 写台账（批量，--json @file 的路径必须是 cwd 相对路径）
lark-cli base +record-batch-create --base-token <B> --table-id <T> \
  --json @records.json --as user

# 建日历日程（带提醒必须用原生命令，+create 没有提醒参数）
lark-cli calendar events create --calendar-id <cal_id> --data @event.json --as user

# 建待办 + 提醒（两步，+create 不接受 reminders）
lark-cli task +create --summary "..." --due "2026-11-06" --as user --format json
lark-cli task +reminder --task-id <guid> --set 1d --as user
```

完整命令细节与参数陷阱见 `references/lark-cli-cookbook.md`。

## 坑位清单（踩过的）

1. **user token 约 1 小时过期**，跨会话常见 `User identity: missing` → `lark-cli auth login`。
2. `--json @file` 路径**必须相对当前工作目录**，绝对路径会失败 → 脚本统一 `chdir` 到临时目录再调用。
3. Base 写入**异步生效**，写后立刻 `+record-list` 读不到，别为验收反复读。
4. 同表写入**必须串行**（并发报 `1254291`），单批 ≤200 条。
5. 甘特/日历视图靠 `+view-set-timebar` 绑定字段，`start_time`/`end_time`/`title` 三个都要传，且必须是日期/时间类型字段。
6. 任务提醒**目前每个任务最多 1 个**；多个提醒只能落在日历上。
7. 只有设了 `due` 才能设 `reminder`；`start` 必须 ≤ `due`。
8. 字段名用**真实名称**（不是 field_id）传 `--json` 的 key，写前用 `+field-list` 确认。

## 首次搭建板块

```bash
"$PY" scripts/init_board.py --name "长期工作管理台"        # dry-run
"$PY" scripts/init_board.py --name "长期工作管理台" --apply
```

建成后把返回的 `base_token` / `table_id` / `calendar_id` 写入 `config.json`（脚本会提示）。
已有板块想复用：把 token 填进 `config.json` 即可，脚本不会重复建。

## 文件结构

```
feishu-work-planner/
├── SKILL.md                       本文件
├── config.json                    运行配置（base_token/table_id/日历/默认板块）
├── references/
│   ├── board-blueprint.md         表结构、视图、仪表盘设计 + 建表命令
│   ├── routing-rules.md           落点路由 + 紧急度矩阵 + 工期/提醒推导
│   └── lark-cli-cookbook.md       命令配方、参数陷阱、排错
└── scripts/
    ├── intake.py                  自然语言/参数 → 结构化 JSON
    ├── sync.py                    结构化 JSON → 飞书（默认 dry-run）
    └── init_board.py              一键搭建板块（表/视图/仪表盘）
```
