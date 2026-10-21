-- 03_lab_first24h.sql
-- 从原始检验表（相当于国内医院的 LIS）提取首日检验指标
-- 时间窗口：入 ICU 前 6 小时 ～ 入 ICU 后 24 小时（labresultoffset 单位为分钟，以入 ICU 时刻为 0）
-- 步骤：窗口过滤 → 合理范围清洗 → 按患者聚合（最大值 / 最小值 / 首次值）

CREATE OR REPLACE TABLE lab_clean AS
WITH lab_window AS (
    SELECT
        patientunitstayid,
        labresultoffset,
        labname,
        labresult
    FROM lab
    WHERE labresultoffset BETWEEN -6 * 60 AND 24 * 60
      AND labresult IS NOT NULL
      AND labname IN ('lactate', 'platelets x 1000', 'bicarbonate', 'potassium',
                      'Hgb', 'PT - INR', 'creatinine', 'BUN', 'WBC x 1000')
)
-- 剔除生理上不可能的值（录入错误、单位错误等），范围参考临床常识
SELECT *
FROM lab_window
WHERE (labname = 'lactate'          AND labresult BETWEEN 0.1 AND 30)
   OR (labname = 'platelets x 1000' AND labresult BETWEEN 1 AND 2000)
   OR (labname = 'bicarbonate'      AND labresult BETWEEN 2 AND 60)
   OR (labname = 'potassium'        AND labresult BETWEEN 1 AND 10)
   OR (labname = 'Hgb'              AND labresult BETWEEN 2 AND 25)
   OR (labname = 'PT - INR'         AND labresult BETWEEN 0.5 AND 20)
   OR (labname = 'creatinine'       AND labresult BETWEEN 0.1 AND 25)
   OR (labname = 'BUN'              AND labresult BETWEEN 1 AND 300)
   OR (labname = 'WBC x 1000'       AND labresult BETWEEN 0.1 AND 200);

CREATE OR REPLACE TABLE lab_features AS
WITH first_lactate AS (
    -- 首次乳酸：按检验时间排序取第一条
    SELECT patientunitstayid, labresult AS lactate_first
    FROM (
        SELECT
            patientunitstayid,
            labresult,
            ROW_NUMBER() OVER (PARTITION BY patientunitstayid ORDER BY labresultoffset) AS rn
        FROM lab_clean
        WHERE labname = 'lactate'
    )
    WHERE rn = 1
)
SELECT
    l.patientunitstayid,
    MAX(CASE WHEN labname = 'lactate'          THEN labresult END) AS lactate_max,
    MIN(CASE WHEN labname = 'platelets x 1000' THEN labresult END) AS platelets_min,
    MIN(CASE WHEN labname = 'bicarbonate'      THEN labresult END) AS bicarbonate_min,
    MAX(CASE WHEN labname = 'potassium'        THEN labresult END) AS potassium_max,
    MIN(CASE WHEN labname = 'Hgb'              THEN labresult END) AS hemoglobin_min,
    MAX(CASE WHEN labname = 'PT - INR'         THEN labresult END) AS inr_max,
    MAX(CASE WHEN labname = 'creatinine'       THEN labresult END) AS creatinine_max_lab,
    MAX(CASE WHEN labname = 'BUN'              THEN labresult END) AS bun_max_lab,
    MAX(CASE WHEN labname = 'WBC x 1000'       THEN labresult END) AS wbc_max_lab,
    ANY_VALUE(f.lactate_first)                                     AS lactate_first
FROM lab_clean l
LEFT JOIN first_lactate f USING (patientunitstayid)
GROUP BY l.patientunitstayid;
