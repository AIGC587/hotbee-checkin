# WorkBuddy 与 HotBee 自动签到系统 · 使用手册

| 项目 | 内容 |
| --- | --- |
| 文档版本 | v2.0 |
| 更新日期 | 2026-10-19 |
| 适用仓库 | `AIGC587/hotbee-checkin`（**Public**，公开仓库的 Actions 免费不限量） |
| 本地目录 | `E:\WorkBuddy\自动签到` |
| 管理账号 | WorkBuddy 2 个 + HotBee 2 个 |

---

## 一、项目概述

本系统用于**自动完成 WorkBuddy 与 HotBee 两个平台的每日签到**，领取每日积分与旅行奖励。签到在 GitHub Actions 云端执行，不依赖本机开机；本机脚本只负责账号管理与应急操作。

### 1.1 运行架构

| 角色 | 位置 | 触发方式 | 职责 |
| --- | --- | --- | --- |
| 生产执行 | GitHub Actions | 每日定时（见 1.2） | 实际签到、领旅行奖励 |
| 账号管理 | 本机 `E:\WorkBuddy\自动签到` | 人工执行命令 | 增删账号、导出令牌、同步云端配置 |
| 凭据存储 | 本机 `C:\Users\aisys\.workbuddy` | — | 账号令牌、GitHub 访问令牌 |

本机**不设任何定时任务**，所有自动签到均由云端完成。

### 1.2 定时计划（北京时间）

| 工作流 | 主跑 | 兜底 | 说明 |
| --- | --- | --- | --- |
| `workbuddy-checkin.yml` | 00:05 | 12:10 | 签到 + 派猫猫旅行 |
| `hotbee-checkin.yml` | 00:05 | 12:00 | 签到 |

GitHub 的定时触发通常有 5–15 分钟延迟，属正常现象。

### 1.3 账号清单

| 别名 | 平台 | 账号标识 | 备注 |
| --- | --- | --- | --- |
| `main` | WorkBuddy | `3a676ad9` | 主号，客户端当前登录 |
| `alt1` | WorkBuddy | `4494bc02` | 小号 |
| `hb1` | HotBee | `152****2587`（id 4620） | — |
| `hb2` | HotBee | `198****2587`（id 4623） | — |

> 两个平台的积分按账号独立记账，**不存在跨账号合并**。本系统只做「逐号签到」。

---

## 二、具体怎么用

### 2.1 三条核心命令

所有命令在 `E:\WorkBuddy\自动签到` 目录下执行。

```bash
# 1) 查看账号清单与状态（脱敏，不含令牌）
python checkin_accounts.py list

# 2) 改完账号后，一键写入云端并立即跑一次
python checkin_accounts.py sync --run

# 3) 改完脚本或文档后，同步回 GitHub 仓库
python checkin_accounts.py upload
```

### 2.2 常用命令全集

| 场景 | 命令 |
| --- | --- |
| 查看本地账号清单 | `python checkin_accounts.py list` |
| 查看客户端当前登录哪个号 | `python checkin_accounts.py whoami` |
| 检查各账号令牌是否有效 | `python checkin_accounts.py check` |
| 本机应急补签（立即签到） | `python checkin_accounts.py run` |
| 只补某个号 | `python checkin_accounts.py run --alias main` |
| 同步账号到云端并跑一次 | `python checkin_accounts.py sync --run` |
| 同步 HotBee 账号（需声明数量） | `python checkin_accounts.py sync --with-hotbee --expect 2` |
| 上传项目文件到仓库 | `python checkin_accounts.py upload` |
| 检查 GitHub 访问令牌状态 | `python checkin_accounts.py token status` |

### 2.3 如何确认云端跑成功

1. 打开 https://github.com/AIGC587/hotbee-checkin/actions
2. 点最新一次运行，展开 `执行签到` 步骤
3. 每个账号输出一行，格式为 `[别名] [状态]`：

| 日志关键字 | 含义 | 是否需要处理 |
| --- | --- | --- |
| `[SKIP] 今日已签到` | 今天已经签过（幂等跳过） | 否 |
| `[OK] 签到成功` | 本次领取成功 | 否 |
| `[TRAVEL]` | 派猫猫旅行状态 | 否 |
| `[AUTH]` | 令牌失效 | **是**，见第三章 |
| `[FAIL]` | 接口异常 | 连续出现才需处理 |

### 2.4 本机应急补签

云端失败而当天需要立即签到时使用（不影响云端逻辑，重复执行无副作用）：

```bash
python checkin_accounts.py run
```

---

## 三、过期了怎么办

本系统有**三类凭据**会过期，处理方式各不相同。判断依据是报错位置，不是日期。

### 3.1 长效令牌过期（WorkBuddy 账号）

**症状**：云端日志出现 `[AUTH] 长效令牌刷新失败`；或本机 `check` 返回 auth 错误。

**原因**：WorkBuddy 长效令牌有效期约 30 天。正常运行时每次签到会自动续期，因此**只有连续 30 天以上未运行时才会真的过期**。

**处理**：重新导出一次即可，其余账号不受影响。

```bash
# 第 1 步：确认客户端登录的是哪个号（切号会中断当前对话，建议新开一个对话操作）
python checkin_accounts.py whoami

# 第 2 步：重新导出该号（--sync 会同时写入云端 Secret 并触发一次运行）
python checkin_accounts.py add --alias main --from-client --sync
```

若失效的是 `alt1`，先把 WorkBuddy 客户端切换到小号登录，再执行上述命令。

### 3.2 GitHub 访问令牌（PAT）过期

**症状**：`sync` 返回 HTTP 401 / 403，提示 `Bad credentials` 或 `Resource not accessible`。

**当前令牌**：名称 `checkin-sync`，失效日期 **2027-01-17**。

**处理**：重新生成并覆盖本机文件。

1. 打开 https://github.com/settings/personal-access-tokens/new
2. 配置如下：

| 项目 | 值 |
| --- | --- |
| Token name | `checkin-sync` |
| Expiration | 90 天或自定义 |
| Repository access | Only select repositories → `AIGC587/hotbee-checkin` |
| Permissions | Contents: Read and write；Secrets: Read and write；Actions: Read and write |

3. 复制生成的 `github_pat_...`
4. 存入本机（输入不回显）：

```bash
python checkin_accounts.py token set
```

5. 验证：

```bash
python checkin_accounts.py sync
```

返回 `"status": "ok"` 即恢复。

### 3.3 HotBee 登录态过期

**症状**：云端日志出现 `[AUTH] 登录态失效`；本机 `check` 该号返回「用户未登录」。

**原因**：HotBee 没有刷新接口，token 由浏览器会话维持（约两周量级）。浏览器仍在登录时，令牌会自动更新；云端拿的是旧副本，过期即失效。

**处理（一条命令，推荐）**：

```bash
python checkin_accounts.py hotbee-fix            # 抓令牌 → 校验 → 写入云端 → 触发签到
python checkin_accounts.py hotbee-fix --dry-run  # 只看浏览器里有哪些可用号
```

- 浏览器仍登录的账号会被自动修复，输出里 `sync.ok=true` 即成功，`run.conclusion=success` 表示云端已跑完。
- 输出含 `missing_local` 时，说明这些号连浏览器登录态也丢了 → 按下面第 1 步登录后重跑同一条命令即可。
- 想少一步：`--no-run` 只写云端不触发运行。

**自动自愈（已内置）**：开机守护 `wb_boot_sync.py` 现在每轮都会校验 HotBee 令牌，发现失效就自动执行上面这套流程（失败间隔 6 小时，不会刷屏）。前提是浏览器里还留着登录态；浏览器也掉线时才需要人工登录一次。

**手动兜底（老流程，仍可用）**：

```bash
python import_hotbee.py --dry-run   # 先确认真能读到号
python import_hotbee.py             # 写入本地
python checkin_accounts.py sync --with-hotbee --expect N --run   # N=本地实际账号数
```

> `--expect` 是防呆：数量不符会中止，避免把云端账号挤掉。用 `hotbee-fix` 可跳过这个参数。

**跨设备提醒**：令牌只在浏览器所在机器上更新。长期不开机时云端会持续失败（GitHub 会发失败邮件），回来后跑一次 `hotbee-fix` 即可。

### 3.4 GitHub 定时任务被停用

**症状**：Actions 列表连续多日无新运行记录。

**原因**：仓库连续 60 天没有提交，GitHub 会自动停用 schedule。

**处理**：进入 Actions 页面点「Enable workflow」，或执行任意一次 `upload` 产生提交。

### 3.5 任务 2 秒失败、日志为空（Actions 额度）

**症状**：每次运行都 `failure`，点进去看不到任何步骤，`runner_id` 为 0，耗时只有 2 秒左右；两个 workflow 同时挂。

**原因**：GitHub 没有分配运行器。私有仓库每月只有 2000 分钟免费额度，用尽或账户账单受限时，任务会直接不启动——不是脚本报错。

**处理**：把仓库设为 **Public**。公有仓库的 GitHub Actions 免费且不限量，本仓库内不含任何密钥（令牌都在 Secrets 里）。

> 2026-11-14 实际发生过一次：11-08 之后所有运行全部 2 秒失败，改 Public 后立即恢复（run #174 起正常）。

**检查是否为该问题**：

```bash
python checkin_accounts.py -h >/dev/null   # 任意命令确认脚本可跑
# 然后看运行详情里有没有步骤；没有步骤就是额度问题
```

### 3.6 快速对照表

| 报错 / 现象 | 凭据类型 | 处理章节 |
| --- | --- | --- |
| `[AUTH] 长效令牌刷新失败` | WorkBuddy 长效令牌 | 3.1 |
| `sync` 返回 401 / 403 | GitHub PAT | 3.2 |
| `sync` 返回 404 | PAT 未勾选该仓库 | 3.2 |
| `[AUTH] 登录态失效` | HotBee token | 3.3 |
| Actions 无新记录 | 定时任务被停用 | 3.4 |
| 运行 2 秒失败、无任何步骤 | Actions 额度（仓库必须 Public） | 3.5 |

---

## 四、以后加号怎么加

### 4.1 WorkBuddy 加号（全自动，三步）

**第 1 步**：将 WorkBuddy 客户端切换到待添加账号并登录。

> 切号会导致当前对话中断，建议**新开一个对话**再操作。

**第 2 步**：在项目目录执行一条命令：

```bash
python checkin_accounts.py add --alias 别名 --from-client --sync
```

| 参数 | 说明 |
| --- | --- |
| `--alias` | 账号短名，建议英文小写（`main`、`alt1`、`work`），会出现在云端日志与缓存文件名中 |
| `--from-client` | 从本机登录态读取令牌 |
| `--sync` | 自动写入 GitHub Secret 并触发一次云端运行 |

该命令完成四件事：读取令牌 → 写入本地账号库 → 覆盖云端 `WB_ACCOUNTS` 全量名单 → 触发云端验证。

**第 3 步**：检查返回值中 `cloud_sync.ok` 与 `cloud_sync.run.ok` 均为 `true` 即成功。

> **注意**：云端只认完整名单，因此每次都整份覆盖。**不要**手动拼接 JSON 后只提交新增账号，否则其余账号会被挤掉。

### 4.2 HotBee 加号（需登录一次）

1. 在 WorkBuddy 内置浏览器打开 `https://hotbee.cn`，登录新账号
2. `python import_hotbee.py --dry-run` 确认账号数量已增加
3. `python import_hotbee.py` 写入本地
4. `python checkin_accounts.py sync --with-hotbee --expect <新的总数>`

`--expect` 与实际数量不符时命令会中止，这是防止误覆盖的保护机制，不是故障。

### 4.3 删除账号

```bash
python checkin_accounts.py remove --alias 别名
python checkin_accounts.py sync --run
```

`sync` 会将剩余账号整份重写进云端，被删账号自然消失。

### 4.4 账号数量建议

当前 4 个，规划上限 5 个。建议只添加实际在用的账号：

- 每增加一个账号，就多一份凭据存放在网络侧，泄露面扩大；
- 平台对多账号签到存在风控，账号越多越易被整体限制；
- 积分按账号独立计算，增加账号不会提升单个账号的收益。

---

## 五、文件与目录说明

| 路径 | 作用 |
| --- | --- |
| `checkin_accounts.py` | 账号管理器：增删账号、生成名单、同步云端、上传文件 |
| `import_hotbee.py` | 从浏览器 localStorage 导入 HotBee 账号 |
| `wb_checkin.py` | 云端 WorkBuddy 签到脚本（GitHub Actions 调用） |
| `checkin.mjs` | 云端 HotBee 签到脚本（GitHub Actions 调用） |
| `cloudflare-worker.mjs` | HotBee 备用方案（Cloudflare Cron），当前未启用 |
| `.github/workflows/` | 两个定时任务定义 |
| `C:\Users\aisys\.workbuddy\accounts\` | 账号令牌文件（每账号一份） |
| `C:\Users\aisys\.workbuddy\gh_token` | GitHub 访问令牌 |
| `C:\Users\aisys\.workbuddy\checkin-accounts.json` | 账号索引（不含令牌明文） |

---

## 六、备份

| 备份对象 | 位置 | 要求 |
| --- | --- | --- |
| 项目文件 | `E:\WorkBuddy\自动签到` | 直接复制；仓库中另有副本 |
| 账号令牌 | `C:\Users\aisys\.workbuddy\accounts` | **等同账号钥匙**，必须加密后再存放 |
| GitHub PAT | `C:\Users\aisys\.workbuddy\gh_token` | 同上 |

GitHub 上的 Secret 无法导出，丢失后执行 `sync` 从本机重新写入即可。

---

## 七、本手册如何维护与更新

本文件与代码同属一个项目，**本地是主副本，GitHub 是备份**。

### 7.1 更新流程

1. 用任意编辑器修改本地文件 `E:\WorkBuddy\自动签到\WorkBuddy与HotBee自动签到-使用手册.md`
2. 更新文首的「文档版本」与「更新日期」
3. 同步到仓库：

```bash
python checkin_accounts.py upload --message "docs: 更新使用手册"
```

4. 到仓库确认：https://github.com/AIGC587/hotbee-checkin/blob/main/WorkBuddy与HotBee自动签到-使用手册.md

### 7.2 需要注意的限制

- `upload` 只同步文件内容，**不会自动同步删除操作**。删除仓库文件需显式指定：
  ```bash
  python checkin_accounts.py upload --delete 文件名 --message "移除 xxx"
  ```
- `.github/workflows/` 下的两个定时任务文件被 `upload` 默认跳过（GitHub 要求单独的 Workflows 权限）。修改定时计划请直接在网页编辑器操作。
- 仓库中的副本仅供查阅与备份，**不要在网页端和本地两端同时修改同一文件**，否则后上传的会覆盖先前的。

### 7.3 变更记录

| 版本 | 日期 | 变更内容 |
| --- | --- | --- |
| v2.0 | 2026-10-19 | 重写为正式使用手册；合并「使用方法 / 过期处理 / 加号流程」三大章节；补充文档维护说明 |
| v1.x | 2026-10-19 | 早期口语化说明（已作废） |
