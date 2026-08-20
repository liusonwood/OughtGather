"""
AWS WAF 202 Challenge 自动求解模块
用于突破 AWS WAF (x-amzn-waf-action: challenge/captcha) 限制，自动换取 aws-waf-token
"""

import base64
import hashlib
import json
import os
import re
import time
import zlib
from dataclasses import dataclass
from typing import Any, Dict, Optional, Tuple
from urllib.parse import urlparse

import httpx
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from src.utils.logger import get_logger

logger = get_logger()

# AWS WAF Challenge SDK 混淆常数 AES-256 密钥
TELEMETRY_AES_KEY = bytes.fromhex(
    "6f71a512b1e035eaab53d8be73120d3fb68a0ca346b9560aab3e5cdf753d5e98"
)

# 已知 Hashcash 挑战类型标识
TYPE_SHA2 = "HashcashSHA2"
TYPE_SCRYPT = "HashcashScrypt"
ID_SCRYPT = "h72f957df656e80ba55f5d8ce2e8c7ccb59687dba3bfb273d54b08a261b2f3002"
ID_SHA2 = "h7b0c470f0cfe3a80a9e26526ad185f484f6817d0832712a4a37a908786a6a67f"


@dataclass
class WafContext:
    """从 202 页面中提取的上下文"""
    goku_props: Dict[str, Any]
    api_base: str
    challenge_js_url: str


class WafTokenCache:
    """域名级别的 Token 缓存管理器"""
    _cache: Dict[str, Tuple[str, float]] = {}
    DEFAULT_TTL: float = 1800.0  # 30 分钟

    @classmethod
    def get(cls, domain: str) -> Optional[str]:
        if domain in cls._cache:
            token, expire_at = cls._cache[domain]
            if time.time() < expire_at:
                return token
            del cls._cache[domain]
        return None

    @classmethod
    def set(cls, domain: str, token: str, ttl: float = DEFAULT_TTL):
        cls._cache[domain] = (token, time.time() + ttl)

    @classmethod
    def clear(cls):
        cls._cache.clear()


def extract_challenge_context(html: str, target_url: str) -> Optional[WafContext]:
    """
    从 202 HTML 挑战页面中提取 gokuProps 和 API 基础端点。

    Args:
        html: 202 页面 HTML
        target_url: 当前目标请求 URL

    Returns:
        WafContext | None
    """
    if not html:
        return None

    # 1. 提取 gokuProps
    goku_props = {}
    goku_match = re.search(r"window\.gokuProps\s*=\s*(\{[\s\S]*?\});", html)
    if goku_match:
        raw_obj = goku_match.group(1)
        # 尝试标准 JSON 解析或正则键值提取
        try:
            goku_props = json.loads(raw_obj)
        except Exception:
            key_m = re.search(r'["\']?key["\']?\s*:\s*["\']([^"\']+)["\']', raw_obj)
            iv_m = re.search(r'["\']?iv["\']?\s*:\s*["\']([^"\']+)["\']', raw_obj)
            ctx_m = re.search(r'["\']?context["\']?\s*:\s*["\']([^"\']+)["\']', raw_obj)
            if key_m and iv_m and ctx_m:
                goku_props = {
                    "key": key_m.group(1),
                    "iv": iv_m.group(1),
                    "context": ctx_m.group(1),
                }

    # 2. 提取 challenge.js 路径并推导 api_base
    js_match = re.search(
        r'<script[^>]+src=["\']([^"\']*/challenge\.js[^"\']*)["\']',
        html,
        re.IGNORECASE,
    )
    if not js_match:
        js_match = re.search(
            r'src=["\']([^"\']+/challenge\.js)["\']',
            html,
            re.IGNORECASE,
        )

    if not js_match:
        return None

    raw_js_url = js_match.group(1).split("?")[0]
    if raw_js_url.startswith("//"):
        challenge_js_url = "https:" + raw_js_url
    elif raw_js_url.startswith("http://") or raw_js_url.startswith("https://"):
        challenge_js_url = raw_js_url
    else:
        from urllib.parse import urljoin
        challenge_js_url = urljoin(target_url, raw_js_url)

    api_base = challenge_js_url.rsplit("/challenge.js", 1)[0]

    return WafContext(
        goku_props=goku_props,
        api_base=api_base,
        challenge_js_url=challenge_js_url,
    )


def build_telemetry(domain: str, user_agent: str) -> dict:
    """构造用于 WAF 校验的浏览器指纹对象"""
    now_ms = int(time.time() * 1000)
    return {
        "metrics": {
            "fp2": 3,
            "browser": 1,
            "capabilities": 1,
            "gpu": 1,
            "dnt": 0,
            "math": 0,
            "screen": 0,
            "navigator": 0,
            "auto": 1,
            "stealth": 0,
            "subtle": 0,
            "canvas": 1,
            "formdetector": 2,
            "be": 4,
        },
        "start": now_ms,
        "flashVersion": None,
        "plugins": [],
        "dupedPlugins": "unknown||1920-1080-1040-24-*-*-*",
        "screenInfo": "1920-1080-1040-24-*-*-*",
        "referrer": "",
        "userAgent": user_agent,
        "location": f"https://{domain}/",
        "webDriver": False,
        "capabilities": {
            "hasLiedLanguages": False,
            "hasLiedResolution": False,
            "hasLiedOs": False,
            "hasLiedBrowser": False,
            "touchSupport": [0, False, False],
        },
        "math": {
            "tan": "-1.4214488238747245",
            "sin": "0.8414709848078965",
            "cos": "0.5403023058681398",
        },
        "automation": {
            "phantom": False,
            "nightmare": False,
            "selenium": False,
            "webDriver": False,
        },
        "crypto": {"subtle": True},
        "formDetected": False,
        "numForms": 0,
        "numFormElements": 0,
        "be": {"si": False},
        "end": now_ms + 5,
        "errors": [],
        "version": "2.4.0",
        "id": str(now_ms),
    }


def encode_telemetry_signal(telemetry: dict) -> Tuple[dict, str]:
    """
    序列化 Telemetry、计算 CRC32 并执行 AES-256-GCM 加密，生成 Zoey.Present

    Returns:
        (signal_dict, checksum_hex)
    """
    # 严格采用紧凑序列化（无多余空格）
    telemetry_json = json.dumps(
        telemetry,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    checksum = f"{zlib.crc32(telemetry_json.encode('utf-8')) & 0xFFFFFFFF:08X}"
    plaintext = f"{checksum}#{telemetry_json}".encode("utf-8")

    iv = os.urandom(12)
    encrypted = AESGCM(TELEMETRY_AES_KEY).encrypt(iv, plaintext, None)
    ciphertext = encrypted[:-16]
    tag = encrypted[-16:]
    iv_b64 = base64.b64encode(iv).decode("ascii").rstrip("=")

    present = f"{iv_b64}::{tag.hex()}::{ciphertext.hex()}"
    signal = {"name": "Zoey", "value": {"Present": present}}
    return signal, checksum


def _check_difficulty(digest_bytes: bytes, difficulty: int) -> bool:
    """检查哈希前导 0 bit 数量是否满足 difficulty"""
    full_zero_bytes = difficulty // 8
    rem_bits = difficulty % 8

    if digest_bytes[:full_zero_bytes] != b"\x00" * full_zero_bytes:
        return False

    if rem_bits > 0:
        next_byte = digest_bytes[full_zero_bytes]
        mask = ((1 << rem_bits) - 1) << (8 - rem_bits)
        if (next_byte & mask) != 0:
            return False

    return True


def solve_hashcash(
    challenge_type: str,
    challenge_input: str,
    checksum: str,
    difficulty: int = 4,
    max_iterations: int = 5000000,
) -> Tuple[str, str]:
    """
    求解 Hashcash PoW

    Args:
        challenge_type: 题目类型 (SHA2 或 Scrypt)
        challenge_input: 题目输入字符串
        checksum: 与 Telemetry 绑定的 CRC32
        difficulty: 难度（前导 0 bit 数）
        max_iterations: 最大尝试次数

    Returns:
        (solution_nonce_str, digest_hex)
    """
    payload_prefix = f"{challenge_input}{checksum}".encode("utf-8")
    is_scrypt = challenge_type in (TYPE_SCRYPT, ID_SCRYPT) or "scrypt" in challenge_type.lower()
    salt = checksum.encode("utf-8") if is_scrypt else b""

    for nonce in range(max_iterations):
        nonce_bytes = str(nonce).encode("ascii")
        data = payload_prefix + nonce_bytes

        if is_scrypt:
            h = hashlib.scrypt(data, salt=salt, n=128, r=8, p=1, dklen=16)
        else:
            h = hashlib.sha256(data).digest()

        if _check_difficulty(h, difficulty):
            return str(nonce), h.hex()

    raise RuntimeError(f"Hashcash solver exceeded max iterations ({max_iterations})")


def solve_aws_waf(
    client: httpx.Client,
    target_url: str,
    challenge_html: str,
    user_agent: str,
    timeout: int = 15,
) -> Optional[str]:
    """
    执行完整的 AWS WAF 202 挑战求解链路并换取 aws-waf-token。

    Args:
        client: httpx.Client 客户端实例
        target_url: 原请求目标 URL
        challenge_html: 202 挑战页面 HTML 内容
        user_agent: 发送请求使用的 User-Agent
        timeout: 超时时间（秒）

    Returns:
        token 字符串，若求解失败则返回 None
    """
    try:
        domain = urlparse(target_url).netloc
        ctx = extract_challenge_context(challenge_html, target_url)
        if not ctx:
            logger.warning(f"AWS WAF: Failed to extract challenge context from {target_url}")
            return None

        logger.info(f"AWS WAF: Solving challenge for {domain} via {ctx.api_base}")

        # 1. 请求 /inputs 获取题目
        inputs_url = f"{ctx.api_base}/inputs?client=browser"
        inputs_resp = client.get(
            inputs_url,
            headers={
                "User-Agent": user_agent,
                "Accept": "*/*",
                "Referer": target_url,
            },
            timeout=timeout,
        )
        if inputs_resp.status_code != 200:
            logger.warning(f"AWS WAF: /inputs returned HTTP {inputs_resp.status_code}")
            return None

        inputs_data = inputs_resp.json()
        challenge_obj = inputs_data.get("challenge") or {}
        challenge_type = inputs_data.get("challenge_type", TYPE_SHA2)
        difficulty = int(inputs_data.get("difficulty", 4))
        challenge_input = challenge_obj.get("input", "")

        # 2. 生成 Telemetry Signal 与 CRC32 Checksum
        telemetry = build_telemetry(domain, user_agent)
        signal, checksum = encode_telemetry_signal(telemetry)

        # 3. 求解 Hashcash PoW
        solution, digest = solve_hashcash(
            challenge_type=challenge_type,
            challenge_input=challenge_input,
            checksum=checksum,
            difficulty=difficulty,
        )
        logger.debug(
            f"AWS WAF: PoW solved (nonce={solution}, difficulty={difficulty}, digest={digest[:8]}...)"
        )

        # 4. POST /verify 提交验证换取 token
        verify_body = {
            "challenge": challenge_obj,
            "solution": solution,
            "signals": [signal],
            "checksum": checksum,
            "existing_token": None,
            "client": "Browser",
            "domain": domain,
            "metrics": [],
            "goku_props": ctx.goku_props,
        }

        verify_url = f"{ctx.api_base}/verify"
        verify_resp = client.post(
            verify_url,
            headers={
                "User-Agent": user_agent,
                "Content-Type": "application/json",
                "Accept": "*/*",
                "Referer": target_url,
            },
            content=json.dumps(verify_body, separators=(",", ":"), ensure_ascii=False),
            timeout=timeout,
        )

        if verify_resp.status_code != 200:
            logger.warning(
                f"AWS WAF: /verify failed (HTTP {verify_resp.status_code}): {verify_resp.text[:200]}"
            )
            return None

        token = verify_resp.json().get("token")
        if token:
            WafTokenCache.set(domain, token)
            logger.info(f"AWS WAF: Successfully obtained aws-waf-token for {domain}")
            return token
        else:
            logger.warning(f"AWS WAF: /verify response did not contain token: {verify_resp.text}")
            return None

    except Exception as e:
        logger.error(f"AWS WAF: Challenge resolution failed for {target_url}: {e}")
        return None
