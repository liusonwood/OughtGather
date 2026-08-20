"""
AWS WAF 202 Challenge 自动求解器单元测试
"""

import base64
import json
import zlib
import pytest
from unittest.mock import MagicMock, patch
import httpx
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from src.utils.aws_waf import (
    TELEMETRY_AES_KEY,
    TYPE_SHA2,
    TYPE_SCRYPT,
    WafTokenCache,
    extract_challenge_context,
    build_telemetry,
    encode_telemetry_signal,
    solve_hashcash,
    solve_aws_waf,
    _check_difficulty,
)
from src.config import ContentSource
from src.fetchers.base import BaseFetcher, FetchResult


class DummyFetcher(BaseFetcher):
    type_name = "dummy"

    def fetch(self) -> FetchResult:
        return FetchResult(source=self.source, articles=[])


class TestExtractChallengeContext:
    """上下文提取测试"""

    def test_valid_html_extraction(self):
        html = """
        <!DOCTYPE html>
        <html>
        <head>
            <script>
            window.gokuProps = {
                "key": "test_key_123",
                "iv": "test_iv_456",
                "context": "test_context_789"
            };
            </script>
            <script src="https://a1b2c3d4.token.awswaf.com/a1b2c3d4/challenge.js"></script>
        </head>
        <body>WAF Challenge</body>
        </html>
        """
        ctx = extract_challenge_context(html, "https://www.scientificamerican.com/feed/")
        assert ctx is not None
        assert ctx.goku_props.get("key") == "test_key_123"
        assert ctx.goku_props.get("iv") == "test_iv_456"
        assert ctx.goku_props.get("context") == "test_context_789"
        assert ctx.api_base == "https://a1b2c3d4.token.awswaf.com/a1b2c3d4"
        assert ctx.challenge_js_url == "https://a1b2c3d4.token.awswaf.com/a1b2c3d4/challenge.js"

    def test_unquoted_js_props(self):
        html = """
        <script>
        window.gokuProps = {
            key: "unquoted_key",
            iv: "unquoted_iv",
            context: "unquoted_ctx"
        };
        </script>
        <script src="https://tenant123.token.awswaf.com/subpath/challenge.js"></script>
        """
        ctx = extract_challenge_context(html, "https://example.com")
        assert ctx is not None
        assert ctx.goku_props.get("key") == "unquoted_key"
        assert ctx.goku_props.get("iv") == "unquoted_iv"
        assert ctx.goku_props.get("context") == "unquoted_ctx"

    def test_missing_challenge_js(self):
        html = "<html><body>No challenge script here</body></html>"
        ctx = extract_challenge_context(html, "https://example.com")
        assert ctx is None

    def test_empty_html(self):
        assert extract_challenge_context("", "https://example.com") is None


class TestTelemetryAndEncryption:
    """Telemetry 生成、校验和与 AES-GCM 加解密测试"""

    def test_telemetry_encoding_and_decryption(self):
        domain = "www.scientificamerican.com"
        ua = "Mozilla/5.0 TestBrowser"
        telemetry = build_telemetry(domain, ua)
        signal, checksum = encode_telemetry_signal(telemetry)

        # 校验 signal 结构
        assert signal["name"] == "Zoey"
        present = signal["value"]["Present"]
        parts = present.split("::")
        assert len(parts) == 3

        iv_b64, tag_hex, cipher_hex = parts
        # 补全 base64 padding
        pad_len = (4 - len(iv_b64) % 4) % 4
        iv = base64.b64decode(iv_b64 + "=" * pad_len)
        assert len(iv) == 12

        tag = bytes.fromhex(tag_hex)
        assert len(tag) == 16
        ciphertext = bytes.fromhex(cipher_hex)

        # 用 AESGCM 解密验证
        plaintext = AESGCM(TELEMETRY_AES_KEY).decrypt(iv, ciphertext + tag, None)
        plaintext_str = plaintext.decode("utf-8")

        # 验证明文格式为 checksum#json
        assert "#" in plaintext_str
        recovered_checksum, recovered_json_str = plaintext_str.split("#", 1)
        assert recovered_checksum == checksum

        # 验证 CRC32 校验和
        expected_crc = f"{zlib.crc32(recovered_json_str.encode('utf-8')) & 0xFFFFFFFF:08X}"
        assert checksum == expected_crc

        # 验证 JSON 内容
        recovered_obj = json.loads(recovered_json_str)
        assert recovered_obj["location"] == f"https://{domain}/"
        assert recovered_obj["userAgent"] == ua


class TestSolveHashcash:
    """PoW Hashcash 求解测试"""

    def test_check_difficulty(self):
        assert _check_difficulty(b"\x00\x00\x12", 16) is True
        assert _check_difficulty(b"\x00\x7f\x00", 9) is True   # 00000000 01111111 -> 9 leading zeros
        assert _check_difficulty(b"\x00\x80\x00", 9) is False  # 00000000 10000000 -> 8 leading zeros
        assert _check_difficulty(b"\x0f\x00", 4) is True      # 00001111 -> 4 leading zeros
        assert _check_difficulty(b"\x1f\x00", 4) is False     # 00011111 -> 3 leading zeros

    def test_solve_hashcash_sha2(self):
        challenge_input = "test_challenge_input_"
        checksum = "ABCD1234"
        difficulty = 6  # 前导 6 bit 0

        nonce, digest = solve_hashcash(
            challenge_type=TYPE_SHA2,
            challenge_input=challenge_input,
            checksum=checksum,
            difficulty=difficulty,
            max_iterations=100000,
        )

        assert nonce.isdigit()
        digest_bytes = bytes.fromhex(digest)
        assert _check_difficulty(digest_bytes, difficulty) is True

    def test_solve_hashcash_scrypt(self):
        challenge_input = "test_challenge_scrypt_"
        checksum = "B19C567E"
        difficulty = 4  # 4 bit 0

        nonce, digest = solve_hashcash(
            challenge_type=TYPE_SCRYPT,
            challenge_input=challenge_input,
            checksum=checksum,
            difficulty=difficulty,
            max_iterations=10000,
        )

        assert nonce.isdigit()
        digest_bytes = bytes.fromhex(digest)
        assert _check_difficulty(digest_bytes, difficulty) is True


class TestWafTokenCache:
    """Token 缓存测试"""

    def setup_method(self):
        WafTokenCache.clear()

    def test_cache_set_and_get(self):
        WafTokenCache.set("example.com", "token_123", ttl=100)
        assert WafTokenCache.get("example.com") == "token_123"
        assert WafTokenCache.get("other.com") is None

    def test_cache_expiration(self):
        WafTokenCache.set("example.com", "token_expired", ttl=-1)
        assert WafTokenCache.get("example.com") is None


class TestSolveAwsWafEndToEnd:
    """模拟端到端 solve_aws_waf 流程测试"""

    def test_solve_aws_waf_success(self):
        html = """
        <script>
        window.gokuProps = {"key": "k", "iv": "i", "context": "c"};
        </script>
        <script src="https://waf.example.com/ch/challenge.js"></script>
        """

        client = httpx.Client()
        target_url = "https://www.scientificamerican.com/feed/"

        def mock_get(url, **kwargs):
            if "inputs?client=browser" in url:
                return httpx.Response(
                    200,
                    json={
                        "challenge": {"input": "test_input", "hmac": "hmac", "region": "us-east-1"},
                        "challenge_type": "HashcashSHA2",
                        "difficulty": 4,
                    },
                    request=httpx.Request("GET", url),
                )
            return httpx.Response(404, request=httpx.Request("GET", url))

        def mock_post(url, **kwargs):
            if "/verify" in url:
                body = json.loads(kwargs.get("content", "{}"))
                assert "solution" in body
                assert "signals" in body
                assert "checksum" in body
                return httpx.Response(
                    200,
                    json={"token": "mocked_aws_waf_token_xyz"},
                    request=httpx.Request("POST", url),
                )
            return httpx.Response(404, request=httpx.Request("POST", url))

        with patch.object(client, "get", side_effect=mock_get), \
             patch.object(client, "post", side_effect=mock_post):
            token = solve_aws_waf(client, target_url, html, "Mozilla/5.0")
            assert token == "mocked_aws_waf_token_xyz"
            assert WafTokenCache.get("www.scientificamerican.com") == "mocked_aws_waf_token_xyz"


class TestBaseFetcherIntegration:
    """BaseFetcher 遇到 202 挑战自动重试测试"""

    def test_base_fetcher_handles_202_challenge(self):
        source = ContentSource(type="dummy", src="https://www.scientificamerican.com/feed/")
        fetcher = DummyFetcher(source)

        challenge_html = """
        <html>
        <script>window.gokuProps = {"key": "k", "iv": "i", "context": "c"};</script>
        <script src="https://waf.test.com/id/challenge.js"></script>
        </html>
        """

        # 模拟响应序列：第1次返回 202 挑战，第2次（求解后带 token 重试）返回 200
        resp_202 = httpx.Response(
            202,
            headers={"x-amzn-waf-action": "challenge", "content-type": "text/html"},
            content=challenge_html.encode("utf-8"),
            request=httpx.Request("GET", source.src),
        )

        resp_200 = httpx.Response(
            200,
            headers={"content-type": "application/xml"},
            content=b"<xml><title>Success Feed</title></xml>",
            request=httpx.Request("GET", source.src),
        )

        mock_requests = [resp_202, resp_200]

        # 隔离真实网络请求：模拟 _curl_cffi_fallback 失败时触发 httpx 降级分支
        with patch.object(fetcher, "_curl_cffi_fallback", return_value=None), \
             patch("src.fetchers.base.solve_aws_waf", return_value="token_12345") as mock_solver, \
             patch.object(httpx.Client, "request", side_effect=lambda *args, **kwargs: mock_requests.pop(0)):
            resp = fetcher._make_request(source.src, browser=True)
            assert resp.status_code == 200
            assert b"Success Feed" in resp.content
            mock_solver.assert_called_once()

    def test_curl_cffi_fallback_and_waf_solve(self):
        source = ContentSource(type="dummy", src="https://www.scientificamerican.com/feed/")
        fetcher = DummyFetcher(source)

        mock_202 = MagicMock()
        mock_202.status_code = 202
        mock_202.headers = {"x-amzn-waf-action": "challenge"}
        mock_202.text = "<html>challenge</html>"
        mock_202.url = source.src

        mock_200 = MagicMock()
        mock_200.status_code = 200
        mock_200.headers = {}
        mock_200.content = b"<html><body>Recovered Content</body></html>"
        mock_200.text = "<html><body>Recovered Content</body></html>"
        mock_200.url = source.src

        mock_session = MagicMock()
        mock_session.get.side_effect = [mock_202, mock_200]

        with patch("curl_cffi.requests.Session", return_value=mock_session), \
             patch("src.fetchers.base.solve_aws_waf", return_value="token_12345") as mock_solver:
            res = fetcher._curl_cffi_fallback(source.src)
            assert res is not None
            assert res.status_code == 200
            assert b"Recovered Content" in res.content
            mock_solver.assert_called_once()
