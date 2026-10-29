# MarketSignalSources

从本地源数据构建和校验市场信号文件。

[English](README.md) | 简体中文

## 状态

实验项目。本项目不构成投资建议，也不保证交易收益。下游实盘交易可能亏损，
使用者须对自己的配置和订单负责。

## 简介

本 Python 包面向需要可复现输入的策略研究和平台集成开发者。它规范化本地数据，
计算衍生指标，生成 JSON 或 CSV 文件，并记录哈希、来源、时效信息以及规定
消费方所需字段的契约。

本包提供 BTC 周期指标、日线 OHLCV（开盘、最高、最低、收盘和成交量）技术指标、半导体轮动输入和美股研究导出。
目录和契约校验器检查信号源类别是否提供消费方需要的标的与字段。

## 不适用范围

本包不规划或提交订单，不管理券商账户，也不修改平台设置。信号文件通过校验，
不代表已证明历史数据可用性、获得数据许可或取得交易授权。券商适配器消费
经过校验的文件，不自行计算跨平台共享信号。

## 快速开始

需要 Python 3.11 或更新版本。本地安装：

```bash
git clone https://github.com/QuantStrategyLab/MarketSignalSources.git
cd MarketSignalSources
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -e . pytest
python -m pytest tests -q
```

查看内置目录，不获取数据，也不写入产物：

```bash
python -m market_signal_sources.cli.list_signal_source_families --pretty
python -m market_signal_sources.cli.list_consumer_contracts --pretty
```

下游安装时，固定到经过审查的不可变版本：

```text
market-signal-sources @ git+https://github.com/QuantStrategyLab/MarketSignalSources.git@<commit-sha>
```

开发时可使用当前公开分支：

```bash
python -m pip install "market-signal-sources @ git+https://github.com/QuantStrategyLab/MarketSignalSources.git@main"
uv add "market-signal-sources @ git+https://github.com/QuantStrategyLab/MarketSignalSources.git@main"
```

本地构建信号包、研究导出、文件校验和交接示例见
[CLI 参考](docs/cli-reference.md)。交接清单通过哈希关联信号包、信号源目录和
消费方契约注册表。

## 配置

核心 CLI 使用显式参数和本地文件。下列参数适用于 `build_btc_cycle_bundle`；
其他命令的选项见各自的 `--help`。

| 选项 | 必需 | 默认值 | 用途 |
| --- | --- | --- | --- |
| `--input-csv` | 是 | 无 | 本地 OHLCV CSV，例如 `./btc_daily.csv`。 |
| `--output-dir` | 是 | 无 | 存放信号包、质量报告、清单和本地索引的目录。 |
| `--as-of` | 是 | 无 | `YYYY-MM-DD` 格式的源数据截止日期。 |
| `--generated-at` | 是 | 无 | 带时区的文件生成时间。 |
| `--symbol` | 否 | `BTC-USD` | 输入 CSV 对应的标的。 |
| `--provider` | 否 | `local_csv` | 记录在来源信息中的数据提供方。 |
| `--provider-dataset` | 否 | `btc_usd_daily_ohlcv` | 记录在来源信息中的数据集。 |
| `--source-version` | 否 | `0.1.0` | 记录在来源信息中的生成器版本。 |
| `--code-commit` | 否 | 全零的提交占位符 | 生成器版本；发布产物时设置真实提交版本。 |
| `--license-scope` | 否 | `internal_runtime` | 声明的数据使用范围，本身不授予许可。 |
| `--max-age-hours` | 否 | `36` | 信号包的时效上限，单位为小时。 |
| `--publication-index` | 否 | 无 | 可选的本地共享索引，用新清单更新。 |

本地 CSV 输入默认需要 `date` 和 `close` 列。缺少 `high` 和 `low` 列时使用
收盘价，`volume` 为可选列。列名可以配置。产物中不得包含签名 URL、token、
cookie、账户 ID 或原始券商数据。

## 架构

`providers` 读取本地输入，`derived` 计算指标，`artifacts` 写入和校验契约，
`cli` 提供命令入口。详见[信号源架构](docs/platform-signal-source-architecture.md)
和[平台消费契约](docs/platform-consumption-contract.md)。

[CLI 参考](docs/cli-reference.md)介绍信号包和注册表结构、信号源目录、质量检查、
时效策略、运行时输入映射，以及仅供研究使用的导出。组织概览见
[QuantStrategyLab](https://github.com/QuantStrategyLab/.github/blob/main/profile/README.md)。

## 仓库结构

```text
src/market_signal_sources/    数据读取、指标、产物和 CLI 命令
tests/                       单元测试和本地产物测试
docs/                        架构、契约和 CLI 参考
scripts/                     发布和维护入口
```

## 参与贡献

详见 [CONTRIBUTING.md](CONTRIBUTING.md)。AI 助手与维护者遵循 [AGENTS.md](AGENTS.md)。文档遵循
[QuantStrategyLab 文档风格指南](https://github.com/QuantStrategyLab/.github/blob/main/docs/STYLE_GUIDE.md)。

## 安全

私下报告漏洞的方式见 [SECURITY.md](SECURITY.md)。不要在公开 issue 中提供凭据
或提交漏洞报告。

## 许可证

[MIT](LICENSE)。
