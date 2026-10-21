-- 运营商政企业务 NL2SQL 样例库（完全虚构，seed=20261020）
-- 设计原则：可复现、含确定性埋点、支持 6 类题型（单表/两表/三表/聚合/时间窗口/否定空值）

CREATE TABLE dim_customer (
    customer_id    TEXT PRIMARY KEY,   -- 客户ID
    customer_name  TEXT NOT NULL,      -- 客户名称
    industry       TEXT,               -- 行业
    city           TEXT,               -- 地市（埋点：存在"杭州"/"杭州市"不一致）
    customer_level TEXT,               -- 客户等级 A/B/C（埋点：存在空值）
    sign_date      TEXT,               -- 签约日期 YYYY-MM-DD
    status         TEXT                -- 状态：正常/停用
);

CREATE TABLE dim_product (
    product_id      TEXT PRIMARY KEY,  -- 产品ID
    product_name    TEXT NOT NULL,     -- 产品名称（埋点：同名不同规格）
    product_type    TEXT NOT NULL,     -- 类型：专线/云/IDC
    bandwidth_mbps  INTEGER,           -- 带宽(Mbps)
    standard_price  REAL,              -- 标准月费(元)
    status          TEXT               -- 在售/下架
);

CREATE TABLE dim_employee (
    emp_id   TEXT PRIMARY KEY,         -- 员工ID
    emp_name TEXT NOT NULL,            -- 姓名
    team     TEXT,                     -- 班组/部门
    role     TEXT,                     -- 客户经理/维护班组/客服
    city     TEXT                      -- 地市
);

CREATE TABLE fact_order (
    order_id        TEXT PRIMARY KEY,  -- 订单号
    customer_id     TEXT NOT NULL,     -- 客户ID
    product_id      TEXT NOT NULL,     -- 产品ID
    order_date      TEXT NOT NULL,     -- 下单日期（埋点：2 条未来日期）
    effective_date  TEXT,              -- 生效日期
    cancel_date     TEXT,              -- 退订日期（NULL=在网）
    monthly_fee     REAL NOT NULL,     -- 月费(元)
    discount_rate   REAL NOT NULL,     -- 折扣率 0.70~1.00
    sales_emp_id    TEXT,              -- 销售员工ID
    status          TEXT               -- 在网/已退订/待生效
);

CREATE TABLE fact_ticket (
    ticket_id          TEXT PRIMARY KEY, -- 工单号
    customer_id        TEXT NOT NULL,
    product_id         TEXT,
    ticket_type        TEXT NOT NULL,    -- 故障/投诉/开通
    urgency            TEXT,             -- 高/中/低
    created_at         TEXT NOT NULL,    -- 创建时间 YYYY-MM-DD HH:MM:SS
    first_response_at  TEXT,             -- 首次响应（埋点：存在空值）
    resolved_at        TEXT,             -- 解决时间（埋点：存在空值）
    sla_flag           TEXT,             -- SLA 标记 Y/N（埋点：与时间不一致）
    handle_team        TEXT              -- 处理班组
);

CREATE TABLE fact_bill (
    bill_month    TEXT NOT NULL,      -- 账期 YYYY-MM
    customer_id   TEXT NOT NULL,
    product_id    TEXT NOT NULL,
    amount_due    REAL NOT NULL,      -- 应收（埋点：少量与月费×折扣不符）
    amount_paid   REAL NOT NULL,      -- 实收
    arrears       REAL NOT NULL,      -- 欠费
    adjustment    REAL NOT NULL,      -- 调整金额（埋点：存在负值）
    order_id      TEXT NOT NULL,      -- 关联订单（对账口径必须能落到订单）
    PRIMARY KEY (bill_month, order_id)
);

CREATE INDEX idx_order_customer ON fact_order(customer_id);
CREATE INDEX idx_order_product  ON fact_order(product_id);
CREATE INDEX idx_order_date     ON fact_order(order_date);
CREATE INDEX idx_ticket_customer ON fact_ticket(customer_id);
CREATE INDEX idx_ticket_created  ON fact_ticket(created_at);
CREATE INDEX idx_bill_month      ON fact_bill(bill_month);
