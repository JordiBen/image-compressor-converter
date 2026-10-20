"""Pure image helpers: input parsing, decoding (incl. HEIC/AVIF), EXIF orientation, resize, metadata stripping,
encoding to JPEG/PNG/WebP/AVIF/GIF and the target-file-size search. No Apify or network code here (see main.py)."""
from __future__ import annotations

import io
import math
import re
from dataclasses import dataclass, field
from urllib.parse import parse_qs, unquote, urlencode, urlsplit, urlunsplit

from PIL import Image, ImageCms, ImageOps, ImageSequence, UnidentifiedImageError, features

try:  # HEIC/HEIF input (iPhone photos). Decoding only.
    import pillow_heif
    pillow_heif.register_heif_opener()
    HEIF = True
except ImportError:  # pragma: no cover
    HEIF = False

EVENT = 'image-processed'
UNIT_MP = 25            # one billing unit per started 25 megapixels of input (width x height x frames)
MAX_ANIM_MP = 50        # total pixels across all frames of an animation we keep in memory
MAX_FRAMES = 500
MAX_IMAGES = 5000
OUT_CHOICES = ('keep', 'jpeg', 'png', 'webp', 'avif')
METADATA_MODES = ('all', 'gps', 'none')
# key -> (Pillow format, MIME type, file extension)
FORMATS = {'jpeg': ('JPEG', 'image/jpeg', 'jpg'), 'png': ('PNG', 'image/png', 'png'),
           'webp': ('WEBP', 'image/webp', 'webp'), 'avif': ('AVIF', 'image/avif', 'avif'),
           'gif': ('GIF', 'image/gif', 'gif')}
PIL_TO_KEY = {'JPEG': 'jpeg', 'MPO': 'jpeg', 'PNG': 'png', 'WEBP': 'webp', 'AVIF': 'avif', 'GIF': 'gif'}
ANIM_OUT = ('webp', 'gif', 'png', 'avif')
GPS_IFD = 0x8825
ORIENTATION = 0x0112
HEX_RE = re.compile(r'^#?([0-9a-fA-F]{6})$')


class ImageError(ValueError):
    """A problem with one image (bad link, not an image, too large...). The image is reported and not charged."""


@dataclass
class Options:
    fmt: str = 'webp'
    quality: int = 80
    max_width: int = 0
    max_height: int = 0
    metadata: str = 'all'
    keep_icc: bool = True
    target_kb: int = 0
    resize_for_target: bool = True
    png_colors: bool = False
    lossless: bool = False
    background: tuple[int, int, int] = (255, 255, 255)
    zip: bool = False
    max_mp: float = 100.0
    max_bytes: int = 50 * 1024 * 1024
    avif_speed: int = 8
    keep_original_if_smaller: bool = True
    allow_private: bool = False


@dataclass
class Inspected:
    im: Image.Image
    src_key: str            # 'jpeg', 'png', 'heif', 'tiff', ...
    width: int
    height: int
    frames: int
    animated: bool
    megapixels: float
    units: int
    exif_tags: int = 0
    has_gps: bool = False
    has_xmp: bool = False
    icc: bytes | None = None
    notes: list[str] = field(default_factory=list)


def avif_quality(q: int) -> int:
    """AVIF's quality scale is 'higher' than JPEG/WebP: AVIF 80 is near-lossless and often bigger than WebP 80.
    Map the user's JPEG-like quality so the same number gives a similar look (80 -> 56, 50 -> 35, 95 -> 82, 100 -> 100)."""
    return max(1, round(q * 0.7)) if q <= 90 else round(63 + (q - 90) * 3.7)


def units_for(megapixels: float) -> int:
    return max(1, math.ceil(round(megapixels, 3) / UNIT_MP))


# ---------------------------------------------------------------- input

def normalize_url(url: str) -> str:
    """Turn Google Drive / Dropbox share links into direct-download links."""
    url = url.strip()
    p = urlsplit(url)
    host = (p.hostname or '').lower()
    if host == 'drive.google.com':
        m = re.search(r'/file/d/([\w-]+)', p.path)
        fid = m.group(1) if m else (parse_qs(p.query).get('id') or [None])[0]
        if fid:
            return f'https://drive.google.com/uc?export=download&id={fid}'
    if host in ('www.dropbox.com', 'dropbox.com'):
        q = parse_qs(p.query)
        q['dl'] = ['1']
        return urlunsplit((p.scheme, p.netloc, p.path, urlencode({k: v[0] for k, v in q.items()}), ''))
    return url


def _int(inp: dict, key: str, default: int, lo: int, hi: int) -> int:
    v = inp.get(key, default)
    if v in (None, ''):
        v = default
    try:
        v = int(v)
    except (TypeError, ValueError):
        raise ImageError(f'"{key}" must be a whole number') from None
    if not lo <= v <= hi:
        raise ImageError(f'"{key}" must be between {lo} and {hi}')
    return v


def parse_color(s: str | None) -> tuple[int, int, int]:
    m = HEX_RE.match((s or '#ffffff').strip())
    if not m:
        raise ImageError('"backgroundColor" must be a hex color such as #ffffff')
    h = m.group(1)
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def parse_input(inp: dict) -> tuple[list[str], Options]:
    urls: list[str] = []
    for s in [inp.get('uploadedFile')] + list(inp.get('imageUrls') or []):
        u = (s.get('url') if isinstance(s, dict) else s) or ''
        u = u.strip()
        if u and u not in urls:
            urls.append(u)
    if not urls:
        raise ImageError('Add at least one image link in "imageUrls" (or upload an image).')
    if len(urls) > MAX_IMAGES:
        raise ImageError(f'Too many images ({len(urls)}); max {MAX_IMAGES} per run. Split the list into several runs.')
    for u in urls:
        if urlsplit(u).scheme not in ('http', 'https'):
            raise ImageError(f'Not a web link: {u[:80]!r}. Use http(s) links to image files.')
    fmt = (inp.get('outputFormat') or 'webp').strip().lower()
    fmt = {'jpg': 'jpeg', 'original': 'keep'}.get(fmt, fmt)
    if fmt not in OUT_CHOICES:
        raise ImageError(f'outputFormat must be one of {list(OUT_CHOICES)}')
    if fmt == 'avif' and not features.check('avif'):  # pragma: no cover - our image always has AVIF
        raise ImageError('AVIF is not available in this build')
    meta = inp.get('stripMetadata', 'all')
    meta = 'all' if meta in (None, '') else meta
    if meta is True:
        meta = 'all'
    elif meta is False:
        meta = 'none'
    if meta not in METADATA_MODES:
        raise ImageError(f'stripMetadata must be one of {list(METADATA_MODES)}')
    opts = Options(
        fmt=fmt, quality=_int(inp, 'quality', 80, 1, 100),
        max_width=_int(inp, 'maxWidth', 0, 0, 20000), max_height=_int(inp, 'maxHeight', 0, 0, 20000),
        metadata=meta, keep_icc=bool(inp.get('keepColorProfile', True)),
        target_kb=_int(inp, 'targetMaxSizeKB', 0, 0, 100000),
        resize_for_target=bool(inp.get('resizeToReachTarget', True)),
        png_colors=bool(inp.get('pngReduceColors', False)), lossless=bool(inp.get('lossless', False)),
        background=parse_color(inp.get('backgroundColor')), zip=bool(inp.get('createZip', False)),
        max_mp=float(_int(inp, 'maxMegapixels', 100, 1, 150)),
        avif_speed=_int(inp, 'avifSpeed', 8, 0, 10),
        keep_original_if_smaller=bool(inp.get('keepOriginalIfSmaller', True)))
    return urls, opts


def file_stem(url: str, n: int) -> str:
    """Safe Apify key-value-store key stem from the URL's file name."""
    name = unquote(urlsplit(url).path.rstrip('/').rsplit('/', 1)[-1])
    if '.' in name:
        name = name.rsplit('.', 1)[0]
    name = re.sub(r'[^A-Za-z0-9._()\-]+', '-', name).strip('-.')[:80]
    return name or f'image-{n}'


# ---------------------------------------------------------------- decode

def sniff(data: bytes) -> None:
    head = data[:512].lstrip().lower()
    if head.startswith((b'<!doctype html', b'<html', b'<head', b'<body')) or b'<html' in head[:200]:
        raise ImageError('The link returned a web page, not an image. Use a direct link to the image file '
                         '(right-click the image > "Copy image address").')
    if head.startswith((b'<svg', b'<?xml')) or b'<svg' in head:
        raise ImageError('SVG is a vector format and is not supported. Use PNG, JPEG, WebP, AVIF, HEIC, GIF, TIFF or BMP.')
    if head.startswith(b'%pdf'):
        raise ImageError('PDF files are not images. Use the PDF & Image OCR Extractor for PDFs.')


def inspect(data: bytes, opts: Options) -> Inspected:
    """Read the header only (cheap): size, frames, metadata, billing units. Raises ImageError."""
    if not data:
        raise ImageError('Downloaded file is empty')
    sniff(data)
    Image.MAX_IMAGE_PIXELS = None  # we enforce our own limit below, from the header, before decoding
    try:
        im = Image.open(io.BytesIO(data))
    except UnidentifiedImageError:
        raise ImageError('Not an image or an unsupported image format') from None
    except Exception as e:  # noqa: BLE001 - corrupt headers raise all sorts of errors
        raise ImageError(f'Could not read the image: {str(e)[:120]}') from None
    w, h = im.size
    frames = int(getattr(im, 'n_frames', 1) or 1)
    # MPO (camera JPEGs with a preview/depth image) report several frames but are not animations
    animated = bool(getattr(im, 'is_animated', False)) and frames > 1 and im.format in ('GIF', 'WEBP', 'PNG', 'AVIF')
    if not animated:
        frames = 1
    mp = w * h / 1e6
    if mp > opts.max_mp:
        raise ImageError(f'Image too large: {w}x{h} = {mp:.0f} megapixels (limit {opts.max_mp:.0f} MP, see "maxMegapixels"). Not charged.')
    src_key = PIL_TO_KEY.get(im.format or '', (im.format or 'unknown').lower())
    billed_frames = min(frames, MAX_FRAMES) if animated else 1
    ins = Inspected(im=im, src_key=src_key, width=w, height=h, frames=frames, animated=animated,
                    megapixels=round(mp * billed_frames, 3), units=units_for(mp * billed_frames))
    try:
        exif = im.getexif()
        ins.exif_tags = len(exif)
        ins.has_gps = bool(exif.get_ifd(GPS_IFD)) or GPS_IFD in exif
    except Exception:  # noqa: BLE001
        pass
    ins.has_xmp = bool(im.info.get('xmp') or im.info.get('XML:com.adobe.xmp'))
    ins.icc = im.info.get('icc_profile') or None
    return ins


# ---------------------------------------------------------------- convert

def out_key_for(ins: Inspected, opts: Options) -> str:
    if opts.fmt != 'keep':
        return opts.fmt
    if ins.src_key in FORMATS:
        return ins.src_key
    return 'png' if _has_alpha(ins.im) else 'jpeg'  # HEIC, TIFF, BMP, ICO... -> JPEG (or PNG with transparency)


def _has_alpha(im: Image.Image) -> bool:
    return im.mode in ('RGBA', 'LA', 'PA', 'RGBa', 'La') or (im.mode == 'P' and 'transparency' in im.info)


def fit(w: int, h: int, mw: int, mh: int) -> tuple[int, int]:
    """Largest size that fits in mw x mh (0 = no limit), keeping the aspect ratio. Never upscales."""
    s = 1.0
    if mw and w > mw:
        s = min(s, mw / w)
    if mh and h > mh:
        s = min(s, mh / h)
    return (w, h) if s >= 1 else (max(1, round(w * s)), max(1, round(h * s)))


def _to_srgb(im: Image.Image, icc: bytes | None) -> tuple[Image.Image, bytes | None]:
    """CMYK (print) images -> RGB. Uses the embedded profile when there is one."""
    if im.mode != 'CMYK':
        return im, icc
    if icc:
        try:
            src = ImageCms.ImageCmsProfile(io.BytesIO(icc))
            return ImageCms.profileToProfile(im, src, ImageCms.createProfile('sRGB'), outputMode='RGB'), None
        except Exception:  # noqa: BLE001 - broken profile: plain conversion below
            pass
    return im.convert('RGB'), None


def prepare(im: Image.Image, key: str, bg: tuple[int, int, int]) -> Image.Image:
    """Convert pixel mode to what the output format supports."""
    if im.mode.startswith('I') and not (key == 'png' and im.mode == 'I;16'):
        im = im.convert('I').point(lambda v: v * (1 / 256)).convert('L')  # 16/32-bit grayscale -> 8-bit
    if im.mode == 'F':
        im = im.convert('L')
    alpha = _has_alpha(im)
    if key == 'jpeg':
        if alpha:
            rgba = im.convert('RGBA')
            base = Image.new('RGB', rgba.size, bg)
            base.paste(rgba, mask=rgba.getchannel('A'))
            return base
        return im if im.mode in ('RGB', 'L') else im.convert('RGB')
    if key in ('webp', 'avif'):
        if alpha:
            return im if im.mode == 'RGBA' else im.convert('RGBA')
        return im if im.mode == 'RGB' else im.convert('RGB')
    if key == 'png':
        if im.mode in ('RGB', 'RGBA', 'L', 'LA', 'P', '1', 'I;16'):
            return im
        return im.convert('RGBA' if alpha else 'RGB')
    if key == 'gif':
        return im if im.mode in ('P', 'L') else im.convert('RGBA' if alpha else 'RGB')
    return im


def reduce_colors(im: Image.Image, colors: int = 256) -> Image.Image:
    """TinyPNG-style lossy PNG: <= 256 colors with dithering (much smaller, usually invisible)."""
    if im.mode in ('P', '1', 'L'):
        return im
    if im.mode in ('RGBA', 'LA'):
        return im.convert('RGBA').quantize(colors, method=Image.Quantize.FASTOCTREE, dither=Image.Dither.FLOYDSTEINBERG)
    return im.convert('RGB').quantize(colors, method=Image.Quantize.MEDIANCUT, dither=Image.Dither.FLOYDSTEINBERG)


def _meta_kwargs(key: str, opts: Options, exif: Image.Exif | None, xmp: bytes | None, icc: bytes | None) -> dict:
    kw: dict = {}
    if icc and opts.keep_icc and key in ('jpeg', 'png', 'webp', 'avif'):
        kw['icc_profile'] = icc
    if opts.metadata != 'all' and exif is not None and len(exif) and key in ('jpeg', 'png', 'webp', 'avif'):
        if opts.metadata == 'gps':
            exif.pop(GPS_IFD, None)
        if ORIENTATION in exif:
            exif[ORIENTATION] = 1  # pixels are already rotated
        kw['exif'] = exif.tobytes()
    if opts.metadata == 'none' and xmp and key in ('jpeg', 'png', 'webp', 'avif'):
        kw['xmp'] = xmp
    return kw


def encode(frames: list[Image.Image], durations: list[int], loop: int, key: str, quality: int, opts: Options,
           meta: dict) -> bytes:
    pil_fmt = FORMATS[key][0]
    buf = io.BytesIO()
    kw = dict(meta)
    if key == 'jpeg':
        kw.update(quality=quality, optimize=True, progressive=True, subsampling='4:2:0' if quality < 90 else '4:4:4')
    elif key == 'webp':
        kw.update(quality=quality, method=4, lossless=opts.lossless)
    elif key == 'avif':
        kw.update(quality=100 if opts.lossless else avif_quality(quality), speed=opts.avif_speed)
        if opts.lossless:
            kw['subsampling'] = '4:4:4'
    elif key == 'png':
        # zlib level 9 / optimize costs 7x the CPU for ~5% smaller photos: only for palette (already small) images
        kw.update(optimize=frames[0].mode in ('P', '1', 'L') and len(frames) == 1, compress_level=6)
    elif key == 'gif':
        kw.update(optimize=True)
    if len(frames) > 1:
        kw.update(save_all=True, append_images=frames[1:], duration=durations, loop=loop)
        if key == 'png':
            kw.pop('optimize', None)
    frames[0].save(buf, pil_fmt, **kw)
    return buf.getvalue()


def _load_frames(ins: Inspected, key: str, size: tuple[int, int]) -> tuple[list[Image.Image], list[int], int]:
    im = ins.im
    if ins.animated and key in ANIM_OUT:
        if ins.width * ins.height * min(ins.frames, MAX_FRAMES) > MAX_ANIM_MP * 1e6:
            raise ImageError(f'Animation too large ({ins.frames} frames of {ins.width}x{ins.height}); max {MAX_ANIM_MP} '
                             'megapixels across all frames. Choose JPEG to keep only the first frame. Not charged.')
        frames, durs = [], []
        for i, f in enumerate(ImageSequence.Iterator(im)):
            if i >= MAX_FRAMES:
                ins.notes.append(f'animation cut to the first {MAX_FRAMES} frames')
                break
            durs.append(int(f.info.get('duration') or im.info.get('duration') or 100))
            fr = f.convert('RGBA')
            frames.append(fr.resize(size, Image.Resampling.LANCZOS) if fr.size != size else fr)
        return frames, durs, int(im.info.get('loop', 0) or 0)
    if ins.animated:
        ins.notes.append(f'animated image: only the first frame was kept ({key.upper()} has no animation)')
    # JPEG draft mode: decode at 1/2, 1/4 or 1/8 scale when shrinking a lot (much faster, less memory)
    if im.format == 'JPEG' and size != (ins.width, ins.height):
        o = ins.im.getexif().get(ORIENTATION, 1) if ins.exif_tags else 1
        req = (size[1], size[0]) if o in (5, 6, 7, 8) else size
        try:
            im.draft(im.mode if im.mode in ('RGB', 'L') else 'RGB', req)
        except Exception:  # noqa: BLE001
            pass
    im.load()
    return [im], [], 0


def convert(data: bytes, ins: Inspected, opts: Options) -> tuple[bytes, str, dict]:
    """Full pipeline for one image. Returns (output bytes, output format key, info for the dataset row)."""
    key = out_key_for(ins, opts)
    xmp = ins.im.info.get('xmp') or ins.im.info.get('XML:com.adobe.xmp')
    if isinstance(xmp, str):
        xmp = xmp.encode()
    # final size is computed in the upright orientation
    o = 1
    if ins.exif_tags:
        try:
            o = ins.im.getexif().get(ORIENTATION, 1)
        except Exception:  # noqa: BLE001
            o = 1
    up_w, up_h = (ins.height, ins.width) if o in (5, 6, 7, 8) else (ins.width, ins.height)
    tw, th = fit(up_w, up_h, opts.max_width, opts.max_height)
    stored_size = (th, tw) if o in (5, 6, 7, 8) else (tw, th)
    try:
        frames, durs, loop = _load_frames(ins, key, stored_size)
    except ImageError:
        raise
    except Image.DecompressionBombError:
        raise ImageError('Image too large to decode safely. Not charged.') from None
    except Exception as e:  # noqa: BLE001
        raise ImageError(f'Could not decode the image (corrupt or truncated file?): {str(e)[:120]}') from None
    icc = ins.icc
    out_frames = []
    exif = None
    for fr in frames:
        if len(frames) == 1:
            fr = ImageOps.exif_transpose(fr)  # apply the camera's rotation, then drop the tag
            exif = fr.getexif()
            if fr.size != (tw, th):
                fr = fr.resize((tw, th), Image.Resampling.LANCZOS, reducing_gap=3.0)
        fr, icc = _to_srgb(fr, icc)
        out_frames.append(prepare(fr, key, opts.background))
    if key == 'png' and opts.png_colors and len(out_frames) == 1:
        out_frames = [reduce_colors(out_frames[0])]
    meta = _meta_kwargs(key, opts, exif, xmp, icc)
    q = opts.quality
    out = encode(out_frames, durs, loop, key, q, opts, meta)
    notes = ins.notes
    target = opts.target_kb * 1024
    if target and len(out) > target:
        out, q, out_frames = _shrink_to_target(out, out_frames, durs, loop, key, q, opts, meta, target, notes)
    w, h = out_frames[0].size
    kept_original = False
    same_fmt = key == ins.src_key and (w, h) == (ins.width, ins.height) and o == 1
    no_private_meta = opts.metadata == 'none' or not (ins.has_gps or ins.has_xmp or (opts.metadata == 'all' and ins.exif_tags))
    if (opts.keep_original_if_smaller and same_fmt and len(out) >= len(data) and no_private_meta and not target
            and not (key == 'png' and opts.png_colors)):
        out, kept_original = data, True
        notes.append('already well compressed: the original file was kept (re-encoding made it bigger)')
    removed = []
    if opts.metadata in ('all', 'gps') and ins.has_gps:
        removed.append('gps')
    if opts.metadata == 'all' and ins.exif_tags and not kept_original:
        removed.append('exif')
    if opts.metadata in ('all', 'gps') and ins.has_xmp and not kept_original:
        removed.append('xmp')
    if ins.icc and not (opts.keep_icc and key in ('jpeg', 'png', 'webp', 'avif')) and not kept_original:
        removed.append('icc-profile')
    info = {
        'inputFormat': ins.src_key, 'outputFormat': key,
        'originalBytes': len(data), 'outputBytes': len(out),
        'savedBytes': len(data) - len(out),
        'savingsPercent': round((len(data) - len(out)) * 100 / len(data), 1),
        'originalWidth': ins.width, 'originalHeight': ins.height, 'width': w, 'height': h,
        'frames': len(out_frames), 'quality': q if key in ('jpeg', 'webp', 'avif') and not opts.lossless else None,
        'metadataRemoved': removed, 'gpsRemoved': 'gps' in removed,
    }
    if notes:
        info['note'] = '; '.join(dict.fromkeys(notes))
    return out, key, info


def _shrink_to_target(out, frames, durs, loop, key, q, opts, meta, target, notes):
    """Binary-search quality (lossy formats), then reduce colors (PNG), then scale down until <= target bytes."""
    best = (out, q, frames)
    lossy = key in ('jpeg', 'webp', 'avif') and not opts.lossless
    for rnd in range(5):
        if lossy:
            lo, hi, found = 10, best[1] if rnd == 0 else opts.quality, None
            for _ in range(6 if key != 'avif' else 5):
                if lo > hi:
                    break
                mid = (lo + hi) // 2
                cand = encode(frames, durs, loop, key, mid, opts, meta)
                if len(cand) <= target:
                    found, lo = (cand, mid), mid + 1
                else:
                    hi = mid - 1
            if found:
                return found[0], found[1], frames
            cand = encode(frames, durs, loop, key, 10, opts, meta)
            best = (cand, 10, frames) if len(cand) < len(best[0]) else best
        elif key == 'png' and len(frames) == 1 and frames[0].mode not in ('P', '1'):
            frames = [reduce_colors(frames[0])]
            cand = encode(frames, durs, loop, key, q, opts, meta)
            notes.append('PNG reduced to 256 colors to reach the target size')
            best = (cand, q, frames)
            if len(cand) <= target:
                return cand, q, frames
        if not opts.resize_for_target:
            notes.append(f'could not reach {opts.target_kb} KB without resizing (resizeToReachTarget is off)')
            return best
        size = best[0]
        scale = max(0.3, min(0.9, math.sqrt(target / len(size)) * 0.95))
        w, h = frames[0].size
        nw, nh = max(1, int(w * scale)), max(1, int(h * scale))
        if (nw, nh) == (w, h) or nw < 16 or nh < 16:
            break
        frames = [f.resize((nw, nh), Image.Resampling.LANCZOS) for f in frames]
        notes.append(f'scaled down to {nw}x{nh} to reach the {opts.target_kb} KB target')
        cand = encode(frames, durs, loop, key, opts.quality if lossy else q, opts, meta)
        best = (cand, opts.quality if lossy else q, frames)
        if len(cand) <= target:
            return best
    notes.append(f'could not reach the {opts.target_kb} KB target; this is the smallest version')
    return best
