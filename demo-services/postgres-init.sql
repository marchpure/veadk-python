CREATE TABLE stores (
  store_id TEXT PRIMARY KEY,
  store_name TEXT NOT NULL,
  city TEXT NOT NULL
);
CREATE TABLE orders (
  order_id TEXT PRIMARY KEY,
  store_id TEXT NOT NULL REFERENCES stores(store_id),
  order_date DATE NOT NULL,
  amount_cents INTEGER NOT NULL,
  status TEXT NOT NULL
);
INSERT INTO stores VALUES ('store-sh', '安踏上海旗舰店', '上海'), ('store-hz', '安踏杭州湖滨店', '杭州');
INSERT INTO orders VALUES
  ('order-1001', 'store-sh', '2026-08-28', 42000, 'paid'),
  ('order-1002', 'store-sh', '2026-08-28', 31800, 'paid'),
  ('order-1003', 'store-hz', '2026-08-28', 25600, 'refunded');
