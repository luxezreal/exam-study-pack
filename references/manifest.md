# 原题裁图清单与辅助脚本

仅在需要原题/原答案截图汇编时读本文件。脚本路径是 skill 内的 `scripts/exam_pdf.py`，需当前 Python 能 `import fitz`（PyMuPDF）。它不安装 Python 包或 TeX，不识别题目语义，也不自动决定去重。

## 坐标与路径

- `page` 为源 PDF 的**物理页码，从 1 起**，不是纸面页码。
- `rect` 为 `[左, 上, 右, 下]`，单位 PDF 点（72点=1英寸），原点在页左上。必须从实际渲染页确认，留足上下标、图边、表底线和跨页续文。
- 裁图只支持未旋转、MediaBox 原点为零且 CropBox=MediaBox 的页。`inspect` 会报告几何数据；被引用页不符合时脚本明确拒绝。需要时另建规范化派生 PDF，记录其与原文件/页码的对应关系，再针对派生页重新选框；不要修改原文件后沿用旧坐标。
- `source_root` 相对 manifest 所在目录解析，仅影响 `sources.*.path`。缺省为 `.`。绝对源路径也允许。
- `supplement` 相对 manifest 所在目录解析；它是已有的 `.tex` 片段，不是另一份完整文档。片段可用常规 AMS 数学、表格、TikZ、forest、listings，以及 `\suppnote{...}`。片段内若再引用其他资源，须自行使用可靠路径。
- id 使用 ASCII 字母、数字、点、下划线、连字符，不能含路径分隔符；显示标题/标签可以用中文。TeX 项目输出路径及其图片/补答引用路径不能包含花括号、百分号、反斜杠或换行；这些路径会被明确拒绝。源PDF路径只参与Python读取，文件名中的百分号本身不受此TeX限制。

## 可直接改的最小 manifest

下面是假想源文件与坐标；先用实际源页替换，不能直接把示例框当成正确题目边界。

```json
{
  "title": "课程真题与随题答案",
  "source_root": "sources",
  "sources": {
    "paper": {"path": "paper.pdf", "role": "question", "label": "原卷"},
    "key": {"path": "key.pdf", "role": "answer", "label": "参考答案"}
  },
  "units": [
    {
      "id": "q01",
      "label": "第一题",
      "title": "原题简短索引名",
      "section": "某年试题",
      "question": [{"source": "paper", "page": 1, "rect": [50, 100, 540, 260]}],
      "answer": [{"source": "key", "page": 2, "rect": [50, 90, 540, 330]}],
      "supplement": "answers/q01.tex",
      "notes": "源答案保留，补充区解释计算过程。"
    },
    {
      "id": "q02",
      "label": "另一年第一题",
      "title": "同一完整任务的重复问法",
      "question": [{"source": "paper", "page": 3, "rect": [50, 100, 540, 260]}],
      "answer": [],
      "duplicate_of": "q01",
      "dedup_reason": "已逐项比较题干、数据、条件及小问，q01完整覆盖此题要求。"
    }
  ]
}
```

保留项必须有非空 `question`。`answer` 可以是空数组，但成稿必须有源答案图或现存 `supplement`。没有额外补答时省略 `supplement`，不要填空字符串。多个截图片段按数组顺序放置；先放本题全部题图片段，再放其全部答案图片段及补答，接着进入下一题。独立编号小题应分别建 unit；只有共用题干且相互依赖的小问才在用户允许时保留为题组。

删除项需 `duplicate_of` 和非空 `dedup_reason`。目标必须直接指向保留项；不接受自指、环或链。只因考点、图形模板或变量改名相似，不足以自动删题；脚本只检查记录结构，**不证明语义去重正确**。

`section` 可省略，缺省放入“试题与随题答案”。清单顺序就是成稿顺序，同一 section 应连续排列。源文件 role 仅是说明，不限制从答案文件截出其中实际保留的题干；这类情况应在 notes 写明。

## 命令

在工作目录运行，`SKILL` 表示此 skill 的绝对目录；不要把示例中的尖括号原样复制。

```bash
python3 "$SKILL/scripts/exam_pdf.py" inspect sources/paper.pdf sources/key.pdf --out inspection --pages 1-2
python3 "$SKILL/scripts/exam_pdf.py" validate manifest.json
python3 "$SKILL/scripts/exam_pdf.py" validate manifest.json --ready
python3 "$SKILL/scripts/exam_pdf.py" render manifest.json --out build --dpi 180
python3 "$SKILL/scripts/exam_pdf.py" tex manifest.json --build build --out build/main.tex
```

`inspect` 不带 `--out` 时只输出几何与文本/图片数量；带 `--out` 时保存文本索引与逐页元数据。`--pages 1,3-5` 在该目录另外保存选定页 PNG，按每个 PDF 的物理页码解释。不指定 `--pages` 就不批量渲染整本书。文字层少不等于空白页，提取文字也不代替查看公式和图形。

`validate` 默认允许草稿暂未配答案，列出 `unanswered_units`；`--ready`、`render` 和 `tex` 会拒绝缺答案的保留题。指定了 supplement 时，即使草稿也要求文件已存在。修改 manifest 或源文件后应重新 render；tex/verify 会拒绝旧的渲染缓存，也会核对缓存图片的像素摘要。显式输出路径不能覆盖manifest、源PDF、补答片段或当前必需的渲染资源。`render` 生成源裁图与 `render.json`，不动源 PDF。

用可用的 LaTeX 技能或已有工具链编译，例：

```bash
cd build
latexmk -xelatex -interaction=nonstopmode -halt-on-error main.tex
```

生成器使用 ctexbook、发行版自带 Fandol 和常用 TeX 包。图片按源PDF点尺寸显示，默认最多放大1.25倍，并同时受正文宽度与页高上限限制；窄评分条不会被强行撑满整页。需要改变这一上限时用 `tex --max-upscale 1.5` 等显式设置。应从主 TeX 所在目录编译。源码引用所选 build 与补答的绝对路径；如果要跨机器分享，应一起打包资源并改成可用相对路径。脚本不自动复制或发布任何源材料。

```bash
python3 "$SKILL/scripts/exam_pdf.py" verify manifest.json --build build --pdf build/main.pdf
```

基础版式按新题换页，便于逐题刷题。若用户有页限或希望密集简答顺排，可编辑生成的TeX减少换页，保留原图顺序与闭合的 `[id]` 题答标记，再编译、核验和检查可读性；不要把默认模板当成必须遵守的考试资料格式。

## 验证的含义与边界

默认 strict 验证：

1. 从清单指定的源页/框以同一 DPI 重新渲染，确认与保存裁图的尺寸和像素摘要相同。
2. 确认最终 PDF 的所有图片帧摘要多重集与源裁图相同，并且出现顺序符合题图→原答图的清单顺序。
3. 确认每个生成的“题目原文 / [id]”“本题答案 / [id]”标记恰好一次且先后顺序正确。
4. 检查图片框没有越过最终页面范围，输出 `verification.json` 与最终 PDF SHA256。

如果有单独的封面图或补答图片，strict 会拒绝额外图像。仅在这些额外图像确为预期、并另行审查时使用 `--allow-extra-images`；结果会明确显示 `passed-source-subset` 与 `all_pdf_images_accounted_for=false`，不能再宣称全部图片均是源截图。TikZ/forest 的矢量图通常不算额外栅格图。

这不证明选框没有漏掉题干外的条件，不证明原答案正确，也不替代视觉检查字号、跨页代码、表底线、图形连线或题目语境。对于自定义排版、重采样/有损压缩过的 PDF，像素摘要或可见标记可能不匹配；应明确改用何种可追溯核验，不把失败改成虚假的通过。不要用重新生成的题目图片冒充原题。
