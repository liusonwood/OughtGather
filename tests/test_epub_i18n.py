import json
from pathlib import Path

from src.epub.i18n import DEFAULT_LOCALE, EPUBTranslator


def test_default_and_invalid_locale_fall_back_to_english(monkeypatch):
    monkeypatch.delenv("EPUB_LANGUAGE", raising=False)
    assert EPUBTranslator().locale == DEFAULT_LOCALE
    assert EPUBTranslator().translate("navigation.contents") == "Contents"

    monkeypatch.setenv("EPUB_LANGUAGE", "en")
    assert EPUBTranslator().locale == DEFAULT_LOCALE


def test_locale_uses_full_name_and_missing_resource_falls_back_to_english():
    translator = EPUBTranslator("ja-JP")
    assert translator.locale == "ja-JP"
    assert translator("summary.title") == "Summary"


def test_missing_key_falls_back_to_english(tmp_path, monkeypatch):
    locale_dir = Path(__file__).parents[1] / "src" / "epub" / "locales"
    source = json.loads((locale_dir / "zh-CN.json").read_text(encoding="utf-8"))
    source.pop("summary.title")
    temporary = tmp_path / "locales"
    temporary.mkdir()
    (temporary / "en-US.json").write_text(
        (locale_dir / "en-US.json").read_text(encoding="utf-8"), encoding="utf-8"
    )
    (temporary / "zh-CN.json").write_text(json.dumps(source), encoding="utf-8")

    monkeypatch.setattr("src.epub.i18n.LOCALES_DIR", temporary)
    assert EPUBTranslator("zh-CN")("summary.title") == "Summary"


def test_base_locale_files_have_identical_keys():
    locale_dir = Path(__file__).parents[1] / "src" / "epub" / "locales"
    english = json.loads((locale_dir / "en-US.json").read_text(encoding="utf-8"))
    chinese = json.loads((locale_dir / "zh-CN.json").read_text(encoding="utf-8"))
    assert english.keys() == chinese.keys()
