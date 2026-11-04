#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""audit_table.py — 事件影响力评分 v3：自动产出 §6.1 审计表 + 排序榜 + 一致性校验。

模型（详见 references/scoring-rules.md）：
  基线 B = [Σ(维度分 × 权重)] ÷ 5，归一到 0–100
  放大器 F = 命中触发器档位相加（0–15，硬上限）
  总评 T = min(B + F, 100)（软封顶）
  定级：S ≥ 85 / A 70–84 / B 60–69 / C < 60

用法：
  python audit_table.py --input events.json
  python audit_table.py --input events.json --json out.json   # 额外导出 JSON
  python audit_table.py --demo                                  # 用内置 13 事件样例自检

events.json 结构：
{
  "events": [
    { "id": "GPT-6 Astra", "scores": [5,5,4,4,3,4,3], "amplifier": 6, "amp_tags": "T1" }
  ]
}
`scores` 顺序固定：技/范/战/资/治/接/验（对应权重 24/20/17/15/12/7/5）。
"""

import argparse
import json
import math
import sys

# 权重：技/范/战/资/治/接/验 —— 必须 Σ=100
WEIGHTS = [24, 20, 17, 15, 12, 7, 5]
DIM_NAMES = ["技术", "范围", "战略", "资本", "治理", "接纳", "验证"]
MAX_F = 15
SOFT_CAP = 100


def round_half_up(x):
    """标准四舍五入（half-up），避免 Python 内置 round 的银行家舍入歧义。
    本模型 Σ 为整数、Σ/5 末位只可能是 0/2/4/6/8，无 0.5 边界，此函数仅作确定语义。"""
    return int(math.floor(x + 0.5))


def grade_of(t):
    if t >= 85:
        return "S"
    if t >= 70:
        return "A"
    if t >= 60:
        return "B"
    return "C"


def weighted_sum(scores):
    if len(scores) != len(WEIGHTS):
        raise ValueError(f"维度数 {len(scores)} ≠ 7（{DIM_NAMES}）")
    for s in scores:
        if not (0 <= s <= 5):
            raise ValueError(f"维度分 {s} 越界 [0,5]")
    return sum(s * w for s, w in zip(scores, WEIGHTS))


def main():
    ap = argparse.ArgumentParser(description="生成 v3 影响力评分 §6.1 审计表")
    ap.add_argument("--input", help="events.json 路径")
    ap.add_argument("--json", help="额外把结果导出为 JSON")
    ap.add_argument("--demo", action="store_true", help="用内置 13 事件样例自检")
    args = ap.parse_args()

    if args.demo:
        events = DEMO["events"]
        src = "内置 13 事件样例（demo）"
    elif args.input:
        with open(args.input, "r", encoding="utf-8") as f:
            events = json.load(f)["events"]
        src = args.input
    else:
        ap.error("必须提供 --input 或 --demo")
        return 2

    # ---- 全局校验：权重和 = 100 ----
    wsum = sum(WEIGHTS)
    print(f"[校验] 权重和 Σ = {wsum}（须=100）{'✓' if wsum == 100 else '✗ 禁止定级'}")
    if wsum != 100:
        print("权重和 ≠100，终止。先修正 v3 权重再继续。")
        return 1

    rows = []
    warnings = []
    for ev in events:
        eid = ev.get("id", "(未命名)")
        scores = ev["scores"]
        sigma = weighted_sum(scores)
        b_precise = sigma / 5.0
        b_round = round_half_up(b_precise)
        f = ev.get("amplifier", 0)
        if f > MAX_F:
            warnings.append(f"{eid}: F={f} 越上限 +{MAX_F}，请降档")
        f_eff = min(f, MAX_F)
        b_plus_f = b_round + f_eff
        capped = b_plus_f > SOFT_CAP
        t = min(b_plus_f, SOFT_CAP)
        rows.append({
            "id": eid,
            "scores": scores,
            "sigma": sigma,
            "b_precise": round(b_precise, 1),
            "b": b_round,
            "f": f_eff,
            "amp_tags": ev.get("amp_tags", ""),
            "b_plus_f": b_plus_f,
            "capped": capped,
            "t": t,
            "grade": grade_of(t),
        })

    # ---- §6.1 审计表（markdown） ----
    print("\n## §6.1 逐事件归一性审计表")
    print(f"权重：技{WEIGHTS[0]}/范{WEIGHTS[1]}/战{WEIGHTS[2]}/资{WEIGHTS[3]}/治{WEIGHTS[4]}/接{WEIGHTS[5]}/验{WEIGHTS[6]}（Σ={wsum}）")
    print("B = Σ(分×权重) ÷ 5；T = min(B+F,100)；取整=标准四舍五入\n")
    print("| 事件 | 7 维分(技/范/战/资/治/接/验) | 加权和Σ | B(精确) | B(取整) | F | T=B+F | 触发封顶 | T 封顶后 | 定级 |")
    print("|---|---|---|---|---|---|---|---|---|---|")
    for r in rows:
        sc = "/".join(str(x) for x in r["scores"])
        cap = "是" if r["capped"] else "否"
        tshow = f"{r['b_plus_f']}→{r['t']}" if r["capped"] else str(r["t"])
        print(f"| {r['id']} | {sc} | {r['sigma']} | {r['b_precise']} | {r['b']} | +{r['f']} | {r['b_plus_f']} | {cap} | {tshow} | {r['grade']} |")

    # ---- 排序榜（按 T 降序，同分按 B 降序、再按 id 稳定） ----
    ranked = sorted(rows, key=lambda r: (-r["t"], -r["b"], r["id"]))
    print("\n## 排行榜（按总评 T 降序）")
    print("| 新序 | 事件 | B | F | 总评 | 等级 |")
    print("|---|---|---|---|---|---|")
    for i, r in enumerate(ranked, 1):
        print(f"| {i} | {r['id']} | {r['b']} | +{r['f']} | **{r['t']}** | {r['grade']} |")

    # ---- 汇总校验 ----
    max_bf = max(r["b_plus_f"] for r in rows)
    capped_any = any(r["capped"] for r in rows)
    print(f"\n[汇总] 事件数={len(rows)}；最大 B+F={max_bf}；{'已触发 100 软封顶' if capped_any else '未触发 100 软封顶（T=min 仅制度约束）'}")
    if warnings:
        print("[警告]")
        for w in warnings:
            print(f"  - {w}")

    if args.json:
        with open(args.json, "w", encoding="utf-8") as f:
            json.dump({"weight_sum": wsum, "max_b_plus_f": max_bf,
                       "capped_any": capped_any, "rows": rows,
                       "ranking": ranked, "warnings": warnings},
                      f, ensure_ascii=False, indent=2)
        print(f"[输出] 结果已导出 {args.json}")
    print(f"[来源] {src}")
    return 0


# 内置 13 事件样例（= 2026-09 定稿报告 §二，用于 --demo 自检与回归）
DEMO = {"events": [
    {"id": "GPT-6 Astra", "scores": [5, 5, 4, 4, 3, 4, 3], "amplifier": 6, "amp_tags": "T1"},
    {"id": "NVIDIA", "scores": [4, 4, 5, 5, 3, 3, 3], "amplifier": 8, "amp_tags": "T1"},
    {"id": "Anthropic", "scores": [3, 5, 4, 5, 5, 2, 2], "amplifier": 8, "amp_tags": "T3"},
    {"id": "月之暗面", "scores": [4, 4, 5, 5, 2, 4, 3], "amplifier": 6, "amp_tags": "T2"},
    {"id": "微软", "scores": [4, 4, 5, 3, 4, 4, 3], "amplifier": 5, "amp_tags": "T1"},
    {"id": "Meta", "scores": [4, 4, 5, 4, 2, 3, 2], "amplifier": 7, "amp_tags": "T1/T2"},
    {"id": "DevDay+播客", "scores": [4, 4, 4, 3, 3, 4, 2], "amplifier": 6, "amp_tags": "T1"},
    {"id": "Google", "scores": [4, 4, 5, 3, 3, 4, 3], "amplifier": 0, "amp_tags": ""},
    {"id": "UN 安理会", "scores": [2, 5, 4, 2, 5, 3, 1], "amplifier": 8, "amp_tags": "T3"},
    {"id": "中国厂商", "scores": [3, 3, 4, 2, 1, 3, 3], "amplifier": 4, "amp_tags": "T2"},
    {"id": "Apple", "scores": [3, 3, 3, 2, 2, 3, 2], "amplifier": 0, "amp_tags": ""},
    {"id": "Google 太空", "scores": [3, 2, 3, 2, 1, 3, 1], "amplifier": 0, "amp_tags": ""},
    {"id": "Manus/华为", "scores": [2, 2, 3, 3, 1, 3, 2], "amplifier": 0, "amp_tags": ""},
]}


if __name__ == "__main__":
    sys.exit(main())
