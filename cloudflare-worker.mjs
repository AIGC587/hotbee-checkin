/**
 * Cloudflare Worker 版 HotBee 签到（免费 Cron Triggers）
 *
 * 部署:
 *   1. Cloudflare Dashboard → Workers & Pages → Create Worker
 *   2. 粘贴本文件内容，Deploy
 *   3. Settings → Variables and Secrets → 添加 Secret: HOTBEE_TOKEN
 *   4. Settings → Triggers → Cron Triggers → 添加 "5 0 * * *"（UTC，= 北京 08:05）
 */

const BASE = "https://www.smsz.xyz/prod-api";

async function call(method, path, token, body) {
  const res = await fetch(`${BASE}${path}`, {
    method,
    headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  const text = await res.text();
  try {
    return { httpStatus: res.status, ...JSON.parse(text) };
  } catch {
    return { httpStatus: res.status, code: res.status, msg: text.slice(0, 200) };
  }
}

async function run(token) {
  const st = await call("GET", "/charge/signinStatus", token);
  if (st.httpStatus === 401 || (st.code === 500 && /未登录/.test(st.msg || ""))) {
    return { ok: false, reason: "AUTH_EXPIRED", raw: st };
  }
  if (st.code !== 200) return { ok: false, reason: "STATUS_FAILED", raw: st };
  if (st.data?.signedIn) return { ok: true, reason: "ALREADY_SIGNED" };

  const r = await call("POST", "/charge/signin", token, {});
  if (r.httpStatus === 401 || (r.code === 500 && /未登录/.test(r.msg || ""))) {
    return { ok: false, reason: "AUTH_EXPIRED", raw: r };
  }
  if (r.code === 200) return { ok: true, reason: "SIGNED", points: r.data?.points };
  return { ok: false, reason: "SIGN_FAILED", raw: r };
}

export default {
  async scheduled(_event, env, ctx) {
    const out = await run(env.HOTBEE_TOKEN);
    console.log(JSON.stringify(out));
    if (!out.ok) throw new Error(`HotBee 签到失败: ${out.reason} ${JSON.stringify(out.raw || {})}`);
  },
  async fetch(_req, env) {
    const out = await run(env.HOTBEE_TOKEN);
    return new Response(JSON.stringify(out, null, 2), {
      headers: { "Content-Type": "application/json; charset=utf-8" },
    });
  },
};
