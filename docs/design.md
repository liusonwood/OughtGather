# Ought Gather 项目设计文档

## 1. 项目概述 (Overview)
**项目名称：** Ought Gather
**项目目标：** 打造一个自动化的信息聚合聚合工具。将用户订阅的邮件 (Email Newsletter)、RSS 内容源以及网页链接 (Web Links) 的内容提取出来，生成合规的 EPUB 电子书，并自动推送到用户的 Kindle 等设备。
**运行环境：** 依托 GitHub Actions 提供的服务实现自动化定时运行。

## 2. 凭证与全局配置 (Secrets & Config)
系统运行需要依赖 GitHub Secrets 存储敏感信息，以及一个全局的 JSON 配置文件（仓库中应提供一个 config 模板文件）。

### 2.1 环境变量/Secrets 信息
见后文 6. Secrets 配置清单

## 3. 抓取配置数据结构 (Input Data Structure)
系统通过读取 `config.json` 来决定抓取行为。JSON 结构主要分为两大部分：

### 3.1 标题块 (Title Block)
定义生成的 EPUB 书名。
*   格式支持：`自定义文本` 或动态时间，例如：`{Daily news {time}}`
*   img属性：封面图片链接，流空则抓取bing wallpaper
### 3.2 内容块 (Body Block)
一个数组，包含多个内容源对象。每个对象支持以下属性配置：

| 属性字段 | 类型 / 可选值 | 说明 |
| :--- | :--- | :--- |
| `type` | `mail` / `rss` / `web` / `trending` | **必填**。定义当前任务的内容源类型。 |
| `title` | String | 可选。自定义大章节标题。 |
| `src` | String / URL | **必填**。对应内容源的链接、RSS 地址、邮箱、或是 Trending 的抓取目标/描述。 |
| `priority` | Integer | 优先级。数字越大优先级越高（用于最终排版）。 |
| `keep_link` | `Y` / `N` | 是否保留原文中的超链接。 |
| `metadata.full_text` | `Y` / `N` | （仅针对 RSS 有效，位于 `metadata` 内部）`Y`=抓取源网页正文；`N`=仅使用 RSS 摘要。 |
| `chop` | String (Regex) | 支持 Python 的基础切片指令（/[数字:数字]），截取并从正文中**删除**。 |
| `exclude` | String | 删除指定**开头**或**结尾**的无用内容块。 |
| `delete` | String | 当标题包含关键词不抓取 |
| `metadata.goal` | String | （仅针对 `trending`）分析目标，可选，有默认值。 |
| `metadata.model` | String | （仅针对 `trending`）指定使用的模型，默认留空则使用全局配置模型。 |

## 4. 数据抓取与处理逻辑 (Data Fetching & Processing)
根据配置项 `keep_link`, `chop`, `delete`, `exclude` 执行清洗，提取核心正文。
根据 `type` 的不同，执行不同的清洗管道：

1.  **Mail (邮件):**
    *   通过 testmail.app API 直接读取并获取 JSON 格式内容。
    *   进行清洗，转换为统一的排版格式。
    *   请访问doc连接：https://testmail.app/docs/#using-cypress-json-api
2.  **RSS (订阅):**
    *   如果 `metadata.full_text = N`：直接抓取 RSS feed 中的 description/内容。
    *   如果 `metadata.full_text = Y`：提取链接，请求目标网页，抓取网页正文。
3.  **Web (网页):**
    *   通过类似于 trafilatura 的工具提取正文并降噪。
4.  **Trending (热点分析):**
    *   **触发条件：** 只有满足 `metadata.goal` 设置条件（且配置了正确的 API Key）时才会调用，否则报错拦截。
    *   **执行逻辑：** 根据 `src` 传入的关键词或描述性语句，调用 Open Router API (LLM) 进行热点信息汇总分析，生成文本。
5.  **图片处理规则 (针对所有类型):**
    *   将包含特殊标记/样式的图片转化为正常的 Markdown/HTML 图片标签插入正文。
    *   **压缩机制：** 根据图片尺寸自动进行压缩，确保转换后的体积在 EPUB 格式的最大限制之内。

## 5. EPUB 生成与排版规则 (EPUB Generation)

### 5.1 封面生成规范 (Cover Page)
*   **封面来源优先级：**
    1.  **方案1：** 自动化流运行时，优先抓取当天的 **Bing 每日壁纸** 作为封面。

    '''
            # 定义 Bing API 的网络地址
        bing_api_url = "https://www.bing.com/HPImageArchive.aspx?format=js&idx=0&n=1&mkt=zh-CN"

        # 1. 访问 API 并获取 JSON 响应数据
        json_data = fetch_content_from_url(bing_api_url)

        # 2. 解析 JSON，提取图片的相对 URL 路径
        # 注：快捷指令里的 "images.1.url" 相当于代码里的 images[0]['url']
        relative_image_path = json_data["images"][0]["url"]

        # 3. 将主域名与相对路径拼接，生成完整的图片直链
        full_image_url = "https://www.bing.com" + relative_image_path

        # 4. 访问完整直链，下载图片二进制数据
        image_raw_data = fetch_content_from_url(full_image_url)

        # 5. 将数据转换为系统可识别的图像对象
        wallpaper_image = convert_to_image(image_raw_data)

        # 6. 调用系统接口，将其设为锁屏与主屏幕壁纸
        set_system_wallpaper(target="lock_and_home_screen", image=wallpaper_image)

    '''

    2.  **方案2：** 抓取title设置中带有 `img` 标记的图片连接作为封面。
*   **文字叠加：** 
    *   将获取到的封面图片与书名、时间等进行拼装，生成封面。

### 5.2 目录结构与层级约束 (TOC & Document Hierarchy)
为了保证 Kindle 等阅读设备上的排版兼容性与阅读体验，电子书采用**单级根目录扁平化设计**，目录中所有小节均需附带超链接，其映射关系定义如下：

*   **一级大章节（逻辑根目录）：**
    根据自定义的title属性或者
    *   `mail` 源：以 **邮件账号/邮箱地址** 命名。
    *   `rss` 源：以 **源网站/内容源名称** 命名。
    *   `web` 源：以 **网页原始名称** 命名。
    *   `trending` 源：以 **大模型分析的主题名称** 命名。
*   **二级小章节（正文页）：**
    *   `mail` 源：对应邮件内的邮件标题。
    *   `rss` 源：对应具体的单篇文章标题。
    *   `trending`/`web` 源：无小标题。
*   **层级约束：** 每一个大章节在 EPUB 内部作为独立的逻辑块（根），**不设置多级的嵌套子章**。下属的各个小章节以平铺的 HTML 页面形式按顺序承接，并通过目录中的超链接直接指向具体内容。

### 5.3 内容排序机制 (Content Sorting)
在整合生成多源内容时，文章和章节的先后排列顺序遵循以下排序算法：
1.  **优先级第一原则（Priority-Based）：** 优先读取配置项中的 `priority` 值，数值越大，排版位置越靠前。
2.  **次序稳定原则（Order-Preserving）：** 若多个内容源的 `priority` 相同，则采用稳定排序，按照配置文件中的自然先后次序进行排列。

### 5.4 图片及媒体资源处理 (Image & Media Processing)
*   **标记转换：** 提取清洗过程中的图片，将其转化为标准的 Markdown/HTML 图片标签，并正确嵌入正文对应位置。
*   **体积控制：** 为防止电子书过大导致邮件发送失败或设备解析缓慢，需对下载的所有图片执行画质与分辨率压缩，将单张图片体积以及 EPUB 总体积控制在 Kindle 支持的最佳限制内。

### 5.5 触发与发送机制 (Trigger & Sending Conditions)
*   **内容增量校验（空书拦截）：** 
    *   每次 GitHub Actions 触发后，系统会自动检测是否有新抓取的内容。
    *   **触发发送：** 必须满足**至少有一个内容源中产生了至少一条内容更新**这一条件。
    *   **静默退出（不发书）：** 若本次运行检测到没有任何新数据更新，系统将不进行 EPUB 合成，亦不执行邮件推送，以防止设备收到空白、重复或无意义的电子书。

## 6. Secrets 配置清单
为了在 GitHub Actions 中安全地运行该自动化工作流，且不泄露您的个人账户隐私（如邮箱密码、API 密钥以及内容源链接），您需要在 GitHub 仓库的 **Settings -> Secrets and variables -> Actions** 中添加以下 **Repository secrets**。

### 6.1 必需配置的 Secrets（核心发送模块）
用于将生成的 EPUB 文件通过 SMTP 邮箱服务发送到您的 Kindle 设备。

| Secret 名称 | 作用描述 | 示例 / 说明 |
| :--- | :--- | :--- |
| `SMTP_HOST` | 发送端邮箱的 SMTP 服务器地址 | 例如：`smtp.qq.com` 或 `smtp.gmail.com` |
| `SMTP_PORT` | SMTP 服务的端口号 | 通常为 SSL 安全端口 `465` 或 TLS 端口 `587` |
| `SMTP_USERNAME` | 用于发送电子书的邮箱账号（发送端） | 例如：`sender@example.com` |
| `SMTP_PASSWORD` | 发送端邮箱的授权码或密码 | **注意：** 通常不是邮箱的登录密码，而是邮箱设置中开启 SMTP 服务时生成的**应用授权码** |
| `KINDLE_EMAIL` | 您的 Kindle 接收邮箱地址（接收端） | 例如：`username@kindle.com`（需在亚马逊后台将上面的发送端邮箱加入白名单） |

### 6.2 可选配置的 Secrets（按需启用）
这些 Secrets 对应手稿中提到的可选功能（如邮件读取、大模型热点分析以及订阅隐私保护）。

#### 6.2.1 邮件订阅抓取（若配置了 `type = "mail"`）
| Secret 名称 | 作用描述 | 说明 |
| :--- | :--- | :--- |
| `TESTMAIL_APP_API_KEY` | 用于读取订阅邮件内容的 API 密钥 | json 邮件 -> API key |

#### 6.2.2 大模型热点分析（若配置了 `type = "trending"`）
| Secret 名称 | 作用描述 | 说明 |
| :--- | :--- | :--- |
| `OPENROUTER_API_KEY` | OpenRouter 的 API 访问密钥 | 用于调用大模型总结、分析热点 |
| `OPENROUTER_API_ENDPOINT` | llm API 请求地址 | 用于调用非openrouter大模型总结、分析热点 |

#### 6.2.3 隐私配置保护（建议配置）
| Secret 名称 | 作用描述 | 说明 |
| :--- | :--- | :--- |
| `CONFIG_JSON` | 实际运行的完整 `config.json` 内容 | 由于仓库里只放公开的模板文件（Template），若您的 RSS 内容源中含有私人 Token，或需要隐藏关注的网页链接，建议将**真实的订阅 JSON 配置**直接存放在此 Secret 中，运行时由 GitHub Actions 动态生成配置文件。 |
