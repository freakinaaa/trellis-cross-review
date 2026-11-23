# Trellis Cross Review

在 **Codex** 里开发 **Trellis** 项目时，自动拉起本机另外两个 AI CLI 做**两轮只读交叉评审**——全程在后台跑完，**不用手动开别的 IDE，也不用复制粘贴方案和意见**。

装一次就能在你本机**所有 Trellis 项目**通用，不会改动或污染任何业务代码库。

## 工作方式

这套技能本质上是 **Codex 主控 + 本机 Python 状态机（`scripts/review.py`）+ 两位只读外部 CLI + Trellis 本地 Channel**，不依赖打开任何外部 IDE 窗口：

```text
你在 Codex 里开发（方案批准前 / 最终验收前）
  │
  ▼
scripts/review.py gate  ──► 读任务 task.json 里的选择（未选时只问一次）
  │                         ├─ 本次自查 / 待选择 ──► 外部 CLI 调用数为 0
  │                         └─ 选了当前阶段双评 ──► 继续派发
  ▼
第 1 轮（并发独立审）   ──► 同时在后台拉起两个外部 CLI（如 qodercli + agy）
  │                         各自只读查阅 PRD、方案和关联源码，互不可见
  ▼
第 2 轮（原文互验）     ──► 脚本把双方第 1 轮完整原文直接交换给对方核查
  │                         顺带把历史未关闭的阻塞项交回原提出者复核
  ▼
确定性门禁与归档        ──► 全部回执追加写入项目本地 Trellis Channel
                            按脚本解析的硬结论汇报给 Codex（0 通过 / 1 阻塞 / 2 待复核）
```

### 几个核心机制（为什么稳、为什么不乱改代码）

1. **全程只读隔离，不打开 IDE**
   - 评审者以无头 CLI 子进程运行，通过各 CLI 的原生只读模式/权限拒绝规则限制写操作（例如 Qoder 只放行 `Read/Glob/Grep`，Antigravity 启用沙箱并拒绝写文件/命令/MCP/URL 执行）。
   - Windows 下自动读取系统代理（WinINET）透传给子进程，不会因为终端没配 `HTTP_PROXY` 而连不上网。
2. **两轮原文互验，防止“和稀泥”**
   - 第 2 轮直接交换第 1 轮原文，Codex 不会替评审者摘要或改写观点；
   - 结论由脚本独立解析末行标记（`结论：通过` / `结论：阻塞` / `结论：待复核`，自动忽略代码块里的示例文本）；标记缺失或自相矛盾一律记为 `待复核`；
   - 只有两位互验后都明确通过且未关闭阻塞为 `0`，才给出 **双评通过**；任何阻塞项修订后都必须由**原提出者**复核确认才能关闭。
3. **幂等缓存与断点恢复**
   - 每轮请求按材料内容、版本、评审者与模型生成指纹 `reqId`，原样追加记录到项目本地的 **Trellis Channel**；
   - 同一版材料重跑、或一端失败后重试时，已成功的回执直接复用（`reused=true`），不重复消耗额度。
4. **个人配置与项目记录彻底隔离（零污染业务仓库）**
   - `~/.codex/skills/trellis-cross-review/`：全局技能仓库本体，所有项目共用一套代码；
   - `~/.codex/cross-review.json` & `~/.codex/AGENTS.md`：你的个人 CLI 偏好与全局触发入口；
   - `<项目>/.trellis/tasks/<任务>/task.json` 与项目 Trellis Channel：只存当前项目的选择、评审记录和回执（均在被忽略的 `.trellis/` 下，不进业务 Git）；
   - `~/.codex/cross-review-trials/`：适配新 CLI 时使用的独立 Git worktree 与临时配置，试配失败或取消不会动到你原本的 `cross-review.json` 和安装目录 `main`。

---

## 快速安装（一句话让 Codex 自己装）

### 前置条件

- Python 3.10+（只用标准库，不需要 `pip install`）
- 已安装 **Codex** 和 **Trellis**（确认终端能跑通 `trellis channel --help`）
- 本机已安装并登录两位外部评审 CLI（内置开箱即用 **Qoder CLI** `qodercli` 和 **Antigravity CLI** `agy`；其他 AI CLI 安装时可由 Codex 自动检测、查文档并适配接入；已验证系统为 Windows）

### 安装方式：直接把下面这句话发给 Codex

复制发给 Codex，它会自己克隆或安全更新仓库，再按 [SKILL.md](SKILL.md) 的首次配置流程自动检测本机 CLI、生成配置、补全全局入口，并分别验证脚本单测和本机就绪状态：

> 帮我安装并初始化 `trellis-cross-review` 全局技能：若 `$HOME/.codex/skills/trellis-cross-review` 不存在，将 `https://github.com/freakinaaa/trellis-cross-review.git` 克隆到该路径；若目录已存在，先核对 `origin` 指向该团队仓库、当前分支为 `main` 且工作区干净，再执行 `git pull --ff-only origin main`（若 `origin`、分支不符或有未提交改动，先停下来提示我）。更新后按该技能 `SKILL.md`「首次配置与缺配引导」完成本机 CLI 检测、配置生成、全局 `AGENTS.md` 触发规则核验，并分别汇报脚本单测结果与本机就绪检查结果。

完成后**新开一个 Codex 对话**即可生效。如果你已经手动克隆过仓库，直接跟 Codex 说“按 `trellis-cross-review` 技能帮我检测 CLI 并初始化配置”就行。

<details>
<summary>想手动安装，或查看 Agent 具体会改哪两个文件？点这里展开</summary>

1. **克隆或更新仓库**：
   ```sh
   git clone "https://github.com/freakinaaa/trellis-cross-review.git" "$HOME/.codex/skills/trellis-cross-review"
   ```
   若目录已存在，先确认 `git remote get-url origin` 指向团队仓库、当前分支为 `main`，且在技能目录执行 `git status --porcelain` 输出为空，再执行 `git pull --ff-only origin main`。
2. **创建 `~/.codex/cross-review.json`**（UTF-8，Windows 下为 `C:\Users\<用户名>\.codex\cross-review.json`）：
   ```json
   {
     "reviewers": ["qoder", "agy"],
     "models": {}
   }
   ```
   - `reviewers`：两位不同的已注册评审者（当前内置 `qoder`、`agy`）。
   - `models`：指定某端模型时填 `{"qoder": "模型名"}`；留空 `{}` 沿用各 CLI 默认模型。临时想换也可以在聊天里直接告诉 Codex 覆盖。
3. **核对 `~/.codex/AGENTS.md` 的全局触发入口**：
   ```markdown
   ## Trellis 交叉评审
   在存在 `.trellis/tasks/` 的项目中，提交方案给用户批准前和实施最终全范围验收前，按全局技能 `trellis-cross-review` 执行交叉评审入口。
   ```
   - 标题和完整触发正文都已在文件里：保持原文件不变。
   - 只有 `## Trellis 交叉评审` 空标题或正文残缺：直接在该标题下方补全正文，不产生重复标题。
   - 两者都缺失：在文件末尾追加完整两行，不动原有内容。
4. **分开验证“脚本单测”和“本机就绪”**：
   - **脚本单测**：在技能目录执行 `python -B -m unittest discover -s tests -v`（只验证脚本逻辑，单测通过不代表本机已就绪）。
   - **本机就绪（4 项全过才算安装完成）**：
     1. `trellis channel --help` 退出码为 `0`；
     2. 在技能目录用 `python -B` 加载 `scripts/review.py`，调用 `resolve_reviewers(None, {})` 校验 `~/.codex/cross-review.json` 合法；
     3. 用配置返回的每位评审者标识调用 `PROVIDERS[name].executable()`，确认两个真实可执行文件都能定位；
     4. 确认 `~/.codex/AGENTS.md` 已包含第 3 步的完整触发正文。

</details>

---

## 平时怎么用

装完之后几乎不用记命令，正常在 Codex 里聊就行：

- **什么都不说**：Codex 第一次走到方案提交前或验收前，会弹窗问你选哪种范围：
  - `本次自查`（小改动推荐，不调外部 CLI）
  - `仅方案`
  - `仅验收`
  - `方案和验收`
- **提前说清楚**：在任务一开始直接跟 Codex 说一句“这次仅验收双评”或“这次小改，自查就行”，Codex 会记在当前任务的 `task.json` 里，不会反复追问。
- **中途改主意**：随时可以直接说“改成两阶段都双评”或“这次用某模型复审”。

> 完整的触发细节、记录格式和退出码约定（`0` 通过 / `1` 阻塞 / `2` 待复核或异常）见 [SKILL.md](SKILL.md)。所有评审记录和回执都会留在各自项目的任务目录和 Trellis Channel 里，不会串项目。

---

## 我用的不是 Qoder + Antigravity 怎么办？

**不用自己改代码。** 仓库目前默认只内置了已经真机跑通端到端验收的 `qoder` 和 `agy`，如果你本机装的是其他 AI CLI（比如 Claude Code、Gemini CLI、OpenCode 等），直接让 Codex 帮你自动适配即可：

1. **首次初始化时自动列清单**：Codex 会同时扫描本机已内置的 CLI 和其他常见 AI CLI，全部列出来让你选两个（没扫到的你也可以直接报命令名）。
2. **在独立工作树试用**：选好两位后，Codex 查本机帮助和官方文档，为能原生限制写入的新 CLI 创建独立 Git worktree 和临时配置，自动编写适配器并跑实测。试验失败、取消或等待团队合并期间，你仍可用原组合；首次安装也无需提前创建正式配置。
3. **验收后使用**：想先体验，可以直接用通过验收的候选工作树和临时配置。候选分支可提交 PR 供团队共享；本机安装的 `main` 更新到受测适配器后，再启用新组合。

### 候选适配器验收

<details>
<summary>适配器技术契约与 4 项实测标准（Codex 自动适配和手动开发共用）</summary>

并发调度、超时控制、Windows 系统代理透传、断线重试、Channel 存档和结论解析都由 [scripts/review.py](scripts/review.py) 的公共框架接管，新适配器只需新增一个类注册到 `PROVIDERS` 并实现 **3 个方法**：

| 方法 | 作用 | 要注意的点 |
| --- | --- | --- |
| `executable()` | 找到本机可执行文件路径 | 找不到时抛出带命令名的 `FileNotFoundError` |
| `request(prompt, model, seconds)` | 组装命令行参数和标准输入 | 返回 `(args, stdin_text)`；务必开启**非交互**和**原生只读权限**，尽量透传剩余超时秒数；只在 `model` 非空时传模型参数 |
| `decode(events)` | 解析 CLI 输出的事件流 | 接收按行解析的 JSON 事件迭代器，返回 `(success, body, observed_model, errors, warnings)`；保留原文，只读工具偶发报错可记进 `warnings` |

> **可选属性**：如果 CLI 支持查询可用模型列表，可以顺手定义类属性 `list_args`（如 `["--list-models"]`），在用户点错模型名时自动列出可选项。若新 CLI 不是按行输出 JSON，则需要同步适配公共解析入口并补上单测。

**隔离试验（PowerShell 示例，由 Codex 在本机执行）**。先按用户所选的两位标识替换 `<甲>`、`<乙>`。启动前核对全局技能安装位于团队仓库的干净 `main`。

```powershell
$trial = python -B "$HOME/.codex/skills/trellis-cross-review/scripts/adapter_trial.py" --reviewers "<甲>" "<乙>" | ConvertFrom-Json
```

脚本在安装目录外创建独立工作树，并返回候选配置的绝对路径 `$trial.config`。其中的 `models: {}` 沿用所选 CLI 的默认模型。所有适配代码和对应测试写入 `$trial.worktree`；可在 `candidate.json` 中设置用户点名的型号。从一次性项目根目录运行所测工作树的入口：

```powershell
python -B "$($trial.worktree)/scripts/review.py" gate --config "$($trial.config)" --task ".trellis/tasks/<验收任务>" --stage plan --scope plan --revision "<试验版本>" --brief-file "<问题文件>" --file "<方案文件>"
```

**四项真机验收**（代码或权限参数有变化时使用新试验版本）：

1. **读源码**：附上需求并让评审者读取项目里的关联文件，用未写进提示词的源码事实或随机标记核对回执。
2. **只读拦截实测**：按实际启用的工具逐项核对 CLI 参数和权限，确认写文件、Shell/命令执行、MCP/插件及子代理/后台任务等可写入口已被原生禁用或受只读限制；对每个仍可调用的写入口在一次性目录分别发起最小写入探针，等后台操作结束，确认 CLI **实际拒绝调用**且整个探针目录的文件清单与内容哈希不变（只靠模型口头拒绝不算通过，无需额外填表）。
3. **两轮双评**：用上述命令向两位真实 CLI 派发，完整跑通独立首评与交换原文互验，核对两轮回执与最终结论。
4. **同参重放与单测**：重复同一命令，确认四份回执 `reused=true` 且无新增 CLI 调用；在候选工作树运行 `python -B -m unittest discover -s tests -v` 全绿。

失败或取消时保留原 `~/.codex/cross-review.json` 和安装目录 `main` 不变；全部通过后在候选分支提交代码即可推送提 PR。合并回 `main` 后若适配代码或权限参数有变动须换新试验版本复验，确认无变化并核对 `previous_config_sha256` 后再原子替换正式配置。

</details>

## 许可证

[MIT](LICENSE)
