# EPUB 系统文本多语言支持

Ought Gather 支持为 EPUB 中的系统文本选择语言。此功能只翻译 EPUB 界面文本，不翻译文章标题、文章正文、内容源名称或抓取到的错误原文。

## 配置语言

通过 `EPUB_LANGUAGE` 环境变量或 GitHub Actions Secret 配置语言。值使用 Bing 壁纸 API 的 locale 格式：

```bash
EPUB_LANGUAGE=zh-CN python3.11 src/main.py
EPUB_LANGUAGE=en-US python3.11 src/main.py
```

同一个值同时控制：

- EPUB metadata 的语言
- XHTML 文档的 `lang` 和 `xml:lang`
- Bing 每日壁纸 API 的 `mkt` 地区参数

在 GitHub Actions 中，将 `EPUB_LANGUAGE` 添加到仓库的 `Settings -> Secrets and variables -> Actions`。项目的 Secret 自动同步脚本会将它注入 Daily Gather workflow：

```text
EPUB_LANGUAGE=zh-CN
```

该变量是可选的。

## 默认值和回退规则

所有无法确定语言或翻译文本的情况都使用英文 `en-US`：

| 情况 | EPUB/Bing locale | 系统文本资源 |
| --- | --- | --- |
| 未设置或为空 | `en-US` | `en-US.json` |
| 格式无效，例如 `en` | `en-US` | `en-US.json` |
| 有效 locale，但资源文件不存在，例如 `ja-JP` | `ja-JP` | `en-US.json` |
| 当前资源缺少某个 key | 当前 locale | 该 key 使用 `en-US.json` |

locale 不通过固定语言列表限制，只要符合 Bing locale 格式即可。这样未来增加语言时，不需要修改语言选择逻辑。

## 语言资源

内置资源位于：

```text
src/epub/locales/en-US.json
src/epub/locales/zh-CN.json
```

代码只使用资源 key，不直接写入系统文本。资源使用扁平 JSON key，例如：

```json
{
  "navigation.back_to_contents": "Back to Contents",
  "summary.runtime_seconds": "{seconds} seconds"
}
```

带 `{name}`、`{count}` 或 `{seconds}` 的值是动态插值模板，key 名称和占位符必须保持不变。

新增语言时，只需新增对应的完整 locale 文件，例如：

```text
src/epub/locales/ja-JP.json
```

新文件应包含 `en-US.json` 中的全部 key。缺少的 key 会在运行时使用英文资源，因此 `en-US.json` 是必需且完整的基准资源。

## 覆盖的系统文本

语言资源覆盖 EPUB 中生成器添加的可见系统文本，包括：

- 目录、返回目录、封面和导航 landmarks
- 文章作者、日期和原文链接标签
- 推送汇总页的标题、说明、统计、错误和内容源详情
- 成功、失败、文章数量和运行耗时等动态文本

文章自身的标题、正文、来源名称和抓取错误内容保持原样。

## Secret 自动同步

不要直接手动维护由脚本生成的 workflow Secret 区块。修改 Secret 注册说明后，运行：

```bash
python3 scripts/update_workflow_secrets.py
python3 scripts/update_readme_secrets.py
```

这两个脚本分别更新 GitHub Actions workflow 和中文 README 的 Secret 配置表。英文 README 需要手动维护。

## 验证

运行完整测试：

```bash
python3.11 -m pytest tests/
```

应验证默认英文、显式中文、无效 locale、缺失资源、单个 key 英文回退，以及 Bing `mkt` 参数与 EPUB locale 保持一致。
