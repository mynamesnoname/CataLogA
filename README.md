# CataLogA — 红移灾难检测 Agent

DESI 巡天中，Redrock 模板拟合偶尔会给出错误红移（天空线误判、χ²局部极小值、模板错配等）。这类"红移灾难"会直接污染 BAO 和大尺度结构宇宙学分析。

CataLogA 利用 DESI **重复观测**（同一目标被观测两次）的特性：两条光谱各自跑 Redrock，如果 |z₁ − z₂| 很大，就标记为可疑。然后启动 LLM agent 链（SH → FA → HS → RA）逐层审查。

## 快速开始

```bash
# 1. 环境
conda activate cataloga
pip install -r requirements.txt

# 2. 配置
cp .env_example .env
# 编辑 .env，必填 LLM_API_KEY

# 3. 预处理（扫描 DESI 数据、找重复观测对、建 symlink）
python scripts/preprocess.py

# 4. 运行管道
python scripts/run_pipeline.py
```

## 配置参数

全部参数按功能分组：

### LLM

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `LLM_API_KEY` | *必填* | API 密钥（DeepSeek 或 Anthropic，取决于 `LLM_MODEL`） |
| `LLM_BASE_URL` | (留空) | 留空 = 官方 API：模型名以 `claude` 开头走 Anthropic 原生 API，否则走 OpenAI 兼容端点。DeepSeek 示例：`https://api.deepseek.com` |
| `LLM_MODEL` | `claude-opus-5` | 默认模型名称，被下方 `LLM_MODEL_{SH,FA,HS,RA}` 未设置时使用 |
| `LLM_MODEL_SH` / `LLM_MODEL_FA` / `LLM_MODEL_HS` / `LLM_MODEL_RA` | (留空 = 用 `LLM_MODEL`) | 按 stage 覆盖模型，见下方「成本优化」 |
| `LLM_TEMPERATURE` | `0.1` | 采样温度。Claude Opus/Sonnet 5 等当前 Anthropic 模型不接受该参数，自动忽略 |
| `LLM_MAX_TOKENS` | (自动) | 最大输出 token。留空时 DeepSeek 自动设为 65536，Anthropic 模型默认 16000 |
| `LLM_THINKING` | `disabled` | 思维链模式。`enabled` 仅在简单 LLM 调用时生效；工具调用模式始终显式 `disabled`（Claude Opus 5 若不显式传值默认开启 adaptive thinking，工具调用响应可能变成多 block 而非纯文本） |
| `LLM_STREAMING` | `false` | ReAct 过程实时输出。`true` 时每轮 LLM 的工具调用和返回都会打印到终端，同时写入 `*_react.md` 日志 |

### CWT 特征检测

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `CWT_SNR_THRESH` | `8.0` | SNR 阈值，越大越严格 |
| `CWT_MIN_RIDGE_LENGTH` | `4` | 最小脊线长度，特征需在至少这么多尺度上被检测 |
| `CWT_N_SCALES` | `24` | 小波尺度数量（对数均匀分布） |
| `CWT_MIN_WIDTH` | `1.0` | 最窄谱线宽度（≈ FWHM / 2.355 px） |
| `CWT_MAX_WIDTH` | `80.0` | 最宽谱线宽度（≈ FWHM / 2.355 px） |

### Agent 递归上限

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `MAX_TURNS_SH` | `500` | Single Hypothesis 最大工具调用轮数 |
| `MAX_TURNS_FA` | `500` | Feature Auditor 最大轮数 |
| `MAX_TURNS_HS` | `500` | Hypothesis Synthesis 最大轮数 |
| `MAX_TURNS_RA` | `500` | Result Auditor 最大轮数 |

### 数据路径与预处理

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `DATA_ROOT` | `.data/test_catas` | DESI 原始数据根目录。脚本在此目录下按硬编码路径搜索 FITS |
| `INTERMEDIATE_DIR` | `input` | 中间目录。`preprocess.py` 在此按 TARGETID 创建子目录和 symlink |
| `OUTPUT_DIR` | `output` | 流水线输出目录。每 TARGETID 一个子目录 |
| `DZ_THRESHOLD_QSO` | `0.03` | QSO 对（RedrockType 任一侧为 QSO）的红移差阈值，≈ dv 10,000 km/s |
| `DZ_THRESHOLD_GALAXY` | `0.003` | 星系类对的红移差阈值，≈ dv 1,000 km/s |

### 运行目标

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `TARGETID` | — | 要处理的目标。支持格式见下文 |

`TARGETID` 取值：

| 值 | 含义 |
|----|------|
| `39628250216924756` | 单个 TARGETID |
| `396...,396...` | 逗号分隔的多个 ID |
| `all` | `INTERMEDIATE_DIR` 下全部 |
| `tail-10` | `targets.txt` 最后 10 个（|Δz| 最大的） |
| `head-5` | 前 5 个 |
| `[10:]` | Python 切片：第 10 到末尾 |
| `[:30]` | 前 30 个 |
| `[8:10,17:50]` | 多段切片 |

CLI 参数会覆盖 `.env` 的 `TARGETID`：

```bash
python scripts/run_pipeline.py 39628250216924756   # 覆盖为单个 ID
python scripts/run_pipeline.py --all               # 覆盖为全部
```

## 预处理：preprocess.py

```bash
python scripts/preprocess.py           # 扫描数据，生成 CSV 和 symlink
python scripts/preprocess.py --force   # 强制重新扫描（忽略已有 CSV）
```

### 数据目录结构（重要）

脚本在 `DATA_ROOT` 下按 **硬编码路径** 搜索 FITS 文件：

```
{DATA_ROOT}/
└── spectro/loa/tiles/cumulative/    ← 硬编码，不可通过 .env 配置
    └── {TILEID}/
        └── {NIGHT}/
            ├── coadd-{PETAL}-{TILEID}-thru{NIGHT}.fits
            └── redrock-{PETAL}-{TILEID}-thru{NIGHT}.fits
```

`DATA_ROOT` 只需写到测试数据集的根目录（如 `.data/test_catas/`）。脚本会自动拼接 `spectro/loa/tiles/cumulative/` 子路径。如果你的数据使用不同的目录结构，需要修改 `scripts/preprocess.py` 中的 `scan_redrock_files()` 函数。

每个 redrock FITS 的 `FIBERMAP` 和 `REDSHIFTS` HDU 被读取，提取 TARGETID、Z、ZWARN、SPECTYPE、DELTACHI2。仅统计 `OBJTYPE='TGT'` 的科学光纤（排除天空光纤）。

### 四步流程

**第一步：扫描 → repeat_pairs.csv**

遍历所有 `redrock-*.fits`，按 TARGETID 交叉匹配。同一 TARGETID 出现在不同 `(tile, night, petal)` 组合中即为重复观测对。计算每对的 |Δz| = |z₁-z₂| / (1 + (z₁+z₂)/2)（mean-normalized 分数红移差，与顺序无关），按从大到小排列，输出到 `{OUTPUT_DIR}/repeat_pairs.csv`。**这是全部重复观测对**（绝大多数两次拟合是一致的），不代表都是灾难候选。

CSV 表头：`targetid, z1, RedrockType1, zwarn1, dchi2_1, fits1, z2, RedrockType2, zwarn2, dchi2_2, fits2, abs_dz`。其中 `fits1/fits2` 为 `(tile,night,petal)` 格式的元组。

**第二步：筛选 → catastrophic_pairs.csv**

从 `repeat_pairs.csv` 中按 tracer 类型筛选灾难候选：若任一侧 `RedrockType` 为 `QSO`，用 `|Δz| ≥ DZ_THRESHOLD_QSO`；否则用 `|Δz| ≥ DZ_THRESHOLD_GALAXY`（Redrock 不给出 BGS/LRG/ELG 分类，只能按拟合出的 SPECTYPE 区分）。结果写入 `{OUTPUT_DIR}/catastrophic_pairs.csv`（与 `repeat_pairs.csv` 同表头）。

**第三步：Symlink**

为 `catastrophic_pairs.csv` 中的每个 TARGETID 在 `INTERMEDIATE_DIR` 下创建子目录，用绝对路径 symlink 指向原始的 coadd 和 redrock FITS：

```
{INTERMEDIATE_DIR}/{targetid}/
├── coadd-A.fits   → {DATA_ROOT}/spectro/loa/tiles/cumulative/{tile1}/{night1}/coadd-{petal1}-{tile1}-thru{night1}.fits
├── redrock-A.fits  → .../redrock-{petal1}-{tile1}-thru{night1}.fits
├── coadd-B.fits
└── redrock-B.fits
```

同时生成 `{INTERMEDIATE_DIR}/targets.txt`：每行一个 TARGETID，按 |Δz| 从大到小排列。

**第四步：报告**

打印扫描统计：红移文件数、唯一 TARGETID 数、重复观测对总数、ZWARN=0/0 对数量、入选灾难候选数量（按 QSO/galaxy 分类）。

## 管道运行：run_pipeline.py

```bash
python scripts/run_pipeline.py              # 从 .env 读 TARGETID
python scripts/run_pipeline.py 12345        # CLI 覆盖单个 ID
python scripts/run_pipeline.py --all        # 全部
```

### 管道架构

```
VI(coadd-A) + VI(coadd-B)          并行加载两条光谱，CWT 特征检测
        │
   ┌────┴────┐
   │         │
SH-H1      SH-H2                    各自在自己的光谱上用 fit_peak 验证谱线
(coadd-A)  (coadd-B)
   │         │
   └────┬────┘
        │
   FA-H1 || FA-H2                   并行交叉审计：每条特征是否真实？
        │
   ┌────┴────┐
   │         │
  HS          RA                   HS 综合判决；RA 独立诊断灾难成因
(双光谱)    (双光谱)
```

### 各模块职责

| 模块 | 职责 | LLM 工具 |
|------|------|----------|
| **VI** (VisualInterpreter) | 加载 FITS，median-filter CWT 检测特征，Chebyshev 连续谱拟合 | 无（纯数值） |
| **SH** (SingleHypothesis) | 对单个红移假设验证其预测谱线 | `fit_peak`, `fit_doublet`, `read_spectrum_region`, `compute_redshift`, `write_lines_csv` |
| **FA** (FeatureAuditor) | 独立审计每条 claim 是否为真实光谱特征 | `read_spectrum_region`, `grep_kb` |
| **HS** (HypothesisSynthesis) | 综合比较两条 FA 结果，判定偏好哪个红移 | `read_spec(spec)`, `grep_kb` |
| **RA** (ResultAuditor) | 独立诊断灾难成因（天空线混淆 / 模板错配 / 噪声过拟合等） | `read_spec(spec)`, `grep_kb` |

### 成本优化

单目标全流程（VI → SH×2 → FA×2 → HS → RA）在纯 Claude Opus 5 下约 $3-5，两项优化叠加后可降到约 $1.5-2：

1. **Prompt caching**（`core/llm.py: create_chat_anthropic`）— 每次 Anthropic 请求自动带上
   `cache_control: {"type": "ephemeral"}`，缓存到目前为止的整个前缀（skill 系统提示 + 工具定义 +
   历史对话）。SH/FA/HS/RA 都是多轮 ReAct 工具调用循环，同一份 skill 文本（FA_skill.md 达 37K
   字符）不缓存的话每轮都要全价重发。实测单目标节省约 35-40%。
2. **按 stage 分层模型**（`LLM_MODEL_SH`/`LLM_MODEL_FA`/`LLM_MODEL_HS`/`LLM_MODEL_RA`）—
   SH/FA 是规则化的工具调用任务（逐条验证/审计谱线，判据已写在 skill 里），HS/RA 是开放式综合
   判断和成因诊断（HS 明确不打分排序，RA 要重建物理机制）。SH/FA 用 Sonnet 5，HS/RA 保持 Opus 5，
   在 caching 基础上再省约 40%。

   **A/B 验证**（4 个目标，配对对照）：3/4 target verdict 完全不变；唯一变化的 1 个（QSO/QSO 简并
   案例）在纯 Opus 5 下 HS/RA 本就意见分裂（`PREFER_H2` vs `INDETERMINATE`），换用 Sonnet 5 后
   两者转为一致的 `INDETERMINATE` —— 是让分裂判决收敛，而非推翻一个确定的正确答案。已知答案的
   flagship 案例（`39628250216924756`，文档标注正确答案 `PREFER_H2`）在两种配置下都给出正确判决。

流水线运行结束会打印每个目标的 token 用量和实际花费（按各 stage 实际使用的模型分别计价，非固定
按 Opus 5 计价）：

```
Tokens: 48 input, 292043 cache-write, 469140 cache-read, 40576 output
Est. cost: $1.94 (vs $3.20 without caching, 39% saved)
```

### 输出结构

```
{OUTPUT_DIR}/{targetid}/
├── cwt_features_A.png              CWT 全局特征 (coadd-A)
├── cwt_features_B.png              CWT 全局特征 (coadd-B)
├── sh_lines_H1.csv                 SH 线表 (H1)
├── sh_lines_H2.csv                 SH 线表 (H2)
├── sh_H1_react.md                  SH ReAct 日志 (H1)
├── sh_H2_react.md                  SH ReAct 日志 (H2)
├── fa_cleaned_H1.png               经 FA 审计的 H1 谱线图
├── fa_cleaned_H2.png               经 FA 审计的 H2 谱线图
├── fa_H1_react.md                  FA ReAct 日志 (H1)
├── fa_H1_verdict.json              FA 审计结果 (H1)
├── fa_H2_react.md                  FA ReAct 日志 (H2)
├── fa_H2_verdict.json              FA 审计结果 (H2)
├── hs_react.md                     HS ReAct 日志
├── hs_verdict.json                 HS 判决 (PREFER_H1 / PREFER_H2 / INDETERMINATE)
├── ra_react.md                     RA ReAct 日志
└── ra_verdict.json                 RA 诊断 (catastrophe_type + 成因叙述)
```

## 依赖

```
numpy, scipy, astropy, specutils, PyWavelets, matplotlib
langchain-core, langchain-openai, langgraph, pydantic
python-dotenv, tiktoken
```

详见 `requirements.txt`。

## 许可

MIT
