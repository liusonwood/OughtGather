import pytest
from unittest.mock import MagicMock, patch
from src.config import ContentSource
from src.fetchers.raindropio_fetcher import RaindropFetcher

class TestRaindropFetcher:
    """RaindropioFetcher 测试"""

    @patch.dict("os.environ", {"RAINDROPIO_API_KEY": "test_key_123"})
    @patch.object(RaindropFetcher, "_make_request")
    @patch.object(RaindropFetcher, "_fetch_full_text", return_value=("", ""))
    def test_fetch_bookmarks(self, mock_fetch_full_text, mock_request):
        """测试书签抓取"""
        # 模拟 Raindrop API 响应
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "result": True,
            "items": [
                {
                    "title": "Bookmark 1",
                    "link": "https://example.com/1",
                    "excerpt": "Excerpt 1",
                    "cover": "https://example.com/1.jpg"
                }
            ]
        }
        mock_request.return_value = mock_response

        # 配置源
        source = ContentSource(
            type="raindropio", 
            src="0", 
            metadata={"collection_id": "0"}
        )

        fetcher = RaindropFetcher(source)
        result = fetcher.fetch()

        assert result.success is True
        assert len(result.articles) == 1
        assert result.articles[0].title == "Bookmark 1"
        assert result.articles[0].url == "https://example.com/1"
        assert "Excerpt 1" in result.articles[0].content
        assert result.articles[0].images == ["https://example.com/1.jpg"]

    @patch.dict("os.environ", {"RAINDROPIO_API_KEY": "test_key_123"})
    @patch.object(RaindropFetcher, "_make_request")
    @patch.object(RaindropFetcher, "_fetch_full_text")
    def test_fetch_full_text(self, mock_fetch_full_text, mock_request):
        """测试全文抓取"""
        # 模拟 Raindrop API 响应
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "result": True,
            "items": [
                {
                    "title": "Bookmark Full",
                    "link": "https://example.com/full",
                    "excerpt": "Excerpt Full"
                }
            ]
        }
        mock_request.return_value = mock_response
        
        # 模拟全文提取
        mock_fetch_full_text.return_value = ("<h1>Full Content</h1>", "raw html")

        # 配置源
        source = ContentSource(
            type="raindropio",
            src="0"
        )

        fetcher = RaindropFetcher(source)
        result = fetcher.fetch()

        assert result.success is True
        assert len(result.articles) == 1
        assert result.articles[0].content == "<h1>Full Content</h1>"
        mock_fetch_full_text.assert_called_once_with("https://example.com/full")

    @patch.dict("os.environ", {"RAINDROPIO_API_KEY": "test_key_123"})
    @patch.object(RaindropFetcher, "_make_request")
    def test_api_error(self, mock_request):
        """测试 API 返回错误"""
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "result": False,
            "message": "Invalid API key"
        }
        mock_request.return_value = mock_response

        source = ContentSource(type="raindropio", src="0")
        fetcher = RaindropFetcher(source)
        result = fetcher.fetch()

        assert result.success is False
        assert "Invalid API key" in result.error

    def test_missing_api_key_is_rejected(self, monkeypatch):
        monkeypatch.delenv("RAINDROPIO_API_KEY", raising=False)
        with pytest.raises(ValueError, match="RAINDROPIO_API_KEY"):
            RaindropFetcher(ContentSource(type="raindropio", src="0"))

    @patch.dict("os.environ", {"RAINDROPIO_API_KEY": "key"})
    @patch.object(RaindropFetcher, "_make_request")
    def test_fetch_list_returns_normalized_candidates(self, mock_request):
        response = MagicMock()
        response.json.return_value = {
            "result": True,
            "items": [{"link": "https://example.com/a", "title": "A", "excerpt": "E", "cover": "C"}],
        }
        mock_request.return_value = response
        fetcher = RaindropFetcher(ContentSource(type="raindropio", src="123"))

        candidates = fetcher.fetch_list()

        assert candidates == [{"url": "https://example.com/a", "title": "A", "excerpt": "E", "cover": "C"}]
        mock_request.assert_called_once()
        assert "/raindrops/123" in mock_request.call_args.args[0]

    @patch.dict("os.environ", {"RAINDROPIO_API_KEY": "key"})
    @patch.object(RaindropFetcher, "_make_request")
    def test_fetch_list_api_failure_returns_none(self, mock_request):
        response = MagicMock()
        response.json.return_value = {"result": False, "message": "bad collection"}
        mock_request.return_value = response
        fetcher = RaindropFetcher(ContentSource(type="raindropio", src="123"))

        assert fetcher.fetch_list() is None

    @patch.dict("os.environ", {"RAINDROPIO_API_KEY": "key"})
    def test_fetch_items_empty_candidates_is_successful_noop(self):
        fetcher = RaindropFetcher(ContentSource(type="raindropio", src="0"))
        result = fetcher.fetch_items([])
        assert result.success is True
        assert result.articles == []

    @patch.dict("os.environ", {"RAINDROPIO_API_KEY": "key"})
    @patch.object(RaindropFetcher, "_fetch_full_text", return_value=("<p>Full</p>", "raw"))
    def test_fetch_items_uses_full_text_and_cover(self, mock_full_text):
        fetcher = RaindropFetcher(ContentSource(type="raindropio", src="0"))
        result = fetcher.fetch_items([{
            "url": "https://example.com/a", "title": "A", "excerpt": "E", "cover": "cover.jpg"
        }])
        assert result.success is True
        assert result.articles[0].content == "<p>Full</p>"
        assert result.articles[0].images == ["cover.jpg"]
        mock_full_text.assert_called_once_with("https://example.com/a")

    @patch.dict("os.environ", {"RAINDROPIO_API_KEY": "key"})
    @patch.object(RaindropFetcher, "_fetch_full_text", return_value=("", ""))
    def test_fetch_items_falls_back_and_applies_delete(self, mock_full_text):
        source = ContentSource(type="raindropio", src="0", delete="blocked")
        fetcher = RaindropFetcher(source)
        result = fetcher.fetch_items([
            {"url": "", "title": "blocked title", "excerpt": "ignored"},
            {"url": "", "title": "kept", "excerpt": "fallback"},
        ])
        assert result.success is True
        assert len(result.articles) == 1
        assert result.articles[0].content == "<p>fallback</p>"
        mock_full_text.assert_not_called()
