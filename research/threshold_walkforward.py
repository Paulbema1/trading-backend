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
MAIN_TF, CONFIRM_TF = "1h", "4h"
THRESHOLDS = [70, 75, 80, 85]
TRAIN_RATIO = 0.7
MIN_TRAIN, MIN_TEST = 30, 15
OUT = Path("research/output")
OUT.mkdir(parents=True, exist_ok=True)


async def ensure(symbol, tf):
    df = historical_data_manager.load_data(symbol, tf)
    if df is not None and len(df) >= 100:
        return True
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


async def main():
    rows = []
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
            train = metrics([t for t, ts in sel if ts <= cut])
            test = metrics([t for t, ts in sel if ts > cut])
            row = {"symbol": symbol, "seuil": th, "train": train, "test": test, "verdict": verdict(train, test)}
            rows.append(row)
            print(f"  seuil {th}: train {train['n']}t PF {train['pf']:.2f} | test {test['n']}t PF {test['pf']:.2f} -> {row['verdict']}", flush=True)

    (OUT / "threshold_walkforward.json").write_text(json.dumps(rows, indent=2, ensure_ascii=False))

    md = ["## Calibrage du seuil (entraînement 70 % / test 30 %)", "",
          "| Actif | Seuil | Train n | Train PF | Test n | Test PF | Test exp (R) | Verdict |",
          "|---|---|---|---|---|---|---|---|"]
    for r in rows:
        md.append(f"| {r['symbol']} | {r['seuil']} | {r['train']['n']} | {r['train']['pf']:.2f} | "
                  f"{r['test']['n']} | {r['test']['pf']:.2f} | {r['test']['exp']:+.2f} | {r['verdict']} |")
    md += ["", "Limites : une seule fenêtre de données (~7 mois), filtrage a posteriori des trades, "
           "pas de validation IA dans le backtest, news/calendrier neutralisés (aucune donnée historique)."]
    text = "\n".join(md)
    (OUT / "threshold_walkforward.md").write_text(text, encoding="utf-8")
    summary = os.getenv("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as f:
            f.write(text + "\n")
    print("\n" + text)


if __name__ == "__main__":
    asyncio.run(main())
