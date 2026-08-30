import os
import importlib.util
import sys
import re
from pathlib import Path

# Add project root to path so we can import src.config etc.
sys.path.append(os.getcwd())

# ── 必要变量（核心运行所需，与 Fetcher 无关） ────────────────────────────────
BASE_SECRETS = {
    "SMTP_HOST":        "发件邮箱 SMTP 服务器地址，如 `smtp.gmail.com`",
    "SMTP_PORT":        "发件邮箱 SMTP 端口；`465` 使用 SSL，`587` 使用 STARTTLS",
    "SMTP_USERNAME":    "发件邮箱账号",
    "SMTP_PASSWORD":    "发件邮箱密码或应用授权码",
    "KINDLE_EMAIL":     "Kindle 接收邮箱（`@kindle.com`）",
    "WEBDAV_ENABLED":   "设置为 `true` 以启用 WebDAV 上传",
    "WEBDAV_URL":       "WebDAV 服务器地址",
    "WEBDAV_USERNAME":  "WebDAV 用户名",
    "WEBDAV_PASSWORD":  "WebDAV 密码",
    "WEBDAV_REMOTE_PATH": "远程存储路径，默认 `/`",
    "CONFIG_JSON":      "完整的 `config.json` 字符串；优先级高于项目根目录的 `config.json` 文件。推荐在 GitHub Actions 中使用，可避免将私有内容源写入仓库",
    "EPUB_LANGUAGE":    "可选 EPUB/Bing locale，例如 `en-US` 或 `zh-CN`；未设置或无效时使用英文 `en-US`",
}


def get_fetcher_secrets() -> dict:
    """从各 Fetcher 类的 required_secrets 属性收集 Fetcher 自定义变量。"""
    secrets = {}
    fetchers_dir = Path('src/fetchers')

    for file in fetchers_dir.glob('*.py'):
        if file.name in ('__init__.py', 'base.py'):
            continue

        module_name = file.stem
        spec = importlib.util.spec_from_file_location(module_name, file)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        for name in dir(module):
            obj = getattr(module, name)
            if hasattr(obj, 'required_secrets') and isinstance(obj.required_secrets, dict):
                secrets.update(obj.required_secrets)

    return secrets


def _build_table(header: str, secrets: dict) -> str:
    """生成单个 Markdown 表格（含小标题）。"""
    lines = [
        "",
        f"### {header}",
        "",
        "| Secret / 环境变量 | 说明 |",
        "| --- | --- |",
    ]
    for key in sorted(secrets.keys()):
        desc = secrets[key]
        clean_key = key.replace('*', '')
        lines.append(f"| `{clean_key}` | {desc} |")
    lines.append("")  # 末尾空行
    return "\n".join(lines)


def generate_markdown_section(base_secrets: dict, fetcher_secrets: dict) -> str:
    """生成完整的 Secrets 配置 section，包含两个子表格。"""
    parts = []
    parts.append(_build_table("必要变量", base_secrets))
    parts.append(_build_table("Fetcher 自定义变量", fetcher_secrets))
    return "\n".join(parts)


def update_readme(section_content: str):
    """用行扫描方式定位并替换 README 中的 Secrets 表格区域（幂等）。

    策略：
    1. 找到第一个 '| Secret / 环境变量' 行作为锚点。
    2. 向前回溯，将紧邻的空行和 ### 子标题一并纳入替换范围（start）。
    3. 向后扫描，将所有属于同一表格块的行（表格行、### 子标题、空行）
       纳入替换范围（end），遇到非这三类的行即停止。
    """
    readme_path = 'README.md'
    with open(readme_path, 'r', encoding='utf-8') as f:
        lines = f.readlines()

    TABLE_HEADER_MARKER = '| Secret / 环境变量'

    # ── 1. 找到第一个表格标题行 ──────────────────────────────────────────────
    anchor = None
    for i, line in enumerate(lines):
        if line.startswith(TABLE_HEADER_MARKER):
            anchor = i
            break

    if anchor is None:
        raise RuntimeError("README.md 中未找到 '| Secret / 环境变量' 表格，请手动检查。")

    # ── 2. 向前回溯：吃掉前面紧邻的空行和 ### 子标题 ────────────────────────
    start = anchor
    while start > 0:
        prev = lines[start - 1].strip()
        if prev == '' or prev.startswith('###'):
            start -= 1
        else:
            break

    # ── 3. 向后扫描：吃掉所有表格行、### 子标题、空行 ────────────────────────
    def _in_block(line: str) -> bool:
        s = line.strip()
        return s.startswith('|') or s.startswith('###') or s == ''

    end = anchor
    while end < len(lines) and _in_block(lines[end]):
        end += 1

    # ── 4. 拼接 ─────────────────────────────────────────────────────────────
    new_lines = (
        lines[:start]
        + [section_content.rstrip('\n') + '\n\n']
        + lines[end:]
    )

    with open(readme_path, 'w', encoding='utf-8') as f:
        f.writelines(new_lines)


if __name__ == '__main__':
    fetcher_secrets = get_fetcher_secrets()
    section = generate_markdown_section(BASE_SECRETS, fetcher_secrets)
    update_readme(section)
    print("Successfully updated README.md secrets table")
    print(f"  必要变量: {len(BASE_SECRETS)} 条")
    print(f"  Fetcher 自定义变量: {len(fetcher_secrets)} 条")
