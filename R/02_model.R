# 第 5 步：预测模型的构建与验证
#   1. 多重插补：mice 5 次，建模组、验证组分别插补
#   2. 单因素 Logistic 回归（建模组观测数据）：连续变量用限制性立方样条（RCS）检验整体关联和非线性
#   3. 多因素 Logistic 回归：单因素 P < 0.05 的变量进入，非线性显著的用 RCS，再按 AIC 向后逐步回归精简；
#      5 个插补数据集分别拟合，按 Rubin 规则合并
#   4. 森林图、RCS 曲线、列线图
#   5. 内部验证：Bootstrap 1000 次，每次重抽样都重做变量筛选，校正乐观偏倚
#   6. 外部验证：验证组的 ROC、校准曲线、DCA，并与 APACHE IVa 比较（DeLong 检验）
# 用法：在项目根目录运行 Rscript R/02_model.R

source("R/utils.R")
suppressPackageStartupMessages({
  library(rms)
  library(mice)
  library(pROC)
  library(ggplot2)
  library(dcurves)
  library(ragg)
  library(jsonlite)
})
set.seed(2026)
options(warn = 1)

# ---------------------------------------------------------------- 数据与候选变量
df <- read.csv("data/processed/analysis_dataset.csv", fileEncoding = "UTF-8")
vars <- read.csv("config/variables.csv", fileEncoding = "UTF-8")
LABEL <- setNames(vars$label, vars$name)
UNIT <- setNames(ifelse(is.na(vars$unit), "", vars$unit), vars$name)

# 候选变量：入 ICU 首日可获得、缺失率 < 30%、有临床意义；检验指标优先用 SQL 从原始检验表提取的版本（缺失率更低）
CANDIDATES <- c("age", "male", "heart_rate", "mean_bp", "resp_rate", "temperature", "gcs",
                "bun_max_lab", "creatinine_max_lab", "wbc_max_lab", "hemoglobin_min",
                "platelets_min", "bicarbonate_min", "potassium_max", "glucose",
                "mech_vent", "elective_surgery", "diabetes", "immunosuppression",
                "metastatic_cancer", "cirrhosis", "hematologic_cancer")
BINARY <- intersect(CANDIDATES, vars$name[vars$type == "binary"])
CONTINUOUS <- setdiff(CANDIDATES, BINARY)

# 单因素 OR 的计算单位（每增加多少）
STEP <- c(age = 10, heart_rate = 10, mean_bp = 10, resp_rate = 5, temperature = 1, gcs = 1,
          bun_max_lab = 10, creatinine_max_lab = 1, wbc_max_lab = 5, hemoglobin_min = 1,
          platelets_min = 50, bicarbonate_min = 1, potassium_max = 1, glucose = 50)

# 多因素结果展示用的临床对比（高值 vs 参照值）；线性项只用第一组，RCS 项低端、高端都展示
CMP <- list(
  age = list(c(70, 60)), heart_rate = list(c(130, 90), c(50, 90)),
  mean_bp = list(c(50, 80), c(130, 80)), resp_rate = list(c(35, 18), c(8, 18)),
  temperature = list(c(35, 36.8), c(38.5, 36.8)), gcs = list(c(8, 15)),
  bun_max_lab = list(c(40, 15)), creatinine_max_lab = list(c(2.5, 1)),
  wbc_max_lab = list(c(20, 8), c(3, 8)), hemoglobin_min = list(c(8, 12)),
  platelets_min = list(c(80, 200)), bicarbonate_min = list(c(15, 24), c(32, 24)),
  potassium_max = list(c(5.5, 4.2)), glucose = list(c(250, 120))
)

# 列线图各连续变量的刻度（临床常见范围）
AXIS <- list(
  age = seq(20, 90, 10), heart_rate = seq(40, 180, 20), mean_bp = seq(40, 160, 20),
  resp_rate = seq(5, 55, 10), temperature = c(32, 33, 34, 35, 36, 37, 38, 39, 40),
  gcs = c(3, 5, 7, 9, 11, 13, 15), bun_max_lab = c(5, 20, 40, 60, 80, 100),
  creatinine_max_lab = c(0.5, 1, 1.5, 2, 3, 5, 8), wbc_max_lab = c(2, 5, 10, 15, 20, 30, 40),
  hemoglobin_min = seq(6, 16, 2), platelets_min = c(20, 50, 100, 200, 300, 400),
  bicarbonate_min = c(8, 12, 16, 20, 24, 28, 32, 36), potassium_max = seq(3, 7, 0.5),
  glucose = c(50, 100, 200, 300, 400)
)

# 二分类变量转成 否 / 是，列线图和结果表上直接显示中文
for (v in BINARY) df[[v]] <- factor(df[[v]], levels = c(0, 1), labels = c("否", "是"))

keep_cols <- c("patientunitstayid", "death_hosp", CANDIDATES, "apache_iva_pred")
dev <- df[df$cohort_split == "development", keep_cols]
val <- df[df$cohort_split == "validation", keep_cols]
cat(sprintf("建模组 %d 例（死亡 %d），验证组 %d 例（死亡 %d）\n",
            nrow(dev), sum(dev$death_hosp), nrow(val), sum(val$death_hosp)))

# ---------------------------------------------------------------- 1. 多重插补
impute <- function(d) {
  mice(d[, c("death_hosp", CANDIDATES)], m = 5, method = "pmm", maxit = 10,
       printFlag = FALSE, seed = 2026)
}
imp_dev <- impute(dev)
imp_val <- impute(val)
dev1 <- complete(imp_dev, 1)
# 中文标签（列线图上显示），插补之后再加，避免影响 mice
for (v in CANDIDATES) {
  lab <- if (UNIT[v] == "") LABEL[[v]] else paste0(LABEL[[v]], "（", UNIT[[v]], "）")
  label(dev[[v]]) <- lab
  label(dev1[[v]]) <- lab
}
dd <- datadist(dev1)
options(datadist = "dd")

# ---------------------------------------------------------------- 2. 单因素分析
univariate <- function(v) {
  d <- dev[complete.cases(dev[, c("death_hosp", v)]), c("death_hosp", v)]
  g <- glm(reformulate(v, "death_hosp"), family = binomial, data = d)
  step <- if (v %in% CONTINUOUS) STEP[[v]] else 1
  est <- coef(g)[2] * step
  se <- sqrt(vcov(g)[2, 2]) * step
  p <- summary(g)$coefficients[2, 4]
  p_nonlin <- NA
  if (v %in% CONTINUOUS) {
    # RCS 模型的整体检验能发现 U 型关系，线性检验会漏掉
    a <- anova(lrm(as.formula(sprintf("death_hosp ~ rcs(%s, 3)", v)), data = d))
    p <- a[1, "P"]
    p_nonlin <- a[" Nonlinear", "P"]
  }
  data.frame(
    变量 = v, 中文名 = LABEL[[v]],
    单位 = if (v %in% CONTINUOUS) sprintf("每增加 %s %s", STEP[[v]], UNIT[[v]]) else "是 vs 否",
    OR = round(exp(est), 2), CI下限 = round(exp(est - 1.96 * se), 2), CI上限 = round(exp(est + 1.96 * se), 2),
    P = p, P_非线性 = p_nonlin, 例数 = nrow(d)
  )
}
uni <- do.call(rbind, lapply(CANDIDATES, univariate))
uni_out <- transform(uni, P = fmt_p(P), P_非线性 = fmt_p(P_非线性))
write_csv_bom(uni_out, "results/tables/table2_univariate.csv")

# ---------------------------------------------------------------- 3. 多因素 Logistic 回归
selected <- uni$变量[uni$P < 0.05]
nonlinear <- uni$变量[uni$变量 %in% selected & !is.na(uni$P_非线性) & uni$P_非线性 < 0.05]
term <- function(v) if (v %in% nonlinear) sprintf("rcs(%s, 3)", v) else v
make_formula <- function(vs) as.formula(paste("death_hosp ~", paste(sapply(vs, term), collapse = " + ")))
cat("单因素 P < 0.05 的变量：", paste(selected, collapse = ", "), "\n")
cat("其中非线性显著（用 RCS）：", paste(nonlinear, collapse = ", "), "\n")

full <- lrm(make_formula(selected), data = dev1, x = TRUE, y = TRUE)
bw <- fastbw(full, rule = "aic")
final_vars <- selected[selected %in% bw$names.kept]
final_formula <- make_formula(final_vars)
cat("向后逐步回归保留：", paste(final_vars, collapse = ", "), "\n")

# 5 个插补数据集分别拟合，按 Rubin 规则合并系数和方差
fit <- fit.mult.impute(final_formula, lrm, imp_dev, data = dev, pr = FALSE,
                       fitargs = list(x = TRUE, y = TRUE))
n_params <- length(coef(fit)) - 1
cat(sprintf("最终模型 %d 个变量，%d 个参数，EPV = %.1f\n", length(final_vars), n_params,
            sum(dev$death_hosp) / n_params))

# 多因素结果：每个变量的临床对比 OR
wald <- anova(fit)
multi_rows <- list()
for (v in final_vars) {
  p_overall <- wald[v, "P"]
  if (v %in% BINARY) {
    pairs <- list(c("是", "否"))
    texts <- "是 vs 否"
  } else {
    pairs <- if (v %in% nonlinear) CMP[[v]] else CMP[[v]][1]
    texts <- sapply(pairs, function(x) {
      if (v == "age") "每增加 10 岁" else sprintf("%s vs %s %s", x[1], x[2], UNIT[[v]])
    })
  }
  for (i in seq_along(pairs)) {
    k <- contrast(fit, setNames(list(pairs[[i]][1]), v), setNames(list(pairs[[i]][2]), v))
    multi_rows[[length(multi_rows) + 1]] <- data.frame(
      变量 = v, 中文名 = LABEL[[v]], 对比 = texts[i],
      OR = exp(k$Contrast), CI下限 = exp(k$Lower), CI上限 = exp(k$Upper),
      P_对比 = k$Pvalue, P_整体 = p_overall,
      P_非线性 = if (v %in% nonlinear) wald[match(v, rownames(wald)) + 1, "P"] else NA
    )
  }
}
multi <- do.call(rbind, multi_rows)
multi_out <- transform(multi, OR = round(OR, 2), CI下限 = round(CI下限, 2), CI上限 = round(CI上限, 2),
                       P_对比 = fmt_p(P_对比), P_整体 = fmt_p(P_整体), P_非线性 = fmt_p(P_非线性))
write_csv_bom(multi_out, "results/tables/table3_multivariable.csv")

# ---------------------------------------------------------------- 4a. 森林图
forest <- multi
forest$row <- paste0(forest$中文名, "  ", forest$对比)
forest$row <- factor(forest$row, levels = rev(forest$row))
forest$txt <- sprintf("%.2f (%.2f–%.2f)", forest$OR, forest$CI下限, forest$CI上限)
x_text <- max(forest$CI上限) * 1.8
p_forest <- ggplot(forest, aes(OR, row)) +
  geom_vline(xintercept = 1, linetype = "dashed", colour = "grey50") +
  geom_errorbar(aes(xmin = CI下限, xmax = CI上限), width = 0.25, orientation = "y", colour = COL_MODEL) +
  geom_point(shape = 15, size = 2.6, colour = COL_MODEL) +
  geom_text(aes(x = x_text, label = txt), hjust = 0, family = FONT, size = 3.2) +
  scale_x_log10(expand = expansion(mult = c(0.05, 0.45))) +
  labs(x = "OR（95% CI，对数刻度）", y = NULL, title = "多因素 Logistic 回归：院内死亡的独立影响因素") +
  theme_cn()
save_plot(p_forest, "results/figures/fig2_forest.png", 9, 0.38 * nrow(forest) + 1.6)

# ---------------------------------------------------------------- 4b. RCS 曲线（非线性变量）
if (length(intersect(final_vars, nonlinear))) {
  rcs_df <- do.call(rbind, lapply(intersect(final_vars, nonlinear), function(v) {
    pr <- Predict(fit, name = v, fun = exp, ref.zero = TRUE)
    data.frame(变量 = paste0(LABEL[[v]], if (UNIT[[v]] != "") paste0("（", UNIT[[v]], "）") else ""),
               x = pr[[v]], or = pr$yhat, lo = pr$lower, hi = pr$upper)
  }))
  p_rcs <- ggplot(rcs_df, aes(x, or)) +
    geom_hline(yintercept = 1, linetype = "dashed", colour = "grey50") +
    geom_ribbon(aes(ymin = lo, ymax = hi), fill = COL_MODEL, alpha = 0.18) +
    geom_line(colour = COL_MODEL, linewidth = 0.9) +
    facet_wrap(~变量, scales = "free_x") +
    scale_y_log10() +
    labs(x = NULL, y = "OR（以中位数为参照，对数刻度）", title = "限制性立方样条：非线性变量与院内死亡风险的关系") +
    theme_cn()
  save_plot(p_rcs, "results/figures/fig4_rcs.png", 9, 4.2)
}

# ---------------------------------------------------------------- 4c. 列线图
# 多重插补合并后的模型不带变量标签，手动补上中文短标签（去掉"首日最差值"等括注，避免压到刻度轴）
fit$Design$label <- sapply(fit$Design$name, function(v) {
  short <- sub("（.*?）", "", LABEL[[v]])
  if (UNIT[[v]] == "") short else paste0(short, "（", UNIT[[v]], "）")
})
axis_args <- AXIS[intersect(final_vars, names(AXIS))]
nom <- do.call(nomogram, c(list(fit, fun = plogis, fun.at = c(0.02, 0.05, 0.1, 0.2, 0.4, 0.6, 0.8),
                                funlabel = "院内死亡风险", lp = FALSE), axis_args))
agg_png("results/figures/fig3_nomogram.png", width = 10, height = 0.55 * length(final_vars) + 2.6,
        units = "in", res = 300)
par(family = FONT, mar = c(1, 1, 2, 1))
plot(nom, xfrac = 0.25, cex.axis = 0.8, cex.var = 0.95, lmgp = 0.2,
     points.label = "得分", total.points.label = "总得分")
title("院内死亡风险列线图", family = FONT)
mtext("生命体征为入 ICU 首日最差值；肌酐为首日最高值，碳酸氢根为首日最低值",
      side = 1, line = -0.5, cex = 0.75, family = FONT, col = "grey35")
invisible(dev.off())
cat("已生成 results/figures/fig3_nomogram.png\n")

# ---------------------------------------------------------------- 5. 内部验证（Bootstrap，含变量筛选）
B <- 1000
# jsonlite 也有同名的 validate()，这里显式指定 rms 的版本
v_int <- rms::validate(full, B = B, bw = TRUE, rule = "aic")
final1 <- lrm(final_formula, data = dev1, x = TRUE, y = TRUE)
cal_int <- calibrate(final1, B = B)

# ---------------------------------------------------------------- 6. 预测与外部验证
# 每个插补数据集分别预测，取 5 次平均
predict_avg <- function(imp) {
  rowMeans(sapply(1:imp$m, function(k) predict(fit, newdata = complete(imp, k), type = "fitted")))
}
dev$p_model <- predict_avg(imp_dev)
val$p_model <- predict_avg(imp_val)

# 导出预测值，供机器学习对比（R/03_ml_compare.R）使用
pred_out <- rbind(
  data.frame(patientunitstayid = dev$patientunitstayid, cohort_split = "development",
             death_hosp = dev$death_hosp, p_logistic = dev$p_model, apache_iva_pred = dev$apache_iva_pred),
  data.frame(patientunitstayid = val$patientunitstayid, cohort_split = "validation",
             death_hosp = val$death_hosp, p_logistic = val$p_model, apache_iva_pred = val$apache_iva_pred)
)
write.csv(pred_out, "results/model/predictions_logistic.csv", row.names = FALSE)

idx <- function(m, name) m[name, "index.corrected"]
corrected <- data.frame(
  例数 = nrow(dev), 死亡数 = sum(dev$death_hosp),
  AUC = sprintf("%.3f", 0.5 + idx(v_int, "Dxy") / 2), Brier = round(idx(v_int, "B"), 3),
  校准截距 = round(idx(v_int, "Intercept"), 2), 校准斜率 = round(idx(v_int, "Slope"), 2), HL检验P = ""
)

dev_a <- dev[!is.na(dev$apache_iva_pred), ]
val_a <- val[!is.na(val$apache_iva_pred), ]
performance <- rbind(
  cbind(数据集 = "建模组", 模型 = "本研究模型（表观）", perf(dev$p_model, dev$death_hosp)),
  cbind(数据集 = "建模组", 模型 = sprintf("本研究模型（Bootstrap %d 次校正）", B), corrected),
  cbind(数据集 = "验证组", 模型 = "本研究模型", perf(val$p_model, val$death_hosp)),
  cbind(数据集 = "建模组（有 APACHE 预测者）", 模型 = "本研究模型", perf(dev_a$p_model, dev_a$death_hosp)),
  cbind(数据集 = "建模组（有 APACHE 预测者）", 模型 = "APACHE IVa", perf(dev_a$apache_iva_pred, dev_a$death_hosp)),
  cbind(数据集 = "验证组（有 APACHE 预测者）", 模型 = "本研究模型", perf(val_a$p_model, val_a$death_hosp)),
  cbind(数据集 = "验证组（有 APACHE 预测者）", 模型 = "APACHE IVa", perf(val_a$apache_iva_pred, val_a$death_hosp))
)
write_csv_bom(performance, "results/tables/table4_performance.csv")

# 与 APACHE IVa 的 AUC 比较（同一批患者，配对 DeLong 检验）
delong <- function(d) {
  r1 <- roc(d$death_hosp, d$p_model, levels = c(0, 1), direction = "<", quiet = TRUE)
  r2 <- roc(d$death_hosp, d$apache_iva_pred, levels = c(0, 1), direction = "<", quiet = TRUE)
  roc.test(r1, r2, method = "delong", paired = TRUE)$p.value
}
p_delong <- c(建模组 = delong(dev_a), 验证组 = delong(val_a))
cat("DeLong 检验（本研究模型 vs APACHE IVa）P 值：",
    paste(names(p_delong), fmt_p(p_delong), collapse = "；"), "\n")

# ---------------------------------------------------------------- 6a. ROC 曲线
roc_df <- function(p, y, label, panel) {
  r <- roc(y, p, levels = c(0, 1), direction = "<", quiet = TRUE)
  ci <- ci.auc(r, method = "delong")
  data.frame(fpr = 1 - r$specificities, tpr = r$sensitivities, panel = panel,
             曲线 = sprintf("%s  AUC %.3f (%.3f–%.3f)", label, ci[2], ci[1], ci[3]), 模型 = label)
}
roc_all <- rbind(
  roc_df(dev_a$p_model, dev_a$death_hosp, "本研究模型", "A  建模组"),
  roc_df(dev_a$apache_iva_pred, dev_a$death_hosp, "APACHE IVa", "A  建模组"),
  roc_df(val_a$p_model, val_a$death_hosp, "本研究模型", "B  外部验证组"),
  roc_df(val_a$apache_iva_pred, val_a$death_hosp, "APACHE IVa", "B  外部验证组")
)
roc_all <- roc_all[order(roc_all$panel, roc_all$曲线, roc_all$fpr, roc_all$tpr), ]
auc_lab <- unique(roc_all[, c("panel", "曲线", "模型")])
auc_lab$y <- ifelse(auc_lab$模型 == "本研究模型", 0.16, 0.08)
p_roc <- ggplot(roc_all, aes(fpr, tpr, colour = 模型)) +
  geom_abline(linetype = "dashed", colour = "grey60") +
  geom_path(linewidth = 0.8) +
  geom_text(data = auc_lab, aes(x = 0.98, y = y, label = 曲线), hjust = 1, family = FONT,
            size = 3.2, show.legend = FALSE) +
  facet_wrap(~panel) +
  scale_colour_manual(values = c("本研究模型" = COL_MODEL, "APACHE IVa" = COL_APACHE)) +
  coord_equal() +
  labs(x = "1 − 特异度", y = "灵敏度", colour = NULL,
       title = "ROC 曲线：本研究模型 vs APACHE IVa",
       caption = sprintf("DeLong 检验 P：建模组 %s，外部验证组 %s（仅含有 APACHE IVa 预测值的患者）",
                         fmt_p(p_delong[1]), fmt_p(p_delong[2]))) +
  theme_cn()
save_plot(p_roc, "results/figures/fig5_roc.png", 9, 5.2)

# ---------------------------------------------------------------- 6b. 校准曲线
smooth_cal <- function(p, y, label, panel) {
  lo <- lowess(p, y, iter = 0)
  data.frame(pred = lo$x, obs = lo$y, 曲线 = label, panel = panel)
}
CAL_LABELS <- c("A：本研究模型（表观）", sprintf("A：本研究模型（Bootstrap %d 次校正）", B),
                "B：本研究模型", "B：APACHE IVa")
cal_df <- rbind(
  data.frame(pred = cal_int[, "predy"], obs = cal_int[, "calibrated.orig"], 曲线 = CAL_LABELS[1],
             panel = "A  建模组（内部验证）"),
  data.frame(pred = cal_int[, "predy"], obs = cal_int[, "calibrated.corrected"], 曲线 = CAL_LABELS[2],
             panel = "A  建模组（内部验证）"),
  smooth_cal(val$p_model, val$death_hosp, CAL_LABELS[3], "B  外部验证组"),
  smooth_cal(val_a$apache_iva_pred, val_a$death_hosp, CAL_LABELS[4], "B  外部验证组")
)
cal_df$曲线 <- factor(cal_df$曲线, levels = CAL_LABELS)
cal_cols <- setNames(c("grey60", COL_MODEL, COL_MODEL, COL_APACHE), CAL_LABELS)
lim <- c(0, 0.8)
p_cal <- ggplot(cal_df, aes(pred, obs, colour = 曲线)) +
  geom_abline(linetype = "dashed", colour = "grey60") +
  geom_line(linewidth = 0.9) +
  facet_wrap(~panel) +
  scale_colour_manual(values = cal_cols) +
  coord_equal(xlim = lim, ylim = lim) +
  labs(x = "预测死亡概率", y = "实际死亡比例", colour = NULL, title = "校准曲线（虚线为理想校准）") +
  guides(colour = guide_legend(nrow = 2)) +
  theme_cn()
save_plot(p_cal, "results/figures/fig6_calibration.png", 9, 5.2)

# ---------------------------------------------------------------- 6c. 决策曲线（DCA）
dca_df <- function(d, panel) {
  d$model <- d$p_model
  d$apache <- d$apache_iva_pred
  x <- dca(death_hosp ~ model + apache, data = d, thresholds = seq(0, 0.5, 0.01),
           label = list(model = "本研究模型", apache = "APACHE IVa"))
  out <- as.data.frame(x$dca)
  out$panel <- panel
  out
}
dca_all <- rbind(dca_df(dev_a, "A  建模组"), dca_df(val_a, "B  外部验证组"))
dca_all$label <- as.character(dca_all$label)
dca_all$label[dca_all$label == "Treat All"] <- "全部干预"
dca_all$label[dca_all$label == "Treat None"] <- "均不干预"
dca_cols <- c("本研究模型" = COL_MODEL, "APACHE IVa" = COL_APACHE, "全部干预" = "grey55", "均不干预" = "black")
ymax <- max(dca_all$net_benefit[dca_all$label != "全部干预"], na.rm = TRUE)
p_dca <- ggplot(dca_all, aes(threshold, net_benefit, colour = label)) +
  geom_line(linewidth = 0.8) +
  facet_wrap(~panel) +
  scale_colour_manual(values = dca_cols) +
  coord_cartesian(ylim = c(-0.02, ymax * 1.15)) +
  labs(x = "阈概率", y = "净获益", colour = NULL, title = "决策曲线分析（DCA）") +
  theme_cn()
save_plot(p_dca, "results/figures/fig7_dca.png", 9, 4.8)

# ---------------------------------------------------------------- 7. 导出模型（供风险计算器网页使用）
knots <- lapply(intersect(final_vars, nonlinear), function(v) fit$Design$parms[[v]])
names(knots) <- intersect(final_vars, nonlinear)
ranges <- lapply(final_vars, function(v) {
  if (v %in% BINARY) NULL else as.numeric(quantile(dev1[[v]], c(0.01, 0.5, 0.99)))
})
names(ranges) <- final_vars
# 校验用例：随机生成 12 位虚构患者（不含真实患者数据），网页计算器用同样的输入，算出的线性预测值必须与 R 一致
set.seed(11)
tc <- as.data.frame(lapply(setNames(final_vars, final_vars), function(v) {
  if (v %in% BINARY) sample(0:1, 12, replace = TRUE)
  else round(runif(12, quantile(dev1[[v]], 0.02), quantile(dev1[[v]], 0.98)), 1)
}))
nd <- tc
for (v in intersect(final_vars, BINARY)) nd[[v]] <- factor(nd[[v]], levels = c(0, 1), labels = c("否", "是"))
tc$lp_expected <- as.numeric(predict(fit, newdata = nd, type = "lp"))

model_json <- list(
  outcome = "院内死亡",
  coefficients = as.list(coef(fit)),
  test_cases = tc,
  variables = lapply(final_vars, function(v) list(
    name = v, label = LABEL[[v]], unit = UNIT[[v]],
    type = if (v %in% BINARY) "binary" else if (v %in% nonlinear) "rcs" else "linear",
    knots = knots[[v]], p01_median_p99 = ranges[[v]]
  )),
  performance = performance
)
write_json(model_json, "results/model/model.json", auto_unbox = TRUE, digits = 10, pretty = TRUE)
saveRDS(list(fit = fit, final_vars = final_vars, nonlinear = nonlinear), "results/model/model.rds")
cat("已生成 results/model/model.json\n")

print(performance, row.names = FALSE)
