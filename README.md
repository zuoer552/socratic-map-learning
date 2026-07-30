# Book Grilling 1.0.0

一个通用 Codex Skill：沿着知识型作品的真实来源结构，一次只讲清一个
问题，同时把已经讲过的内容沉淀为经过复核、逐步解锁的可视问题树。

本版本是一次从零重建。仓库保留了原 `socratic-map-learning` 的发布历史，
但技能名称、运行时和课程数据模型已经全部改为 `book-grilling`。

## 它怎样带你读完整部作品

1. 开始作品时，确认标题、作者、版本、完整来源和作者目录。
2. 沿作者目录划分学习单元；单元必须足够完整，也必须安全地装入一次
   准备上下文。
3. 进入一个单元时，读取该单元的完整原文，建立本单元的问题树。
4. 每个问题都同时提供完整推荐答案和可核查的精确原文依据。
5. 一次只处理一个问题。学习者可以同意、追问、质疑或理解但不同意。
6. 当前问题讲清以后，只解锁下一个问题，并自动更新独立 HTML 阅读页。
7. 所有单元完成后，生成一次经过复核的全书收束；不制造复杂的全书图谱。

版本 1 的目标是让整部作品的实质知识都被系统讲过并达到共同理解。它不把
“读完”夸大为闭卷记忆、长期保持或考试意义上的掌握。

## 防止遗漏与错误

- 不用摘要、书评或模型记忆代替完整来源。
- 每个问题节点都是“一个问题 + 一个推荐答案 + 精确原文依据”。
- 每个单元必须有覆盖台账，分类其全部来源区段。
- 问题树只有通过独立的来源对照复核才能解锁。
- 来源、问题树和最终综合均使用 SHA-256 指纹。
- 锁定节点的答案不会写入公开网页数据。
- 发现已学内容有误时，该单元及其后续单元会被归档并失效，等待重新复核。
- 部分来源会在网页中持续显示警告，不能被标记为“整本书已经讲完”。

## 阅读网页

课程初始化时会生成 `book-grilling.html`：

- 左侧保留作者的卷、部、章、节等真实目录；
- 已完成单元可完整回顾；
- 当前单元的问题树随进度逐题解锁；
- 未来单元只显示来源位置，不提前泄露答案；
- 支持桌面与手机、明暗主题、键盘操作、可见焦点和减少动态效果；
- 使用暖纸色、深青色完成状态和琥珀色当前状态的学术编辑界面；
- 不依赖外部字体、图标、前端框架或网络资源。

## 安装

需要 Codex 和 Python 3.9 或更高版本。运行时只使用 Python 标准库。

```bash
git clone https://github.com/zuoer552/socratic-map-learning.git \
  ~/.codex/skills/book-grilling
```

重新打开 Codex 或新建任务，然后点名使用：

```text
请使用 $book-grilling，沿着作者目录一次一问地带我系统读完这本书。
每个问题同时给出推荐答案，并把已经学完的单元显示成可回顾的问题树。
```

检查安装：

```bash
python3 ~/.codex/skills/book-grilling/scripts/book_grilling.py --help
cat ~/.codex/skills/book-grilling/VERSION
```

已经从旧仓库安装的用户可以在原目录执行 `git pull --ff-only`。目录名即使
仍是 `socratic-map-learning`，新触发名也已经变为 `$book-grilling`。

## 重要的升级说明

这是全新数据模型，不迁移旧 `.socratic-map` SQLite 课程。旧课程文件不会
被自动删除；要使用新机制，请为作品新建 Book Grilling 课程。

## 仓库结构

```text
book-grilling/
├── SKILL.md
├── README.md
├── VERSION
├── agents/
│   └── openai.yaml
├── assets/
│   └── reader-template.html
├── examples/
│   └── demo/
├── references/
│   ├── runtime-contract.md
│   ├── source-preparation.md
│   ├── teaching-loop.md
│   └── unit-preparation.md
├── scripts/
│   └── book_grilling.py
└── tests/
    └── test_book_grilling.py
```

## 本地验证

```bash
python3 -B -m unittest discover -s tests -v
python3 -B scripts/book_grilling.py --help
```

测试覆盖完整学习流程、逐题解锁、锁定答案脱敏、旧回执拒绝、复核门禁、
来源证据篡改、错误分支归档、目录顺序和学习单元范围重叠。

## 演示课程

`examples/demo/` 提供一套短小但完整的来源、目录、单元原文、问题树、
复核记录和学习回合，可用于检查运行时或网页：

```bash
python3 scripts/book_grilling.py init /tmp/book-grilling-demo \
  --manifest examples/demo/manifest.json
python3 scripts/book_grilling.py prepare-unit /tmp/book-grilling-demo \
  --tree examples/demo/unit-one-tree.json \
  --review examples/demo/unit-one-review.json \
  --source-text examples/demo/unit-one.txt \
  --expected-revision 0 \
  --expected-unit chapter-one
```

正式学习时不要把演示复核记录复用于真实作品。

## License

MIT
