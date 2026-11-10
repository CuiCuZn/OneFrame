"""In-process job runner: one model, one channel, no cross-vendor fallback."""

from __future__ import annotations

import asyncio
import contextlib
import io
import traceback
from pathlib import Path
from typing import Any

import httpx
from PIL import Image, ImageOps

from .. import config, crypto, db
from ..errors import ProviderError, Unsupported
from ..providers import ProviderContext, RefImage
from ..providers.base import SubmitResult
from . import library, router, storage

POLL_TIMEOUT = {"image": 900, "video": 2400}

def _attempt(conn, job_id: str, entry: dict[str, Any]) -> None:
    job = db.one(conn, "SELECT attempts FROM jobs WHERE id = ?", (job_id,))
    attempts = db.loads(job["attempts"], []) if job else []
    attempts.append({"at": db.now(), **entry})
    conn.execute("UPDATE jobs SET attempts = ? WHERE id = ?", (db.dumps(attempts[-40:]), job_id))


def _set(conn, job_id: str, **fields: Any) -> None:
    if not fields:
        return
    columns = ", ".join(f"{key} = ?" for key in fields)
    conn.execute(f"UPDATE jobs SET {columns} WHERE id = ?", (*fields.values(), job_id))


def _refs_snapshot(refs: list[dict]) -> list[dict[str, Any]]:
    snapshot: list[dict[str, Any]] = []
    for ref in refs or []:
        entry: dict[str, Any] = {
            "role": ref.get("role") or "reference",
            "name": ref.get("name") or "",
            "variant": ref.get("variant") or "base",
        }
        if ref.get("asset_id"):
            entry.update({"source": "asset", "id": ref["asset_id"]})
        elif ref.get("library_id"):
            entry.update({"source": "library", "id": ref["library_id"]})
        else:
            continue
        snapshot.append(entry)
    return snapshot


def _load_ref(path: Path, role: str, name: str, max_side: int = 2048) -> RefImage:
    data = path.read_bytes()
    mime = storage.sniff_mime(data)
    if mime.startswith("image/"):
        try:
            with Image.open(io.BytesIO(data)) as image:
                image = ImageOps.exif_transpose(image)
                if max(image.size) > max_side or mime not in ("image/png", "image/jpeg"):
                    image = image.convert("RGB")
                    image.thumbnail((max_side, max_side), Image.LANCZOS)
                    buffer = io.BytesIO()
                    image.save(buffer, "JPEG", quality=92)
                    data, mime = buffer.getvalue(), "image/jpeg"
        except Exception:
            pass
    return RefImage(name=name, mime=mime, data=data, role=role)


def _resolve_refs(conn, refs: list[dict], modality: str) -> list[RefImage]:
    resolved: list[RefImage] = []
    total = 0
    for ref in refs[:16]:
        path: Path | None = None
        name = ref.get("name") or "reference"
        if ref.get("asset_id"):
            asset = db.one(conn, "SELECT * FROM assets WHERE id = ?", (ref["asset_id"],))
            if asset and asset.get("path"):
                path = storage.resolve_media(asset["path"])
                name = name if name != "reference" else (asset.get("prompt") or "reference")[:40]
        elif ref.get("library_id"):
            item = db.one(conn, "SELECT * FROM library_items WHERE id = ?", (ref["library_id"],))
            if item:
                variant = ref.get("variant") or "base"
                rel = item.get("depth_path") if variant == "depth" and item.get("depth_path") else item.get("image_path")
                candidate = Path(rel) if rel else None
                path = candidate if candidate and candidate.exists() and library.is_allowed(candidate) else None
                name = name if name != "reference" else (item.get("title") or "reference")[:40]
        if not path or not path.exists():
            continue
        ref_image = _load_ref(path, ref.get("role", "reference"), name)
        total += len(ref_image.data or b"")
        if total > 30 * 1024 * 1024:
            raise Unsupported("参考图总大小超过 30MB，请先压缩")
        resolved.append(ref_image)
    return resolved


def _load_mask(request: dict) -> RefImage | None:
    rel = request.get("mask_path")
    if not rel:
        return None
    path = storage.resolve_media(rel)
    if not path:
        raise Unsupported("蒙版文件已丢失")
    data = path.read_bytes()
    if not data.startswith(b"\x89PNG\r\n\x1a\n"):
        raise Unsupported("蒙版不是 PNG")
    return RefImage(name="mask", mime="image/png", data=data, role="mask")


def _align_mask(refs: list[RefImage], mask: RefImage | None) -> RefImage | None:
    """Provider edits require image and mask to share exactly one pixel size."""

    if not mask or not refs or not refs[0].data or not mask.data:
        return mask
    try:
        with Image.open(io.BytesIO(refs[0].data)) as source:
            size = source.size
        with Image.open(io.BytesIO(mask.data)) as layer:
            layer = layer.convert("RGBA")
            if layer.size != size:
                layer = layer.resize(size, Image.NEAREST)
            buffer = io.BytesIO()
            layer.save(buffer, "PNG")
        mask.data = buffer.getvalue()
        mask.mime = "image/png"
        return mask
    except Exception as exc:
        raise Unsupported("蒙版与源图尺寸不匹配") from exc


def _transport_error(exc: Exception) -> ProviderError:
    if isinstance(exc, (httpx.ConnectError, httpx.ConnectTimeout)):
        return ProviderError("无法连接上游服务，请检查地址与网络", kind="connect", retryable=True)
    if isinstance(exc, (httpx.ReadTimeout, httpx.WriteTimeout, httpx.RemoteProtocolError)):
        return ProviderError(
            "上游长时间无响应，请求可能已提交；为避免重复扣费已停止自动重试",
            kind="network",
            ambiguous=True,
            retryable=False,
        )
    if isinstance(exc, httpx.HTTPError):
        return ProviderError(f"网络异常：{type(exc).__name__}", kind="network", retryable=True)
    return ProviderError(str(exc) or "上游调用失败", kind="upstream")


class JobRunner:
    def __init__(self) -> None:
        self._scheduler: asyncio.Task | None = None
        self._running: dict[str, asyncio.Task] = {}
        self._image_gate = asyncio.Semaphore(config.IMAGE_WORKERS)
        self._video_gate = asyncio.Semaphore(config.VIDEO_WORKERS)
        self._stopping = False
        self._client: httpx.AsyncClient | None = None

    # ── lifecycle ──────────────────────────────────────────────────────────
    async def start(self) -> None:
        self._stopping = False
        self._running.clear()
        self._image_gate = asyncio.Semaphore(config.IMAGE_WORKERS)
        self._video_gate = asyncio.Semaphore(config.VIDEO_WORKERS)
        self._client = httpx.AsyncClient(follow_redirects=True, timeout=httpx.Timeout(180.0, connect=30.0))
        with db.connect() as conn:
            stale = db.rows(
                conn,
                "SELECT id FROM jobs WHERE status IN ('submitting','downloading','polling')",
            )
            for job in stale:
                _set(
                    conn,
                    job["id"],
                    status="failed",
                    error="应用在生成过程中退出，请检查上游任务后再决定是否重试",
                    finished_at=db.now(),
                )
            resumable = db.rows(
                conn,
                "SELECT id FROM jobs WHERE status = 'running' AND upstream_job_id IS NOT NULL",
            )
            for job in resumable:
                _set(conn, job["id"], status="queued", stage="恢复轮询")
        self._scheduler = asyncio.create_task(self._loop(), name="oneframe-scheduler")

    async def stop(self) -> None:
        self._stopping = True
        if self._scheduler:
            self._scheduler.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._scheduler
        for task in list(self._running.values()):
            task.cancel()
        if self._running:
            await asyncio.gather(*self._running.values(), return_exceptions=True)
        if self._client:
            await self._client.aclose()

    async def _loop(self) -> None:
        while not self._stopping:
            try:
                await self._tick()
            except Exception:  # pragma: no cover - keep the loop alive
                traceback.print_exc()
            await asyncio.sleep(0.7)

    async def _tick(self) -> None:
        capacity = config.IMAGE_WORKERS + config.VIDEO_WORKERS - len(self._running)
        if capacity <= 0:
            return
        with db.connect() as conn:
            rows = db.rows(
                conn,
                "SELECT id FROM jobs WHERE status = 'queued' ORDER BY created_at LIMIT ?",
                (capacity * 2,),
            )
        for row in rows:
            if len(self._running) >= config.IMAGE_WORKERS + config.VIDEO_WORKERS:
                break
            job_id = row["id"]
            if job_id in self._running:
                continue
            task = asyncio.create_task(self._run(job_id), name=f"job-{job_id}")
            self._running[job_id] = task
            task.add_done_callback(lambda _task, jid=job_id: self._running.pop(jid, None))

    # ── execution ──────────────────────────────────────────────────────────
    async def _run(self, job_id: str) -> None:
        with db.connect() as conn:
            job = db.one(conn, "SELECT modality FROM jobs WHERE id = ?", (job_id,))
        if not job:
            return
        gate = self._video_gate if job["modality"] == "video" else self._image_gate
        async with gate:
            try:
                await self._execute(job_id)
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # pragma: no cover - defensive
                with db.connect() as conn:
                    _set(
                        conn,
                        job_id,
                        status="failed",
                        error=f"内部错误：{exc}",
                        finished_at=db.now(),
                    )
                traceback.print_exc()

    async def _execute(self, job_id: str) -> None:
        with db.connect() as conn:
            job = db.one(conn, "SELECT * FROM jobs WHERE id = ?", (job_id,))
            if not job or job["status"] != "queued":
                return
            claimed = conn.execute(
                "UPDATE jobs SET status='submitting', started_at=COALESCE(started_at, ?), stage='准备请求' "
                "WHERE id = ? AND status = 'queued'",
                (db.now(), job_id),
            ).rowcount
            if not claimed:
                return
            request = db.loads(job["request"], {})
            request.setdefault("modality", job["modality"])
            model = router.load_model(conn, job["model_id"])

        req = router.build_request(
            upstream_model=model["upstream_model"],
            prompt=request.get("prompt", ""),
            negative=request.get("negative", ""),
            refs=[],
            count=int(request.get("count", 1)),
            params=request.get("params", {}),
        )
        if job["upstream_job_id"]:
            await self._resume_poll(job_id, job, model, req, request)
            return

        try:
            with db.connect() as conn:
                router.check(conn, model, req)
        except Unsupported as exc:
            with db.connect() as conn:
                _set(conn, job_id, status="failed", stage="失败", error=exc.message, finished_at=db.now())
            return

        with db.connect() as conn:
            try:
                refs = _resolve_refs(conn, request.get("refs", []), job["modality"])
            except (Unsupported, OSError) as exc:
                _set(conn, job_id, status="failed", stage="失败", error=str(exc), finished_at=db.now())
                return
            key = router.pick_key(conn, model["channel_id"]) if router.needs_key(model) else None
            if router.needs_key(model) and not key:
                _set(
                    conn,
                    job_id,
                    status="failed",
                    stage="失败",
                    error="该渠道没有可用密钥（缺失或全部冷却中）",
                    finished_at=db.now(),
                )
                return

        try:
            req.mask = _load_mask(request)
        except (Unsupported, OSError) as exc:
            with db.connect() as conn:
                _set(conn, job_id, status="failed", stage="失败", error=str(exc), finished_at=db.now())
            return
        if req.mask and len(refs) != 1:
            with db.connect() as conn:
                _set(conn, job_id, status="failed", stage="失败", error="局部重绘需要且只需要一张源图", finished_at=db.now())
            return
        req.mask = _align_mask(refs, req.mask)

        target = router.target(model)
        await self._attempt_once(job_id, target, req, refs, request, key)

    async def _attempt_once(
        self,
        job_id: str,
        target: router.Target,
        req,
        refs: list[RefImage],
        request: dict[str, Any],
        key: dict | None,
    ) -> str | ProviderError:
        provider_req = router.build_request(
            upstream_model=target.upstream_model,
            prompt=req.prompt,
            negative=req.negative,
            refs=refs,
            count=req.count,
            params=req.params,
            mask=req.mask,
        )
        await self._set_async(job_id, stage=f"提交到 {target.channel_name}", progress=0.05)
        key_secret = crypto.decrypt(key["secret"]) if key else ""
        key_id = key["id"] if key else None
        with db.connect() as conn:
            _set(conn, job_id, channel_id=target.channel_id, channel_name=target.channel_name, key_id=key_id)
            _attempt(
                conn,
                job_id,
                {
                    "phase": "submit",
                    "channel": target.channel_name,
                    "model": target.upstream_model,
                    "key": key["label"] if key else "",
                },
            )

        ctx = ProviderContext(
            client=self._client,  # type: ignore[arg-type]
            base_url=target.base_url,
            api_key=key_secret,
            headers=target.headers,
            request=provider_req,
            overrides=target.overrides,
            modality=request.get("modality", "image"),
            timeout=float(target.overrides.get("timeout", 600 if request.get("modality") == "video" else 240)),
        )
        try:
            result = await target.adapter.submit(ctx)
        except ProviderError as exc:
            with db.connect() as conn:
                _attempt(
                    conn,
                    job_id,
                    {
                        "phase": "error",
                        "channel": target.channel_name,
                        "kind": exc.kind,
                        "message": exc.message,
                    },
                )
                if exc.kind in {"auth", "quota"}:
                    router.record_key_failure(conn, key_id, exc)
            if exc.ambiguous:
                with db.connect() as conn:
                    _set(
                        conn,
                        job_id,
                        status="uncertain",
                        stage="待核对",
                        error=exc.message,
                        finished_at=db.now(),
                    )
                return "stop"
            with db.connect() as conn:
                _set(conn, job_id, status="failed", stage="失败", error=exc.message, finished_at=db.now())
            return "stop"
        except Exception as exc:  # unexpected adapter bug or transport error
            error = _transport_error(exc)
            with db.connect() as conn:
                _attempt(
                    conn,
                    job_id,
                    {"phase": "error", "channel": target.channel_name, "kind": error.kind, "message": error.message},
                )
            if error.ambiguous:
                with db.connect() as conn:
                    _set(conn, job_id, status="uncertain", stage="待核对", error=error.message, finished_at=db.now())
                return "stop"
            with db.connect() as conn:
                _set(conn, job_id, status="failed", stage="失败", error=error.message, finished_at=db.now())
            return "stop"

        with db.connect() as conn:
            router.record_key_success(conn, key_id)
        if result.outputs:
            await self._finish(job_id, target, request, result.outputs, result.external_url)
            return "done"
        if not result.upstream_id:
            with db.connect() as conn:
                _set(conn, job_id, status="failed", error="上游没有返回任务编号", finished_at=db.now())
            return "stop"
        with db.connect() as conn:
            raw_progress = result.raw.get("progress")
            progress = raw_progress / 100 if isinstance(raw_progress, (int, float)) else 0.15
            _set(
                conn,
                job_id,
                status="running",
                stage="上游生成中",
                progress=max(0.15, progress),
                upstream_job_id=result.upstream_id,
                external_url=result.external_url,
            )
        await self._poll_until_done(job_id, target, request, result)
        return "done"

    # ── polling ────────────────────────────────────────────────────────────
    async def _resume_poll(self, job_id, job, model, req, request) -> None:
        with db.connect() as conn:
            key = db.one(conn, "SELECT * FROM channel_keys WHERE id = ?", (job["key_id"],)) if job["key_id"] else None
        target = router.target(model)
        ctx = ProviderContext(
            client=self._client,  # type: ignore[arg-type]
            base_url=target.base_url,
            api_key=crypto.decrypt(key["secret"]) if key else "",
            headers=target.headers,
            request=req,
            overrides=target.overrides,
            modality=job["modality"],
            timeout=300.0,
        )
        handle = SubmitResult(upstream_id=job["upstream_job_id"])
        await self._poll_loop(job_id, target, request, handle, ctx)

    async def _poll_until_done(self, job_id, target, request, result) -> None:
        with db.connect() as conn:
            job = db.one(conn, "SELECT modality FROM jobs WHERE id = ?", (job_id,))
            key = db.one(conn, "SELECT * FROM channel_keys WHERE id = (SELECT key_id FROM jobs WHERE id=?)", (job_id,))
        modality = job["modality"] if job else "image"
        req = router.build_request(
            upstream_model=target.upstream_model,
            prompt=request.get("prompt", ""),
            negative=request.get("negative", ""),
            refs=[],
            count=int(request.get("count", 1)),
            params=request.get("params", {}),
        )
        ctx = ProviderContext(
            client=self._client,  # type: ignore[arg-type]
            base_url=target.base_url,
            api_key=crypto.decrypt(key["secret"]) if key else "",
            headers=target.headers,
            request=req,
            overrides=target.overrides,
            modality=modality,
            timeout=300.0,
        )
        await self._poll_loop(job_id, target, request, result, ctx)

    async def _poll_loop(self, job_id, target, request, handle, ctx) -> None:
        started = asyncio.get_event_loop().time()
        interval = max(2.0, float(handle.poll_after or 3.0))
        timeout = POLL_TIMEOUT.get(request.get("modality", "image"), 1800)
        while True:
            if self._canceled(job_id):
                with contextlib.suppress(Exception):
                    await target.adapter.cancel(ctx, handle)
                with db.connect() as conn:
                    _set(conn, job_id, status="canceled", stage="已取消", finished_at=db.now())
                return
            if asyncio.get_event_loop().time() - started > timeout:
                with db.connect() as conn:
                    _set(
                        conn,
                        job_id,
                        status="uncertain",
                        stage="超时",
                        error="上游长时间未完成，任务编号已保留，可稍后继续查询",
                        finished_at=db.now(),
                    )
                return
            await asyncio.sleep(interval)
            try:
                polled = await target.adapter.poll(ctx, handle)
            except ProviderError as exc:
                with db.connect() as conn:
                    _attempt(conn, job_id, {"phase": "poll_error", "message": exc.message, "kind": exc.kind})
                if exc.kind in ("network",) or exc.status in (500, 502, 503, 504):
                    interval = min(interval * 1.4, 15)
                    continue
                with db.connect() as conn:
                    _set(conn, job_id, status="failed", error=exc.message, finished_at=db.now())
                return
            if polled.failed:
                with db.connect() as conn:
                    _set(
                        conn,
                        job_id,
                        status="failed",
                        stage="上游失败",
                        error=polled.error or "上游任务失败",
                        finished_at=db.now(),
                    )
                return
            if polled.done:
                await self._finish(job_id, target, request, polled.outputs, polled.external_url)
                return
            with db.connect() as conn:
                _set(conn, job_id, stage="上游生成中", progress=min(0.95, max(0.15, polled.progress or 0.2)))
            interval = min(interval * 1.15, 8.0)

    # ── finishing ──────────────────────────────────────────────────────────
    async def _finish(self, job_id, target, request, outputs, external_url=None) -> None:
        assets: list[str] = []
        refs_snapshot = _refs_snapshot(request.get("refs", []))
        source_id = (request.get("options") or {}).get("source_asset_id")
        parent_id = root_id = None
        next_version = 1
        if source_id:
            with db.connect() as conn:
                source = db.one(conn, "SELECT * FROM assets WHERE id = ?", (source_id,))
                if source:
                    parent_id = source["id"]
                    root_id = source.get("root_id") or source["id"]
                    next_version = int(
                        db.scalar(
                            conn,
                            "SELECT COALESCE(MAX(version), 0) + 1 FROM assets WHERE root_id = ?",
                            (root_id,),
                        )
                        or 1
                    )
        for index, output in enumerate(outputs):
            data = output.data
            if not data and output.url:
                try:
                    async with httpx.AsyncClient(timeout=180, follow_redirects=True) as client:
                        resp = await client.get(output.url)
                        resp.raise_for_status()
                        data = resp.content
                except httpx.HTTPError:
                    continue
            if not data:
                continue
            kind = output.kind
            record = await asyncio.to_thread(storage.save_output, data, kind, output.mime)
            if kind == "video" and not record.get("duration_ms"):
                try:
                    seconds = float(str(request.get("params", {}).get("duration") or 0))
                except (TypeError, ValueError):
                    seconds = 0
                if seconds > 0:
                    record["duration_ms"] = int(seconds * 1000)
            asset_id = db.new_id()
            asset_root = root_id or asset_id
            asset_version = (next_version + index) if root_id else 1
            with db.connect() as conn:
                conn.execute(
                    """
                    INSERT INTO assets
                      (id, kind, path, thumb_path, poster_path, width, height, duration_ms, bytes,
                       job_id, prompt, negative, model_id, model_name, params, origin, meta,
                       parent_id, root_id, tool, version, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'generated', ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        asset_id,
                        kind,
                        record["path"],
                        record.get("thumb_path"),
                        record.get("thumb_path") if kind == "video" else None,
                        record.get("width"),
                        record.get("height"),
                        record.get("duration_ms"),
                        record.get("bytes"),
                        job_id,
                        request.get("prompt", ""),
                        request.get("negative", ""),
                        request.get("model_id"),
                        request.get("model_name", ""),
                        db.dumps(request.get("params", {})),
                        db.dumps(
                            {
                                "ratio": request.get("params", {}).get("aspect_ratio"),
                                "refs": len(refs_snapshot),
                                "refs_snapshot": refs_snapshot,
                                "channel": target.channel_name,
                                "upstream_model": target.upstream_model,
                                "tool": request.get("tool", ""),
                                "options": request.get("options", {}),
                                "source_asset_id": source_id,
                            }
                        ),
                        parent_id,
                        asset_root,
                        request.get("tool", ""),
                        asset_version,
                        db.now(),
                    ),
                )
            assets.append(asset_id)

        req = router.build_request(
            upstream_model=target.upstream_model,
            prompt=request.get("prompt", ""),
            negative=request.get("negative", ""),
            refs=[],
            count=int(request.get("count", 1)),
            params=request.get("params", {}),
        )
        amount = router.quote_price(target.price, req) or 0.0
        currency = str(target.price.get("currency", "CNY"))
        with db.connect() as conn:
            if assets:
                _set(
                    conn,
                    job_id,
                    status="succeeded",
                    stage="完成",
                    progress=1.0,
                    price=amount,
                    currency=currency,
                    external_url=external_url,
                    finished_at=db.now(),
                    error=None,
                )
                _attempt(conn, job_id, {"phase": "succeeded", "assets": len(assets)})
            else:
                _set(
                    conn,
                    job_id,
                    status="failed",
                    stage="失败",
                    error="没有可保存的生成结果",
                    finished_at=db.now(),
                )

    # ── helpers ────────────────────────────────────────────────────────────
    def _canceled(self, job_id: str) -> bool:
        with db.connect() as conn:
            row = db.one(conn, "SELECT canceled, status FROM jobs WHERE id = ?", (job_id,))
        return bool(row and row["canceled"])

    async def _set_async(self, job_id: str, **fields: Any) -> None:
        with db.connect() as conn:
            _set(conn, job_id, **fields)

    async def retry(self, job_id: str) -> None:
        with db.connect() as conn:
            job = db.one(conn, "SELECT * FROM jobs WHERE id = ?", (job_id,))
            if not job:
                raise KeyError(job_id)
            _set(
                conn,
                job_id,
                status="queued",
                stage="重新排队",
                progress=0,
                error=None,
                canceled=0,
                upstream_job_id=None,
                started_at=None,
                finished_at=None,
            )
            _attempt(conn, job_id, {"phase": "requeued", "message": "手动重试"})


runner = JobRunner()
