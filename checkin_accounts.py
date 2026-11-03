#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""多账号档案管理器（WorkBuddy 签到助手 · 多账号扩展）

定位：把「一个账号一个令牌文件」升级为「多账号档案 + 逐号执行」。
注意：WorkBuddy 账号按 sub（账号 UUID）隔离，积分/资产无法跨账号合并；
本脚本只做「同一台机器上管理多份令牌，按账号逐个签到」，不做任何跨号搬运。

依赖 totorosir-workbuddy-checkin 技能的 rt_auth.py / workbuddy_checkin.py，
仅复用其中的刷新、签到、旅行实现，不修改技能目录任何文件。

存储布局
  ~/.workbuddy/checkin-accounts.json      索引（别名、sub、时间；不含令牌明文）
  ~/.workbuddy/accounts/checkin-rt.<别名>.json   每账号一份，格式同 checkin-rt.json（0600）
  ~/.workbuddy/checkin-rt.json            技能默认单账号文件（use 命令可镜像）

用法
  python checkin_accounts.py whoami                      # 看当前客户端登录的是哪个号
  python checkin_accounts.py add --alias main --from-client
  python checkin_accounts.py add --alias alt2 --token-file 其他号.txt
  python checkin_accounts.py list                        # 脱敏列表
  python checkin_accounts.py run                          # 全部账号逐个签到
  python checkin_accounts.py run --alias main --no-travel
  python checkin_accounts.py check                        # 只查状态，不领取
  python checkin_accounts.py export --alias main          # 脱敏回执
  python checkin_accounts.py export --alias main --show   # 输出明文（显式）
  python checkin_accounts.py use --alias main             # 镜像到技能默认文件
  python checkin_accounts.py cloud secret --clip          # 生成 WB_ACCOUNTS（复制到剪贴板）
  python checkin_accounts.py remove --alias alt2
"""

import argparse
import base64
import json
import os
import re
import stat
import sys
import time

SKILL_SCRIPTS = os.path.join(
    os.path.expanduser("~"), ".workbuddy", "skills",
    "totorosir-workbuddy-checkin", "scripts")

HOME = os.path.expanduser("~")
WB_DIR = os.path.join(HOME, ".workbuddy")
ACC_DIR = os.path.join(WB_DIR, "accounts")
INDEX = os.path.join(WB_DIR, "checkin-accounts.json")
DEFAULT_RT = os.path.join(WB_DIR, "checkin-rt.json")

# GitHub 侧配置与凭据位置
GH_OWNER = "AIGC587"
GH_REPO = "hotbee-checkin"
GH_BRANCH = "main"
GH_TOKEN_FILE = os.path.join(WB_DIR, "gh_token")
GH_CRED_FILE = os.path.join(WB_DIR, "git-credentials")
REPO_DIR = os.path.dirname(os.path.abspath(__file__))
WORKFLOW_WB = "workbuddy-checkin.yml"
WORKFLOW_HB = "hotbee-checkin.yml"

# PyNaCl 装在隔离虚拟环境里；用主解释器跑时补一条 site-packages 兜底
_VENV_SITE = os.path.join(
    HOME, ".workbuddy", "binaries", "python", "envs", "default",
    "Lib", "site-packages")

if not os.path.isdir(SKILL_SCRIPTS):
    sys.stderr.write("未找到签到技能脚本目录：%s\n" % SKILL_SCRIPTS)
    sys.exit(2)
if SKILL_SCRIPTS not in sys.path:
    sys.path.insert(0, SKILL_SCRIPTS)

import rt_auth  # noqa: E402
import workbuddy_checkin as wc  # noqa: E402


# ---------------------------------------------------------------- 基础工具
def _chmod600(path):
    try:
        os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)
    except Exception:
        pass


def jwt_claims(tok):
    """解出 JWT payload（不验签，仅用于识别账号与有效期）。"""
    try:
        part = tok.split(".")[1]
        part += "=" * (-len(part) % 4)
        return json.loads(base64.urlsafe_b64decode(part))
    except Exception:
        return {}


def sub_of(tok):
    return str(jwt_claims(tok).get("sub") or "")


def exp_of(tok):
    return int(jwt_claims(tok).get("exp") or 0)


def fmt_ts(ts):
    if not ts:
        return "-"
    return time.strftime("%Y-%m-%d %H:%M", time.localtime(int(ts)))


def mask(tok):
    return (tok[:6] + "…" + tok[-4:]) if tok and len(tok) > 12 else "***"


def safe_alias(a):
    a = re.sub(r"[^0-9A-Za-z_\-]+", "_", (a or "").strip())
    if not a:
        raise SystemExit("别名不能为空")
    return a


def rt_path(alias):
    return os.path.join(ACC_DIR, "checkin-rt.%s.json" % alias)


# ---------------------------------------------------------------- 索引
def load_index():
    if not os.path.isfile(INDEX):
        return {"v": 1, "accounts": {}}
    try:
        with open(INDEX, "r", encoding="utf-8") as f:
            obj = json.load(f)
    except Exception:
        return {"v": 1, "accounts": {}}
    if not isinstance(obj, dict) or not isinstance(obj.get("accounts"), dict):
        return {"v": 1, "accounts": {}}
    return obj


def save_index(idx):
    os.makedirs(WB_DIR, exist_ok=True)
    with open(INDEX, "w", encoding="utf-8") as f:
        json.dump(idx, f, ensure_ascii=False, indent=2)
    _chmod600(INDEX)


def read_profile_rt(alias):
    p = rt_path(alias)
    if not os.path.isfile(p):
        return None
    try:
        with open(p, "r", encoding="utf-8") as f:
            obj = json.load(f)
        return (obj.get("rt") or "").strip() or None
    except Exception:
        return None


def write_profile_rt(alias, rt, source="manual", extra=None):
    os.makedirs(ACC_DIR, exist_ok=True)
    p = rt_path(alias)
    obj = {
        "v": 1,
        "rt": rt,
        "source": source,
        "saved_at": int(time.time()),
        "version": rt_auth.VERSION,
        "alias": alias,
        "sub": sub_of(rt),
    }
    if extra:
        obj.update(extra)
    with open(p, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)
    _chmod600(p)
    if os.name != "nt":
        try:
            os.chmod(ACC_DIR, stat.S_IRWXU)
        except Exception:
            pass
    return p


def upsert(alias, rt, source, label=None):
    """写入/更新档案，返回 (action, sub)。"""
    alias = safe_alias(alias)
    sub = sub_of(rt)
    idx = load_index()
    accs = idx["accounts"]
    # 同一账号若已在别的别名下，提示（不自动删除，避免误伤）
    dup = [a for a, m in accs.items() if m.get("sub") == sub and a != alias]
    existed = alias in accs
    write_profile_rt(alias, rt, source=source, extra={"label": label} if label else None)
    accs[alias] = {
        "sub": sub,
        "label": label or (accs.get(alias, {}) or {}).get("label") or "",
        "file": os.path.basename(rt_path(alias)),
        "saved_at": int(time.time()),
        "source": source,
        "exp": exp_of(rt),
    }
    save_index(idx)
    return ("updated" if existed else "added"), sub, dup


# ---------------------------------------------------------------- 命令
def cmd_whoami(_a):
    try:
        tok, path = rt_auth._load_local_rt()
    except Exception as e:
        print(json.dumps({"status": "error", "msg": str(e)[:300]}, ensure_ascii=False, indent=2))
        return 1
    c = jwt_claims(tok)
    print(json.dumps({
        "status": "ok",
        "client_account_sub": c.get("sub"),
        "client_account_short": str(c.get("sub") or "")[:8],
        "exp": fmt_ts(c.get("exp")),
        "auth_file": path,
        "token_masked": mask(tok),
    }, ensure_ascii=False, indent=2))
    return 0


def cmd_add(a):
    if a.from_client:
        try:
            rt, src_file = rt_auth._load_local_rt()
        except Exception as e:
            sys.stderr.write("读取本机登录态失败：%s\n" % str(e)[:300])
            return 1
        source = "client-export"
    elif a.token:
        rt, src_file, source = a.token.strip(), "-", "manual"
    elif a.token_file:
        try:
            with open(a.token_file, "r", encoding="utf-8") as f:
                rt = f.read().strip()
        except OSError as e:
            sys.stderr.write("读取令牌文件失败：%s\n" % e)
            return 1
        src_file, source = a.token_file, "file"
    else:
        sys.stderr.write("需要 --from-client 或 --token / --token-file 之一\n")
        return 1
    if not rt_auth._looks_like_token(rt):
        sys.stderr.write("令牌格式不像长效令牌（需三段式、长度>=200），已拒绝写入。\n")
        return 1
    action, sub, dup = upsert(a.alias, rt, source, label=a.label)
    out = {
        "status": "ok",
        "action": action,
        "alias": safe_alias(a.alias),
        "account_short": sub[:8],
        "exp": fmt_ts(exp_of(rt)),
        "token_masked": mask(rt),
        "file": rt_path(safe_alias(a.alias)),
        "source": source if source != "client-export" else "本机登录态导出",
    }
    if dup:
        out["warn"] = "同一账号已存在于别名 %s，确认是否重复添加" % ",".join(dup)
    if getattr(a, "sync", False):
        items, missing = build_accounts_json("wb")
        payload = json.dumps(items, ensure_ascii=False, separators=(",", ":"))
        tok = _read_gh_token()
        if tok:
            ok, msg = _put_secret("WB_ACCOUNTS", payload, tok)
            out["cloud_sync"] = {
                "secret_name": "WB_ACCOUNTS", "ok": ok,
                "accounts": [i["name"] for i in items],
                "chars": len(payload), "msg": msg, "missing": missing,
                "mode": "自动写入 GitHub",
            }
            if ok:
                ok2, msg2 = _dispatch(WORKFLOW_WB, tok)
                out["cloud_sync"]["run"] = {"ok": ok2, "msg": msg2}
        else:
            out["cloud_sync"] = {
                "secret_name": "WB_ACCOUNTS",
                "accounts": [i["name"] for i in items],
                "chars": len(payload),
                "clipboard": "已复制，粘到 GitHub Secret 即可" if _clip_text(payload) else "复制失败",
                "missing": missing,
                "mode": "未配置 PAT，退回手动粘贴",
            }
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0


def cmd_list(_a):
    idx = load_index()
    accs = idx.get("accounts", {})
    if not accs:
        print("（无档案）先运行：python checkin_accounts.py add --alias main --from-client")
        return 0
    rows = []
    for alias, m in accs.items():
        rt = read_profile_rt(alias)
        rows.append({
            "alias": alias,
            "account_short": (m.get("sub") or "")[:8] or "?",
            "label": m.get("label") or "",
            "exp": fmt_ts(m.get("exp")),
            "saved_at": fmt_ts(m.get("saved_at")),
            "token": mask(rt) if rt else "缺失",
            "file": m.get("file") or os.path.basename(rt_path(alias)),
        })
    w = [max(len(str(r[k])) for r in rows + [{"alias": "别名"}]) for k in ("alias",)]
    print("%-10s %-10s %-16s %-6s %s" % ("别名", "账号", "有效期", "令牌", "来源"))
    print("-" * 78)
    for r in rows:
        print("%-10s %-10s %-16s %-6s %s" % (
            r["alias"], r["account_short"], r["exp"], "已存" if r["token"] != "缺失" else "缺失",
            r["label"] or r["saved_at"]))

    hb = idx.get("hotbee", {})
    if hb:
        print("\nHotBee 账号：")
        print("%-10s %-16s %-8s %s" % ("别名", "手机号", "令牌", "备注"))
        print("-" * 60)
        for alias, m in hb.items():
            tok = read_hotbee_token(alias)
            print("%-10s %-16s %-8s %s" % (
                alias, m.get("phone") or "-", "已存" if tok else "缺失",
                "id=%s" % m.get("account_id") if m.get("account_id") else ""))
    total = len(rows) + len(hb)
    print("\n共 %d 个账号（WorkBuddy %d + HotBee %d；令牌各自独立，余额/积分不互通）"
          % (total, len(rows), len(hb)))
    return 0


def _run_one(alias, check_only, no_travel, location):
    rt = read_profile_rt(alias)
    if not rt:
        return {"alias": alias, "status": "error", "msg": "令牌文件缺失"}
    old_file = rt_auth.RT_FILE
    rt_auth.RT_FILE = rt_path(alias)
    try:
        travel_mode = "readonly" if (no_travel or check_only) else "auto"
        if no_travel:
            travel_mode = "off"
        res = rt_auth.run_rt(check_only=check_only, do_checkin=not check_only,
                             travel_mode=travel_mode, location_id=location)
    except Exception as e:
        res = {"status": "error", "msg": "未捕获异常: %s" % str(e)[:200], "detail": {}}
    finally:
        rt_auth.RT_FILE = old_file
    return res


def cmd_run(a):
    idx = load_index()
    aliases = [safe_alias(x) for x in a.alias] if a.alias else list(idx.get("accounts", {}))
    if not aliases:
        print("（无档案）先 add 一个账号")
        return 1
    results = []
    for al in aliases:
        t0 = time.time()
        r = _run_one(al, a.check_only, a.no_travel, a.location)
        dt = time.time() - t0
        st = r.get("status")
        tr = (r.get("travel") or {}).get("state_text") if isinstance(r.get("travel"), dict) else None
        results.append({
            "alias": al,
            "account_short": ((load_index().get("accounts", {}).get(al) or {}).get("sub") or "")[:8],
            "status": st,
            "action": r.get("action"),
            "points": r.get("points"),
            "balance": r.get("balance"),
            "travel": tr,
            "msg": (r.get("msg") or "")[:160],
            "secs": round(dt, 1),
        })
        time.sleep(0.5)
    if a.json:
        print(json.dumps({"status": "ok", "results": results}, ensure_ascii=False, indent=2))
        return 0
    print("%-8s %-9s %-6s %-8s %-8s %-8s %s" % (
        "别名", "账号", "结果", "本次积分", "余额", "旅行", "说明"))
    print("-" * 96)
    for r in results:
        print("%-8s %-9s %-6s %-8s %-8s %-8s %s" % (
            r["alias"], r["account_short"], r["status"],
            r["points"] if r["points"] is not None else "-",
            r["balance"] if r["balance"] is not None else "-",
            r["travel"] or "-", r["msg"]))
    okn = sum(1 for r in results if r["status"] == "ok")
    print("\n成功 %d / %d" % (okn, len(results)))
    return 0 if okn == len(results) else 1


def cmd_export(a):
    alias = safe_alias(a.alias)
    rt = read_profile_rt(alias)
    if not rt:
        sys.stderr.write("别名 %s 无令牌\n" % alias)
        return 1
    if a.show:
        sys.stdout.write(rt + "\n")
        return 0
    print(json.dumps({
        "status": "ok", "alias": alias, "account_short": sub_of(rt)[:8],
        "token_masked": mask(rt), "exp": fmt_ts(exp_of(rt)),
        "hint": "加 --show 可输出明文（等同账号钥匙，勿外泄）",
    }, ensure_ascii=False, indent=2))
    return 0


def cmd_use(a):
    alias = safe_alias(a.alias)
    rt = read_profile_rt(alias)
    if not rt:
        sys.stderr.write("别名 %s 无令牌\n" % alias)
        return 1
    old = rt_auth.RT_FILE
    rt_auth.RT_FILE = DEFAULT_RT
    try:
        rt_auth.save_rt(rt, source="use:%s" % alias)
    finally:
        rt_auth.RT_FILE = old
    print(json.dumps({
        "status": "ok", "action": "mirrored",
        "alias": alias, "target": DEFAULT_RT,
        "account_short": sub_of(rt)[:8],
        "note": "技能的 rt_auth.py / auto_checkin.py 通道 C 现在操作该账号",
    }, ensure_ascii=False, indent=2))
    return 0


def cmd_remove(a):
    alias = safe_alias(a.alias)
    idx = load_index()
    if alias not in idx["accounts"]:
        sys.stderr.write("别名 %s 不存在\n" % alias)
        return 1
    idx["accounts"].pop(alias, None)
    save_index(idx)
    p = rt_path(alias)
    if os.path.isfile(p):
        with open(p, "w", encoding="utf-8") as f:
            f.write("{}")   # 置空覆盖，不删文件（与技能约定一致）
        _chmod600(p)
    print(json.dumps({"status": "ok", "action": "removed", "alias": alias,
                      "note": "令牌已置空覆盖；如需彻底删除请自行删除 %s" % p},
                     ensure_ascii=False, indent=2))
    return 0


def build_accounts_json(provider="wb"):
    """按云端脚本约定的格式拼出账号数组。

    WorkBuddy: [{"name":"<别名>","rt":"<长效令牌>"}]  → secret WB_ACCOUNTS
    HotBee   : [{"name":"<别名>","token":"<32位token>"}] → secret HOTBEE_ACCOUNTS
    顺序固定为索引顺序，name 用别名（会作为 Actions 缓存文件名 rt.<name>）。
    """
    idx = load_index()
    items, missing = [], []
    key = "rt" if provider == "wb" else "token"
    source = idx.get("accounts", {}) if provider == "wb" else idx.get("hotbee", {})
    for alias in source:
        val = read_profile_rt(alias) if provider == "wb" else read_hotbee_token(alias)
        if val:
            items.append({"name": alias, key: val})
        else:
            missing.append(alias)
    return items, missing


def hotbee_path(alias):
    return os.path.join(ACC_DIR, "hotbee.%s.json" % alias)


def read_hotbee_token(alias):
    p = hotbee_path(alias)
    if not os.path.isfile(p):
        return None
    try:
        with open(p, "r", encoding="utf-8") as f:
            obj = json.load(f)
        return (obj.get("token") or "").strip() or None
    except Exception:
        return None


def upsert_hotbee(alias, token, phone=None, account_id=None):
    """HotBee 账号入库（token 为 32 位 hex，不是 JWT）。"""
    alias = safe_alias(alias)
    os.makedirs(ACC_DIR, exist_ok=True)
    token = (token or "").strip()
    if len(token) < 16:
        raise ValueError("token 长度异常")
    p = hotbee_path(alias)
    obj = {"v": 1, "token": token, "alias": alias,
           "phone": phone, "account_id": account_id,
           "saved_at": int(time.time()), "provider": "hotbee"}
    with open(p, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)
    _chmod600(p)
    idx = load_index()
    hb = idx.setdefault("hotbee", {})
    existed = alias in hb
    hb[alias] = {"phone": phone, "account_id": account_id,
                 "file": os.path.basename(p), "saved_at": int(time.time())}
    save_index(idx)
    return ("updated" if existed else "added"), safe_alias(alias)


def _clip_text(text):
    """把文本放进 Windows 剪贴板，避免明文落到终端或日志。"""
    try:
        import subprocess
        p = subprocess.run("clip", input=text.encode("utf-16le"),
                           shell=True, timeout=10)
        return p.returncode == 0
    except Exception:
        return False


def cmd_cloud(a):
    provider = (a.provider or "wb").lower()
    if provider not in ("wb", "hotbee"):
        sys.stderr.write("provider 只支持 wb / hotbee\n")
        return 1
    items, missing = build_accounts_json(provider)
    if not items:
        sys.stderr.write("没有可用账号，先 add\n")
        return 1
    payload = json.dumps(items, ensure_ascii=False, separators=(",", ":"))
    out = a.out or os.path.join(WB_DIR, "%s_accounts.secret.json" % provider)
    with open(out, "w", encoding="utf-8") as f:
        f.write(payload)
    _chmod600(out)
    if a.clip:
        clipped = _clip_text(payload)
    else:
        clipped = False
    secret_name = "WB_ACCOUNTS" if provider == "wb" else "HOTBEE_ACCOUNTS"
    print(json.dumps({
        "status": "ok",
        "provider": provider,
        "secret_name": secret_name,
        "accounts": [i["name"] for i in items],
        "chars": len(payload),
        "file": out,
        "clipboard": "已复制，可直接粘贴到 GitHub Secret 输入框" if clipped else "未复制",
        "preview_masked": "[" + ",".join(
            '{"name":"%s","%s":"%s"}' % (i["name"], "rt" if provider == "wb" else "token",
                                         mask(i["rt"] if provider == "wb" else i["token"]))
            for i in items) + "]",
        "missing": missing,
        "note": "该 JSON 含全部令牌明文，等同账号钥匙；写完 Secret 后建议删除该文件",
    }, ensure_ascii=False, indent=2))
    return 0


# ---------------------------------------------------------------- GitHub 同步
def _load_nacl():
    """懒加载 PyNaCl（只有写 Secret 才需要）。"""
    try:
        from nacl import encoding, public  # noqa
        return public, encoding
    except Exception:
        pass
    if sys.version_info[:2] == (3, 13) and os.path.isdir(_VENV_SITE):
        if _VENV_SITE not in sys.path:
            sys.path.append(_VENV_SITE)
        try:
            from nacl import encoding, public  # noqa
            return public, encoding
        except Exception:
            pass
    return None, None


def _read_gh_token():
    if not os.path.isfile(GH_TOKEN_FILE):
        return None
    try:
        with open(GH_TOKEN_FILE, "r", encoding="utf-8") as f:
            return f.read().strip() or None
    except Exception:
        return None


def _write_gh_token(tok):
    os.makedirs(WB_DIR, exist_ok=True)
    with open(GH_TOKEN_FILE, "w", encoding="utf-8") as f:
        f.write(tok.strip() + "\n")
    _chmod600(GH_TOKEN_FILE)
    try:
        import subprocess
        user = os.environ.get("USERNAME") or ""
        if user:
            subprocess.run(
                'icacls "%s" /inheritance:r /grant:r "%s:F"'
                % (GH_TOKEN_FILE, user),
                shell=True, stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL, timeout=15)
    except Exception:
        pass


def _gh_api(method, path, payload=None, token=None, timeout=25):
    import urllib.request
    import urllib.error
    url = "https://api.github.com" + path
    data = None if payload is None else json.dumps(payload).encode()
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Authorization", "Bearer " + (token or ""))
    req.add_header("Accept", "application/vnd.github+json")
    req.add_header("X-GitHub-Api-Version", "2022-11-28")
    req.add_header("Content-Type", "application/json")
    req.add_header("User-Agent", "checkin-accounts-sync")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read().decode() or "{}"
            try:
                return r.status, json.loads(raw)
            except Exception:
                return r.status, {"raw": raw[:200]}
    except urllib.error.HTTPError as e:
        try:
            body = json.loads(e.read().decode() or "{}")
        except Exception:
            body = {}
        return e.code, body


def _put_secret(name, value, token):
    """用仓库公钥做 sealed box 加密后写入 Actions Secret。"""
    public, encoding = _load_nacl()
    if public is None:
        return False, "缺少 PyNaCl，请用虚拟环境解释器运行：" + os.path.join(
            HOME, ".workbuddy", "binaries", "python", "envs", "default",
            "Scripts", "python.exe")
    st, key = _gh_api("GET", "/repos/%s/%s/actions/secrets/public-key"
                      % (GH_OWNER, GH_REPO), token=token)
    if st != 200 or "key" not in key:
        return False, "取公钥失败 HTTP %s %s" % (st, str(key)[:160])
    pk = public.PublicKey(key["key"].encode(), encoding.Base64Encoder())
    sealed = public.SealedBox(pk).encrypt(value.encode("utf-8"))
    enc = base64.b64encode(sealed).decode()
    st, body = _gh_api("PUT", "/repos/%s/%s/actions/secrets/%s"
                       % (GH_OWNER, GH_REPO, name),
                       {"encrypted_value": enc, "key_id": key["key_id"]},
                       token=token)
    if st in (201, 204):
        return True, "已写入 %s（%d 字符）" % (name, len(value))
    return False, "写入失败 HTTP %s %s" % (st, str(body)[:160])


def _dispatch(workflow, token):
    st, body = _gh_api("POST", "/repos/%s/%s/actions/workflows/%s/dispatches"
                       % (GH_OWNER, GH_REPO, workflow),
                       {"ref": GH_BRANCH}, token=token)
    return st in (204, 201), ("已触发 %s" % workflow if st in (204, 201)
                              else "触发失败 HTTP %s %s" % (st, str(body)[:160]))


def _latest_run(workflow, token):
    st, body = _gh_api(
        "GET", "/repos/%s/%s/actions/workflows/%s/runs?per_page=1"
        % (GH_OWNER, GH_REPO, workflow), token=token)
    if st != 200:
        return None
    runs = body.get("workflow_runs") or []
    return runs[0] if runs else None


def _wait_run(workflow, token, wait_s=90):
    """等最新一次运行出结论（最多 wait_s 秒）。"""
    run0 = _latest_run(workflow, token)
    target_id = run0.get("id") if run0 else None
    deadline = time.time() + wait_s
    last = run0
    while time.time() < deadline:
        time.sleep(8)
        cur = _latest_run(workflow, token)
        if not cur:
            continue
        last = cur
        if cur.get("id") != target_id or cur.get("status") == "completed":
            if cur.get("status") == "completed":
                break
    if not last:
        return None
    return {
        "status": last.get("status"),
        "conclusion": last.get("conclusion"),
        "run_number": last.get("run_number"),
        "url": last.get("html_url"),
    }


def cmd_token(a):
    if a.action == "status":
        tok = _read_gh_token()
        print(json.dumps({
            "configured": bool(tok),
            "file": GH_TOKEN_FILE,
            "token_masked": mask(tok) if tok else None,
        }, ensure_ascii=False, indent=2))
        return 0
    if a.action == "clear":
        if os.path.isfile(GH_TOKEN_FILE):
            with open(GH_TOKEN_FILE, "w", encoding="utf-8") as f:
                f.write("")
            _chmod600(GH_TOKEN_FILE)
        print(json.dumps({"status": "ok", "action": "cleared"}, ensure_ascii=False))
        return 0
    # set
    tok = ""
    if a.file:
        with open(a.file, "r", encoding="utf-8") as f:
            tok = f.read().strip()
    else:
        import getpass
        tok = getpass.getpass("粘贴 fine-grained PAT（输入不回显）：").strip()
    if len(tok) < 20:
        sys.stderr.write("令牌长度异常，已拒绝保存。\n")
        return 1
    _write_gh_token(tok)
    # 立即验证一次
    st, body = _gh_api("GET", "/repos/%s/%s" % (GH_OWNER, GH_REPO), token=tok)
    ok = (st == 200)
    print(json.dumps({
        "status": "ok" if ok else "warn",
        "saved": GH_TOKEN_FILE,
        "token_masked": mask(tok),
        "repo_access": "可访问" if ok else "HTTP %s（检查仓库范围/过期时间）" % st,
        "scopes": "该接口不返回细粒度权限，Secrets 写入会在 sync 时验证",
    }, ensure_ascii=False, indent=2))
    return 0 if ok else 1


def cmd_hotbee_fix(a):
    """一条命令自愈：从浏览器抓最新 HotBee 令牌 → 校验 → 入库 → 写云端 → 触发签到。

    典型用法（令牌过期报 [AUTH] 时）：
        python checkin_accounts.py hotbee-fix
    浏览器里已登录的账号会被自动修复；登录态也丢了的账号会列出来提示重新登录。
    """
    import import_hotbee as ih

    token = _read_gh_token()
    report = {"status": "ok", "scanned": 0, "valid": [], "dead": [],
              "missing_local": [], "sync": None, "errors": []}

    hits = {}
    for d in ih.CANDIDATE_DIRS:
        for hit in ih.scan_dir(d):
            hits.setdefault(hit["token"], hit)
    report["scanned"] = len(hits)

    by_id = {}
    for tok, hit in hits.items():
        ok, msg = ih._validate(tok)
        hit["valid"], hit["why"] = ok, msg
        key = hit.get("id") or tok
        if key not in by_id or (ok and not by_id[key]["valid"]):
            by_id[key] = hit

    valid = [h for h in by_id.values() if h["valid"]]
    dead = [h for h in by_id.values() if not h["valid"]]
    for h in valid:
        report["valid"].append({"id": h.get("id"), "phone": (h.get("phone") or "")[-4:]})
    for h in dead:
        report["dead"].append({"id": h.get("id"), "why": h.get("why")})

    if not valid:
        report["status"] = "need-login"
        report["errors"].append(
            "浏览器里没有可用的 HotBee 登录态。请先在浏览器登录 hotbee.cn，再跑本命令。")
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 2

    if a.dry_run:
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0

    # 入库：按 id 复用已有别名，新号补 hbN；同时清掉本地已失效、浏览器里也没有的账号
    idx = load_index()
    hb = idx.setdefault("hotbee", {})
    by_id_local = {str(m.get("account_id")): alias for alias, m in hb.items() if m.get("account_id")}
    used = set()
    for h in valid:
        acc = str(h.get("id") or "")
        alias = by_id_local.get(acc)
        if not alias:
            n = 1
            while ("hb%d" % n) in hb or ("hb%d" % n) in used:
                n += 1
            alias = "hb%d" % n
        used.add(alias)
        upsert_hotbee(alias, h["token"], h.get("phone"), h.get("id"))
        log_msg = "%s(%s) 已更新" % (alias, (h.get("phone") or "")[-4:])
        report.setdefault("updated", []).append(log_msg)

    idx = load_index()
    hb = idx.get("hotbee", {})
    valid_ids = {str(h.get("id") or "") for h in valid}
    for alias in list(hb.keys()):
        if alias in used:
            continue
        acc = str((hb.get(alias) or {}).get("account_id") or "")
        if acc and acc in valid_ids:
            continue
        report["missing_local"].append(alias)
        hb.pop(alias, None)
    save_index(idx)

    # 写云端 + 触发运行
    items, missing = build_accounts_json("hotbee")
    if not items:
        report["status"] = "error"
        report["errors"].append("本地没有可用 HotBee 账号，未写入云端")
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 1
    if not token:
        report["status"] = "error"
        report["errors"].append("未配置 GitHub PAT（先 token set），本地已修好但云端未更新")
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 1

    payload = json.dumps(items, ensure_ascii=False, separators=(",", ":"))
    ok, msg = _put_secret("HOTBEE_ACCOUNTS", payload, token)
    report["sync"] = {"ok": ok, "msg": msg, "accounts": [i["name"] for i in items],
                      "chars": len(payload), "missing": missing}
    if not ok:
        report["status"] = "error"
        report["errors"].append("写入 HOTBEE_ACCOUNTS 失败：%s" % msg)
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 1

    if not a.no_run:
        ok2, msg2 = _dispatch(WORKFLOW_HB, token)
        report["trigger"] = {"ok": ok2, "msg": msg2}
        if ok2:
            report["run"] = _wait_run(WORKFLOW_HB, token, wait_s=a.wait)

    if report["missing_local"]:
        report["status"] = "partial"
        report["note"] = "以下账号浏览器登录态已丢失，需重新登录后重跑本命令：%s" \
                         % ", ".join(report["missing_local"])
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["status"] in ("ok", "partial") else 1


def cmd_sync(a):
    token = _read_gh_token()
    if not token:
        sys.stderr.write(
            "未配置 PAT。先执行：python checkin_accounts.py token set\n"
            "PAT 需要：仓库 AIGC587/hotbee-checkin 的 Secrets(读写)、"
            "Actions(读写)、Contents(读写)。\n")
        return 1
    report = {"status": "ok", "secrets": [], "errors": []}
    providers = ["wb"]
    if getattr(a, "with_hotbee", False):
        hb_items, _ = build_accounts_json("hotbee")
        expect = getattr(a, "expect", None)
        if expect is None:
            report["status"] = "error"
            report["errors"].append(
                "热备保护：同步 HotBee 会整份覆盖云端名单，必须加 --expect N 声明"
                "本地应有几个号（当前本地 %d 个）" % len(hb_items))
        elif expect != len(hb_items):
            report["status"] = "error"
            report["errors"].append(
                "数量不符：--expect %d，本地实际 %d 个，已中止（防止把云端账号挤掉）"
                % (expect, len(hb_items)))
        else:
            providers.append("hotbee")
    for provider in providers:
        items, missing = build_accounts_json(provider)
        if not items:
            if provider == "hotbee":
                report["errors"].append("hotbee: 本地没有 HotBee 账号，已跳过（云端原 Secret 未动）")
                continue
            report["errors"].append("wb: 没有可用账号")
            report["status"] = "error"
            continue
        payload = json.dumps(items, ensure_ascii=False, separators=(",", ":"))
        name = "WB_ACCOUNTS" if provider == "wb" else "HOTBEE_ACCOUNTS"
        ok, msg = _put_secret(name, payload, token)
        report["secrets"].append({
            "name": name, "ok": ok, "accounts": [i["name"] for i in items],
            "chars": len(payload), "msg": msg, "missing": missing,
        })
        if not ok:
            report["status"] = "error"
    if a.run and report["status"] == "ok":
        ok, msg = _dispatch(WORKFLOW_WB, token)
        report["trigger"] = {"ok": ok, "msg": msg}
        if ok:
            report["run"] = _wait_run(WORKFLOW_WB, token, wait_s=a.wait)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["status"] == "ok" else 1


def _git(args, check=True):
    import subprocess
    p = subprocess.run(["git"] + args, cwd=REPO_DIR, capture_output=True,
                       text=True, encoding="utf-8", errors="replace")
    if check and p.returncode != 0:
        raise RuntimeError((p.stderr or p.stdout or "").strip()[:400])
    return p


UPLOAD_SKIP_DIRS = {".git", "__pycache__", ".workbuddy", "node_modules",
                    ".venv", ".idea", ".vscode", ".hb", ".wb", ".wb_local_test", "_diag",
                    ".wrangler", "_logs"}
UPLOAD_SKIP_EXT = (".pyc", ".secret.json", ".log", ".tmp")


def _iter_project_files():
    for dirpath, dirnames, filenames in os.walk(REPO_DIR):
        dirnames[:] = [d for d in dirnames if d not in UPLOAD_SKIP_DIRS]
        for name in filenames:
            if name.endswith(UPLOAD_SKIP_EXT) or name in ("Thumbs.db", ".DS_Store"):
                continue
            full = os.path.join(dirpath, name)
            rel = os.path.relpath(full, REPO_DIR).replace("\\", "/")
            yield full, rel


def _content_sha(rel, token):
    import urllib.parse
    st, body = _gh_api(
        "GET", "/repos/%s/%s/contents/%s?ref=%s"
        % (GH_OWNER, GH_REPO, urllib.parse.quote(rel), GH_BRANCH), token=token)
    if st == 200 and isinstance(body, dict):
        return body.get("sha")
    return None


def cmd_upload(a):
    """用 Contents API 把项目文件同步到仓库（本机 git 到 github.com 不通时的替代）。"""
    token = _read_gh_token()
    if not token:
        sys.stderr.write("未配置 PAT，先 token set\n")
        return 1
    import urllib.parse
    if getattr(a, "delete", None):
        removed = []
        for rel in a.delete:
            rel = rel.replace("\\", "/").lstrip("/")
            sha = _content_sha(rel, token)
            if not sha:
                removed.append({"file": rel, "ok": False, "state": "仓库中不存在"})
                continue
            st, body = _gh_api(
                "DELETE", "/repos/%s/%s/contents/%s"
                % (GH_OWNER, GH_REPO, urllib.parse.quote(rel)),
                {"message": a.message or "chore: remove %s" % rel,
                 "sha": sha, "branch": GH_BRANCH}, token=token)
            ok = st in (200, 204)
            removed.append({"file": rel, "ok": ok,
                            "state": "deleted" if ok else "HTTP %s %s" % (st, str(body)[:100])})
        print(json.dumps({"status": "ok" if all(r["ok"] for r in removed) else "partial",
                          "deleted": removed}, ensure_ascii=False, indent=2))
        return 0 if all(r["ok"] for r in removed) else 1
    files = []
    skipped_wf = 0
    for full, rel in _iter_project_files():
        if rel.startswith(".github/workflows/") and not getattr(a, "include_workflows", False):
            skipped_wf += 1
            continue
        files.append((full, rel))
    if a.dry_run:
        print(json.dumps({"status": "ok", "dry_run": True,
                          "files": [rel for _f, rel in files],
                          "skipped_workflows": skipped_wf},
                         ensure_ascii=False, indent=2))
        return 0
    results, failed = [], 0
    for full, rel in files:
        with open(full, "rb") as f:
            raw = f.read()
        payload = {
            "message": a.message or "chore: sync checkin project",
            "content": base64.b64encode(raw).decode(),
            "branch": GH_BRANCH,
        }
        sha = _content_sha(rel, token)
        if sha:
            payload["sha"] = sha
        st, body = _gh_api(
            "PUT", "/repos/%s/%s/contents/%s"
            % (GH_OWNER, GH_REPO, urllib.parse.quote(rel)),
            payload, token=token)
        ok = st in (200, 201)
        if not ok:
            failed += 1
        results.append({"file": rel, "ok": ok,
                        "state": ("created" if st == 201 else "updated" if st == 200
                                  else "HTTP %s %s" % (st, str(body)[:100]))})
    print(json.dumps({
        "status": "ok" if failed == 0 else "partial",
        "total": len(results), "failed": failed, "results": results,
        "skipped_workflows": skipped_wf,
        "note": "workflow 文件需要 PAT 额外开 Workflows 权限；默认跳过，改动请用网页编辑"
                if skipped_wf else "",
    }, ensure_ascii=False, indent=2))
    return 0 if failed == 0 else 1


def build_parser():
    p = argparse.ArgumentParser(
        description="WorkBuddy 多账号档案管理（逐号签到，不跨号合并资产）",
        formatter_class=argparse.RawDescriptionHelpFormatter, epilog=__doc__)
    sp = p.add_subparsers(dest="cmd")

    sp.add_parser("whoami", help="查看当前客户端登录的账号").set_defaults(fn=cmd_whoami)

    pa = sp.add_parser("add", help="添加/更新账号档案")
    pa.add_argument("--alias", required=True)
    pa.add_argument("--from-client", action="store_true", help="从本机登录态导出")
    pa.add_argument("--token")
    pa.add_argument("--token-file")
    pa.add_argument("--label", help="备注，如 主号/小号")
    pa.add_argument("--sync", action="store_true",
                    help="顺手生成 WB_ACCOUNTS 并复制到剪贴板（省一步）")
    pa.set_defaults(fn=cmd_add)

    sp.add_parser("list", help="脱敏列出所有账号").set_defaults(fn=cmd_list)

    pr = sp.add_parser("run", help="逐号签到（默认全部）")
    pr.add_argument("--alias", action="append")
    pr.add_argument("--check-only", action="store_true")
    pr.add_argument("--no-travel", action="store_true")
    pr.add_argument("--location", type=int)
    pr.add_argument("--json", action="store_true")
    pr.set_defaults(fn=cmd_run)

    sp.add_parser("check", help="只查状态").set_defaults(
        fn=lambda a: cmd_run(argparse.Namespace(alias=None, check_only=True,
                                                no_travel=False, location=None, json=False)))

    pe = sp.add_parser("export", help="导出某账号令牌（默认脱敏）")
    pe.add_argument("--alias", required=True)
    pe.add_argument("--show", action="store_true", help="输出明文")
    pe.set_defaults(fn=cmd_export)

    pu = sp.add_parser("use", help="把某账号镜像为技能默认账号")
    pu.add_argument("--alias", required=True)
    pu.set_defaults(fn=cmd_use)

    pd = sp.add_parser("remove", help="移除账号档案（置空令牌）")
    pd.add_argument("--alias", required=True)
    pd.set_defaults(fn=cmd_remove)

    pc = sp.add_parser("cloud", help="生成云端 GitHub Secret 用的账号 JSON")
    pc.add_argument("action", choices=["secret"])
    pc.add_argument("--provider", default="wb", choices=["wb", "hotbee"])
    pc.add_argument("--out", help="输出文件路径")
    pc.add_argument("--clip", action="store_true", help="同时复制到剪贴板")
    pc.set_defaults(fn=cmd_cloud)

    pt = sp.add_parser("token", help="管理 GitHub PAT（写入本机，不落项目）")
    pt.add_argument("action", choices=["set", "status", "clear"])
    pt.add_argument("--file", help="从文件读取令牌")
    pt.set_defaults(fn=cmd_token)

    ps = sp.add_parser("sync", help="把账号名单自动写入 GitHub Secret（可顺手跑一次）")
    ps.add_argument("--run", action="store_true", help="写完立即触发云端运行并等结果")
    ps.add_argument("--wait", type=int, default=90, help="等待运行的秒数，默认 90")
    ps.add_argument("--with-hotbee", dest="with_hotbee", action="store_true",
                    help="连 HotBee 账号一起同步（默认只同步 WorkBuddy）")
    ps.add_argument("--expect", type=int,
                    help="配合 --with-hotbee，声明本地 HotBee 账号数，防止误覆盖")
    ps.set_defaults(fn=cmd_sync)

    pf = sp.add_parser("hotbee-fix", help="HotBee 令牌失效后一条命令自愈（抓令牌→校验→写云端→触发签到）")
    pf.add_argument("--dry-run", action="store_true", help="只看浏览器里能读到哪些有效账号，不改任何东西")
    pf.add_argument("--no-run", dest="no_run", action="store_true", help="只写云端，不触发运行")
    pf.add_argument("--wait", type=int, default=120, help="等待运行结果秒数，默认 120")
    pf.set_defaults(fn=cmd_hotbee_fix)

    pu2 = sp.add_parser("upload", help="把项目文件同步到 GitHub 仓库（走 API，不依赖 git）")
    pu2.add_argument("--message", help="提交说明")
    pu2.add_argument("--dry-run", action="store_true", help="只列出要上传的文件")
    pu2.add_argument("--include-workflows", dest="include_workflows",
                     action="store_true", help="连 .github/workflows 一起传（需 PAT 有 Workflows 权限）")
    pu2.add_argument("--delete", action="append", metavar="路径",
                     help="删除仓库中的文件（可重复；只在这一侧删除不影响本地）")
    pu2.set_defaults(fn=cmd_upload)

    return p


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    p = build_parser()
    a = p.parse_args()
    if not getattr(a, "cmd", None):
        p.print_help()
        return 0
    return a.fn(a)


if __name__ == "__main__":
    sys.exit(main())
