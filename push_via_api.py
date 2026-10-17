#!/usr/bin/env python3
"""
通过 GitHub Git Data API 创建提交并更新分支引用。

用于 git push 走不通（代理拦截 github.com）但 api.github.com 可达的场景。
"""

import base64
import json
import os
import subprocess
import sys

REPO = "/Users/fooktong/Downloads/clash-ruler"
GH = "/opt/homebrew/bin/gh"
R = "repos/FookTong-Chan/clash-ruler"


def gh(*args, payload=None):
    cmd = [GH, "api"] + list(args)
    if payload is not None:
        cmd += ["--input", "-"]
    r = subprocess.run(cmd, capture_output=True, text=True,
                       input=json.dumps(payload) if payload is not None else None)
    if r.returncode != 0:
        raise RuntimeError(f"{' '.join(args)} 失败：{(r.stderr or r.stdout)[:300]}")
    return json.loads(r.stdout) if r.stdout.strip() else {}


def main():
    os.chdir(REPO)

    # 1. 远端 main 当前 commit 与 tree
    ref = gh(f"{R}/git/ref/heads/main")
    base_commit = ref["object"]["sha"]
    commit = gh(f"{R}/git/commits/{base_commit}")
    base_tree = commit["tree"]["sha"]
    print(f"远端 main: {base_commit[:7]}  tree={base_tree[:7]}")

    # 2. 本地 HEAD 与远端差异
    diff = subprocess.run(
        ["git", "diff", "--name-status", base_commit, "HEAD"],
        capture_output=True, text=True, check=True).stdout.strip().splitlines()
    print(f"差异 {len(diff)} 项")

    tree_entries = []
    for line in diff:
        parts = line.split("\t")
        status = parts[0]
        if status.startswith("R"):
            old, new = parts[1], parts[2]
            # 删除旧路径 + 新增新路径
            tree_entries.append({"path": old, "mode": "100644", "type": "blob", "sha": None})
            path = new
        elif status.startswith("D"):
            tree_entries.append({"path": parts[1], "mode": "100644", "type": "blob", "sha": None})
            print(f"  删除 {parts[1]}")
            continue
        else:
            path = parts[1]

        with open(path, "rb") as f:
            raw = f.read()
        try:
            text = raw.decode("utf-8")
            blob = gh(f"{R}/git/blobs", payload={
                "content": text, "encoding": "utf-8"})
            print(f"  上传 {path}  ({len(raw)} B, utf-8)")
        except UnicodeDecodeError:
            blob = gh(f"{R}/git/blobs", payload={
                "content": base64.b64encode(raw).decode(), "encoding": "base64"})
            print(f"  上传 {path}  ({len(raw)} B, base64 二进制)")
        tree_entries.append({
            "path": path, "mode": "100644", "type": "blob", "sha": blob["sha"]})

    # 3. 新 tree
    new_tree = gh(f"{R}/git/trees", payload={"base_tree": base_tree, "tree": tree_entries})
    print(f"新 tree: {new_tree['sha'][:7]}")

    # 4. 新 commit
    msg = subprocess.run(
        ["git", "log", "-1", "--format=%B", "HEAD"],
        capture_output=True, text=True, check=True).stdout.strip()
    new_commit = gh(f"{R}/git/commits", payload={
        "message": msg, "tree": new_tree["sha"], "parents": [base_commit]})
    print(f"新 commit: {new_commit['sha'][:7]}")

    # 5. 更新 ref
    gh("-X", "PATCH", f"{R}/git/refs/heads/main",
       payload={"sha": new_commit["sha"], "force": False})
    print("\n✓ origin/main 已更新")

    # 6. 同步本地 remote-tracking
    subprocess.run(["git", "fetch", "origin", "main"], capture_output=True)
    st = subprocess.run(["git", "status", "-sb"], capture_output=True, text=True).stdout
    print(st.strip().splitlines()[0])


if __name__ == "__main__":
    sys.exit(main())