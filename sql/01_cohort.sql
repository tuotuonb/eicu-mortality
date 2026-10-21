-- 01_cohort.sql
-- 研究队列：逐步应用纳入排除标准，记录每一步的剩余例数（用于绘制患者筛选流程图）
-- 研究单位：每位患者首次住院中的首次 ICU 入住
-- 结局：院内死亡（hospitaldischargestatus = 'Expired'）

-- 1. 基础表：整理年龄、ICU 停留时长，并给每位患者的住院 / ICU 入住编号
CREATE OR REPLACE TABLE stay_base AS
SELECT
    p.patientunitstayid,
    p.uniquepid,
    p.patienthealthsystemstayid,
    p.hospitalid,
    h.region,
    p.gender,
    -- eICU 把 90 岁及以上统一记为 '> 89'（去标识化处理）
    CASE WHEN p.age = '> 89' THEN 90 ELSE TRY_CAST(p.age AS INTEGER) END AS age,
    p.ethnicity,
    p.unittype,
    p.unitadmitsource,
    p.admissionheight,
    p.admissionweight,
    p.unitdischargeoffset / 60.0 AS icu_los_hours,
    p.hospitaldischargestatus,
    -- 同一患者可能多次住院、多次入 ICU：按出院年份、住院 ID、ICU 入住序号排序编号
    ROW_NUMBER() OVER (
        PARTITION BY p.uniquepid
        ORDER BY p.hospitaldischargeyear, p.patienthealthsystemstayid, p.unitvisitnumber
    ) AS stay_seq
FROM patient p
LEFT JOIN hospital h USING (hospitalid);

-- 2. 给每条记录打上各项纳入标准的标记
CREATE OR REPLACE TABLE stay_flags AS
SELECT
    b.*,
    b.stay_seq = 1                                              AS f_first_stay,
    COALESCE(b.age >= 18, FALSE)                                AS f_adult,
    -- 参照 APACHE IV：ICU 停留不足 4 小时的不纳入
    COALESCE(b.icu_los_hours >= 4, FALSE)                       AS f_los,
    COALESCE(b.hospitaldischargestatus IN ('Alive', 'Expired'), FALSE) AS f_outcome,
    b.patientunitstayid IN (SELECT patientunitstayid FROM apacheapsvar) AS f_aps
FROM stay_base b;

-- 3. 筛选流程：每一步的剩余例数和死亡例数
CREATE OR REPLACE TABLE cohort_steps AS
WITH steps AS (
    SELECT 0 AS step, '全部 ICU 入住记录' AS description, TRUE AS keep, * FROM stay_flags
    UNION ALL
    SELECT 1, '保留每位患者首次住院的首次 ICU 入住', f_first_stay, * FROM stay_flags
    UNION ALL
    SELECT 2, '排除年龄 < 18 岁或年龄缺失', f_first_stay AND f_adult, * FROM stay_flags
    UNION ALL
    SELECT 3, '排除 ICU 停留不足 4 小时', f_first_stay AND f_adult AND f_los, * FROM stay_flags
    UNION ALL
    SELECT 4, '排除出院结局缺失', f_first_stay AND f_adult AND f_los AND f_outcome, * FROM stay_flags
    UNION ALL
    SELECT 5, '排除缺少 APACHE 首日生理数据', f_first_stay AND f_adult AND f_los AND f_outcome AND f_aps, * FROM stay_flags
)
SELECT
    step,
    description,
    COUNT(*)                                                     AS n,
    COUNT(*) FILTER (WHERE hospitaldischargestatus = 'Expired')  AS deaths
FROM steps
WHERE keep
GROUP BY step, description
ORDER BY step;

-- 4. 最终队列
CREATE OR REPLACE TABLE cohort AS
SELECT
    patientunitstayid,
    uniquepid,
    hospitalid,
    region,
    gender,
    age,
    ethnicity,
    unittype,
    unitadmitsource,
    admissionheight,
    admissionweight,
    icu_los_hours,
    CAST(hospitaldischargestatus = 'Expired' AS INTEGER) AS death_hosp
FROM stay_flags
WHERE f_first_stay AND f_adult AND f_los AND f_outcome AND f_aps;
