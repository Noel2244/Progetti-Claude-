"""Backtest reports (Markdown, JSON, CSV, HTML).

Sections are labelled so that a reader always knows what kind of statement
they are reading: FACT, MODEL OUTPUT, MARKET DATA, ESTIMATE, UNCERTAINTY,
INTERPRETATION. Interpretations are generated conservatively from confidence
intervals - a result whose interval includes "no difference" is reported as
"no evidence", never as a win.
"""

from __future__ import annotations

import html
import json
from pathlib import Path

import pandas as pd

from sports_engine.backtesting.walkforward import BacktestResult


def interpret(result: BacktestResult) -> list[str]:
    out: list[str] = []
    comps = result.comparisons
    models = sorted({k.split(":")[0] for k in result.metrics if not k.startswith("_")})
    for m in models:
        if m in ("climatology", "market"):
            continue
        c = comps.get(f"{m}_vs_climatology")
        if c:
            if c["ci_high"] < 0:
                out.append(f"{m}: beats the league base-rate baseline (log-loss diff {c['mean_diff']:+.4f}, 95% CI [{c['ci_low']:+.4f}, {c['ci_high']:+.4f}]).")
            else:
                out.append(f"{m}: NO evidence it beats the league base rates (CI [{c['ci_low']:+.4f}, {c['ci_high']:+.4f}] includes 0).")
        mk = comps.get(f"{m}_vs_market")
        if mk:
            if mk["ci_high"] < 0:
                out.append(f"{m}: beats the market consensus out-of-sample (CI [{mk['ci_low']:+.4f}, {mk['ci_high']:+.4f}]) - requires confirmation on untouched data before any trust.")
            elif mk["ci_low"] > 0:
                out.append(f"{m}: the market is significantly better (CI [{mk['ci_low']:+.4f}, {mk['ci_high']:+.4f}]). The model does not add information beyond the market.")
            else:
                out.append(f"{m}: not distinguishable from the market (CI [{mk['ci_low']:+.4f}, {mk['ci_high']:+.4f}]).")
    if not any(k.endswith("_vs_market") for k in comps):
        out.append("MARKET BENCHMARK UNAVAILABLE: the data used contains no odds for this window, so it is impossible to say whether any model adds information beyond the market. No betting conclusion can be drawn.")
    for m in models:
        raw, cal = result.metrics.get(f"{m}:raw"), result.metrics.get(f"{m}:calibrated")
        if raw and cal:
            d = cal["log_loss"] - raw["log_loss"]
            if d > 0.0005:
                out.append(f"{m}: sequential calibration made out-of-sample log loss WORSE by {d:.4f}; the raw probabilities are preferable for this model.")
            elif d < -0.0005:
                out.append(f"{m}: sequential calibration improved out-of-sample log loss by {-d:.4f}.")
    b = result.betting
    if b.get("available") and b.get("bets"):
        lo, hi = b["yield_ci95"]
        if lo > 0:
            out.append(f"Paper betting: yield {b['yield']:+.1%} with 95% CI [{lo:+.1%}, {hi:+.1%}] over {b['bets']} bets. Positive, but historical ROI is NOT proof of predictive validity; check CLV and out-of-sample stability.")
        else:
            out.append(f"Paper betting: {b['bets']} bets, yield {b['yield']:+.1%}, 95% CI [{lo:+.1%}, {hi:+.1%}] includes zero -> no evidence of an edge.")
        if b.get("mean_clv_fair") is not None:
            out.append(f"Mean fair CLV {b['mean_clv_fair']:+.2%} (EV of the taken prices at the fair closing probability).")
    elif b.get("available"):
        out.append("The abstention engine produced no bets in this window: 'NO BET' throughout.")
    return out


def _fmt(x, nd=4):
    return "-" if x is None or (isinstance(x, float) and pd.isna(x)) else (f"{x:.{nd}f}" if isinstance(x, float) else str(x))


def to_markdown(result: BacktestResult, meta: dict) -> str:
    L = []
    L.append(f"# Backtest report `{meta.get('run_id', '')}`\n")
    L.append("> Research output of a personal analytics engine. Paper mode only. Not betting advice. "
             "Historical performance does not guarantee anything.\n")
    L.append("## FACT - data and setup\n")
    cfg = result.config
    L.append(f"- Competitions: {', '.join(cfg['competitions'])}")
    L.append(f"- Test window: {cfg['test_start']} -> {cfg['test_end']}  (burn-in for calibration from {cfg.get('burn_in_start')})")
    L.append(f"- Final holdout starts: {cfg.get('holdout_start')} (used: {cfg.get('use_holdout')})")
    L.append(f"- Dataset fingerprint: `{meta.get('dataset_fingerprint')}` | code: `{meta.get('code_version')}` | experiment: `{meta.get('experiment_id')}`")
    L.append(f"- Sources: {meta.get('sources', 'n/a')}")
    cov = result.metrics.get("_coverage", {})
    L.append(f"- Fixtures evaluated: {cov.get('fixtures_scheduled')} | predictions per model: {cov.get('predictions_per_model')}")
    L.append(f"- Decision-time policies: {cov.get('decision_policies')}")
    L.append(f"- Runtime: {result.runtime_seconds}s")
    for n in result.notes:
        L.append(f"- NOTE: {n}")
    L.append("\n## MODEL OUTPUT - probability quality (out-of-sample, walk-forward)\n")
    L.append("| model | probs | n | log loss | Brier | RPS | mean ECE | slope H | slope D | slope A |")
    L.append("|---|---|---:|---:|---:|---:|---:|---:|---:|---:|")
    for k, v in sorted(result.metrics.items()):
        if k.startswith("_"):
            continue
        m, lab = k.split(":")
        cl = v["classes"]
        L.append(f"| {m} | {lab} | {v['n']} | {v['log_loss']:.4f} | {v['brier']:.4f} | {v.get('rps', float('nan')):.4f} | "
                 f"{v['ece_mean']:.4f} | {cl['H']['slope']:.2f} | {cl['D']['slope']:.2f} | {cl['A']['slope']:.2f} |")
    L.append("\nLower is better for log loss / Brier / RPS / ECE; calibration slope 1.0 is ideal.\n")
    L.append("## UNCERTAINTY - paired comparisons (log loss, block bootstrap by week)\n")
    L.append("| comparison | mean diff | 95% CI | P(first better) | n |")
    L.append("|---|---:|---|---:|---:|")
    for k, c in sorted(result.comparisons.items()):
        L.append(f"| {k} | {c['mean_diff']:+.4f} | [{c['ci_low']:+.4f}, {c['ci_high']:+.4f}] | {c['p_a_better']:.2f} | {c['n']} |")
    L.append("\nNegative mean diff = first model has lower log loss.\n")
    if not result.per_season.empty:
        L.append("## MODEL OUTPUT - per season (calibrated probabilities, log loss)\n")
        pv = result.per_season.pivot_table(index="season", columns="model", values="log_loss")
        L.append("| season | " + " | ".join(pv.columns) + " |")
        L.append("|---|" + "---:|" * len(pv.columns))
        for s, row in pv.iterrows():
            L.append(f"| {s} | " + " | ".join(_fmt(x) for x in row.values) + " |")
        L.append("")
    L.append("## ESTIMATE - calibration choices (selected on earlier out-of-sample seasons only)\n")
    for m, seasons in result.calibration.items():
        methods = {}
        for s, d in seasons.items():
            methods[d["method"]] = methods.get(d["method"], 0) + 1
        L.append(f"- {m}: {methods}")
    L.append("\n## MARKET DATA - paper betting simulation\n")
    b = result.betting
    if not b.get("available"):
        L.append(f"- Not available: {b.get('reason')}")
    else:
        L.append(f"- Selections evaluated: {b['selections_evaluated']} | status counts: {b['status_counts']}")
        L.append(f"- NO BET reasons (count): {b['no_bet_reasons']}")
        if b.get("bets"):
            L.append(f"- Bets: {b['bets']} (W {b['wins']} / L {b['losses']}) | staked {b['staked_units']:.1f}u | P/L {b['profit_units']:+.2f}u | "
                     f"yield {b['yield']:+.2%} (95% CI {b['yield_ci95'][0]:+.1%} .. {b['yield_ci95'][1]:+.1%})")
            L.append(f"- Max drawdown {b['max_drawdown_units']:.2f}u | mean odds {b['mean_odds']:.2f} | hit rate {b['hit_rate']:.1%} vs model-expected {b['expected_hit_rate']:.1%}")
            L.append(f"- CLV: mean price-CLV {_fmt(b.get('mean_clv_price'))}, mean fair-CLV {_fmt(b.get('mean_clv_fair'))}, share beating close {_fmt(b.get('share_beating_close'))}")
    L.append("\n## INTERPRETATION (conservative, generated from the intervals above)\n")
    for s in interpret(result):
        L.append(f"- {s}")
    L.append("\n---\nA losing prediction does not mean the model was wrong; a profitable backtest does not mean it is valid. "
             "Model quality (calibration, log loss) and decision performance (CLV, P/L) are reported separately on purpose.\n")
    return "\n".join(L)


def write_backtest_report(result: BacktestResult, out_dir: Path, meta: dict) -> dict[str, str]:
    out_dir.mkdir(parents=True, exist_ok=True)
    md = to_markdown(result, meta)
    (out_dir / "report.md").write_text(md, encoding="utf-8")
    payload = {"meta": meta, "config": result.config, "metrics": result.metrics, "comparisons": result.comparisons,
               "calibration": result.calibration, "betting": result.betting, "notes": result.notes,
               "interpretation": interpret(result), "runtime_seconds": result.runtime_seconds}
    (out_dir / "report.json").write_text(json.dumps(payload, indent=1, default=str), encoding="utf-8")
    cols = [c for c in result.predictions.columns if c not in ("ll",)]
    result.predictions[cols].to_csv(out_dir / "predictions.csv", index=False)
    result.per_season.to_csv(out_dir / "per_season.csv", index=False)
    if not result.bets.empty:
        result.bets.to_csv(out_dir / "bets.csv", index=False)
    (out_dir / "report.html").write_text(markdown_to_html(md, f"Backtest {meta.get('run_id', '')}"), encoding="utf-8")
    return {"markdown": str(out_dir / "report.md"), "json": str(out_dir / "report.json"), "html": str(out_dir / "report.html")}


def markdown_to_html(md: str, title: str) -> str:
    """Tiny, dependency-free Markdown -> HTML (headings, lists, tables, code)."""
    lines, out, in_table, in_list = md.splitlines(), [], False, False
    for ln in lines:
        esc = html.escape(ln)
        esc = __import__("re").sub(r"`([^`]+)`", r"<code>\1</code>", esc)
        if ln.startswith("|"):
            cells = [c.strip() for c in ln.strip("|").split("|")]
            if all(set(c) <= set("-:") for c in cells):
                continue
            if not in_table:
                out.append("<table>")
                in_table = True
                out.append("<tr>" + "".join(f"<th>{html.escape(c)}</th>" for c in cells) + "</tr>")
            else:
                out.append("<tr>" + "".join(f"<td>{html.escape(c)}</td>" for c in cells) + "</tr>")
            continue
        if in_table:
            out.append("</table>")
            in_table = False
        if ln.startswith("- "):
            if not in_list:
                out.append("<ul>")
                in_list = True
            out.append(f"<li>{esc[2:]}</li>")
            continue
        if in_list:
            out.append("</ul>")
            in_list = False
        if ln.startswith("#"):
            level = len(ln) - len(ln.lstrip("#"))
            out.append(f"<h{level}>{esc[level:].strip()}</h{level}>")
        elif ln.startswith(">"):
            out.append(f"<blockquote>{esc[4:]}</blockquote>")
        elif ln.strip() == "---":
            out.append("<hr>")
        elif ln.strip():
            out.append(f"<p>{esc}</p>")
    if in_table:
        out.append("</table>")
    if in_list:
        out.append("</ul>")
    css = ("body{font-family:system-ui,sans-serif;max-width:1100px;margin:2rem auto;padding:0 1rem;color:#1b1f24;background:#fff}"
           "table{border-collapse:collapse;margin:1rem 0;font-size:.9rem}td,th{border:1px solid #d0d7de;padding:4px 8px;text-align:right}"
           "th{background:#f6f8fa}td:first-child,th:first-child{text-align:left}code{background:#f6f8fa;padding:0 4px}"
           "blockquote{border-left:4px solid #d0d7de;margin:0;padding:0 1rem;color:#57606a}"
           "@media (prefers-color-scheme: dark){body{background:#0d1117;color:#e6edf3}th,code{background:#161b22}td,th{border-color:#30363d}}")
    return f"<!doctype html><html><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'><title>{html.escape(title)}</title><style>{css}</style></head><body>{''.join(out)}</body></html>"
