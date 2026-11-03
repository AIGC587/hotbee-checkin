#!/usr/bin/env python3
"""WorkBuddy 每日签到（云端版，仅标准库，支持多账号）
签到 + 派猫猫旅行；用长效令牌换取接口令牌，轮换结果按账号回写文件。

环境变量（二选一）：
  WB_ACCOUNTS       JSON 数组：[{"name":"主号","rt":"..."},{"name":"小号","rt":"..."}]
  WB_REFRESH_TOKEN  单账号长效令牌（向后兼容）
  WB_RT_DIR         可选，轮换令牌回写目录，默认 .wb
"""
import json
import os
import random
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone

REFRESH_URL = "https://copilot.tencent.com/v2/plugin/auth/token/refresh"
CHECKIN_BASE = "https://www.codebuddy.cn"
TRAVEL_BASE = "https://www.workbuddy.cn"

# 北京时间，用于「今日已签」标记的日期
CST = timezone(timedelta(hours=8))


def request(method, url, headers=None, payload=None, timeout=30):
    data = None if payload is None else json.dumps(payload).encode()
    req = urllib.request.Request(url, data=data, method=method, headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, json.loads(resp.read().decode() or "{}")
    except urllib.error.HTTPError as exc:
        body = exc.read().decode(errors="replace")
        try:
            return exc.code, json.loads(body or "{}")
        except Exception:
            return exc.code, {"raw": body[:300]}


def load_accounts():
    raw = (os.environ.get("WB_ACCOUNTS") or "").strip()
    if raw:
        try:
            items = json.loads(raw)
        except Exception:
            print("[ERROR] WB_ACCOUNTS 不是合法 JSON")
            sys.exit(2)
        if not isinstance(items, list) or not items:
            print("[ERROR] WB_ACCOUNTS 必须是非空数组")
            sys.exit(2)
        accounts = []
        for i, item in enumerate(items):
            item = item or {}
            rt = str(item.get("rt") or "").strip()
            if rt:
                accounts.append((str(item.get("name") or f"账号{i + 1}"), rt))
        if not accounts:
            print("[ERROR] WB_ACCOUNTS 中没有有效令牌")
            sys.exit(2)
        return accounts

    single = (os.environ.get("WB_REFRESH_TOKEN") or "").strip()
    if not single:
        print("[ERROR] 缺少环境变量 WB_ACCOUNTS 或 WB_REFRESH_TOKEN")
        sys.exit(2)
    return [("默认账号", single)]


def marker_path(rt_dir, name):
    """按账号记「今日已签成功」，避免一个号签完后把新增号一起挡掉。"""
    day = datetime.now(CST).strftime("%Y-%m-%d")
    safe = "".join(c if (c.isalnum() or c in "-_.") else "_" for c in str(name))
    return os.path.join(rt_dir, f"done-{day}.{safe}")


def prune_markers(rt_dir):
    """只保留最近 7 天的标记文件。"""
    try:
        keep = {(datetime.now(CST) - timedelta(days=d)).strftime("%Y-%m-%d")
                for d in range(7)}
        for fn in os.listdir(rt_dir):
            if not fn.startswith("done-"):
                continue
            day = fn[5:15]
            if day in keep:
                continue
            if len(fn) == 15:
                continue  # 老版本全局标记（done-YYYY-MM-DD），留着无害
            try:
                os.remove(os.path.join(rt_dir, fn))
            except Exception:
                pass
    except Exception:
        pass


def run_one(name, rt, rt_dir):
    tag = f"[{name}]"
    rt_file = os.path.join(rt_dir, f"rt.{name}") if rt_dir else ""

    # 该账号今天已签成功 → 本地跳过，不访问平台
    if rt_dir and os.path.exists(marker_path(rt_dir, name)):
        print(f"{tag} [SKIP-LOCAL] 今日已签到成功（本地标记），未访问平台")
        return "ok"

    # 候选顺序：缓存里轮换过的令牌优先，Secret 里的令牌兜底。
    # 这样档案刷新后即使缓存还是旧令牌，本次运行也能自愈，不必手动清缓存。
    candidates = [rt]
    if rt_file and os.path.exists(rt_file):
        saved = open(rt_file, encoding="utf-8").read().strip()
        if saved and saved != rt:
            candidates = [saved, rt]

    body = {}
    for idx, cand in enumerate(candidates):
        status, body = request(
            "POST",
            REFRESH_URL,
            {
                "Content-Type": "application/json",
                "X-Refresh-Token": cand,
                "X-Auth-Refresh-Source": "plugin",
                "X-Domain": "copilot.tencent.com",
            },
            {},
        )
        if status == 200 and body.get("code") == 0:
            rt = cand
            break
        if idx + 1 < len(candidates):
            print(f"{tag} [AUTH] 缓存令牌失效，回退到 Secret 中的令牌重试")
            continue
        print(f"{tag} [AUTH] 长效令牌刷新失败：" + json.dumps(body, ensure_ascii=False)[:200])
        if "12153" in json.dumps(body) or "invalid_grant" in json.dumps(body):
            print(f"{tag} [AUTH] 令牌背后的登录会话已被回收（客户端重新登录会换 session），"
                  f"需本机重新导出：python checkin_accounts.py add --alias {name} --from-client --sync")
        return "auth"

    token = body["data"]["accessToken"]
    new_rt = body["data"].get("refreshToken") or ""
    if rt_file and new_rt and new_rt != rt:
        os.makedirs(rt_dir, exist_ok=True)
        with open(rt_file, "w", encoding="utf-8") as fh:
            fh.write(new_rt)

    headers = {"Authorization": "Bearer " + token, "Content-Type": "application/json"}

    status, body = request("POST", CHECKIN_BASE + "/v2/billing/meter/checkin-activity-status", headers, {})
    if status in (401, 403):
        print(f"{tag} [AUTH] 接口令牌无效：" + json.dumps(body, ensure_ascii=False)[:200])
        return "auth"
    data = body.get("data") or {}
    balance = next(
        (data.get(k) for k in ("total_credits", "total_credit", "credits", "balance") if data.get(k) is not None),
        None,
    )

    result = "ok"
    if data.get("today_checked_in"):
        print(f"{tag} [SKIP] 今日已签到，连签 {data.get('streak_days', '?')} 天，积分 {balance}")
    else:
        status, body = request("POST", CHECKIN_BASE + "/v2/billing/meter/daily-checkin", headers, {})
        code = body.get("code")
        if code == 0:
            credit = body.get("credit") or (body.get("data") or {}).get("credit")
            # 复查一次状态：拿签到后的最新积分和连签天数
            after, streak = None, body.get("streak_days") or "?"
            status2, body2 = request(
                "POST", CHECKIN_BASE + "/v2/billing/meter/checkin-activity-status", headers, {}
            )
            if status2 == 200:
                d2 = body2.get("data") or {}
                after = next(
                    (d2.get(k) for k in ("total_credits", "total_credit", "credits", "balance") if d2.get(k) is not None),
                    None,
                )
                streak = d2.get("streak_days") or streak
            if after is not None and isinstance(after, int) and isinstance(balance, int):
                print(f"{tag} [OK] 签到成功：积分 {balance} → {after}（本次 +{after - balance}），连签 {streak} 天")
            else:
                print(f"{tag} [OK] 签到成功 +{credit} 积分，连签 {streak} 天")
        elif code == 10001 or "已签到" in str(body.get("msg", "")):
            print(f"{tag} [SKIP] 今日已签到")
        else:
            print(f"{tag} [FAIL] 签到失败：" + json.dumps(body, ensure_ascii=False)[:200])
            result = "fail"

    # 该账号今天签成功（含"已签到"）→ 记标记，后续运行本地跳过
    if result == "ok" and rt_dir:
        try:
            os.makedirs(rt_dir, exist_ok=True)
            with open(marker_path(rt_dir, name), "w", encoding="utf-8") as fh:
                fh.write(datetime.now(CST).isoformat())
        except Exception:
            pass

    try:
        status, body = request("GET", TRAVEL_BASE + "/activity/growth/buddy/travel/status", headers)
        tdata = body.get("data") or {}
        state = tdata.get("state")
        if state == "arrived":
            status, claim = request("POST", TRAVEL_BASE + "/activity/growth/buddy/travel/claim", headers, {})
            reward = (claim.get("data") or {}).get("reward_credit")
            print(f"{tag} [TRAVEL] 领取旅行积分：{claim.get('code')} {reward if reward is not None else ''}".rstrip())
            status, body = request("GET", TRAVEL_BASE + "/activity/growth/buddy/travel/status", headers)
            tdata = body.get("data") or {}
            state = tdata.get("state")
        if state == "idle" and not tdata.get("daily_limit_reached"):
            status, depart = request(
                "POST", TRAVEL_BASE + "/activity/growth/buddy/travel/depart", headers, {"location_id": 1}
            )
            print(f"{tag} [TRAVEL] 派出 Buddy：{depart.get('code')} {depart.get('msg', '')}".rstrip())
        elif state == "traveling":
            print(f"{tag} [TRAVEL] 旅行中，到达后自动领取")
        elif tdata.get("daily_limit_reached"):
            print(f"{tag} [TRAVEL] 今日派遣已达上限")
    except Exception as exc:  # 旅行失败不影响签到结论
        print(f"{tag} [TRAVEL] 跳过（{exc}）")

    return result


def main():
    accounts = load_accounts()
    rt_dir = (os.environ.get("WB_RT_DIR") or ".wb").strip()
    prune_markers(rt_dir)

    # 防风控：云端运行时在窗口内随机延迟后再签到（本地手动运行不延迟）
    max_delay = int(os.environ.get("RANDOM_DELAY_MAX_SECONDS") or 0)
    if max_delay > 0:
        delay = random.randint(0, max_delay)
        print(f"[DELAY] 随机延迟 {delay} 秒（约 {delay // 60} 分 {delay % 60} 秒）后开始签到")
        time.sleep(delay)

    results = []
    for name, rt in accounts:
        try:
            results.append(run_one(name, rt, rt_dir))
        except Exception as exc:
            print(f"[{name}] [ERROR] 异常：{exc}")
            results.append("fail")

    ok_names = [n for (n, _), r in zip(accounts, results) if r == "ok"]
    bad = [(n, r) for (n, _), r in zip(accounts, results) if r != "ok"]

    if not ok_names:
        if all(r == "auth" for r in results):
            print("[AUTH] 所有账号长效令牌均失效，需要重新导出")
            print("::error::所有账号令牌失效，请在本机执行 checkin_accounts.py add --from-client --sync")
            return 3
        print("::error::所有账号签到失败")
        return 1

    if bad:
        # 部分账号失败：主号成功即视为通过，失败账号降级为告警，避免每天红灯淹没真实故障
        detail = "、".join(f"{n}({r})" for n, r in bad)
        print(f"[WARN] 部分账号未成功：{detail}")
        print(f"::warning::部分账号未成功：{detail}")
    if ok_names:
        print(f"[DONE] 成功账号：{'、'.join(ok_names)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
