# Kronos 权重获取与验证指南

> 适用场景：在受限网络（如沙箱、企业内网、校园网）中，HF xet CDN 被拦截导致
> `from_pretrained("NeoQuasar/Kronos-*")` 拉不到权重。本文给出**已实测有效**的双源方案。

## 1. 结论速览

| 问题 | 答案 |
|------|------|
| Kronos 需要自己训练吗？ | ❌ 不需要，公开预训练权重 |
| GitHub 上有权重吗？ | ❌ 没有，GitHub 只托管代码 |
| 权重在哪儿？ | HuggingFace Hub `NeoQuasar/Kronos-*` |
| 为什么沙箱拉不到？ | HF xet CDN (`cas-bridge.xethub.hf.co`) 被网络白名单拦截 |
| 国内镜像能下吗？ | ✅ **base 经 hf-mirror.com / huggingface.co 可下；small 额外可走 Gitee AI（Gitee 仅镜像 small）** |

## 2. 国内 5 大镜像站实测（2026-07-09）

| 镜像站 | 模型 small | 分词器 | 可下权重？ | 方式 |
|--------|:---:|:---:|:---:|------|
| **Gitee AI** `hf-api.gitee.com` | ✅ | ❌ | **✅ 模型** | curl 直连 |
| **GitCode AI** `gitcode.com` | ✅ | ✅ | **✅ 分词器** | git clone 匿名 |
| hf-mirror.com | ✅元数据 | ✅元数据 | ⚠️ 权重走 xet 被拦 | — |
| ModelScope 魔塔 | ❌404 | ❌404 | 无 | — |
| WiseModel 始智 | ✅ | 未测 | 需登录 | — |

**关键发现**：Gitee AI 的 `hf-api.gitee.com` 是 HF 兼容 API 端点，可 curl 直连下载
`model.safetensors`（绕过 xet CDN）；GitCode AI 的 Kronos 仓库可**匿名 git clone**
（含分词器权重）。**但 Gitee AI 仅镜像 `Kronos-small`**（`-base`/`-mini`/`-large` 均 404）。

> **模型尺寸与端点（2026-07-10 起平台默认 `Kronos-base`）**
> - `Kronos-small`：Gitee AI（`hf-api.gitee.com`）已验证可下，绕过 xet CDN。
> - `Kronos-base` / `-mini`：Gitee AI 未镜像，**需走 hf-mirror.com / huggingface.co**（完整镜像 HF 官方全量权重）；base 权重约 102MB。
> - 分词器 `Kronos-Tokenizer-base`：base/small 共用，恒走 hf-mirror.com（Gitee 未镜像）。
> - 适配器按模型尺寸**自动选择端点**，无需手动指定；也可用 `KRONOS_MODEL_ENDPOINT` 覆盖。

## 3. 一键获取

### 3.1 默认 base（推荐，需 hf-mirror / HF 官方可达）

```bash
cd /workspace/quant-platform
python download_kronos_weights.py --repo NeoQuasar/Kronos-base --out ./kronos_weights
export KRONOS_LOCAL_DIR=$(pwd)/kronos_weights
```

走 `hf-mirror.com` 完整镜像，把 base + 分词器整仓快照下载到本地（离线搬运用）。

### 3.2 受限网络（仅 Gitee AI 可达）→ small 兜底

```bash
cd /workspace/quant-platform
python fetch_kronos_weights.py --out ./kronos_weights       # 仅 Kronos-small（Gitee + GitCode 双源）
export KRONOS_LOCAL_DIR=$(pwd)/kronos_weights
export KRONOS_MODEL_REPO=NeoQuasar/Kronos-small             # 与落地权重一致
```

`fetch_kronos_weights.py` 逻辑（small 专用）：
- 模型 `NeoQuasar/Kronos-small` → 从 `https://hf-api.gitee.com/.../resolve/main/` curl 下载
- 分词器 `NeoQuasar/Kronos-Tokenizer-base` → 从 `https://gitcode.com/hf_mirrors/...` git clone
- 输出目录结构适配 `KRONOS_LOCAL_DIR` 约定（`/` → `--`）

## 4. 沙箱已完成的验证

**权重文件**（位于 `_local_kronos_weights/`）：

```
NeoQuasar--Kronos-small/model.safetensors         95 MB  (136 tensors)
NeoQuasar--Kronos-Tokenizer-base/model.safetensors 15.1 MB (96 tensors)
```

**真实推理验证**（用真实 A 股行情，196 根日K）：

| 股票 | 预测(5日) | 置信区间 |
|------|----------|---------|
| 600519 贵州茅台 | +3.19% | [-3.58%, +9.95%] |
| 000858 五粮液 | +7.99% | [+1.81%, +14.17%] |
| 601318 中国平安 | +2.22% | [-10.05%, +14.49%] |

全链路：适配器 → 本地权重加载 → Tokenizer → 模型 → 自回归预测 → 逆归一化 → 收益预测 ✅

> 注：以上为沙箱以 `Kronos-small` 完成的真实推理验证（small 是沙箱唯一可拉到的尺寸）。
> 平台现已默认 `Kronos-base`；若你想在沙箱复现，设 `KRONOS_MODEL_REPO=NeoQuasar/Kronos-small`
> 即可直接使用上述已落地的 small 权重。在具备完整外网的本地电脑上，base 可正常拉取。

## 5. 在你的机器上跑

```bash
cd /workspace/quant-platform
bash bootstrap_kronos.sh                  # 拉官方推理代码到 _vendor/Kronos + 默认下载 base 权重
python download_kronos_weights.py --repo NeoQuasar/Kronos-base --out ./kronos_weights  # base 权重（hf-mirror）   # 双源���载权重
export KRONOS_LOCAL_DIR=$(pwd)/kronos_weights
python _run_real.py                       # 完整真实预测（含 Kronos 第4源）
```

若你的网络**直连 HF 正常**（多数家庭/云主机可直连 xet CDN），可省略权重下载，
适配器按模型尺寸自动选端点（base → hf-mirror.com / huggingface.co）在线加载。

## 6. 环境变量参考

| 变量 | 用途 | 默认 |
|------|------|------|
| `KRONOS_LOCAL_DIR` | 本地权重目录（最高优先级） | 未设 |
| `KRONOS_HF_ENDPOINT` | 全局 HF 端点 | 按尺寸自动（small→Gitee / 其他→hf-mirror） |
| `KRONOS_MODEL_ENDPOINT` | 仅模型端点 | 同上（按尺寸自动） |
| `KRONOS_TOK_ENDPOINT` | 仅分词器端点 | `https://hf-mirror.com` |
| `KRONOS_MODEL_REPO` | 覆盖模型尺寸（mini/small/base） | `NeoQuasar/Kronos-base` |
| `KRONOS_TOK_REPO` | 覆盖分词器 id | `NeoQuasar/Kronos-Tokenizer-base` |
| `KRONOS_REPO_PATH` | 官方推理代码路径 | `_vendor/Kronos` |

## 7. 已知限制

- 平台默认 `Kronos-base`（约 102MB）；`Kronos-small`（约 25MB）是其轻量版。base 需 hf-mirror / HF 官方可达。
- Gitee AI 仅镜像 `Kronos-small`（无 `-base`/`-mini`）；受限网络只有 Gitee 可达时自动回退 small。
- GitCode AI 需 `git clone`（匿名可用），不支持纯浏览器单文件下载。
- 权重文件较大（base 102MB + 分词器 15MB），首次下载需稳定网络。
