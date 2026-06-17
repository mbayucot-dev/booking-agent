"""App wiring: create_app routes, versioning, the runner dependency."""


def test_create_app_registers_versioned_routes():
    from app.main import create_app

    app = create_app()
    # Inspect the OpenAPI path map (authoritative + prefix-resolved) rather than the raw
    # app.routes, which varies by Starlette version in how included routes are flattened.
    paths = set(app.openapi()["paths"])
    assert "/api/v1/runs" in paths
    assert "/api/v1/runs/{run_id}" in paths
    assert "/api/v1/health" in paths
    # No external ServiceM8 OAuth endpoints remain.
    assert not any("servicem8" in p for p in paths)


def test_get_runner_reads_app_state():
    from types import SimpleNamespace

    from app.api import deps

    sentinel = object()
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(runner=sentinel)))
    assert deps.get_runner(request) is sentinel


def test_get_runner_falls_back_to_building_and_caches():
    from types import SimpleNamespace

    from app.api import deps

    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace()))  # lifespan didn't run
    runner = deps.get_runner(request)
    assert runner is not None
    assert request.app.state.runner is runner  # cached on app.state for reuse


def test_lifespan_seeds_and_builds_runner():
    # Entering the TestClient context runs the lifespan: best-effort staff seeding
    # plus building the shared runner onto app.state.
    from fastapi.testclient import TestClient

    from app.main import create_app

    app = create_app()
    with TestClient(app) as c:
        assert c.get("/api/v1/health").status_code == 200
        assert app.state.runner is not None
