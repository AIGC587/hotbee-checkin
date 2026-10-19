#!/usr/bin/env node
/**
 * HotBee 每日签到（纯 HTTP，无需浏览器，可跑在 GitHub Actions / Cloudflare Workers 等）
 *
 * 环境变量:
 *   HOTBEE_TOKEN     必填，浏览器 localStorage 里的 token（不带 "Bearer " 前缀也可）
 *   HOTBEE_API_BASE  可选，默认 https://www.smsz.xyz/prod-api
 *
 * 退出码: 0=成功或今日已签到  1=签到失败  2=缺少配置  3=登录态失效
 */

const BASE = (process.env.HOTBEE_API_BASE || "https://www.smsz.xyz/prod-api").replace(/\/+$/, "");
const TOKEN = (process.env.HOTBEE_TOKEN || "").trim().replace(/^Bearer\s+/i, "");

if (!TOKEN) {
  console.error("[ERROR] 缺少环境变量 HOTBEE_TOKEN");
  process.exit(2);
}

const HEADERS = {
  "Content-Type": "application/json",
  Authorization: `Bearer ${TOKEN}`,
};

async function call(method, path, body) {
  const res = await fetch(`${BASE}${path}`, {
    method,
    headers: HEADERS,
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  const text = await res.text();
  if (res.status === 401) return { httpStatus: 401, code: 401, msg: "HTTP 401" };
  let data;
  try {
    data = JSON.parse(text);
  } catch {
    return { httpStatus: res.status, code: res.status, msg: `非 JSON 响应: ${text.slice(0, 200)}` };
  }
  return { httpStatus: res.status, ...data };
}

const isAuthExpired = (r) => {
  if (r.httpStatus === 401) return true;
  const msg = String(r.msg ?? r.message ?? "");
  return r.code === 500 && /未登录|登录已?过期|token/i.test(msg);
};

async function main() {
  const status = await call("GET", "/charge/signinStatus");

  if (isAuthExpired(status)) {
    console.error("[AUTH] 登录态已失效，请重新获取 token 并更新 secret。原始响应:", JSON.stringify(status));
    process.exit(3);
  }
  if (status.code !== 200) {
    console.error("[ERROR] 查询签到状态失败:", JSON.stringify(status));
    process.exit(1);
  }
  if (status.data?.signedIn === true) {
    console.log("[SKIP] 今日已签到，无需重复操作");
    process.exit(0);
  }

  const result = await call("POST", "/charge/signin", {});

  if (isAuthExpired(result)) {
    console.error("[AUTH] 登录态已失效，请重新获取 token 并更新 secret。原始响应:", JSON.stringify(result));
    process.exit(3);
  }
  if (result.code === 200) {
    const pts = result.data?.points;
    console.log(`[OK] 签到成功${Number.isFinite(Number(pts)) ? `，当前积分 ${pts}` : ""}`);
    process.exit(0);
  }
  console.error(`[FAIL] 签到失败: ${result.msg ?? JSON.stringify(result)}`);
  process.exit(1);
}

main().catch((e) => {
  console.error("[ERROR] 请求异常:", e?.message ?? e);
  process.exit(1);
});
