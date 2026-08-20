# Playwright 网页挑战回退说明

## 目的

Ought Gather 默认先使用 `httpx` 请求网页。网页请求最终返回非 `200` 时，网页类抓取器会自动切换到 Playwright Headless Chromium，执行页面 JavaScript，并将渲染后的 HTML 交给现有正文提取流程。

实现入口：`src/fetchers/base.py` 的 `BaseFetcher._make_request()` 和 `_make_browser_request()`。

## 适用范围

会启用浏览器回退的请求：

- `web` 抓取器的页面请求；
- `xpath_list_auto` 抓取器的列表页和详情页请求；
- RSS `metadata.full_text=Y` 时的文章详情页请求。

不会启用浏览器回退的请求：

- RSS/Atom feed XML 本身；
- mail、weather、trending、Twitter、Raindrop 等 API 请求；
- 未在调用 `_make_request()` 时传入 `allow_browser_fallback=True` 的请求。

## 状态码和挑战等待

- 普通页面返回 `200`：直接使用 HTTP 响应。
- 页面返回 `202`：视为可能存在 AWS WAF JavaScript challenge，启动浏览器并等待后续文档响应。
- 浏览器最终返回 `200` 或其他非 `202` 的 `2xx`：回退成功，使用渲染后的 DOM。
- 浏览器初始返回 `403`、`404`、`500` 等终态错误：立即失败，不等待完整超时。
- `202` 在超时内没有变成有效 `2xx`：回退失败，保留原始 HTTP 错误并由上层处理。

Playwright 默认启用 JavaScript，不需要额外设置 `java_script_enabled`。如果结果仍是“JavaScript is disabled”挑战页，通常表示挑战没有完成、站点识别出 Headless 浏览器，或最终页面仍未完成跳转。

## 浏览器生命周期

- 每个 fetcher 复用一个 Chromium 进程。
- 每次页面请求创建独立 Browser Context，确保不同请求的 User-Agent 和 headers 不互相污染。
- 页面请求完成后立即关闭 page 和 context。
- 主抓取流程会显式调用 `fetcher.close()`；`__del__` 仅作为异常情况下的最后兜底。

## 日志

成功触发回退时，日志中会出现类似内容：

```text
[Playwright] Triggering browser fallback ... after HTTP 202
[Playwright] Launching headless Chromium
[Playwright] ... initial document status: 202
[Playwright] Waiting for JavaScript challenge: ...
[Playwright] Browser fallback succeeded ... with final HTTP 200
```

如果出现 `Playwright fallback failed`，请同时查看原始 HTTP 状态、浏览器最终状态和启动错误。

## 依赖和 GitHub Actions

Python 依赖位于 `requirements.txt`：

```text
playwright>=1.40.0
```

daily workflow 的安装顺序：

1. 从 Actions cache 恢复 `~/.cache/ms-playwright`；
2. 缓存未命中时执行 `playwright install-deps chromium`，安装 Ubuntu 系统依赖；
3. 执行 `playwright install chromium`，安装或校验 Chromium 浏览器文件。

浏览器二进制可以缓存，但 Actions runner 的系统包状态不会被该缓存持久化。因此系统依赖只在浏览器缓存未命中时安装，以减少后续运行时间；如果 GitHub runner 基础镜像发生重大变化，应删除旧缓存或更新缓存键后重新运行。

## 本地验证

安装 Python 依赖和浏览器：

```bash
pip install -r requirements.txt
playwright install --with-deps chromium
```

运行测试：

```bash
python3.11 -m pytest tests/
```

如果只测试普通抓取逻辑而本机没有 Chromium，非挑战页面仍可运行；真正触发浏览器回退时会记录明确的 Playwright 安装错误。

## RSS 全文降级

当 RSS 设置 `metadata.full_text=Y` 时，文章详情页会依次尝试：

1. 普通 HTTP 请求；
2. Playwright JavaScript 回退；
3. RSS 条目的 `content`、`summary` 或 `description`。

如果最终使用 RSS 摘要，系统仍会保留文章，并从摘要 HTML 中提取图片。
