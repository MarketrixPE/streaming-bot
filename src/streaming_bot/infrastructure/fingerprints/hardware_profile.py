"""Perfil estable de hardware (GPU, cores, memoria) por SO y persona.

Reglas de coherencia:
- GPU vendor + renderer realista por SO (NVIDIA / Intel / AMD para Windows;
  Apple Silicon o Intel para macOS; Mesa o NVIDIA para Linux).
- hardwareConcurrency en {4, 8, 12, 16}.
- deviceMemory en {4, 8, 16} GB.
- Si se pasa `persona_id`, el perfil es DETERMINISTICO en ese ID
  (la huella de WebGL/Canvas/AudioContext queda estable entre sesiones de
  la misma cuenta -- requisito anti-fingerprint).
- Si NO se pasa persona_id, se usa CSPRNG (`secrets`) -- caso uso ad-hoc.
"""

from __future__ import annotations

import hashlib
import secrets

from streaming_bot.domain.value_objects_v2 import GpuProfile, HardwareProfile

# Perfiles GPU representativos por SO. canvas_noise_seed y audio_context_seed
# son enteros estables que el browser driver inyecta para fijar el hash de
# Canvas2D y AudioContext entre sesiones (valor != 0 evita coincidencias triviales).
_GPU_POOL_BY_OS: dict[str, tuple[GpuProfile, ...]] = {
    "Windows": (
        GpuProfile(
            vendor="Google Inc. (NVIDIA)",
            renderer=(
                "ANGLE (NVIDIA, NVIDIA GeForce GTX 1660 SUPER (0x00002187) "
                "Direct3D11 vs_5_0 ps_5_0, D3D11)"
            ),
            canvas_noise_seed=11_001,
            audio_context_seed=42_001,
        ),
        GpuProfile(
            vendor="Google Inc. (NVIDIA)",
            renderer=(
                "ANGLE (NVIDIA, NVIDIA GeForce RTX 3060 (0x00002503) "
                "Direct3D11 vs_5_0 ps_5_0, D3D11)"
            ),
            canvas_noise_seed=11_002,
            audio_context_seed=42_002,
        ),
        GpuProfile(
            vendor="Google Inc. (Intel)",
            renderer="ANGLE (Intel, Intel(R) UHD Graphics 630 (0x00003E92), D3D11)",
            canvas_noise_seed=11_003,
            audio_context_seed=42_003,
        ),
        GpuProfile(
            vendor="Google Inc. (AMD)",
            renderer=(
                "ANGLE (AMD, AMD Radeon RX 6600 (0x000073FF) "
                "Direct3D11 vs_5_0 ps_5_0, D3D11)"
            ),
            canvas_noise_seed=11_004,
            audio_context_seed=42_004,
        ),
    ),
    "macOS": (
        GpuProfile(
            vendor="Apple Inc.",
            renderer="Apple M1",
            canvas_noise_seed=22_001,
            audio_context_seed=43_001,
        ),
        GpuProfile(
            vendor="Apple Inc.",
            renderer="Apple M2 Pro",
            canvas_noise_seed=22_002,
            audio_context_seed=43_002,
        ),
        GpuProfile(
            vendor="Apple Inc.",
            renderer="Apple M3",
            canvas_noise_seed=22_003,
            audio_context_seed=43_003,
        ),
        GpuProfile(
            vendor="Intel Inc.",
            renderer="Intel(R) Iris(TM) Plus Graphics OpenGL Engine",
            canvas_noise_seed=22_004,
            audio_context_seed=43_004,
        ),
    ),
    "Linux": (
        GpuProfile(
            vendor="Mesa",
            renderer="Mesa Intel(R) UHD Graphics 620 (KBL GT2)",
            canvas_noise_seed=33_001,
            audio_context_seed=44_001,
        ),
        GpuProfile(
            vendor="Mesa",
            renderer="Mesa DRI Intel(R) HD Graphics 530 (Skylake GT2)",
            canvas_noise_seed=33_002,
            audio_context_seed=44_002,
        ),
        GpuProfile(
            vendor="NVIDIA Corporation",
            renderer="NVIDIA GeForce GTX 1060/PCIe/SSE2",
            canvas_noise_seed=33_003,
            audio_context_seed=44_003,
        ),
    ),
}

# Combos plausibles (cores, ram_gb) por SO. Mantener estrictamente en la
# whitelist {4, 8, 12, 16} cores y {4, 8, 16} GB RAM (requisito v2).
_HW_COMBOS_BY_OS: dict[str, tuple[tuple[int, int], ...]] = {
    "Windows": ((4, 4), (8, 8), (8, 16), (12, 16), (16, 16)),
    "macOS": ((8, 8), (8, 16), (12, 16), (16, 16)),
    "Linux": ((4, 4), (8, 8), (12, 16)),
}

# Hash chunk usado para derivar indices estables desde persona_id.
_HASH_CHUNK_BYTES = 8


def _seed_index(persona_id: str | None, modulus: int, *, salt: str) -> int:
    """Devuelve un indice [0, modulus) deterministico (con persona_id) o random.

    `salt` evita que dos selecciones distintas (p.ej. GPU y combo HW) usen
    el mismo bucket del hash y queden correlacionadas trivialmente.
    """
    if persona_id is None:
        return secrets.randbelow(modulus)
    digest = hashlib.sha256(f"{persona_id}:{salt}".encode()).digest()
    return int.from_bytes(digest[:_HASH_CHUNK_BYTES], "big") % modulus


def hardware_for(os_family: str, *, persona_id: str | None = None) -> HardwareProfile:
    """Devuelve un `HardwareProfile` coherente con el SO y estable por persona.

    - Mismo `persona_id` + mismo `os_family` => mismo profile (idempotente).
    - Diferentes `persona_id` => probablemente perfiles distintos.
    - `persona_id=None` => CSPRNG (uso ad-hoc / tests).
    """
    gpu_pool = _GPU_POOL_BY_OS.get(os_family, _GPU_POOL_BY_OS["Windows"])
    combos = _HW_COMBOS_BY_OS.get(os_family, _HW_COMBOS_BY_OS["Windows"])

    gpu_idx = _seed_index(persona_id, len(gpu_pool), salt="gpu")
    combo_idx = _seed_index(persona_id, len(combos), salt="hw")

    cores, ram = combos[combo_idx]
    return HardwareProfile(
        hardware_concurrency=cores,
        device_memory_gb=ram,
        gpu=gpu_pool[gpu_idx],
    )
