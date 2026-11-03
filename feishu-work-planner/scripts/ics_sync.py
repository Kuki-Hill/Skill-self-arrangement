#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ics_sync.py — Canvas iCalendar 订阅源 → 飞书任务台账计划（配合 sync.py 写入）。

Canvas 的 Calendar Feed 不需要 API token，学校关闭自助 token 也不受影响：
  Canvas → 左侧 Calendar → 右侧栏 "Calendar Feed" → 复制 .ics 链接

  python ics_sync.py --url "https://canvas.polyu.edu.hk/feeds/calendars/user_xxx.ics" \
      --project "学业" --days 60 --out /tmp/plan_ics.json
  python sync.py --plan /tmp/plan_ics.json            # 预览
  python sync.py --plan /tmp/plan_ics.json --apply    # 写入

规则：
- 只收一次性事件；带 RRULE 的重复事件（每周讲座/课表）不进入任务台账
- 紧急度按距今天数推导：≤2 天 P0，≤7 天 P1，≤14 天 P2，其余 P3
- 已过期的作业默认跳过（--include-past 可保留）
- 去重由 sync.py 的按标题查重兜底
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.request
from datetime import date, datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from intake import build_task  # noqa: E402

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

HK_TZ = timezone(timedelta(hours=8))


def unfold(text):
    """ICS 行首空格/制表符是上一行的延续。"""
    out, buf = [], ""
    for line in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        if line.startswith((" ", "\t")):
            buf += line[1:]
        else:
            if buf:
                out.append(buf)
            buf = line
    if buf:
        out.append(buf)
    return out


def parse_dt(value):
    """解析 DTSTART/DTEND 的值。返回 (datetime|date|None, is_datetime)。"""
    v = value.strip()
    m = re.match(r"^(\d{8})T(\d{6})Z$", v)
    if m:
        dt = datetime.strptime(v, "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc)
        return dt.astimezone(HK_TZ), True
    m = re.match(r"^(\d{8})T(\d{6})$", v)
    if m:
        dt = datetime.strptime(v, "%Y%m%dT%H%M%S")
        return dt.replace(tzinfo=HK_TZ), True
    m = re.match(r"^(\d{8})$", v)
    if m:
        return datetime.strptime(v, "%Y%m%d").date(), False
    return None, False


def unescape(s):
    return s.replace("\\n", "\n").replace("\\,", ",").replace("\\;", ";").replace("\\\\", "\\")


def parse_events(text):
    events = []
    cur = None
    for line in unfold(text):
        if line == "BEGIN:VEVENT":
            cur = {}
        elif line == "END:VEVENT":
            if cur is not None:
                events.append(cur)
            cur = None
        elif cur is not None and ":" in line:
            key, value = line.split(":", 1)
            key = key.split(";")[0].upper()
            if key in ("SUMMARY", "UID", "DESCRIPTION", "LOCATION", "RRULE", "DTSTART", "DTEND", "URL"):
                cur[key] = value if key in ("DTSTART", "DTEND", "RRULE") else unescape(value)
    return events


def priority_by_days(days_left):
    if days_left <= 2:
        return "P0"
    if days_left <= 7:
        return "P1"
    if days_left <= 14:
        return "P2"
    return "P3"


def fetch_ics(url):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (ics-sync)"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return resp.read().decode("utf-8", errors="replace")


def main():
    p = argparse.ArgumentParser(description="Canvas ICS → 飞书任务计划")
    p.add_argument("--url", help="Canvas Calendar Feed 的 .ics 链接")
    p.add_argument("--file", help="本地 .ics 文件路径（二选一）")
    p.add_argument("--days", type=int, default=60, help="只收未来 N 天内的事件（默认 60）")
    p.add_argument("--project", default="学业", help="写入的板块（默认 学业）")
    p.add_argument("--include-past", action="store_true", help="保留已过期的事件")
    p.add_argument("--title-prefix", default="", help="给任务标题加前缀，例如 [Canvas]")
    p.add_argument("--out", help="plan.json 输出路径，默认 stdout")
    args = p.parse_args()

    if not args.url and not args.file:
        raise SystemExit("需要 --url 或 --file")
    if args.url:
        text = fetch_ics(args.url)
        source = args.url
    else:
        with open(args.file, "r", encoding="utf-8") as f:
            text = f.read()
        source = args.file

    today = datetime.now(HK_TZ).date()
    horizon = today + timedelta(days=args.days)
    events = parse_events(text)
    skipped_recurring = 0
    skipped_old = 0

    tasks = []
    for ev in events:
        if "RRULE" in ev:
            skipped_recurring += 1
            continue
        summary = (ev.get("SUMMARY") or "").strip()
        if not summary:
            continue
        dt, is_dt = parse_dt(ev.get("DTSTART") or "")
        if dt is None:
            continue
        due = dt.date() if is_dt else dt
        if due > today + timedelta(days=args.days):
            continue
        if due < today and not args.include_past:
            skipped_old += 1
            continue
        days_left = (due - today).days
        notes_parts = []
        desc = (ev.get("DESCRIPTION") or "").strip()
        if desc:
            notes_parts.append(re.sub(r"\s+", " ", desc)[:300])
        if ev.get("LOCATION"):
            notes_parts.append("地点：" + ev["LOCATION"].strip())
        if ev.get("UID"):
            notes_parts.append("canvas-uid:" + ev["UID"].strip()[:60])
        raw = {
            "title": args.title_prefix + summary,
            "deadline": due.strftime("%Y-%m-%d"),
            "priority": priority_by_days(max(days_left, 0)),
            "project": args.project,
            "notes": "\n".join(notes_parts),
            "source": "AI 同步",
        }
        tasks.append(build_task(raw, today, {"project": args.project}))

    plan = {
        "timezone": "Asia/Shanghai",
        "generated_at": datetime.now(HK_TZ).strftime("%Y-%m-%d %H:%M:%S"),
        "today": today.strftime("%Y-%m-%d"),
        "task_count": len(tasks),
        "ics_source": source,
        "ics_stats": {
            "total_events": len(events),
            "skipped_recurring": skipped_recurring,
            "skipped_past": skipped_old,
            "window_days": args.days,
        },
        "tasks": tasks,
    }
    text_out = json.dumps(plan, ensure_ascii=False, indent=2)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            f.write(text_out)
        print("共 %d 个事件，跳过重复课 %d 条、过期 %d 条，生成任务 %d 条 → %s" %
              (len(events), skipped_recurring, skipped_old, len(tasks), args.out))
        print("下一步：python scripts/sync.py --plan %s --apply" % args.out)
    else:
        print(text_out)


if __name__ == "__main__":
    main()
