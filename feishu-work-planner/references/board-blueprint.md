# 板块蓝图：长期工作管理台

一个 Base 承载全部数据。核心是「任务台账」一张表，其余都是它的视图或辅助表。

## 1. 表结构

### 1.1 任务台账（主表，唯一真源）

`--fields` 数组，**第一项是主字段**。字段定义只用 `type` + `name` + 类型特有字段（不要用 `field_name` / `property` / `ui_type`）。

```json
[
  {"type":"text","name":"任务名称"},
  {"type":"text","name":"任务编号"},
  {"type":"select","name":"所属板块","multiple":false,"options":[
    {"name":"WindSinger 硬件"},{"name":"学业"},{"name":"实习/求职"},{"name":"个人"},{"name":"其他"}]},
  {"type":"text","name":"里程碑"},
  {"type":"text","name":"负责人"},
  {"type":"datetime","name":"开始日期","style":{"format":"yyyy-MM-dd"}},
  {"type":"datetime","name":"截止日期","style":{"format":"yyyy-MM-dd"}},
  {"type":"select","name":"紧急度","multiple":false,"options":[
    {"name":"P0"},{"name":"P1"},{"name":"P2"},{"name":"P3"}]},
  {"type":"select","name":"状态","multiple":false,"default_value":["未开始"],"options":[
    {"name":"未开始"},{"name":"进行中"},{"name":"阻塞"},{"name":"待验收"},{"name":"已完成"}]},
  {"type":"number","name":"进度","style":{"type":"plain","precision":0}},
  {"type":"text","name":"交付物"},
  {"type":"text","name":"标签"},
  {"type":"text","name":"日历日程链接","style":{"type":"url"}},
  {"type":"text","name":"飞书任务链接","style":{"type":"url"}},
  {"type":"select","name":"来源","multiple":false,"default_value":["AI 同步"],"options":[
    {"name":"AI 同步"},{"name":"手动"},{"name":"会议"},{"name":"周计划"}]},
  {"type":"text","name":"备注"},
  {"type":"created_at","name":"录入时间","style":{"format":"yyyy-MM-dd HH:mm"}}
]
```

设计取舍：
- **负责人用 `text` 不用 `user`** — 跨组织成员（个人版飞书）拿不到 open_id，写 `user` 字段必然失败。
- **里程碑用 `text` 不用 link** — 少一张表就少一处同步成本；里程碑节点单独用日历日程承载。
- **进度用 `number`** — 甘特视图不依赖它，看板/表格里手动填更自由。
- **两个链接字段** — 让台账能反查日历与待办，避免三处失联。

### 1.2 里程碑表（辅助，可选）

```json
[
  {"type":"text","name":"里程碑名称"},
  {"type":"datetime","name":"目标日期","style":{"format":"yyyy-MM-dd"}},
  {"type":"select","name":"状态","multiple":false,"options":[
    {"name":"未开始"},{"name":"进行中"},{"name":"已达成"},{"name":"已延期"}]},
  {"type":"text","name":"判定标准"},
  {"type":"text","name":"备注"}
]
```

### 1.3 周复盘表（可选）

```json
[
  {"type":"text","name":"周次"},
  {"type":"datetime","name":"周起始日","style":{"format":"yyyy-MM-dd"}},
  {"type":"text","name":"本周完成"},
  {"type":"text","name":"本周阻塞"},
  {"type":"text","name":"下周重点"}
]
```

## 2. 视图（甘特 / 日历 / 看板都是同一张表的视图）

```bash
# 甘特图 —— 长期规划主视图
lark-cli base +view-create --base-token <B> --table-id <T> \
  --json '{"name":"时间线甘特","type":"gantt"}' --as user

lark-cli base +view-set-timebar --base-token <B> --table-id <T> --view-id "时间线甘特" \
  --json '{"start_time":"开始日期","end_time":"截止日期","title":"任务名称"}' --as user

lark-cli base +view-set-group --base-token <B> --table-id <T> --view-id "时间线甘特" \
  --json '{"group_config":[{"field":"所属板块","desc":false}]}' --as user

# 日历视图 —— 看交付节点分布
lark-cli base +view-create --base-token <B> --table-id <T> \
  --json '{"name":"交付日历","type":"calendar"}' --as user
lark-cli base +view-set-timebar --base-token <B> --table-id <T> --view-id "交付日历" \
  --json '{"start_time":"开始日期","end_time":"截止日期","title":"任务名称"}' --as user

# 看板 —— 日常推进
lark-cli base +view-create --base-token <B> --table-id <T> \
  --json '{"name":"状态看板","type":"kanban"}' --as user
lark-cli base +view-set-group --base-token <B> --table-id <T> --view-id "状态看板" \
  --json '{"group_config":[{"field":"状态","desc":false}]}' --as user

# 表格：本周到期（手工维护日期常量，见下方说明）
lark-cli base +view-create --base-token <B> --table-id <T> \
  --json '{"name":"本周到期","type":"grid"}' --as user
lark-cli base +view-set-filter --base-token <B> --table-id <T> --view-id "本周到期" \
  --json '{"logic":"and","conditions":[
    ["截止日期","<","ExactDate(2026-11-09 00:00:00)"],
    ["状态","disjoint",["已完成"]]]}' --as user

# 表格：逾期预警
lark-cli base +view-create --base-token <B> --table-id <T> \
  --json '{"name":"逾期预警","type":"grid"}' --as user
lark-cli base +view-set-filter --base-token <B> --table-id <T> --view-id "逾期预警" \
  --json '{"logic":"and","conditions":[
    ["截止日期","<","ExactDate(2026-11-03 00:00:00)"],
    ["状态","disjoint",["已完成"]]]}' --as user
```

> **日期筛选是静态的**：`ExactDate(...)` 写进去就固定了。「本周到期」这类滚动窗口要么每周用 `+view-set-filter` 刷一次，要么改成按「状态」分组的看板视图。脚本 `init_board.py` 会按创建当天生成一次，后续刷新用 `scripts/sync.py --refresh-views --apply`。

过滤条件语法：`intersects`（命中任一）、`disjoint`（无交集）、`non_empty` / `empty`、数字 `>=` `<=`；日期**不支持 `>=`**，含当天下界写「大于前一天 23:59:59.999」；「本周到期」的上界是下周一 00:00（含整个周日）。

## 3. 仪表盘

```bash
lark-cli base +dashboard-create --base-token <B> --name "工作全景" --as user

# 指标卡：任务总数
lark-cli base +dashboard-block-create --base-token <B> --dashboard-id <D> \
  --name "任务总数" --type statistics \
  --data-config '{"table_name":"任务台账","count_all":true}' --as user

# 分布图：按状态 / 按紧急度（count_all 计数 + group_by 维度；rollup 只支持 SUM/MAX/MIN/AVERAGE，做计数要用 count_all）
lark-cli base +dashboard-block-create --base-token <B> --dashboard-id <D> \
  --name "状态分布" --type pie \
  --data-config '{"table_name":"任务台账","count_all":true,"group_by":[{"field_name":"状态","mode":"integrated"}]}' --as user

lark-cli base +dashboard-arrange --base-token <B> --dashboard-id <D> --as user
```

- 组件必须**串行**创建（并发容易失败）。
- `count_all` 与 `series` 二选一，不能同传；分布计数图用 `count_all` + `group_by`。
- `--type` 直接选图表类型（pie/column/bar/line…），没有 `chart` 这个类型。
- 表名/字段名用真实名称，不是 ID。

## 4. 权限与入口

```bash
# 个人使用可不开放分享；要手机端查看时开只读链接
lark-cli drive permission.public patch --token <base_token> --type bitable \
  --data '{"link_share_entity":"anyone_readable"}' --yes --as user
```

`--yes` 属 **high-risk-write**，必须先取得用户明确同意。共享链接设为 `anyone_readable` 而非 editable，避免误改台账。
