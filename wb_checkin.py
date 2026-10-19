#!/usr/bin/env python3
"""WorkBuddy 每日签到（云端版，仅标准库）
签名 + 派猫猫旅行；使用长效令牌换取接口令牌，轮换结果可回写文件。
环境变量：
  WB_REFRESH_TOKEN  长效令牌（必需，或用 WB_RT_FILE 指定的文件）
  WB_RT_FILE        可选，轮换后的长效令牌回写路径
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


def main():
    rt = (os.environ.get("WB_REFRESH_TOKEN") or "").strip()
    rt_file = (os.environ.get("WB_RT_FILE") or "").strip()
    if rt_file and os.path.exists(rt_file):
        saved = open(rt_file, encoding="utf-8").read().strip()
        if saved:
            rt = saved
    if not rt:
        print("[ERROR] 缺少长效令牌（WB_REFRESH_TOKEN）")
        return 2

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
        print("[AUTH] 长效令牌刷新失败，需要重新导出一次：" + json.dumps(body, ensure_ascii=False)[:300])
        return 3

    token = body["data"]["accessToken"]
    new_rt = body["data"].get("refreshToken") or ""
    if rt_file and new_rt and new_rt != rt:
        os.makedirs(os.path.dirname(rt_file) or ".", exist_ok=True)
        with open(rt_file, "w", encoding="utf-8") as fh:
            fh.write(new_rt)
        print("[INFO] 长效令牌已轮换并写入 " + rt_file)

    headers = {"Authorization": "Bearer " + token, "Content-Type": "application/json"}

    status, body = request("POST", CHECKIN_BASE + "/v2/billing/meter/checkin-activity-status", headers, {})
    if status in (401, 403):
        print("[AUTH] 接口令牌无效：" + json.dumps(body, ensure_ascii=False)[:200])
        return 3
    data = body.get("data") or {}
    balance = next(
        (data.get(k) for k in ("total_credits", "total_credit", "credits", "balance") if data.get(k) is not None),
        None,
    )

    if data.get("today_checked_in"):
        print(f"[SKIP] 今日已签到，连签 {data.get('streak_days', '?')} 天，积分 {balance}")
    else:
        status, body = request("POST", CHECKIN_BASE + "/v2/billing/meter/daily-checkin", headers, {})
        code = body.get("code")
        if code == 0:
            credit = body.get("credit") or (body.get("data") or {}).get("credit")
            print(f"[OK] 签到成功 +{credit} 积分，连签 {body.get('streak_days', '?')} 天")
        elif code == 10001 or "已签到" in str(body.get("msg", "")):
            print("[SKIP] 今日已签到")
        else:
            print("[FAIL] 签到失败：" + json.dumps(body, ensure_ascii=False)[:300])
            return 1

    try:
        status, body = request("GET", TRAVEL_BASE + "/activity/growth/buddy/travel/status", headers)
        tdata = body.get("data") or {}
        state = tdata.get("state")
        if state == "arrived":
            status, claim = request("POST", TRAVEL_BASE + "/activity/growth/buddy/travel/claim", headers, {})
            reward = (claim.get("data") or {}).get("reward_credit")
            print(f"[TRAVEL] 领取旅行积分：{claim.get('code')} {reward if reward is not None else ''}")
            status, body = request("GET", TRAVEL_BASE + "/activity/growth/buddy/travel/status", headers)
            tdata = body.get("data") or {}
            state = tdata.get("state")
        if state == "idle" and not tdata.get("daily_limit_reached"):
            status, depart = request(
                "POST", TRAVEL_BASE + "/activity/growth/buddy/travel/depart", headers, {"location_id": 1}
            )
            print(f"[TRAVEL] 派出 Buddy：{depart.get('code')} {depart.get('msg', '')}".rstrip())
        elif state == "traveling":
            print("[TRAVEL] 旅行中，到达后自动领取")
        elif tdata.get("daily_limit_reached"):
            print("[TRAVEL] 今日派遣已达上限")
    except Exception as exc:  # 旅行失败不影响签到结论
        print(f"[TRAVEL] 跳过（{exc}）")

    return 0


if __name__ == "__main__":
    sys.exit(main())
