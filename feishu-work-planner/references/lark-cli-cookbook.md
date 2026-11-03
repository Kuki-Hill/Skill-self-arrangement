# lark-cli 命令配方与排错

## 0. 环境

```bash
export PATH="$PATH:/c/Users/Wyki/.workbuddy/binaries/node/cli-connector-packages"
lark-cli doctor            # 健康检查：config / auth / connectivity
lark-cli auth status       # 不接受 --format
lark-cli whoami
```

- `user` token 有效期约 1 小时（refresh 可延续数日）。过期 → `lark-cli auth login`。
- 个人日历 / 我的任务 / 个人 Base 一律 `--as user`。`--as bot` 只写应用自己的资源。
- 每个命令都有 `read | write | high-risk-write` 风险级；`high-risk-write` 必须 `--yes`，且**先取得用户明确同意**。

## 1. 发现能力，不要猜

```bash
lark-cli <domain> --help                     # 列出 +shortcuts 与原生 resource
lark-cli <domain> <+shortcut> --help         # 看真实 flag
lark-cli schema <service>.<resource>.<method> # 参数/类型/scope
lark-cli api GET /open-apis/...              # 兜底：任意 HTTP 路径
lark-cli skills read lark-base               # 领域指南（也含 references/*）
lark-cli skills read "lark-base/references/lark-base-field-schema.md"
```

出现 `unknown_subcommand` 就停止猜变体，回到 `--help` 重新发现。
`schema` 的 service 白名单：approval, attendance, calendar, contact, drive, im, mail, mindnotes, minutes, okr, sheets, slides, task, vc, wiki（**没有 base**）。

## 2. Base（多维表格）—— 台账与甘特

```bash
# 字段盘点（写入前必做）
lark-cli base +field-list --base-token <B> --table-id <T> --as user --format json

# 批量写记录（单批 ≤200，同表串行）
lark-cli base +record-batch-create --base-token <B> --table-id <T> \
  --json @records.json --as user
# records.json: {"create_records":[{"任务名称":"...","紧急度":["P0"],"截止日期":"2026-11-06 00:00"}]}

# 更新已有记录
lark-cli base +record-upsert --base-token <B> --table-id <T> --record-id rec_xxx \
  --json '{"状态":["进行中"],"进度":60}' --as user

# 查重
lark-cli base +record-search --base-token <B> --table-id <T> \
  --keyword "BMP390" --search-field "任务名称" --as user --format json
```

CellValue 规则：
- 文本/电话/URL → `"字符串"`
- 数字/货币/百分比/评分 → `12.5`
- 单选/多选 → `["P0"]`（`multiple=false` 时数组只能一个值；选项必须已存在）
- 日期 → `"2026-03-24 10:00"`（不带时区，按 Base 时区转换）或带时区 ISO、或毫秒时间戳
- 复选 → `true` / `false`
- 人员/群/关联 → `[{"id":"ou_xxx"}]` / `[{"id":"oc_xxx"}]` / `[{"id":"rec_xxx"}]`

**不要写**：系统字段、formula、lookup、attachment（当成普通 CellValue 会报错）。

## 3. Calendar —— 日程

```bash
# 简单日程（无提醒）
lark-cli calendar +create --summary "测试冻结评审" \
  --start "2026-11-06T10:00:00+08:00" --end "2026-11-06T11:00:00+08:00" \
  --description "**来源**：WindSinger 硬件" --as user

# 带提醒 → 用原生命令（+create 没有提醒 flag）
lark-cli calendar events create --calendar-id <cal_id> --data @event.json --as user
```

`event.json`：
```json
{
  "summary": "测试冻结评审",
  "description": "里程碑：测试冻结\n来源：AI 同步",
  "start_time": {"timestamp": "1730858400", "timezone": "Asia/Shanghai"},
  "end_time":   {"timestamp": "1730862000", "timezone": "Asia/Shanghai"},
  "reminders": [{"minutes": 1440}, {"minutes": 120}]
}
```
- 时间戳是**秒级字符串**，用 `date +%s` 取，不要手算。
- `reminders[].minutes` 正数 = 开始前 X 分钟。
- 全天日程用 `--start/--end` 传日期 + `--data '{"all_day":true}'`（不同版本支持度不同，失败就改时段日程）。
- `calendar_id` 省略则写主日历。

## 4. Task —— 待办

```bash
# 建任务（+create 不接受 reminders，分两步）
lark-cli task +create --summary "完成 BMP390 驱动联调" \
  --due "2026-11-06" --description "..." --as user --format json
# 返回 task.guid（不是客户端显示的 t104121）

# 设提醒（每个任务最多 1 个）
lark-cli task +reminder --task-id <guid> --set 1d --as user   # 15m / 1h / 1d

# 完成 / 重开 / 搜索
lark-cli task +complete --task-id <guid> --as user
lark-cli task +reopen   --task-id <guid> --as user
lark-cli task +get-my-tasks --as user --format json
lark-cli task +search --query "BMP390" --as user --format json
```

- 只有设了 `due` 才能设 reminder；`start` ≤ `due`。
- `assignee` 用 `ou_`（用户）或 `cli_`（应用）；跨租户/跨组织加成员会失败 → 不加，靠台账的负责人文本字段。
- 幂等：`--idempotency-key` 防重复创建。

## 5. View —— 甘特 / 日历 / 看板

```bash
lark-cli base +view-create --base-token <B> --table-id <T> \
  --json '{"name":"时间线甘特","type":"gantt"}' --as user
# type 取值：grid | kanban | gallery | calendar | gantt（form 不算视图）

lark-cli base +view-set-timebar --base-token <B> --table-id <T> --view-id "时间线甘特" \
  --json '{"start_time":"开始日期","end_time":"截止日期","title":"任务名称"}' --as user
# 仅 calendar / gantt 支持；三个字段必填，前两个必须是日期时间类型

lark-cli base +view-set-group --base-token <B> --table-id <T> --view-id "状态看板" \
  --json '{"group_config":[{"field":"状态","desc":false}]}' --as user

lark-cli base +view-set-filter --base-token <B> --table-id <T> --view-id "逾期预警" \
  --json @filter.json --as user
```

## 6. 排错速查

| 现象 | 原因 / 处理 |
|---|---|
| `User identity: missing / refresh token expired` | `lark-cli auth login` 重新授权 |
| `missing_scope: xxx` | 该权限未授予用户身份；换 `--as bot` 或放弃该操作 |
| `1254291` | 同表并发写入 → 改串行 |
| 写后立刻读读不到 | Base 写入异步生效，隔几秒再读，或以写入成功响应为准 |
| `--json @file` 找不到文件 | 路径必须是 **cwd 相对**；脚本统一 chdir 到临时目录 |
| `unknown_subcommand` | 命令不存在，回 `--help` 重新发现，不要猜变体 |
| 选项写入报「选项不存在」 | select 字段只能写已存在选项，先 `+field-create` 补选项 |
| `230002 Bot/User can NOT be out of the chat` | 发群消息前先把 bot 拉进群 |

## 7. 安全与预览

- 任何写入前先 `--dry-run` 预览请求体。
- `--format json --jq '.data'` 精简输出，减少 token 消耗。
- 批量/删除/权限变更属高风险，逐个确认，不静默执行。
