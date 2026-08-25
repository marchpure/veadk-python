"""Bounded parsers shared by local source connector adapters."""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from html.parser import HTMLParser
from pathlib import Path
from typing import Literal, Protocol, cast

DocumentSourceType = Literal["markdown", "text", "html"]


class _ArrowField(Protocol):
    type: object


class _ArrowListType(Protocol):
    value_type: object


class _ArrowMapType(Protocol):
    key_type: object
    item_type: object


def bounded_integer(
    configuration: Mapping[str, object],
    key: str,
    *,
    default: int,
    maximum: int,
) -> int:
    value = configuration.get(key, default)
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{key} must be an integer")
    if value < 1 or value > maximum:
        raise ValueError(f"{key} must be between 1 and {maximum}")
    return value


def read_json_rows(
    path: Path, *, max_depth: int, max_rows: int
) -> list[dict[str, object]]:
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError as error:
        raise ValueError("JSON source must be UTF-8") from error
    try:
        if path.suffix.lower() in {".jsonl", ".ndjson"}:
            value: object = [
                json.loads(line) for line in text.splitlines() if line.strip()
            ]
        else:
            value = json.loads(text)
    except json.JSONDecodeError as error:
        raise ValueError("JSON source is invalid") from error
    if _json_depth(value) > max_depth:
        raise ValueError("JSON source exceeds the configured nesting depth")
    values = value if isinstance(value, list) else [value]
    if len(values) > max_rows:
        raise ValueError("JSON source exceeds the configured record limit")
    rows: list[dict[str, object]] = []
    for row in values:
        if not isinstance(row, dict):
            raise TypeError("JSON source must contain an object or an array of objects")
        rows.append({str(key): item for key, item in row.items()})
    return rows


def infer_mapping_fields(
    rows: list[dict[str, object]],
) -> list[tuple[str, str, bool]]:
    names: list[str] = []
    for row in rows:
        for name in row:
            if name not in names:
                names.append(name)
    fields: list[tuple[str, str, bool]] = []
    for name in names:
        values = [row.get(name) for row in rows]
        present = [value for value in values if value is not None]
        if present and all(isinstance(value, bool) for value in present):
            data_type = "boolean"
        elif present and all(
            isinstance(value, int) and not isinstance(value, bool) for value in present
        ):
            data_type = "integer"
        elif present and all(
            isinstance(value, (int, float)) and not isinstance(value, bool)
            for value in present
        ):
            data_type = "number"
        elif present and all(isinstance(value, str) for value in present):
            data_type = "string"
        elif present and all(isinstance(value, list) for value in present):
            data_type = "array"
        elif present and all(isinstance(value, dict) for value in present):
            data_type = "object"
        else:
            data_type = "mixed"
        fields.append((name, data_type, len(present) != len(values)))
    return fields


def read_parquet(
    path: Path,
    *,
    max_rows: int,
    max_columns: int,
    max_uncompressed_bytes: int,
    max_nesting_depth: int,
) -> tuple[list[dict[str, object]], list[tuple[str, str, bool]]]:
    try:
        import pyarrow.parquet as pq
    except ImportError as error:
        raise ValueError(
            "Parquet adapter requires the server-side pyarrow dependency"
        ) from error
    try:
        parquet = pq.ParquetFile(path)
        metadata = parquet.metadata
        schema = parquet.schema_arrow
    except Exception as error:
        raise ValueError("Parquet source is invalid") from error
    if metadata.num_rows > max_rows:
        raise ValueError("Parquet source exceeds the configured record limit")
    if len(schema) > max_columns:
        raise ValueError("Parquet source exceeds the configured column limit")
    if max((_arrow_type_depth(field.type) for field in schema), default=1) > (
        max_nesting_depth
    ):
        raise ValueError("Parquet schema exceeds the configured nesting depth")
    uncompressed_bytes = sum(
        metadata.row_group(group).total_byte_size
        for group in range(metadata.num_row_groups)
    )
    if uncompressed_bytes > max_uncompressed_bytes:
        raise ValueError("Parquet source exceeds the uncompressed byte limit")
    try:
        table = parquet.read()
    except Exception as error:
        raise ValueError("Parquet source could not be read") from error
    rows = [
        {str(key): _json_compatible(value) for key, value in row.items()}
        for row in table.to_pylist()
    ]
    fields = [(field.name, str(field.type), field.nullable) for field in schema]
    return rows, fields


def read_text_document(path: Path, *, max_chars: int) -> tuple[DocumentSourceType, str]:
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError as error:
        raise ValueError("text document must be UTF-8") from error
    if path.suffix.lower() in {".html", ".htm"}:
        parser = _SafeTextExtractor()
        try:
            parser.feed(text)
            parser.close()
        except Exception as error:
            raise ValueError("HTML document is invalid") from error
        text = "\n".join(
            line.strip() for line in "".join(parser.parts).splitlines() if line.strip()
        )
        source_type = "html"
    elif path.suffix.lower() in {".md", ".markdown"}:
        source_type = "markdown"
    else:
        source_type = "text"
    if len(text) > max_chars:
        raise ValueError("document exceeds the configured extracted character limit")
    if not text.strip():
        raise ValueError("document contains no readable text")
    return source_type, text


def read_pdf_rows(path: Path, *, max_chars: int) -> list[dict[str, object]]:
    """Extract PDF text while enforcing the configured post-decompression budget."""
    try:
        import pypdfium2 as pdfium
    except ImportError as error:
        raise ValueError(
            "PDF adapter requires the server-side pypdfium2 dependency"
        ) from error
    try:
        document = pdfium.PdfDocument(path)
    except Exception as error:
        raise ValueError("PDF source is invalid") from error
    rows: list[dict[str, object]] = []
    extracted_chars = 0
    try:
        for page_number, page in enumerate(document, 1):
            text_page = page.get_textpage()
            try:
                text = text_page.get_text_bounded()
                extracted_chars += len(text)
                if extracted_chars > max_chars:
                    raise ValueError(
                        "document exceeds the configured extracted character limit"
                    )
                rows.extend(
                    {
                        "page": page_number,
                        "text": line.strip(),
                    }
                    for line in text.splitlines()
                    if line.strip()
                )
            finally:
                text_page.close()
                page.close()
    finally:
        document.close()
    if not rows:
        raise ValueError("PDF contains no extractable text")
    return rows


def _json_depth(value: object, depth: int = 0) -> int:
    if isinstance(value, dict):
        return max(
            (_json_depth(item, depth + 1) for item in value.values()),
            default=depth,
        )
    if isinstance(value, list):
        return max(
            (_json_depth(item, depth + 1) for item in value),
            default=depth,
        )
    return depth


def _arrow_type_depth(data_type: object, depth: int = 1) -> int:
    import pyarrow as pa

    if pa.types.is_struct(data_type):
        children = [field.type for field in cast(Iterable[_ArrowField], data_type)]
    elif pa.types.is_list(data_type) or pa.types.is_large_list(data_type):
        children = [cast(_ArrowListType, data_type).value_type]
    elif pa.types.is_map(data_type):
        map_type = cast(_ArrowMapType, data_type)
        children = [
            map_type.key_type,
            map_type.item_type,
        ]
    else:
        children = []
    return max(
        (_arrow_type_depth(child, depth + 1) for child in children),
        default=depth,
    )


def _json_compatible(value: object) -> object:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, bytes):
        return value.hex()
    if isinstance(value, dict):
        return {str(key): _json_compatible(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_compatible(item) for item in value]
    isoformat = getattr(value, "isoformat", None)
    if callable(isoformat):
        return isoformat()
    return str(value)


class _SafeTextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._ignored_depth = 0
        self.parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        del attrs
        if tag.casefold() in {"script", "style", "template", "noscript"}:
            self._ignored_depth += 1
        elif self._ignored_depth == 0 and tag.casefold() in {
            "br",
            "p",
            "div",
            "li",
            "h1",
            "h2",
            "h3",
            "h4",
            "h5",
            "h6",
        }:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag.casefold() in {"script", "style", "template", "noscript"}:
            self._ignored_depth = max(self._ignored_depth - 1, 0)
        elif self._ignored_depth == 0 and tag.casefold() in {
            "p",
            "div",
            "li",
            "h1",
            "h2",
            "h3",
            "h4",
            "h5",
            "h6",
        }:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if self._ignored_depth == 0:
            self.parts.append(data)


# Compatibility aliases retained for existing internal imports.
_bounded_integer = bounded_integer
_infer_mapping_fields = infer_mapping_fields
_read_json_rows = read_json_rows
_read_parquet = read_parquet
_read_pdf_rows = read_pdf_rows
_read_text_document = read_text_document
