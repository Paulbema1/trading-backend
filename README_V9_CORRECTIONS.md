# TradeVision AI v9 — corrections appliquées

## Architecture
- Le Test Lab a été retiré du périmètre et de la source.
- `/signals/analyze` est maintenant en lecture/analyse : il ne déclenche plus de notification.
- L'Auto-Scan backend est la source automatique des signaux et des notifications.
- Les 4 actifs sont scannés indépendamment.
- La déduplication est basée sur une empreinte du signal, pas uniquement sur l'actif.
- Les Timeframes Admin sont persistés côté serveur dans `system_config` et utilisés par le live/Auto-Scan/backtest.

## Scoring
Le scoring déterministe partagé est dans `src/engine/deterministic_scoring.py` et est utilisé par le live et le backtest : SMC 30, TA 25, MTF 20, News 10, Calendrier 5, Momentum 5, Contexte 5.

## Backtest
- Parquet local uniquement pendant un backtest : aucun appel Twelve Data n'est effectué pour télécharger l'historique.
- Le scoring déterministe est partagé avec le live.
- La confirmation MTF future n'est jamais lisible.
- Les règles du simulateur conservateur sont conservées.

## FCM
Le backend envoie de vrais messages FCM. Les tokens invalides sont nettoyés et les envois sont découpés par lots de 500.

## Déploiement
1. Copier `.env.example` vers `.env` et renseigner les vraies variables.
2. Installer `requirements.txt`.
3. Fournir les datasets Parquet historiques dans `data/<ASSET>/<TF>.parquet` pour les backtests.
4. Fournir `data/news.parquet` et `data/calendar.parquet` si le contexte fondamental historique doit être inclus dans le backtest.
