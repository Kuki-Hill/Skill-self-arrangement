#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
sync.py — 把 intake.py 产出的计划写入飞书（默认 dry-run，加 --apply 才真写）。

  python sync.py --plan plan.json                 # 预览将执行的命令
  python sync.py --plan plan.json --apply         # 真实写入
  python sync.py --plan plan.json --apply --only base
  python sync.py --refresh-views --apply          # 刷新「本周到期 / 逾期预警」视图的日期常量
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from lark import run, run_json, find_all  # noqa: E402

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_PATH = os.path.join(HERE, "config.json")

DEFAULT_FIELD_MAP = {
    "title": "任务名称",
    "project": "所属板块",
    "milestone": "里程碑",
    "owner": "负责人",
    "start_date": "开始日期",
    "due_date": "截止日期",
    "priority": "紧急度",
    "status": "状态",
    "progress": "进度",
    "deliverable": "交付物",
    "tags": "标签",
    "source": "来源",
    "notes": "备注",
    "calendar_link": "日历日程链接",
    "task_link": "飞书任务链接",
}
SELECT_FIELDS = {"所属板块", "里程碑", "紧急度", "状态", "来源", "标签"}


def load_config():
    if not os.path.exists(CONFIG_PATH):
        raise SystemExit(
            "缺少 config.json。请先运行 scripts/init_board.py 搭建板块，"
            "或把已有板块的 base_token / table_id 填进 %s" % CONFIG_PATH
        )
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        cfg = json.load(f)
    token = str(cfg.get("base_token") or "").strip()
    if not token or token.startswith("<") or "PLACEHOLDER" in token.upper():
        raise SystemExit(
            "config.json 里的 base_token 还是占位值，尚未绑定真实板块。\n"
            "执行：python scripts/init_board.py --name \"长期工作管理台\" --apply\n"
            "或把已有 Base 的 token 手工填进 %s" % CONFIG_PATH
        )
    return cfg


def check_auth():
    code, out, err = run(["auth", "status"])
    if code != 0:
        raise SystemExit("lark-cli 不可用：%s" % (err or out))
    if '"ready"' not in out and '"status": "ready"' not in out.replace("'", '"'):
        pass
    if "expired" in out or "missing" in out:
        print("⚠️  飞书用户授权已过期，请先执行：lark-cli auth login", file=sys.stderr)
        if "user" in out:
            return False
    return True


def minutes_to_flag(minutes):
    if minutes % 1440 == 0:
        return "%dd" % (minutes // 1440)
    if minutes % 60 == 0:
        return "%dh" % (minutes // 60)
    return "%dm" % minutes


def to_timestamp(iso_str):
    dt = datetime.strptime(iso_str, "%Y-%m-%dT%H:%M:%S+08:00")
    return int(dt.timestamp())


def build_record(task, fmap):
    fields = {}
    set_text = lambda k, v: fields.__setitem__(fmap[k], v) if v else None
    set_text("title", task["title"])
    set_text("project", task.get("project"))
    set_text("milestone", task.get("milestone"))
    set_text("owner", task.get("owner"))
    if task.get("start_date"):
        fields[fmap["start_date"]] = task["start_date"] + " 00:00"
    if task.get("due_date"):
        fields[fmap["due_date"]] = task["due_date"] + " 00:00"
    set_text("priority", task.get("priority"))
    set_text("status", task.get("status"))
    if task.get("progress"):
        fields[fmap["progress"]] = int(task["progress"])
    set_text("deliverable", task.get("deliverable"))
    set_text("tags", task.get("tags"))
    set_text("source", task.get("source"))
    set_text("notes", task.get("notes"))

    # select 字段必须是数组
    for key, val in list(fields.items()):
        if key in SELECT_FIELDS and not isinstance(val, list):
            fields[key] = [val]
    return fields


def collect_record_ids(data):
    """兼容不同命令返回 record_id 的方式（record_id / record_ids / record_id_list）。"""
    if not data:
        return []
    ids = []
    for key in ("record_id", "record_ids", "record_id_list"):
        for v in find_all(data, key):
            if isinstance(v, list):
                ids.extend([x for x in v if isinstance(x, str)])
            elif isinstance(v, str):
                ids.append(v)
    return ids


def dedupe(cfg, fmap, task, dry, tmp):
    """按任务名称查重，返回 (record_id|None, matched_due|None)。"""
    keyword = task["title"][:12]
    args = ["base", "+record-search",
            "--base-token", cfg["base_token"],
            "--table-id", cfg["table_id"],
            "--keyword", keyword,
            "--search-field", fmap["title"],
            "--as", "user"]
    code, data, err = run_json(args, cwd=tmp, dry=dry)
    if dry or code != 0 or data is None:
        return None, None
    ids = collect_record_ids(data)
    dues = find_all(data, fmap["due_date"])
    if not ids:
        return None, None
    return ids[0], (dues[0] if dues else None)


def write_base(cfg, fmap, task, dry, tmp, record_id=None):
    fields = build_record(task, fmap)
    if record_id:
        args = ["base", "+record-upsert",
                "--base-token", cfg["base_token"],
                "--table-id", cfg["table_id"],
                "--record-id", record_id,
                "--json", json.dumps(fields, ensure_ascii=False),
                "--as", "user"]
    else:
        payload = {"create_records": [fields]}
        with open(os.path.join(tmp, "records.json"), "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False)
        args = ["base", "+record-batch-create",
                "--base-token", cfg["base_token"],
                "--table-id", cfg["table_id"],
                "--json", "@records.json",
                "--as", "user"]
    code, data, err = run_json(args, cwd=tmp, dry=dry)
    if dry:
        return {"dry_run": True, "args": args}
    if code != 0:
        return {"ok": False, "error": (err or data or "")[:400]}
    ids = collect_record_ids(data)
    urls = find_all(data, "url")
    return {"ok": True, "record_id": ids[0] if ids else None, "url": urls[0] if urls else None}


def write_calendar(cfg, task, dry, tmp):
    cal = task["calendar"]
    calendar_id = cfg.get("calendar_id") or "primary"
    event = {
        "summary": task["title"],
        "description": "\n".join(filter(None, [
            "板块：%s" % task.get("project", ""),
            "里程碑：%s" % task.get("milestone", ""),
            "紧急度：%s" % task.get("priority", ""),
            task.get("notes", ""),
        ])).strip(),
        "start_time": {"timestamp": str(to_timestamp(cal["start"])), "timezone": "Asia/Shanghai"},
        "end_time": {"timestamp": str(to_timestamp(cal["end"])), "timezone": "Asia/Shanghai"},
    }
    if cal.get("all_day"):
        event["all_day"] = True
    if cal.get("reminder_minutes"):
        event["reminders"] = [{"minutes": m} for m in cal["reminder_minutes"]]

    with open(os.path.join(tmp, "event.json"), "w", encoding="utf-8") as f:
        json.dump(event, f, ensure_ascii=False)
    args = ["calendar", "events", "create",
            "--calendar-id", calendar_id,
            "--data", "@event.json",
            "--as", "user"]
    code, data, err = run_json(args, cwd=tmp, dry=dry)
    if dry:
        return {"dry_run": True, "args": args}
    if code != 0:
        return {"ok": False, "error": (err or data or "")[:400]}
    eids = find_all(data, "event_id")
    return {"ok": True, "event_id": eids[0] if eids else None}


def write_task(cfg, task, dry, tmp):
    desc = "\n".join(filter(None, [
        "板块：%s" % task.get("project", ""),
        "里程碑：%s" % task.get("milestone", ""),
        "周期：%s → %s" % (task.get("start_date", ""), task.get("due_date", "")),
        task.get("notes", ""),
    ])).strip()
    args = ["task", "+create",
            "--summary", task["title"],
            "--due", task["task"]["due"],
            "--as", "user"]
    if desc:
        args += ["--description", desc]
    code, data, err = run_json(args, cwd=tmp, dry=dry)
    if dry:
        return {"dry_run": True, "args": args}
    if code != 0:
        return {"ok": False, "error": (err or data or "")[:400]}
    ids = find_all(data, "task_id") or find_all(data, "guid")
    urls = find_all(data, "url")
    task_id = ids[0] if ids else None
    result = {"ok": True, "task_id": task_id, "url": urls[0] if urls else None}

    reminder = task["task"].get("reminder_minutes")
    if task_id and reminder:
        r_args = ["task", "+reminder", "--task-id", task_id,
                  "--set", minutes_to_flag(reminder), "--as", "user"]
        r_code, r_data, r_err = run_json(r_args, cwd=tmp, dry=dry)
        result["reminder"] = {"ok": r_code == 0, "set": minutes_to_flag(reminder)}
        if r_code != 0:
            result["reminder"]["error"] = (r_err or "")[:200]
    return result


def write_back_links(cfg, fmap, record_id, links, dry, tmp):
    if not record_id or not links:
        return None
    args = ["base", "+record-upsert",
            "--base-token", cfg["base_token"],
            "--table-id", cfg["table_id"],
            "--record-id", record_id,
            "--json", json.dumps(links, ensure_ascii=False),
            "--as", "user"]
    code, data, err = run_json(args, cwd=tmp, dry=dry)
    return {"ok": code == 0, "error": None if code == 0 else (err or "")[:200]}


def refresh_views(cfg, dry, tmp):
    today = datetime.now()
    week_end = today + timedelta(days=7 - today.weekday())  # 下周一 00:00，含整个周日
    views = [
        ("本周到期", week_end.strftime("%Y-%m-%d 00:00:00")),
        ("逾期预警", today.strftime("%Y-%m-%d 00:00:00")),
    ]
    results = []
    for name, boundary in views:
        flt = {"logic": "and", "conditions": [
            ["截止日期", "<", "ExactDate(%s)" % boundary],
            ["状态", "disjoint", ["已完成"]],
        ]}
        with open(os.path.join(tmp, "filter.json"), "w", encoding="utf-8") as f:
            json.dump(flt, f, ensure_ascii=False)
        args = ["base", "+view-set-filter",
                "--base-token", cfg["base_token"],
                "--table-id", cfg["table_id"],
                "--view-id", name,
                "--json", "@filter.json",
                "--as", "user"]
        code, data, err = run_json(args, cwd=tmp, dry=dry)
        results.append({"view": name, "boundary": boundary, "ok": code == 0,
                        "error": None if code == 0 else (err or "")[:200]})
    return results


def main():
    p = argparse.ArgumentParser(description="把结构化任务写入飞书")
    p.add_argument("--plan", help="intake.py 产出的 plan.json")
    p.add_argument("--apply", action="store_true", help="真实写入；不加则 dry-run")
    p.add_argument("--only", choices=["base", "calendar", "task"], help="只写某一个落点")
    p.add_argument("--no-dedupe", action="store_true", help="跳过查重，强制新建记录")
    p.add_argument("--refresh-views", action="store_true", help="刷新视图日期常量")
    p.add_argument("--out", help="结果 JSON 输出路径")
    args = p.parse_args()

    if not args.plan and not args.refresh_views:
        raise SystemExit("需要 --plan 或 --refresh-views")

    cfg = load_config()
    fmap = dict(DEFAULT_FIELD_MAP)
    fmap.update(cfg.get("field_map", {}))
    dry = not args.apply

    if not check_auth() and args.apply:
        raise SystemExit("授权不可用，已中止")

    tmp = tempfile.mkdtemp(prefix="feishu_sync_")
    summary = {"dry_run": dry, "applied": args.apply, "results": []}

    if args.refresh_views:
        summary["views"] = refresh_views(cfg, dry, tmp)

    if args.plan:
        with open(args.plan, "r", encoding="utf-8") as f:
            plan = json.load(f)
        for task in plan["tasks"]:
            item = {"title": task["title"], "priority": task.get("priority"),
                    "due_date": task.get("due_date"), "routing": task.get("routing"),
                    "warnings": list(task.get("warnings", []))}
            record_id = None
            route = task.get("routing", {})

            if route.get("base", True) and args.only in (None, "base"):
                if not args.no_dedupe:
                    record_id, matched_due = dedupe(cfg, fmap, task, dry, tmp)
                    if record_id:
                        item["warnings"].append("已存在同名记录，改为更新（record_id=%s）" % record_id)
                item["base"] = write_base(cfg, fmap, task, dry, tmp, record_id)
                if not record_id and isinstance(item["base"], dict):
                    record_id = item["base"].get("record_id")

            if route.get("calendar") and args.only in (None, "calendar"):
                item["calendar"] = write_calendar(cfg, task, dry, tmp)

            if route.get("task") and args.only in (None, "task"):
                item["task"] = write_task(cfg, task, dry, tmp)

            if not dry and record_id:
                links = {}
                cal_id = item.get("calendar", {}).get("event_id") if isinstance(item.get("calendar"), dict) else None
                task_url = item.get("task", {}).get("url") if isinstance(item.get("task"), dict) else None
                if cal_id:
                    links[fmap["calendar_link"]] = "event:%s" % cal_id
                if task_url:
                    links[fmap["task_link"]] = task_url
                if links:
                    item["links_back"] = write_back_links(cfg, fmap, record_id, links, dry, tmp)

            summary["results"].append(item)

    text = json.dumps(summary, ensure_ascii=False, indent=2)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            f.write(text)
        print("结果已写入 %s" % args.out)
    else:
        print(text)
    if dry:
        print("\n[dry-run] 以上为预览，未产生真实写入。确认后加 --apply 执行。", file=sys.stderr)


if __name__ == "__main__":
    main()
