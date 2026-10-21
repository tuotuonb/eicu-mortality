-- 04_analysis_dataset.sql
-- 合并队列、APACHE 首日变量和检验指标，生成分析用宽表（一行一位患者）
-- 并按医院所在地区划分建模组和外部验证组（地理外部验证）

CREATE OR REPLACE TABLE analysis_dataset AS
SELECT
    c.patientunitstayid,
    c.hospitalid,
    c.region,
    -- 中西部、南部（以及地区未知）的医院用于建模，西部和东北部的医院用于外部验证
    CASE WHEN c.region IN ('West', 'Northeast') THEN 'validation' ELSE 'development' END AS cohort_split,

    c.death_hosp,

    -- 人口学与入科信息
    c.age,
    CASE c.gender WHEN 'Male' THEN 1 WHEN 'Female' THEN 0 END AS male,
    c.ethnicity,
    c.unittype,
    CASE
        WHEN c.unitadmitsource = 'Emergency Department'              THEN 'ED'
        WHEN c.unitadmitsource IN ('Operating Room', 'Recovery Room',
                                   'PACU')                          THEN 'OR'
        WHEN c.unitadmitsource IN ('Floor', 'Acute Care/Floor',
                                   'Step-Down Unit (SDU)')          THEN 'Ward'
        ELSE 'Other'
    END AS admit_source,
    -- BMI：身高单位 cm，体重单位 kg，剔除明显异常的身高体重
    CASE
        WHEN c.admissionheight BETWEEN 120 AND 220 AND c.admissionweight BETWEEN 25 AND 300
        THEN ROUND(c.admissionweight / POWER(c.admissionheight / 100.0, 2), 1)
    END AS bmi,
    c.icu_los_hours,

    -- APACHE 首日变量
    a.heart_rate, a.mean_bp, a.resp_rate, a.temperature, a.gcs,
    a.wbc, a.sodium, a.creatinine, a.bun, a.glucose, a.hematocrit,
    a.albumin, a.bilirubin, a.urine_24h, a.ph, a.pao2, a.fio2,
    a.mech_vent, a.dialysis,
    a.elective_surgery, a.diabetes, a.cirrhosis, a.immunosuppression,
    a.metastatic_cancer, a.hepatic_failure, a.hematologic_cancer,
    a.apache_score, a.apache_iva_pred,

    -- 原始检验表提取的首日指标
    l.lactate_max, l.lactate_first, l.platelets_min, l.bicarbonate_min,
    l.potassium_max, l.hemoglobin_min, l.inr_max,
    l.creatinine_max_lab, l.bun_max_lab, l.wbc_max_lab
FROM cohort c
LEFT JOIN apache_features a USING (patientunitstayid)
LEFT JOIN lab_features l USING (patientunitstayid)
ORDER BY c.patientunitstayid;
