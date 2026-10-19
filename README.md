# WorkBuddy / HotBee 自动签到 · 统一管理

> 看不懂术语？先看 [`项目说明.md`](项目说明.md)（大白话版）。本文是技术版。

一个项目、一套账号清单。**云端是唯一自动链路**（不依赖开机）；本机脚本只承担「加号 / 换令牌 / 应急补签」。

> 2026-10-19：本机原 00:05 的 WorkBuddy 定时任务已删除（单账号、只在开机时生效，功能被云端完全覆盖）。

## 目录

| 路径 | 作用 |
| --- | --- |
| `checkin_accounts.py` | 本机多账号管理器（唯一定义账号的地方）+ GitHub 同步 |
| `import_hotbee.py` | 从本机浏览器 localStorage 导入 HotBee 账号（可选） |
| `wb_checkin.py` | 云端 WorkBuddy 签到（GitHub Actions 运行，标准库，多账号） |
| `checkin.mjs` | 云端 HotBee 签到（Node 22，零依赖，多账号） |
| `cloudflare-worker.mjs` | HotBee 备选方案（Cloudflare Cron） |
| `.github/workflows/workbuddy-checkin.yml` | WorkBuddy 云端定时任务 |
| `.github/workflows/hotbee-checkin.yml` | HotBee 云端定时任务 |

## 账号清单（唯一来源）

本机 `~/.workbuddy/accounts/`：

| 别名 | 账号 sub | 身份 | 备注 |
| --- | --- | --- | --- |
| `main` | `3a676ad9` | WorkBuddy 主号 | 客户端当前登录 |
| `alt1` | `4494bc02` | WorkBuddy 小号 | 早期 `checkin-rt.json` 存档 |

索引：`~/.workbuddy/checkin-accounts.json`（只存别名/sub/时间，无明文令牌）。

```bash
python checkin_accounts.py list     # 脱敏查看
python checkin_accounts.py whoami   # 当前客户端登录的是哪个号
```

## 本机工具（手动触发，不常驻）

```bash
python checkin_accounts.py run --alias main    # 应急补签：立即签到 + 派猫猫
python checkin_accounts.py check               # 只读状态，不领取
python checkin_accounts.py use --alias main    # 把某号镜像为技能默认账号
```

令牌走 `rt_auth.py` 同款刷新逻辑，轮换后自动回写各自的 `checkin-rt.<别名>.json`。
本机不再挂任何定时任务，避免与云端重复。

## 云端链路（不依赖开机）

两个 workflow 各有两个 cron（北京时间 00:05 主跑 + 12:00 兜底）：

| 服务 | Secret | 脚本 |
| --- | --- | --- |
| WorkBuddy | `WB_ACCOUNTS`（**主**）/ `WB_REFRESH_TOKEN`（旧，兜底） | `wb_checkin.py` |
| HotBee | `HOTBEE_ACCOUNTS`（主）/ `HOTBEE_TOKEN`（旧，兜底） | `checkin.mjs` |

### 账号变化后如何同步到云端

一条命令（加号 → 写 Secret → 触发云端运行）：

```bash
python checkin_accounts.py add --alias xxx --from-client --sync
```

需要先在 `~/.workbuddy/gh_token` 放一个 fine-grained PAT（`token set` 写入），
权限：仓库 `AIGC587/hotbee-checkin` 的 Contents / Secrets / Actions 均读写。
没配 PAT 时 `--sync` 自动退回「生成 JSON + 复制剪贴板」手动模式。

只重写名单不同步新账号：

```bash
python checkin_accounts.py sync [--run] [--wait 90]
```

HotBee 需显式声明数量防误覆盖：

```bash
python checkin_accounts.py sync --with-hotbee --expect 2
```

> `WB_ACCOUNTS` 一旦存在，`wb_checkin.py` **只读它、忽略 `WB_REFRESH_TOKEN`**，
> 所以数组必须包含全部账号，不能只放增量。

### 代码同步（可选）

```bash
python checkin_accounts.py git-init            # 接管远端历史，不动工作区
python checkin_accounts.py push "说明"          # commit + push
```

凭据写在 `~/.workbuddy/git-credentials`（仅本仓库使用 store helper）。

## 设计要点

- **令牌轮换**：云端把轮换后的长效令牌写进 Actions 缓存 `.wb/rt.<别名>`，不落 git；
  缓存优先于 Secret，Secret 里的旧令牌只作兜底（旧令牌在轮换后仍可用一段时间）。
- **失败隔离**：单账号失败不影响其他账号；全部 auth 失败 → exit 3（触发 GitHub 失败邮件）。
- **幂等**：先查状态再领取，重复跑无副作用。
- **不合并资产**：WorkBuddy 按账号 sub 隔离记账，积分不能跨号汇总，本仓库只做「逐号签到」。

## 已知限制

- 仓库 60 天无提交，GitHub 会自动停用定时任务（会发邮件提醒）。
- `schedule` 触发常有 5–15 分钟延迟。
- Actions 缓存 7 天未访问会被清理，之后回落到 Secret 里的令牌。
- 本机与云端同时用同一账号的令牌时，以各自最新轮换结果为准；任一端报 auth 失败，重新导出一次即可。
