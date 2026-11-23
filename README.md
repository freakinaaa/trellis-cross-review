# Trellis Cross Review

在 **Codex** 里开发 **Trellis** 项目时，自动拉起本机另外两个 AI CLI 做**两轮只读交叉评审**——全程在后台跑完，**不用手动开别的 IDE，也不用复制粘贴方案和意见**。

装一次就能在你本机**所有 Trellis 项目**通用，不会改动或污染任何业务代码库。

## 它会怎么帮你审

在每个任务的**方案批准前（`plan`）**和**最终验收前（`acceptance`）**，Codex 会先问你一次这次要不要双评（也可以直接选“本次自查”跳过）：

1. **第 1 轮（独立并发）**：两个外部 CLI 同时在后台启动，各自独立看方案、验收条目和关联源码，**全程只读，不能改文件**。
2. **第 2 轮（原文互验）**：脚本自动把两边的首轮意见原文互相发给对方核查，过滤掉瞎猜和误报，再各自给出最终结论。
3. **结论门禁与缓存**：
   - 只有两位都明确“通过”且没有未关闭的阻塞项，才算**双评通过**；
   - 谁提的阻塞项，修订后必须由**原提出者**复核才能关闭；
   - 同一版材料重跑会直接复用已有回执，不重复消耗额度，也不怕中途断线。

---

## 快速安装（一句话让 Codex 自己装）

### 前置条件

- Python 3.10+（只用标准库，不需要 `pip install`）
- 已安装 **Codex** 和 **Trellis**（确认终端能跑通 `trellis channel --help`）
- 本机已安装并登录两位外部评审 CLI（目前内置已实测 **Qoder CLI** `qodercli` 和 **Antigravity CLI** `agy`，已验证系统为 Windows）

### 安装方式：直接把下面这句话发给 Codex

复制发给 Codex，它会自己克隆或安全更新仓库，再按 [SKILL.md](SKILL.md) 的首次配置流程自动检测本机 CLI、生成配置、补全全局入口，并分别验证脚本单测和本机就绪状态：

> 帮我安装并初始化 `trellis-cross-review` 全局技能：若 `$HOME/.codex/skills/trellis-cross-review` 不存在，将 `ssh://git@192.168.1.81:2222/czl/trellis-cross-review.git` 克隆到该路径；若目录已存在，先核对 `origin` 指向该团队仓库、当前分支为 `main` 且工作区干净，再执行 `git pull --ff-only origin main`（若 `origin`、分支不符或有未提交改动，先停下来提示我）。更新后按该技能 `SKILL.md`「首次配置与缺配引导」完成本机 CLI 检测、配置生成、全局 `AGENTS.md` 触发规则核验，并分别汇报脚本单测结果与本机就绪检查结果。

完成后**新开一个 Codex 对话**即可生效。如果你已经手动克隆过仓库，直接跟 Codex 说“按 `trellis-cross-review` 技能帮我检测 CLI 并初始化配置”就行。

<details>
<summary>想手动安装，或查看 Agent 具体会改哪两个文件？点这里展开</summary>

1. **克隆或更新仓库**：
   ```sh
   git clone "ssh://git@192.168.1.81:2222/czl/trellis-cross-review.git" "$HOME/.codex/skills/trellis-cross-review"
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

不同同事手头装的 CLI 可能不一样（比如 Claude Code、Gemini CLI 等）。为了保证每个内置工具都真机实测过，仓库目前只放了已经跑通端到端验收的 `qoder` 和 `agy`。

如果你用其他支持命令行非交互调用的 AI CLI，接入成本很低——打开 [scripts/review.py](scripts/review.py)，照着里面的 `Qoder` 或 `Antigravity` 类新增一个适配器，并注册到 `PROVIDERS` 字典即可。

并发调度、超时控制、Windows 系统代理透传、断线重试、Channel 存档和结论解析都由公共框架接管，新适配器只需要实现 **3 个方法**：

| 方法 | 作用 | 要注意的点 |
| --- | --- | --- |
| `executable()` | 找到本机可执行文件路径 | 找不到时抛出带命令名的 `FileNotFoundError` |
| `request(prompt, model, seconds)` | 组装命令行参数和标准输入 | 返回 `(args, stdin_text)`；务必开启**非交互**和**原生只读权限**，尽量透传剩余超时秒数；只在 `model` 非空时传模型参数 |
| `decode(events)` | 解析 CLI 输出的事件流 | 接收按行解析的 JSON 事件迭代器，返回 `(success, body, observed_model, errors, warnings)`；保留原文，只读工具偶发报错可记进 `warnings` |

> **可选属性**：如果 CLI 支持查询可用模型列表，可以顺手定义类属性 `list_args`（如 `["--list-models"]`），在用户点错模型名时自动列出可选项。若新 CLI 不是按行输出 JSON，则需要同步适配公共解析入口并补上单测。

**提交新适配器前建议自测 4 件事**：
1. 评审者确实能读到项目里的关联源码（不是只看提示词）；
2. 尝试写文件或执行改写命令会被明确拒绝，目标文件字节不变；
3. 完整跑通两轮（独立首评 + 交换原文互验）；
4. 相同参数重跑一次，确认直接命中缓存、不再触发新的外部 CLI 调用。
