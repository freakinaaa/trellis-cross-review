# Trellis Cross Review

从 Codex 调用两位 CLI 评审者，在 Trellis 任务的方案或验收阶段做两轮只读交叉评审。每人安装一次即可用于自己机器上的多个项目，每个项目的选择、材料与回执留在对应任务和项目 Channel 中。

## 安装

1. 在装有 Python 3.10+、Codex 和 Trellis 的机器上，用有仓库读取权限的 SSH 密钥执行以下克隆命令。确认 `trellis channel --help` 可用。已实测的运行环境为 Windows，评审者 CLI 需要各自安装，并能从当前账号非交互运行。

   ```sh
   git clone "ssh://git@192.168.1.81:2222/czl/trellis-cross-review.git" "$HOME/.codex/skills/trellis-cross-review"
   ```

2. 创建 UTF-8 文件 `~/.codex/cross-review.json`，写入两位已安装且已注册的评审者。以下示例适用于 Qoder CLI 和 Antigravity CLI。使用其他 CLI 的同事先按下文添加并验证适配器，再填相应标识。

   ```json
   {"reviewers": ["qoder", "agy"], "models": {}}
   ```

   `models` 按评审者标识映射到 CLI 接受的型号字符串。空映射沿用各端当前 CLI 或账号的默认型号。实际派发时，`--reviewers` 覆盖本机组合，`--model CLI=MODEL` 逐端覆盖本机型号。若组合和两端型号均已明确传入，则无需配置文件。需要回退到本机配置时，文件缺失或无效会返回错误并给出配置提示。单纯查询阶段、自查和待选均可在配置评审器之前使用。

3. 在自己的 `~/.codex/AGENTS.md` 末尾追加以下两行，保留已有条目。之后在 Trellis 项目中打开新的 Codex 会话即可使用。

   ```markdown
   ## Trellis 交叉评审
   在存在 `.trellis/tasks/` 的项目中，提交方案给用户批准前和实施最终全范围验收前，按全局技能 `trellis-cross-review` 执行交叉评审入口。
   ```

## 验证与使用

在技能仓库运行 `python -B -m unittest discover -s tests -v`。运行时和测试均只使用 Python 标准库。

从任一目标项目的根目录查询真实任务。首次查询会记录“已询问”，对同一任务再次查询会恢复状态。用户已在聊天中明确选择阶段时，Codex 可以在第一次查询就传入 `--scope`。

```sh
python "$HOME/.codex/skills/trellis-cross-review/scripts/review.py" gate --task ".trellis/tasks/<任务>" --stage plan
```

日常只需在聊天中说“这次仅验收双评”或在卡片上选择范围。Codex 会在所选阶段准备材料并运行脚本。派发的退出码为 `0` 双评通过、`1` 阻塞、`2` 待复核或执行失败。完整流程见 [SKILL.md](SKILL.md)。

## 新增 CLI 适配器

在 [scripts/review.py](scripts/review.py) 中实现下面三个方法，再把标识和适配器加入 `PROVIDERS`。现有实现 `Qoder` 与 `Antigravity` 可作参考。公共流程负责项目工作目录、环境代理、超时、传输中断重试、并发、Channel 持久化和结论解析。

| 方法 | 契约 |
|---|---|
| `executable()` | 返回当前机器上可启动的 CLI 可执行文件路径。找不到时抛出带入口名称的 `FileNotFoundError`。 |
| `request(prompt, model, seconds)` | 返回 `(args, stdin_text)`。参数列表不含可执行文件，正文经 UTF-8 stdin 传入。使用 CLI 的非交互设置和原生只读权限。按剩余秒数设置可用的超时参数；仅在型号非空时透传。 |
| `decode(events)` | 消费按行解析的 JSON 事件迭代器，返回 `(success, body, observed_model, errors, warnings)`。从终态判断成功，保留意见原文；未披露型号返回 `None`。错误和告警为字符串列表，已恢复的只读工具错误可保留为告警。公共流程另行检查退出码及正文是否非空。 |

可选类属性 `list_args` 指定查询可用模型的参数。仅在显式点名的型号遭 CLI 拒绝后调用，列表以原始文本呈现。现有两个适配器使用按行 JSON 输出；若新 CLI 的输出格式不同，应同时适配公共解码入口并补对应测试。

注册后，在一次性任务中验证能读取项目内关联源码、写入探针被拒且文件字节保持一致，再测试一轮独立意见、一轮互验及相同参数重放。每场仍固定两位不同的评审者。
