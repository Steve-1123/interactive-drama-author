# 创作协议 1.0-draft.1

这是根据互动剧内容协议方案收敛的**预发行创作子集**。完整字段与必填项以 [content.schema.json](../schemas/content.schema.json) 为准；本文件定义Schema之外的执行语义。不能当作现有HTTP DTO。

## 身份与顺序

剧有key；章、集、单元、台词、角色、状态、规则组、结局和资产需求使用顶层字典键；选项/规则在对应实体类型内全剧键唯一，姿态键在所属角色内唯一。键为小写字母开头、后接小写字母/数字/下划线，最长64字符。允许不同实体类型使用相同键，引用通过字段确定类型。改名/排序不改变身份。

`drama.chapter_order` → `chapter.episode_order` → `episode.unit_order` → `unit.dialogue_order` 是顺序唯一来源。每个子实体必须恰属一个父级，集至少一个单元。章是组织容器，不隐含章出口。集是分支出口；单元和台词在集内线性播放。集概要独立编辑，整集阅读文本从台词派生，不复制存储第二份正文。

## 数量请求

先读 [request.schema.json](../schemas/request.schema.json)。本预发行版的数量覆盖使用**从1开始的章/集序号**，仅用于生成前展开计划，避免要求用户预先知道稳定键。展开后分配稳定键；修订/重排仍按key。旧方案中按key覆盖属于后续扩展，不混用两种请求格式。

每章/集未覆盖部分使用默认数量；重复或越界覆盖报错。`chapter_count`为精确数量，`ending_count`为精确结局数；max字段为上限。所有支线都计入全剧实体数，共享汇合集不重复计数。`max_new_specs`统计create/derive需求数，不能通过谎称reuse逃避预算。

## 演出

- `single_image` 主素材为scene/background图片，无角色层。
- `layered_scene` 主素材为background，角色层显式指向character及其pose，left/right最多各一个；层不跨单元隐式继承。
- 每单元 `advance_mode: click`；零台词单元也可点击前进。
- `bgm`为play/keep/stop；play带bgm需求引用，keep沿实际路径保持，初始静音。离线状态模拟只分析分支数值，不验证BGM重连实现。
- character台词需character引用；narrator/custom禁止该引用。`voice_asset`可省略；有配音时需求的spoken_text必须与正文一致。
- 本版不提供视频、任意动画脚本、隐藏选项、随机分支、循环剧情和跨规则组递归。不要在不认识的字段中塞入这些行为。

## 状态与出口

整数状态有initial/min/max；布尔状态有initial。数值effect按数组顺序add/set，**每次操作后**钳制；布尔只支持set。on_enter在成功进入每个单元时运行一次；模拟中按unit_order依次运行，刷新不重新执行。线上重试幂等由服务端负责，本工具没有玩家请求/存档。

出口mode：sequence（同章下一集）、episode（目标集）、ending（结局）、rules（规则组）、choice（2–4项）。mode与target.type匹配；选项目标可以是episode/ending/rule_set。选择先应用全部effects，再求值规则；进入目标集后按序执行其各单元on_enter。

条件为eq/ne/gt/gte/lt/lte；布尔仅eq/ne；条件组all/any且至少一条。规则priority升序、禁止重复，同组首条匹配采用；有且只有一个default目标。规则目标只能episode/ending。集图包含规则所有潜在边，禁止环。

校验器从初始状态探索所有选择，合并相同(集,状态)以降低开销；所有集和声明的结局都必须实际可达。报告为每个结局保存一条可行路径及数值。未触发规则报告警告，超过max-states报错并标记未穷尽。未模拟的自然语言事实不能得到正确性保证。

## 素材与能力

`asset_specs`是需求，`asset_bindings`是已存在且明确选中的成品。AI不能凭空填写artifact_id或摘要。spec.references引用需求键，生成平台以后必须解析到当时选中的成品版本。人物portrait/pose/voice_profile区分；voice_profile使用application类型元数据，不能当音频播放。

`required_capabilities`至少覆盖实际使用功能；类型single_image/layered_scene、episode_choices、state_rules、unit_effects、bgm、voice。未知能力/字段/版本拒绝。正式服务端仍应再次检查能力兼容性。

## 校验范围与限制

输入最多8MiB，1000集、10000单元；字段/字典另有限制见Schema。默认最多20000个不同(集,状态)，可显式调--max-states，过大可能消耗大量内存。数字采用JSON严格整数表示，不用1.0代替1。不接受重复JSON键、NaN或Infinity。

`valid`表示所执行的离线检查无错误；缺成品产生warning，不妨碍草稿。`publish_ready`始终false：没有检查文件、成品真伪、在线权限、人审或Phoenix实现。参考、状态图无误也不代表画面一致或故事好看。
