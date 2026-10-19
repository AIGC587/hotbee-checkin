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

const BASE = (process.env.HOTBEE_API_BASE || "https://www.smsz.xyz/prod-api").replace(/\/+$/, "");

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
    console.log(`${tag} [SKIP] 今日已签到`);
    return "ok";
  }

  const result = await call(token, "POST", "/charge/signin", {});
  if (isAuthExpired(result)) {
    console.log(`${tag} [AUTH] 登录态失效，需要重新取 token`);
    return "auth";
  }
  if (result.code === 200) {
    const pts = result.data?.points;
    console.log(`${tag} [OK] 签到成功${Number.isFinite(Number(pts)) ? `，当前积分 ${pts}` : ""}`);
    return "ok";
  }
  console.log(`${tag} [FAIL] 签到失败: ${result.msg ?? JSON.stringify(result).slice(0, 200)}`);
  return "fail";
}

(async () => {
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
  if (results.every((r) => r === "auth")) {
    console.error("[AUTH] 所有账号登录态失效，请更新 HOTBEE_ACCOUNTS / HOTBEE_TOKEN");
    process.exit(3);
  }
  if (results.some((r) => r === "fail" || r === "auth")) process.exit(1);
  process.exit(0);
})();
