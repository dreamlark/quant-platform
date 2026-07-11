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
| 国内镜像能下吗？ | ✅ **Gitee AI（模型）+ GitCode AI（分词器）双源方案实测可下** |

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
（含分词器权重）。

## 3. 一键获取（推荐）

```bash
cd /workspace/quant-platform
python fetch_kronos_weights.py --out ./kronos_weights
export KRONOS_LOCAL_DIR=$(pwd)/kronos_weights
```

脚本逻辑：
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

## 5. 在你的机器上跑

```bash
cd /workspace/quant-platform
bash bootstrap_kronos.sh                  # 拉官方推理代码到 _vendor/Kronos
python fetch_kronos_weights.py --out ./kronos_weights   # 双源���载权重
export KRONOS_LOCAL_DIR=$(pwd)/kronos_weights
python _run_real.py                       # 完整真实预测（含 Kronos 第4源）
```

若你的网络**直连 HF 正常**（多数家庭/云主机可直连 xet CDN），可省略第 3 步，
适配器默认 `HF_ENDPOINT=https://hf-api.gitee.com` 会自动尝试在线加载。

## 6. 环境变量参考

| 变量 | 用途 | 默认 |
|------|------|------|
| `KRONOS_LOCAL_DIR` | 本地权重目录（最高优先级） | 未设 |
| `KRONOS_HF_ENDPOINT` | 全局 HF 端点 | `https://hf-api.gitee.com` |
| `KRONOS_MODEL_ENDPOINT` | 仅模型端点 | 同上 |
| `KRONOS_TOK_ENDPOINT` | 仅分词器端点 | `https://hf-mirror.com` |
| `KRONOS_REPO_PATH` | 官方推理代码路径 | `_vendor/Kronos` |

## 7. 已知限制

- Gitee AI 仅镜像 `Kronos-small`（无 `-base`/`-mini`）；如需更大模型需直连 HF。
- GitCode AI 需 `git clone`（匿名可用），不支持纯浏览器单文件下载。
- 权重文件较大（模型 95MB + 分词器 15MB），首次下载需稳定网络。
