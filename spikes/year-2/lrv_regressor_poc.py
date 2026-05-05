"""PoC LRV regressor — LightGBM quantile sobre cohort sintetico.

Objetivo del spike:
    Validar que con un cohort de 14 dias de senales (plays diarios, save_rate,
    geo_mix, premium_ratio, playlist_adds) un LightGBM quantile regressor predice
    LRV_60d con MAE relativo < 25% en holdout, justificando la tesis H0 de
    docs/strategy/year-2/01-thesis-and-kpis.md.

Como ejecutarlo:
    pip install lightgbm==4.5.* numpy==2.* pandas==2.2.* scikit-learn==1.5.*
    python spikes/year-2/lrv_regressor_poc.py

Genera datos sinteticos (cohort simulator) con un proceso generativo plausible:
LRV depende de save_rate, premium_ratio, geo_mix, playlist_adds y un nicho-effect
con ruido lognormal. Train sobre 80%, holdout 5%, validation 15%. Imprime
metricas y feature importance.

Dependencias explicitas: lightgbm, numpy, pandas, scikit-learn.
No requiere infra ni Postgres ni ClickHouse — el dataset se genera en memoria.
"""
from __future__ import annotations

import dataclasses
import hashlib
import math
import random
from typing import List, Tuple

import lightgbm as lgb
import numpy as np
import pandas as pd
from sklearn.metrics import mean_absolute_error

RNG_SEED = 42
N_TRACKS = 8_000
NICHES: List[str] = [
    "lo-fi", "sleep", "ambient", "study", "white-noise",
    "kids", "asmr-binaural", "meditation", "piano-soft",
    "rain-sounds", "jazz-bg", "synthwave-chill",
]
COUNTRIES: List[str] = ["US", "UK", "DE", "FR", "BR", "MX", "IN", "ID", "PH", "VN"]
PAYOUT_PER_STREAM_USD: dict[str, float] = {
    "US": 0.0035, "UK": 0.0034, "DE": 0.0030, "FR": 0.0028,
    "BR": 0.0010, "MX": 0.0012, "IN": 0.0006, "ID": 0.0007,
    "PH": 0.0008, "VN": 0.0006,
}


@dataclasses.dataclass
class Track:
    track_id: str
    niche: str
    plays_d1_d14: List[int]
    save_rate_d14: float
    skip_rate_d14: float
    queue_rate_d14: float
    completion_rate_d14: float
    geo_top5_codes: List[str]
    geo_top5_weights: List[float]
    ratio_premium_listeners: float
    playlist_adds_count_d14: int
    same_niche_releases_last_30d: int
    niche_saturation_score: float
    production_cost_cents: int
    distribution_cost_cents: int
    streaming_invest_d0_d14_cents: int
    organic_share_estimate_d14: float
    lrv_60d_cents: int
    is_holdout: bool


def _hash_holdout(track_id: str, salt: str = "y2-poc-2027") -> bool:
    h = hashlib.blake2b((track_id + salt).encode(), digest_size=8).digest()
    return (int.from_bytes(h, "big") % 1000) < 50


def synth_cohort(rng: random.Random, np_rng: np.random.Generator) -> Track:
    track_id = "tr_" + hashlib.blake2b(
        rng.random().hex().encode(), digest_size=8
    ).hexdigest()
    niche = rng.choices(
        NICHES,
        weights=[3, 4, 2, 3, 2, 2, 1, 2, 2, 2, 1, 2],
    )[0]

    niche_quality = {
        "lo-fi": 1.0, "sleep": 1.05, "ambient": 0.9, "study": 1.0,
        "white-noise": 0.95, "kids": 1.1, "asmr-binaural": 0.7,
        "meditation": 1.0, "piano-soft": 0.95, "rain-sounds": 0.85,
        "jazz-bg": 0.8, "synthwave-chill": 0.95,
    }[niche]

    intrinsic_quality = float(np_rng.beta(2.0, 5.0))
    save_rate_d14 = max(0.005, min(0.25, 0.04 + 0.18 * intrinsic_quality + np_rng.normal(0, 0.015)))
    skip_rate_d14 = max(0.05, min(0.85, 0.55 - 0.45 * intrinsic_quality + np_rng.normal(0, 0.05)))
    queue_rate_d14 = max(0.0, min(0.4, 0.02 + 0.25 * intrinsic_quality + np_rng.normal(0, 0.02)))
    completion_rate_d14 = max(0.2, min(0.98, 0.55 + 0.35 * intrinsic_quality + np_rng.normal(0, 0.03)))

    base_daily = max(20, int(np_rng.lognormal(mean=4.0 + 1.5 * intrinsic_quality, sigma=0.6)))
    plays_d1_d14: List[int] = []
    decay = float(np_rng.uniform(0.85, 1.05))
    cur = base_daily
    for _ in range(14):
        cur = max(5, int(cur * decay + np_rng.normal(0, cur * 0.15)))
        plays_d1_d14.append(cur)

    geo_choices = rng.sample(COUNTRIES, 5)
    weights_raw = np_rng.dirichlet([2.0, 1.5, 1.2, 1.0, 0.8])
    geo_top5_weights = [float(w) for w in weights_raw]

    ratio_premium = float(np_rng.beta(3.0, 4.0))
    playlist_adds = int(np_rng.poisson(0.5 + 4.0 * intrinsic_quality))
    organic_share = float(np_rng.beta(2.0, 8.0))

    same_niche_releases = int(np_rng.poisson(15))
    saturation = max(0.0, min(1.0, same_niche_releases / 60.0 + np_rng.normal(0, 0.05)))

    prod_cost = int(np_rng.uniform(800, 4500))
    distro_cost = int(np_rng.uniform(50, 300))
    invest_d14 = int(np_rng.uniform(500, 5000) * (0.7 + 0.5 * intrinsic_quality))

    weighted_payout = sum(
        w * PAYOUT_PER_STREAM_USD[c] for w, c in zip(geo_top5_weights, geo_choices)
    )
    expected_streams_d15_d60 = (
        sum(plays_d1_d14[7:14])
        * 4.5
        * niche_quality
        * (1.0 - 0.4 * saturation)
        * (1.0 + 1.2 * intrinsic_quality)
        * (1.0 + 0.6 * save_rate_d14)
        * (1.0 - 0.3 * skip_rate_d14)
        * (1.0 + 0.05 * playlist_adds)
    )
    monetizable_share = 0.6 + 0.35 * ratio_premium
    lrv_usd = expected_streams_d15_d60 * weighted_payout * monetizable_share
    lrv_usd *= float(np.exp(np_rng.normal(0, 0.35)))
    lrv_60d_cents = int(max(0, lrv_usd * 100))

    return Track(
        track_id=track_id,
        niche=niche,
        plays_d1_d14=plays_d1_d14,
        save_rate_d14=save_rate_d14,
        skip_rate_d14=skip_rate_d14,
        queue_rate_d14=queue_rate_d14,
        completion_rate_d14=completion_rate_d14,
        geo_top5_codes=geo_choices,
        geo_top5_weights=geo_top5_weights,
        ratio_premium_listeners=ratio_premium,
        playlist_adds_count_d14=playlist_adds,
        same_niche_releases_last_30d=same_niche_releases,
        niche_saturation_score=saturation,
        production_cost_cents=prod_cost,
        distribution_cost_cents=distro_cost,
        streaming_invest_d0_d14_cents=invest_d14,
        organic_share_estimate_d14=organic_share,
        lrv_60d_cents=lrv_60d_cents,
        is_holdout=_hash_holdout(track_id),
    )


def to_dataframe(tracks: List[Track]) -> pd.DataFrame:
    rows = []
    for t in tracks:
        row = {
            "track_id": t.track_id,
            "niche": t.niche,
            "save_rate_d14": t.save_rate_d14,
            "skip_rate_d14": t.skip_rate_d14,
            "queue_rate_d14": t.queue_rate_d14,
            "completion_rate_d14": t.completion_rate_d14,
            "ratio_premium_listeners": t.ratio_premium_listeners,
            "playlist_adds_count_d14": t.playlist_adds_count_d14,
            "same_niche_releases_last_30d": t.same_niche_releases_last_30d,
            "niche_saturation_score": t.niche_saturation_score,
            "production_cost_cents": t.production_cost_cents,
            "distribution_cost_cents": t.distribution_cost_cents,
            "streaming_invest_d0_d14_cents": t.streaming_invest_d0_d14_cents,
            "organic_share_estimate_d14": t.organic_share_estimate_d14,
            "plays_total_d14": sum(t.plays_d1_d14),
            "plays_velocity_d7_d14": sum(t.plays_d1_d14[7:14]) / max(1, sum(t.plays_d1_d14[:7])),
            "lrv_60d_cents": t.lrv_60d_cents,
            "is_holdout": t.is_holdout,
        }
        for i, p in enumerate(t.plays_d1_d14, start=1):
            row[f"plays_d{i}"] = p
        for i, c in enumerate(t.geo_top5_codes):
            row[f"geo_top{i + 1}"] = c
            row[f"geo_top{i + 1}_w"] = t.geo_top5_weights[i]
        rows.append(row)
    return pd.DataFrame(rows)


def time_split(df: pd.DataFrame, train_frac: float = 0.7, val_frac: float = 0.15) -> Tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    in_pool = df[~df.is_holdout].sample(frac=1.0, random_state=RNG_SEED).reset_index(drop=True)
    holdout = df[df.is_holdout].reset_index(drop=True)
    n = len(in_pool)
    n_tr = int(n * train_frac)
    n_val = int(n * val_frac)
    train = in_pool.iloc[:n_tr]
    val = in_pool.iloc[n_tr : n_tr + n_val]
    return train, val, holdout


def fit_quantile(train: pd.DataFrame, val: pd.DataFrame, alpha: float) -> lgb.LGBMRegressor:
    feature_cols = [
        c for c in train.columns
        if c not in {"track_id", "lrv_60d_cents", "is_holdout"}
        and not c.startswith("geo_top")
    ]
    cat_cols = ["niche"]
    X_tr = train[feature_cols].copy()
    X_val = val[feature_cols].copy()
    for c in cat_cols:
        X_tr[c] = X_tr[c].astype("category")
        X_val[c] = X_val[c].astype("category")

    model = lgb.LGBMRegressor(
        objective="quantile",
        alpha=alpha,
        n_estimators=800,
        learning_rate=0.03,
        num_leaves=64,
        min_child_samples=50,
        feature_fraction=0.8,
        bagging_fraction=0.8,
        bagging_freq=5,
        reg_alpha=0.1,
        reg_lambda=0.1,
        verbose=-1,
    )
    model.fit(
        X_tr,
        train["lrv_60d_cents"].clip(lower=0),
        eval_set=[(X_val, val["lrv_60d_cents"].clip(lower=0))],
        callbacks=[lgb.early_stopping(50, verbose=False)],
        categorical_feature=cat_cols,
    )
    return model


def evaluate(model: lgb.LGBMRegressor, df: pd.DataFrame, label: str) -> dict:
    feature_cols = [
        c for c in df.columns
        if c not in {"track_id", "lrv_60d_cents", "is_holdout"}
        and not c.startswith("geo_top")
    ]
    X = df[feature_cols].copy()
    X["niche"] = X["niche"].astype("category")
    pred = model.predict(X)
    actual = df["lrv_60d_cents"].clip(lower=0).values
    mae = mean_absolute_error(actual, pred)
    mae_rel = mae / max(1.0, actual.mean())
    p90_rel = float(
        np.quantile(np.abs(pred - actual) / np.maximum(1.0, actual), 0.9)
    )
    return {"label": label, "n": len(df), "mae": mae, "mae_relative": mae_rel, "p90_rel_err": p90_rel}


def coverage_p10_p90(model_p10: lgb.LGBMRegressor, model_p90: lgb.LGBMRegressor, df: pd.DataFrame) -> float:
    feature_cols = [
        c for c in df.columns
        if c not in {"track_id", "lrv_60d_cents", "is_holdout"}
        and not c.startswith("geo_top")
    ]
    X = df[feature_cols].copy()
    X["niche"] = X["niche"].astype("category")
    p10 = model_p10.predict(X)
    p90 = model_p90.predict(X)
    actual = df["lrv_60d_cents"].clip(lower=0).values
    inside = ((actual >= p10) & (actual <= p90)).mean()
    return float(inside)


def main() -> None:
    rng = random.Random(RNG_SEED)
    np_rng = np.random.default_rng(RNG_SEED)

    print(f"[poc] generating {N_TRACKS} synthetic tracks...")
    tracks = [synth_cohort(rng, np_rng) for _ in range(N_TRACKS)]
    df = to_dataframe(tracks)
    print(f"[poc] dataframe shape: {df.shape}")
    print(f"[poc] holdout share: {df.is_holdout.mean():.3%}")
    print(f"[poc] LRV mean cents: {df.lrv_60d_cents.mean():.0f}")

    train, val, holdout = time_split(df)
    print(f"[poc] train={len(train)} val={len(val)} holdout={len(holdout)}")

    print("[poc] training quantile regressors p10 / p50 / p90 ...")
    m10 = fit_quantile(train, val, alpha=0.1)
    m50 = fit_quantile(train, val, alpha=0.5)
    m90 = fit_quantile(train, val, alpha=0.9)

    res_val = evaluate(m50, val, "val_p50")
    res_holdout = evaluate(m50, holdout, "holdout_p50")
    coverage = coverage_p10_p90(m10, m90, holdout)

    print("[poc] === results ===")
    for r in (res_val, res_holdout):
        print(
            f"  {r['label']:>14} | n={r['n']:>5} | "
            f"MAE_rel={r['mae_relative']:.3f} | P90_rel_err={r['p90_rel_err']:.3f}"
        )
    print(f"  coverage_p10_p90 holdout: {coverage:.3f} (target 0.78-0.82)")

    target_mae = 0.25
    if res_holdout["mae_relative"] < target_mae:
        print(f"[poc] PASS: holdout MAE_rel {res_holdout['mae_relative']:.3f} < {target_mae}")
    else:
        print(f"[poc] FAIL: holdout MAE_rel {res_holdout['mae_relative']:.3f} >= {target_mae}")

    importances = pd.Series(
        m50.feature_importances_, index=m50.booster_.feature_name()
    ).sort_values(ascending=False)
    print("[poc] top-10 feature importances (p50):")
    for name, imp in importances.head(10).items():
        print(f"  {name:>40} {imp:>8}")


if __name__ == "__main__":
    main()
