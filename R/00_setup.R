# 安装本项目用到的 R 包（装到个人库，不需要管理员权限）
lib <- Sys.getenv("R_LIBS_USER")
dir.create(lib, recursive = TRUE, showWarnings = FALSE)
.libPaths(c(lib, .libPaths()))
pkgs <- c("rms", "pROC", "tableone", "ggplot2", "dcurves", "jsonlite", "mice", "ragg")
need <- setdiff(pkgs, rownames(installed.packages()))
if (length(need)) install.packages(need, lib = lib, repos = "https://cloud.r-project.org", type = "binary")
for (p in pkgs) cat(p, as.character(packageVersion(p)), "\n")
