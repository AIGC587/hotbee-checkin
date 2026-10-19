#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""从本机浏览器 localStorage 读取 HotBee 登录态，导入统一账号库。

只在两种情况下用：
  1) 新增一个 HotBee 账号（先在浏览器登录该账号，再跑本脚本）
  2) GitHub 上 HOTBEE_ACCOUNTS 丢了，需要从本机重建

原理：HotBee 的 token 存在 localStorage 的 `_https://hotbee.cn` 键里，
形如 {"token":"<32位hex>", "userInfo":{"id":..., "phoneNumber":"..."}}。
本脚本复制浏览器数据库到临时目录再解析（绕开文件锁），读完即删，不上传任何数据。

用法：
  python import_hotbee.py --dry-run      # 只看能读到几个号，不写入
  python import_hotbee.py                # 写入本地账号库
"""

import argparse
import json
import os
import re
import shutil
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import checkin_accounts as ca  # noqa: E402

HOME = os.path.expanduser("~")
CANDIDATE_DIRS = [
    os.path.join(HOME, "AppData", "Local", "CentBrowser", "User Data",
                 "Default", "Local Storage", "leveldb"),
    os.path.join(HOME, ".workbuddy", "app", "session", "Partitions",
                 "agent-browser-preview-webview", "Local Storage", "leveldb"),
]

KEY = b"_https://hotbee.cn"
TAG_TOKEN = b"\x00\x01token"
TAG_USER = b"\x00\x01userInfo"
TOKEN_RE = re.compile(rb"([0-9a-fA-F]{32})")
ID_RE = re.compile(rb'"id"\s*:\s*(\d+)')
PHONE_RE = re.compile(rb'"phoneNumber"\s*:\s*"(\d+)"')


def _parse_blob(blob, src):
    """按 Chromium localStorage 的真实存储格式解析。

    实际布局：_https://hotbee.cn \\x00\\x01 token \\x21 \\x01 <32位hex>
              _https://hotbee.cn \\x00\\x01 userInfo <varint> \\x01 {json}
    """
    found = []
    for m in re.finditer(re.escape(KEY + TAG_TOKEN), blob):
        window = blob[m.end(): m.end() + 40]
        tm = TOKEN_RE.search(window)
        if not tm:
            continue
        token = tm.group(1).decode()
        # 往后找同一条记录的 userInfo（通常紧跟其后）
        tail = blob[m.end(): m.end() + 6000]
        um = re.search(re.escape(KEY + TAG_USER), tail)
        phone = acc_id = None
        if um:
            seg = tail[um.end(): um.end() + 4000]
            pm = PHONE_RE.search(seg)
            im = ID_RE.search(seg)
            if pm:
                phone = pm.group(1).decode()
                phone = phone[-11:] if len(phone) >= 11 else phone
            if im:
                acc_id = im.group(1).decode()
        found.append({"token": token, "phone": phone, "id": acc_id, "src": src})
    return found


def scan_dir(path):
    """返回 [{token, phone, id, src}]。"""
    found = []
    if not os.path.isdir(path):
        return found
    tmp = tempfile.mkdtemp(prefix="hbscan_")
    try:
        dst = os.path.join(tmp, "db")
        shutil.copytree(path, dst)
        for name in sorted(os.listdir(dst)):
            fp = os.path.join(dst, name)
            if not os.path.isfile(fp):
                continue
            try:
                with open(fp, "rb") as f:
                    blob = f.read()
            except Exception:
                continue
            if KEY not in blob:
                continue
            found.extend(_parse_blob(blob, name))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return found


def _validate(token):
    """向 HotBee 查询签到状态，确认 token 仍然有效。"""
    import urllib.request
    import urllib.error
    url = "https://www.smsz.xyz/prod-api/charge/signinStatus"
    req = urllib.request.Request(url, method="GET")
    req.add_header("Authorization", "Bearer " + token)
    req.add_header("Content-Type", "application/json")
    req.add_header("User-Agent", "checkin-import/1.0")
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            body = json.loads(r.read().decode() or "{}")
            return body.get("code") == 200, body.get("msg") or ""
    except urllib.error.HTTPError as e:
        return False, "HTTP %s" % e.code
    except Exception as e:
        return False, str(e)[:80]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--no-validate", action="store_true",
                    help="跳过在线校验（默认会验证 token 是否还能用）")
    args = ap.parse_args()

    all_hits = {}
    for d in CANDIDATE_DIRS:
        for hit in scan_dir(d):
            all_hits.setdefault(hit["token"], hit)

    if not all_hits:
        print(json.dumps({"status": "empty",
                          "msg": "没读到 HotBee 登录态；请先在浏览器登录 hotbee.cn 再重试"},
                         ensure_ascii=False, indent=2))
        return 1

    # 同一个账号可能在多处留有新旧 token，按 id 去重并保留仍然有效的那份
    by_id = {}
    for tok, hit in all_hits.items():
        ok, msg = (True, "skip") if args.no_validate else _validate(tok)
        hit["valid"] = ok
        hit["why"] = msg
        key = hit.get("id") or tok
        if key not in by_id or (ok and not by_id[key]["valid"]):
            by_id[key] = hit

    items = [h for h in by_id.values() if h.get("valid") or args.no_validate]
    dropped = [h for h in by_id.values() if not h.get("valid")]
    items.sort(key=lambda x: x.get("phone") or "")

    out = []
    for i, it in enumerate(items, 1):
        alias = "hb%d" % i
        masked_phone = ("%s****%s" % (it["phone"][:3], it["phone"][-4:])) if it.get("phone") else "-"
        row = {"alias": alias, "phone": masked_phone, "id": it.get("id"),
               "token_valid": it.get("valid")}
        if not args.dry_run:
            action, _ = ca.upsert_hotbee(alias, it["token"], it.get("phone"), it.get("id"))
            row["action"] = action
        out.append(row)

    print(json.dumps({
        "status": "ok",
        "dry_run": args.dry_run,
        "count": len(out),
        "accounts": out,
        "dropped_invalid": [{"id": d.get("id"), "why": d.get("why")} for d in dropped],
        "next": "python checkin_accounts.py sync --with-hotbee --expect %d --run" % len(out),
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
