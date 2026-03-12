"""Generic resource-shaping helpers for research-v1 scheduling."""

from __future__ import annotations

from typing import Any

DEFAULT_EXPECTED_DURATION_MINUTES = 60
DEFAULT_DURATION_MINUTES = DEFAULT_EXPECTED_DURATION_MINUTES
DEFAULT_GPU_MEMORY_MB = 4096


def _safe_int(value: Any, default: int = 0, *, minimum: int = 0) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return max(default, minimum)
    return max(parsed, minimum)


def _safe_bool(value: Any, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes", "on"}:
            return True
        if normalized in {"0", "false", "no", "off"}:
            return False
    return default


def normalize_execution_shape(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    normalized: dict[str, Any] = {}
    for key, raw in value.items():
        if not isinstance(key, str):
            continue
        clean_key = key.strip()
        if not clean_key:
            continue
        if isinstance(raw, (str, int, float, bool)):
            normalized[clean_key] = raw
    return normalized


def _normalized_gpu_count(resource_request: dict[str, Any], gpu_hint: int | str | None) -> int | str:
    raw = resource_request.get("gpu_count")
    if isinstance(raw, str):
        normalized = raw.strip().lower()
        if normalized == "auto":
            return "auto"
        return _safe_int(normalized, default=0, minimum=0)
    if raw is not None:
        return _safe_int(raw, default=0, minimum=0)
    if isinstance(gpu_hint, int):
        return max(gpu_hint, 0)
    if str(gpu_hint or "").strip().lower() == "auto":
        return "auto"
    return 0


def normalize_resource_request(
    value: Any,
    *,
    gpu_hint: int | str | None = None,
    fallback_gpu_hint: int | str | None = None,
    default_gpu_mem_mb: int = DEFAULT_GPU_MEMORY_MB,
) -> dict[str, Any]:
    payload = value if isinstance(value, dict) else {}
    hint = gpu_hint if gpu_hint is not None else fallback_gpu_hint
    gpu_count = _normalized_gpu_count(payload, hint)
    gpu_mem_mb = _safe_int(
        payload.get("gpu_mem_mb", payload.get("memory_mb", payload.get("gpu_memory_mb"))),
        default=0,
        minimum=0,
    )
    if gpu_mem_mb <= 0 and gpu_count not in {0, "auto"}:
        gpu_mem_mb = max(int(default_gpu_mem_mb or 0), 0)
    return {
        "gpu_count": gpu_count,
        "gpu_mem_mb": gpu_mem_mb,
        "cpu_cores": _safe_int(payload.get("cpu_cores"), default=1, minimum=0),
        "ram_mb": _safe_int(payload.get("ram_mb"), default=0, minimum=0),
        "shareable": _safe_bool(payload.get("shareable"), default=True),
        "exclusive": _safe_bool(payload.get("exclusive"), default=False),
    }


def normalize_expected_duration_minutes(value: Any, *, default: int = DEFAULT_EXPECTED_DURATION_MINUTES) -> int:
    return _safe_int(value, default=default, minimum=1)


def normalize_workload_label(value: Any) -> str:
    return str(value or "").strip()


def resolve_gpu_count(resource_request: dict[str, Any], *, gpu_available: bool) -> int:
    """Resolve auto GPU requests at runtime."""
    raw = resource_request.get("gpu_count")
    if isinstance(raw, str) and raw.strip().lower() == "auto":
        return 1 if gpu_available else 0
    return _safe_int(raw, default=0, minimum=0)


def resolve_gpu_mem_mb(resource_request: dict[str, Any], *, default_gpu_mem_mb: int, gpu_count: int) -> int:
    if gpu_count <= 0:
        return 0
    explicit = _safe_int(resource_request.get("gpu_mem_mb"), default=0, minimum=0)
    return explicit if explicit > 0 else max(int(default_gpu_mem_mb or 0), 0)


def resource_cost_units(resource_request: dict[str, Any], expected_duration_minutes: int) -> float:
    duration = max(int(expected_duration_minutes or DEFAULT_EXPECTED_DURATION_MINUTES), 1)
    raw_gpu_count = resource_request.get("gpu_count")
    if isinstance(raw_gpu_count, str) and raw_gpu_count.strip().lower() == "auto":
        gpu_count = 1
    else:
        gpu_count = _safe_int(raw_gpu_count, default=0, minimum=0)
    cpu_cores = _safe_int(resource_request.get("cpu_cores"), default=1, minimum=1)
    primary_width = gpu_count if gpu_count > 0 else cpu_cores
    return float(max(primary_width, 1) * duration)


def utility_density(
    scores: dict[str, Any] | None,
    *,
    resource_request: dict[str, Any],
    expected_duration_minutes: int,
) -> float:
    expected_value = _safe_int((scores or {}).get("expected_value"), default=3, minimum=1)
    return expected_value / max(resource_cost_units(resource_request, expected_duration_minutes), 1.0)


def is_backfill_candidate(
    *,
    resource_request: dict[str, Any],
    expected_duration_minutes: int,
    threshold_minutes: int,
) -> bool:
    if _safe_bool(resource_request.get("exclusive"), default=False):
        return False
    if not _safe_bool(resource_request.get("shareable"), default=True):
        return False
    return expected_duration_minutes <= max(int(threshold_minutes or 0), 0)


def sort_pending_ideas(
    ideas: list[dict],
    *,
    default_gpu_mem_mb: int = DEFAULT_GPU_MEMORY_MB,
    default_duration_minutes: int = DEFAULT_DURATION_MINUTES,
    backfill_threshold_minutes: int = 30,
) -> list[dict]:
    def _normalized(item: dict) -> tuple[dict[str, Any], int, float, bool]:
        request = normalize_resource_request(
            item.get("resource_request"),
            default_gpu_mem_mb=default_gpu_mem_mb,
            fallback_gpu_hint=item.get("gpu_hint", "auto"),
        )
        duration = normalize_expected_duration_minutes(
            item.get("expected_duration_minutes"),
            default=default_duration_minutes,
        )
        density = utility_density(
            item.get("scores"),
            resource_request=request,
            expected_duration_minutes=duration,
        )
        backfill = is_backfill_candidate(
            resource_request=request,
            expected_duration_minutes=duration,
            threshold_minutes=backfill_threshold_minutes,
        )
        return request, duration, density, backfill

    decorated: list[tuple[tuple, dict]] = []
    for item in ideas:
        request, duration, density, backfill = _normalized(item)
        decorated.append(
            (
                (
                    0 if not backfill else 1,
                    -density,
                    int(item.get("runtime_priority", item.get("priority", 9999)) or 9999),
                    int(item.get("manager_priority", item.get("priority", 9999)) or 9999),
                    duration,
                    0 if request.get("shareable", True) else 1,
                    str(item.get("id", "")),
                ),
                item,
            )
        )
    decorated.sort(key=lambda pair: pair[0])
    return [item for _, item in decorated]
