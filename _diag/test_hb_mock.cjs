const http = require('node:http');
const { execFileSync } = require('node:child_process');
const fs = require('node:fs');

let statusCalls = 0;
const srv = http.createServer((req, res) => {
  let body = '';
  req.on('data', (c) => (body += c));
  req.on('end', () => {
    if (req.url === '/charge/signinStatus') {
      statusCalls++;
      const signed = statusCalls > 1;
      res.setHeader('content-type', 'application/json');
      res.end(JSON.stringify({ msg: 'ok', code: 200, data: { signedIn: signed } }));
    } else if (req.url === '/charge/signin') {
      res.setHeader('content-type', 'application/json');
      res.end(JSON.stringify({ msg: 'ok', code: 200, data: { points: 1260 } }));
    } else {
      res.statusCode = 404;
      res.end('{}');
    }
  });
});

srv.listen(0, '127.0.0.1', () => {
  const port = srv.address().port;
  fs.rmSync('.hb_mock', { recursive: true, force: true });
  const baseEnv = {
    ...process.env,
    HOTBEE_API_BASE: `http://127.0.0.1:${port}`,
    HOTBEE_ACCOUNTS: JSON.stringify([{ name: 'hb1', token: 't' }]),
    HB_STATE_DIR: '.hb_mock',
  };
  const out1 = execFileSync(process.execPath, ['checkin.mjs'], { env: baseEnv, encoding: 'utf-8' });
  console.log('--- 场景1: 未签到、无历史记录 ---');
  console.log(out1.trim());

  fs.writeFileSync('.hb_mock/pts.hb1', '1250'); // 模拟昨天记录了 1250 分
  statusCalls = 99; // 状态接口恒返回"已签"
  const out2 = execFileSync(process.execPath, ['checkin.mjs'], { env: baseEnv, encoding: 'utf-8' });
  console.log('--- 场景2: 已签到、有历史记录 ---');
  console.log(out2.trim());

  srv.close();
  fs.rmSync('.hb_mock', { recursive: true, force: true });
});
