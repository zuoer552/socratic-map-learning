# Socratic Map Learning 7.3.0

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

## 快速教学回合

- 新单元只准备一次最小原文资料包；
- 同一单元的日常回合复用准确原文，不重复扫描 PDF；
- 日常回合最多一次本地调用，通常就是 `commit`；
- 每轮引用一至三句决定性原文，解释一条核心连接；
- 新术语先讲人话再命名，最多一个主要例子；
- 教师侧补齐原文事实、新定义和缺失连接，不要求学习者凭空发明；
- 出题前区分“必须先教的新内容、可由已有前提推出的关系、需要迁移检验的
  已学关系”；
- 拒绝依赖未交代前提、只能复述题干、偷换术语范围或混淆规范要求与客观
  存在的问题；
- 新理论层次按“具体情境 → 普通语言关系 → 作者术语 → 概念边界”逐级推进；
- 每轮自然选择一个最关键的批判性观察角度，不机械填写思维表格；
- 每轮严格一个问题，知识页面蓝色链接固定为最后一行；
- 单元闭合时由教师主动给出完整收束，再做一次复原或现实迁移；
- 现实迁移案例只取自：经核验的新闻或公共事件、可靠的历史知识或事件、
  普通且低风险的人际情景；
- 不使用 AI、工作、职场、商业、产品或运营案例做现实迁移；无法核验的
  当代事件也不能临时编造；
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
│   ├── map-template-v5.html
│   ├── map-template-v6.html
│   ├── map-template-v7.html
│   ├── progress-template-v1.html
│   ├── progress-template-v2.html
│   └── structure-overlay.example.json
└── tests/
    ├── map_geometry_audit.js
    ├── map_contrast_audit.js
    ├── map_runtime_smoke.js
    ├── test_runtime.py
    └── test_skill_response_contract.py
```

旧模板只用于迁移；当前渲染器使用
`map-template-v7.html` 与 `progress-template-v2.html`。

## 安装

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

## 验证

```bash
python3 -m unittest discover -s tests -p 'test_*.py'
node tests/map_runtime_smoke.js <map.html>
node tests/map_geometry_audit.js <map.html>
node tests/map_contrast_audit.js <map.html>
python3 scripts/validate_learning_map.py <map.html>
```

测试覆盖来源层级、唯一问题页、问题链连续性、未来答案隐藏、局部证明
可达性、从下向上推理、渐进展开、无自由画布、进度分层、明暗主题
WCAG 对比度、快速回合与学习回复契约。

## 适用范围

当前版本主要面向具有可核验文本来源和稳定来源结构的理论、历史、实用、
文学及混合作品。理论作品的局部证明支持最完整；其他模式会切换为原因与
证据、方法与条件、文本依据与替代读法等关系语言。

## License

[MIT](LICENSE)
