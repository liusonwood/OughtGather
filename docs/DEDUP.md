# 去重模块说明

## 目的

去重模块避免同一内容源在连续抓取中重复推送文章。当前实现按内容源保存 URL 的 hash 快照，而不是维护一个永久增长的全局历史列表。

## Source 标识

每个 source 的唯一标识由以下格式组成：

```text
{source.type}:{source.src}
```

例如：

```text
rss:https://example.com/feed
mail:namespace.tag
```

完全相同的 `type + src` 会共享同一个快照。

## 文件格式

默认文件为 `data/fetched_urls.txt`，每行包含 source key、Tab 和 URL hash：

```text
rss:https://example.com/feed\t2341951acb69b641d2a1af6ec3a053f3
mail:namespace.tag\ta002c188d6596a00a73e44f97853dc09
```

旧版只有 hash、没有 source key 的文件不兼容，必须删除或重新执行 `--fresh-start`。

## 生命周期

### 正常抓取

1. 初始化 `DedupTracker`，读取现有 source 快照。
2. 抓取阶段使用上一轮快照过滤候选 URL。
3. 抓取成功且返回非空结果时，调用 `stage_source_snapshot()` 暂存本轮完整 URL 集合。
4. 内容处理阶段继续使用上一轮快照，避免本轮结果被自己判重。
5. 主流程调用 `save()`，将暂存快照原子替换到文件中。

### 空结果和失败

- source 抓取失败：不提交快照，保留上一轮记录。
- source 成功但返回空列表：不提交快照，保留上一轮记录。
- source 返回非空列表：以本次返回的全部 URL 替换旧快照；本次没有返回的 URL 会被移除。

### 两阶段抓取

对于实现 `fetch_list()` / `fetch_items()` 的 fetcher，快照来自 `fetch_list()` 返回的全部候选 URL，包括因为本次 limit 没有进入全文抓取的候选。这样候选列表本身就是该 source 的最新可见结果集。

## API 约定

```python
source_key = tracker.make_source_key(source)
tracker.is_fetched(url, source_key)
tracker.mark_as_fetched(url, source_key)
tracker.stage_source_snapshot(source_key, urls)
tracker.save()
```

- `is_fetched()` 和 `mark_as_fetched()` 必须传 source key。
- `stage_source_snapshot()` 忽略空 URL；空集合不会覆盖旧快照。
- `save()` 使用临时文件并替换正式文件，避免写入中断造成半个文件。

## Fresh Start

`python3.11 src/main.py --fresh-start` 会：

- 清空现有去重快照；
- 抓取每个启用去重的 source；
- 写入当前 source 返回的全部 URL hash；
- 不生成或发送 EPUB。

执行后，下一次正常抓取会把这些 URL 视为已抓取。

## 相关代码

- `src/dedup/tracker.py`：快照存储、查询、原子保存。
- `src/main.py`：抓取时暂存快照、结果处理和 Fresh Start 流程。
- `tests/test_dedup_tracker.py`：去重快照及主流程相关测试。
