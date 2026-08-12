import pytest
from unittest.mock import MagicMock, patch, call
from src.main import main, has_valid_content, process_results
from src.config import ContentSource
from src.fetchers.base import Article, FetchResult


# =========================================================================
# has_valid_content
# =========================================================================

class TestHasValidContent:
    """仅具备有效正文的文章才应进入去重与推送。"""

    def test_empty_content(self):
        article = Article(title="t", content="", url="https://example.com/a")
        assert has_valid_content(article) is False

    def test_none_like_whitespace(self):
        article = Article(title="t", content="   \n\t  ", url="https://example.com/a")
        assert has_valid_content(article) is False

    def test_short_plain_text_no_images(self):
        # 只要有字（例如仅 1 个字），无图片也判定为有效正文
        article = Article(
            title="t",
            content="<p>短</p>",
            url="https://example.com/a",
        )
        assert has_valid_content(article) is True

    def test_plain_text_at_threshold(self):
        # 恰好 1 个非空白字符
        plain = "a"
        article = Article(title="t", content=plain, url="https://example.com/a")
        assert has_valid_content(article) is True

    def test_plain_text_above_threshold(self):
        article = Article(
            title="t",
            content="这是一篇有足够长度的正文内容，应当判定为有效。",
            url="https://example.com/a",
        )
        assert has_valid_content(article) is True

    def test_html_stripped_to_enough_text(self):
        article = Article(
            title="t",
            content="<div><p>Hello world, this is long enough.</p></div>",
            url="https://example.com/a",
        )
        assert has_valid_content(article) is True

    def test_html_entities_unescaped(self):
        # &nbsp; 等实体解码后仍可能不够长 → 无效；足够长则有效
        article = Article(
            title="t",
            content="<p>足够长的纯文本内容在实体解码后应有效</p>",
            url="https://example.com/a",
        )
        assert has_valid_content(article) is True

    def test_short_text_with_images_list(self):
        article = Article(
            title="t",
            content="<p>图</p>",
            url="https://example.com/a",
            images=["https://example.com/img.jpg"],
        )
        assert has_valid_content(article) is True

    def test_short_text_with_img_tag_in_content(self):
        article = Article(
            title="t",
            content='<p>图</p><img src="https://example.com/x.png" alt="x">',
            url="https://example.com/a",
        )
        assert has_valid_content(article) is True

    def test_short_text_img_tag_case_insensitive(self):
        article = Article(
            title="t",
            content='<IMG SRC="https://example.com/x.png">',
            url="https://example.com/a",
        )
        assert has_valid_content(article) is True

    def test_only_tags_no_text_no_images(self):
        article = Article(
            title="t",
            content="<div><span></span><br/></div>",
            url="https://example.com/a",
        )
        assert has_valid_content(article) is False


# =========================================================================
# process_results：仅有效正文才 mark 去重并纳入推送
# =========================================================================

class TestProcessResultsValidContent:
    """process_results 应在内容处理后校验有效性，再决定是否 mark / 推送。"""

    def _source(self):
        return ContentSource(type="rss", src="https://example.com/rss", title="测试源")

    def _article(self, title, content, url=None, images=None):
        return Article(
            title=title,
            content=content,
            url=url or f"https://example.com/{title}",
            images=images or [],
        )

    @patch("src.main.ContentProcessor")
    def test_valid_article_marked_and_included(self, mock_cp_cls):
        source = self._source()
        valid = self._article("有效文章", "这是一篇有足够长度的正文，应被保留并写入去重。")
        result = FetchResult(source=source, articles=[valid], success=True)

        mock_processor = MagicMock()
        mock_processor.process.side_effect = lambda a: a
        mock_cp_cls.return_value = mock_processor

        tracker = MagicMock()
        tracker.is_fetched.return_value = False

        out = process_results([result], tracker)

        assert len(out) == 1
        assert len(out[0].articles) == 1
        assert out[0].articles[0].title == "有效文章"
        tracker.mark_as_fetched.assert_called_once_with(valid.url)

    @patch("src.main.ContentProcessor")
    def test_empty_article_not_marked_not_included(self, mock_cp_cls):
        source = self._source()
        empty = self._article("空正文", "")
        result = FetchResult(source=source, articles=[empty], success=True)

        mock_processor = MagicMock()
        mock_processor.process.side_effect = lambda a: a
        mock_cp_cls.return_value = mock_processor

        tracker = MagicMock()
        tracker.is_fetched.return_value = False

        out = process_results([result], tracker)

        assert len(out) == 1
        assert out[0].articles == []
        tracker.mark_as_fetched.assert_not_called()

    @patch("src.main.ContentProcessor")
    def test_empty_text_without_images_skipped(self, mock_cp_cls):
        source = self._source()
        empty = self._article("空壳", "<p></p>")
        result = FetchResult(source=source, articles=[empty], success=True)

        mock_processor = MagicMock()
        mock_processor.process.side_effect = lambda a: a
        mock_cp_cls.return_value = mock_processor

        tracker = MagicMock()
        tracker.is_fetched.return_value = False

        out = process_results([result], tracker)

        assert out[0].articles == []
        tracker.mark_as_fetched.assert_not_called()

    @patch("src.main.ContentProcessor")
    def test_short_text_with_images_marked(self, mock_cp_cls):
        source = self._source()
        with_img = self._article(
            "图文",
            "<p>图</p>",
            images=["https://example.com/photo.jpg"],
        )
        result = FetchResult(source=source, articles=[with_img], success=True)

        mock_processor = MagicMock()
        mock_processor.process.side_effect = lambda a: a
        mock_cp_cls.return_value = mock_processor

        tracker = MagicMock()
        tracker.is_fetched.return_value = False

        out = process_results([result], tracker)

        assert len(out[0].articles) == 1
        tracker.mark_as_fetched.assert_called_once()

    @patch("src.main.ContentProcessor")
    def test_mix_valid_and_invalid(self, mock_cp_cls):
        source = self._source()
        valid = self._article("好文章", "这是足够长的正文内容，应当推送并标记去重记录。")
        empty = self._article("空壳", "")
        short = self._article("简短", "x")
        result = FetchResult(
            source=source, articles=[valid, empty, short], success=True
        )

        mock_processor = MagicMock()
        mock_processor.process.side_effect = lambda a: a
        mock_cp_cls.return_value = mock_processor

        tracker = MagicMock()
        tracker.is_fetched.return_value = False

        out = process_results([result], tracker)

        assert len(out[0].articles) == 2
        assert [a.title for a in out[0].articles] == ["好文章", "简短"]
        assert tracker.mark_as_fetched.call_count == 2

    @patch("src.main.ContentProcessor")
    def test_already_fetched_skipped(self, mock_cp_cls):
        """已抓取文章跳过推送，且不调用 mark_as_fetched。"""
        source = self._source()
        article = self._article("已抓取", "这是足够长的正文，但去重库中已有记录。")
        result = FetchResult(source=source, articles=[article], success=True)

        mock_processor = MagicMock()
        mock_cp_cls.return_value = mock_processor

        tracker = MagicMock()
        tracker.is_fetched.return_value = True

        out = process_results([result], tracker)

        assert out[0].articles == []
        mock_processor.process.assert_not_called()
        tracker.mark_as_fetched.assert_not_called()

    def test_failed_result_passed_through(self):
        source = self._source()
        result = FetchResult(
            source=source, articles=[], success=False, error="connection reset"
        )
        tracker = MagicMock()

        out = process_results([result], tracker)

        assert len(out) == 1
        assert out[0].success is False
        tracker.is_fetched.assert_not_called()
        tracker.mark_as_fetched.assert_not_called()

    @patch("src.main.ContentProcessor")
    def test_processor_exception_keeps_raw_then_validates(self, mock_cp_cls):
        """处理失败时保留原文再做有效性校验；原文有效则仍可推送。"""
        source = self._source()
        valid_raw = self._article(
            "处理失败但仍有效",
            "原始 HTML 正文足够长，即便 ContentProcessor 抛错也应被保留。",
        )
        result = FetchResult(source=source, articles=[valid_raw], success=True)

        mock_processor = MagicMock()
        mock_processor.process.side_effect = RuntimeError("boom")
        mock_cp_cls.return_value = mock_processor

        tracker = MagicMock()
        tracker.is_fetched.return_value = False

        out = process_results([result], tracker)

        assert len(out[0].articles) == 1
        tracker.mark_as_fetched.assert_called_once()

    @patch("src.main.ContentProcessor")
    def test_processor_exception_empty_raw_not_marked(self, mock_cp_cls):
        source = self._source()
        empty_raw = self._article("处理失败且空", "")
        result = FetchResult(source=source, articles=[empty_raw], success=True)

        mock_processor = MagicMock()
        mock_processor.process.side_effect = RuntimeError("boom")
        mock_cp_cls.return_value = mock_processor

        tracker = MagicMock()
        tracker.is_fetched.return_value = False

        out = process_results([result], tracker)

        assert out[0].articles == []
        tracker.mark_as_fetched.assert_not_called()


@patch("src.main.load_config")
@patch("src.main.DedupTracker")
@patch("src.main.get_fetcher")
@patch("src.main.process_results")
@patch("src.main.has_new_content")
@patch("src.main.EPUBGenerator")
@patch("src.main.SMTPSender")
@patch("src.main.get_logger")
def test_main_no_new_content(
    mock_get_logger,
    mock_sender,
    mock_generator,
    mock_has_new,
    mock_process,
    mock_fetcher,
    mock_tracker,
    mock_load_config
):
    # Setup
    mock_logger = MagicMock()
    mock_get_logger.return_value = mock_logger
    mock_config = MagicMock()
    mock_config.body = [ContentSource(type="rss", src="https://example.com/rss")]
    mock_load_config.return_value = mock_config
    
    mock_has_new.return_value = False
    
    # Run
    main()
    
    # Assert
    mock_load_config.assert_called_once()
    mock_has_new.assert_called_once()
    mock_generator.assert_not_called()
    mock_sender.assert_not_called()

@patch("src.main.load_config")
@patch("src.main.DedupTracker")
@patch("src.main.get_fetcher")
@patch("src.main.process_results")
@patch("src.main.has_new_content")
@patch("src.main.EPUBGenerator")
@patch("src.main.SMTPSender")
@patch("src.main.get_logger")
def test_main_failure(
    mock_get_logger,
    mock_sender,
    mock_generator,
    mock_has_new,
    mock_process,
    mock_fetcher,
    mock_tracker,
    mock_load_config
):
    # Setup
    mock_logger = MagicMock()
    mock_get_logger.return_value = mock_logger
    mock_load_config.side_effect = Exception("Config load failed")
    
    # Run
    with pytest.raises(SystemExit) as excinfo:
        main()
    
    # Assert
    assert excinfo.value.code == 1
    mock_logger.exception.assert_called()


@patch("src.main.load_config")
@patch("src.main.DedupTracker")
@patch("src.main.get_fetcher")
@patch("src.main.process_results")
@patch("src.main.has_new_content")
@patch("src.main.EPUBGenerator")
@patch("src.main.SMTPSender")
@patch("src.main.get_logger")
@patch("src.main.time.time")
def test_main_success(
    mock_time,
    mock_get_logger,
    mock_sender,
    mock_generator,
    mock_has_new,
    mock_process,
    mock_fetcher,
    mock_tracker,
    mock_load_config
):
    # Setup
    mock_time.return_value = 12345678.9
    mock_logger = MagicMock()
    mock_get_logger.return_value = mock_logger
    
    mock_config = MagicMock()
    mock_config.body = [ContentSource(type="rss", src="https://example.com/rss")]
    mock_config.title.get_plain_text.return_value = "Test Title"
    mock_load_config.return_value = mock_config
    
    mock_has_new.return_value = True
    
    mock_epub_generator = MagicMock()
    mock_epub_generator.generate.return_value = "dummy.epub"
    mock_generator.return_value = mock_epub_generator
    
    # Run
    with patch("src.uploader.webdav_uploader.WebDavUploader") as mock_webdav:
        main()
    
    # Assert
    mock_load_config.assert_called_once()
    mock_has_new.assert_called_once()
    mock_generator.assert_called_once_with(mock_config)
    mock_epub_generator.generate.assert_called_once_with(
        mock_process.return_value, [], start_time=12345678.9
    )
    mock_sender.assert_called_once()


@patch("src.main.load_config")
@patch("src.main.DedupTracker")
@patch("src.main.get_fetcher")
@patch("src.main.process_results")
@patch("src.main.has_new_content")
@patch("src.main.EPUBGenerator")
@patch("src.main.SMTPSender")
@patch("src.main.get_logger")
@patch("src.main.log_summary_table")
def test_main_raw_counts_isolation(
    mock_log_table,
    mock_get_logger,
    mock_sender,
    mock_generator,
    mock_has_new,
    mock_process,
    mock_fetcher,
    mock_tracker,
    mock_load_config
):
    # Setup two distinct ContentSource objects
    source1 = ContentSource(type="rss", src="https://example.com/rss1", priority=1)
    source2 = ContentSource(type="rss", src="https://example.com/rss2", priority=2)
    
    mock_config = MagicMock()
    mock_config.body = [source1, source2]
    mock_load_config.return_value = mock_config
    
    # Configure mock fetchers
    mock_fetcher_instance1 = MagicMock()
    mock_fetcher_instance1.supports_two_phase = False  # 使用单阶段路径
    mock_result1 = MagicMock()
    mock_result1.success = True
    mock_result1.articles = [MagicMock(), MagicMock(), MagicMock()]  # raw count = 3
    mock_fetcher_instance1.fetch_with_retry.return_value = mock_result1
    
    mock_fetcher_instance2 = MagicMock()
    mock_fetcher_instance2.supports_two_phase = False  # 使用单阶段路径
    mock_result2 = MagicMock()
    mock_result2.success = True
    mock_result2.articles = [MagicMock()]  # raw count = 1
    mock_fetcher_instance2.fetch_with_retry.return_value = mock_result2
    
    # Side effect for get_fetcher to return different fetchers for different sources
    def get_fetcher_side_effect(source, global_limit=15):
        if source == source1:
            return mock_fetcher_instance1
        return mock_fetcher_instance2
    mock_fetcher.side_effect = get_fetcher_side_effect
    
    # Mock deduplication results (e.g. source1 keeps 2 new articles, source2 keeps 0)
    mock_processed1 = MagicMock()
    mock_processed1.source = source1
    mock_processed1.success = True
    mock_processed1.articles = [MagicMock(), MagicMock()]  # new count = 2
    
    mock_processed2 = MagicMock()
    mock_processed2.source = source2
    mock_processed2.success = True
    mock_processed2.articles = []  # new count = 0
    
    mock_process.return_value = [mock_processed1, mock_processed2]
    mock_has_new.return_value = True
    
    # Run
    with patch("src.uploader.webdav_uploader.WebDavUploader") as mock_webdav:
        main()
        
    # Assert
    mock_log_table.assert_called_once()
    headers, rows = mock_log_table.call_args[0]
    
    assert len(rows) == 2
    # Row for source1: raw_c should be 3, new_c should be 2
    assert rows[0][1] == "rss"
    assert "rss1" in rows[0][2]
    assert rows[0][4] == 3  # Raw count
    assert rows[0][5] == 2  # New count
    
    # Row for source2: raw_c should be 1, new_c should be 0
    assert rows[1][1] == "rss"
    assert "rss2" in rows[1][2]
    assert rows[1][4] == 1  # Raw count
    assert rows[1][5] == 0  # New count
