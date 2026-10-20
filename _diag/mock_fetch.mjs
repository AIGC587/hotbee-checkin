// 全局 fetch 打桩：模拟 HotBee 接口，避免真实网络请求
let statusCalls = 0;
globalThis.__mockLog = [];
globalThis.fetch = async (url, opts = {}) => {
  const u = String(url);
  const json = (obj) => ({
    status: 200,
    text: async () => JSON.stringify(obj),
  });
  if (u.endsWith('/charge/signinStatus')) {
    statusCalls++;
    globalThis.__mockLog.push(`status#${statusCalls}`);
    // 场景控制：环境变量 MOCK_SIGNED=1 表示已签
    const signed = process.env.MOCK_SIGNED === '1';
    return json({ msg: 'ok', code: 200, data: { signedIn: signed } });
  }
  if (u.endsWith('/charge/signin')) {
    globalThis.__mockLog.push('signin');
    return json({ msg: 'ok', code: 200, data: { points: 1260 } });
  }
  return json({ msg: 'not found', code: 404 });
};
