# i18n_merger.py

Утилита для объединения файлов локализации (YAML / JSON / JS default-exports) в единый JSON-файл с сохранением вложенной структуры.

## Использование

```sh
python i18n_merger.py merge-yaml --input-dir ./src/yaml --output ./dst/backend.json
python i18n_merger.py merge-json --input-dir ./src/json --output ./dst/translations.json
python i18n_merger.py merge-js   --input-dir ./src/js   --output ./dst/frontend.json
```

- Поддерживаются форматы YAML, JSON и JS (экспорт по умолчанию).
- Сохраняется вложенность ключей и структура переводов.
- Для JS-файлов поддерживаются template-literals.

## Зависимости

- Python 3.8+
- [PyYAML](https://pypi.org/project/PyYAML/)
- [json5](https://pypi.org/project/json5/)
- [quickjs](https://pypi.org/project/quickjs/)

Установить зависимости:

```sh
pip install -r requirements.txt
```

## Структура проекта

- `i18n_merger.py` — основной скрипт
- `src/` — исходные файлы переводов (yaml, json, js)
- `dst/` — результирующие объединённые файлы

## Пример запуска

```sh
python i18n_merger.py merge-yaml --input-dir src/yaml --output dst/backend.json
```

## Лицензия

MIT
