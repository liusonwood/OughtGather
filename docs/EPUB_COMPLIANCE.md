# EPUB Compliance Guide

本文档详细记录了生成符合EPUB规范的电子书文件的经验教训，特别是使用ebooklib库时遇到的常见问题和解决方案。

## 目录

- [EPUB版本与规范](#epub版本与规范)
- [常见错误与解决方案](#常见错误与解决方案)
- [Kindle落点问题 - 打开时随机进入正文而非目录](#kindle落点问题---打开时随机进入正文而非目录)
- [验证工具](#验证工具)
- [最佳实践](#最佳实践)

---

## EPUB版本与规范

### EPUB 2.0 vs EPUB 3.0

| 特性 | EPUB 2.0 | EPUB 3.0 |
|------|---------|---------|
| 导航系统 | NCX文件（必需） | NCX + Nav Document（nav必需） |
| 元数据格式 | Dublin Core | Dublin Core + 新属性 |
| HTML版本 | XHTML 1.1 | HTML5/XHTML 1.1 |
| 文件目录 | 可选OEBPS/OPS | 推荐 `EPUB/` 目录 |
| 验证工具 | EPUBCheck 2.0规则 | EPUBCheck 3.3规则（默认） |
| 官方验证工具 | Amazon Kindle Previewer | Amazon Kindle Previewer |

### ebooklib的限制

**重要发现**：ebooklib 0.20版本**无法生成EPUB 2.0格式文件**。

```python
# ❌ 以下设置无效
book.version = '2.0'  # ebooklib忽略此设置

# ✅ 实际生成的OPF文件
# <package version="3.0">  # 硬编码为3.0
```

**原因分析**：
- `EpubWriter._write_opf()` 方法中硬编码了 `"version": "3.0"`
- 无法通过设置 `book.version` 属性来改变版本号
- 必须接受EPUB 3.0格式并满足其规范要求

---

## 常见错误与解决方案

### 错误1: RSC-026 - URL泄露到容器外部

**错误信息**：
```
ERROR(RSC-026): URL "/content.opf" leaks outside the container
(it is not a valid-relative-ocf-URL-with-fragment string)
```

**问题描述**：
生成的EPUB文件中所有路径都以 `/` 开头（绝对路径），违反OCF规范。

**错误示例**：
```python
# ❌ 错误的设置
book.FOLDER_NAME = ''
book.DEFAULT_PUBLICATION_DIR = ''

# 生成的文件结构（错误）
# - /content.opf       <- 绝对路径！
# - /cover.jpg
# - /cover.xhtml
# - /chapter_0.xhtml
```

**根本原因**：
ebooklib内部使用字符串拼接 `"FOLDER_NAME/{file_name}"`。当 `FOLDER_NAME=''` 时：
```python
# 内部拼接逻辑
path = f"{FOLDER_NAME}/{file_name}"
# 结果: "" + "/" + "content.opf" = "/content.opf"  <- 绝对路径
```

**解决方案**：
```python
# ✅ 正确的做法 - 保留默认值
# 不设置 FOLDER_NAME，使用默认值 'EPUB'

# 生成的文件结构（正确）
# - EPUB/content.opf   <- 相对路径
# - EPUB/cover.jpg
# - EPUB/cover.xhtml
# - EPUB/chapter_0.xhtml
```

**验证方法**：
```bash
unzip -l your_epub.epub | grep "^.*EPUB/"
# 应看到所有文件都在 EPUB/ 目录下
```

---

### 错误2: RSC-005 - 缺少nav属性声明

**错误信息**：
```
ERROR(RSC-005): Exactly one manifest item must declare the "nav" property
(number of "nav" items: 0)
```

**问题描述**：
EPUB 3.0规范要求manifest中必须有**且仅有**一个item声明 `properties="nav"`。

**错误代码**：
```python
# ❌ 只添加NCX，缺少nav document
book.add_item(epub.EpubNcx())

# 生成的manifest（错误）
# <item href="toc.ncx" id="ncx" media-type="application/x-dtbncx+xml"/>
# 缺少 nav 属性的声明
```

**解决方案**：
```python
# ✅ 同时添加NCX和Nav Document
book.add_item(epub.EpubNcx())     # EPUB 2.0兼容导航
book.add_item(epub.EpubNav())     # EPUB 3.0必需导航

# 生成的manifest（正确）
# <item href="nav.xhtml" id="nav" media-type="application/xhtml+xml" properties="nav"/>
# <item href="toc.ncx" id="ncx" media-type="application/x-dtbncx+xml"/>
```

**为什么需要两者**：
- `EpubNcx()`: 提供传统的NCX导航，兼容旧设备和EPUB 2.0阅读器
- `EpubNav()`: EPUB 3.0新增的导航文档，提供更丰富的导航功能和语义结构

---

### 错误3: CSS语法错误 - Python f-string中的大括号

**错误信息**：
```python
NameError: name 'margin' is not defined
```

**问题描述**：
在Python f-string中编写CSS代码时，CSS的大括号 `{}` 被Python解析为表达式占位符。

**错误代码**：
```python
# ❌ CSS中的大括号被Python解析为表达式
cover_html = f"""<!DOCTYPE html>
<html>
<head>
    <style>
        body { margin: 0; padding: 0; }  <- Python尝试执行 "margin"
        img { max-width: 100%; }        <- Python尝试执行 "max-width"
    </style>
</head>
<body>...</body>
</html>"""
```

**解决方案**：
```python
# ✅ 使用双大括号 {{}} 转义
cover_html = f"""<!DOCTYPE html>
<html>
<head>
    <style>
        body {{ margin: 0; padding: 0; }}  <- 字面意义的大括号
        img {{ max-width: 100%; }}
    </style>
</head>
<body>...</body>
</html>"""
```

**记忆技巧**：
- Python f-string: `{expression}` 用于表达式
- CSS语法: `{{property}}` 用于字面大括号
- 双写转义规则适用于所有f-string中的JSON、CSS等需要大括号的文本

---

### 错误4: RSC-016 - 封面文件过早结束

**错误信息**：
```
FATAL(RSC-016): cover.xhtml(-1,-1): Fatal Error while parsing file: Premature end of file.
```

**问题描述**：
生成的 `cover.xhtml` 文件为空（0字节），或内容未正确写入。

**错误示例**：
```bash
unzip -l your_epub.epub
# Length      Date    Time    Name
# ---------  ---------- -----   ----
#       0  06-15-2026 22:09   /cover.xhtml  <- 0字节！
```

**可能原因**：
1. SVG封装方式在某些情况下未正确写入内容
2. `EpubHtml.content` 属性未正确设置
3. 使用了过于复杂的HTML结构导致解析失败

**解决方案**：
```python
# ❌ 复杂的SVG封装（可能失败）
cover_html = """<svg xmlns="http://www.w3.org/2000/svg">
    <image xlink:href="cover.jpg" width="1440" height="1920"/>
</svg>"""

# ✅ 简单可靠的HTML结构
cover_html = f"""<!DOCTYPE html PUBLIC "-//W3C//DTD XHTML 1.1//EN" "http://www.w3.org/TR/xhtml11/DTD/xhtml11.dtd">
<html xmlns="http://www.w3.org/1999/xhtml">
<head>
    <title>Cover</title>
    <style type="text/css">
        body {{ margin: 0; padding: 0; text-align: center; }}
        img {{ max-width: 100%; height: auto; }}
    </style>
</head>
<body>
    <img src="{cover_filename}" alt="Cover"/>
</body>
</html>"""

cover_page = epub.EpubHtml(title='Cover', file_name='cover.xhtml', uid='cover')
cover_page.content = cover_html  # 确保设置content属性
book.add_item(cover_page)
```

---

### 错误5: 图片属性小数点错误

**错误信息**：
```
ERROR(RSC-005): value of attribute "height" is invalid;
must be a decimal number without any significant digits after the decimal point
```

**问题描述**：
图片的 `width` 或 `height` 属性值包含小数点，EPUB规范要求必须是整数。

**错误示例**：
```html
<!-- ❌ 小数点格式的尺寸 -->
<img src="image.jpg" width="120.5" height="798.67"/>
```

**根本原因**：
抓取的网页内容中，图片尺寸可能来自JavaScript动态计算或CSS样式，保留了小数点精度。

**解决方案**：
```python
# ✅ 在内容处理器中自动取整
for img in soup.find_all('img'):
    if 'width' in img.attrs:
        width_str = img.get('width', '').strip()
        if width_str:
            try:
                width = int(float(width_str))  # 取整
                img['width'] = str(width)
            except (ValueError, TypeError):
                del img['width']  # 无效值，删除属性

    if 'height' in img.attrs:
        height_str = img.get('height', '').strip()
        if height_str:
            try:
                height = int(float(height_str))  # 取整
                img['height'] = str(height)
            except (ValueError, TypeError):
                del img['height']  # 无效值，删除属性

# 生成的HTML（正确）
# <img src="image.jpg" width="120" height="798"/>
```

---

### 错误6: 非法HTML标签 - `<cell>`

**错误信息**：
```
ERROR(RSC-005): element "cell" not allowed here;
expected the element end-tag or element "script", "td", "template" or "th"
```

**问题描述**：
使用了非标准的 `<cell>` 标签（应该是 `<td>` 或 `<th>`）。

**错误示例**：
```html
<!-- ❌ 非标准的 <cell> 标签 -->
<table>
    <row>
        <cell>单元格1</cell>
        <cell>单元格2</cell>
    </row>
</table>
```

**根本原因**：
某些网页或邮件内容使用了自定义的HTML标签，不符合XHTML规范。

**解决方案**：
```python
# ✅ 自动转换为标准标签
for cell in soup.find_all('cell'):
    cell.name = 'td'  # 转换为标准表格单元格标签

for row in soup.find_all('row'):
    row.name = 'tr'  # 转换为标准表格行标签

# 生成的HTML（正确）
# <table>
#     <tr>
#         <td>单元格1</td>
#         <td>单元格2</td>
#     </tr>
# </table>
```

---

### 错误7: EPUB 3.0属性误用

**问题描述**：
EPUB 3.0引入了 `properties` 属性，但ebooklib在某些版本中处理不当。

**错误示例**：
```python
# ❌ EPUB 3.0特有属性（可能不兼容旧设备）
cover_item.properties = ['cover-image']

# 如果目标是最大化兼容性，应避免使用EPUB 3.0特有属性
```

**解决方案**：
```python
# ✅ 使用标准方式添加封面（兼容性好）
cover_item = epub.EpubItem(
    uid='cover-img',
    file_name=cover_filename,
    media_type='image/jpeg',
    content=cover_data
)
# 不设置 properties 属性，让ebooklib自动处理

# 在guide中声明封面（EPUB 2.0兼容方式）
book.guide = [
    {'href': 'cover.xhtml', 'title': 'Cover', 'type': 'cover'}
]
```

---

### 错误8: Kindle Previewer 转换失败 - <img> 属性包含 `<` / `>` / `&lt;` / `&gt;`

**错误信息**：
```
"Error","E21018: Enhanced Mobi building failure, while parsing content in the file. Content: <img> in file: .../chapter_x.xhtml line: y"
```

**问题描述**：
使用 Kindle Previewer 命令行工具进行电子书格式转换（`-convert`）时，某些章节会出现 `E21018` 解析错误，导致生成 Mobi/KPF 失败，但 EPUBCheck 却校验通过（无任何警告或错误）。

**根本原因**：
Kindle Previewer 内部的 HTML/XML 解析器存在严重缺陷。在解析 `<img>` 标签时，如果 `alt` 或 `title` 等属性中含有小于号 `<`、大于号 `>` 或其对应的转义实体 `&lt;`、`&gt;`，会被其预处理器误识别并截断（例如在预处理过程中将 `&gt;` 解密为 `>`，接着使用不健全的正则进行抓取），从而导致 `<img>` 标签的闭合被破坏，被误认作是一个未闭合的非法 `<img>` 标签。

**错误示例**：
```html
<!-- ❌ alt 属性包含 HTML 实体，会导致 Kindle 预处理断开报错 -->
<img src="images/image_1.jpg" alt="Security &gt; Settings" />
```

**解决方案**：
在生成 EPUB 时的内容处理（Content Processor）阶段，针对所有 `<img>` 标签的 `alt` 和 `title` 属性，自动剔除或替换 `<`, `>`, `&lt;`, `&gt;` 特殊字符。
```python
# ✅ 清理 alt 和 title 中的特殊字符
for img in soup.find_all('img'):
    for attr in ('alt', 'title'):
        if attr in img.attrs:
            val = img.get(attr, '')
            if isinstance(val, str):
                val_cleaned = val.replace('&gt;', ' - ').replace('&lt;', ' - ').replace('>', ' - ').replace('<', ' - ')
                img[attr] = val_cleaned
```

---

## Kindle落点问题 - 打开时随机进入正文而非目录

**现象**：EPUB 发送到 Kindle 后，打开时有时落在目录页（nav.xhtml），有时直接跳入第一篇正文，行为不稳定。

**根本原因**：Kindle 判断"首次打开落点"依赖**两套独立机制**，缺少其中任一都会导致随机行为：

| 机制 | 格式版本 | 作用范围 |
|------|---------|----------|
| OPF `<guide>` 里的 `type="start"` | EPUB 2.0 兼容 | 老旧 Kindle 固件 |
| `nav.xhtml` 里的 `epub:type="landmarks"` | EPUB 3.0 标准 | 新版固件 / Kindle App |

两者都缺失时，Kindle 会根据 `<spine>` 第一个条目自行决定落点，结果不可预期。

---

### 修复1：OPF Guide 新增 `type="start"`

**问题**：之前 `book.guide` 只有 `type="toc"` 和 `type="text"`，缺少 `type="start"`。老版 Kindle 固件读取 `guide` 里的 `start` 条目来决定"打开时跳到哪"。

```python
# 错误配置：缺少 type="start"
book.guide = [
    {'href': 'nav.xhtml', 'title': 'Table of Contents', 'type': 'toc'},
    {'href': 'cover.xhtml', 'title': 'Cover', 'type': 'cover'},
    {'href': 'nav.xhtml', 'title': 'Table of Contents', 'type': 'text'},
]

# 修复后的配置：新增 type="start" 指向目录页
book.guide = [
    {'href': 'nav.xhtml', 'title': 'Table of Contents', 'type': 'toc'},
    {'href': 'cover.xhtml', 'title': 'Cover', 'type': 'cover'},
    {'href': 'nav.xhtml', 'title': 'Table of Contents', 'type': 'text'},
    {'href': 'nav.xhtml', 'title': 'Start', 'type': 'start'},  # 新增
]
```

---

### 修复2：`nav.xhtml` 新增 `epub:type="landmarks"` 导航块

**问题**：EPUB 3.0 规范规定，`nav.xhtml` 应包含 `epub:type="landmarks"` 导航块来声明书籍各部分的语义起始位置。Kindle 新固件和 App 优先读取此块来决定"正文从哪里开始"。之前的实现只有 `epub:type="toc"` 块，缺少 landmarks。

```xml
<!-- 错误：只有 toc nav，无 landmarks -->
<nav epub:type="toc" id="toc">
    ...
</nav>
</body>

<!-- 修复后：toc nav 后面追加 landmarks nav -->
<nav epub:type="toc" id="toc">
    ...
</nav>

<!-- EPUB 3.0 landmarks: cover -> cover.xhtml, toc + bodymatter 均指向 contents.xhtml -->
<!-- Kindle 根据此块决定"打开时跳转到哪里"，hidden 使其不在阅读器目录中显示 -->
<nav epub:type="landmarks" id="landmarks" hidden="">
    <ol>
        <li><a epub:type="cover" href="cover.xhtml">Cover / 封面</a></li>
        <li><a epub:type="toc" href="contents.xhtml">Table of Contents / 目录</a></li>
        <li><a epub:type="bodymatter" href="contents.xhtml">Start of Content / 开始阅读</a></li>
    </ol>
</nav>
```

**关键设计决策**：
- `epub:type="bodymatter"` 和 `epub:type="toc"` 指向 `contents.xhtml`（而非非线性未入 spine 的 `nav.xhtml`），符合 EPUB 3.0 / 3.3 规范（landmarks 内资源必须属于 spine item），同时让 Kindle 认为"正文起始 = 目录页"。
- `hidden=""` 是 EPUB 3.0 规范要求的属性，表示此导航块不在阅读器 UI 的目录列表中展示，但仍被解析器读取生效。
- 两个 landmark 都指向同一个物理目录页文件，确保无论 Kindle 读哪个 landmark 都落在目录。

---

### 验证方法

```bash
# 解压并检查 nav.xhtml 是否包含 landmarks 块
unzip -p your_epub.epub EPUB/nav.xhtml | grep -A 8 'landmarks'

# 检查 OPF 中的 guide 是否包含 type="start"
unzip -p your_epub.epub EPUB/content.opf | grep 'type="start"'
```

预期输出（nav.xhtml）：

```xml
<nav epub:type="landmarks" id="landmarks" hidden="">
    <ol>
        <li><a epub:type="cover" href="cover.xhtml">Cover / 封面</a></li>
        <li><a epub:type="toc" href="contents.xhtml">Table of Contents / 目录</a></li>
        <li><a epub:type="bodymatter" href="contents.xhtml">Start of Content / 开始阅读</a></li>
    </ol>
</nav>
```

预期输出（content.opf）：

```xml
<reference href="nav.xhtml" title="Start" type="start"/>
```

## Kindle推送失败与内容错误排查

> 本部分内容总结自 [书伴文章：推送 EPUB 文件到 Kindle 的常见失败原因及解决方法](https://bookfere.com/post/992.html)

通过 Send to Kindle 推送 EPUB 到 Kindle 时，可能遇到两类问题：**推送失败**（收到亚马逊退信）和**内容出错**（推送成功但阅读体验异常）。以下逐一列出常见原因及解决方案。

---

### 一、导致推送失败的问题

推送失败时，通常会收到亚马逊标题为"您发送到 Kindle 的文档有问题"的退信。一个 EPUB 文件可能同时存在多个问题，需逐一排查。

#### 1. EPUB 中的某些文件不符合规范

亚马逊个人文档服务对 EPUB 的容错机制较强，但对 **toc.ncx**（EPUB 2.0 导航）和 **nav.xhtml**（EPUB 3.0 导航）两个文件比较敏感，如果它们存在错误，大概率会导致推送失败。

**解决方案**：
- 使用 Sigil 打开 EPUB 文件，点击菜单【工具（Tools）→ 目录（Table Of Contents）→ 生成目录…（Generate Table Of Contents…）】（快捷键：Windows `Ctrl+T` / macOS `Command+T`）重新生成目录。
- 注意：此方式可能会破坏目录层级，生成后需检查调整。
- 也可使用 [Sigil + EpubCheck 插件](https://bookfere.com/post/1004.html) 检测并修复 `content.opf` 和 `toc.ncx` 的所有问题。

#### 2. XHTML 文件名含空格和中文字符

如果 EPUB 中插入了广告页面，且文件名带有空格或中文字符，会导致推送失败。

**解决方案**：
- 用 Sigil 打开 EPUB，直接删除带空格和中文字符的 XHTML 页面并保存。

#### 3. OPF 文件中的 language 元素有误

`<dc:language>` 元素缺失、内容为空或指定了错误的语言代码（如 `und`）都会导致推送失败。

**解决方案**：
- 用 Sigil 打开 OPF 文件（通常为 `content.opf`），在 `<metadata>` 中添加或修改 `<dc:language>` 元素：
  ```xml
  <dc:language>zh</dc:language>
  ```
- 也可通过 Sigil 菜单【工具（Tools）→ 元数据编辑器…（Metadata Editor…）】添加"语言"元数据，选择"中文 – 中国（Chinese – China）"。
- 语言代码参考 [ISO 639-1](https://en.wikipedia.org/wiki/List_of_ISO_639-1_codes) 列表。

#### 4. OPF 文件中出现重复的 item 元素

OPF 文件的 `<manifest>` 中如果出现重复的 `<item>` 元素（相同 id 或 href），会导致推送失败。

**解决方案**：
- 使用 [KindleGen](https://bookfere.com/post/92.html) 转换有问题的 EPUB，它会提示具体哪个 item 重复，例如：
  ```
  Error(xmlmake):E27012: Item or process id already used: 180630.jpg
  ```
- 手动删除重复的 `<item>` 元素。

#### 5. 在 CSS 中隐藏的字符数超过了限制

Kindle 对 CSS 的 `display:none;` 声明有限制：隐藏内容区块中的字符**不能超过 10000 个**，否则会导致推送失败。

**解决方案**：
- 删除 CSS 文件中所有 `display:none;` 声明。

#### 6. XHTML 中的元素含有不兼容属性

某些属性（如 `data-amznremoved`）会导致亚马逊服务器处理失败。

**解决方案**：
- 检查并移除 XHTML 中所有类似 `data-amznremoved` 的不兼容属性。

#### 7. XHTML 文件中的 body 标签含 ID

在 `toc.ncx` 中，如果 `<content>` 元素的 `src` 属性指向的 XHTML 路径包含 URL 片段（如 `text/part0001.html#test_1`），且对应的 `id` 在 `<body>` 元素上，可能导致推送失败。

**解决方案**：
- 将 `<body>` 上的 `id` 移至其子元素上。
- 或直接删除路径中的片段部分（`#` 及其后字符）。

#### 8. NCX 文件中包含的导航目录条目过多

如果 `toc.ncx` 中的 `<navPoint>` 条目**超过 1321 条**，大概率会推送失败。这是亚马逊服务器端的限制。

**解决方案**（变通方案）：
- **删减目录层级**：编辑 NCX 文件，减少 `<navPoint>` 元素数量。缺点：影响 Kindle 目录导航功能。
- **分割电子书**：将 EPUB 文件[分割成多份](https://bookfere.com/post/603.html)。缺点：增加工作量。

---

### 二、导致内容出错的问题

推送成功但阅读体验异常时，可按以下问题排查。

#### 1. 电子书内容出现乱码

中文电子书全部乱码，或英文电子书部分标点符号乱码。通常是因为 XHTML 文件**没有指定 UTF-8 编码**。

**解决方案**：
- 用 Sigil 打开 EPUB，点击菜单【工具（Tools）→ HTML 重新格式化（Reformat HTML）→ 改进所有 HTML 文件（Mend All HTML Files）】，让 Sigil 自动修补所有 HTML 文件，保存后重新推送。

#### 2. 电子书目录层级有误

目录层级与预期不符。

**解决方案**：
- 用 Sigil 的目录编辑功能【工具（Tools）→ 目录（Table Of Contents）→ 编辑目录…（Edit Table Of Contents…）】调整：
  - 上下方向键选中标题
  - `Ctrl` + 上下方向键调整顺序
  - 左右方向键调整缩进（层级）

#### 3. 电子书导航目录缺失

推送后 Kindle 的"前往"功能无法进行目录导航。常见原因：
- `toc.ncx` 中的 URI 包含片段（如 `text/part0001.html#UGI0-1af7590487e04e47b91ab6bb431b89f3`），亚马逊服务器在转换时丢失了导航目录。
- EPUB 3.0 文件不包含 `.ncx` 文件，亚马逊服务器可能不支持这种导航格式。

**解决方案**：
- **删除 URI 片段**：用 Sigil 打开 `toc.ncx`，使用正则表达式 `#[^"]*` 查找，替换为空，全部替换后保存。
- **重新生成目录**：点击菜单【工具（Tools）→ 目录（Table Of Contents）→ 生成目录…（Generate Table Of Contents…）】。
- **格式转换**：用 Calibre 先将 EPUB 转成 AZW3，再转回 EPUB，有时可解决。
- **降级为 EPUB 2.0**：如果 EPUB 3.0 缺少 NCX 文件，用 Calibre 转换成 EPUB 2.0 再推送。

#### 4. 电子书字体显示异常

推送到 Kindle 后字体不一致（黑体宋体掺杂），通常是因为电子书的**实际语言与元数据中的语言不一致**。

**解决方案**：
- 用 Sigil 或 Calibre 的元数据编辑功能，将语言修改为与实际文本一致（参考上文"OPF 文件中的 language 元素有误"）。


---

## 验证工具

### EPUBCheck

**官方工具**：W3C EPUBCheck是验证EPUB文件是否符合规范的权威工具。

#### 安装方法

1. **下载EPUBCheck**：
   ```bash
   # 从官方GitHub下载最新版本
   wget https://github.com/w3c/epubcheck/releases/download/v5.3.0/epubcheck-5.3.0.zip
   unzip epubcheck-5.3.0.zip
   ```

2. **确保Java环境**：
   ```bash
   java -version  # 需要Java 8或更高版本
   ```

#### 使用方法

```bash
# 基本验证（默认使用EPUB 3.3规则）
java -jar epubcheck.jar your_epub.epub

# 详细输出
java -jar epubcheck.jar your_epub.epub --mode exp -v 3.0

# 输出JSON报告
java -jar epubcheck.jar your_epub.epub --json report.json

# 输出XML报告
java -jar epubcheck.jar your_epub.epub --out report.xml
```

#### 验证结果解读

```
Messages: 0 fatals / 0 errors / 0 warnings / 0 infos
EPUBCheck completed

✓ 上述输出表示完全符合规范
```

```
Messages: 1 fatal / 2 errors / 0 warnings / 0 infos
EPUBCheck completed

✗ 存在致命错误或错误，必须修复
```

### 常见EPUBCheck错误代码

| 错误代码 | 说明 | 严重程度 | 出现章节 |
|---------|------|---------|---------|
| RSC-005 | OPF manifest缺少必需属性 / HTML元素嵌套错误 | Error | 多处 |
| RSC-016 | XHTML文件解析失败（文件为空） | Fatal | cover.xhtml |
| RSC-026 | URL路径泄露到容器外部（绝对路径） | Error | 所有文件 |
| RSC-007 | 引用的资源未找到 | Error | content.opf |
| OPF-031 | guide元素引用未声明的文件 | Error | content.opf |
| HTM-010 | HTML属性值无效（小数点等） | Error | chapter_x.xhtml |

**注意**：同一个错误代码可能对应多个不同的问题，如 RSC-005 既可能表示缺少nav属性，也可能表示HTML嵌套错误。

### Kindle Previewer

**官方工具**：Amazon Kindle Previewer 是一款可以模拟 Kindle 设备和阅读软件上书籍排版展示的官方工具。它同样包含命令行界面，可用于自动化验证 EPUB 文件转换为 Kindle 专有格式（Mobi/KF8/KPF）的正确性。

#### 使用方法

```bash
# 将 EPUB 转换为 Kindle 格式以验证文件正确性
kindlepreviewer "/path/to/book.epub" -convert
```

#### 验证结果解读

如果转换成功，控制台将输出以下类似内容，并在指定的输出目录生成对应的 KPF 电子书和转换 Logs：
```
Pre-processing in progress.
Processing 1/1 book(s).
Book converted successfully! : /path/to/book.epub
Post-processing in progress.
```

如果转换失败，则会提示转换失败并在输出的 Logs 目录中生成对应的错误详情 CSV 报告（如 E21018）：
```
Pre-processing in progress.
Processing 1/1 book(s).
Book Conversion failed. /path/to/book.epub
```

---

## 最佳实践

### 1. 文件结构规范

```
your_epub.epub (ZIP压缩包)
├── mimetype                     (必需，第1个文件，不压缩)
├── META-INF/
│   └── container.xml           (必需，指向OPF文件)
└── EPUB/                        (推荐目录名)
    ├── content.opf              (必需，元数据和manifest)
    ├── toc.ncx                  (EPUB 2.0导航)
    ├── nav.xhtml                (EPUB 3.0导航，必需)
    ├── cover.jpg                (封面图片)
    ├── cover.xhtml              (封面页面)
    ├── chapter_0.xhtml          (内容文件)
    ├── chapter_1.xhtml
    ├── style/
    │   └── default.css          (样式文件)
    └── images/
        ├── image1.jpg           (图片资源)
        └── image2.jpg
```

### 2. ebooklib最佳配置

```python
from ebooklib import epub

# ✅ 推荐配置
book = epub.EpubBook()

# 元数据设置
book.set_identifier(str(uuid.uuid4()))
book.set_title('Book Title')
book.set_language('zh')
book.add_author('Author Name')

# 导航文件（EPUB 3.0必需）
book.add_item(epub.EpubNcx())  # NCX导航
book.add_item(epub.EpubNav())  # Nav Document（必需）

# Guide元素（兼容性 + Kindle落点控制）
book.guide = [
    {'href': 'nav.xhtml', 'title': 'Table of Contents', 'type': 'toc'},
    {'href': 'cover.xhtml', 'title': 'Cover', 'type': 'cover'},
    {'href': 'nav.xhtml', 'title': 'Table of Contents', 'type': 'text'},
    # type="start"：Kindle 专认的"打开时跳转到"标志
    {'href': 'nav.xhtml', 'title': 'Start', 'type': 'start'},
]

# 不修改FOLDER_NAME，保留默认 'EPUB'
# book.FOLDER_NAME = 'EPUB'  # 默认值

# 保存
epub.write_epub('output.epub', book, {})
```

### 3. XHTML文件模板

```python
# ✅ EPUB 3.0兼容的XHTML模板
def generate_xhtml_content(title, body_content):
    safe_title = html.escape(title)
    
    return f"""<!DOCTYPE html PUBLIC "-//W3C//DTD XHTML 1.1//EN" "http://www.w3.org/TR/xhtml11/DTD/xhtml11.dtd">
<html xmlns="http://www.w3.org/1999/xhtml" xml:lang="zh">
<head>
    <title>{safe_title}</title>
    <link rel="stylesheet" type="text/css" href="style/default.css"/>
</head>
<body>
    <h1>{safe_title}</h1>
    <div class='content'>
        {body_content}
    </div>
</body>
</html>"""
```

### 4. CSS样式模板

```python
# ✅ f-string中的CSS编写
css_content = """
body {{
    font-family: serif;
    line-height: 1.6;
    margin: 1em;
}}
h1 {{
    font-size: 1.5em;
    color: #333;
}}
.content {{
    text-align: justify;
}}
img {{
    max-width: 100%;
    height: auto;
}}
"""
```

### 5. 图片处理最佳实践

```python
# ✅ 图片添加到EPUB的正确方式
def add_image_to_epub(book, image_url, article_url, chapter_content):
    # 下载和处理图片
    filename, img_data = download_and_process_image(image_url, article_url)
    
    # 检查是否已添加（避免重复）
    image_uid = f"image_{filename}"
    if not any(item.id == image_uid for item in book.items):
        # 添加图片item
        epub_image = epub.EpubItem(
            uid=image_uid,
            file_name=f"images/{filename}",
            media_type="image/jpeg",
            content=img_data
        )
        book.add_item(epub_image)
    
    # 更新HTML中的图片引用（相对路径）
    # <img src="images/filename.jpg"/>
```

---

## 问题排查流程

当EPUBCheck报告错误时，按以下流程排查：

### Step 1: 检查文件结构
```bash
unzip -l your_epub.epub
```
- 确认所有文件都在 `EPUB/` 目录下（无 `/` 前缀的绝对路径）
- 确认 `mimetype` 是第一个文件
- 确认文件大小合理（无0字节文件）

### Step 2: 检查OPF文件
```bash
unzip -p your_epub.epub EPUB/content.opf
```
- 确认 `version="3.0"`（无法改为2.0）
- 确认manifest中有 `properties="nav"` 的item
- 确认所有XHTML文件都在manifest中声明

### Step 3: 检查XHTML文件
```bash
unzip -p your_epub.epub EPUB/cover.xhtml | head -20
```
- 确认有正确的DOCTYPE声明
- 确认有完整的 `<html>` 结构
- 确认内容不为空

### Step 4: 使用EPUBCheck详细输出
```bash
java -jar epubcheck.jar your_epub.epub --json report.json
cat report.json
```

---

## 参考资源

- [EPUB 3.3 规范](https://www.w3.org/TR/epub-33/) - W3C官方规范文档
- [EPUBCheck官方文档](https://github.com/w3c/epubcheck) - 验证工具文档
- [ebooklib GitHub](https://github.com/aerkalov/ebooklib) - Python库源码
- [EPUB最佳实践](https://github.com/IDPF/epub3-samples) - 官方示例文件
- [Kindle-Previewer下载](https://www.amazon.com/Kindle-Previewer/b?node=21381691011) - 官方验证工具

---

## 总结

### 关键要点

1. ✅ **接受EPUB 3.0格式** - ebooklib无法生成EPUB 2.0
2. ✅ **使用标准目录结构** - 保留 `FOLDER_NAME='EPUB'` 默认值
3. ✅ **添加nav document** - EPUB 3.0必需，用 `EpubNav()`
4. ✅ **转义CSS大括号** - 在f-string中使用 `{{}}`
5. ✅ **简化HTML结构** - 避免复杂的SVG封装
6. ✅ **清理非法标签** - `<cell>` → `<td>`，`<row>` → `<tr>`
7. ✅ **取整图片属性** - `width` 和 `height` 必须是整数
8. ✅ **修复嵌套结构** - `<p>` 内不能有块级元素
9. ✅ **验证EPUB文件** - 使用EPUBCheck确保合规
10. ✅ **Kindle落点控制** - OPF guide 加 `type="start"` + nav.xhtml 加 `epub:type="landmarks"` 块，确保打开时总是进入目录
11. ✅ **清理图片描述中的特殊字符** - 清理 `alt` / `title` 属性中的 `<` / `>` 防止 Kindle Previewer 报错 (E21018)

### 验证成功的标志

```bash
$ java -jar epubcheck.jar output.epub
Validating using EPUB version 3.3 rules.
No errors or warnings detected.
Messages: 0 fatals / 0 errors / 0 warnings / 0 infos
EPUBCheck completed
```

看到上述输出，说明EPUB文件完全符合规范，可以安全地发送到Kindle和其他电子阅读器。