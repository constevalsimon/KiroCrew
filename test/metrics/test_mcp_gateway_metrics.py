"""Tests for MCP gateway OTEL metric emit call-sites.

Every test drives the REAL production emit path with a patched recorder and
asserts the captured metric name + attributes:

* ``kirocrew.mcp.warm_pool.acquire`` -- via ``gatewayd._emit_backend_acquire_metric``
* ``kirocrew.mcp.backend.acquire.duration`` — via ``gatewayd._emit_backend_acquire_metric``
* ``kirocrew.mcp.lazy_load.{count,duration}`` — via ``gatewayd._emit_lazy_load_metrics``

The metric names/attrs live in production (daemon/diagnostics.py), so a
rename, attribute change, or removed emit fails these tests rather than passing
green against logic the test wrote itself.
"""

from unittest.mock import patch


class _CapturingRecorder:
    """Stand-in recorder that captures every counter() and histogram() call."""

    def __init__(self) -> None:
        self.counters: list[tuple[str, dict]] = []
        self.histograms: list[tuple[str, float, str, dict]] = []

    def counter(self, name: str, *, attrs: dict | None = None, **kwargs) -> None:
        self.counters.append((name, dict(attrs or {})))

    def histogram(
        self, name: str, value: float, *, unit: str = "ms", attrs: dict | None = None, **kwargs
    ) -> None:
        self.histograms.append((name, value, unit, dict(attrs or {})))


# ---------------------------------------------------------------------------
# kirocrew.mcp.warm_pool.acquire -- daemon/diagnostics._emit_backend_acquire_metric
# ---------------------------------------------------------------------------


class TestWarmPoolAcquireCounter:
    """The acquire point counts hit/miss, with or without the prewarm store."""

    def test_warm_acquire_counts_hit(self):
        from kiro_crew.mcp_gateway.gatewayd import _emit_backend_acquire_metric

        rec = _CapturingRecorder()
        with patch("kiro_crew.mcp_gateway.gatewayd.get_recorder", return_value=rec):
            _emit_backend_acquire_metric(3.0, warm=True)
        assert rec.counters == [("kirocrew.mcp.warm_pool.acquire", {"result": "hit"})]

    def test_spawning_acquire_counts_miss(self):
        from kiro_crew.mcp_gateway.gatewayd import _emit_backend_acquire_metric

        rec = _CapturingRecorder()
        with patch("kiro_crew.mcp_gateway.gatewayd.get_recorder", return_value=rec):
            _emit_backend_acquire_metric(300.0, warm=False)
        assert rec.counters == [("kirocrew.mcp.warm_pool.acquire", {"result": "miss"})]

    def test_lazy_path_counts_once(self):
        from kiro_crew.mcp_gateway.gatewayd import _emit_lazy_load_metrics

        rec = _CapturingRecorder()
        with patch("kiro_crew.mcp_gateway.gatewayd.get_recorder", return_value=rec):
            _emit_lazy_load_metrics(5.0, warm=True)
        assert [c for c in rec.counters if c[0] == "kirocrew.mcp.warm_pool.acquire"] == [
            ("kirocrew.mcp.warm_pool.acquire", {"result": "hit"})
        ]

    def test_hot_key_tally_no_longer_emits(self, tmp_path):
        """The prewarm store keeps its tally but must not count the metric twice."""
        from kiro_crew.mcp_gateway.prewarm import HotKeyStore

        store = HotKeyStore(tmp_path / "hot-keys.json")
        rec = _CapturingRecorder()
        with patch("kiro_crew.metrics.provider.get_recorder", return_value=rec):
            store.record_outcome(hit=True)
        assert rec.counters == []
        assert store.hit_stats()["warm_pool_hits"] == 1


# ---------------------------------------------------------------------------
# kirocrew.mcp.backend.acquire.duration — gatewayd._emit_backend_acquire_metric
# ---------------------------------------------------------------------------


class TestBackendAcquireMetric:
    """The ensure_backend path emits acquire duration via this helper."""

    def test_warm_hit(self):
        from kiro_crew.mcp_gateway.gatewayd import _emit_backend_acquire_metric

        rec = _CapturingRecorder()
        with patch("kiro_crew.mcp_gateway.gatewayd.get_recorder", return_value=rec):
            _emit_backend_acquire_metric(12.5, warm=True)
        assert rec.histograms == [
            ("kirocrew.mcp.backend.acquire.duration", 12.5, "ms", {"warm": True})
        ]

    def test_cold_spawn(self):
        from kiro_crew.mcp_gateway.gatewayd import _emit_backend_acquire_metric

        rec = _CapturingRecorder()
        with patch("kiro_crew.mcp_gateway.gatewayd.get_recorder", return_value=rec):
            _emit_backend_acquire_metric(340.0, warm=False)
        assert rec.histograms == [
            ("kirocrew.mcp.backend.acquire.duration", 340.0, "ms", {"warm": False})
        ]


# ---------------------------------------------------------------------------
# kirocrew.mcp.lazy_load.{count,duration} — gatewayd._emit_lazy_load_metrics
# ---------------------------------------------------------------------------


class TestLazyLoadMetrics:
    """The lazy-spawn path emits count + duration + acquire via this helper."""

    def test_emits_count_duration_and_acquire(self):
        from kiro_crew.mcp_gateway.gatewayd import _emit_lazy_load_metrics

        rec = _CapturingRecorder()
        with patch("kiro_crew.mcp_gateway.gatewayd.get_recorder", return_value=rec):
            _emit_lazy_load_metrics(250.0, warm=False)

        # Counters: lazy_load.count, then the acquire's warm-pool outcome
        assert rec.counters == [
            ("kirocrew.mcp.lazy_load.count", {"transport": "stdio"}),
            ("kirocrew.mcp.warm_pool.acquire", {"result": "miss"}),
        ]

        # Histograms: lazy_load.duration + backend.acquire.duration
        by_name = {h[0]: h for h in rec.histograms}
        assert set(by_name) == {
            "kirocrew.mcp.lazy_load.duration",
            "kirocrew.mcp.backend.acquire.duration",
        }
        assert by_name["kirocrew.mcp.lazy_load.duration"] == (
            "kirocrew.mcp.lazy_load.duration", 250.0, "ms", {"transport": "stdio"},
        )
        assert by_name["kirocrew.mcp.backend.acquire.duration"] == (
            "kirocrew.mcp.backend.acquire.duration", 250.0, "ms", {"warm": False},
        )
