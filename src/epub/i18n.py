"""EPUB system-text localization."""

import json
import os
import re
from pathlib import Path
from typing import Any, Dict


DEFAULT_LOCALE = "en-US"
LOCALE_PATTERN = re.compile(r"^[a-z]{2,3}-[A-Z]{2,3}$")
LOCALES_DIR = Path(__file__).with_name("locales")


class EPUBTranslator:
    """Load locale resources and fall back to the English base locale."""

    def __init__(self, locale: str | None = None):
        requested = locale if locale is not None else os.getenv("EPUB_LANGUAGE", "")
        self.locale = requested.strip() if requested and LOCALE_PATTERN.fullmatch(requested.strip()) else DEFAULT_LOCALE
        self._english = self._load(DEFAULT_LOCALE)
        self._translations = self._load(self.locale) if self.locale != DEFAULT_LOCALE else self._english

    @staticmethod
    def _load(locale: str) -> Dict[str, Any]:
        path = LOCALES_DIR / f"{locale}.json"
        try:
            with path.open(encoding="utf-8") as file:
                data = json.load(file)
        except (FileNotFoundError, json.JSONDecodeError):
            return {}
        if not isinstance(data, dict):
            return {}
        return data

    def translate(self, key: str, **values: Any) -> str:
        value = self._translations.get(key, self._english.get(key))
        if value is None:
            raise KeyError(f"Missing EPUB translation key: {key}")
        if not isinstance(value, str):
            raise TypeError(f"EPUB translation value must be a string: {key}")
        return value.format(**values)

    __call__ = translate
