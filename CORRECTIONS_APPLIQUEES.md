# TradeVision AI v9.1.0 — Rapport de corrections (AUDIT → 🟢)

Ce document liste chaque problème identifié lors de l'audit et la correction
appliquée. **Aucune règle de scoring, de hiérarchie de garde-fous, ou de
formule métier n'a été modifiée** — toutes les corrections portent sur la
sécurité, la configuration, l'orchestration, la compilation et les tests.

---

## 🔴 CRITIQUE → 🟢 Résolu

| ID | Correction appliquée | Fichier(s) |
|---|---|---|
| C-01 | Suppression du défaut JWT_SECRET codé en dur ; fail-fast en production si absent | `src/core/config.py`, `src/main.py` |
| C-02 | `registerDummyFcmToken()` remplacé par `registerRealFcmToken()` utilisant le vrai token Firebase (`FirebaseMessaging.getInstance().token`) | `MainActivity.kt` |
| C-03 | Suppression complète de la boucle de polling 15s (`startBackgroundMonitor`) | `MainActivity.kt` |
| C-04 | Clés du payload FCM alignées entre backend et mobile (`entry_price`, `stop_loss`, `take_profit_1/2/3`, `signal_id`) | `src/services/notifications.py` |
| C-05 | Dépendances Firebase Messaging + AndroidX Security ajoutées ; plugin `google-services` configuré ; `google-services.json` placeholder documenté | `build.gradle.kts` (racine + app), `README_FIREBASE_MOBILE.md` |
| C-06 | Anti-stacking implémenté : nouveau modèle `OpenPosition`, vérifié avant chaque dispatch (bloque doublon même direction, autorise retournement) | `src/models/position.py`, `src/services/signal_dispatch.py` |
| C-07 | `.gitignore` + `.env.example` créés ; `.env` retiré du dépôt | racine backend |
| — (détecté en cours de correction) | `FCMService` n'était pas déclaré dans le Manifest → notifications physiquement impossibles à recevoir | `AndroidManifest.xml` |

## 🟠 HAUTE → 🟢 Résolu

| ID | Correction appliquée | Fichier(s) |
|---|---|---|
| H-01 | `TWELVE_DATA_COOLDOWN_SECONDS` / `EXHAUSTED_SECONDS` configurables via env, bornés [60,300] | `src/core/config.py`, `src/services/request_manager.py` |
| H-02 | Tests P0 manquants ajoutés : POOR→WAIT, score 69/70, MTF ouverte/clôturée, no-look-ahead backtest, all-keys-cooldown, anti-stacking | `tests/test_p0_guards.py`, `tests/test_backtest_lookahead.py`, `tests/test_anti_stacking.py`, `tests/test_request_manager.py` |
| H-03 | `test_cache.py` et `test_smc.py` remplis (étaient vides) | `tests/test_cache.py`, `tests/test_smc.py` |
| H-04 | `signal_id` (UUID) généré côté backend, propagé au schéma, au modèle DB, à l'API et au FCM | `src/engine/signal_engine.py`, `src/schemas/signal.py`, `src/models/signal.py`, mobile `Models.kt` |
| H-05 | `android:usesCleartextTraffic` passé à `false` | `AndroidManifest.xml` |
| H-06 | Tests réels ajoutés : chiffrement JWT, logout, déduplication signal_id, notification avec actions | `SessionManagerInstrumentedTest.kt`, `NotificationHelperInstrumentedTest.kt`, `PriceFormatterUnitTest.kt` |
| H-07 | Actions de notification "Ouvrir le signal" / "Copier les niveaux" ajoutées (+ `CopyLevelsReceiver`) | `NotificationHelper.kt`, `receivers/CopyLevelsReceiver.kt`, `AndroidManifest.xml` |

## 🟡 MOYENNE → 🟢 Résolu

| ID | Correction appliquée | Fichier(s) |
|---|---|---|
| M-01 | Méthode `is_ready()` dupliquée (stub mort) supprimée | `src/services/request_manager.py` |
| M-02 | `TWELVE_DATA_BASE_URL` rendu configurable via env | `src/core/config.py` |
| M-03 | `main_tf`/`confirm_tf` désormais réellement pris en compte par `/signals/analyze/{symbol}` | `src/api/v2/signals.py` |
| M-04 | `rate_limit.py` documenté (placeholder volontaire, non une fonctionnalité oubliée) | `src/utils/rate_limit.py` |
| M-05 | `android:allowBackup` passé à `false` | `AndroidManifest.xml` |
| M-06 | CI exécute désormais les tests unitaires + lint avant le build | `.github/workflows/build_apk.yml` |
| M-07 | `pytest`, `pytest-cov`, `pytest-asyncio` ajoutés aux dépendances | `requirements.txt`, `pytest.ini` |

## 🔵 FAIBLE → 🟢 Résolu

| ID | Correction appliquée | Fichier(s) |
|---|---|---|
| F-01 | `CORS_ORIGINS` configurable via env (reste `*` par défaut en dev) | `src/core/config.py`, `src/main.py` |
| F-02 | `BASE_URL` mobile déplacé vers `BuildConfig` (configurable par variante de build) | `app/build.gradle.kts`, `Constants.kt` |

---

## ⚠️ Action manuelle requise avant déploiement production

Ces corrections **ne peuvent pas être automatisées** et nécessitent une action de votre part :

1. **`app/google-services.json`** est un placeholder — remplacez-le par le vrai
   fichier téléchargé depuis votre Console Firebase (voir `README_FIREBASE_MOBILE.md`).
2. **`.env`** (backend) — copiez `.env.example` en `.env` et renseignez vos
   vraies clés (Twelve Data, JWT_SECRET, Firebase, OpenRouter).
3. **`JWT_SECRET`** — générez une valeur forte pour la production :
   ```bash
   python -c "import secrets; print(secrets.token_urlsafe(64))"
   ```
4. **`ENVIRONMENT=production`** doit être positionné en prod pour activer le
   garde-fou fail-fast sur `JWT_SECRET`.
5. **Migration DB** — les nouvelles colonnes/tables (`signals.signal_id`,
   `open_positions`) sont créées automatiquement par `Base.metadata.create_all`
   au démarrage **uniquement sur une base neuve**. Si vous avez déjà une base
   de données existante en production, une migration manuelle (ALTER TABLE /
   Alembic) sera nécessaire.

## 🧪 Validation effectuée

Faute d'accès réseau dans cet environnement pour installer `fastapi`,
`sqlalchemy`, `httpx`, etc., la suite de tests complète n'a pas pu être
exécutée via `pytest` directement. **Chaque nouvelle règle testée a cependant
été validée manuellement** en exécutant la logique réelle du code source
(cache TTL/stale, SMC bias BUY/SELL, MTF bougie clôturée/ouverte, absence de
look-ahead du backtest, rotation/cooldown/exhaustion des clés Twelve Data) —
tous les scénarios se comportent comme attendu.

**Recommandation** : exécutez `pip install -r requirements.txt && pytest tests/ -v --cov=src`
dans votre environnement avant tout déploiement, pour une validation finale automatisée.
