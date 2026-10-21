# 各 R 脚本共用的设置和工具函数：source("R/utils.R")

.libPaths(c(Sys.getenv("R_LIBS_USER"), .libPaths()))

FONT <- "Microsoft YaHei"
COL_MODEL <- "#2F6FA3"   # 本研究 Logistic 模型
COL_APACHE <- "#E07B39"  # APACHE IVa
COL_RF <- "#4E9A5B"      # 随机森林
COL_XGB <- "#8A5CB8"     # XGBoost

dir.create("results/figures", recursive = TRUE, showWarnings = FALSE)
dir.create("results/tables", recursive = TRUE, showWarnings = FALSE)
dir.create("results/model", recursive = TRUE, showWarnings = FALSE)

theme_cn <- function() {
  ggplot2::theme_bw(base_family = FONT, base_size = 11) +
    ggplot2::theme(panel.grid.minor = ggplot2::element_blank(),
                   strip.background = ggplot2::element_rect(fill = "#EEF3F8"),
                   legend.position = "bottom")
}

save_plot <- function(p, file, w, h) {
  ggplot2::ggsave(file, p, device = ragg::agg_png, width = w, height = h, units = "in", res = 300)
  cat("已生成", file, "\n")
}

# 写出带 BOM 的 UTF-8 CSV，Excel 打开时中文不乱码
write_csv_bom <- function(x, file) {
  con <- file(file, open = "wb")
  writeBin(as.raw(c(0xEF, 0xBB, 0xBF)), con)
  close(con)
  suppressWarnings(write.table(x, file, append = TRUE, sep = ",", row.names = FALSE,
                               qmethod = "double", fileEncoding = "UTF-8"))
  cat("已生成", file, "\n")
}

fmt_p <- function(p) ifelse(is.na(p), "", ifelse(p < 0.001, "<0.001", sprintf("%.3f", p)))

# 区分度、校准度汇总：AUC（DeLong 95% CI）、Brier、校准截距与斜率、Hosmer-Lemeshow 检验
perf <- function(p, y) {
  r <- pROC::roc(y, p, levels = c(0, 1), direction = "<", quiet = TRUE)
  ci <- pROC::ci.auc(r, method = "delong")
  vp <- rms::val.prob(p, y, pl = FALSE)
  g <- cut(p, unique(quantile(p, 0:10 / 10)), include.lowest = TRUE)
  o <- tapply(y, g, sum)
  e <- tapply(p, g, sum)
  n <- tapply(y, g, length)
  hl <- sum((o - e)^2 / (e * (1 - e / n)))
  data.frame(例数 = length(y), 死亡数 = sum(y),
             AUC = sprintf("%.3f (%.3f–%.3f)", ci[2], ci[1], ci[3]),
             Brier = round(vp[["Brier"]], 3), 校准截距 = round(vp[["Intercept"]], 2),
             校准斜率 = round(vp[["Slope"]], 2), HL检验P = fmt_p(1 - pchisq(hl, length(o) - 2)))
}
