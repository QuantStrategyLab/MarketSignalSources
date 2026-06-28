# MarketSignalSources

QuantStrategyLab 策略平台的市场信号源构建工具包，采用 artifact-first 设计。

## 安装

```bash
python -m pip install "market-signal-sources @ git+https://github.com/QuantStrategyLab/MarketSignalSources.git@main"
```

运行时平台应将此包视为信号 artifact 生产者和合约校验器。券商执行仓库应消费已发布的 JSON artifact 或固定的合约导出，而非在券商适配器内计算市场信号。

## 许可证

详见 [LICENSE](LICENSE)。
