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
import sys
import urllib.error
import urllib.request

REFRESH_URL = "https://copilot.tencent.com/v2/plugin/auth/token/refresh"
CHECKIN_BASE = "https://www.codebuddy.cn"
TRAVEL_BASE = "https://www.workbuddy.cn"


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


def run_one(name, rt, rt_dir):
    tag = f"[{name}]"
    rt_file = os.path.join(rt_dir, f"rt.{name}") if rt_dir else ""
    if rt_file and os.path.exists(rt_file):
        saved = open(rt_file, encoding="utf-8").read().strip()
        if saved:
            rt = saved

    status, body = request(
        "POST",
        REFRESH_URL,
        {
            "Content-Type": "application/json",
            "X-Refresh-Token": rt,
            "X-Auth-Refresh-Source": "plugin",
            "X-Domain": "copilot.tencent.com",
        },
        {},
    )
    if status != 200 or body.get("code") != 0:
        print(f"{tag} [AUTH] 长效令牌刷新失败：" + json.dumps(body, ensure_ascii=False)[:200])
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
    results = []
    for name, rt in accounts:
        try:
            results.append(run_one(name, rt, rt_dir))
        except Exception as exc:
            print(f"[{name}] [ERROR] 异常：{exc}")
            results.append("fail")

    if all(r == "auth" for r in results):
        print("[AUTH] 所有账号长效令牌均失效，需要重新导出")
        return 3
    if any(r != "ok" for r in results):
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
