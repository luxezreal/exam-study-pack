# 期末复习与真题汇编

`exam-study-pack` 是一个 Codex skill，根据用户提供的课件、教材和试卷制作考试资料。

| 用途 | 输出重点 |
| --- | --- |
| 期末复习讲义 | 课程范围、基础概念、解题步骤、完整例题、自测与答案 |
| 开卷考试速查 | 概念与题型索引、公式适用条件、方法卡片、页码导航与限页排版 |
| 历年真题汇编 | 按完整任务去重，保留原题和已有答案截图，每题后紧跟答案，必要时用 LaTeX 补答或勘误 |

## 安装

需要已安装 Codex。尚未安装此 skill 时，可将仓库克隆到个人技能目录：

```bash
mkdir -p "$HOME/.codex/skills"
git clone https://github.com/luxezreal/exam-study-pack.git "$HOME/.codex/skills/exam-study-pack"
```

私有仓库需要具有访问权限的 GitHub 登录。已有同名目录时先检查现有版本；上述命令不会覆盖它。安装后，在新对话中调用 `$exam-study-pack`，并提供相关材料。

## 使用示例

```text
用 $exam-study-pack，结合这些课件、教材和历年真题，制作适合第一次学习的期末复习讲义，包含完整例题和自测答案。
```

```text
用 $exam-study-pack，整理一份最多 10 页 A4 的开卷考试资料。按概念和题型建立索引，写清公式条件，保证打印后可读。
```

```text
用 $exam-study-pack，把这些历年试卷去重合成一个 PDF。题目从原文件截图，有答案的截取原答案；没有答案或答案过简的用 LaTeX 补写，每道题后紧跟答案。
```

## 可选的裁图与校验工具

skill 的说明和模板可独立使用。需要原题截图汇编时，附带的 Python 脚本提供检查、裁图、LaTeX 排版和源像素校验。

依赖：

- Python 3.9 或更新版本。
- PyMuPDF（安装包名 `PyMuPDF`，导入名 `fitz`）。
- 编译 PDF 时另需可用的 XeLaTeX/latexmk、ctex、Fandol 和模板引用的常用 TeX 包；脚本不会自动安装 TeX。

可在自己的工作目录中准备 Python 环境：

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -r "$HOME/.codex/skills/exam-study-pack/requirements.txt"
python "$HOME/.codex/skills/exam-study-pack/scripts/exam_pdf.py" --help
```

执行顺序为 `inspect` → 人工确定题目边界及去重清单 → `validate` → `render` → `tex` → 编译 → `verify`。完整命令、清单示例和坐标约定见 [清单格式与辅助脚本](references/manifest.md)。

脚本不自动判断语义重复或答案正确性。像素核验只能确认清单选定的源截图及其嵌入，仍需检查裁框是否完整、题答是否匹配以及最终 PDF 是否可读。旋转页或非默认裁剪区域会被明确拒绝，应使用支持该几何的工具或可追溯的规范化副本。

## 文件导航

- [SKILL.md](SKILL.md)：技能入口、用途选择和交付检查。
- [学习讲义与开卷速查](references/study-openbook.md)：两种资料的组织方法。
- [原卷与随题答案](references/source-papers.md)：去重、源截图和答案编排规则。
- [清单格式与辅助脚本](references/manifest.md)：裁图工具的接口和验证边界。
- [讲义模板](assets/handout.tex)、[速查模板](assets/openbook.tex)：可复制后填入实际内容的 LaTeX 起点。

仓库包含通用说明、工具和模板。实际课程资料和生成的考试资料在各自任务目录中处理。
