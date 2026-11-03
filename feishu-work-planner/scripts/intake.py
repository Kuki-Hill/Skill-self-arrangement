#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
intake.py — 把「任务描述 + 截止时间 + 紧急程度」结构化为飞书写入计划。

单条：
  python intake.py --title "完成 BMP390 驱动联调" --deadline "11-06" --priority P0 \
      --project "WindSinger 硬件" --milestone "测试冻结" --owner wyki --out plan.json

多条（同一批参数可共享；每条可覆盖）：
  python intake.py --batch tasks.json --out plan.json
  tasks.json: [{"title":"...","deadline":"11-06","priority":"P0"}, ...]

输出 JSON：{"timezone":..., "tasks":[{..., "routing":{...}, "calendar":{...}, "task":{...}, "warnings":[...]}]}
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import datetime, timedelta

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

TZ = "Asia/Shanghai"
DEFAULT_DURATION = {"P0": 1, "P1": 3, "P2": 7, "P3": 14}
REMINDER_MINUTES = {"P0": [1440, 120], "P1": [1440], "P2": [120], "P3": []}
PRIORITY_ALIAS = {
    "p0": "P0", "紧急": "P0", "很急": "P0", "特急": "P0", "最高": "P0",
    "urgent": "P0", "critical": "P0", "火烧眉毛": "P0",
    "p1": "P1", "高": "P1", "重要": "P1", "high": "P1", "优先": "P1",
    "p2": "P2", "中": "P2", "普通": "P2", "一般": "P2", "medium": "P2", "normal": "P2",
    "p3": "P3", "低": "P3", "不急": "P3", "有空": "P3", "再说": "P3", "low": "P3",
}
WEEKDAY_MAP = {"一": 0, "二": 1, "三": 2, "四": 3, "五": 4, "六": 5, "日": 6, "天": 6,
               "1": 0, "2": 1, "3": 2, "4": 3, "5": 4, "6": 5, "7": 6, "0": 6}
DEFAULT_SLOT_HOUR = 9
DEFAULT_SLOT_MINUTES = 60


def norm_priority(value):
    if value is None:
        return "P2", False
    s = str(value).strip()
    if not s:
        return "P2", False
    if s.upper() in ("P0", "P1", "P2", "P3"):
        return s.upper(), False
    for key, val in PRIORITY_ALIAS.items():
        if key in s.lower():
            return val, False
    return "P2", True


def parse_date(text, today):
    """返回 (datetime|None, has_time)。解析失败返回 (None, False)。"""
    if text is None:
        return None, False
    s = str(text).strip()
    if not s:
        return None, False
    low = s.lower().replace(" ", "")

    if low in ("today", "今天"):
        return datetime(today.year, today.month, today.day), False
    if low in ("tomorrow", "明天", "明日"):
        d = today + timedelta(days=1)
        return datetime(d.year, d.month, d.day), False
    if low in ("后天",):
        d = today + timedelta(days=2)
        return datetime(d.year, d.month, d.day), False
    if low in ("大后天",):
        d = today + timedelta(days=3)
        return datetime(d.year, d.month, d.day), False

    m = re.match(r"^\+(\d+)\s*d$", low)
    if m:
        d = today + timedelta(days=int(m.group(1)))
        return datetime(d.year, d.month, d.day), False
    m = re.match(r"^(\d+)\s*(天|日)后$", low)
    if m:
        d = today + timedelta(days=int(m.group(1)))
        return datetime(d.year, d.month, d.day), False
    m = re.match(r"^(\d+)\s*周后$", low)
    if m:
        d = today + timedelta(weeks=int(m.group(1)))
        return datetime(d.year, d.month, d.day), False
    m = re.match(r"^(\d+)\s*个?月后$", low)
    if m:
        d = today + timedelta(days=30 * int(m.group(1)))
        return datetime(d.year, d.month, d.day), False

    if low in ("月底", "月末"):
        nxt = (today.replace(day=28) + timedelta(days=4)).replace(day=1)
        last = nxt - timedelta(days=1)
        return datetime(last.year, last.month, last.day), False
    if low in ("年底", "年末"):
        return datetime(today.year, 12, 31), False

    m = re.match(r"^(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})(?:[T ](\d{1,2}):(\d{2}))?$", s)
    if m:
        y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
        if m.group(4):
            return datetime(y, mo, d, int(m.group(4)), int(m.group(5))), True
        return datetime(y, mo, d), False

    m = re.match(r"^(\d{1,2})[-/.](\d{1,2})(?:[T ](\d{1,2}):(\d{2}))?$", s)
    if m:
        mo, d = int(m.group(1)), int(m.group(2))
        y = today.year
        try:
            dt = datetime(y, mo, d)
        except ValueError:
            return None, False
        if m.group(3):
            dt = dt.replace(hour=int(m.group(3)), minute=int(m.group(4)))
            has_time = True
        else:
            has_time = False
        if dt.date() < today:
            try:
                dt = dt.replace(year=y + 1)
            except ValueError:
                pass
        return dt, has_time

    m = re.search(r"(本|下)?\s*周\s*([一二三四五六日天0-7])", s)
    if m:
        target = WEEKDAY_MAP[m.group(2)]
        prefix = m.group(1) or ""
        delta = (target - today.weekday()) % 7
        if delta == 0:
            delta = 7
        if prefix == "下":
            delta = delta + 7 if delta < 7 else 7
        d = today + timedelta(days=delta)
        return datetime(d.year, d.month, d.day), False

    return None, False


def build_task(raw, today, defaults):
    warnings = []
    title = (raw.get("title") or "").strip()
    if not title:
        raise ValueError("每条任务必须有 title")

    priority, alias_failed = norm_priority(raw.get("priority", defaults.get("priority")))
    if alias_failed:
        warnings.append("紧急度「%s」无法识别，已按 P2 处理" % raw.get("priority"))
    if raw.get("priority") is None and defaults.get("priority") is None:
        warnings.append("未指定紧急度，默认 P2")

    due_dt, due_has_time = parse_date(raw.get("deadline") or raw.get("due"), today)
    start_dt, _ = parse_date(raw.get("start"), today)
    duration = raw.get("duration_days")
    duration = int(duration) if duration else DEFAULT_DURATION[priority]

    if due_dt is None and start_dt is None:
        due_dt = datetime(today.year, today.month, today.day) + timedelta(days=duration)
        start_dt = datetime(today.year, today.month, today.day)
        warnings.append("未给出截止日期，按 P%s 默认工期 %d 天推算至 %s" %
                        (priority[1], duration, due_dt.strftime("%Y-%m-%d")))
    elif due_dt is None:
        due_dt = start_dt + timedelta(days=duration)
        warnings.append("未给出截止日期，按开始日期 + %d 天推算" % duration)
    elif start_dt is None:
        start_dt = due_dt - timedelta(days=duration)
        today_dt = datetime(today.year, today.month, today.day)
        if start_dt < today_dt:
            start_dt = today_dt
    elif start_dt > due_dt:
        start_dt, due_dt = due_dt, start_dt
        warnings.append("开始日期晚于截止日期，已自动对调")

    span = (due_dt.date() - start_dt.date()).days
    duration_days = span if span > 0 else 1

    # ---- 落点路由 ----
    force_cal = raw.get("calendar")
    force_task = raw.get("task")
    base_on = raw.get("base", True) is not False
    if force_cal is True:
        cal_on = True
    elif force_cal is False:
        cal_on = False
    else:
        cal_on = priority == "P0" or (priority == "P1" and bool(raw.get("milestone")))
    if force_task is True:
        task_on = True
    elif force_task is False:
        task_on = False
    else:
        task_on = priority in ("P0", "P1", "P2")

    # ---- 日历时段 ----
    all_day = bool(raw.get("all_day"))
    if due_has_time:
        cal_start = due_dt
    else:
        cal_start = due_dt.replace(hour=DEFAULT_SLOT_HOUR, minute=0)
    cal_end = cal_start + timedelta(minutes=DEFAULT_SLOT_MINUTES)
    reminder_minutes = list(REMINDER_MINUTES[priority])

    task_reminder = max(reminder_minutes) if (task_on and reminder_minutes) else None

    return {
        "title": title,
        "project": (raw.get("project") or defaults.get("project") or "").strip(),
        "milestone": (raw.get("milestone") or "").strip(),
        "owner": (raw.get("owner") or defaults.get("owner") or "").strip(),
        "priority": priority,
        "start_date": start_dt.strftime("%Y-%m-%d"),
        "due_date": due_dt.strftime("%Y-%m-%d"),
        "due_has_time": due_has_time,
        "duration_days": duration_days,
        "status": (raw.get("status") or "未开始").strip(),
        "progress": int(raw.get("progress") or 0),
        "deliverable": (raw.get("deliverable") or "").strip(),
        "tags": raw.get("tags") or "",
        "notes": (raw.get("notes") or "").strip(),
        "source": (raw.get("source") or "AI 同步").strip(),
        "routing": {"base": base_on, "calendar": cal_on, "task": task_on},
        "calendar": {
            "create": cal_on,
            "all_day": all_day,
            "start": cal_start.strftime("%Y-%m-%dT%H:%M:%S+08:00"),
            "end": cal_end.strftime("%Y-%m-%dT%H:%M:%S+08:00"),
            "reminder_minutes": reminder_minutes,
        },
        "task": {
            "create": task_on,
            "due": due_dt.strftime("%Y-%m-%d"),
            "reminder_minutes": task_reminder,
        },
        "warnings": warnings,
    }


def load_raws(args):
    if args.batch:
        with open(args.batch, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            data = [data]
        return data
    if args.json_arg:
        data = json.loads(args.json_arg)
        return data if isinstance(data, list) else [data]
    raw = {
        "title": args.title,
        "deadline": args.deadline or args.due,
        "start": args.start,
        "priority": args.priority,
        "project": args.project,
        "milestone": args.milestone,
        "owner": args.owner,
        "status": args.status,
        "progress": args.progress,
        "deliverable": args.deliverable,
        "tags": args.tags,
        "notes": args.notes,
        "source": args.source,
        "duration_days": args.duration,
        "all_day": args.all_day,
    }
    if args.calendar:
        raw["calendar"] = True
    if args.no_calendar:
        raw["calendar"] = False
    if args.task:
        raw["task"] = True
    if args.no_task:
        raw["task"] = False
    return [raw]


def main():
    p = argparse.ArgumentParser(description="把任务描述结构化为飞书写入计划")
    p.add_argument("--title")
    p.add_argument("--deadline")
    p.add_argument("--due")
    p.add_argument("--start")
    p.add_argument("--priority", help="P0/P1/P2/P3 或 紧急/高/中/低")
    p.add_argument("--project")
    p.add_argument("--milestone")
    p.add_argument("--owner")
    p.add_argument("--status", default="未开始")
    p.add_argument("--progress", type=int)
    p.add_argument("--deliverable")
    p.add_argument("--tags")
    p.add_argument("--notes")
    p.add_argument("--source", default="AI 同步")
    p.add_argument("--duration", type=int, help="工期天数，覆盖按紧急度推导的默认值")
    p.add_argument("--all-day", action="store_true", help="日历日程设为全天")
    p.add_argument("--calendar", action="store_true", help="强制创建日历日程")
    p.add_argument("--no-calendar", action="store_true")
    p.add_argument("--task", action="store_true", help="强制创建飞书待办")
    p.add_argument("--no-task", action="store_true")
    p.add_argument("--batch", help="JSON 文件，数组，每项字段同上（下划线命名）")
    p.add_argument("--json", dest="json_arg", help="内联 JSON 字符串或数组")
    p.add_argument("--today", help="覆盖今天日期 YYYY-MM-DD，便于测试")
    p.add_argument("--out", help="输出文件路径，默认 stdout")
    args = p.parse_args()

    if args.today:
        today = datetime.strptime(args.today, "%Y-%m-%d").date()
    else:
        today = datetime.now().date()

    defaults = {
        "project": args.project,
        "owner": args.owner,
        "priority": args.priority,
    }

    raws = load_raws(args)
    tasks = []
    for raw in raws:
        merged = dict(defaults)
        merged.update({k: v for k, v in raw.items() if v is not None})
        if args.batch or args.json_arg:
            merged.setdefault("project", args.project)
            merged.setdefault("owner", args.owner)
        tasks.append(build_task(merged, today, defaults))

    plan = {
        "timezone": TZ,
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "today": today.strftime("%Y-%m-%d"),
        "task_count": len(tasks),
        "tasks": tasks,
    }
    text = json.dumps(plan, ensure_ascii=False, indent=2)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            f.write(text)
        print("已写入 %s（%d 条任务）" % (args.out, len(tasks)))
    else:
        print(text)


if __name__ == "__main__":
    main()
