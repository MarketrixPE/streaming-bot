"""PoC Contextual bandit — LinUCB sobre asignacion de budget streaming.

Objetivo del spike:
    Validar que un LinUCB simple converge a >= 80% del retorno del oraculo
    retrospectivo en <= 60 iteraciones cuando elige bucket de budget para
    cada track entre {0, 5, 10, 25, 50, 100, 200} USD/dia, dado un contexto
    cohort_14d. Justifica HS4 en docs/strategy/year-2/01-thesis-and-kpis.md.

Como ejecutarlo:
    pip install numpy==2.*
    python spikes/year-2/contextual_bandit_poc.py

Dependencias explicitas: numpy.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import List

import numpy as np

RNG_SEED = 11
N_TRACKS = 200
N_DAYS = 90
BUDGET_BUCKETS_USD: List[float] = [0, 5, 10, 25, 50, 100, 200]
DAILY_BUDGET_USD = 800.0
CTX_DIM = 8


@dataclass
class TrackCtx:
    track_id: int
    quality: float
    saturation: float
    cold_start_days: int


def make_track(rng: np.random.Generator, idx: int) -> TrackCtx:
    return TrackCtx(
        track_id=idx,
        quality=float(rng.beta(2.0, 5.0)),
        saturation=float(rng.uniform(0.0, 0.8)),
        cold_start_days=int(rng.integers(0, 5)),
    )


def context_vector(t: TrackCtx, age_days: int) -> np.ndarray:
    return np.array([
        1.0,
        t.quality,
        t.saturation,
        max(0.0, 14.0 - age_days) / 14.0,
        min(1.0, age_days / 30.0),
        t.quality * (1.0 - t.saturation),
        float(t.cold_start_days > 0),
        np.tanh(age_days / 30.0),
    ], dtype=float)


def true_marginal_reward(
    t: TrackCtx, action_usd: float, age_days: int, rng: np.random.Generator,
) -> float:
    """Funcion oraculo (desconocida para el bandit). Reward = LRV marginal - cost."""
    if action_usd == 0:
        return -0.5
    saturation_penalty = 1.0 - 0.55 * t.saturation
    age_decay = np.exp(-age_days / 35.0)
    diminishing = np.log1p(action_usd) / np.log1p(200.0)
    base = 9.0 * t.quality * saturation_penalty * age_decay * diminishing * 200.0
    reward = base - action_usd + rng.normal(0, 4.0)
    return float(reward)


class LinUCB:
    """LinUCB con un modelo lineal por accion."""

    def __init__(self, n_actions: int, ctx_dim: int, alpha: float = 1.5):
        self.n_actions = n_actions
        self.ctx_dim = ctx_dim
        self.alpha = alpha
        self.A = [np.eye(ctx_dim) for _ in range(n_actions)]
        self.b = [np.zeros(ctx_dim) for _ in range(n_actions)]

    def select(self, ctx: np.ndarray) -> tuple[int, np.ndarray]:
        ucb_scores = np.zeros(self.n_actions)
        for a in range(self.n_actions):
            A_inv = np.linalg.inv(self.A[a])
            theta = A_inv @ self.b[a]
            mean = float(theta @ ctx)
            uncertainty = self.alpha * float(np.sqrt(ctx @ A_inv @ ctx))
            ucb_scores[a] = mean + uncertainty
        chosen = int(np.argmax(ucb_scores))
        return chosen, ucb_scores

    def update(self, action: int, ctx: np.ndarray, reward: float) -> None:
        self.A[action] += np.outer(ctx, ctx)
        self.b[action] += reward * ctx


def knapsack_assign(
    selected_actions: List[int], ucb_scores: List[np.ndarray], buckets: List[float], budget: float,
) -> List[int]:
    """Greedy con UCB-per-cost ordering bajo restriccion de budget total."""
    n = len(selected_actions)
    base_costs = [buckets[a] for a in selected_actions]
    base_total = sum(base_costs)
    if base_total <= budget:
        return selected_actions

    best_alt = list(selected_actions)
    while sum(buckets[a] for a in best_alt) > budget:
        worst_idx = max(
            range(n),
            key=lambda i: buckets[best_alt[i]] / max(0.001, ucb_scores[i][best_alt[i]]),
        )
        cur_a = best_alt[worst_idx]
        if cur_a == 0:
            break
        next_a = max(0, cur_a - 1)
        if next_a == cur_a:
            break
        best_alt[worst_idx] = next_a
    return best_alt


def oracle_assign(
    tracks: List[TrackCtx], age: int, rng: np.random.Generator,
) -> tuple[List[int], float]:
    n = len(tracks)
    expected = np.zeros((n, len(BUDGET_BUCKETS_USD)))
    for i, t in enumerate(tracks):
        for a, usd in enumerate(BUDGET_BUCKETS_USD):
            samples = [true_marginal_reward(t, usd, age, rng) for _ in range(20)]
            expected[i, a] = float(np.mean(samples))
    actions = list(np.argmax(expected, axis=1))
    while sum(BUDGET_BUCKETS_USD[a] for a in actions) > DAILY_BUDGET_USD:
        worst_idx = max(
            range(n),
            key=lambda i: BUDGET_BUCKETS_USD[actions[i]]
            / max(0.001, expected[i, actions[i]]),
        )
        if actions[worst_idx] == 0:
            break
        actions[worst_idx] -= 1
    total = sum(expected[i, a] for i, a in enumerate(actions))
    return actions, float(total)


def main() -> None:
    rng = np.random.default_rng(RNG_SEED)
    rng_oracle = np.random.default_rng(RNG_SEED + 17)
    tracks = [make_track(rng, i) for i in range(N_TRACKS)]
    bandit = LinUCB(n_actions=len(BUDGET_BUCKETS_USD), ctx_dim=CTX_DIM, alpha=1.5)

    cum_bandit = 0.0
    cum_oracle = 0.0
    history = []

    for day in range(N_DAYS):
        chosen_per_track: List[int] = []
        ucb_per_track: List[np.ndarray] = []
        ctx_per_track: List[np.ndarray] = []
        for t in tracks:
            ctx = context_vector(t, age_days=day)
            ctx_per_track.append(ctx)
            a, ucb = bandit.select(ctx)
            chosen_per_track.append(a)
            ucb_per_track.append(ucb)

        feasible = knapsack_assign(
            chosen_per_track, ucb_per_track, BUDGET_BUCKETS_USD, DAILY_BUDGET_USD,
        )

        day_reward = 0.0
        for i, t in enumerate(tracks):
            a = feasible[i]
            reward = true_marginal_reward(t, BUDGET_BUCKETS_USD[a], day, rng)
            bandit.update(a, ctx_per_track[i], reward)
            day_reward += reward
        cum_bandit += day_reward

        oracle_actions, oracle_reward = oracle_assign(tracks, day, rng_oracle)
        cum_oracle += oracle_reward

        if day % 10 == 0 or day == N_DAYS - 1:
            ratio = cum_bandit / max(1e-6, cum_oracle)
            history.append((day, cum_bandit, cum_oracle, ratio))
            print(
                f"[poc] day={day:>3} | bandit={cum_bandit:>10.0f} | "
                f"oracle={cum_oracle:>10.0f} | ratio={ratio:.3f}"
            )
        if day == 0 or day % 30 == 29:
            bandit.alpha = max(0.5, bandit.alpha * 0.85)

    final_ratio = cum_bandit / max(1e-6, cum_oracle)
    print(f"[poc] final cumulative bandit/oracle ratio: {final_ratio:.3f}")
    if final_ratio >= 0.80:
        print("[poc] PASS: bandit >= 80% del oraculo")
    else:
        print("[poc] FAIL: bandit < 80% del oraculo")


if __name__ == "__main__":
    main()
