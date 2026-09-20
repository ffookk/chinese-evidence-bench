# 首批公开事实的来源复核

[公开事实数据](../data/public-facts.jsonl) 收录 8 条中文案例，核验日期为 **2026-09-20（UTC）**。本轮由 AI 代理实际打开下列发布机构网页、阅读所列证据位置并核对中文概括，之后设置 `synthetic: false`、`review_status: reviewed`。**这表示已做一次来源支持复核，不表示独立人工认证、机构背书或模型评测已经完成。**

问题均明确限定某个已发布文件，`time_sensitive: false` 表示回答的是该版本写了什么；不声称这些文件覆盖所有后续修订、实现行为或最新标准状态。BIPM 案例核对的是其发布的英文文本；该页面注明法文为正式文本，本轮没有进行英法逐句核对。

## 逐条证据索引

| 案例 ID | 已打开的原始来源 | 精确位置 | 核对要点 |
| --- | --- | --- | --- |
| `rfc8259-duplicate-names` | [RFC 8259](https://www.rfc-editor.org/rfc/rfc8259) | 第 4 节首段及语法块后段落，印刷页 6–7 | 唯一性使用 SHOULD；保留不同实现对重复名称的行为差异。 |
| `rfc8259-nonfinite-numbers` | [RFC 8259](https://www.rfc-editor.org/rfc/rfc8259) | 第 6 节，number 语法之前的禁止句，印刷页 7 | NaN 与 Infinity 不是该 JSON 数值语法允许的值。 |
| `rfc2119-must-requirement` | [RFC 2119](https://www.rfc-editor.org/rfc/rfc2119) | 第 1 节 MUST，印刷页 1 | MUST 表达绝对要求，并与 REQUIRED、SHALL 对应。 |
| `rfc2119-should-exceptions` | [RFC 2119](https://www.rfc-editor.org/rfc/rfc2119) | 第 3 节 SHOULD，印刷页 1 | 例外需要特定理由，并先理解影响、仔细权衡。 |
| `rfc8174-uppercase-keywords` | [RFC 8174](https://www.rfc-editor.org/rfc/rfc8174) | 第 2 节 NEW 部分三个项目符号，印刷页 3 | 大小写影响关键词的特殊含义；规范性不取决于是否使用这些词。 |
| `cgpm2018-metre-definition` | [CGPM 第 26 届第 1 号决议英文文本](https://www.bipm.org/en/committees/cg/cgpm/26-2018/resolution-1) | 附录 3 第 2 个项目符号，metre | 核对真空光速固定数值、m/s 单位及秒的定义关系。 |
| `cgpm2018-mole-entities` | [CGPM 第 26 届第 1 号决议英文文本](https://www.bipm.org/en/committees/cg/cgpm/26-2018/resolution-1) | 附录 3 mole 项及紧随其后的说明段 | 核对固定数量；基本单元的范围不限于原子。 |
| `rfc9110-safe-side-effects` | [RFC 9110](https://www.rfc-editor.org/rfc/rfc9110.html) | 第 9.2.1 节前 3 段 | 区分客户端请求语义与实现副作用；GET 与访问日志示例均在原文。 |

数据只保存自行撰写的短中文概括、标题、定位和链接，没有复制完整标准、网站正文、作者联系方式或网页元数据。链接没有查询参数或片段；章节信息单独保存在 `evidence_locator`。

## 覆盖与下一步

这 8 条记录只覆盖 5 份文件、2 个发布机构，且有多个同源案例；内容集中于技术标准和 SI 定义，全部是证据充分的短问题。它们不能代表中文事实核查的领域覆盖，也不适合单独形成模型总体排名。真实数据尚缺证据不足、澄清、多源冲突及较长推理案例；原有 3 条虚构样例仍仅用于测试格式。

后续需要独立人工复核问题表述、中文概括和证据定位，并扩展到 30 条及更多来源。复核只证明所列来源支持所写答案，不证明来源网页将永久可用。自动测试离线执行，不重新访问网页，也不判断答案真实性。

```sh
python3 -m evidence_bench validate data/public-facts.jsonl --real-only --require-reviewed
python3 -m evidence_bench validate examples/synthetic.jsonl data/public-facts.jsonl
python3 -m unittest discover -s tests -v
```
