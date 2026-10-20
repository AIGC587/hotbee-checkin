#!/usr/bin/env node
/**
 * HotBee 每日签到（纯 HTTP，支持多账号，无需浏览器）
 *
 * 环境变量（二选一）:
 *   HOTBEE_ACCOUNTS  JSON 数组，多账号：[{"name":"主号","token":"..."},{"name":"小号","token":"..."}]
 *   HOTBEE_TOKEN     单账号 token（向后兼容）
 *   HOTBEE_API_BASE  可选，默认 https://www.smsz.xyz/prod-api
 *
 * 退出码: 0=全部成功或已签到  1=有账号失败  2=缺少配置  3=全部登录态失效
 */

import fs from "node:fs";

const BASE = (process.env.HOTBEE_API_BASE || "https://www.smsz.xyz/prod-api").replace(/\/+$/, "");
const STATE_DIR = (process.env.HB_STATE_DIR || ".hb").replace(/\/+$/, "");

// 记录每个账号上次的积分，用于输出「积分 X → Y（+N）」
function stateFile(name) {
  const safe = String(name).replace(/[^\w.-]+/g, "_");
  return `${STATE_DIR}/pts.${safe}`;
}
function readLastPoints(name) {
  try {
    const v = Number(fs.readFileSync(stateFile(name), "utf-8").trim());
    return Number.isFinite(v) && v > 0 ? v : null;
  } catch {
    return null;
  }
}
function savePoints(name, pts) {
  const v = Number(pts);
  if (!Number.isFinite(v) || v <= 0) return;
  try {
    fs.mkdirSync(STATE_DIR, { recursive: true });
    fs.writeFileSync(stateFile(name), String(Math.floor(v)));
  } catch {}
}

// 「今日已签成功」标记（按北京时间记日期），用于后续运行直接跳过、不访问平台
function cstToday() {
  return new Date(Date.now() + 8 * 3600 * 1000).toISOString().slice(0, 10);
}
function doneMarker() {
  return `${STATE_DIR}/done-${cstToday()}`;
}
function alreadySignedToday() {
  try {
    return fs.existsSync(doneMarker());
  } catch {
    return false;
  }
}
function writeDoneMarker() {
  try {
    fs.mkdirSync(STATE_DIR, { recursive: true });
    fs.writeFileSync(doneMarker(), new Date().toISOString());
  } catch {}
}

function loadAccounts() {
  const raw = (process.env.HOTBEE_ACCOUNTS || "").trim();
  if (raw) {
    let list;
    try {
      list = JSON.parse(raw);
    } catch {
      console.error("[ERROR] HOTBEE_ACCOUNTS 不是合法 JSON");
      process.exit(2);
    }
    if (!Array.isArray(list) || list.length === 0) {
      console.error("[ERROR] HOTBEE_ACCOUNTS 必须是非空数组");
      process.exit(2);
    }
    const accounts = list
      .map((item, i) => ({
        name: (item && item.name) || `账号${i + 1}`,
        token: String((item && item.token) || "").trim().replace(/^Bearer\s+/i, ""),
      }))
      .filter((a) => a.token);
    if (accounts.length === 0) {
      console.error("[ERROR] HOTBEE_ACCOUNTS 中没有有效 token");
      process.exit(2);
    }
    return accounts;
  }

  const single = (process.env.HOTBEE_TOKEN || "").trim().replace(/^Bearer\s+/i, "");
  if (!single) {
    console.error("[ERROR] 缺少环境变量 HOTBEE_ACCOUNTS 或 HOTBEE_TOKEN");
    process.exit(2);
  }
  return [{ name: "默认账号", token: single }];
}

async function call(token, method, path, body) {
  const res = await fetch(`${BASE}${path}`, {
    method,
    headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  const text = await res.text();
  if (res.status === 401) return { httpStatus: 401, code: 401, msg: "HTTP 401" };
  try {
    return { httpStatus: res.status, ...JSON.parse(text) };
  } catch {
    return { httpStatus: res.status, code: res.status, msg: `非 JSON 响应: ${text.slice(0, 200)}` };
  }
}

const isAuthExpired = (r) => {
  if (r.httpStatus === 401) return true;
  const msg = String(r.msg ?? r.message ?? "");
  return r.code === 500 && /未登录|登录已?过期|token/i.test(msg);
};

async function runOne({ name, token }) {
  const tag = `[${name}]`;

  const status = await call(token, "GET", "/charge/signinStatus");
  if (isAuthExpired(status)) {
    console.log(`${tag} [AUTH] 登录态失效，需要重新取 token`);
    return "auth";
  }
  if (status.code !== 200) {
    console.log(`${tag} [ERROR] 查询签到状态失败: ${JSON.stringify(status).slice(0, 200)}`);
    return "fail";
  }
  if (status.data?.signedIn === true) {
    const last = readLastPoints(name);
    console.log(`${tag} [SKIP] 今日已签到${last ? `，积分（上次记录）${last}` : ""}`);
    return "ok";
  }

  const before = readLastPoints(name);
  const result = await call(token, "POST", "/charge/signin", {});
  if (isAuthExpired(result)) {
    console.log(`${tag} [AUTH] 登录态失效，需要重新取 token`);
    return "auth";
  }
  if (result.code === 200) {
    const pts = Number(result.data?.points);
    savePoints(name, pts);
    if (Number.isFinite(pts) && before) {
      console.log(`${tag} [OK] 签到成功：积分 ${before} → ${pts}（本次 +${pts - before}）`);
    } else if (Number.isFinite(pts)) {
      console.log(`${tag} [OK] 签到成功，当前积分 ${pts}`);
    } else {
      console.log(`${tag} [OK] 签到成功`);
    }
    return "ok";
  }
  console.log(`${tag} [FAIL] 签到失败: ${result.msg ?? JSON.stringify(result).slice(0, 200)}`);
  return "fail";
}

(async () => {
  // 防重复：今天已有成功签到的记录时，直接结束（不访问平台任何接口）
  if (alreadySignedToday()) {
    console.log("[SKIP-RUN] 今日已由先前的运行签到成功，本次直接结束（未访问平台）");
    process.exit(0);
  }

  // 防风控：云端运行时在窗口内随机延迟后再签到（本地手动运行不延迟）
  const maxDelay = Number(process.env.RANDOM_DELAY_MAX_SECONDS || 0);
  if (maxDelay > 0) {
    const delay = Math.floor(Math.random() * (maxDelay + 1));
    console.log(`[DELAY] 随机延迟 ${delay} 秒（约 ${Math.floor(delay / 60)} 分 ${delay % 60} 秒）后开始签到`);
    await new Promise((resolve) => setTimeout(resolve, delay * 1000));
  }

  const accounts = loadAccounts();
  const results = [];
  for (const account of accounts) {
    try {
      results.push(await runOne(account));
    } catch (e) {
      console.log(`[${account.name}] [ERROR] 请求异常: ${e?.message ?? e}`);
      results.push("fail");
    }
  }
  if (results.length > 0 && results.every((r) => r === "ok")) writeDoneMarker();
  if (results.every((r) => r === "auth")) {
    console.error("[AUTH] 所有账号登录态失效，请更新 HOTBEE_ACCOUNTS / HOTBEE_TOKEN");
    process.exit(3);
  }
  if (results.some((r) => r === "fail" || r === "auth")) process.exit(1);
  process.exit(0);
})();
