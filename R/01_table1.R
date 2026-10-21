# 第 3 步：基线特征表（Table 1）
#   表 1A：存活组 vs 死亡组
#   表 1B：建模组 vs 验证组（检查两组人群是否可比）
# 连续变量用 中位数 [四分位间距] 表示、Mann-Whitney U 检验；分类变量用 n (%) 表示、卡方检验
# 用法：在项目根目录运行 Rscript R/01_table1.R

source("R/utils.R")
suppressPackageStartupMessages(library(tableone))

df <- read.csv("data/processed/analysis_dataset.csv", fileEncoding = "UTF-8")
vars <- read.csv("config/variables.csv", fileEncoding = "UTF-8")
vars <- vars[vars$table1 == 1, ]

# 变量显示名：中文名 + 单位
display <- ifelse(vars$unit == "" | is.na(vars$unit), vars$label, paste0(vars$label, "（", vars$unit, "）"))
names(display) <- vars$name

# 二分类变量转成 否 / 是，入科来源转成中文
for (v in vars$name[vars$type == "binary"]) {
  df[[v]] <- factor(df[[v]], levels = c(0, 1), labels = c("否", "是"))
}
df$admit_source <- factor(df$admit_source,
                          levels = c("ED", "OR", "Ward", "Other"),
                          labels = c("急诊", "手术室 / 麻醉恢复室", "普通病房", "其他"))
df$outcome <- factor(df$death_hosp, levels = c(0, 1), labels = c("存活", "死亡"))
df$split <- factor(df$cohort_split, levels = c("development", "validation"), labels = c("建模组", "验证组"))

# 列名换成中文显示名，表格直接可用
tab_data <- df[, vars$name]
names(tab_data) <- display[vars$name]
continuous <- unname(display[vars$name[vars$type == "continuous"]])

make_table <- function(strata, file) {
  tab_data$group <- strata
  t1 <- CreateTableOne(vars = unname(display[vars$name]), strata = "group", data = tab_data, test = TRUE)
  out <- print(t1, nonnormal = continuous, showAllLevels = FALSE, missing = TRUE, contDigits = 1,
               quote = FALSE, noSpaces = TRUE, printToggle = FALSE)
  out <- out[, colnames(out) != "test"]
  colnames(out)[colnames(out) == "Missing"] <- "缺失率(%)"
  out <- cbind(变量 = rownames(out), out)
  write_csv_bom(out, file)
  invisible(out)
}

t1a <- make_table(df$outcome, "results/tables/table1_by_outcome.csv")
t1b <- make_table(df$split, "results/tables/table1_by_split.csv")
print(t1a[, c("存活", "死亡", "p")], quote = FALSE)
