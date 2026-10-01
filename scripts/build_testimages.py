from pathlib import Path
import math
import random
import shutil
import numpy as np
from PIL import Image, ImageChops, ImageEnhance, ImageDraw, ImageFilter, ImageOps

ROOT = Path('/Users/kristofvandebeek/Documents/TestImages')
SOURCE = ROOT / 'Originals'
SEED = 20260930
TARGET = 10


def kind(im):
    return 'rgb' if im.mode in ('RGB', 'RGBA', 'CMYK') else 'mono'


def working_image(im):
    if im.mode == 'I;16':
        return Image.fromarray((np.asarray(im, dtype=np.uint16) // 257).astype(np.uint8), mode='L')
    return im


def selected_files():
    groups = {'rgb': [], 'mono': []}
    for path in sorted(SOURCE.iterdir()):
        if not path.is_file():
            continue
        try:
            with Image.open(path) as im:
                extrema = im.getextrema()
                channels = extrema if isinstance(extrema, tuple) and extrema and isinstance(extrema[0], tuple) else (extrema,)
                # Exclude solid black/white source frames from the test pool.
                if all(lo == hi for lo, hi in channels) or all(lo == 0 and hi == 0 for lo, hi in channels) or all(lo == hi and lo > 0 for lo, hi in channels):
                    continue
                groups[kind(im)].append(path)
        except Exception as exc:
            print(f'skip unreadable {path.name}: {exc}')
    rng = random.Random(SEED)
    chosen = []
    for label in ('rgb', 'mono'):
        items = groups[label][:]
        rng.shuffle(items)
        chosen.extend(items[:TARGET])
        print(f'{label}: {len(items)} available, selected {min(TARGET, len(items))}')
    return chosen


def convert_mode(im, source):
    with Image.open(source) as original:
        if original.mode in ('RGBA', 'RGB'):
            return im.convert('RGBA' if original.mode == 'RGBA' else 'RGB')
        if original.mode == 'I;16':
            # A Pillow conversion from L to I;16 does not expand 0..255.
            # Explicitly scale so 16-bit mono files remain displayable.
            gray = im.convert('L')
            return Image.fromarray((np.asarray(gray, dtype=np.uint16) * 257), mode='I;16')
        return im.convert(original.mode if original.mode == 'L' else 'L')


def transform(im, folder):
    name = folder.lower()
    if name.startswith('resize-'):
        pct = int(name.removeprefix('resize-').removesuffix('percent'))
        return im.resize((max(1, round(im.width * pct / 100)), max(1, round(im.height * pct / 100))), Image.Resampling.LANCZOS)
    if name == 'heavily-stretched':
        return im.resize((max(1, round(im.width * 2.8)), max(1, round(im.height * .38))), Image.Resampling.LANCZOS)
    if name == 'mirrored-horizontal':
        return ImageOps.mirror(im)
    if name == 'mirrored-vertical':
        return ImageOps.flip(im)
    if name == 'rotated':
        return im.rotate(90, expand=True)
    if name == 'varied-size-rotation':
        scale = (0.55, 0.8, 1.35, 1.8)[(im.width + im.height) % 4]
        angle = (15, 90, 180, 270)[(im.width // 17 + im.height // 13) % 4]
        resized = im.resize((max(1, round(im.width * scale)), max(1, round(im.height * scale))), Image.Resampling.LANCZOS)
        return resized.rotate(angle, expand=True, resample=Image.Resampling.BICUBIC)
    if name == 'slight-skew':
        amount = 0.045 if (im.width + im.height) % 2 else -0.045
        return im.transform(im.size, Image.Transform.AFFINE, (1, amount, 0, amount, 1, 0), resample=Image.Resampling.BICUBIC)
    if name == 'mild-stretch':
        return im.resize((max(1, round(im.width * 1.22)), max(1, round(im.height * .9))), Image.Resampling.LANCZOS)
    if name.startswith('blur-gaussian-'):
        radius = float(name.removeprefix('blur-gaussian-').removesuffix('px'))
        # Pillow cannot blur 16-bit integer TIFF images directly; use a
        # grayscale working image and convert back to the source mode on save.
        work = working_image(im)
        return work.filter(ImageFilter.GaussianBlur(radius))
    if name == 'blur-motion-5px':
        work = working_image(im)
        kernel = [(1 / 5 if row == 2 else 0) for row in range(5) for _ in range(5)]
        return work.filter(ImageFilter.Kernel((5, 5), kernel, scale=1))
    if name == 'reduced-contrast':
        work = working_image(im)
        return ImageEnhance.Contrast(work).enhance(0.55)
    if name == 'rgb-overloaded-saturation':
        return ImageEnhance.Color(im).enhance(2.8) if kind(im) == 'rgb' else im
    if name == 'bottom-black-cutouts':
        out = im.copy()
        draw = ImageDraw.Draw(out)
        h, w = out.height, out.width
        draw.rectangle((round(w * .08), round(h * .86), round(w * .38), h), fill=0)
        draw.rectangle((round(w * .58), round(h * .92), round(w * .93), h), fill=0)
        return out
    if name == 'middle-black-cutouts':
        out = im.copy()
        draw = ImageDraw.Draw(out)
        h, w = out.height, out.width
        draw.rectangle((round(w * .18), round(h * .43), round(w * .48), round(h * .55)), fill=0)
        draw.ellipse((round(w * .62), round(h * .28), round(w * .79), round(h * .46)), fill=0)
        return out
    if name == 'cropped':
        left, top = round(im.width * .06), round(im.height * .05)
        right, bottom = round(im.width * .94), round(im.height * .93)
        return im.crop((left, top, right, bottom))
    if name == 'black-split-half':
        out = im.copy()
        draw = ImageDraw.Draw(out)
        x1, x2 = round(out.width * .47), round(out.width * .53)
        draw.rectangle((x1, 0, x2, out.height), fill=0)
        return out
    if name == 'additional-edge-cases':
        work = working_image(im)
        # The caller supplies a deterministic variant through the image seed.
        rng = random.Random(im.width * 19 + im.height * 23)
        variant = rng.randrange(4)
        if variant == 0:  # uneven illumination / gradient
            overlay = Image.new('L', work.size)
            pix = overlay.load()
            for y in range(work.height):
                value = round(70 + 150 * y / max(1, work.height - 1))
                for x in range(work.width): pix[x, y] = value
            shaded = ImageChops.multiply(work.convert('L'), overlay)
            return shaded.convert('RGB') if kind(im) == 'rgb' else shaded
        if variant == 1:  # clipped highlights and shadows
            return ImageOps.autocontrast(work, cutoff=18)
        if variant == 2:  # strong sensor-like noise
            noise = Image.effect_noise(work.size, 55)
            if work.mode == 'RGB':
                noise = noise.convert('RGB')
            return ImageChops.add(work, noise, scale=2.0, offset=-32)
        # quantization / posterization
        return ImageOps.posterize(work.convert('RGB') if kind(im) == 'rgb' else work, 3)
    if name == 'speckled-noise':
        out = working_image(im).copy()
        draw = ImageDraw.Draw(out)
        rng = random.Random(im.width * 29 + im.height * 41)
        for _ in range(max(80, (out.width * out.height) // 18000)):
            x, y = rng.randrange(out.width), rng.randrange(out.height)
            radius = rng.choice((1, 1, 2, 3))
            value = rng.choice((0, 0, 255))
            draw.ellipse((x-radius, y-radius, x+radius, y+radius), fill=value)
        return out.convert('RGB') if kind(im) == 'rgb' else out
    if name == 'partial-blur':
        out = working_image(im).copy()
        blurred = out.filter(ImageFilter.GaussianBlur(5))
        mask = Image.new('L', out.size, 0)
        ImageDraw.Draw(mask).rectangle((0, 0, out.width // 2, out.height), fill=255)
        return Image.composite(blurred, out, mask)
    if name == 'partial-color':
        if kind(im) != 'rgb':
            return im
        work = im.convert('RGB')
        gray = ImageOps.grayscale(work).convert('RGB')
        mask = Image.new('L', work.size, 0)
        ImageDraw.Draw(mask).rectangle((work.width // 2, 0, work.width, work.height), fill=255)
        return Image.composite(gray, work, mask)
    if name == 'film-grain':
        work = working_image(im)
        noise = Image.effect_noise(work.size, 35)
        if work.mode == 'RGB': noise = noise.convert('RGB')
        return ImageChops.add(work, noise, scale=2.0, offset=-64)
    if name == 'true-black-white':
        return working_image(im).convert('L').point(lambda p: 255 if p >= 128 else 0, mode='1')
    if name == 'missing-vertical-10px':
        out = im.copy()
        x = out.width // 2
        ImageDraw.Draw(out).rectangle((x, 0, min(out.width - 1, x + 9), out.height), fill=0)
        return out
    if name == 'missing-horizontal-10px':
        out = im.copy()
        y = out.height // 2
        ImageDraw.Draw(out).rectangle((0, y, out.width, min(out.height - 1, y + 9)), fill=0)
        return out
    if name == 'adversarial-edge-cases':
        work = working_image(im)
        if kind(im) == 'rgb':
            work = work.convert('RGB')
            # Channel misregistration plus a color cast.
            r, g, b = work.split()
            r = ImageChops.offset(r, 3, 0)
            b = ImageChops.offset(b, -3, 1)
            work = Image.merge('RGB', (r, g.point(lambda p: min(255, p + 12)), b))
        # Duplicate-strip / ghost-like stacking defect.
        shifted = ImageChops.offset(work, 7, -2)
        work = Image.blend(work, shifted, .28)
        # Clipped highlights, dead/hot pixels, and missing corner region.
        draw = ImageDraw.Draw(work)
        draw.rectangle((0, 0, work.width // 12, work.height // 10), fill=255)
        draw.rectangle((work.width * 3 // 4, work.height * 3 // 4, work.width, work.height), fill=0)
        for x, y in ((work.width // 3, work.height // 3), (work.width // 2, work.height // 2), (work.width * 2 // 3, work.height // 4)):
            draw.point((x, y), fill=255)
        return work
    if name == 'double-moon':
        work = working_image(im)
        shifted = ImageChops.offset(work, work.width // 3, work.height // 12)
        return Image.blend(work, shifted, .48)
    if name == 'random-heavy-edits':
        rng = random.Random(SEED + im.width * 17 + im.height * 31)
        work = working_image(im)
        if rng.random() < 0.9:
            pct = rng.choice((29, 34, 41, 57, 73))
            work = work.resize((max(1, round(work.width * pct / 100)), max(1, round(work.height * pct / 100))), Image.Resampling.BILINEAR)
            work = work.resize((im.width, im.height), Image.Resampling.NEAREST)
        if rng.random() < 0.9:
            work = work.filter(ImageFilter.GaussianBlur(rng.choice((1.5, 2.5, 4.0, 6.0))))
        work = ImageEnhance.Contrast(work).enhance(rng.choice((0.25, 0.4, 0.7, 1.8)))
        work = ImageEnhance.Brightness(work).enhance(rng.choice((0.45, 0.7, 1.6, 2.4)))
        if kind(im) == 'rgb' and rng.random() < 0.8:
            work = ImageEnhance.Color(work).enhance(rng.choice((0.2, 2.5, 4.0)))
        if rng.random() < 0.7:
            work = work.filter(ImageFilter.UnsharpMask(radius=2, percent=250, threshold=4))
        if rng.random() < 0.65:
            draw = ImageDraw.Draw(work)
            if rng.random() < 0.5:
                draw.rectangle((0, round(work.height * rng.uniform(.72, .96)), work.width, work.height), fill=0)
            else:
                x = round(work.width * rng.uniform(.1, .7))
                y = round(work.height * rng.uniform(.2, .7))
                draw.rectangle((x, y, min(work.width, x + round(work.width * .25)), min(work.height, y + round(work.height * .12))), fill=0)
        return work
    if name == 'bad-stacked-ghosting':
        work = working_image(im)
        # Simulate misregistered stack frames: translated copies remain visible
        # around the lunar limb and high-contrast detail.
        layers = [
            (work, 0.52),
            (ImageChops.offset(work, round(work.width * .018), round(work.height * -.006)), 0.28),
            (ImageChops.offset(work, round(work.width * -.025), round(work.height * .010)), 0.20),
        ]
        result = Image.new(work.mode, work.size, 0)
        for layer, weight in layers:
            result = Image.blend(result, layer, weight)
        return result
    raise ValueError(folder)


def save_variant(folder, files):
    destination = ROOT / folder
    destination.mkdir(exist_ok=True)
    for old in destination.iterdir():
        if old.is_file() or old.is_symlink():
            old.unlink()
        elif old.is_dir():
            shutil.rmtree(old)
    for source in files:
        with Image.open(source) as original:
            original.load()
            result = transform(original, folder)
            result = convert_mode(result, source)
            result.save(destination / source.name, format=original.format or 'TIFF')
    print(f'{folder}: {len(files)} files')


def main():
    files = selected_files()
    folders = [p.name for p in ROOT.iterdir() if p.is_dir() and p.name != 'Originals']
    folders += ['Reduced-contrast', 'RGB-overloaded-saturation', 'Bottom-black-cutouts', 'Middle-black-cutouts', 'Cropped', 'Random-heavy-edits', 'Bad-stacked-ghosting', 'Resize-10percent', 'Black-split-half', 'Heavily-stretched', 'Additional-edge-cases', 'Mirrored-horizontal', 'Mirrored-vertical', 'Rotated', 'Speckled-noise', 'Partial-blur', 'Partial-color', 'Varied-size-rotation', 'Film-grain', 'True-black-white', 'Slight-skew', 'Mild-stretch', 'Missing-vertical-10px', 'Missing-horizontal-10px', 'Blur-gaussian-20px', 'Blur-motion-5px', 'Adversarial-edge-cases', 'Double-moon']
    for folder in sorted(set(folders)):
        if folder == 'Adversarial-edge-cases':
            subset = files[:2] + files[10:12]
        elif folder == 'Double-moon':
            subset = files[:1]
        else:
            subset = files[:5] if folder in ('Resize-10percent', 'Heavily-stretched') else files
        save_variant(folder, subset)


if __name__ == '__main__':
    main()
