#!/usr/bin/env bash
# Kronos 300x5 评估：监控分片进度 -> 全部完成后自动合并 -> 写最终报告
set -u
cd /workspace/quant-platform
LOG=_eval_monitor.log
REPORT=_eval_final_report.txt
N_SHARDS=8
echo "[$(date '+%F %T')] 监控启动 (n_shards=$N_SHARDS)" | tee -a "$LOG"

while true; do
  alive=$(pgrep -f "_eval_kronos_shard.py" | wc -l)
  total_pairs=0
  for k in $(seq 0 $((N_SHARDS-1))); do
    f=_kronos_eval_ckpt_kronos_e5_s0_part$k.json
    [ -f "$f" ] && total_pairs=$((total_pairs + $(python3 -c "import json;print(len(json.load(open('$f')).get('pairs',[])))" 2>/dev/null || echo 0)))
  done
  done_stocks=$((total_pairs / 15))
  echo "[$(date '+%F %T')] alive_procs=$alive total_pairs=$total_pairs done_stocks=$done_stocks/300" | tee -a "$LOG"
  if [ "$alive" -eq 0 ]; then
    echo "[$(date '+%F %T')] 所有分片进程已退出，开始合并" | tee -a "$LOG"
    break
  fi
  sleep 60
done

# 合并
echo "[$(date '+%F %T')] 运行合并..." | tee -a "$LOG"
python3 _eval_kronos_shard.py --merge --n-shards $N_SHARDS 2>&1 | tee -a "$LOG"

# 最终稳健复核：从合并后的主 checkpoint 重算 总 + 分周期 dir_acc
echo "[$(date '+%F %T')] 生成最终报告..." | tee -a "$LOG"
python3 - <<'PY' | tee -a "$REPORT"
import json, numpy as np
d=json.load(open('_kronos_eval_ckpt_kronos_e5_s0.json'))
pairs=d.get('pairs',[])
print(f"合并总样本对: {len(pairs)}")
valid=[(dd,a) for dd,a in pairs if a!=0]
acc=np.mean([1 if dd==a else 0 for dd,a in valid])
print(f"有效(非平盘)样本: {len(valid)}")
print(f"总 dir_acc = {acc:.4f}")
# 分周期（15对/股, [H1x5,H5x5,H10x5]）
per={"H1":[],"H5":[],"H10":[]}
assert len(pairs)%15==0, f"pairs 非15倍数: {len(pairs)}"
for i in range(0,len(pairs),15):
    blk=pairs[i:i+15]
    for j,h in enumerate(["H1","H5","H10"]):
        seg=blk[j*5:(j+1)*5]
        v=[(dd,a) for dd,a in seg if a!=0]
        if v:
            per[h].append(np.mean([1 if dd==a else 0 for dd,a in v]))
for h in ["H1","H5","H10"]:
    arr=per[h]
    a=np.mean(arr) if arr else float('nan')
    print(f"  {h} dir_acc = {a:.4f}  (覆盖股票 {len(arr)} 只)")
base=0.4
def w(acc):
    return base*max(0,(acc-0.5)*2) if acc>=0.52 else 0.0
print("融合权重建议(base=%.2f):"%base)
print(f"  总权重 = {w(acc):.4f}")
for h in ["H1","H5","H10"]:
    arr=per[h]; a=np.mean(arr) if arr else 0
    print(f"  {h}权重 = {w(a):.4f}")
PY
echo "[$(date '+%F %T')] 完成" | tee -a "$LOG"
