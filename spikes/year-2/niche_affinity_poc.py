"""PoC Niche affinity — clasificador multi-label LightGBM.

Objetivo del spike:
    Demostrar que dado el historico de un operador (rolling 30/60/90 dias por
    nicho) y la saturacion observada, un clasificador multi-label OneVsRest
    LightGBM predice el top-K de nichos cuyo LRV/track esperado mes-siguiente
    cae en el cuartil superior con AUC > 0.75 en holdout.

    Esto justifica HS5 y H2 en docs/strategy/year-2/01-thesis-and-kpis.md.

Como ejecutarlo:
    pip install lightgbm==4.5.* numpy==2.* pandas==2.2.* scikit-learn==1.5.*
    python spikes/year-2/niche_affinity_poc.py

Dependencias explicitas: lightgbm, numpy, pandas, scikit-learn.
"""
from __future__ import annotations

import random
from dataclasses import dataclass
from typing import List

import lightgbm as lgb
import numpy as np
import pandas as pd
from sklearn.metrics import roc_auc_score
from sklearn.preprocessing import StandardScaler

RNG_SEED = 7
N_MONTHS = 36
NICHES: List[str] = [
    "lo-fi", "sleep", "ambient", "study", "white-noise",
    "kids", "asmr-binaural", "meditation", "piano-soft",
    "rain-sounds", "jazz-bg", "synthwave-chill",
]


@dataclass
class NicheMonth:
    month_idx: int
    niche: str
    releases_30d: int
    releases_60d: int
    releases_90d: int
    avg_lrv_per_track_30d: float
    avg_lrv_per_track_60d: float
    avg_lrv_per_track_90d: float
    success_rate_30d: float
    saturation_score: float
    seasonal_phase: float
    next_month_lrv_per_track: float
    next_month_top_quartile: int


def simulate(rng: random.Random, np_rng: np.random.Generator) -> pd.DataFrame:
    rows: List[NicheMonth] = []
    quality = {n: float(np_rng.beta(2.0, 5.0)) for n in NICHES}

    for m in range(N_MONTHS):
        for n in NICHES:
            releases_30d = max(0, int(np_rng.normal(20 + 8 * quality[n], 6)))
            releases_60d = max(releases_30d, int(np_rng.normal(35 + 14 * quality[n], 8)))
            releases_90d = max(releases_60d, int(np_rng.normal(50 + 20 * quality[n], 9)))

            sat = max(0.0, min(1.0, releases_30d / 60.0))
            base_lrv = 4000 * quality[n] * (1.0 - 0.45 * sat)
            base_lrv *= 1.0 + 0.2 * np.sin(2 * np.pi * m / 12.0 + hash(n) % 12)
            avg_30 = float(max(50, np_rng.normal(base_lrv, 800)))
            avg_60 = float(max(50, np_rng.normal(base_lrv * 0.95, 700)))
            avg_90 = float(max(50, np_rng.normal(base_lrv * 0.9, 700)))
            success = float(np.clip(0.18 + 0.55 * quality[n] - 0.4 * sat, 0.02, 0.95))

            seasonal = float(np.sin(2 * np.pi * m / 12.0))
            next_lrv = float(max(0, np_rng.normal(base_lrv * 0.97, 1000)))

            rows.append(
                NicheMonth(
                    month_idx=m,
                    niche=n,
                    releases_30d=releases_30d,
                    releases_60d=releases_60d,
                    releases_90d=releases_90d,
                    avg_lrv_per_track_30d=avg_30,
                    avg_lrv_per_track_60d=avg_60,
                    avg_lrv_per_track_90d=avg_90,
                    success_rate_30d=success,
                    saturation_score=sat,
                    seasonal_phase=seasonal,
                    next_month_lrv_per_track=next_lrv,
                    next_month_top_quartile=0,
                )
            )

    df = pd.DataFrame([r.__dict__ for r in rows])
    threshold_per_month = df.groupby("month_idx")["next_month_lrv_per_track"].quantile(0.75)
    df["threshold"] = df["month_idx"].map(threshold_per_month)
    df["next_month_top_quartile"] = (df["next_month_lrv_per_track"] >= df["threshold"]).astype(int)
    df = df.drop(columns=["threshold"])
    return df


def split_time(df: pd.DataFrame, train_share: float = 0.7) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    cutoff_train = int(N_MONTHS * train_share)
    cutoff_val = int(N_MONTHS * (train_share + 0.15))
    train = df[df.month_idx < cutoff_train]
    val = df[(df.month_idx >= cutoff_train) & (df.month_idx < cutoff_val)]
    test = df[df.month_idx >= cutoff_val]
    return train, val, test


def build_xy(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.Series]:
    feat_cols = [
        "releases_30d", "releases_60d", "releases_90d",
        "avg_lrv_per_track_30d", "avg_lrv_per_track_60d", "avg_lrv_per_track_90d",
        "success_rate_30d", "saturation_score", "seasonal_phase",
    ]
    X = df[feat_cols].copy()
    X = pd.concat(
        [X.reset_index(drop=True), pd.get_dummies(df["niche"], prefix="niche").reset_index(drop=True)],
        axis=1,
    )
    y = df["next_month_top_quartile"].astype(int)
    return X, y


def main() -> None:
    rng = random.Random(RNG_SEED)
    np_rng = np.random.default_rng(RNG_SEED)
    df = simulate(rng, np_rng)
    print(f"[poc] dataset: {len(df)} rows / {df.month_idx.nunique()} months / {df.niche.nunique()} niches")

    train, val, test = split_time(df)
    X_tr, y_tr = build_xy(train)
    X_val, y_val = build_xy(val)
    X_te, y_te = build_xy(test)

    scaler = StandardScaler()
    cont_cols = [c for c in X_tr.columns if not c.startswith("niche_")]
    X_tr[cont_cols] = scaler.fit_transform(X_tr[cont_cols])
    X_val[cont_cols] = scaler.transform(X_val[cont_cols])
    X_te[cont_cols] = scaler.transform(X_te[cont_cols])

    model = lgb.LGBMClassifier(
        objective="binary",
        n_estimators=600,
        learning_rate=0.04,
        num_leaves=48,
        min_child_samples=30,
        feature_fraction=0.85,
        bagging_fraction=0.85,
        bagging_freq=4,
        reg_alpha=0.1,
        reg_lambda=0.2,
        verbose=-1,
    )
    model.fit(
        X_tr,
        y_tr,
        eval_set=[(X_val, y_val)],
        callbacks=[lgb.early_stopping(50, verbose=False)],
    )

    preds_val = model.predict_proba(X_val)[:, 1]
    preds_te = model.predict_proba(X_te)[:, 1]
    auc_val = roc_auc_score(y_val, preds_val)
    auc_te = roc_auc_score(y_te, preds_te)

    print(f"[poc] AUC val: {auc_val:.3f}")
    print(f"[poc] AUC test: {auc_te:.3f}")

    test_with_pred = test.copy().reset_index(drop=True)
    test_with_pred["pred_score"] = preds_te
    top_k = 5
    coverage_per_month = []
    for m, sub in test_with_pred.groupby("month_idx"):
        ranked = sub.sort_values("pred_score", ascending=False).head(top_k)
        actual_top = sub.sort_values("next_month_lrv_per_track", ascending=False).head(top_k)
        coverage = len(set(ranked.niche) & set(actual_top.niche)) / top_k
        coverage_per_month.append(coverage)
    avg_cov = float(np.mean(coverage_per_month))
    print(f"[poc] top-{top_k} coverage on test (mean per month): {avg_cov:.3f}")

    if auc_te > 0.75:
        print("[poc] PASS: AUC test > 0.75")
    else:
        print("[poc] FAIL: AUC test <= 0.75")
    if avg_cov >= 0.6:
        print(f"[poc] PASS: top-{top_k} coverage >= 0.60")
    else:
        print(f"[poc] FAIL: top-{top_k} coverage < 0.60")


if __name__ == "__main__":
    main()
