from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app import db
from app.core import library, taxonomy
from app.main import app


@pytest.fixture(autouse=True)
def clean_library():
    db.init_db()
    with db.connect() as conn:
        conn.execute("DELETE FROM library_items")
        conn.execute("DELETE FROM library_facets")
        conn.execute("DELETE FROM assets")
        conn.execute("DELETE FROM jobs")
    yield


def test_pose_keeps_series_class_and_angle():
    classification = taxonomy.classify_pose(
        {
            "id": "full_sexy_P001_front",
            "体系": "全身单人・性感系",
            "分类": "站姿",
            "角度": "正面",
            "姿势名称": "S形站姿・胯部侧顶",
            "姿势编号": "P001",
        }
    )
    assert classification.category == "站姿"
    assert classification.category_path == "全身单人・性感系 / 站姿"
    assert ("姿势分类", "站姿", 2) in classification.facets
    assert ("角度", "正面", 3) in classification.facets
    assert "p001" in classification.search_text
    assert "站姿" in classification.search_text


def test_costume_derives_garment_types_and_colours():
    classification = taxonomy.classify_costume(
        {
            "id": "SPR-0001",
            "分类": "春季穿搭",
            "服装名称": "象牙白荷叶边针织衫・牛仔迷你半身裙・大衣・短袜・白色运动鞋",
            "标签": ["象牙白", "荷叶边", "针织", "牛仔", "迷你", "半身裙", "大衣", "短袜", "白色", "运动鞋"],
            "关键词": "ivory frill knit denim mini skirt coat socks white sneakers",
        }
    )
    assert classification.category == "上装"
    assert classification.category_path == "春季穿搭 / 上装"
    types = [value for name, value, _ in classification.facets if name == "品类"]
    assert types == ["上装", "半身裙", "外套", "袜类", "鞋履"]
    colours = {value for name, value, _ in classification.facets if name == "颜色"}
    assert {"象牙白", "白色"} <= colours
    assert "ivory frill" in classification.search_text


def test_folder_import_builds_tree_and_multitoken_search(tmp_path: Path):
    with db.connect() as conn:
        db.set_setting(conn, "library_roots", str(tmp_path))
    root = tmp_path / "set"
    for folder in ("正面", "侧面"):
        directory = root / "人像" / folder
        directory.mkdir(parents=True)
        Image.new("RGB", (120, 160), (40, 70, 110)).save(directory / f"{folder}.png")

    result = library.import_folder(str(root), kind="custom")
    assert result["added"] == 2

    with db.connect() as conn:
        tree = library.facets(conn, kind="custom")["tree"]
        assert tree[0]["label"] == "素材"
        assert tree[0]["children"][0]["value"] == "人像"
        assert {child["value"] for child in tree[0]["children"][0]["children"]} == {"正面", "侧面"}

        both = library.list_items(conn, kind="custom", query="人像 正面")
        assert both["total"] == 1
        assert both["items"][0]["category"] == "正面"
        assert both["items"][0]["category_path"] == "人像 / 正面"
        assert both["items"][0]["facets"]["目录"] == ["人像", "正面"]

        filtered = library.list_items(conn, kind="custom", facets=[("目录", "侧面")])
        assert filtered["total"] == 1

        missing = library.list_items(conn, kind="custom", query="人像 不存在")
        assert missing["total"] == 0


def test_rebuild_reclassifies_legacy_rows(tmp_path: Path):
    image = tmp_path / "人像" / "正面" / "a.png"
    image.parent.mkdir(parents=True)
    Image.new("RGB", (80, 100), (10, 20, 30)).save(image)

    with db.connect() as conn:
        conn.execute(
            "INSERT INTO library_items (id, source, external_id, kind, title, subtitle, category,"
            " image_path, created_at) VALUES ('legacy', 'folder:x', '人像/正面/a.png', 'custom',"
            " 'a', '人像/正面/a.png', '旧分类', ?, ?)",
            (str(image), db.now()),
        )
        library.rebuild_taxonomy(conn)
        row = db.one(conn, "SELECT * FROM library_items WHERE id = 'legacy'")
        assert row["category"] == "正面"
        assert row["category_path"] == "人像 / 正面"
        assert "正面" in row["search_text"]
        facets = library.item_facets(conn, "legacy")
        assert facets["目录"] == ["人像", "正面"]


def test_rebuild_keeps_classification_without_source_json(tmp_path: Path):
    image = tmp_path / "x.png"
    Image.new("RGB", (90, 110), (90, 20, 30)).save(image)

    with db.connect() as conn:
        conn.execute(
            "INSERT INTO library_items (id, source, external_id, kind, title, subtitle, category,"
            " image_path, created_at) VALUES ('costume-1', 'pose-gallery:missing', 'costume:A1',"
            " 'costume', '黑色针织衫・迷你半身裙', 'A1', '上装', ?, ?)",
            (str(image), db.now()),
        )
        conn.executemany(
            "INSERT INTO library_facets (item_id, field, value, level) VALUES (?, ?, ?, ?)",
            [
                ("costume-1", "风格", "春季穿搭", 1),
                ("costume-1", "主类", "上装", 2),
                ("costume-1", "品类", "上装", 3),
            ],
        )
        library.rebuild_taxonomy(conn)
        row = db.one(conn, "SELECT * FROM library_items WHERE id = 'costume-1'")
        assert row["category_path"] == "春季穿搭 / 上装"
        assert library.item_facets(conn, "costume-1")["主类"] == ["上装"]


def test_nsfw_items_are_hidden_until_enabled(tmp_path: Path):
    image = tmp_path / "a.png"
    Image.new("RGB", (80, 100), (10, 20, 30)).save(image)

    with db.connect() as conn:
        for item_id, nsfw in (("safe", 0), ("adult", 1)):
            conn.execute(
                "INSERT INTO library_items (id, source, external_id, kind, title, subtitle, category,"
                " category_path, image_path, nsfw, meta, created_at) VALUES (?, 'folder:x', ?, 'pose',"
                " '测试', '测试', '站姿', '全身单人 / 站姿', ?, ?, '{}', ?)",
                (item_id, item_id, str(image), nsfw, db.now()),
            )
            conn.executemany(
                "INSERT INTO library_facets (item_id, field, value, level) VALUES (?, ?, ?, ?)",
                [
                    (item_id, "构图", "全身单人", 1),
                    (item_id, "姿势分类", "站姿", 2),
                ],
            )

        hidden = library.list_items(conn, kind="pose", include_nsfw=False)
        assert hidden["total"] == 1
        assert hidden["items"][0]["id"] == "safe"

        shown = library.list_items(conn, kind="pose", include_nsfw=True)
        assert shown["total"] == 2

        facets = library.facets(conn, kind="pose", include_nsfw=False)
        assert facets["total"] == 1
        assert facets["nsfw_hidden"] == 1
        assert facets["visible_total"] == 1
        assert facets["tree"][0]["count"] == 1


def test_generated_asset_can_be_saved_as_reference(tmp_path: Path):
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO assets (id, kind, path, thumb_path, width, height, prompt, model_name,"
            " origin, meta, created_at) VALUES ('asset1', 'image', 'media/2026/11/a.webp',"
            " 'media/2026/11/a_thumb.webp', 1024, 1024, '霓虹街头，回头', 'demo', 'generated',"
            " '{}', ?)",
            (db.now(),),
        )
        asset = db.one(conn, "SELECT * FROM assets WHERE id = 'asset1'")
        item_id, created = library.add_asset_reference(conn, asset)
        assert created is True
        again_id, again_created = library.add_asset_reference(conn, asset)
        assert again_created is False and again_id == item_id
        row = db.one(conn, "SELECT * FROM library_items WHERE id = ?", (item_id,))
        assert row["kind"] == "work"
        assert row["category_path"] == "我的作品"
        assert row["nsfw"] == 0
        assert library.item_facets(conn, item_id)["目录"] == ["我的作品"]

    with TestClient(app) as client:
        response = client.post("/api/library/assets/asset1")
        assert response.status_code == 200
        assert response.json()["created"] is False


def test_jobs_api_exposes_duration_and_search():
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO jobs (id, model_id, model_name, channel_name, modality, request, status, stage, progress,"
            " route_id, channel_id, key_id, upstream_job_id, attempts, error, price, currency,"
            " canceled, created_at, started_at, finished_at) VALUES ('job1', 'm1', 'demo-model', '智谱AI',"
            " 'image', ?, 'succeeded', '完成', 1, NULL, NULL, NULL, NULL, '[]', NULL, 0.02, 'CNY',"
            " 0, ?, ?, ?)",
            (
                db.dumps({"prompt": "雨夜霓虹人像", "refs": []}),
                "2026-01-01T00:00:00+00:00",
                "2026-01-01T00:00:02+00:00",
                "2026-01-01T00:00:09+00:00",
            ),
        )

    with TestClient(app) as client:
        payload = client.get("/api/jobs", params={"q": "霓虹"}).json()
        assert payload["total"] == 1
        job = payload["items"][0]
        assert job["duration_ms"] == 7000
        assert job["prompt"] == "雨夜霓虹人像"
        assert job["channel_name"] == "智谱AI"
        # 验证支持按厂商名检索
        vendor_payload = client.get("/api/jobs", params={"q": "智谱"}).json()
        assert vendor_payload["total"] == 1
        assert vendor_payload["items"][0]["channel_name"] == "智谱AI"
        assert client.get("/api/jobs", params={"q": "不存在"}).json()["total"] == 0


def test_api_accepts_repeated_facet_filters(tmp_path: Path):
    with db.connect() as conn:
        db.set_setting(conn, "library_roots", str(tmp_path))
    folder = tmp_path / "refs" / "暖色"
    folder.mkdir(parents=True)
    Image.new("RGB", (100, 120), (200, 90, 40)).save(folder / "orange.png")
    library.import_folder(str(tmp_path), kind="custom")

    with TestClient(app) as client:
        payload = client.get("/api/library/facets", params={"kind": "custom"}).json()
        assert payload["grand_total"] == 1
        assert payload["tree"][0]["children"][0]["value"] == "refs"

        listing = client.get(
            "/api/library", params=[("kind", "custom"), ("facet", "目录:暖色")]
        ).json()
        assert listing["total"] == 1
        assert listing["items"][0]["category"] == "暖色"
