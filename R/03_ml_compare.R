# 第 7 步：在外部验证组比较四个模型
#   Logistic 列线图模型（R/02_model.R）、随机森林、XGBoost（src/ml_models.py）、APACHE IVa
#   ROC 曲线与配对 DeLong 检验、校准曲线、性能汇总表
# 用法：在项目根目录运行 Rscript R/03_ml_compare.R

source("R/utils.R")
suppressPackageStartupMessages({
  library(pROC)
  library(ggplot2)
  library(rms)
})

lg <- read.csv("results/model/predictions_logistic.csv")
ml <- read.csv("results/model/predictions_ml.csv")
d <- merge(lg, ml, by = "patientunitstayid")
val <- d[d$cohort_split == "validation", ]
val_a <- val[!is.na(val$apache_iva_pred), ]

MODELS <- c(p_logistic = "Logistic 列线图模型", p_rf = "随机森林", p_xgb = "XGBoost", apache_iva_pred = "APACHE IVa")
COLS <- setNames(c(COL_MODEL, COL_RF, COL_XGB, COL_APACHE), MODELS)

# ---------------------------------------------------------------- 性能汇总与 DeLong 检验
roc_of <- function(data, col) roc(data$death_hosp, data[[col]], levels = c(0, 1), direction = "<", quiet = TRUE)
delong_p <- function(data, a, b) roc.test(roc_of(data, a), roc_of(data, b), method = "delong", paired = TRUE)$p.value

rows <- list()
for (col in names(MODELS)[1:3]) {
  rows[[length(rows) + 1]] <- cbind(数据集 = "外部验证组（全部）", 模型 = MODELS[[col]], perf(val[[col]], val$death_hosp),
                                    `vs Logistic P` = if (col == "p_logistic") "" else fmt_p(delong_p(val, col, "p_logistic")),
                                    `vs APACHE IVa P` = "")
}
for (col in names(MODELS)) {
  rows[[length(rows) + 1]] <- cbind(数据集 = "外部验证组（有 APACHE 预测者）", 模型 = MODELS[[col]],
                                    perf(val_a[[col]], val_a$death_hosp),
                                    `vs Logistic P` = if (col == "p_logistic") "" else fmt_p(delong_p(val_a, col, "p_logistic")),
                                    `vs APACHE IVa P` = if (col == "apache_iva_pred") "" else fmt_p(delong_p(val_a, col, "apache_iva_pred")))
}
comparison <- do.call(rbind, rows)
write_csv_bom(comparison, "results/tables/table6_model_comparison.csv")
print(comparison, row.names = FALSE)

# ---------------------------------------------------------------- ROC 曲线（同一批患者）
roc_df <- do.call(rbind, lapply(names(MODELS), function(col) {
  r <- roc_of(val_a, col)
  ci <- ci.auc(r, method = "delong")
  data.frame(fpr = 1 - r$specificities, tpr = r$sensitivities, 模型 = MODELS[[col]],
             图例 = sprintf("%s  AUC %.3f (%.3f–%.3f)", MODELS[[col]], ci[2], ci[1], ci[3]))
}))
roc_df <- roc_df[order(roc_df$模型, roc_df$fpr, roc_df$tpr), ]
legend_map <- unique(roc_df[, c("模型", "图例")])

# 导出 ROC 坐标，供展示网页绘制交互式 ROC 曲线
roc_json <- lapply(names(MODELS), function(col) {
  r <- roc_of(val_a, col)
  ci <- ci.auc(r, method = "delong")
  pts <- unique(data.frame(fpr = round(1 - r$specificities, 4), tpr = round(r$sensitivities, 4)))
  pts <- pts[order(pts$fpr, pts$tpr), ]
  list(key = col, name = MODELS[[col]], auc = round(ci[2], 3), lo = round(ci[1], 3), hi = round(ci[3], 3),
       fpr = pts$fpr, tpr = pts$tpr)
})
jsonlite::write_json(list(n = nrow(val_a), deaths = sum(val_a$death_hosp),
                          p_vs_apache = round(delong_p(val_a, "p_logistic", "apache_iva_pred"), 3),
                          curves = roc_json),
                     "results/model/roc_validation.json", auto_unbox = TRUE, digits = NA)
cat("已生成 results/model/roc_validation.json\n")
p_roc <- ggplot(roc_df, aes(fpr, tpr, colour = 模型)) +
  geom_abline(linetype = "dashed", colour = "grey60") +
  geom_path(linewidth = 0.8) +
  scale_colour_manual(values = COLS, breaks = MODELS,
                      labels = setNames(legend_map$图例, legend_map$模型)[MODELS]) +
  coord_equal() +
  guides(colour = guide_legend(ncol = 1)) +
  labs(x = "1 − 特异度", y = "灵敏度", colour = NULL,
       title = "外部验证组 ROC 曲线：四个模型对比",
       subtitle = sprintf("同一批 %d 例患者（死亡 %d 例）", nrow(val_a), sum(val_a$death_hosp))) +
  theme_cn() +
  theme(legend.position = "right")
save_plot(p_roc, "results/figures/fig8_model_roc.png", 9, 5.2)

# ---------------------------------------------------------------- 校准曲线
cal_df <- do.call(rbind, lapply(names(MODELS), function(col) {
  lo <- lowess(val_a[[col]], val_a$death_hosp, iter = 0)
  data.frame(pred = lo$x, obs = lo$y, 模型 = MODELS[[col]])
}))
cal_df$模型 <- factor(cal_df$模型, levels = MODELS)
p_cal <- ggplot(cal_df, aes(pred, obs, colour = 模型)) +
  geom_abline(linetype = "dashed", colour = "grey60") +
  geom_line(linewidth = 0.9) +
  scale_colour_manual(values = COLS) +
  coord_equal(xlim = c(0, 0.8), ylim = c(0, 0.8)) +
  labs(x = "预测死亡概率", y = "实际死亡比例", colour = NULL,
       title = "外部验证组校准曲线：四个模型对比", subtitle = "虚线为理想校准") +
  theme_cn() +
  theme(legend.position = "right")
save_plot(p_cal, "results/figures/fig9_model_calibration.png", 8, 5.2)
