from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app import db
from app.core import library
from app.main import app


@pytest.fixture(autouse=True)
def clean_library():
    db.init_db()
    with db.connect() as conn:
        conn.execute("DELETE FROM library_items")
        conn.execute("DELETE FROM library_facets")
        conn.execute("DELETE FROM app_meta WHERE k = 'library_variants'")
    yield


def _image(path: Path, color=(30, 60, 100)) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (120, 160), color).save(path)


def _gallery(tmp_path: Path) -> Path:
    root = tmp_path / "gallery"
    data = root / "data"
    data.mkdir(parents=True)
    pose_id = "full_sexy_P001_front"
    _image(root / "img" / f"{pose_id}.png")
    _image(root / "thumbs" / f"{pose_id}.jpg")
    _image(root / "img" / "depth" / f"{pose_id}.webp")
    _image(root / "thumbs" / "depth" / f"{pose_id}.webp")
    (data / "pose-zh.json").write_text(
        json.dumps(
            [
                {
                    "id": pose_id,
                    "体系": "全身单人・性感系",
                    "分类": "站姿",
                    "姿势名称": "S形站姿",
                    "姿势编号": "P001",
                    "角度": "正面",
                    "缩略图": f"thumbs/{pose_id}.jpg",
                    "原图": f"img/{pose_id}.png",
                }
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (data / "costume-zh.json").write_text("[]", encoding="utf-8")
    (data / "portrait-zh.json").write_text("[]", encoding="utf-8")
    views = []
    for view_id, label in (("front", "正面"), ("diag", "斜侧")):
        _image(root / "img" / "costumes" / "shisei" / f"costume_C001_{view_id}.webp")
        _image(root / "thumbs" / "costumes" / "shisei" / f"costume_C001_{view_id}.webp")
        views.append(
            {
                "id": view_id,
                "label": label,
                "缩略图": f"thumbs/costumes/shisei/costume_C001_{view_id}.webp",
                "预览图": f"img/costumes/shisei/costume_C001_{view_id}.webp",
                "原图": f"img/costumes/shisei/costume_C001_{view_id}.webp",
            }
        )
    (data / "costume-shisei-zh.json").write_text(
        json.dumps(
            [
                {
                    "id": "shisei-C001",
                    "分类": "中国历代",
                    "服装名称": "商 · 上衣下裳",
                    "标签": ["商", "男性"],
                    "关键词": "shang dynasty",
                    "views": views,
                    "缩略图": views[0]["缩略图"],
                    "原图": views[0]["原图"],
                }
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (data / "costume-gia-anime-zh.json").write_text(
        json.dumps(
            [
                {
                    "id": "gia-anime-SPR-0001",
                    "分类": "春季穿搭",
                    "服装名称": "远程动漫服装",
                    "原图": "https://example.com/a.png",
                }
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (data / "costume-anime-zh.json").write_text("[]", encoding="utf-8")
    return root


def test_import_shisei_and_depth(tmp_path: Path):
    root = _gallery(tmp_path)
    with db.connect() as conn:
        db.set_setting(conn, "library_roots", str(root))
    result = library.import_pose_gallery(str(root))
    assert result["added"] == 3
    assert result["depth_added"] == 1
    assert result["skipped_remote"] == 1
    assert result["sources"]["pose"] == 1

    with db.connect() as conn:
        pose = db.one(conn, "SELECT * FROM library_items WHERE kind = 'pose'")
        assert pose["group_key"] == "pose:全身单人・性感系:P001"
        assert pose["variant_label"] == "正面"
        assert pose["has_depth"] == 1
        assert Path(pose["depth_path"]).exists()
        shisei = db.rows(conn, "SELECT * FROM library_items WHERE group_key = 'shisei:shisei-C001'")
        assert len(shisei) == 2
        assert {row["variant_label"] for row in shisei} == {"正面", "斜侧"}
        assert all(row["category_path"] for row in shisei)

        depth_items = library.list_items(conn, kind="pose", depth_only=True)
        assert depth_items["total"] == 1
        item = library.serialize_item(pose)
        assert item["depth_url"].endswith("variant=depth")
        assert "image_path" not in item

        variants = library.item_variants(conn, pose["id"])
        assert variants["group_key"] == "pose:全身单人・性感系:P001"
        assert len(variants["items"]) == 1

        random = library.random_item(conn, kind="pose")
        assert random and random["id"] == pose["id"]


def test_reimport_is_idempotent_and_updates_depth(tmp_path: Path):
    root = _gallery(tmp_path)
    with db.connect() as conn:
        db.set_setting(conn, "library_roots", str(root))
    first = library.import_pose_gallery(str(root))
    second = library.import_pose_gallery(str(root))
    assert first["added"] == 3
    assert second["added"] == 0
    assert second["updated"] >= 3


def test_api_variants_depth_and_random(tmp_path: Path):
    root = _gallery(tmp_path)
    with db.connect() as conn:
        db.set_setting(conn, "library_roots", str(root))
    library.import_pose_gallery(str(root))
    with db.connect() as conn:
        db.set_setting(conn, "library_nsfw", "1")
        pose = db.one(conn, "SELECT * FROM library_items WHERE kind = 'pose'")
        shisei = db.one(conn, "SELECT * FROM library_items WHERE group_key = 'shisei:shisei-C001'")

    with TestClient(app) as client:
        depth = client.get(f"/api/library/{pose['id']}/file", params={"variant": "depth"})
        assert depth.status_code == 200
        assert depth.headers["content-type"].startswith("image/")
        variants = client.get(f"/api/library/{shisei['id']}/variants")
        assert variants.status_code == 200
        assert len(variants.json()["items"]) == 2
        random = client.get("/api/library/random", params={"kind": "pose"})
        assert random.status_code == 200
        assert random.json()["id"] == pose["id"]
        listing = client.get("/api/library", params={"depth": "true"}).json()
        assert listing["total"] == 1
