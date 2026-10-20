/**
 * Cloudflare Worker —— 签到准点触发器
 *
 * 作用：每天两个时间点准点调用 GitHub API 手动触发 AIGC587/hotbee-checkin
 * 仓库里的两个签到工作流，绕过 GitHub 定时任务的排队延迟：
 *   - UTC 16:05 = 北京 00:05  → 触发后脚本在窗口内随机延迟，实际签到 00:05~00:55 之间
 *   - UTC 04:10 = 北京 12:10  → 实际签到 12:10~13:00 之间（"12:30 左右"）
 * 工作流内部带「今日已签成功」标记：当天已签过时，后续运行直接结束、不访问平台。
 *
 * 部署（Dashboard 方式，全程无需安装工具）:
 *   1. Cloudflare Dashboard → Workers & Pages → Create Worker
 *   2. 粘贴本文件全部代码，Deploy
 *   3. Settings → Variables and Secrets → 添加两个 Secret：
 *        GH_PAT       = GitHub 细粒度令牌（需对该仓库有 Actions: Read and write 权限）
 *        TRIGGER_KEY  = 任意一串随机字符（网页手动触发测试用的口令）
 *   4. Settings → Triggers → Cron Triggers → 添加两条（均为 UTC）：
 *        "5 16 * * *"  和  "10 4 * * *"
 *   5. 测试：浏览器访问 https://<worker域名>/?key=<TRIGGER_KEY>
 *      返回两个工作流的触发结果，204=成功；同时到 GitHub Actions 页面
 *      应能看到两条 workflow_dispatch 运行。
 *
 * 安全说明：GH_PAT 只存在 Cloudflare Secret 里，不出现在代码和日志中；
 * 网页触发需要 TRIGGER_KEY 口令，防止陌生人乱触发（签到本身幂等，风险也仅是浪费次数）。
 */

const GH = "https://api.github.com";
const OWNER = "AIGC587";
const REPO = "hotbee-checkin";
const REF = "main";
const WORKFLOWS = ["hotbee-checkin.yml", "workbuddy-checkin.yml"];

async function dispatchOne(wf, pat) {
  const res = await fetch(
    `${GH}/repos/${OWNER}/${REPO}/actions/workflows/${wf}/dispatches`,
    {
      method: "POST",
      headers: {
        Authorization: `Bearer ${pat}`,
        Accept: "application/vnd.github+json",
        "Content-Type": "application/json",
        "User-Agent": "checkin-dispatcher",
        "X-GitHub-Api-Version": "2022-11-28",
      },
      // via_cf=true 让工作流启用「窗口内随机延迟」；手动触发 GitHub 页面时默认不延迟
      body: JSON.stringify({ ref: REF, inputs: { via_cf: "true" } }),
    }
  );
  // 204 = 触发成功；401/403 = PAT 无效或权限不足；404 = 工作流文件名不对
  return { workflow: wf, status: res.status, ok: res.status === 204 };
}

async function dispatchAll(env) {
  if (!env.GH_PAT) return { ok: false, error: "缺少 Secret: GH_PAT" };
  const results = [];
  for (const wf of WORKFLOWS) {
    results.push(await dispatchOne(wf, env.GH_PAT));
  }
  return { ok: results.every((r) => r.ok), results };
}

export default {
  // 两个定时点（UTC）：16:05 = 北京 00:05；04:10 = 北京 12:10
  async scheduled(_event, env, ctx) {
    const out = await dispatchAll(env);
    console.log(JSON.stringify(out));
    if (!out.ok) throw new Error(`触发失败: ${JSON.stringify(out)}`);
  },

  // 网页手动触发（测试用）：https://<worker>/?key=<TRIGGER_KEY>
  async fetch(request, env) {
    const url = new URL(request.url);
    if (!env.TRIGGER_KEY || url.searchParams.get("key") !== env.TRIGGER_KEY) {
      return new Response(JSON.stringify({ ok: false, error: "需要 ?key= 口令" }), {
        status: 401,
        headers: { "Content-Type": "application/json; charset=utf-8" },
      });
    }
    const out = await dispatchAll(env);
    return new Response(JSON.stringify(out, null, 2), {
      headers: { "Content-Type": "application/json; charset=utf-8" },
    });
  },
};
