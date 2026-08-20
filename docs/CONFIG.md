# Ought Gather 配置指南

本文档详细说明 `config.json` 的所有配置项。

## 概览

`config.json` 包含三个顶层字段：`title`（书名与封面）、`limit`（全局抓取上限，可选）和 `body`（内容源列表）。

```json
{
  "title": {
    "text": "{Daily News {time}}",
    "img": ""
  },
  "limit": 20,
  "body": [
    {
      "type": "rss",
      "src": "https://example.com/rss",
      "priority": 10
    }
  ]
}
```

### 顶层配置字段

| 字段 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| `title` | object | ✓ | 无 | 书名与封面配置（详见下方 title 说明） |
| `limit` | int | | `15` | 每个内容源的抓取条数上限。应用于所有类型（rss/web/mail/trending/raindropio/weather） |
| `load_images` | string | | `"Y"` | 全局图片开关。`"Y"`（默认）加载并压缩图片；`"N"` 禁用所有图片（不下载，且移除 HTML 中的 `<img>` 标签）。Emoji 渲染不受此开关影响 |
| `body` | array | ✓ | 无 | 内容源列表（详见下方 body 说明） |

可通过以下任一方式提供配置：

- 将 `config.json` 放在项目根目录
- 设置环境变量 `CONFIG_JSON` 为完整的 JSON 字符串（推荐用于 GitHub Actions，可保护隐私）

也可以使用浏览器端的可视化编辑器 `config-editor.html`，在浏览器中打开即可使用。

## 标题配置 (title)

```json
{
  "title": {
    "text": "{Daily News {time}}",
    "img": "https://example.com/cover.jpg"
  }
}
```

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `text` | string | ✓ | 书名，显示在封面中央。支持两种占位符写法：`{time}` → `2026-06-14`；`{前缀 {time}}` → `前缀 2026-06-14`（外层花括号仅用于嵌套，输出时被展开） |
| `img` | string | | 封面背景图片 URL。留空 `""` 或未配置 → 自动使用 Bing 每日壁纸¹；Bing 也失败时 → 深蓝色纯色背景；有效 URL → 下载并缩放到 1600×2560（Kindle 推荐尺寸） |

> ¹ **版权说明**：Bing 每日壁纸版权归微软及对应合作摄影师所有。程序自动抓取仅限于个人非商业的阅读学习使用，请勿公开发布、传播含有此类封面的电子书。

## 内容源配置 (body)

`body` 是一个数组，每个元素定义一个内容源。EPUB 中的章节按 `priority` 降序排列（数值越大越靠前），相同优先级保持配置中的原始顺序（稳定排序）。

### 通用属性（所有 type 共用）

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `type` | string | ✓ | 内容源类型：`rss` / `web` / `mail` / `trending` / `raindropio` / `weather` |
| `src` | string | ✓ | 内容源地址，含义因 `type` 而异（详见下方各类型说明） |
| `title` | string | | 自定义章节标题，显示在 EPUB 目录中。各类型的默认行为：`rss` → 使用 RSS feed 自身的标题；`web` → 优先从网页 `<title>`/`<h1>`/`og:title` 提取；`mail` → 无默认，建议手动指定；`trending` → `"热点分析: {src}"`；`raindropio` → 使用收藏夹原始标题；`weather` → `"{城市名}天气预报"` |
| `priority` | int | | 优先级，数字越大在 EPUB 中越靠前。默认 `0`。相同值保持配置顺序 |
| `load_images` | string | | 是否为该源加载图片。`"Y"`（默认）加载图片；`"N"` 禁用此源的图片。仅在全局 `load_images` 为 `"Y"` 时生效 |
| `keep_link` | string | | 是否保留文章中的超链接。`"Y"`（默认）保留 `<a>` 标签，Kindle 上可点击跳转；`"N"` 移除所有 `<a>` 标签，只保留链接文字 |
| `exclude` | array | | 内容过滤规则列表，在 **HTML 源码**上操作，保留标签结构。每条规则是一个 `{type, value}` 对象，按数组顺序依次执行（详见下方 exclude 说明） |
| `delete` | string | | 按标题关键词**删除整篇文章**（逗号分隔多个关键词）。文章标题中包含任意一个关键词就跳过不收录 |


### exclude 规则详解

`exclude` 数组中每条规则包含 `type` 和 `value` 两个字段，支持三种模式：

| type | 说明 | 示例 |
|------|------|------|
| `start` | 删除从文档**开头**到 `value`（含 value 本身）之间的所有内容。在文本节点中顺序查找第一个匹配位置 | `{ "type": "start", "value": "前言部分" }` |
| `end` | 删除从 `value`（含）到文档**结尾**的所有内容。在文本节点中逆序查找最后一次出现（rfind 语义） | `{ "type": "end", "value": "— 完 —" }` |
| `exact` | 在 HTML **源码**中精确匹配 `value` 字符串并删除所有出现。`value` 可以包含 HTML 标签，适合精确移除特定链接或广告 | `{ "type": "exact", "value": "<a href=\"https://spam.com\">推广</a>" }` |

> **注意**：`exclude` 在 HTML 上操作，会保留原始标签结构。关键词可以包含冒号等特殊字符。多条规则按顺序依次执行，可组合使用。

### 各类型详解

---

#### `rss` — RSS/Atom 订阅

| 专属字段 | 类型 | 必填 | 说明 |
|---------|------|------|------|
| `src` | string | ✓ | RSS/Atom feed 的完整 URL |
| `metadata` | object | | RSS 可选扩展配置 |

##### `rss` 支持的 `metadata` 字段

| metadata 键 | 类型 | 说明 |
|------------|------|------|
| `metadata.full_text` | string | 是否抓取完整正文。`"N"`（默认）→ 使用 feed 提供的摘要；`"Y"` → 访问原始 URL，用 trafilatura 提取全文，失败时回退到 BeautifulSoup 提取 `<article>`/`<main>` 等区域 |
| `limit` | number | 限制抓取最大条目数，未设置时遵循全局 limit |

```json
{
  "type": "rss",
  "title": "Hacker News",
  "src": "https://hnrss.org/frontpage",
  "priority": 10,
  "keep_link": "Y",
  "metadata": {
    "full_text": "Y"
  },
  "exclude": [
    { "type": "start", "value": "阅读更多" },
    { "type": "end", "value": "— 完 —" }
  ],
  "delete": "广告,推广"
}
```

---

#### `web` — 网页抓取

| 专属字段 | 类型 | 必填 | 说明 |
|---------|------|------|------|
| `src` | string | ✓ | 目标网页的完整 URL |

`web` 类型没有额外专属属性，通用属性 `exclude`、`delete` 同样适用。

```json
{
  "type": "web",
  "title": "热门文章",
  "src": "https://example.com/article",
  "priority": 5,
  "keep_link": "N",
  "exclude": [
    { "type": "start", "value": "分享到：" }
  ]
}
```

---

#### `mail` — 邮件订阅

需要设置环境变量 `TESTMAIL_APP_API_KEY`。

| 专属字段 | 类型 | 必填 | 说明 |
|---------|------|------|------|
| `src` | string | ✓ | testmail.app 的 **namespace**，支持两种格式：`"mynamespace"` — 只指定 namespace，获取该 namespace 下所有邮件；`"mynamespace.tag"` — 同时指定 namespace 和 tag，只获取该 tag 的邮件（等同于在 metadata 中设置 `"tag": "tag"`）。空格会被自动移除。testmail 的收件地址格式为 `{namespace}.{tag}@inbox.testmail.app` |
| `metadata` | object | | 邮件查询的可选过滤参数（见下表） |

**metadata 字段详解：**

| 字段 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `tag` | string | 无 | 按标签精确过滤。如果 `src` 中已包含 tag（如 `"mynamespace.tag"`），metadata 中的 tag 会覆盖它 |
| `tag_prefix` | string | 无 | 按标签前缀过滤，例如 `"news"` 匹配 tag 为 `"news"`/`"newsletter"`/`"news-daily"` 的邮件 |
| `timestamp_from` | int | 无 | 起始时间戳（**毫秒**级 Unix 时间戳），只返回此时间之后收到的邮件 |
| `timestamp_to` | int | 无 | 结束时间戳（**毫秒**级），只返回此时间之前收到的邮件 |
| `limit` | int | `50` | 返回邮件数量上限（最大 `100`） |
| `offset` | int | `0` | 分页偏移量，配合 limit 使用 |

```json
{
  "type": "mail",
  "title": "订阅邮件",
  "src": "mynamespace.daily",
  "priority": 8,
  "metadata": {
    "timestamp_from": 1718300000000,
    "limit": 10
  }
}
```

---

#### `trending` — AI 热点分析

需要设置环境变量 `OPENROUTER_API_KEY`。

| 专属字段 | 类型 | 必填 | 说明 |
|---------|------|------|------|
| `src` | string | ✓ | 搜索关键词/主题，发送给 LLM 的主题文本 |
| `metadata.goal` | string | | 分析目标/指令，告诉 LLM 要做什么。LLM 会输出 3-5 个要点 + 趋势分析 + 亮点。留空或不配置 → 自动使用默认值 `"分析并总结相关热点信息"` |
| `metadata.model` | string | | OpenRouter 模型 ID。留空或不配置 → 默认使用 `"openai/gpt-3.5-turbo"`。也可通过环境变量 `OPENROUTER_MODEL` 设置全局默认模型（优先级低于此字段）。常用示例：`"openai/gpt-4o"`、`"anthropic/claude-3.5-sonnet"`、`"google/gemini-pro-1.5"` |

```json
{
  "type": "trending",
  "title": "AI 热点",
  "src": "人工智能最新发展趋势",
  "priority": 15,
  "metadata": {
    "goal": "分析最新的 AI 技术突破和应用案例，重点关注大模型、Agent、多模态方向",
    "model": "openai/gpt-4o"
  }
}
```

---

#### `raindropio` — Raindrop.io 收藏夹抓取

需要设置环境变量 `RAINDROPIO_API_KEY`。

| 专属字段 | 类型 | 必填 | 说明 |
|---------|------|------|------|
| `src` | string | ✓ | Raindrop.io 的收藏夹 ID（集合 ID），例如 `"1234567"`，或者 `"0"` 代表未分类收藏（Unsorted） |

> **注**：`raindropio` 会自动抓取书签指向网页的全文正文，无需额外配置。

```json
{
  "type": "raindropio",
  "title": "稍后阅读收藏",
  "src": "1234567",
  "priority": 12,
  "keep_link": "Y"
}
```

---

#### `weather` — 和风天气预报抓取

需要设置环境变量 `QWEATHER_KEY`（和风天气 API 密钥）和 `QWEATHER_HOST`（和风天气 API 主机地址，例如 `devapi.qweather.com` 或 `api.qweather.com`）。

| 专属字段 | 类型 | 必填 | 说明 |
|---------|------|------|------|
| `src` | string | ✓ | 城市名称。例如 `"北京"`、`"上海"` 或 `"Shanghai"`。程序将自动通过 Geolocation API 进行拼音/中文名解析，从而转换为内部位置 ID |
| `metadata` | object | | 天气查询可选参数（见下表） |

**metadata 字段详解：**

| 字段 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `date` | string | `"tomorrow"` | 预报的目标日期。可选值：`"today"` 或 `"0"`（今天），`"tomorrow"` 或 `"1"`（明天，默认值），`"2"`（后天），或符合 `YYYY-MM-DD` 格式的特定日期（需在和风 3 天天气预报接口范围内） |

```json
{
  "type": "weather",
  "title": "北京天气预报",
  "src": "北京",
  "priority": 20,
  "metadata": {
    "date": "tomorrow"
  }
}
```

## 完整示例

下面是一个使用了所有属性的完整 `config.json`，包含全部六种内容源：

```json
{
  "title": {
    "text": "{每日综合新闻 {time}}",
    "img": ""
  },
  "limit": 20,  // 每个内容源最多抓取 20 条
  "body": [
    {
      "type": "weather",
      "src": "北京",
      "title": "今日北京天气",
      "priority": 20,
      "metadata": {
        "date": "today"
      }
    },
    {
      "type": "trending",
      "src": "人工智能最新发展趋势",
      "title": "AI 行业热点",
      "priority": 15,
      "metadata": {
        "goal": "分析最新的 AI 技术突破和应用案例，重点关注大模型、Agent、多模态方向",
        "model": "openai/gpt-4o"
      }
    },
    {
      "type": "raindropio",
      "src": "1234567",
      "title": "稍后阅读选编",
      "priority": 12,
      "keep_link": "Y"
    },
    {
      "type": "rss",
      "src": "https://hnrss.org/frontpage",
      "title": "Hacker News 首页",
      "priority": 10,
      "keep_link": "Y",
      "metadata": {
        "full_text": "Y"
      },
      "exclude": [
        { "type": "start", "value": "阅读更多" },
        { "type": "end", "value": "— 完 —" },
        { "type": "exact", "value": "<a href=\"https://spam.com\">推广链接</a>" }
      ],
      "delete": "广告,推广,赞助"
    },
    {
      "type": "mail",
      "src": "mynamespace.daily",
      "title": "每日精选邮件",
      "priority": 8,
      "keep_link": "Y",
      "metadata": {
        "timestamp_from": 1718300000000,
        "limit": 10
      }
    },
    {
      "type": "web",
      "src": "https://example.com/article/123",
      "title": "深度报道",
      "priority": 5,
      "keep_link": "N",
      "exclude": [
        { "type": "start", "value": "分享到：" }
      ]
    }
  ]
}
```

**EPUB 中章节的排列顺序**（按 priority 降序）：

1. 今日北京天气（priority: 20）
2. AI 行业热点（priority: 15）
3. 稍后阅读选编（priority: 12）
4. Hacker News 首页（priority: 10）
5. 每日精选邮件（priority: 8）
6. 深度报道（priority: 5）

## 配置工具

项目提供了一个可视化 HTML 配置编辑器，浏览器打开 `config-editor.html` 即可使用：

- 启动时为空白状态，无默认配置，用户从零开始构建
- 支持全部 6 种内容源类型（rss / mail / web / trending / raindropio / weather），自动切换专属字段
- 导入已有 config.json，添加 / 删除 / 排序内容源，管理排除规则和邮件、天气、RaindropIO 等专属参数
- 通过下载或复制到剪贴板导出配置
- 所有操作均有 toast 提示反馈
