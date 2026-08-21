#!/usr/bin/env python3
"""
RSSHub Telegram 频道实例测试脚本
依次测试所有可用公共 RSSHub 实例
用法: python test_rsshub_instances.py [频道ID] [--verbose]
示例: 
    python test_rsshub_instances.py           # 默认测试 tnews365
    python test_rsshub_instances.py durov     # 测试指定频道
"""

import argparse
import feedparser
import requests
from typing import List

DEFAULT_HOSTS = [
    # ── 你已实测通的 5 个 ──
    "https://rsshub.rssforever.com",
    "https://rsshub.ktachibana.party",
    "https://hub.slarker.me",
    "https://rss.owo.nz",
    "https://rsshub.liumingye.cn",
    
    # ── 新增待测备选节点 ──
    "https://rss.peachyjoy.top",
    "https://rsshub.umzzz.com",
    "https://rsshub.isrss.com",
    "https://rsshub.asailor.org",
    "https://rsshub.cups.moe",
    "https://rsshub.speednet.icu",
    "https://rsshub.henry.wang",
    "https://yangzhi.app",
    "https://rss.lilywhite.cc",
]

def test_rsshub(host: str, channel_id: str, verbose: bool = False) -> dict:
    """测试单个 RSSHub 实例"""
    url = f"{host}/telegram/channel/{channel_id}"
    
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
        }
        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status()
        
        feed = feedparser.parse(response.text)
        
        if feed.entries and not feed.bozo:
            success = True
            status = "成功"
            articles = len(feed.entries)
            title = feed.feed.get("title", "未知频道")
            if verbose:
                print(f"  {host} - 成功 | {articles} 篇文章 | {title}")
        else:
            success = False
            status = "解析失败" if feed.bozo else "无条目"
            articles = 0
            title = "未知"
        
        return {
            "host": host,
            "success": success,
            "status": status,
            "articles": articles,
            "title": title,
            "url": url
        }
    except Exception as e:
        return {
            "host": host,
            "success": False,
            "status": f"错误: {str(e).split(':')[0]}",
            "articles": 0,
            "title": "错误",
            "url": url
        }

def main():
    parser = argparse.ArgumentParser(description="RSSHub Telegram 频道实例测试脚本")
    # 设置 nargs='?' 并提供 default='tnews365'
    parser.add_argument(
        "channel_id", 
        nargs="?", 
        default="tnews365", 
        help="Telegram 频道ID（如 durov 或 @durov，默认: tnews365）"
    )
    parser.add_argument("--verbose", "-v", action="store_true", help="详细输出")
    args = parser.parse_args()
    
    channel_id = args.channel_id.strip().lstrip("@")
    if not channel_id:
        print("频道ID不能为空")
        return
    
    print(f"开始测试 Telegram 频道: {channel_id}")
    print("=" * 60)
    
    results = []
    for host in DEFAULT_HOSTS:
        result = test_rsshub(host, channel_id, args.verbose)
        results.append(result)
        
        if not args.verbose:
            print(f"{host.split('//')[-1]} - {result['status']}")
    
    print("\n测试总结:")
    successful = [r for r in results if r["success"]]
    failed = [r for r in results if not r["success"]]
    
    print(f"成功 ({len(successful)}/{len(DEFAULT_HOSTS)}):")
    for r in successful:
        print(f"  ✓ {r['host'].split('//')[-1]} ({r['articles']} 篇)")
    
    if failed:
        print(f"\n失败 ({len(failed)}):")
        for r in failed:
            print(f"  ✗ {r['host'].split('//')[-1]} - {r['status']}")
    
    print("\n建议: 在 config.json 中可将这些实例添加到 TelegramFetcher 的 metadata.rsshub_host 中实现 failover")

if __name__ == "__main__":
    main()