#!/usr/bin/env python3
"""
i18n_merger.py — merge localisation files (YAML / JSON / JS default-exports)
into a single JSON file with **preserved nesting**.

Usage
-----
python i18n_merger.py merge-yaml --input-dir ./src/yaml --output ./dst/backend.json
python i18n_merger.py merge-json --input-dir ./src/json --output ./dst/translations.json
python i18n_merger.py merge-js   --input-dir ./src/js   --output ./dst/frontend.json
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Dict, Mapping, MutableMapping

import json5
import quickjs
import yaml


# --------------------------------------------------------------------------- #
class InvalidTranslationFile(ValueError):
    """Raised when a localisation file has an unexpected structure."""


class BaseMerger(ABC):
    """Base class for any file-type merger."""

    def __init__(self, input_dir: Path) -> None:
        if not input_dir.is_dir():
            raise FileNotFoundError(f"{input_dir} is not a directory")
        self.input_dir = input_dir.resolve()

    @abstractmethod
    def merge(self) -> Dict[str, Any]:  # noqa: D401
        """Return merged translations with nested structure preserved."""

    # ---------- helpers ---------------------------------------------------- #
    @staticmethod
    def _validate_tree(node: Any, filename: Path) -> None:
        """
        Рекурсивно проверяем дерево переводов.

        Допустимые листья:
        • str
        • list[...]   — элементы рекурсивно валидируются
        • dict        — элементы рекурсивно валидируются
        """
        if isinstance(node, Mapping):            # словарь
            for v in node.values():
                BaseMerger._validate_tree(v, filename)

        elif isinstance(node, list):             # массив
            for item in node:
                BaseMerger._validate_tree(item, filename)

        elif not isinstance(node, str):          # всё остальное запрещено
            raise InvalidTranslationFile(
                f"{filename}: leaf values must be strings, got {type(node).__name__}"
            )


# ---------- deep-merge routine --------------------------------------------- #
def _merge_nested(
    base: MutableMapping[str, Any],
    incoming: Mapping[str, Any],
    lang: str,
    filename: Path,
) -> None:
    """
    Рекурсивно сливаем `incoming` в `base`.

    * dict  → углубляемся рекурсией;
    * list  → элементы объединяем по индексам:
        ─ элемент-строка        → {"ru": "...", "en": "..."}
        ─ элемент-словарь       → объединяем так же рекурсивно;
    * str   → прежнее поведение.
    """
    for key, value in incoming.items():

        # ---------- вложенный словарь ----------------------------------
        if isinstance(value, Mapping):
            base.setdefault(key, {})
            if not isinstance(base[key], Mapping):
                raise InvalidTranslationFile(
                    f"Structure mismatch at key '{key}' between languages (file {filename})"
                )
            _merge_nested(base[key], value, lang, filename)

        # ---------- массив --------------------------------------------
        elif isinstance(value, list):
            base.setdefault(key, [])
            dst_list: list[Any] = base[key]  # type: ignore[arg-type]

            if not isinstance(dst_list, list):
                raise InvalidTranslationFile(
                    f"Structure mismatch at key '{key}' between languages (file {filename})"
                )

            # расширяем список, если этот язык принёс больше элементов
            while len(dst_list) < len(value):
                # пустая «ячейка» — словарь (для строк и словарей)
                dst_list.append({})

            for i, item in enumerate(value):
                # гарантируем, что dst_list[i] — dict (контейнер для слияния)
                if not isinstance(dst_list[i], Mapping):
                    dst_list[i] = {}

                if isinstance(item, Mapping):            # объект внутри массива
                    _merge_nested(dst_list[i], item, lang, filename)

                elif isinstance(item, str):              # строка внутри массива
                    dst_list[i][lang] = item

                else:                                    # недопустимый тип
                    raise InvalidTranslationFile(
                        f"{filename}: unsupported array element "
                        f"type {type(item).__name__} at key '{key}[{i}]'"
                    )

        # ---------- строка --------------------------------------------
        else:
            leaf = base.setdefault(key, {})
            if not isinstance(leaf, Mapping):
                raise InvalidTranslationFile(
                    f"Structure mismatch at key '{key}' between languages (file {filename})"
                )
            leaf[lang] = value


# --------------------------------------------------------------------------- #
class YamlMerger(BaseMerger):
    def merge(self) -> Dict[str, Any]:
        merged: Dict[str, Any] = {}
        for file in self.input_dir.glob("*.y*ml"):
            lang = file.stem
            payload: Any = yaml.safe_load(file.read_text(encoding="utf-8")) or {}
            self._validate_tree(payload, file)
            _merge_nested(merged, payload, lang, file)
        return merged


class JsonMerger(BaseMerger):
    def merge(self) -> Dict[str, Any]:
        merged: Dict[str, Any] = {}
        for file in self.input_dir.glob("*.json"):
            lang = file.stem
            payload: Any = json.loads(file.read_text(encoding="utf-8"))
            self._validate_tree(payload, file)
            _merge_nested(merged, payload, lang, file)
        return merged


class JsMerger(BaseMerger):
    """
    Парсит файлы формата  export default { ... };
    Понимает template-literals через json5 или (fallback) QuickJS.
    """

    _re_export   = re.compile(r"^\s*export\s+default\s+", re.I | re.S)
    _re_backtick = re.compile(r"`([^`\\]*(?:\\.[^`\\]*)*)`", re.S)

    @staticmethod
    def _strip_template_literals(src: str) -> str:
        """`строка` → "строка", если нет ${…}."""
        def repl(m: re.Match) -> str:
            body = m.group(1)
            if "${" in body:
                return m.group(0)                  # оставляем как есть
            return json.dumps(body, ensure_ascii=False)
        return JsMerger._re_backtick.sub(repl, src)

    # ----------------------------------------------------------------- #
    def _load_js_object(self, file: Path) -> Mapping[str, Any]:
        src = file.read_text(encoding="utf-8")
        src = self._re_export.sub("(", src, count=1).rstrip()
        if src.endswith(";"):
            src = src[:-1].rstrip()
        src += ")"                                 # делаем выражение

        # 1) дешёвый вариант — json5
        try:
            return json5.loads(self._strip_template_literals(src))
        except ValueError:
            pass

        # 2) полный парсинг QuickJS
        ctx = quickjs.Context()
        try:
            json_str = ctx.eval(f"JSON.stringify({src})")
            return json.loads(json_str)
        except quickjs.JSException as exc:
            raise InvalidTranslationFile(f"{file}: {exc}") from exc

    # ----------------------------------------------------------------- #
    def merge(self) -> Dict[str, Any]:
        merged: Dict[str, Any] = {}
        for file in self.input_dir.glob("*.js"):
            lang = file.stem
            payload = self._load_js_object(file)
            self._validate_tree(payload, file)
            _merge_nested(merged, payload, lang, file)
        return merged


# --------------------------------------------------------------------------- #
def _get_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Merge i18n files into a single JSON file.")
    sub = p.add_subparsers(dest="command", required=True)

    def _add(name: str, help_: str) -> None:
        sp = sub.add_parser(name, help=help_)
        sp.add_argument("--input-dir", type=Path, required=True, help="Directory with language files")
        sp.add_argument("--output", type=Path, default=Path("translations.json"), help="Output file")

    _add("merge-yaml", "Merge *.yaml / *.yml files")
    _add("merge-json", "Merge flat JSON files")
    _add("merge-js",   "Merge JS files containing `export default { ... }`")
    return p


def _write_output(tree: Dict[str, Any], dst: Path) -> None:
    dst.write_text(json.dumps(tree, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"✅ wrote {dst} ({len(tree)} top-level keys)")


def main(argv: list[str] | None = None) -> None:
    args = _get_parser().parse_args(argv)

    merger: BaseMerger
    match args.command:
        case "merge-yaml":
            merger = YamlMerger(args.input_dir)
        case "merge-json":
            merger = JsonMerger(args.input_dir)
        case "merge-js":
            merger = JsMerger(args.input_dir)
        case _:
            sys.exit(f"Unknown command {args.command!r}")

    _write_output(merger.merge(), args.output)


if __name__ == "__main__":
    main()
