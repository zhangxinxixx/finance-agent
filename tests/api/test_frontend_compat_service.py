import pytest
from fastapi.testclient import TestClient

from apps.api.main import app
from apps.api.services import frontend_compat_service as service


@pytest.fixture
def frontend_roots(tmp_path, monkeypatch):
    dist = tmp_path / "dist"
    public = tmp_path / "public"
    (dist / "assets").mkdir(parents=True)
    public.mkdir()
    monkeypatch.setattr(service, "_FRONTEND_DIST_DIR", dist)
    monkeypatch.setattr(service, "_FRONTEND_PUBLIC_DIR", public)
    return dist, public


def test_nested_asset_is_served(frontend_roots):
    dist, _ = frontend_roots
    asset = dist / "assets" / "nested" / "app.js"
    asset.parent.mkdir()
    asset.write_text("console.log('isolated');")
    assert service.resolve_frontend_asset("nested/app.js") == asset
    response = TestClient(app).get("/assets/nested/app.js")
    assert response.status_code == 200
    assert response.text == "console.log('isolated');"


@pytest.mark.parametrize("escape", ["prefix", "symlink", "absolute"])
def test_assets_cannot_escape_root(frontend_roots, escape):
    dist, _ = frontend_roots
    outside = dist / "assets-copy" / "private.js"
    outside.parent.mkdir()
    outside.write_text("private")
    if escape == "prefix":
        asset_path = "../assets-copy/private.js"
    elif escape == "symlink":
        (dist / "assets" / "linked").symlink_to(outside.parent, target_is_directory=True)
        asset_path = "linked/private.js"
    else:
        asset_path = str(outside)
    assert service.resolve_frontend_asset(asset_path) is None
    if escape == "symlink":
        assert TestClient(app).get("/assets/linked/private.js").status_code == 404


@pytest.mark.parametrize("root_index", [0, 1])
@pytest.mark.parametrize("escape", ["prefix", "symlink", "absolute"])
def test_root_assets_cannot_escape_either_root(frontend_roots, root_index, escape):
    root = frontend_roots[root_index]
    outside = root.with_name(root.name + "-copy") / "private.svg"
    outside.parent.mkdir()
    outside.write_text("private")
    if escape == "prefix":
        asset_name = f"../{outside.parent.name}/private.svg"
    elif escape == "symlink":
        (root / "private.svg").symlink_to(outside)
        asset_name = "private.svg"
    else:
        asset_name = str(outside)
    assert service.resolve_frontend_root_asset(asset_name) is None


def test_root_assets_preserve_dist_precedence_and_public_fallback(frontend_roots):
    dist, public = frontend_roots
    (public / "favicon.svg").write_text("public")
    assert service.resolve_frontend_root_asset("favicon.svg") == public / "favicon.svg"
    (dist / "favicon.svg").write_text("dist")
    assert service.resolve_frontend_root_asset("favicon.svg") == dist / "favicon.svg"
    assert TestClient(app).get("/favicon.svg").text == "dist"
    assert service.resolve_frontend_asset("missing.js") is None
    assert service.resolve_frontend_root_asset("missing.svg") is None


def test_rejected_dist_symlink_still_allows_safe_public_fallback(frontend_roots):
    dist, public = frontend_roots
    outside = dist.parent / "outside.svg"
    outside.write_text("private")
    (dist / "favicon.svg").symlink_to(outside)
    (public / "favicon.svg").write_text("public")
    assert service.resolve_frontend_root_asset("favicon.svg") == public / "favicon.svg"
