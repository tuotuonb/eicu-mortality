-- 02_apache_features.sql
-- 从 APACHE 相关表提取入 ICU 首日变量
--   apacheapsvar：首日生理指标的"最差值"（APACHE 定义），缺失记为 -1
--   apachepredvar：合并症、是否择期手术等
--   apachepatientresult：APACHE IVa 预测的院内死亡概率（用于和本研究模型对比）

CREATE OR REPLACE TABLE apache_features AS
SELECT
    a.patientunitstayid,

    -- 生命体征（首日最差值）
    NULLIF(a.heartrate, -1)        AS heart_rate,
    NULLIF(a.meanbp, -1)           AS mean_bp,
    NULLIF(a.respiratoryrate, -1)  AS resp_rate,
    -- 体温 < 30 ℃ 或 > 43 ℃ 视为录入错误（数据中出现过 22.2 ℃），按缺失处理
    CASE WHEN a.temperature BETWEEN 30 AND 43 THEN a.temperature END AS temperature,

    -- GCS 总分：使用镇静 / 肌松药物时无法评估（meds = 1），任一分项缺失也视为缺失
    CASE
        WHEN a.meds = 0 AND a.eyes > 0 AND a.motor > 0 AND a.verbal > 0
        THEN a.eyes + a.motor + a.verbal
    END                            AS gcs,

    -- 实验室指标（首日最差值）
    NULLIF(a.wbc, -1)              AS wbc,
    NULLIF(a.sodium, -1)           AS sodium,
    NULLIF(a.creatinine, -1)       AS creatinine,
    NULLIF(a.bun, -1)              AS bun,
    NULLIF(a.glucose, -1)          AS glucose,
    NULLIF(a.hematocrit, -1)       AS hematocrit,
    NULLIF(a.albumin, -1)          AS albumin,
    NULLIF(a.bilirubin, -1)        AS bilirubin,
    NULLIF(a.urine, -1)            AS urine_24h,
    NULLIF(a.ph, -1)               AS ph,
    NULLIF(a.pao2, -1)             AS pao2,
    NULLIF(a.fio2, -1)             AS fio2,

    -- 首日机械通气 / 透析
    GREATEST(a.vent, a.intubated)  AS mech_vent,
    a.dialysis                     AS dialysis,

    -- 合并症与入院类型
    -- 只有手术患者才记录是否择期，非手术患者为空，视为"否"
    COALESCE(pv.electivesurgery, 0) AS elective_surgery,
    pv.diabetes                    AS diabetes,
    pv.cirrhosis                   AS cirrhosis,
    pv.immunosuppression           AS immunosuppression,
    pv.metastaticcancer            AS metastatic_cancer,
    pv.hepaticfailure              AS hepatic_failure,
    GREATEST(pv.lymphoma, pv.leukemia) AS hematologic_cancer,

    -- APACHE IVa 预测的院内死亡概率；-1 表示未计算
    CASE WHEN r.predictedhospitalmortality >= 0
         THEN r.predictedhospitalmortality END AS apache_iva_pred,
    NULLIF(r.apachescore, -1)      AS apache_score
FROM apacheapsvar a
LEFT JOIN apachepredvar pv USING (patientunitstayid)
LEFT JOIN apachepatientresult r
       ON r.patientunitstayid = a.patientunitstayid
      AND r.apacheversion = 'IVa';
