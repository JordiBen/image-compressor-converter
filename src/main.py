"""Apify entrypoint: bulk image compressor & converter (JPEG/PNG/WebP/AVIF, resize, strip EXIF/GPS, target size, ZIP)."""
from __future__ import annotations

import asyncio
import os
import tempfile
import time
import zipfile

import httpx
from apify import Actor

from .imgproc import EVENT, FORMATS, ImageError, Options, convert, file_stem, inspect, normalize_url, parse_input
from .netguard import BlockedAddressError, assert_public_url

UA = 'Mozilla/5.0 (compatible; ImageCompressorConverter/1.0; +https://apify.com/manageable_gully/image-compressor-converter)'
DOWNLOAD_CONCURRENCY = 4
MAX_ZIP_BYTES = 300 * 1024 * 1024


async def download(client: httpx.AsyncClient, url: str, opts: Options) -> bytes:
    await assert_public_url(url, allow_private=opts.allow_private)
    for attempt in range(3):
        async with client.stream('GET', url) as r:
            if r.status_code in (429, 503) and attempt < 2:
                await asyncio.sleep(2 + attempt * 3)
                continue
            if r.status_code >= 400:
                raise ImageError(f'Download failed: HTTP {r.status_code}')
            ctype = (r.headers.get('content-type') or '').lower()
            if ctype.startswith('text/html'):
                raise ImageError('The link returned a web page, not an image. Use a direct link to the image file '
                                 '(right-click the image > "Copy image address").')
            declared = int(r.headers.get('content-length') or 0)
            if declared > opts.max_bytes:
                raise ImageError(f'File too large ({declared // 1048576} MB; max {opts.max_bytes // 1048576} MB). Not charged.')
            buf = bytearray()
            async for chunk in r.aiter_bytes(1 << 16):
                buf += chunk
                if len(buf) > opts.max_bytes:
                    raise ImageError(f'File too large (> {opts.max_bytes // 1048576} MB). Not charged.')
            return bytes(buf)
    raise ImageError('Download failed: the server kept answering "too many requests"')


async def main() -> None:
    async with Actor:
        inp = await Actor.get_input() or {}
        try:
            urls, opts = parse_input(inp)
        except ImageError as e:
            await Actor.fail(status_message=str(e))
            return
        if os.environ.get('ALLOW_PRIVATE_NETWORK_FOR_LOCAL_DEV') == '1' and not Actor.is_at_home():
            opts.allow_private = True
        kvs = await Actor.open_key_value_store()
        cm = Actor.get_charging_manager()
        stats = {'done': 0, 'failed': 0, 'skipped': 0, 'in': 0, 'out': 0, 'units': 0}
        budget_hit = False
        used: set[str] = set()
        lock = asyncio.Lock()
        sem = asyncio.Semaphore(DOWNLOAD_CONCURRENCY)
        ztmp = tempfile.NamedTemporaryFile(delete=False, suffix='.zip') if opts.zip else None
        zf = zipfile.ZipFile(ztmp, 'w', zipfile.ZIP_STORED) if ztmp else None
        zip_full = False

        async def handle(n: int, raw: str, client: httpx.AsyncClient) -> None:
            nonlocal budget_hit, zip_full
            rec: dict = {'url': raw, 'position': n}
            try:
                url = normalize_url(raw)
                async with sem:
                    if budget_hit:
                        raise ImageError('Skipped: the run\'s max charge was reached (not charged).')
                    data = await download(client, url, opts)
                async with lock:
                    ins = inspect(data, opts)
                    rec.update(megapixels=round(ins.megapixels, 2))
                    allowed = cm.calculate_max_event_charge_count_within_limit(EVENT)
                    if allowed is not None and allowed < ins.units:
                        budget_hit = True
                        raise ImageError(f'Skipped: needs {ins.units} image unit(s) but your max charge per run allows '
                                         f'{allowed}. Raise the run\'s max cost limit (not charged).')
                    await Actor.set_status_message(f'Image {stats["done"] + stats["failed"] + 1}/{len(urls)}: '
                                                   f'{ins.width}x{ins.height} {ins.src_key} -> {opts.fmt}')
                    t0 = time.time()
                    out, key, info = await asyncio.to_thread(convert, data, ins, opts)
                    _, mime, ext = FORMATS[key]
                    stem = file_stem(url, n)
                    name = f'{stem}.{ext}'
                    i = 2
                    while name in used:
                        name, i = f'{stem}-{i}.{ext}', i + 1
                    used.add(name)
                    await kvs.set_value(name, out, content_type=mime)
                    rec.update(fileName=name, **info, downloadUrl=await kvs.get_public_url(name),
                               processingSeconds=round(time.time() - t0, 2))
                    if zf and not zip_full:
                        if ztmp.tell() + len(out) > MAX_ZIP_BYTES:
                            zip_full = True
                            Actor.log.warning('ZIP limit of 300 MB reached; remaining images are only in the key-value store.')
                        else:
                            zf.writestr(name, out)
                    res = await Actor.charge(EVENT, count=ins.units)
                    rec['billedUnits'] = res.charged_count
                    stats['units'] += res.charged_count
                    stats['done'] += 1
                    stats['in'] += len(data)
                    stats['out'] += len(out)
            except (ImageError, BlockedAddressError) as e:
                rec['error'] = str(e)[:300]
            except httpx.HTTPError as e:
                rec['error'] = f'Download failed: {type(e).__name__}'
            except Exception as e:  # noqa: BLE001 - one bad image must not kill the batch
                Actor.log.exception('Image failed')
                rec['error'] = f'Processing failed: {str(e)[:200]}'
            if 'error' in rec:
                rec['billedUnits'] = 0
                stats['skipped' if rec['error'].startswith('Skipped') else 'failed'] += 1
            await Actor.push_data(rec)

        limits = httpx.Limits(max_connections=DOWNLOAD_CONCURRENCY * 2)
        async with httpx.AsyncClient(timeout=httpx.Timeout(30, read=60), follow_redirects=True, limits=limits,
                                     headers={'User-Agent': UA, 'Accept': 'image/avif,image/webp,image/*,*/*;q=0.8'},
                                     event_hooks={'request': [lambda req: assert_public_url(str(req.url), allow_private=opts.allow_private)]}) as client:
            await asyncio.gather(*(handle(n, u, client) for n, u in enumerate(urls, 1)))

        summary = {'images': len(urls), 'processed': stats['done'], 'failed': stats['failed'], 'skipped': stats['skipped'],
                   'originalBytes': stats['in'], 'outputBytes': stats['out'], 'savedBytes': stats['in'] - stats['out'],
                   'savingsPercent': round((stats['in'] - stats['out']) * 100 / stats['in'], 1) if stats['in'] else 0,
                   'billedUnits': stats['units']}
        if zf:
            zf.close()
            ztmp.close()
            try:
                if stats['done']:
                    with open(ztmp.name, 'rb') as f:
                        await kvs.set_value('images.zip', f.read(), content_type='application/zip')
                    summary['zipUrl'] = await kvs.get_public_url('images.zip')
                    Actor.log.info(f'ZIP with all images: {summary["zipUrl"]}')
            finally:
                os.unlink(ztmp.name)
        await kvs.set_value('OUTPUT', summary)
        mb = (stats['in'] - stats['out']) / 1048576
        msg = (f'Done: {stats["done"]}/{len(urls)} image(s), saved {mb:.2f} MB ({summary["savingsPercent"]}%), '
               f'{stats["units"]} unit(s) billed')
        if budget_hit:
            msg += ' (some images skipped: max charge reached)'
        await Actor.set_status_message(msg, is_terminal=True)
