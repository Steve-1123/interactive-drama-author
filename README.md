# Interactive Drama Author

供合伙人、编剧和外包团队共享的互动剧创作 skill。把自然语言大纲细化为指定章/集/播放单元数量的剧情、台词、选项、状态规则及素材生成需求。

**版本：0.2.0；创作协议：1.0-draft.1。** 本仓库独立于业务仓库。当前 Alfred 管理平台支持上传、预检并导入为草稿；本 Skill 只负责生成和离线校验协议，不能替代服务器预检、人审、素材生成或发布。

## 开始使用

将整个仓库目录交给能读取文件的 AI agent，要求它读取 [SKILL.md](SKILL.md)。支持本地 skills 的工具可以把此目录复制到其技能目录，目录名保持 `interactive-drama-author`。无需获取业务仓库或任何 API key。本次创建没有自动安装或发布到远端。

普通聊天工具可上传 SKILL.md、references、schemas 和示例，按同一工作流程执行；没有文件或程序执行能力时，需人工保存 JSON 并在独立 Python 环境校验。不同产品原生 skill 安装方式不同，不承诺所有模型聊天窗口都能直接安装本目录。

可给 agent 的完整任务示例：

> 使用本目录的 interactive-drama-author skill。把我提供的原始故事改编成2章，每章2集，每集2个播放单元；最多1个有选项的集、2个结局、最多2个状态变量、最多4项新建或派生素材需求。保留主要人物动机，可以新增支线。只规划素材和 prompt，不生成图片、不上传、不发布。实际运行校验，最终只交付一份 `剧情协议.json`。

本包 examples 是手工编写的技术验证小样，不是一次真实模型创作验收；正式创作应使用自己的原稿。

## 零依赖离线验证

需要 Python 3.10+，无需安装第三方包或联网。校验器只支持本包 Schema 使用的显式子集，未知关键字报错；不是任意 JSON Schema 的通用实现。

```sh
python3 scripts/validate.py --plan --request examples/branching.request.json
python3 scripts/validate.py examples/branching.content.json --request examples/branching.request.json --report /tmp/drama-validation.json
python3 -m unittest discover -s tests -v
```

退出码：0=本次离线校验通过；1=内容或数量等校验失败；2=输入/运行错误。未提供 `--request` 时不能验证创作篇幅，报告有明确警告。需要校验精确篇幅时应带临时请求文件重跑。`valid` 不等于可发布，`publish_ready` 始终为 false；媒体文件存在性、服务器兼容性和人审不在本工具证明范围。最终交付目录只保留 `剧情协议.json`，请求和报告不随剧本交付。

## 目录

- [SKILL.md](SKILL.md)：agent执行入口。
- [中文使用说明](docs/使用说明.md)：安装、跨模型使用、唯一交付物、校验与 Alfred 导入流程。
- [协议](references/protocol.md)、[工作流](references/workflow.md)、[资产](references/assets.md)、[兼容边界](references/compatibility.md)。
- [内容Schema](schemas/content.schema.json) / [请求Schema](schemas/request.schema.json)：本预发行包契约。
- [线性示例](examples/linear.content.json) / [分支示例](examples/branching.content.json)：完整闭合的文件。
- [校验器](scripts/validate.py) / [测试](tests/test_validate.py)。

## 维护与交付边界

同一发布包固定 skill、协议、样例和校验器版本；主业务仓库以后应引用同一发行物，不复制后独立修改。变更协议时同步文档、样例、负例测试和迁移说明。数值模拟是Python参考实现；接入Phoenix前必须用共同fixture验证效果顺序、条件、钳制与目标的语义一致。

本仓库不保存生产凭证，不绑定 GPT、Grok、DeepSeek 中的某一家，不附带供应商调用或自动发布。外包只交付 `剧情协议.json`；接收方在管理端再次校验和审核。图片模型、分辨率、费用与生成结果属于管理平台生成阶段，不写入当前协议交付流程。
