import io
import pathlib

import pytest
from PIL import Image, ImageDraw

from src import imgproc as ip
from src.imgproc import ImageError, Options


def photo(w=1200, h=800, fmt='JPEG', mode='RGB', **save) -> bytes:
    """Synthetic 'photo': gradient + shapes, so encoders have real work to do."""
    im = Image.linear_gradient('L').resize((w, h)).convert(mode if mode != 'RGBA' else 'RGB')
    im = Image.merge('RGB', (im.convert('L'), im.convert('L').rotate(90, expand=False).resize((w, h)),
                             Image.effect_noise((w, h), 40))) if mode in ('RGB', 'RGBA') else im
    d = ImageDraw.Draw(im)
    for i in range(0, w, 97):
        d.ellipse((i, i % h, i + 80, (i % h) + 80), fill=(i % 255, 120, 200) if im.mode == 'RGB' else 128)
    if mode == 'RGBA':
        im = im.convert('RGBA')
        im.putalpha(Image.linear_gradient('L').resize((w, h)))
    b = io.BytesIO()
    im.save(b, fmt, **save)
    return b.getvalue()


def gps_exif(orientation=None) -> bytes:
    ex = Image.Exif()
    ex[0x010F] = 'TestCam'  # Make
    ex[0x8298] = 'Copyright Me'
    if orientation:
        ex[ip.ORIENTATION] = orientation
    gps = ex.get_ifd(ip.GPS_IFD)
    gps[1] = 'N'
    gps[2] = (32.0, 4.0, 0.0)
    gps[3] = 'E'
    gps[4] = (34.0, 46.0, 0.0)
    return ex.tobytes()


def run(data, **kw):
    opts = ip.parse_input({'imageUrls': [{'url': 'https://example.com/a.jpg'}], **kw})[1]
    ins = ip.inspect(data, opts)
    return ip.convert(data, ins, opts)


def test_parse_defaults_and_upload_first():
    urls, o = ip.parse_input({'imageUrls': [{'url': 'https://x.org/a.png'}, 'https://x.org/a.png', {'url': ' '}],
                              'uploadedFile': 'https://api.apify.com/v2/key-value-stores/s/records/up'})
    assert urls == ['https://api.apify.com/v2/key-value-stores/s/records/up', 'https://x.org/a.png']
    assert o.fmt == 'webp' and o.quality == 80 and o.metadata == 'all' and o.keep_icc and not o.zip
    assert ip.parse_input({'imageUrls': ['https://x/a'], 'outputFormat': 'JPG', 'stripMetadata': False})[1].fmt == 'jpeg'
    assert ip.parse_input({'imageUrls': ['https://x/a'], 'stripMetadata': False})[1].metadata == 'none'


@pytest.mark.parametrize('inp', [{}, {'imageUrls': []}, {'imageUrls': ['ftp://x/a.png']},
                                 {'imageUrls': ['https://x/a'], 'outputFormat': 'bmp'},
                                 {'imageUrls': ['https://x/a'], 'quality': 0},
                                 {'imageUrls': ['https://x/a'], 'quality': 'high'},
                                 {'imageUrls': ['https://x/a'], 'stripMetadata': 'some'},
                                 {'imageUrls': ['https://x/a'], 'backgroundColor': 'white'},
                                 {'imageUrls': ['https://x/a'], 'maxMegapixels': 500}])
def test_parse_rejects(inp):
    with pytest.raises(ImageError):
        ip.parse_input(inp)


def test_normalize_share_links():
    assert ip.normalize_url('https://drive.google.com/file/d/abc_1/view?usp=sharing') == \
        'https://drive.google.com/uc?export=download&id=abc_1'
    assert 'dl=1' in ip.normalize_url('https://www.dropbox.com/s/xyz/a.png?dl=0')
    assert ip.normalize_url(' https://x.org/a.png ') == 'https://x.org/a.png'


def test_fit_never_upscales():
    assert ip.fit(4000, 3000, 1600, 0) == (1600, 1200)
    assert ip.fit(4000, 3000, 0, 600) == (800, 600)
    assert ip.fit(4000, 3000, 1000, 1000) == (1000, 750)
    assert ip.fit(800, 600, 1600, 1600) == (800, 600)


def test_units_and_names():
    assert ip.units_for(0.1) == 1 and ip.units_for(25) == 1 and ip.units_for(25.01) == 2 and ip.units_for(100) == 4
    assert ip.file_stem('https://x.org/img/My%20Photo%20(1).JPG?x=1', 3) == 'My-Photo-(1)'
    assert ip.file_stem('https://x.org/', 7) == 'image-7'


def test_jpeg_to_webp_saves_and_strips_gps():
    src = photo(exif=gps_exif(), quality=95)
    out, key, info = run(src, outputFormat='webp', quality=75)
    assert key == 'webp' and out[:4] == b'RIFF' and out[8:12] == b'WEBP'
    assert info['outputBytes'] < info['originalBytes'] and info['savingsPercent'] > 30
    assert info['gpsRemoved'] and 'exif' in info['metadataRemoved']
    im = Image.open(io.BytesIO(out))
    assert len(im.getexif()) == 0


def test_gps_only_mode_keeps_camera_info():
    out, key, info = run(photo(exif=gps_exif(), quality=95), outputFormat='jpeg', stripMetadata='gps')
    ex = Image.open(io.BytesIO(out)).getexif()
    assert ex.get(0x010F) == 'TestCam' and not ex.get_ifd(ip.GPS_IFD) and info['metadataRemoved'] == ['gps']


def test_keep_all_metadata():
    out, _, info = run(photo(exif=gps_exif(), quality=95), outputFormat='jpeg', stripMetadata='none', quality=70)
    ex = Image.open(io.BytesIO(out)).getexif()
    assert ex.get_ifd(ip.GPS_IFD) and not info['gpsRemoved']


def test_exif_orientation_applied_and_resize():
    src = photo(1200, 800, exif=gps_exif(orientation=6))  # stored landscape, displayed portrait
    out, _, info = run(src, outputFormat='jpeg', maxWidth=400)
    im = Image.open(io.BytesIO(out))
    assert im.size == (400, 600) and (info['width'], info['height']) == (400, 600)
    assert im.getexif().get(ip.ORIENTATION) in (None, 1)


def test_png_alpha_to_jpeg_uses_background():
    src = photo(300, 200, fmt='PNG', mode='RGBA')
    out, key, info = run(src, outputFormat='jpeg', backgroundColor='#ff0000')
    im = Image.open(io.BytesIO(out))
    assert key == 'jpeg' and im.mode == 'RGB'
    r, g, b = im.getpixel((0, 0))  # alpha 0 at the left edge -> background shows through
    assert r > 200 and g < 60 and b < 60


def test_png_alpha_to_webp_keeps_alpha_and_avif_works():
    src = photo(300, 200, fmt='PNG', mode='RGBA')
    out, _, _ = run(src, outputFormat='webp')
    assert Image.open(io.BytesIO(out)).mode == 'RGBA'
    out, key, info = run(src, outputFormat='avif', quality=50)
    im = Image.open(io.BytesIO(out))
    assert key == 'avif' and im.format == 'AVIF' and im.size == (300, 200)


def test_png_reduce_colors_tinypng_style():
    src = photo(600, 400, fmt='PNG')
    _, _, plain = run(src, outputFormat='png')
    out, _, small = run(src, outputFormat='png', pngReduceColors=True)
    assert Image.open(io.BytesIO(out)).mode == 'P' and small['outputBytes'] < plain['outputBytes']


@pytest.mark.parametrize('fmt', ['jpeg', 'webp', 'avif'])
def test_target_size_reached(fmt):
    src = photo(1600, 1200, quality=95)
    out, _, info = run(src, outputFormat=fmt, quality=90, targetMaxSizeKB=60)
    assert len(out) <= 60 * 1024 and info['outputBytes'] == len(out)


def test_target_size_png_downscales():
    out, _, info = run(photo(800, 600, fmt='PNG'), outputFormat='png', targetMaxSizeKB=40)
    assert len(out) <= 40 * 1024 and 'note' in info


def test_keep_format_and_original_kept_if_smaller():
    src = photo(400, 300, quality=30)  # already tiny, no metadata
    out, key, info = run(src, outputFormat='keep', quality=95)
    assert key == 'jpeg' and out == src and 'original file was kept' in info['note'] and info['savingsPercent'] == 0
    out2, _, _ = run(src, outputFormat='keep', quality=95, keepOriginalIfSmaller=False)
    assert out2 != src


def test_keep_from_tiff_and_bmp_becomes_jpeg_or_png():
    _, key, _ = run(photo(200, 100, fmt='TIFF'), outputFormat='keep')
    assert key == 'jpeg'
    _, key, _ = run(photo(200, 100, fmt='PNG', mode='RGBA'), outputFormat='keep')
    assert key == 'png'
    _, key, _ = run(photo(200, 100, fmt='BMP'), outputFormat='keep')
    assert key == 'jpeg'


def gif_anim(n=6) -> bytes:
    frames = [Image.new('RGB', (120, 80), (i * 40, 255 - i * 40, 90)) for i in range(n)]
    b = io.BytesIO()
    frames[0].save(b, 'GIF', save_all=True, append_images=frames[1:], duration=120, loop=0)
    return b.getvalue()


def test_animated_gif_to_webp_keeps_frames_and_to_jpeg_first_frame():
    out, key, info = run(gif_anim(), outputFormat='webp')
    im = Image.open(io.BytesIO(out))
    assert key == 'webp' and getattr(im, 'n_frames', 1) == 6 and info['frames'] == 6
    out, _, info = run(gif_anim(), outputFormat='jpeg')
    assert info['frames'] == 1 and 'first frame' in info['note']


def test_cmyk_and_16bit_inputs():
    b = io.BytesIO()
    Image.new('CMYK', (64, 64), (0, 255, 255, 0)).save(b, 'JPEG')
    out, _, _ = run(b.getvalue(), outputFormat='webp')
    assert Image.open(io.BytesIO(out)).mode == 'RGB'
    b = io.BytesIO()
    Image.new('I;16', (64, 64), 30000).save(b, 'PNG')
    out, _, _ = run(b.getvalue(), outputFormat='jpeg')
    assert Image.open(io.BytesIO(out)).mode == 'L'


FIX = pathlib.Path(__file__).parent / 'fixtures'


def test_heic_input_decoded():
    # zPug_3.heic is from the pillow-heif test suite (BSD-3-Clause); not shipped in the public repo
    f = FIX / 'zPug_3.heic'
    if not f.exists():
        pytest.skip('HEIC fixture not present')
    out, key, info = run(f.read_bytes(), outputFormat='keep')
    assert info['inputFormat'] == 'heif' and key == 'jpeg' and Image.open(io.BytesIO(out)).size == (64, 64)


@pytest.mark.parametrize('data,msg', [(b'<!DOCTYPE html><html><body>hi', 'web page'), (b'<svg xmlns="x"></svg>', 'SVG'),
                                      (b'%PDF-1.4 ...', 'PDF'), (b'just some text', 'Not an image'), (b'', 'empty')])
def test_refuses_non_images(data, msg):
    with pytest.raises(ImageError, match=msg):
        ip.inspect(data, Options())


def test_megapixel_limit_from_header_only():
    src = photo(3000, 2000)
    with pytest.raises(ImageError, match='too large'):
        ip.inspect(src, Options(max_mp=5))
    ins = ip.inspect(src, Options())
    assert ins.units == 1 and abs(ins.megapixels - 6.0) < 0.01


def test_corrupt_image_reported():
    src = photo()[:2000]
    opts = Options()
    with pytest.raises(ImageError):
        ins = ip.inspect(src, opts)
        ip.convert(src, ins, opts)
