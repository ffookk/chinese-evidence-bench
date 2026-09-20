# 案例数据格式 v1

本规范是当前校验器的权威口径。仅使用 Python 3.10+ 标准库，不安装依赖，不联网。

## 文件与字段

输入为 UTF-8：`.json` 顶层必须是案例数组，`.jsonl` 每个非空行是一条案例对象；允许 JSONL 空行。每个输入文件至少包含一条可读案例。JSON 重复键、`NaN`、`Infinity`、未知字段均报错。一次命令传入的所有文件合在一起检查 `id` 唯一性。

每条案例必须有下列全部字段；允许为空的字段必须显式写 `null`，不能省略。

| 字段 | 格式及含义 |
| --- | --- |
| `schema_version` | 整数 `1` |
| `id` | 3–64 位小写 ASCII 字母、数字、`_` 或 `-`，首位是字母；不得填身份、账号或联系方式 |
| `synthetic` | 布尔值；虚构案例必须为 `true`，不能作为真实基准数据 |
| `question` | 非空字符串；约定用中文，程序不猜测自然语言 |
| `reference_answer` | `supported` 时为非空答案，其他状态必须为 `null` |
| `evidence` | 来源对象数组；`supported` 时至少一个，其他状态可为空 |
| `time_sensitive` | 布尔值，表示答案是否依赖时间 |
| `valid_as_of` | 有时效性时必填 `YYYY-MM-DD`；其他情况为 `null` |
| `verified_at` | `reviewed` 时必填最近一次证据复核日期；`pending` 时必须为 `null`；复核执行方式和范围见批次说明 |
| `answerability` | `supported` / `insufficient_evidence` / `needs_clarification` |
| `review_status` | `pending` / `reviewed` |

`answerability` 和 `review_status` 独立：`supported` + `pending` 表示作者提出了一个带来源的候选答案，仍待复核。`reviewed` + `insufficient_evidence` 表示复核后的证据不足判断，不能解释为已经证明某个答案。证据不足或问题不清时，空证据数组获准通过格式检查，仍须人工审查判断理由与检索范围。

`reviewed` 表示完成批次说明所披露的来源支持复核，不能单凭标记推断执行者为人类。每批真实数据须在说明中写清由人工还是 AI 代理核对、日期、证据位置及范围局限；未经独立人工复核不得宣传为人工认证。首批公开事实见 [来源复核说明](source-review.md)。这是对文档复核口径的明确说明，JSON v1 字段与校验逻辑不变。

每个来源对象必须且只能包含：

| 字段 | 格式及含义 |
| --- | --- |
| `source_url` | HTTPS URL；不得有用户信息、查询参数、片段、反斜杠、空白或非 443 端口。需要锚点的信息写入定位字段。域名使用合法 ASCII 标签（国际化域名需用 Punycode）。虚构案例只允许 `.invalid` 子域名；真实案例使用带点的域名，拒绝 IP 地址、`localhost`、`.local`、`.invalid`、`.test`、`.example`，以及 `example.com` / `example.org` / `example.net` 及其子域名 |
| `source_title` | 非空来源标题 |
| `evidence_locator` | 对象，且只能含 `type`、`value` 两个字段 |

`evidence_locator.type` 为 `paragraph`、`page`、`section`、`table` 或 `timestamp`；`value` 为非空字符串，例如 `第 2 节，第 3 段`。校验器只保证定位存在；位置能否定位、是否精确以及是否支持答案都需实际打开来源核对，并在批次说明披露复核方式。来源 URL 不得包含访问凭据、跟踪参数或个人资料；有参数的原始网页应先整理为可公开的稳定来源。

日期必须是严格的 ISO 日历日期，例如 `2026-01-15`；拒绝不存在的日期、缺少补零、时间戳和未来日期。未来的基准由本机当天日期决定，可用 `--as-of YYYY-MM-DD` 固定以便重现。若同时提供两个日期，`verified_at` 不能早于 `valid_as_of`。这套格式用于回顾已核验事实，不覆盖未来预测。

## 编辑时的类型检查

- `schema_version` 写整数 `1`；`1.0`、`true` 或字符串 `"1"` 都不能代替它。
- `synthetic` 和 `time_sensitive` 使用 JSON 布尔值 `true` / `false`，不能使用 `0` / `1` 或字符串。
- 非空文本字段不能只填空格、制表符或换行；当前校验用去除首尾空白后的内容判断是否为空。
- 对象字段的排列顺序不影响校验；保留全部必填字段比复制某个固定顺序更重要。
- 来源数组会逐项检查；一条合格来源不会抵消同一案例内另一条来源的格式错误。

## 校验、入库与评测

```sh
python3 -m evidence_bench validate examples/synthetic.jsonl
python3 -m evidence_bench validate examples/synthetic.jsonl --as-of 2026-01-31
python3 -m unittest discover -s tests -v
```

导入真实案例时，使用 `--real-only --require-reviewed` 限制为真实且已复核的记录。`data/public-facts.jsonl` 已通过该门槛；对虚构样例运行这两个开关会按预期失败；该失败不是工具故障。

```sh
python3 -m evidence_bench validate examples/synthetic.jsonl --real-only --require-reviewed
```

退出码：`0` 为格式检查通过，`1` 为数据或输入文件错误，`2` 为命令行参数错误。诊断使用输入文件序号和案例/行号，不回显字段值、文件路径或来源正文。

格式检查通过并不证明事实正确、来源存在、许可合规或没有个人信息。`--real-only` 只检查标记，不能识别被错标为真实的数据。目前有 8 条经代理核对的公开事实案例；独立人工复核与正式评分流程仍未完成。实际模型评测前须先完成约定的独立复核和评分口径。
