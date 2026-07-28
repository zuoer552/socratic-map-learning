# Socratic Map Learning 7.5.0

一个通用 Codex Skill：以一次一问的苏格拉底对话精读复杂作品，同时维护
原书结构、全书问题链、单问题局部关系，以及彼此独立的阅读与掌握进度。

## v7 的学习界面

- 第一入口是作品自身的卷、部分、章、节、篇、幕等来源结构；
- 进入一个来源单元，先看它承接什么、解决什么，再看其中的问题目录；
- 每个核心问题只有一个页面，相关章节只链接它，不重复制造页面；
- 当前推理内容优先于定位信息、历史记录和辅助说明；
- 核心学习内容直接可见，深层细节再逐步展开；
- 页面依靠清晰结构与简洁标签自解释，不堆叠操作教程或维护信息；
- 页面只展示当前问题的局部关系，不把全书塞进一个画布；
- 当前问题显示“理解、验证、批判、迁移、收束”五阶段中的实际位置；
- 默认保留压缩结论，展开后可以重新查看原子关系链、完整原文上下文与每根
  关系的掌握层级；
- 理论作品采用“结论在上、根据在下、箭头向上”的证明语法；
- 直接根据默认可见，更深根据向下逐层展开；
- 桌面端使用可折叠来源目录，手机端使用抽屉；
- 不使用自由画布、拖拽、缩放或横向寻找节点；
- 进度页按相同来源层级展开，同时严格区分阅读位置与推理掌握。

底层结构适用于不同类型的作品：

- 理论：结论 ← 前提与推理；
- 历史：结果或解释 ← 原因、证据与竞争解释；
- 实用作品：目标 ← 方法、条件、失败模式与迁移；
- 文学：解释 ← 文本证据、形式、冲突与替代读法。

运行时继续使用 `argument_atlas`、`proposition`、`inference` 等兼容字段，
但教学语言按当前体裁转换；不会把历史因果、实用条件或文学解释伪装成
演绎证明。混合型作品按当前单元选择体裁语法，并明确切换。

## v7.5 问题闭环与教学循环

- 学习者回答后，教师必须先给出这一题的规范化完整结论，或明确进入同一
  连接的修补；不会不公布答案就跳到下一个知识点；
- 规范化结论要求关系等价，不要求学习者逐字匹配唯一标准答案；
- 半懂时保留已经独立说出的部分，只补一根缺失连接；当前节点、目标、
  五阶段位置和掌握层级全部冻结；
- “修补中”是当前五阶段内部的临时状态，不另造第六阶段，也不计作进度；
- 二至五步只是单轮呈现上限；原子性以学习者能否独立复原为准；
- 运行时保存当前问题、历次尝试、已理解部分、缺失连接与规范化结论，
  因而换轮后也不能悄悄遗失上一题；
- 网页顶部同时显示最近闭环的结论和当前唯一学习动作，并高亮其对应关系；
- 开放问题的预期答案、评分前提、原始回答和尝试记录永远不写入公开网页。

- 新单元只准备一次最小原文资料包；
- 同一单元的日常回合复用准确原文，不重复扫描 PDF；
- 日常回合最多一次本地调用，通常就是 `commit`；
- 每轮使用最短充分原文片段，明确区分原文、忠实直译和教师解释；
- 每条核心连接先拆成二至五个原子步骤，再给出可反向展开的压缩总结；
- 每轮都交代“上一结果 → 当前问题 → 当前结论 → 下一压力”；
- 新术语先讲人话再命名，最多一个主要例子；
- 教师侧补齐原文事实、新定义和缺失连接，不要求学习者凭空发明；
- 每轮必须有一次有效互动，但不强制使用开放问题；可以要求区分、补全、
  判断、重建、解释或迁移；
- 互动前先生成预期答案并核对全部前提；模糊指代、教案腔、复述题干、
  偷换范围或多重思维动作都必须重写；
- 学习者答不上来时先审查题目本身，坏问题不能登记为学习缺陷；
- 新理论层次按“具体情境 → 普通语言关系 → 作者术语 → 概念边界”逐级推进；
- 每个局部单元依次经过理解、验证、批判、合适时的迁移与收束；不是每轮
  强塞全部阶段；
- 知识页面蓝色链接固定为最后一行；
- 单元闭合时由教师主动给出完整收束，再做一次复原或现实迁移；
- 迁移案例不按领域建立黑名单，只按结构相关性、事实可靠性、风险、隐私
  与适用边界判断；没有高质量案例时直接跳过；
- 现实迁移必须完成“原文关系 → 现实信息 → 判断 → 适用边界”，
  不把表面相似当作触类旁通。

## 文件

```text
socratic-map-learning/
├── SKILL.md
├── README.md
├── VERSION
├── references/
│   ├── course-model.md
│   ├── map-contract.md
│   ├── response-contract.md
│   └── unit-preparation.md
├── scripts/
│   ├── sml.py
│   └── validate_learning_map.py
├── templates/
│   ├── course-blueprint.example.json
│   ├── map-template-v7.html
│   ├── progress-template-v2.html
│   └── structure-overlay.example.json
└── tests/
    ├── map_geometry_audit.js
    ├── map_contrast_audit.js
    ├── map_runtime_smoke.js
    ├── test_runtime.py
    └── test_skill_response_contract.py
```

当前渲染器只有一套正式模板：
`map-template-v7.html` 与 `progress-template-v2.html`。旧版本仍可通过
`import-html` 迁移，不依赖旧渲染模板。

## 安装

运行要求：Codex、Python 3.9 或更高版本。日常使用只依赖 Python 标准库，
不需要 `pip install`、npm 或数据库服务器。

推荐直接克隆到 Codex Skills 目录：

```bash
git clone https://github.com/zuoer552/socratic-map-learning.git \
  ~/.codex/skills/socratic-map-learning
```

也可以从 GitHub 下载 ZIP，解压后将整个 `socratic-map-learning` 目录放到：

```text
~/.codex/skills/socratic-map-learning/
```

重新打开 Codex 或新建任务。

安装后可立即自检：

```bash
python3 ~/.codex/skills/socratic-map-learning/scripts/sml.py --help
cat ~/.codex/skills/socratic-map-learning/VERSION
```

第二条命令应输出当前发布版本。看到命令帮助后，即可在新任务中点名
`$socratic-map-learning` 使用。

更新已有安装：

```bash
git -C ~/.codex/skills/socratic-map-learning pull --ff-only
```

## 使用

```text
请用 $socratic-map-learning 带我逐章精读这本书。
一次只问一道题；先按原书结构进入章节，再点击问题查看它唯一的局部证明。
```

## 常用命令

```bash
# 初始化
python3 scripts/sml.py init <course-dir> \
  --blueprint <blueprint.json> \
  --map-path <map.html>

# 恢复或进入新单元时获取上下文
python3 scripts/sml.py context <course-dir>

# 新单元准备一次原文资料包
python3 scripts/sml.py prepare-unit <course-dir> \
  --packet <unit-packet.json> \
  --expected-revision <revision> \
  --expected-current <node-id>

# 提交一次学习证据
python3 scripts/sml.py commit <course-dir> \
  --expected-revision <revision> \
  --expected-current <node-id> \
  --diagnosis mastered \
  --evidence-kind own_words_reason \
  --turn <turn-update.json> \
  --learning-phase synthesis \
  --inference-step <inference-id> \
  --inference-level reconstructable

# 审校来源结构、问题归属、问题链或局部证明
python3 scripts/sml.py structure <course-dir> --overlay <overlay.json>

# 同步生成知识页与进度页
python3 scripts/sml.py render <course-dir>

# 验收
python3 scripts/sml.py audit <course-dir>
python3 scripts/sml.py validate <course-dir> --deep
```

`turn-update.json` 是每轮闭环的事务输入。完整回答并开启下一步：

```json
{
  "resolution": {
    "move_id": "move-current-link",
    "outcome": "resolved",
    "learner_response": "学习者这一轮的原话",
    "evidence_kind": "own_words_reason",
    "accepted_parts": ["学习者已经独立建立的部分"],
    "resolved_statement": "教师给出的规范化完整结论"
  },
  "next_move": {
    "id": "move-next-link",
    "node_id": "node-next",
    "target_id": "inference-next-link",
    "interaction_kind": "distinguish",
    "prompt": "下一次只完成的一项动作",
    "expected_answer": "供教师内部判断，不进入公开网页",
    "required_premises": ["已经提供的前提"],
    "scope_boundary": "这一步不能推出什么"
  }
}
```

半懂、误解或答不上来时不提供 `next_move`，而是记录修补：

```json
{
  "resolution": {
    "move_id": "move-current-link",
    "outcome": "partial",
    "learner_response": "学习者这一轮的原话",
    "evidence_kind": "own_words_reason",
    "accepted_parts": ["已经说对的部分"],
    "missing_link": "仍需补齐的唯一连接"
  }
}
```

## 核心数据

`argument_atlas.source_structure` 保存作品真实来源层级和阅读模式。
每个 `system_spine.stage` 保存一个 `primary_unit_id` 和可选的
`related_unit_ids`。

`argument_atlas.system_spine` 保存：

- `arcs`：连续的大型解释任务；
- `stages`：按问题逻辑排列的核心问题与唯一答案；
- `transitions`：相邻问题间的“因此必须追问”桥梁；
- `terminal_mastery`：全书最终掌握标准。

`argument_atlas.maps` 与 `argument_atlas.inferences` 保存单问题局部关系：

- 一个或多个根据（兼容字段 `premise_ids`）；
- 一个目标（兼容字段 `conclusion_id`）；
- 可完整复述的 `bridge`；
- 支持、反驳、回应或限定等结构角色；
- 来源与学习掌握映射。

运行时还保存：

- `learning_phases`：每个当前或已学问题的五阶段位置；
- `active_move`：当前唯一学习动作及其开放或修补状态；
- `move_history`：历次尝试、已理解部分与规范化闭环结论；
- `unit_packets`：按问题归档的最短教学片段、完整上下文和直译；
- `inference_mastery`：当下理解、能够重建、能够迁移与稳定掌握；
- `latest_inference_step_id`：地图中最近一次验证的关系。

## 验证

```bash
python3 -m unittest discover -s tests -p 'test_*.py'
node tests/map_runtime_smoke.js <map.html>
node tests/map_geometry_audit.js <map.html>
node tests/map_contrast_audit.js <map.html>
python3 scripts/validate_learning_map.py <map.html>
```

测试覆盖来源层级、唯一问题页、问题链连续性、上一题闭环、半懂修补、
开放答案不泄露、局部证明可达性、从下向上推理、渐进展开、无自由画布、
进度分层、明暗主题 WCAG 对比度、快速回合与学习回复契约。

## 适用范围

当前版本主要面向具有可核验文本来源和稳定来源结构的理论、历史、实用、
文学及混合作品。理论作品的局部证明支持最完整；其他模式会切换为原因与
证据、方法与条件、文本依据与替代读法等关系语言。

## License

[MIT](LICENSE)
