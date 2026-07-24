<div align="center">

# 📖 Ought Gather

**自动化信息聚合工具，支持将 RSS、网页、邮件等定时打包为 EPUB 推送至 Kindle**

[![Daily Gather](https://github.com/liusonwood/oughtgather/actions/workflows/daily-gather.yml/badge.svg)](https://github.com/liusonwood/oughtgather/actions/workflows/daily-gather.yml)
[![Python 3.11+](https://img.shields.io/badge/Python-3.11%2B-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![License: AGPL v3](https://img.shields.io/badge/License-AGPL%20v3-blue.svg)](LICENSE)
[![EPUB 3.0](https://img.shields.io/badge/EPUB-3.0-6f42c1)](docs/EPUB_COMPLIANCE.md)
[![Kindle Delivery](https://img.shields.io/badge/Kindle-Email%20Delivery-orange)](#github-actions-部署)

🌐 [简体中文](./README.md) | [English](./README_EN.md)

</div>

Ought Gather 是一个 Python 自动化信息聚合工具。它从 RSS、网页、newsletter、稍后阅读 等可自定义内容源收集内容，每天定时发送到 Kindle 阅读。


<p align="center">
  <img src="img/Kindle_img0.jpg" alt="Kindle preview 0" width="23%">
  <img src="img/Kindle_img1.jpg" alt="Kindle preview 1" width="23%">
  <img src="img/Kindle_img2.jpg" alt="Kindle preview 2" width="23%">
  <img src="img/Kindle_img3.jpg" alt="Kindle preview 3" width="23%">
</p>

## 功能

- 内置四类内容源：`rss`、`web`、`mail`、`trending`
- 可以用插件的形式添加自定义内容源
- 使用 GitHub actions ，无需自己服务器
- 自动 Emoji 渲染：将文档中的 Emoji 动态渲染为黑白 PNG 图片，确保在 Kindle 等各类水墨屏阅读器上完美显示
- 支持按源设置优先级、链接保留、全文抓取、HTML 过滤和标题关键词删除
- 生成 EPUB 3.0 文件，包含封面、目录、正文和推送汇总章节
- 封面可使用自定义图片；未配置时尝试使用 Bing 每日壁纸，失败后使用纯色背景
- 支持标题日期占位符 `{time}` 和封面标题换行标记 `</br>`
- 使用 `fetched_urls.txt` 记录已处理内容；记录超过 500000 条时保留最新记录
- 支持通过 `CONFIG_JSON` 环境变量提供完整配置，避免把私有源写入仓库
- 支持 `Cloudflare Workers` 配置actions外部触发器，准时推送

## 环境要求

- Python 3.11+
- 依赖见 `requirements.txt`
- Kindle 推送需要可用的 SMTP 邮箱
- `各内容源` 需要各自配置 `***_API_KEY`

---

## GitHub Actions 部署（推荐）

工作流文件是 [.github/workflows/daily-gather.yml](.github/workflows/daily-gather.yml)，每天定时运行一次，也可以手动触发。工作流会安装依赖、准备 `config.json`、执行 `python src/main.py`、提交去重记录，并把生成的 EPUB 作为 artifact 保留 7 天。

### 部署步骤

**1. Fork 仓库**

在 GitHub 页面点击 `Fork`，把项目复制到自己的账号下。

**2. 配置内容源及环境变量**

[可视化配置内容源](https://liusonwood.github.io/OughtGather/)

见下方 [Secrets 配置](#secrets-配置) 一节。

**3. 手动触发一次**

```text
Actions -> Daily Gather -> Run workflow
```

成功运行后：

- `output/` 中生成 EPUB，并作为 artifact 上传（保留 7 天）
- EPUB 通过邮件发送到 `KINDLE_EMAIL`
- `data/fetched_urls.txt` 在actions缓存，用于下次去重

### 修改运行时间

通过 Cloudflare Workers 定时触发 GitHub Actions，触发时间比 GitHub 自带的 `schedule` 更精准（误差通常在 1 分钟以内）。`schedule` 保留为保底备用，且会在外部触发后 12 小时内自动跳过，避免重复执行。

#### 配置外部触发器（推荐）

**第一步：修改运行时间代码**

修改 `wrangler.toml` 中的 Cron 时间为你需要的触发时间（UTC 时区）：

```toml
[triggers]
crons = ["30 23 * * *"]  # UTC 23:30，即北京时间早上 7:30
```

**第二步：在 Cloudflare 仪表板关联仓库**

1. 登录 [Cloudflare 仪表板](https://dash.cloudflare.com)，进入 **Workers & Pages** → **Create** → **Connect to Git**
2. 授权 GitHub，选择此仓库
3. 将 **Root directory** 设置为 `/cloudflare-worker`，**Build command** 留空
4. 点击 **Save and Deploy**

**第三步：配置环境变量**

在 Worker 的 **Settings** → **Variables** 中添加以下三个变量：

| 变量名 | 说明 |
|:---|:---|
| `GITHUB_OWNER` | 你的 GitHub 用户名 |
| `GITHUB_REPO` | 仓库名称（例如 `oughtgather`） |
| `GITHUB_PAT` | GitHub Personal Access Token（需要 `repo` 权限，建议加密保存） |

>注：关于 GITHUB_PAT (Personal Access Token)，在 [GitHub Token 申请页面](https://github.com/settings/tokens/new) 生成。勾选上 repo 权限范围即可。

**验证**：访问 Worker 链接（`https://<worker-name>.<subdomain>.workers.dev/`），页面显示 `GitHub Actions trigger sent successfully!` 即为成功。

#### schedule定时触发

定时触发由 `on.schedule` 的 `cron` 字段控制，使用 UTC（建议时间与外部触发器时间相同）：

```yaml
on:
  schedule:
    - cron: '0 0 * * *'   # UTC 00:00，北京时间约 08:00
  workflow_dispatch:
```

> **注意**：工作流里的 `TZ: Asia/Shanghai` 只影响程序内部的日期和日志，不影响 cron 触发时间。实际触发时间以 GitHub Actions 运行记录为准，可能与 cron 语义有偏差。

### 去重缓存机制（无需开启写入权限）

由于项目引入了 `actions/cache` 机制，去重数据 `data/fetched_urls.txt` 会自动加密保存在 GitHub 的缓存服务器中。

### 排查失败

<details>
<summary><b>排查发送失败</b></summary>

| 现象 | 常见原因 |
| --- | --- |
| 配置准备步骤失败 | `CONFIG_JSON` 不是合法 JSON |
| SMTP 登录失败 | 账号、密码、端口或授权码错误 |
| 邮件发出但 Kindle 未收到 | 发件邮箱未加入 Kindle 认可发件人列表 |
| `Send to Kindle` 网页端显示失败 | EPUB生成兼容性问题，请提交反馈报告问题 |
| 没有生成 EPUB | 内容源无新文章 |
</details>

---

## Secrets 配置

在 GitHub 仓库的 `Settings -> Secrets and variables -> Actions` 中配置，本地开发时通过环境变量设置。

### 必要变量

| Secret / 环境变量 | 说明 |
| --- | --- |
| `CONFIG_JSON` | 完整的 `config.json` 字符串；优先级高于项目根目录的 `config.json` 文件。推荐在 GitHub Actions 中使用，可避免将私有内容源写入仓库 |
| `KINDLE_EMAIL` | Kindle 接收邮箱（`@kindle.com`） |
| `SMTP_HOST` | 发件邮箱 SMTP 服务器地址，如 `smtp.gmail.com` |
| `SMTP_PASSWORD` | 发件邮箱密码或应用授权码 |
| `SMTP_PORT` | 发件邮箱 SMTP 端口；`465` 使用 SSL，`587` 使用 STARTTLS |
| `SMTP_USERNAME` | 发件邮箱账号 |
| `WEBDAV_ENABLED` | 设置为 `true` 以启用 WebDAV 上传 |
| `WEBDAV_PASSWORD` | WebDAV 密码 |
| `WEBDAV_REMOTE_PATH` | 远程存储路径，默认 `/` |
| `WEBDAV_URL` | WebDAV 服务器地址 |
| `WEBDAV_USERNAME` | WebDAV 用户名 |


### Fetcher 自定义变量

| Secret / 环境变量 | 说明 |
| --- | --- |
| `OPENROUTER_API_ENDPOINT` | 自定义 OpenRouter 兼容接口，默认 `https://openrouter.ai/api/v1/chat/completions`。 |
| `OPENROUTER_API_KEY` | OpenRouter API 密钥，用于调用 LLM 生成热点分析。 |
| `OPENROUTER_MODEL` | 使用的 LLM 模型名称。 |
| `QWEATHER_HOST` | 和风天气 API 主机地址。 |
| `QWEATHER_KEY` | 和风天气 API 密钥，用于获取天气数据。 |
| `RAINDROPIO_API_KEY` | Raindrop.io 的 API 访问密钥。 |
| `TAVILY_API_KEY` | Tavily API 密钥，用于搜索热点信息。 |
| `TESTMAIL_APP_API_KEY` | 从 testmail.app 获取的 API Key，用于邮件抓取。 |

- **[SEND TO KINDLE](https://www.amazon.com/sendtokindle)**：Kindle 侧需要在亚马逊账号设置里，把发件邮箱加入「已认可的发件人电子邮箱列表」，否则推送不会被接收。
- **WebDAV**：用于非kindle设备，生成的 EPUB 自动同步至 WebDAV 云端（如坚果云、Nextcloud、本地 NAS 等）。

---
## config.json 说明

完整字段说明见 [docs/CONFIG.md](docs/CONFIG.md)

<details>
<summary>以下是核心结构速览</summary>

### 顶层字段

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `title` | object | ✓ | EPUB 标题和封面配置 |
| `limit` | int | | 每个内容源的默认抓取上限，默认 `15` |
| `load_images` | string | | 全局图片开关：`"Y"` (默认) 或 `"N"` (禁用所有图片) |
| `body` | array | ✓ | 内容源列表 |

`title` 子字段：

| 字段 | 说明 |
| --- | --- |
| `text` | 书名，支持 `{time}` 占位符（展开为日期）和 `</br>` 换行 |
| `img` | 封面图片 URL；留空则自动使用 Bing 每日壁纸¹，失败则用纯色背景 |

> ¹ **版权说明**：Bing 每日壁纸版权归微软及对应合作摄影师所有。程序自动抓取仅限于个人非商业的阅读学习使用，请勿公开发布、传播含有此类封面的电子书。

### 内容源通用字段

| 字段 | 说明 |
| --- | --- |
| `title` | EPUB 中的章节标题 |
| `type` | `rss`、`web`、`mail`、`trending` 或自定义插件类型名 |
| `src` | 内容源地址或关键词，所有类型必填 |
| `priority` | 排序值，数值越大越靠前；默认 `0`，相同值保持配置顺序 |
| `load_images` | `Y`（默认）加载图片；`N` 禁用此源的图片并移除 `<img>` 标签 |
| `keep_link` | `Y`（默认）保留 `<a>` 标签；`N` 移除链接标签只保留文字 |
| `exclude` | HTML 内容过滤规则，支持 `start` / `end` / `exact` 三种模式 |
| `delete` | 逗号 `,` 分隔的关键词；标题包含任一关键词时跳过整篇文章 |
| `metadata` | 不同fetcher定义的扩展配置 |

### 最小配置示例

```json
{
  "title": {
    "text": "{每日新闻 {time}}",
    "img": ""
  },
  "limit": 15,
  "body": [
    {
      "type": "rss",
      "src": "https://hnrss.org/frontpage",
      "title": "Hacker News",
      "priority": 10,
      "keep_link": "Y",
      "full_text": "N"
    }
  ]
}
```
</details>

---

## Config Editor 使用

项目提供了一个可视化 HTML [配置编辑器](https://liusonwood.github.io/OughtGather/)，无需安装任何依赖。

**在线版**（推荐）：

```text
https://liusonwood.github.io/OughtGather/
```

**离线版**：下载并打开仓库里的 `config-editor.html`。

<details>
<summary><b>主要功能</b></summary>

- 支持全部内容源类型（`rss` / `web` / `mail` / `trending` 及自定义插件），提醒每一类内容源所需配置的环境变量
- 导入已有 `config.json`，可视化添加 / 删除 / 拖拽排序内容源
- 导入已有 `opml.xml`，快速配置rss
- 编辑排除规则（`exclude`）和扩展参数（`metadata`）
- 通过下载或复制到剪贴板导出最终 JSON
- 所有改动自动保存到 `localStorage`，刷新不丢失
</details>

---


## 本地开发部署

<details>
<summary><b>展开：</b></summary>

### 1. 安装依赖

```bash
pip install -r requirements.txt
```

### 2. 准备配置

```bash
cp config.template.json config.json
# 编辑 config.json，或用 config-editor.html 可视化编辑后复制进来
```

### 3. 设置环境变量

```bash
export SMTP_HOST="smtp.example.com"
export SMTP_PORT="587"
export SMTP_USERNAME="sender@example.com"
export SMTP_PASSWORD="app-password"
export KINDLE_EMAIL="name@kindle.com"
```

### 4. 运行

```bash
python3.11 src/main.py
```

有新内容时，程序在 `output/` 下生成 EPUB，并尝试发送到 `KINDLE_EMAIL`。日志写入 `logs/`。


### 5. 测试文件

```bash
# 运行全部测试
python3.11 -m pytest tests/
```

**EPUBCheck 校验**：

使用 [epubcheck](https://github.com/w3c/epubcheck) 验证生成的 EPUB 是否符合 EPUB 3 标准

把 `epubcheck.jar` 放在 `epubcheck/epubcheck.jar`，然后运行：

```bash
python3.11 -m pytest tests/test_integration.py::TestEpubcheckValidation -v
```

更多说明见 [docs/TESTING.md](docs/TESTING.md) 和 [docs/EPUB_COMPLIANCE.md](docs/EPUB_COMPLIANCE.md)。
</details>

---


## 开发新的 Fetcher

项目采用插件化抓取器架构，新增内容源类型只需在 `src/fetchers/` 添加一个文件，无需修改主入口。

### 开发规则

- 继承 `BaseFetcher`（`from src.fetchers.base import BaseFetcher`）
- 声明唯一的类属性 `type_name`，用于在 `config.json` 中通过 `"type"` 字段识别
- 实现 `fetch(self) -> FetchResult` 方法，返回 `FetchResult` 对象
- 文件命名：`src/fetchers/<type_name>_fetcher.py`
- 注册是自动的，模块加载时即完成注册

</br>
<details>
<summary><b>使用 LLM 快速生成</b></summary>

[docs/new_fetcher_prompt_template.md](docs/new_fetcher_prompt_template.md) 提供了一个可复制给任意 LLM 的开发提示词模板，填入你的需求后即可自动生成符合架构规范的 fetcher 代码。使用前回答模板开头的 5 个问题：

1. 目标内容源是什么？（网站、API、RSS 等）
2. `config.json` 中需要哪些配置字段？（`src` 的含义、`metadata` 参数等）
3. 是否需要 API Key 等凭据？
4. 如何解析文章内容？（HTML 标签、JSON 字段位置等）
5. 是否有特殊处理需求？（内容过滤、重试策略等）
</details>

<details>
<summary><b>关键父类方法</b></summary>

| 方法 | 说明 |
| --- | --- |
| `self._make_request(url, ...)` | 封装 HTTP 请求，内置重试 |
| `self._extract_images(html)` | 从 HTML 提取图片 URL 列表 |
| `self._should_delete(title)` | 检查标题是否匹配 `delete` 关键词 |
| `self._restore_img_tags(html)` | 修复 trafilatura 输出的非标准图片标签 |
</details>

<details>
<summary><b>代码框架</b></summary>

```python
from src.config import ContentSource, get_secret
from src.fetchers.base import BaseFetcher, FetchResult, Article

class MyFetcher(BaseFetcher):
    type_name = "my_type"                    # config.json 中的 type 值
    src_placeholder = "输入提示文字"           # config-editor 中 src 字段的占位符
    config_schema = {                        # config-editor 中显示的专属字段
        "metadata.my_param": {
            "type": "text",
            "label": "自定义参数",
            "placeholder": "请输入..."
        }
    }

    def fetch(self) -> FetchResult:
        result = FetchResult(source=self.source, articles=[])
        try:
            url = self.source.src
            response = self._make_request(url)
            # ... 解析内容 ...
            article = Article(title="标题", content="<p>内容</p>", url=url)
            if not self._should_delete(article.title):
                result.articles.append(article)
        except Exception as e:
            result.success = False
            result.error = str(e)
        return result
```
</details>

### 新增fetcher后同步文档和脚本

**方式一**：Actions自动同步

工作流文件是 [.github/workflows/sync-project-docs.ymll](.github/workflows/sync-project-docs.yml)

**方式二**：手动触发同步

运行 `scripts/` 目录下的文件

```bash
python3.11 scripts/update_editor.py
python3.11 scripts/update_readme_secrets.py
python3.11 scripts/update_workflow_secrets.py
```

---

## 📚 项目文档

为了帮助您更好地安装、配置、运维及参与本项目，请参考以下全套文档：

- **核心使用与配置**
  - [📖 配置指南 (CONFIG.md)](docs/CONFIG.md) — 详细的 `config.json` 字段说明、过滤规则及各内容源配置。
- **开发与社区**
  - [🏗️ 项目设计文档 (design.md)](docs/design.md) — 系统架构、内容清洗流水线及 EPUB 生成逻辑。
  - [✅ 测试指南 (TESTING.md)](docs/TESTING.md) — 如何运行自动化测试、编写测试用例及查看覆盖率。
  - [🤝 贡献指南 (CONTRIBUTING.md)](.github/CONTRIBUTING.md) — 代码风格、插件化开发规范及时区约束。
  - [📜 行为准则 (CODE_OF_CONDUCT.md)](.github/CODE_OF_CONDUCT.md) — 社区交流标准。
  - [🛡️ 安全策略 (SECURITY.md)](.github/SECURITY.md) — 如何安全地报告漏洞及保护您的私有凭证。
  - [🙋 支持指南 (SUPPORT.md)](.github/SUPPORT.md) — 获取技术支持的正式渠道。
 
---

## 项目结构

```text
.
├── LICENSE
├── README.md
├── cloudflare- worker/ # worker部署触发器
├── config-editor.html
├── config.json
├── config.template.json
├── GEMINI.md
├── requirements.txt
├── data/               # 去重数据库
│   └── fetched_urls.txt
├── docs/               # 开发文档
├── epubcheck/          # EPUB 标准校验工具
│   └── epubcheck.jar
├── img/                # Kindle 效果图片
├── Fonts/              # 字体文件 (NotoEmoji-Medium.ttf, README_Emoji.txt, etc.)
├───scripts/            # 辅助脚本
├── src/                # 核心源代码
│   ├── main.py
│   ├── config.py
│   ├── dedup/          # 去重逻辑
│   ├── epub/           # EPUB 生成
│   ├── fetchers/       # 内容源抓取器
│   ├── mailer/         # 邮件发送
│   ├── processors/     # 内容与图片处理
│   ├── uploader/       # WebDAV 上传
│   └── utils/          # 工具与日志
└── tests/              # 测试套件
```

**目录说明：**
- `src/`: 项目核心逻辑，包含各个功能模块的实现。
- `docs/`: 详细的架构设计、开发指南及合规性文档。
- `tests/`: 覆盖全功能的单元测试与集成测试，确保 EPUB 生成与抓取逻辑正确。
- `epubcheck/`: 用于验证生成的 EPUB 3 文件是否严格符合国际标准。
- `data/`: 内容去重数据库。

---


## 免责声明

本项目支持自动获取 Bing 每日壁纸作为封面，并对该图片进行裁剪、缩放及加盖文字遮罩等处理。此类图片版权均归微软公司或其合作摄影师所有。

使用本软件的个人用户应在国家法律及微软服务条款的约束下，**仅将生成的电子书用于个人学习、阅读或研究等非商业目的**。严禁将含有版权封面图片的电子书公开发布、上传至公共网络或进行商业传播。因不当使用导致的任何侵权纠纷，由使用者本人承担全部法律责任，本项目及其作者概不负责。

## 许可证

GNU AGPLv3.0，见 [LICENSE](LICENSE)。
