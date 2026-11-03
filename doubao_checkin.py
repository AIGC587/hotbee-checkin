# -*- coding: utf-8 -*-
"""豆包每日签到（Windows UI 自动化，不依赖接口/风控）。

做三件事：
  1. 确保豆包客户端在运行；没开就拉起；
  2. 用活动页地址打开内部浏览器窗口（单实例会自动转发）；
  3. 在无障碍树里找「立即签到 / 立即领取」并点击，再读页面判断结果。

结果写入 _logs/doubao-checkin.log，并输出 RESULT 行：
  SUCCESS   今天领到了
  ALREADY   今天已签过
  FAILED    失败（附原因）
退出码：0 成功/已签，1 失败。
"""
import datetime
import os
import re
import subprocess
import sys
import time

import uiautomation as auto

HERE = os.path.dirname(os.path.abspath(__file__))
EXE = r"C:\Users\aisys\AppData\Local\Doubao\Application\Doubao.exe"
CAMPAIGN = "https://www.doubao.com/member/campaign"
LOG_DIR = os.path.join(HERE, "_logs")
LOG = os.path.join(LOG_DIR, "doubao-checkin.log")


def log(msg):
    line = "[%s] %s" % (datetime.datetime.now().strftime("%m-%d %H:%M:%S"), msg)
    os.makedirs(LOG_DIR, exist_ok=True)
    try:
        with open(LOG, "a", encoding="utf-8") as fh:
            fh.write(line + "\n")
    except Exception:
        pass
    print(line, flush=True)


def doubao_running():
    out = subprocess.run(["tasklist", "/FI", "IMAGENAME eq Doubao.exe"],
                         capture_output=True, text=True, errors="replace").stdout
    return "Doubao.exe" in out


def ensure_app():
    if doubao_running():
        return True
    log("豆包未运行，尝试拉起")
    try:
        subprocess.Popen([EXE], close_fds=True)
    except Exception as exc:
        log("拉起失败：%s" % exc)
        return False
    for _ in range(30):
        time.sleep(2)
        if doubao_running():
            log("豆包已启动")
            return True
    return False


def open_campaign():
    log("打开活动页：%s" % CAMPAIGN)
    try:
        subprocess.Popen([EXE, CAMPAIGN], close_fds=True)
    except Exception as exc:
        log("打开活动页失败：%s" % exc)
        return False
    return True


def iter_controls(root, limit=6000):
    stack = [root]
    seen = 0
    while stack and seen < limit:
        ctrl = stack.pop()
        seen += 1
        yield ctrl
        try:
            for ch in ctrl.GetChildren():
                stack.append(ch)
        except Exception:
            continue


def find_targets():
    """在顶层窗口里找签到相关控件。"""
    auto.SetGlobalSearchTimeout(3)
    root = auto.GetRootControl()
    hits = []
    for win in root.GetChildren():
        try:
            if win.ControlTypeName not in ("WindowControl", "PaneControl"):
                continue
        except Exception:
            continue
        for ctrl in iter_controls(win):
            try:
                name = ctrl.Name or ""
            except Exception:
                continue
            if not name:
                continue
            if re.search(r"立即签到|立即领取|签到领", name):
                hits.append(ctrl)
            if len(hits) >= 8:
                return hits
    return hits


def text_of_window(ctrl):
    try:
        return " ".join((c.Name or "") for c in iter_controls(ctrl, 1500))
    except Exception:
        return ""


def click(ctrl):
    try:
        if ctrl.ControlTypeName in ("ButtonControl", "HyperlinkControl"):
            ctrl.GetInvokePattern().Invoke()
            return True
    except Exception:
        pass
    try:
        rect = ctrl.BoundingRectangle
        ctrl.Click(rect.left + (rect.right - rect.left) // 2,
                   rect.top + (rect.bottom - rect.top) // 2)
        return True
    except Exception:
        return False


def main():
    log("=== 豆包签到开始 ===")
    if not ensure_app():
        log("RESULT=FAILED reason=app-not-running")
        return 1

    open_campaign()
    time.sleep(8)

    deadline = time.time() + 45
    clicked = False
    while time.time() < deadline:
        hits = find_targets()
        if hits:
            for h in hits:
                try:
                    txt = h.Name
                except Exception:
                    txt = "?"
                log("找到控件：%s" % txt)
                if "已签到" in txt:
                    log("RESULT=ALREADY")
                    return 0
                if click(h):
                    clicked = True
                    log("已点击：%s" % txt)
                    time.sleep(4)
                    break
            if clicked:
                break
        time.sleep(3)

    # 复查状态
    for _ in range(6):
        hits = find_targets()
        names = [h.Name for h in hits]
        joined = " ".join(names)
        if re.search(r"已签到|签到成功|明天再来", joined):
            log("页面反馈：%s" % joined[:80])
            log("RESULT=SUCCESS" if clicked else "RESULT=ALREADY")
            return 0
        time.sleep(3)

    if not clicked:
        log("RESULT=FAILED reason=button-not-found")
        return 1
    log("RESULT=FAILED reason=result-unknown")
    return 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:
        log("异常：%s" % str(exc)[:200])
        print("RESULT=FAILED reason=exception")
        sys.exit(1)
