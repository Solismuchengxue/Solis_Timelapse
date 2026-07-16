"""Stateless image operations used by the one-pass rendering pipeline."""

from io import BytesIO
from pathlib import Path

import numpy as np
from PIL import Image


RAW_EXTENSIONS = {".arw"}
GRADE_PRESETS = {
    "punchy": {"sat": 1.25, "con": 1.18, "pivot": 110.0},
    "natural": {"sat": 1.20, "con": 1.12, "pivot": 118.0},
    "clear": {"sat": 1.10, "con": 1.20, "pivot": 112.0},
    "custom": {"sat": 1.00, "con": 1.00, "pivot": 118.0},
    "none": {"sat": 1.00, "con": 1.00, "pivot": 118.0},
}
GOLDEN_STRENGTH = {"mild": 0.55, "medium": 0.85, "strong": 1.20}
_GAMMA = {"srgb": (2.222, 4.5), "linear": (1.0, 1.0)}


def _finite_number(
    value: float, name: str, minimum: float | None = None, maximum: float | None = None
) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as error:
        raise ValueError(f"{name} must be a finite number") from error
    if not np.isfinite(number):
        raise ValueError(f"{name} must be a finite number")
    if minimum is not None and number < minimum:
        raise ValueError(f"{name} must be at least {minimum}")
    if maximum is not None and number > maximum:
        raise ValueError(f"{name} must be at most {maximum}")
    return number


def _finite_rgb(rgb: np.ndarray) -> np.ndarray:
    array = np.asarray(rgb, dtype=np.float32)
    if array.ndim < 1 or array.shape[-1] != 3 or array.size == 0:
        raise ValueError("RGB image must be non-empty and have three channels")
    if not np.isfinite(array).all():
        raise ValueError("RGB image contains non-finite pixels")
    return array


def _window_size(window: int) -> int:
    number = _finite_number(window, "median window", 1, 1001)
    if not number.is_integer():
        raise ValueError("median window must be an integer")
    return int(number)


def frame_num(path: str | Path) -> int:
    """Extract the numeric part of a frame name, or -1 when absent."""
    base = Path(path).stem
    digits = "".join(character for character in base if character.isdigit())
    return int(digits) if digits else -1


def is_raw(path: str | Path) -> bool:
    return Path(path).suffix.lower() in RAW_EXTENSIONS


def decode_raw(
    path: str | Path,
    bright: float = 3.5,
    wb: str = "camera",
    gamma: str = "srgb",
    half: bool = False,
) -> np.ndarray:
    import rawpy

    bright = _finite_number(bright, "RAW brightness", 0.01, 16.0)

    with rawpy.imread(str(path)) as raw:
        return raw.postprocess(
            use_camera_wb=(wb == "camera"),
            use_auto_wb=(wb == "auto"),
            no_auto_bright=True,
            bright=bright,
            output_bps=8,
            gamma=_GAMMA.get(gamma, _GAMMA["srgb"]),
            half_size=half,
        ).astype(np.float32)


def load_image(
    path: str | Path, decode: dict | None = None, half: bool = False
) -> np.ndarray:
    """Decode a RAW or JPEG source without modifying it."""
    options = decode or {}
    if is_raw(path):
        return decode_raw(
            path,
            options.get("bright", 3.5),
            options.get("wb", "camera"),
            options.get("gamma", "srgb"),
            half,
        )

    with Image.open(path) as source:
        image = source.convert("RGB")
        if half:
            image = image.resize(
                (max(1, image.width // 2), max(1, image.height // 2)),
                Image.Resampling.BILINEAR,
            )
        return np.asarray(image, dtype=np.float32)


def load_preview(
    path: str | Path,
    decode: dict | None = None,
    max_size: tuple[int, int] = (640, 480),
) -> np.ndarray:
    """Decode a small analysis preview without changing final render quality."""
    source_path = Path(path)
    image = None
    if is_raw(source_path):
        try:
            import rawpy

            with rawpy.imread(str(source_path)) as raw:
                thumbnail = raw.extract_thumb()
            if thumbnail.format == rawpy.ThumbFormat.JPEG:
                image = Image.open(BytesIO(thumbnail.data))
            else:
                image = Image.fromarray(thumbnail.data)
        except (OSError, RuntimeError, ValueError):
            rgb = load_image(source_path, decode, half=True)
            image = Image.fromarray(np.clip(rgb, 0, 255).astype(np.uint8))
    else:
        image = Image.open(source_path)
        image.draft("RGB", max_size)

    try:
        converted = image.convert("RGB")
        converted.thumbnail(max_size, Image.Resampling.BILINEAR)
        return np.asarray(converted, dtype=np.float32)
    finally:
        image.close()


def measure_luminance(rgb: np.ndarray) -> float:
    return float(_finite_rgb(rgb).mean(dtype=np.float64))


def save_jpeg(rgb: np.ndarray, path: str | Path, quality: int = 95) -> None:
    output = Path(path)
    quality_value = _finite_number(quality, "JPEG quality", 1, 100)
    if not quality_value.is_integer():
        raise ValueError("JPEG quality must be an integer")
    Image.fromarray(np.clip(_finite_rgb(rgb), 0, 255).astype(np.uint8)).save(
        output, format="JPEG", quality=int(quality_value)
    )


def smooth_median(values: np.ndarray | list[float], window: int) -> np.ndarray:
    values = np.asarray(values, dtype=np.float64)
    if values.ndim != 1 or values.size == 0:
        raise ValueError("luminance must be a non-empty one-dimensional sequence")
    if not np.isfinite(values).all() or np.any(values < 0):
        raise ValueError("luminance values must be finite and non-negative")
    window = _window_size(window)
    half = window // 2
    output = np.empty(len(values), dtype=np.float64)
    for index in range(len(values)):
        output[index] = np.median(
            values[max(0, index - half) : min(len(values), index + half + 1)]
        )
    return output


def exposure_gain(
    luminance: np.ndarray | list[float], window: int, clip: tuple[float, float] | list[float]
) -> np.ndarray:
    luminance = np.asarray(luminance, dtype=np.float64)
    if luminance.ndim != 1 or luminance.size == 0:
        raise ValueError("luminance must be a non-empty one-dimensional sequence")
    if not np.isfinite(luminance).all() or np.any(luminance < 0):
        raise ValueError("luminance values must be finite and non-negative")
    if not isinstance(clip, (tuple, list)) or len(clip) != 2:
        raise ValueError("gain clip must contain lower and upper bounds")
    lower = _finite_number(clip[0], "gain clip lower bound", 1e-6, 16.0)
    upper = _finite_number(clip[1], "gain clip upper bound", 1e-6, 16.0)
    if lower > upper:
        raise ValueError("gain clip lower bound must not exceed upper bound")
    target = smooth_median(luminance, window)
    gain = np.clip(target / np.maximum(luminance, 1e-6), lower, upper)
    if not np.isfinite(gain).all():
        raise ValueError("calculated exposure gain is not finite")
    return gain


def apply_gain(rgb: np.ndarray, gain: float) -> np.ndarray:
    gain = _finite_number(gain, "exposure gain", 0.0, 16.0)
    return np.clip(_finite_rgb(rgb) * gain, 0, 255)


def grade(rgb: np.ndarray, sat: float, con: float, pivot: float) -> np.ndarray:
    rgb = _finite_rgb(rgb)
    sat = _finite_number(sat, "saturation", 0.0, 4.0)
    con = _finite_number(con, "contrast", 0.0, 4.0)
    pivot = _finite_number(pivot, "grade pivot", 0.0, 255.0)
    gray = rgb.mean(axis=2, keepdims=True)
    output = gray + (rgb - gray) * sat
    output = (output - pivot) * con + pivot
    return np.clip(output, 0, 255)


def grade_by_style(
    rgb: np.ndarray, style: str, overrides: dict | None = None
) -> np.ndarray:
    if overrides is not None and not isinstance(overrides, dict):
        raise ValueError("grade overrides must be a mapping")
    parameters = dict(GRADE_PRESETS.get(style, GRADE_PRESETS["none"]))
    parameters.update(
        {
            key: value
            for key, value in (overrides or {}).items()
            if key in ("sat", "con", "pivot")
        }
    )
    return grade(rgb, parameters["sat"], parameters["con"], parameters["pivot"])


def rgb2hsv(rgb: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    rgb = _finite_rgb(rgb)
    r, g, b = rgb[..., 0] / 255.0, rgb[..., 1] / 255.0, rgb[..., 2] / 255.0
    maximum = np.maximum(np.maximum(r, g), b)
    minimum = np.minimum(np.minimum(r, g), b)
    difference = maximum - minimum
    hue = np.zeros_like(maximum)
    colored = difference > 1e-9
    red = (maximum == r) & colored
    green = (maximum == g) & colored & ~red
    blue = (maximum == b) & colored & ~red & ~green
    hue[red] = ((g - b)[red] / difference[red]) % 6
    hue[green] = ((b - r)[green] / difference[green]) + 2
    hue[blue] = ((r - g)[blue] / difference[blue]) + 4
    hue /= 6.0
    saturation = np.where(
        maximum > 0, difference / np.maximum(maximum, 1e-9), 0
    )
    return hue, saturation, maximum


def hsv2rgb(hue: np.ndarray, saturation: np.ndarray, value: np.ndarray) -> np.ndarray:
    hue = np.asarray(hue, dtype=np.float64)
    saturation = np.asarray(saturation, dtype=np.float64)
    value = np.asarray(value, dtype=np.float64)
    if not (np.isfinite(hue).all() and np.isfinite(saturation).all() and np.isfinite(value).all()):
        raise ValueError("HSV values must be finite")
    if np.any(hue < 0) or np.any(hue > 1):
        raise ValueError("hue must be between 0 and 1")
    if np.any(saturation < 0) or np.any(saturation > 1):
        raise ValueError("saturation must be between 0 and 1")
    if np.any(value < 0) or np.any(value > 1):
        raise ValueError("value must be between 0 and 1")
    hue6 = (hue * 6.0) % 6
    sector = np.floor(hue6).astype(int)
    fraction = hue6 - sector
    p = value * (1 - saturation)
    q = value * (1 - saturation * fraction)
    t = value * (1 - saturation * (1 - fraction))
    red = np.choose(sector, [value, q, p, p, t, value])
    green = np.choose(sector, [t, value, value, q, p, p])
    blue = np.choose(sector, [p, p, t, value, value, q])
    return np.stack([red, green, blue], axis=-1) * 255.0


def enhance_golden(rgb: np.ndarray, strength: float) -> np.ndarray:
    """Enhance warm lit areas while separating cooler environmental shadows."""
    rgb = _finite_rgb(rgb)
    strength = _finite_number(strength, "golden strength", 0.0, 4.0)
    if strength <= 0:
        return rgb
    hue, saturation, value = rgb2hsv(rgb)
    golden_hue = np.clip(1 - np.abs(hue - 0.09) / 0.11, 0, 1)
    lit = np.clip((value - 0.42) / 0.42, 0, 1)
    golden = golden_hue * lit
    shadow = np.clip((0.38 - value) / 0.38, 0, 1)
    value2 = np.clip(
        value + golden * 0.18 * strength - shadow * 0.17 * strength, 0, 1
    )
    saturation2 = np.clip(saturation + golden * 0.38 * strength, 0, 1)
    hue2 = hue + golden * (0.075 - hue) * 0.35 * strength
    output = hsv2rgb(np.clip(hue2, 0, 1), saturation2, value2)
    output[..., 2] += shadow * 15 * strength
    output[..., 0] -= shadow * 8 * strength
    return np.clip(output, 0, 255)


def golden_ramp_strength(
    number: int, core: tuple[int, int] | list[int], ramp: int, full: float
) -> float:
    if not isinstance(core, (tuple, list)) or len(core) != 2:
        raise ValueError("golden core must contain start and end frame numbers")
    low = _finite_number(core[0], "golden core start")
    high = _finite_number(core[1], "golden core end")
    if not low.is_integer() or not high.is_integer() or low > high:
        raise ValueError("golden core must be an ordered integer frame range")
    ramp_value = _finite_number(ramp, "golden ramp", 0.0)
    if not ramp_value.is_integer():
        raise ValueError("golden ramp must be an integer")
    full = _finite_number(full, "golden strength", 0.0, 4.0)
    low, high, ramp = int(low), int(high), int(ramp_value)
    if low <= number <= high:
        return float(full)
    if ramp <= 0:
        return 0.0
    if low - ramp <= number < low:
        return float(full) * (number - (low - ramp)) / ramp
    if high < number <= high + ramp:
        return float(full) * ((high + ramp) - number) / ramp
    return 0.0
