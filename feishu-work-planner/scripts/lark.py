#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
lark.py — 调用 lark-cli 的公共封装。

要点：
1. lark-cli 不在 PATH 上，需要把 CLI 目录拼进 PATH；
2. 无扩展名的可执行脚本在 Windows 上要用 bash 启动；
3. --json @file 的路径必须相对当前工作目录，所以调用前统一 chdir 到临时目录。
"""
from __future__ import annotations

import json
import os
import shlex
import shutil
import subprocess

BIN_DIR = r"C:/Users/Wyki/.workbuddy/binaries/node/cli-connector-packages"
EXTS = ("lark-cli.cmd", "lark-cli.exe", "lark-cli.bat", "lark-cli.ps1", "lark-cli")


def build_cmd(args):
    """构造可执行的命令列表。"""
    exe = shutil.which("lark-cli")
    if exe:
        return [exe] + args
    for name in EXTS:
        path = os.path.join(BIN_DIR, name)
        if os.path.exists(path):
            if name.endswith((".cmd", ".exe", ".bat", ".ps1")):
                return [path] + args
            # 无扩展名脚本：交给 bash 执行
            return ["bash", "-lc", "lark-cli " + shlex.join(args)]
    raise RuntimeError("找不到 lark-cli，请检查 %s" % BIN_DIR)


def run(args, cwd=None, dry=False, timeout=180):
    """执行一条 lark-cli 命令，返回 (returncode, stdout, stderr)。"""
    cmd = build_cmd(args)
    if dry:
        args = list(args) + ["--dry-run"]
        cmd = build_cmd(args)
    env = os.environ.copy()
    env["PATH"] = BIN_DIR + os.pathsep + env.get("PATH", "")
    try:
        proc = subprocess.run(
            cmd, cwd=cwd, env=env, timeout=timeout,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )
    except FileNotFoundError as exc:
        return 127, "", "无法启动命令: %s" % exc
    out = proc.stdout.decode("utf-8", errors="replace")
    err = proc.stderr.decode("utf-8", errors="replace")
    return proc.returncode, out.strip(), err.strip()


def run_json(args, cwd=None, dry=False, timeout=180):
    """执行并尝试解析 JSON 输出，失败返回 None。"""
    args = list(args) + ["--format", "json"]
    code, out, err = run(args, cwd=cwd, dry=dry, timeout=timeout)
    try:
        return code, json.loads(out), err
    except (ValueError, TypeError):
        return code, None, err


def find_all(obj, key):
    """在嵌套结构里递归收集某个 key 的所有值。"""
    found = []

    def walk(node):
        if isinstance(node, dict):
            for k, v in node.items():
                if k == key:
                    found.append(v)
                else:
                    walk(v)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(obj)
    return found
