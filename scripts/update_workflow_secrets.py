import os
import importlib.util
import sys
import re
from pathlib import Path

# Add project root to path so we can import src.config etc.
sys.path.append(os.getcwd())

def get_all_required_secrets():
    secrets = {}
    fetchers_dir = Path('src/fetchers')
    
    for file in fetchers_dir.glob('*.py'):
        if file.name == '__init__.py' or file.name == 'base.py':
            continue
            
        module_name = file.stem
        spec = importlib.util.spec_from_file_location(module_name, file)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        
        # Look for classes that have required_secrets
        for name in dir(module):
            obj = getattr(module, name)
            if hasattr(obj, 'required_secrets') and isinstance(obj.required_secrets, dict):
                secrets.update(obj.required_secrets)
                
    return secrets

def update_workflow(secrets):
    workflow_path = '.github/workflows/daily-gather.yml'
    with open(workflow_path, 'r', encoding='utf-8') as f:
        content = f.read()
    
    # 构造新的 env 块
    # 从现有 workflow 中提取时区设置（保留，不自动更新）
    tz_match = re.search(r'^(\s*)(TZ:\s*\S+)', content, re.MULTILINE)
    existing_tz = tz_match.group(2) if tz_match else "TZ: Asia/Shanghai"

    new_env = "        env:\n"
    new_env += "          # 时区设置\n"
    new_env += f"          {existing_tz}\n\n"
    new_env += "          # SMTP 配置（必需）\n"
    new_env += "          SMTP_HOST: ${{ secrets.SMTP_HOST }}\n"
    new_env += "          SMTP_PORT: ${{ secrets.SMTP_PORT }}\n"
    new_env += "          SMTP_USERNAME: ${{ secrets.SMTP_USERNAME }}\n"
    new_env += "          SMTP_PASSWORD: ${{ secrets.SMTP_PASSWORD }}\n"
    new_env += "          KINDLE_EMAIL: ${{ secrets.KINDLE_EMAIL }}\n\n"
    new_env += "          # WebDAV 配置\n"
    new_env += "          WEBDAV_ENABLED: ${{ secrets.WEBDAV_ENABLED }}\n"
    new_env += "          WEBDAV_PASSWORD: ${{ secrets.WEBDAV_PASSWORD }}\n"
    new_env += "          WEBDAV_REMOTE_PATH: ${{ secrets.WEBDAV_REMOTE_PATH }}\n"
    new_env += "          WEBDAV_URL: ${{ secrets.WEBDAV_URL }}\n"
    new_env += "          WEBDAV_USERNAME: ${{ secrets.WEBDAV_USERNAME }}\n\n"
    new_env += "          # EPUB localization and Bing wallpaper market (optional)\n"
    new_env += "          EPUB_LANGUAGE: ${{ secrets.EPUB_LANGUAGE }}\n\n"
    new_env += "          # 自动注入 Secrets\n"
    
    # Sort keys
    for key in sorted(secrets.keys()):
        new_env += f"          {key}: ${{{{ secrets.{key} }}}}\n"
    
    # 正则替换 env 块
    # 匹配 "Run Ought Gather" 步骤下的 env 块
    env_pattern = r'name: Run Ought Gather\n\s*env:[\s\S]*?run: \|'
    
    new_content = re.sub(env_pattern, f"name: Run Ought Gather\n{new_env}\n        run: |", content)
    
    with open(workflow_path, 'w', encoding='utf-8') as f:
        f.write(new_content)
    print(f"Successfully updated {workflow_path}")

if __name__ == '__main__':
    secrets = get_all_required_secrets()
    update_workflow(secrets)
