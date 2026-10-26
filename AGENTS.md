# 项目维护约定

- 本项目提取抗衰老论文的候选化合物、生物实验和证据，再查询外部数据库；结果需要人工核验。
- 保持包名 `chem-pdf-extractor`、版本 `0.4.0`、虚拟环境名 `SenoMiner_AI` 和 Python `3.11.15`，除非用户明确要求升级。
- Python 命令使用 `.conda/SenoMiner_AI/bin/python`。不要移动环境目录。
- 根目录 `README.md` 是使用说明的唯一入口，开发细节放在 `docs/开发说明.md`；不要恢复被移除的旧系统或堆积历史介绍。
- 修改相关逻辑后运行 `.conda/SenoMiner_AI/bin/python -m unittest discover -s tests -v`、两个 CLI 的 `--help` 和 `git diff --check`。
- 保留本地回环服务、请求 token、密钥脱敏和导出公式转义。云端处理应由用户选择配置。
- 不提交 `.env`、`config.local.json`、真实密钥、论文、生成结果、环境、缓存或日志。
- 保留第三方许可证与来源记录。不要用未核验的结果宣称科学准确率、实验可重复性或人体疗效。
