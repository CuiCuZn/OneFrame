from __future__ import annotations

import io
from pathlib import Path

import pytest
from PIL import Image

from app import config, db
from app.core import library, prompt, router, storage
from app.errors import Unsupported
from app.providers import GenRequest
from app.providers.base import RefImage


@pytest.fixture(autouse=True)
def clean_db():
    db.init_db()
    with db.connect() as conn:
        for table in ("models", "channel_keys", "channels", "library_items", "assets", "jobs"):
            conn.execute(f"DELETE FROM {table}")
    yield


def make_channel(protocol="mock", endpoint="", enabled=1) -> str:
    channel_id = db.new_id()
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO channels(id, name, protocol, base_url, headers, enabled, note, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, '{}', ?, '', ?, ?)",
            (channel_id, f"{protocol}-channel", protocol, endpoint, enabled, db.now(), db.now()),
        )
    return channel_id


def make_model(
    modality="image",
    caps=None,
    params=None,
    channel_id="",
    upstream="mock-image",
) -> str:
    model_id = db.new_id()
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO models(id, name, modality, channel_id, upstream_model, description, enabled, "
            "caps, params, price, overrides, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, '', 1, ?, ?, '{}', '{}', ?, ?)",
            (
                model_id,
                "Test Model",
                modality,
                channel_id,
                upstream,
                db.dumps(caps or {"max_refs": 2, "max_count": 4, "features": ["reference"]}),
                db.dumps(params or {"size": ["1024x1024"]}),
                db.now(),
                db.now(),
            ),
        )
    return model_id


def test_prompt_recipe_orders_roles_and_marks_mapping():
    result = prompt.compile_recipe(
        {
            "refs": [
                {"role": "costume", "title": "风衣"},
                {"role": "character", "title": "短发"},
            ],
            "style": "cinematic",
            "extra": "雨夜天台",
            "language": "zh",
        }
    )
    text = result["prompt"]
    assert "图1 = 人物外貌" in text
    assert "图2 = 服装造型" in text
    assert "让同一个人物穿上图2" in text
    assert "雨夜天台" in text
    assert "电影" in text
    assert result["negative"]


def test_prompt_recipe_english():
    result = prompt.compile_recipe(
        {"refs": [{"role": "pose", "title": "standing"}], "language": "en", "extra": "rooftop"}
    )
    assert "image 1 = pose and framing" in result["prompt"]
    assert "take only the pose" in result["prompt"]


def test_router_rejects_too_many_refs():
    channel = make_channel()
    model_id = make_model(channel_id=channel, upstream="mock-image")
    with db.connect() as conn:
        model = router.load_model(conn, model_id)
        req = GenRequest(model="", prompt="x", refs=[RefImage() for _ in range(3)])
        with pytest.raises(Unsupported):
            router.check(conn, model, req)


def test_router_binds_one_channel_and_validates_parameters():
    channel = make_channel()
    model_id = make_model(channel_id=channel, upstream="mock-image")
    with db.connect() as conn:
        model = router.load_model(conn, model_id)
        assert model["channel_id"] == channel
        assert model["upstream_model"] == "mock-image"
        assert model["available"] is True
        router.check(conn, model, GenRequest(model="mock-image", prompt="x", count=1))
        with pytest.raises(Unsupported):
            router.check(conn, model, GenRequest(model="mock-image", prompt="x", params={"aspect_ratio": "5:4"}))
        with pytest.raises(Unsupported):
            router.check(conn, model, GenRequest(model="mock-image", prompt="x", params={"resolution": "8K"}))


def test_model_without_channel_is_unavailable():
    model_id = make_model()
    with db.connect() as conn:
        model = router.load_model(conn, model_id)
        assert model["available"] is False
        assert model["reason"] == "未绑定服务渠道"


def test_key_pool_skips_cooling_and_disabled():
    channel = make_channel(protocol="openai_image", endpoint="https://relay.example.com/v1")
    with db.connect() as conn:
        for label, cooldown, enabled in [
            ("cooling", "2999-01-01T00:00:00+00:00", 1),
            ("disabled", None, 0),
            ("healthy", None, 1),
        ]:
            conn.execute(
                "INSERT INTO channel_keys(id, channel_id, label, secret, enabled, status, cooldown_until, created_at) "
                "VALUES (?, ?, ?, 'x', ?, 'untested', ?, ?)",
                (db.new_id(), channel, label, enabled, cooldown, db.now()),
            )
        key = router.pick_key(conn, channel)
        assert key is not None and key["label"] == "healthy"


def test_storage_saves_image_and_thumbnail():
    buffer = io.BytesIO()
    Image.new("RGB", (300, 200), (120, 40, 200)).save(buffer, "PNG")
    record = storage.save_output(buffer.getvalue(), "image")
    assert record["width"] == 300 and record["height"] == 200
    path = config.DATA_DIR / record["path"]
    thumb = config.DATA_DIR / record["thumb_path"]
    assert path.exists() and thumb.exists()
    with Image.open(thumb) as image:
        assert max(image.size) <= 640


def test_library_rejects_paths_outside_roots(tmp_path: Path):
    with pytest.raises(PermissionError):
        library.resolve_allowed(str(tmp_path))


def test_library_folder_import(tmp_path: Path):
    with db.connect() as conn:
        db.set_setting(conn, "library_roots", str(tmp_path))
    folder = tmp_path / "set" / "cat"
    folder.mkdir(parents=True)
    for index in range(2):
        Image.new("RGB", (120, 160), (30 * index, 80, 120)).save(folder / f"a{index}.png")

    result = library.import_folder(str(tmp_path / "set"), kind="pose")
    assert result["added"] == 2
    with db.connect() as conn:
        rows = library.list_items(conn, kind="pose")
        assert rows["total"] == 2
        item = rows["items"][0]
        path, _ = library.file_for(conn, item["id"], prefer_thumb=True)
        assert path.exists()
    again = library.import_folder(str(tmp_path / "set"), kind="pose")
    assert again["added"] == 0

