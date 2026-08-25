"""Create deterministic local source fixtures for browser certification."""

from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
from openpyxl import Workbook


def _write_pdf(path: Path) -> None:
    text = "Browser certified PDF source"
    stream = f"BT\n/F1 12 Tf\n72 760 Td\n({text}) Tj\nET\n".encode("ascii")
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        (
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
            b"/Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>"
        ),
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        b"<< /Length "
        + str(len(stream)).encode("ascii")
        + b" >>\nstream\n"
        + stream
        + b"endstream",
    ]
    body = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for index, value in enumerate(objects, 1):
        offsets.append(len(body))
        body.extend(f"{index} 0 obj\n".encode())
        body.extend(value)
        body.extend(b"\nendobj\n")
    xref = len(body)
    body.extend(f"xref\n0 {len(objects) + 1}\n".encode())
    body.extend(b"0000000000 65535 f \n")
    for offset in offsets[1:]:
        body.extend(f"{offset:010d} 00000 n \n".encode())
    body.extend(
        (
            f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\n"
            f"startxref\n{xref}\n%%EOF\n"
        ).encode()
    )
    path.write_bytes(body)


def main() -> None:
    root = Path(sys.argv[1]).resolve()
    root.mkdir(parents=True, exist_ok=True)
    rows = [
        {"order_id": "A-1", "amount": 12},
        {"order_id": "B-2", "amount": 5},
    ]
    (root / "orders.csv").write_text(
        "order_id,amount\nA-1,12\nB-2,5\n",
        encoding="utf-8",
    )
    (root / "orders.json").write_text(
        json.dumps(rows, ensure_ascii=False),
        encoding="utf-8",
    )
    (root / "event.schema.json").write_text(
        json.dumps(
            {
                "type": "object",
                "required": ["sku", "stock"],
                "properties": {
                    "sku": {"type": "string"},
                    "stock": {"type": "integer"},
                },
                "additionalProperties": False,
            }
        ),
        encoding="utf-8",
    )
    (root / "notes.md").write_text("# Browser certification\n\nPinned revision.\n")
    (root / "notes.txt").write_text("Browser certification text.\n")
    (root / "notes.html").write_text(
        "<html><body><h1>Browser certification</h1><p>Safe HTML.</p></body></html>"
    )
    _write_pdf(root / "notes.pdf")
    workbook = Workbook()
    sheet = workbook.active
    assert sheet is not None
    sheet.title = "Orders"
    sheet.append(["order_id", "amount"])
    sheet.append(["A-1", 12])
    sheet.append(["B-2", 5])
    workbook.save(root / "orders.xlsx")
    pq.write_table(pa.Table.from_pylist(rows), root / "orders.parquet")
    connection = sqlite3.connect(root / "orders.sqlite")
    try:
        connection.execute(
            "CREATE TABLE orders (order_id TEXT PRIMARY KEY, amount INTEGER NOT NULL)"
        )
        connection.executemany(
            "INSERT INTO orders(order_id, amount) VALUES (?, ?)",
            [("A-1", 12), ("B-2", 5)],
        )
        connection.commit()
    finally:
        connection.close()


if __name__ == "__main__":
    main()
