"""
Calibrage du seuil de score avec découpage chronologique entraînement/test.
RECHERCHE UNIQUEMENT : ne modifie aucun fichier de scoring ni de prod.
Approximation : on lance UN backtest par actif au seuil plancher (70) puis on
filtre les trades par score. À vérifier ensuite par un vrai run au seuil retenu.
"""
import asyncio
import json
import os
from pathlib import Path

import pandas as pd

from src.backtest.engine import backtest_engine
from src.backtest.historical_data import historical_data_manager
from src.backtest.results import BacktestResults

SYMBOLS = [s.strip() for s in os.getenv("SYMBOLS", "EUR/USD,GBP/USD,USD/JPY,XAU/USD").split(",") if s.strip()]
VARIANT = os.getenv("VARIANT", "baseline").strip()
if VARIANT in ("ob", "ob_sr"):
    # Expérience SMC v2 : remplace le moteur SMC UNIQUEMENT dans ce process de recherche.
    import src.engine.deterministic_scoring as _ds
    from research.smc_experiment import ExperimentalSMC
    _ds.smc_engine = ExperimentalSMC(VARIANT)
MAIN_TF, CONFIRM_TF = "1h", "4h"
CALENDAR = os.getenv("CALENDAR", "none").strip()
if CALENDAR == "fred":
    # Calendrier économique réel (FRED) : écrit calendar.parquet, lu ensuite par le moteur.
    from research.fred_calendar import build_calendar_parquet
    build_calendar_parquet(historical_data_manager.base_dir)
THRESHOLDS = [70, 75, 80, 85]
TRAIN_RATIO = 0.7
MIN_TRAIN, MIN_TEST = 30, 15
OUT = Path("research/output")
OUT.mkdir(parents=True, exist_ok=True)


async def ensure(symbol, tf):
    df = historical_data_manager.load_data(symbol, tf)
    if df is not None and len(df) >= 100:
        return True
    try:
        from research.neon_store import get_conn, restore_local_parquet
        conn = get_conn()
        if restore_local_parquet(conn, symbol, tf):
            conn.close()
            return True
        conn.close()
    except Exception as e:
        print(f"  (Neon indisponible pour {symbol} {tf} : {e})")
    df = await historical_data_manager.download_historical_range(symbol, tf, outputsize=5000)
    return df is not None


def metrics(trades):
    m = BacktestResults.calculate_metrics(trades, compounding=False)
    return {
        "n": m["closed_trades"],
        "pf": m["profit_factor"],
        "exp": m["expectancy_r"],
        "wr": m["win_rate_pct"],
        "dd": m["max_drawdown_pct"],
    }


def verdict(tr, te):
    if tr["n"] < MIN_TRAIN or te["n"] < MIN_TEST:
        return "échantillon insuffisant"
    if tr["pf"] > 1 and te["pf"] > 1:
        return "robuste"
    return "rejeté"


COSTS = [float(x) for x in os.getenv("COSTS", "0,0.2,0.5,1.0").split(",") if x.strip()]


def apply_cost(trades, cost):
    """Retire un coût aller-retour (spread + slippage, en unités de prix) de chaque trade, en R.
    Distance du stop retrouvée à partir du trade : |sortie - entrée| / |R|."""
    out = []
    for t in trades:
        t2 = dict(t)
        r = float(t["r_multiple"])
        if abs(r) > 0.05:
            risk = abs(float(t["exit_price"]) - float(t["entry_price"])) / abs(r)
            if risk > 0:
                t2["r_multiple"] = r - cost / risk
        out.append(t2)
    return out


DETAIL_TH = float(os.getenv("DETAIL_THRESHOLD", "70"))
DETAIL_COST = float(os.getenv("DETAIL_COST", "0.5"))


def detail_lines(symbol, sel):
    """Gagnants / perdants par année et par sens, au seuil DETAIL_TH, avec coût DETAIL_COST."""
    net = apply_cost([t for t, _ in sel], DETAIL_COST)
    groups = {}
    for (t, ts), tn in zip(sel, net):
        for key in (str(ts.year), "Total " + str(t["action"]), "Total"):
            g = groups.setdefault(key, {"n": 0, "w": 0, "l": 0, "gross": 0.0, "net": 0.0})
            g["n"] += 1
            g["w"] += 1 if t["result"] == "WIN" else 0
            g["l"] += 1 if t["result"] == "LOSS" else 0
            g["gross"] += float(t["r_multiple"])
            g["net"] += float(tn["r_multiple"])
    lines = ["", f"### Détail {symbol} - seuil {DETAIL_TH:g}, coût {DETAIL_COST} (tous les trades, toute la période)", "",
             "| Période | Trades | Gagnants | Perdants | Taux de réussite | R brut total | R net total | Exp. nette (R) |",
             "|---|---|---|---|---|---|---|---|"]
    for key in sorted(groups, key=lambda k: (k.startswith("Total"), k)):
        g = groups[key]
        wr = 100.0 * g["w"] / g["n"] if g["n"] else 0.0
        lines.append(f"| {key} | {g['n']} | {g['w']} | {g['l']} | {wr:.1f} % | {g['gross']:+.1f} | "
                     f"{g['net']:+.1f} | {g['net'] / g['n']:+.2f} |")
    return lines


SIM_START = float(os.getenv("SIM_START", "20"))
SIM_FRACS = [float(x) for x in os.getenv("SIM_FRACS", "0.25,0.05,0.02").split(",") if x.strip()]
SIM_MIN_EQUITY = 5.0  # sous ce montant, on considère le compte "ruiné" (risque de 5 $ impossible)


def _simulate(trades, mode, frac=0.0):
    """trades : liste de (r_net, risk_dist). mode 'frac' = risque = frac x équité (composé) ;
    mode 'lot' = taille fixe d'1 once (0.01 lot), gain en dollars = r_net x distance du stop."""
    eq = peak = low = SIM_START
    maxdd = 0.0
    taken = 0
    for r_net, risk_dist in trades:
        if eq <= 0:
            break
        if mode == "frac":
            eq += frac * eq * r_net
        else:
            if risk_dist is None:
                continue
            eq += risk_dist * r_net
        taken += 1
        peak = max(peak, eq)
        low = min(low, eq)
        maxdd = max(maxdd, (peak - eq) / peak if peak > 0 else 1.0)
    return {"final": max(eq, 0.0), "maxdd": maxdd * 100, "low": max(low, 0.0), "taken": taken}


def sim_lines(symbol, sel):
    net = apply_cost([t for t, _ in sel], DETAIL_COST)
    rows = []
    for (t, ts), tn in zip(sel, net):
        r = float(t["r_multiple"])
        rd = abs(float(t["exit_price"]) - float(t["entry_price"])) / abs(r) if abs(r) > 0.05 else None
        rows.append((ts, float(tn["r_multiple"]), rd))
    if not rows:
        return []
    strategies = [(f"Risque {f * 100:g} % de l'équité (composé)", "frac", f) for f in SIM_FRACS]
    strategies.append(("Taille minimale fixe (1 once = 0.01 lot)", "lot", 0.0))
    lines = ["", f"### Simulation compte démo {SIM_START:g} $ - {symbol}, seuil {DETAIL_TH:g}, coût {DETAIL_COST}", "",
             "Départ à " + f"{SIM_START:g} $. Sur toute la période :", "",
             "| Méthode | Trades pris | Équité finale | Pire creux | Drawdown max |", "|---|---|---|---|---|"]
    for name, mode, f in strategies:
        s = _simulate([(r, rd) for _, r, rd in rows], mode, f)
        lines.append(f"| {name} | {s['taken']} | {s['final']:.2f} $ | {s['low']:.2f} $ | {s['maxdd']:.0f} % |")
    first, last = rows[0][0], rows[-1][0]
    for months in (3, 12):
        starts = []
        cur = first.normalize()
        while cur + pd.DateOffset(months=months) <= last + pd.Timedelta(days=1):
            starts.append(cur)
            cur = cur + pd.DateOffset(months=1)
        if not starts:
            continue
        lines += ["", f"Fenêtres glissantes de {months} mois ({len(starts)} départs différents, chacun repart de {SIM_START:g} $) :", "",
                  f"| Méthode | Finissent au-dessus de {SIM_START:g} $ | Équité finale médiane | Pire fenêtre | Ruinés (< {SIM_MIN_EQUITY:g} $ à un moment) |",
                  "|---|---|---|---|---|"]
        for name, mode, f in strategies:
            finals, ruined = [], 0
            for st in starts:
                en = st + pd.DateOffset(months=months)
                s = _simulate([(r, rd) for ts, r, rd in rows if st <= ts < en], mode, f)
                finals.append(s["final"])
                ruined += 1 if s["low"] < SIM_MIN_EQUITY else 0
            finals.sort()
            up = 100.0 * sum(1 for x in finals if x > SIM_START) / len(finals)
            lines.append(f"| {name} | {up:.0f} % | {finals[len(finals) // 2]:.2f} $ | {finals[0]:.2f} $ | "
                         f"{100.0 * ruined / len(starts):.0f} % |")
    return lines


async def main():
    rows = []
    cost_rows = []
    detail_sels = []
    for symbol in SYMBOLS:
        print(f"=== {symbol} ===", flush=True)
        if not (await ensure(symbol, MAIN_TF) and await ensure(symbol, CONFIRM_TF)):
            print(f"  téléchargement impossible pour {symbol}, actif ignoré", flush=True)
            continue
        res = await backtest_engine.run_backtest(symbol, MAIN_TF, CONFIRM_TF, min_confidence=70)
        if "error" in res:
            print(f"  erreur : {res['error']}", flush=True)
            continue
        trades = res["trades"]
        times = pd.to_datetime([t["entry_time"] for t in trades])
        cut = times.min() + (times.max() - times.min()) * TRAIN_RATIO
        for th in THRESHOLDS:
            sel = [(t, ts) for t, ts in zip(trades, times) if t["score"] >= th]
            if th == DETAIL_TH:
                detail_sels.append((symbol, sel))
            train = metrics([t for t, ts in sel if ts <= cut])
            test = metrics([t for t, ts in sel if ts > cut])
            row = {"symbol": symbol, "seuil": th, "train": train, "test": test, "verdict": verdict(train, test)}
            rows.append(row)
            print(f"  seuil {th}: train {train['n']}t PF {train['pf']:.2f} | test {test['n']}t PF {test['pf']:.2f} -> {row['verdict']}", flush=True)
            for cst in COSTS:
                cost_rows.append({
                    "symbol": symbol, "seuil": th, "cout": cst,
                    "train": metrics(apply_cost([t for t, ts in sel if ts <= cut], cst)),
                    "test": metrics(apply_cost([t for t, ts in sel if ts > cut], cst)),
                })

    (OUT / f"threshold_walkforward_{VARIANT}_{CALENDAR}.json").write_text(json.dumps(rows, indent=2, ensure_ascii=False))

    md = [f"## Calibrage du seuil (entraînement 70 % / test 30 %) - variante : {VARIANT} / calendrier : {CALENDAR}", "",
          "| Actif | Seuil | Train n | Train PF | Test n | Test PF | Test exp (R) | Verdict |",
          "|---|---|---|---|---|---|---|---|"]
    for r in rows:
        md.append(f"| {r['symbol']} | {r['seuil']} | {r['train']['n']} | {r['train']['pf']:.2f} | "
                  f"{r['test']['n']} | {r['test']['pf']:.2f} | {r['test']['exp']:+.2f} | {r['verdict']} |")
    for _sym, _sel in detail_sels:
        md += detail_lines(_sym, _sel)
        md += sim_lines(_sym, _sel)
    if cost_rows:
        md += ["", "### Impact des coûts (aller-retour par trade, en unités de prix)", "",
               "| Actif | Seuil | Coût | Train PF | Train exp (R) | Test n | Test PF | Test exp (R) |",
               "|---|---|---|---|---|---|---|---|"]
        for r in cost_rows:
            md.append(f"| {r['symbol']} | {r['seuil']} | {r['cout']} | {r['train']['pf']:.2f} | "
                      f"{r['train']['exp']:+.2f} | {r['test']['n']} | {r['test']['pf']:.2f} | {r['test']['exp']:+.2f} |")
    md += ["", "Limites : une seule fenêtre de données (~7 mois), filtrage a posteriori des trades, "
           "pas de validation IA dans le backtest, news/calendrier neutralisés (aucune donnée historique)."]
    text = "\n".join(md)
    (OUT / f"threshold_walkforward_{VARIANT}_{CALENDAR}.md").write_text(text, encoding="utf-8")
    summary = os.getenv("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as f:
            f.write(text + "\n")
    print("\n" + text)


if __name__ == "__main__":
    asyncio.run(main())
