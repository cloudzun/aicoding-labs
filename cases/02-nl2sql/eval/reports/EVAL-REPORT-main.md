# EX 评测报告 · main

> 生成时间：2026-10-21T12:13:53+08:00　题数：150　判定：**EX 全自动（零 judge）**
> 比对规则见 [docs/00-数据与口径.md](../../docs/00-数据与口径.md) §5.2。

## 一、门禁

**FAIL —— AC-01 EX（主集）、AC-04 JOIN 桶 EX、AC-08 延迟 p50**

| 指标 | 阈值 | 实测 | 判定 |
|---|---|---|---|
| AC-01 EX（主集） | ≥85% | 83.33% | FAIL |
| AC-02 可执行率 | ≥95% | 100.00% | PASS |
| AC-03 单表桶 EX | ≥90% | 90.00% | PASS |
| AC-04 JOIN 桶 EX | ≥80% | 68.00% | FAIL |
| AC-05 聚合桶 EX | ≥80% | 86.67% | PASS |
| AC-05 时间桶 EX | ≥80% | 100.00% | PASS |
| AC-05 空值桶 EX | ≥80% | 93.33% | PASS |
| 反问率（主集，应接近 0） | ≤5% | 0.00% | PASS |
| AC-08 延迟 p50 | ≤2000ms | 2019.0 | FAIL |
| AC-08 延迟 p95 | ≤4000ms | 2950.0 | PASS |

- 通过 **125/150**　可执行率 **100.00%**　平均尝试 **1.0** 次
- 延迟 p50/p95：**2019.0 / 2950.0 ms**（AC-08 阈值 2000/4000）

## 二、分桶

| 分桶 | n | EX 命中 | 一致率 |
|---|---|---|---|
| aggregate | 30 | 26 | 86.67% |
| negation_null | 15 | 14 | 93.33% |
| single_hop | 40 | 36 | 90.00% |
| three_join | 20 | 15 | 75.00% |
| time_window | 15 | 15 | 100.00% |
| two_join | 30 | 19 | 63.33% |

## 三、失败样本（前 40）

- `si-006` [single_hop] 行数不同（gold 15 / out 20）
  - out: `SELECT * FROM (
SELECT emp_name, team
FROM dim_employee
WHERE role = '客户经理'
ORDER BY emp_name
) LIMIT 1001`
  - gold: `[["员工001", "宁波政企一部"], ["员工002", "温州政企一部"], ["员工003", "金华政企一部"]]` / out: `[["员工001", "宁波政企一部"], ["员工002", "温州政企一部"], ["员工003", "金华政企一部"]]`
- `tw-001` [two_join] 顺序或内容不一致
  - out: `SELECT * FROM (
SELECT c.customer_name, ROUND(SUM(o.monthly_fee * o.discount_rate), 2) AS monthly_fee_total
FROM fact_order o
JOIN dim_customer c ON c.customer_id = o.customer_id
W`
  - gold: `[["C0282", 188584.75], ["C0082", 86435.52], ["C0218", 83962.42]]` / out: `[["杭州优博科教育科技股份有限公司", 188584.75], ["杭州云栖科政务科技集团", 86435.52], ["杭州澜庭电金融科技股份有限公司", 83962.42]]`
- `tw-004` [two_join] 列数不同（gold 2 / out 3）
  - out: `SELECT * FROM (
SELECT c.customer_id, c.customer_name, AVG((julianday(t.resolved_at) - julianday(t.created_at)) * 24.0) AS avg_hours
FROM fact_ticket t
JOIN dim_customer c ON c.cus`
  - gold: `[["金华优博通金融科技有限公司", 59.77], ["金华澜庭成政务科技有限公司", 57.57], ["金华澜庭源教育科技集团", 56.43]]` / out: `[["C0285", "金华优博通金融科技有限公司", 59.77], ["C0213", "金华澜庭成政务科技有限公司", 57.57], ["C0204", "金华澜庭源教育科技集团", 56.43]]`
- `th-001` [three_join] 顺序或内容不一致
  - out: `SELECT * FROM (
SELECT b.customer_id, b.product_id, SUM(b.amount_due) AS amount_due
FROM fact_bill b
WHERE b.bill_month = '2026-09'
GROUP BY b.customer_id, b.product_id
ORDER BY am`
  - gold: `[["金华瑞启信交通建设有限公司", "政企专线-1000M", 37706.42], ["宁波启元科装备制造有限公司", "政企专线-1000M", 31128.14], ["宁波启元航教育科技集团", "政企专线-1000M", 302` / out: `[["C0077", "P0020", 37706.42], ["C0162", "P0019", 31128.14], ["C0175", "P0020", 30201.28]]`
- `th-004` [three_join] 顺序或内容不一致
  - out: `SELECT * FROM (
SELECT b.customer_id, p.product_type, SUM(b.amount_paid) AS amount_paid
FROM fact_bill b
JOIN fact_order o ON o.order_id = b.order_id
JOIN dim_product p ON p.produc`
  - gold: `[["金华瑞启信交通建设有限公司", "专线", 37706.42], ["宁波启元航教育科技集团", "专线", 30201.28], ["绍兴旭诚智装备制造科技股份有限公司", "专线", 30067.72]]` / out: `[["C0077", "专线", 37706.42], ["C0175", "专线", 30201.28], ["C0240", "专线", 30067.72]]`
- `ag-005` [aggregate] 顺序或内容不一致
  - out: `SELECT * FROM (
SELECT handle_team, COUNT(*) AS ticket_count
FROM fact_ticket
WHERE sla_flag = 'Y'
GROUP BY handle_team
ORDER BY ticket_count DESC
LIMIT 5
) LIMIT 1001`
  - gold: `[["宁波维护班组组", 20], ["温州维护班组组", 15], ["绍兴维护班组组", 9]]` / out: `[["宁波维护班组组", 33], ["温州维护班组组", 29], ["绍兴维护班组组", 17]]`
- `ag-008` [aggregate] 顺序或内容不一致
  - out: `SELECT * FROM (
SELECT product_name, COUNT(*) AS product_count
FROM dim_product
GROUP BY product_name
HAVING COUNT(*) > 1
ORDER BY product_count DESC, product_name
LIMIT 10
) LIMIT`
  - gold: `[["政企云-高级版", 3], ["政企云-标准版", 3], ["政企云-基础版", 3]]` / out: `[["政企专线-1000M", 3], ["政企专线-100M", 3], ["政企专线-10M", 3]]`
- `ne-006` [negation_null] 行数不同（gold 6 / out 66）
  - out: `SELECT * FROM (
SELECT DISTINCT o.order_id, b.bill_month
FROM fact_order o
JOIN fact_bill b ON b.order_id = o.order_id
WHERE o.cancel_date IS NOT NULL
ORDER BY o.order_id, b.bill_m`
  - gold: `[["SO0000002", "2025-06"], ["SO0000079", "2025-07"], ["SO0000781", "2025-12"]]` / out: `[["SO0000002", "2025-03"], ["SO0000002", "2025-06"], ["SO0000054", "2026-06"]]`
- `si-015` [single_hop] 行数不同（gold 4 / out 20）
  - out: `SELECT * FROM (
SELECT DISTINCT e.emp_name, e.city
FROM dim_employee e
JOIN fact_order o ON o.sales_emp_id = e.emp_id
JOIN dim_customer c ON c.customer_id = o.customer_id
WHERE e.r`
  - gold: `[["员工005", "杭州"], ["员工010", "杭州"], ["员工015", "杭州"]]` / out: `[["员工001", "宁波"], ["员工014", "绍兴"], ["员工010", "杭州"]]`
- `tw-010` [two_join] 列数不同（gold 2 / out 1）
  - out: `SELECT * FROM (
SELECT ROUND(SUM(o.monthly_fee * o.discount_rate), 2) AS fee
FROM fact_order o
JOIN dim_customer c ON c.customer_id = o.customer_id
WHERE c.industry = '制造'
  AND o.`
  - gold: `[["制造", 1674124.28]]` / out: `[[1674124.28]]`
- `tw-012` [two_join] 列数不同（gold 1 / out 2）
  - out: `SELECT * FROM (
SELECT c.city, COUNT(*) AS order_count
FROM fact_order o
JOIN dim_customer c ON c.customer_id = o.customer_id
WHERE c.city LIKE '杭州%'
  AND o.cancel_date IS NOT NUL`
  - gold: `[[30]]` / out: `[["杭州", 30]]`
- `ag-013` [aggregate] 行数不同（gold 2 / out 67）
  - out: `SELECT * FROM (
SELECT adjustment, COUNT(*) AS bill_count FROM fact_bill GROUP BY adjustment
) LIMIT 1001`
  - gold: `[["无调整", 1139], ["负调整", 66]]` / out: `[[-293.93, 1], [-277.18, 1], [-273.9, 1]]`
- `ag-023` [aggregate] 行数不同（gold 4 / out 31）
  - out: `SELECT * FROM (
SELECT discount_rate, COUNT(*) AS order_count
FROM fact_order
GROUP BY discount_rate
ORDER BY discount_rate
) LIMIT 1001`
  - gold: `[[1.0, 335], [0.9, 642], [0.8, 720]]` / out: `[[0.7, 30], [0.71, 72], [0.72, 80]]`
- `si-017` [single_hop] 值不同（97 vs 95）
  - out: `SELECT * FROM (
SELECT COUNT(DISTINCT customer_id) AS cnt FROM dim_customer WHERE customer_level = 'B' AND status = '正常'
) LIMIT 1001`
  - gold: `[[97]]` / out: `[[95]]`
- `tw-015` [two_join] 行数不同（gold 3 / out 9）
  - out: `SELECT * FROM (
SELECT p.product_name, COUNT(o.order_id) AS order_count
FROM fact_order o
JOIN dim_product p ON p.product_id = o.product_id
WHERE p.product_type = '云'
GROUP BY p.pr`
  - gold: `[["政企云-高级版", 172], ["政企云-基础版", 171], ["政企云-标准版", 166]]` / out: `[["政企云-标准版", 66], ["政企云-基础版", 64], ["政企云-高级版", 60]]`
- `th-008` [three_join] 列数不同（gold 3 / out 5）
  - out: `SELECT * FROM (
SELECT b.customer_id, c.customer_name, b.product_id, p.product_name, SUM(b.amount_due) AS amount_due
FROM fact_bill b
JOIN dim_customer c ON c.customer_id = b.custo`
  - gold: `[["杭州优博正能源科技股份有限公司", "政企专线-1000M", 34147.54], ["金华远信光交通建设股份有限公司", "政企专线-1000M", 29039.72], ["杭州泓泰成交通建设有限公司", "政企专线-1000M` / out: `[["C0286", "杭州优博正能源科技股份有限公司", "P0020", "政企专线-1000M", 34147.54], ["C0007", "金华远信光交通建设股份有限公司", "P0020", "政企专线-1000M", 2903`
- `th-011` [three_join] 列数不同（gold 3 / out 4）
  - out: `SELECT * FROM (
SELECT c.customer_id, c.customer_name, p.product_type, SUM(b.amount_paid) AS amount_paid
FROM fact_bill b
JOIN fact_order o ON b.order_id = o.order_id
JOIN dim_cust`
  - gold: `[["金华远信光交通建设股份有限公司", "专线", 29039.72], ["杭州泓泰成交通建设有限公司", "专线", 28764.47], ["杭州优博正能源科技股份有限公司", "专线", 24296.96]]` / out: `[["C0007", "金华远信光交通建设股份有限公司", "专线", 29039.72], ["C0053", "杭州泓泰成交通建设有限公司", "专线", 28764.47], ["C0286", "杭州优博正能源科技股份有限公司", `
- `si-028` [single_hop] 行数不同（gold 4 / out 20）
  - out: `SELECT * FROM (
SELECT DISTINCT e.emp_name, e.city FROM dim_employee e JOIN fact_order o ON o.sales_emp_id = e.emp_id JOIN dim_customer c ON c.customer_id = o.customer_id WHERE e.r`
  - gold: `[["员工001", "宁波"], ["员工006", "宁波"], ["员工011", "宁波"]]` / out: `[["员工010", "杭州"], ["员工009", "绍兴"], ["员工007", "温州"]]`
- `tw-018` [two_join] 列数不同（gold 2 / out 1）
  - out: `SELECT * FROM (
SELECT ROUND(SUM(o.monthly_fee * o.discount_rate), 2) AS fee
FROM fact_order o
JOIN dim_customer c ON c.customer_id = o.customer_id
WHERE c.industry = '金融'
  AND o.`
  - gold: `[["金融", 1688080.07]]` / out: `[[1688080.07]]`
- `tw-019` [two_join] 列数不同（gold 2 / out 1）
  - out: `SELECT * FROM (
SELECT COUNT(*) AS ticket_count FROM fact_ticket t JOIN dim_product p ON p.product_id = t.product_id WHERE p.product_type = '云' AND t.urgency = '高'
) LIMIT 1001`
  - gold: `[["云", 244]]` / out: `[[244]]`
- `tw-023` [two_join] 行数不同（gold 3 / out 6）
  - out: `SELECT * FROM (
SELECT p.product_name, COUNT(o.order_id) AS order_count
FROM dim_product p
LEFT JOIN fact_order o ON o.product_id = p.product_id
WHERE p.product_type = 'IDC'
GROUP `
  - gold: `[["IDC-机柜A", 122], ["IDC-机柜B", 105], ["IDC-整柜", 102]]` / out: `[["IDC-机柜A", 62], ["IDC-机柜A", 60], ["IDC-机柜B", 55]]`
- `th-016` [three_join] 列数不同（gold 2 / out 3）
  - out: `SELECT * FROM (
SELECT c.city, b.bill_month, ROUND(SUM(b.arrears), 2) AS arrears FROM fact_bill b JOIN dim_customer c ON c.customer_id = b.customer_id WHERE b.bill_month BETWEEN '2`
  - gold: `[["杭州", 39922.05], ["金华市", 36236.59], ["宁波", 33616.18]]` / out: `[["宁波", "2026-06", 3154.62], ["宁波市", "2026-06", 0.0], ["杭州", "2026-06", 9320.92]]`
- `tw-025` [two_join] 列数不同（gold 2 / out 1）
  - out: `SELECT * FROM (
SELECT ROUND(SUM(o.monthly_fee * o.discount_rate), 2) AS fee
FROM fact_order o
JOIN dim_customer c ON c.customer_id = o.customer_id
WHERE c.industry = '政府'
  AND o.`
  - gold: `[["政府", 1838083.28]]` / out: `[[1838083.28]]`
- `tw-026` [two_join] 列数不同（gold 2 / out 1）
  - out: `SELECT * FROM (
SELECT COUNT(*) AS ticket_count
FROM fact_ticket t
JOIN dim_product p ON p.product_id = t.product_id
WHERE p.product_type = 'IDC'
  AND t.urgency = '高'
) LIMIT 1001`
  - gold: `[["IDC", 173]]` / out: `[[173]]`
- `tw-029` [two_join] 列数不同（gold 2 / out 1）
  - out: `SELECT * FROM (
SELECT ROUND(SUM(o.monthly_fee * o.discount_rate), 2) AS fee
FROM fact_order o
JOIN dim_customer c ON c.customer_id = o.customer_id
WHERE c.industry = '医疗'
  AND o.`
  - gold: `[["医疗", 2117376.19]]` / out: `[[2117376.19]]`

## 四、诚实边界

- 主集问句由 LLM 从 gold SQL 反写，**与 SQL 结构同源**，真实自由提问会更难；锚点集用于校准这一偏差。
- 延迟为单机单并发采样，受网关排队影响。
- 未达标项一律保留 FAIL，未下调阈值。
