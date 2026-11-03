#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
init_board.py — 一键搭建「长期工作管理台」板块（默认 dry-run，加 --apply 才真建）。

  python init_board.py --name "长期工作管理台"              # 预览
  python init_board.py --name "长期工作管理台" --apply      # 真实创建并写 config.json
  python init_board.py --base-token <已有 base> --apply     # 复用已有 Base，只补表与视图
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
import time
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from lark import run, run_json, find_all  # noqa: E402

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_PATH = os.path.join(HERE, "config.json")
DEFAULT_PROJECTS = ["WindSinger 硬件", "学业", "实习/求职", "个人", "其他"]

FIELDS = [
    {"type": "text", "name": "任务名称"},
    {"type": "text", "name": "任务编号"},
    {"type": "select", "name": "所属板块", "multiple": False, "options": [{"name": p} for p in DEFAULT_PROJECTS]},
    {"type": "text", "name": "里程碑"},
    {"type": "text", "name": "负责人"},
    {"type": "datetime", "name": "开始日期", "style": {"format": "yyyy-MM-dd"}},
    {"type": "datetime", "name": "截止日期", "style": {"format": "yyyy-MM-dd"}},
    {"type": "select", "name": "紧急度", "multiple": False,
     "options": [{"name": "P0"}, {"name": "P1"}, {"name": "P2"}, {"name": "P3"}]},
    {"type": "select", "name": "状态", "multiple": False, "default_value": ["未开始"],
     "options": [{"name": "未开始"}, {"name": "进行中"}, {"name": "阻塞"}, {"name": "待验收"}, {"name": "已完成"}]},
    {"type": "number", "name": "进度", "style": {"type": "plain", "precision": 0}},
    {"type": "text", "name": "交付物"},
    {"type": "text", "name": "标签"},
    {"type": "text", "name": "日历日程链接", "style": {"type": "url"}},
    {"type": "text", "name": "飞书任务链接", "style": {"type": "url"}},
    {"type": "select", "name": "来源", "multiple": False, "default_value": ["AI 同步"],
     "options": [{"name": "AI 同步"}, {"name": "手动"}, {"name": "会议"}, {"name": "周计划"}]},
    {"type": "text", "name": "备注"},
    {"type": "created_at", "name": "录入时间", "style": {"format": "yyyy-MM-dd HH:mm"}},
]

VIEWS = [
    {"name": "全部任务", "type": "grid"},
    {"name": "时间线甘特", "type": "gantt", "timebar": {"start_time": "开始日期", "end_time": "截止日期", "title": "任务名称"},
     "group": [{"field": "所属板块", "desc": False}]},
    {"name": "交付日历", "type": "calendar", "timebar": {"start_time": "开始日期", "end_time": "截止日期", "title": "任务名称"}},
    {"name": "状态看板", "type": "kanban", "group": [{"field": "状态", "desc": False}]},
    {"name": "本周到期", "type": "grid", "filter": "week"},
    {"name": "逾期预警", "type": "grid", "filter": "overdue"},
]


def filter_for(kind):
    today = datetime.now()
    if kind == "week":
        boundary = today + timedelta(days=7 - today.weekday())  # 下周一 00:00
    else:
        boundary = today
    return {"logic": "and", "conditions": [
        ["截止日期", "<", "ExactDate(%s)" % boundary.strftime("%Y-%m-%d 00:00:00")],
        ["状态", "disjoint", ["已完成"]],
    ]}


def retry(fn, attempts=3, wait=2.0):
    last = None
    for i in range(attempts):
        res = fn()
        if isinstance(res, dict) and res.get("ok"):
            return res
        last = res
        time.sleep(wait)
    return last


def main():
    p = argparse.ArgumentParser(description="搭建飞书长期工作管理板块")
    p.add_argument("--name", default="长期工作管理台")
    p.add_argument("--base-token", help="复用已有 Base，只补表与视图")
    p.add_argument("--projects", help="逗号分隔的板块选项，覆盖默认值")
    p.add_argument("--apply", action="store_true")
    p.add_argument("--no-dashboard", action="store_true", help="跳过仪表盘")
    args = p.parse_args()

    dry = not args.apply
    if args.projects:
        names = [x.strip() for x in args.projects.split(",") if x.strip()]
        for f in FIELDS:
            if f["name"] == "所属板块":
                f["options"] = [{"name": n} for n in names]

    tmp = tempfile.mkdtemp(prefix="feishu_init_")
    summary = {"dry_run": dry, "steps": []}

    base_token = args.base_token
    table_id = None
    url = None

    if not base_token:
        with open(os.path.join(tmp, "fields.json"), "w", encoding="utf-8") as f:
            json.dump(FIELDS, f, ensure_ascii=False)
        cmd = ["base", "+base-create", "--name", args.name, "--table-name", "任务台账",
               "--time-zone", "Asia/Shanghai", "--fields", "@fields.json", "--as", "user"]
        code, data, err = run_json(cmd, cwd=tmp, dry=dry)
        summary["steps"].append({"step": "base-create", "ok": code == 0, "error": None if code == 0 else (err or "")[:300]})
        if dry:
            summary["hint"] = "dry-run 结束，加 --apply 真实创建"
            print(json.dumps(summary, ensure_ascii=False, indent=2))
            return
        if code != 0:
            print(json.dumps(summary, ensure_ascii=False, indent=2))
            raise SystemExit("创建 Base 失败")
        tokens = find_all(data, "base_token") or find_all(data, "app_token")
        table_id = (find_all(data, "table_id") or [None])[0]
        url = (find_all(data, "url") or [None])[0]
        base_token = tokens[0] if tokens else None
        if not base_token:
            raise SystemExit("未能解析 base_token：%s" % json.dumps(data, ensure_ascii=False)[:400])
        if not table_id:
            # base-create 响应里不一定带 table_id，用 table-list 兜底
            code2, data2, _ = run_json(["base", "+table-list", "--base-token", base_token,
                                        "--as", "user"], cwd=tmp)
            if code2 == 0 and data2:
                for tb in (find_all(data2, "tables") or []):
                    if isinstance(tb, dict) and tb.get("name") == "任务台账":
                        table_id = tb.get("id")
                        break
    else:
        with open(os.path.join(tmp, "fields.json"), "w", encoding="utf-8") as f:
            json.dump(FIELDS, f, ensure_ascii=False)
        cmd = ["base", "+table-create", "--base-token", base_token, "--name", "任务台账",
               "--fields", "@fields.json", "--as", "user"]
        code, data, err = run_json(cmd, cwd=tmp, dry=dry)
        summary["steps"].append({"step": "table-create", "ok": code == 0, "error": None if code == 0 else (err or "")[:300]})
        if not dry and code == 0:
            table_id = (find_all(data, "table_id") or [None])[0]

    summary["base_token"] = base_token
    summary["table_id"] = table_id
    summary["url"] = url

    if dry:
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return

    # ---- 视图 ----
    for view in VIEWS:
        cmd = ["base", "+view-create", "--base-token", base_token, "--table-id", table_id or "任务台账",
               "--json", json.dumps({"name": view["name"], "type": view["type"]}, ensure_ascii=False),
               "--as", "user"]
        code, data, err = run_json(cmd, cwd=tmp, dry=False)
        summary["steps"].append({"step": "view-create:%s" % view["name"], "ok": code == 0,
                                 "error": None if code == 0 else (err or "")[:200]})
        if code != 0:
            continue
        if view.get("timebar"):
            cmd = ["base", "+view-set-timebar", "--base-token", base_token, "--table-id", table_id or "任务台账",
                   "--view-id", view["name"], "--json", json.dumps(view["timebar"], ensure_ascii=False), "--as", "user"]
            code, _, err = run_json(cmd, cwd=tmp, dry=False)
            summary["steps"].append({"step": "timebar:%s" % view["name"], "ok": code == 0,
                                     "error": None if code == 0 else (err or "")[:200]})
        if view.get("group"):
            cmd = ["base", "+view-set-group", "--base-token", base_token, "--table-id", table_id or "任务台账",
                   "--view-id", view["name"], "--json", json.dumps({"group_config": view["group"]}, ensure_ascii=False),
                   "--as", "user"]
            code, _, err = run_json(cmd, cwd=tmp, dry=False)
            summary["steps"].append({"step": "group:%s" % view["name"], "ok": code == 0,
                                     "error": None if code == 0 else (err or "")[:200]})
        if view.get("filter"):
            with open(os.path.join(tmp, "filter.json"), "w", encoding="utf-8") as f:
                json.dump(filter_for(view["filter"]), f, ensure_ascii=False)
            cmd = ["base", "+view-set-filter", "--base-token", base_token, "--table-id", table_id or "任务台账",
                   "--view-id", view["name"], "--json", "@filter.json", "--as", "user"]
            code, _, err = run_json(cmd, cwd=tmp, dry=False)
            summary["steps"].append({"step": "filter:%s" % view["name"], "ok": code == 0,
                                     "error": None if code == 0 else (err or "")[:200]})

    # ---- 仪表盘（组件串行）----
    if not args.no_dashboard:
        code, data, err = run_json(["base", "+dashboard-create", "--base-token", base_token,
                                    "--name", "工作全景", "--as", "user"], cwd=tmp, dry=False)
        summary["steps"].append({"step": "dashboard-create", "ok": code == 0,
                                 "error": None if code == 0 else (err or "")[:200]})
        dash_id = (find_all(data, "dashboard_id") or [None])[0] if code == 0 else None
        if dash_id:
            blocks = [
                ("任务总数", "statistics", {"table_name": "任务台账", "count_all": True}),
                ("状态分布", "pie", {"table_name": "任务台账", "count_all": True,
                                     "group_by": [{"field_name": "状态", "mode": "integrated"}]}),
                ("紧急度分布", "column", {"table_name": "任务台账", "count_all": True,
                                          "group_by": [{"field_name": "紧急度", "mode": "integrated"}]}),
            ]
            for name, btype, cfg_json in blocks:
                cmd = ["base", "+dashboard-block-create", "--base-token", base_token,
                       "--dashboard-id", dash_id, "--name", name, "--type", btype,
                       "--data-config", json.dumps(cfg_json, ensure_ascii=False), "--as", "user"]
                code, _, err = run_json(cmd, cwd=tmp, dry=False)
                summary["steps"].append({"step": "dashboard-block:%s" % name, "ok": code == 0,
                                         "error": None if code == 0 else (err or "")[:200]})
            code, _, err = run_json(["base", "+dashboard-arrange", "--base-token", base_token,
                                     "--dashboard-id", dash_id, "--as", "user"], cwd=tmp, dry=False)
            summary["steps"].append({"step": "dashboard-arrange", "ok": code == 0,
                                     "error": None if code == 0 else (err or "")[:200]})

    # ---- 写 config.json ----
    config = {"base_token": base_token, "table_id": table_id, "calendar_id": "primary",
              "timezone": "Asia/Shanghai", "table_name": "任务台账",
              "projects": [o["name"] for o in FIELDS[2]["options"]],
              "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                old = json.load(f)
            config = {**old, **config}
        except (ValueError, OSError):
            pass
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(config, f, ensure_ascii=False, indent=2)
    summary["config_path"] = CONFIG_PATH
    if url:
        summary["board_url"] = url

    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
