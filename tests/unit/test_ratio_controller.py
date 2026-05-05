"""Tests del `RatioController`: smoothing exponencial + convergencia a target."""

from __future__ import annotations

import statistics

import pytest

from streaming_bot.application.strategies.ratio_controller import (
    BehaviorIntent,
    RatioController,
    RatioControllerConfig,
)
from streaming_bot.application.strategies.ratio_targets import RatioTargets
from streaming_bot.domain.persona import (
    BehaviorProbabilities,
    DeviceType,
    EngagementLevel,
    Persona,
    PersonaTraits,
    PlatformProfile,
    SessionPattern,
)
from streaming_bot.domain.persona import (
    MouseProfile as PersonaMouseProfile,
)
from streaming_bot.domain.persona import (
    TypingProfile as PersonaTypingProfile,
)
from streaming_bot.domain.value_objects import Country


def _make_persona(*, country: Country = Country.US, genre: str | None = None) -> Persona:
    """Persona minima para tests del controller."""
    genres: tuple[str, ...] = (genre,) if genre else ()
    traits = PersonaTraits(
        engagement_level=EngagementLevel.CASUAL,
        preferred_genres=genres,
        preferred_session_hour_local=(18, 23),
        device=DeviceType.DESKTOP_CHROME,
        platform=PlatformProfile.WINDOWS_DESKTOP,
        ui_language="en-US",
        timezone="America/New_York",
        country=country,
        behaviors=BehaviorProbabilities(),
        typing=PersonaTypingProfile(),
        mouse=PersonaMouseProfile(),
        session=SessionPattern(),
    )
    return Persona(account_id="acc-test", traits=traits)


class TestConfig:
    def test_invalid_alpha_raises(self) -> None:
        with pytest.raises(ValueError, match="smoothing_alpha"):
            RatioControllerConfig(smoothing_alpha=0.0)
        with pytest.raises(ValueError, match="smoothing_alpha"):
            RatioControllerConfig(smoothing_alpha=1.5)

    def test_invalid_sensitivity_raises(self) -> None:
        with pytest.raises(ValueError, match="sensitivity"):
            RatioControllerConfig(sensitivity=-0.1)
        with pytest.raises(ValueError, match="sensitivity"):
            RatioControllerConfig(sensitivity=1.5)


class TestAdjustedProbability:
    def test_target_zero_returns_zero(self) -> None:
        controller = RatioController(rng_seed=0)
        assert controller.adjusted_probability(target=0.0, observed=0.5) == 0.0

    def test_observed_equal_target_returns_target(self) -> None:
        controller = RatioController(rng_seed=0)
        result = controller.adjusted_probability(target=0.04, observed=0.04)
        assert result == pytest.approx(0.04)

    def test_observed_below_target_increases_probability(self) -> None:
        controller = RatioController(rng_seed=0)
        boosted = controller.adjusted_probability(target=0.05, observed=0.0)
        assert boosted > 0.05

    def test_observed_above_target_decreases_probability(self) -> None:
        controller = RatioController(rng_seed=0)
        suppressed = controller.adjusted_probability(target=0.05, observed=0.20)
        assert suppressed < 0.05

    def test_extreme_observed_clamped_not_negative(self) -> None:
        controller = RatioController(rng_seed=0)
        # observed >> target debe dejar p en >= 0
        p = controller.adjusted_probability(target=0.05, observed=0.99)
        assert p >= 0.0

    def test_observed_one_returns_zero(self) -> None:
        controller = RatioController(rng_seed=0)
        assert controller.adjusted_probability(target=0.10, observed=1.0) == 0.0


class TestObservedRates:
    def test_empty_history_returns_zero_rates(self) -> None:
        controller = RatioController(rng_seed=0)
        rates = controller.observed_rates([])
        assert all(v == 0.0 for v in rates.values())
        assert set(rates.keys()) == {
            BehaviorIntent.SAVE_TRACK,
            BehaviorIntent.SKIP_TRACK,
            BehaviorIntent.ADD_TO_QUEUE,
            BehaviorIntent.LIKE_ARTIST,
        }

    def test_single_save_increases_save_rate(self) -> None:
        controller = RatioController(
            config=RatioControllerConfig(smoothing_alpha=0.30, sensitivity=0.6),
            rng_seed=0,
        )
        rates = controller.observed_rates([BehaviorIntent.SAVE_TRACK])
        assert rates[BehaviorIntent.SAVE_TRACK] == pytest.approx(0.30)
        assert rates[BehaviorIntent.SKIP_TRACK] == 0.0

    def test_repeated_intent_converges_to_one(self) -> None:
        controller = RatioController(
            config=RatioControllerConfig(smoothing_alpha=0.30, sensitivity=0.6),
            rng_seed=0,
        )
        history = [BehaviorIntent.SAVE_TRACK] * 50
        rates = controller.observed_rates(history)
        # Tras 50 saves la EMA debe estar muy cerca de 1.0.
        assert rates[BehaviorIntent.SAVE_TRACK] > 0.99


class TestNextAction:
    def test_returns_member_of_intent_enum(self) -> None:
        controller = RatioController(rng_seed=42)
        persona = _make_persona()
        result = controller.next_action(persona=persona)
        assert isinstance(result, BehaviorIntent)

    def test_empty_targets_always_returns_none(self) -> None:
        zero_targets = RatioTargets(
            save_rate=0.0,
            skip_rate=0.0,
            queue_rate=0.0,
            like_rate=0.0,
        )
        controller = RatioController(targets=zero_targets, rng_seed=42)
        for _ in range(50):
            assert controller.next_action() == BehaviorIntent.NONE

    def test_seed_reproducibility(self) -> None:
        a = RatioController(rng_seed=99)
        b = RatioController(rng_seed=99)
        persona = _make_persona()
        results_a = [a.next_action(persona=persona) for _ in range(50)]
        results_b = [b.next_action(persona=persona) for _ in range(50)]
        assert results_a == results_b


class TestConvergence:
    """Tests de propiedad: la frecuencia observada converge al target."""

    @staticmethod
    def _simulate(
        *,
        target_rates: RatioTargets,
        seed: int,
        iterations: int,
    ) -> dict[BehaviorIntent, int]:
        controller = RatioController(
            targets=target_rates,
            config=RatioControllerConfig(smoothing_alpha=0.10, sensitivity=0.6),
            rng_seed=seed,
        )
        counts: dict[BehaviorIntent, int] = dict.fromkeys(BehaviorIntent, 0)
        history: list[BehaviorIntent] = []
        for _ in range(iterations):
            intent = controller.next_action(targets=target_rates, recent_history=history)
            counts[intent] += 1
            # Guardamos TODAS las decisiones (incluido NONE) para que la EMA
            # mida "tasa por decision" y no "tasa entre acciones ejecutadas".
            # Esto reproduce como PlaylistSessionUseCase llamara al controller
            # por cada track del flujo real.
            history.append(intent)
            # Ventana acotada: el alpha=0.10 implica que ~30 muestras dominan
            # la EMA (peso < 5% mas alla). Mantenemos 200 para holgura.
            if len(history) > 200:
                history = history[-200:]
        return counts

    def test_save_rate_converges_close_to_target(self) -> None:
        target = RatioTargets(
            save_rate=0.10,
            skip_rate=0.0,
            queue_rate=0.0,
            like_rate=0.0,
        )
        counts = self._simulate(target_rates=target, seed=2026, iterations=4000)
        observed = counts[BehaviorIntent.SAVE_TRACK] / 4000
        # Debe quedar cerca del target (0.10) con holgura razonable
        # debido a la sensibilidad +-60%.
        assert 0.05 <= observed <= 0.18, f"observed save rate {observed} fuera de banda"

    def test_skip_rate_above_save_when_target_higher(self) -> None:
        target = RatioTargets(
            save_rate=0.04,
            skip_rate=0.40,
            queue_rate=0.0,
            like_rate=0.0,
        )
        counts = self._simulate(target_rates=target, seed=7, iterations=3000)
        skip_freq = counts[BehaviorIntent.SKIP_TRACK] / 3000
        save_freq = counts[BehaviorIntent.SAVE_TRACK] / 3000
        assert skip_freq > save_freq

    def test_no_intent_never_dominates_when_targets_present(self) -> None:
        """NONE debe seguir saliendo, pero no debe ser ~100% si hay targets."""
        target = RatioTargets(
            save_rate=0.20,
            skip_rate=0.30,
            queue_rate=0.05,
            like_rate=0.10,
        )
        counts = self._simulate(target_rates=target, seed=11, iterations=2000)
        none_freq = counts[BehaviorIntent.NONE] / 2000
        assert none_freq < 0.95


class TestRedFlagAvoidance:
    """El problema central: NO permitir que TODAS las cuentas guarden el target."""

    def test_save_does_not_dominate_with_default_targets(self) -> None:
        """Con defaults globales, save no debe pasar de ~10% en sesiones largas."""
        controller = RatioController(
            targets=RatioTargets.default(),
            config=RatioControllerConfig(smoothing_alpha=0.10, sensitivity=0.6),
            rng_seed=2026,
        )
        history: list[BehaviorIntent] = []
        save_count = 0
        total = 5000
        for _ in range(total):
            intent = controller.next_action(recent_history=history)
            if intent == BehaviorIntent.SAVE_TRACK:
                save_count += 1
            history.append(intent)
            if len(history) > 200:
                history = history[-200:]
        save_rate = save_count / total
        # Default = 0.04. Con sensibilidad 0.6 nunca debe exceder 0.10.
        assert save_rate <= 0.10, f"save_rate {save_rate} es bandera roja"

    def test_high_observed_save_suppresses_future_saves(self) -> None:
        """Inyectando muchos saves recientes, prob de proximo save debe ser baja."""
        # Historial simulando que la persona ha hecho save en TODOS los tracks.
        loaded_history = [BehaviorIntent.SAVE_TRACK] * 30
        # Tomamos muchas muestras para promediar el RNG.
        save_outcomes = []
        for seed in range(200):
            controller_seeded = RatioController(
                targets=RatioTargets(save_rate=0.04, skip_rate=0.0, queue_rate=0.0, like_rate=0.0),
                rng_seed=seed,
            )
            intent = controller_seeded.next_action(recent_history=loaded_history)
            save_outcomes.append(1 if intent == BehaviorIntent.SAVE_TRACK else 0)
        save_freq = statistics.mean(save_outcomes)
        # Saturado: la prob ajustada cae practicamente a cero.
        assert save_freq < 0.05


class TestPersonaTargets:
    def test_persona_resolution_used_when_no_explicit_targets(self) -> None:
        """Si pasamos persona pero no targets explicitos, los targets vienen
        de RatioTargets.for_persona (geo + genero).
        """
        controller = RatioController(rng_seed=42)
        persona_pe = _make_persona(country=Country.PE, genre="reggaeton")
        # Tomamos muchas muestras y comparamos con persona JP/lo-fi.
        history: list[BehaviorIntent] = []
        pe_saves = 0
        for _ in range(2000):
            intent = controller.next_action(persona=persona_pe, recent_history=history)
            if intent == BehaviorIntent.SAVE_TRACK:
                pe_saves += 1
            history.append(intent)
            if len(history) > 100:
                history = history[-100:]

        controller_jp = RatioController(rng_seed=42)
        persona_jp = _make_persona(country=Country.JP, genre="lo-fi")
        history_jp: list[BehaviorIntent] = []
        jp_saves = 0
        for _ in range(2000):
            intent = controller_jp.next_action(persona=persona_jp, recent_history=history_jp)
            if intent == BehaviorIntent.SAVE_TRACK:
                jp_saves += 1
            history_jp.append(intent)
            if len(history_jp) > 100:
                history_jp = history_jp[-100:]

        assert pe_saves > jp_saves, (
            f"persona PE+reggaeton ({pe_saves}) deberia tener mas saves que "
            f"JP+lo-fi ({jp_saves})"
        )

    def test_explicit_targets_override_persona(self) -> None:
        controller = RatioController(rng_seed=0)
        persona = _make_persona(country=Country.US)
        zero = RatioTargets(save_rate=0.0, skip_rate=0.0, queue_rate=0.0, like_rate=0.0)
        for _ in range(100):
            assert controller.next_action(persona=persona, targets=zero) == BehaviorIntent.NONE
