#!/usr/bin/env python3
"""登录后台守护：盯住 WorkBuddy 客户端登录态，会话一变就把新令牌同步到云端并补签。

为什么要它：
  云端 GitHub Actions 用的长效令牌是从客户端导出的，令牌绑定客户端的登录会话（JWT 里的 sid）。
  客户端重新登录 = 换会话，旧会话派生的令牌全部作废（云端报 12153 invalid_grant）。
  云端自己拿不到新令牌，只能静默失败；所以必须在本机侧、会话变化后立刻把新令牌推上去。

它做什么（幂等，可反复跑）：
  1. 等客户端登录态出现（--wait 秒，登录自启时客户端可能还没起）；
  2. 每 --interval 秒比对一次客户端与档案的会话 sid：
     - sid 变了 → 用客户端最新令牌刷新档案 + 写回 GitHub Secret（不发通知、不刷屏）；
     - 没变 → 什么都不动；
  3. 当天还没本机补签过 → 跑一次本机签到（已签到会自动跳过），写当日标记；
  4. 跑满 --watch-minutes 分钟后自行退出（0 = 常驻到注销；登录自启默认常驻，注销即回收）。

用法：
  pythonw wb_boot_sync.py             # 登录自启用这个（默认看 12 小时）
  python  wb_boot_sync.py --dry-run   # 只探测比对，不改档案、不签到、不动云端
  python  wb_boot_sync.py --once      # 只跑一轮（调试用）
  python  wb_boot_sync.py --dispatch  # 同步后额外触发一次云端运行
"""
import argparse
import base64
import datetime
import json
import os
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.abspath(__file__))
LOG_DIR = os.path.join(ROOT, "_logs")
ACC_DIR = os.path.join(os.path.expanduser("~"), ".workbuddy", "accounts")
ARCHIVE = os.path.join(ACC_DIR, "checkin-rt.main.json")
CLI = os.path.join(ROOT, "checkin_accounts.py")
STATE = os.path.join(LOG_DIR, "boot-sync-state.json")
SKILL_SCRIPTS = os.path.join(os.path.expanduser("~"), ".workbuddy", "skills",
                            "totorosir-workbuddy-checkin", "scripts")

RETRY_GAP = 1800  # 签到失败后至少隔 30 分钟再试，避免空转
_log_path = None


def log(msg):
    line = "[%s] %s" % (datetime.datetime.now().strftime("%m-%d %H:%M:%S"), msg)
    if _log_path:
        try:
            with open(_log_path, "a", encoding="utf-8") as fh:
                fh.write(line + "\n")
        except Exception:
            pass
    if sys.stdout and not sys.stdout.closed:
        try:
            print(line)
            sys.stdout.flush()
        except Exception:
            pass


def claims(tok):
    try:
        seg = tok.split(".")[1]
        seg += "=" * (-len(seg) % 4)
        return json.loads(base64.urlsafe_b64decode(seg))
    except Exception:
        return {}


def client_token():
    """从客户端登录态解出长效令牌；拿不到抛异常。"""
    if SKILL_SCRIPTS not in sys.path:
        sys.path.insert(0, SKILL_SCRIPTS)
    import rt_auth
    tok, _path = rt_auth._load_local_rt()
    return tok


def archive_token():
    try:
        with open(ARCHIVE, "r", encoding="utf-8") as fh:
            return (json.load(fh).get("rt") or "").strip()
    except Exception:
        return ""


def load_state():
    try:
        with open(STATE, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:
        return {}


def save_state(st):
    try:
        os.makedirs(LOG_DIR, exist_ok=True)
        with open(STATE, "w", encoding="utf-8") as fh:
            json.dump(st, fh, ensure_ascii=False)
    except Exception:
        pass


def cli(args, timeout=300):
    p = subprocess.run([sys.executable, CLI] + args, cwd=ROOT, capture_output=True,
                       text=True, encoding="utf-8", errors="replace", timeout=timeout)
    return p.returncode, (p.stdout or "") + (p.stderr or "")


def parse_json(text):
    start = text.find("{")
    if start < 0:
        return None
    try:
        return json.loads(text[start:])
    except Exception:
        return None


def do_checkin(alias):
    rc, out = cli(["run", "--alias", alias, "--json"])
    body = parse_json(out) or {}
    results = body.get("results") or []
    st = (results[0].get("status") if results else "?")
    bal = results[0].get("balance") if results else None
    log("本机签到：%s（余额 %s，rc=%d）" % (st, bal, rc))
    if st not in ("ok", "skip", "already"):
        log("签到明细：%s" % out.strip().replace("\n", " ")[:240])
    return st in ("ok", "skip", "already")


def do_sync(dispatch):
    args = ["sync"] + (["--run", "--wait", "120"] if dispatch else [])
    rc, out = cli(args)
    rep = parse_json(out) or {}
    sec = (rep.get("secrets") or [{}])[0]
    log("云端同步：%s（%s 字符，账号 %s）"
        % ("成功" if sec.get("ok") else "失败", sec.get("chars"), sec.get("accounts")))
    if dispatch and (rep.get("run") or rep.get("trigger")):
        log("云端触发：%s" % json.dumps(rep.get("run") or rep.get("trigger"), ensure_ascii=False))
    if not sec.get("ok"):
        log("同步输出：%s" % out.strip().replace("\n", " ")[:240])
    return bool(sec.get("ok"))


def tick(alias, dispatch, dry_run):
    try:
        tok = client_token()
    except Exception as exc:
        return {"skip": "客户端登录态不可读（%s）" % str(exc)[:80]}

    sid = str(claims(tok).get("sid") or "")
    if not sid:
        return {"skip": "令牌缺少 sid"}

    st = load_state()
    baseline = st.get("sid") or str(claims(archive_token()).get("sid") or "")
    changed = bool(baseline) and sid != baseline
    today = datetime.date.today().isoformat()
    done_today = st.get("done_date") == today
    info = {"sid": sid[:8], "changed": changed, "done_today": done_today}

    if dry_run:
        return info

    if changed:
        log("检测到会话变化：档案 sid=%s → 客户端 sid=%s"
            % ((baseline or "?")[:8], sid[:8]))
        rc, out = cli(["add", "--alias", alias, "--from-client"])
        if rc != 0:
            log("刷新档案失败：%s" % out.strip().replace("\n", " ")[:240])
            return info
        log("档案已换成客户端当前会话的令牌")

    if not done_today and (time.time() - float(st.get("last_try") or 0) >= RETRY_GAP):
        st["last_try"] = time.time()
        save_state(st)
        if do_checkin(alias):
            st["done_date"] = today
            done_today = True
            save_state(st)

    if changed:
        if do_sync(dispatch):
            st["sid"] = sid
            save_state(st)
        else:
            log("同步失败，下一轮重试")

    info["done_today"] = done_today
    return info


def main():
    global _log_path
    ap = argparse.ArgumentParser()
    ap.add_argument("--alias", default="main")
    ap.add_argument("--wait", type=int, default=300, help="启动时等客户端登录态的秒数")
    ap.add_argument("--interval", type=int, default=300, help="轮询间隔秒数")
    ap.add_argument("--watch-minutes", type=int, default=720,
                    help="守护时长（分钟），0 表示常驻直到注销")
    ap.add_argument("--dispatch", action="store_true", help="同步后触发一次云端运行")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--once", action="store_true", help="只跑一轮")
    a = ap.parse_args()

    os.makedirs(LOG_DIR, exist_ok=True)
    _log_path = os.path.join(LOG_DIR, "boot-sync-%s.log" % datetime.date.today().isoformat())
    log("=== 启动 pid=%d 守护=%s分钟 间隔=%ds ===" % (os.getpid(), a.watch_minutes, a.interval))

    end = (time.time() + a.watch_minutes * 60) if a.watch_minutes > 0 else float("inf")
    waited = 0
    first = True
    while True:
        info = tick(a.alias, a.dispatch, a.dry_run)
        if info.get("skip"):
            if first or waited % 600 == 0:
                log(info["skip"])
        else:
            log("检查：sid=%s 会话变化=%s 今日已签=%s"
                % (info["sid"], info["changed"], info["done_today"]))
        first = False
        if a.once or time.time() >= end:
            break
        time.sleep(a.interval)
        waited += a.interval

    log("=== 退出 ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
