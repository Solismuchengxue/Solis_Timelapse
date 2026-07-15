"""Stateless image operations used by the one-pass rendering pipeline."""

from pathlib import Path

import numpy as np
from PIL import Image


RAW_EXTENSIONS = {".arw"}
GRADE_PRESETS = {
    "punchy": {"sat": 1.25, "con": 1.18, "pivot": 110.0},
    "natural": {"sat": 1.20, "con": 1.12, "pivot": 118.0},
    "none": {"sat": 1.00, "con": 1.00, "pivot": 118.0},
}
GOLDEN_STRENGTH = {"mild": 0.55, "medium": 0.85, "strong": 1.20}
_GAMMA = {"srgb": (2.222, 4.5), "linear": (1.0, 1.0)}


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


def measure_luminance(rgb: np.ndarray) -> float:
    return float(np.asarray(rgb, dtype=np.float64).mean())


def save_jpeg(rgb: np.ndarray, path: str | Path, quality: int = 95) -> None:
    output = Path(path)
    Image.fromarray(np.clip(rgb, 0, 255).astype(np.uint8)).save(
        output, format="JPEG", quality=quality
    )


def smooth_median(values: np.ndarray | list[float], window: int) -> np.ndarray:
    values = np.asarray(values, dtype=np.float64)
    if window < 1:
        raise ValueError("median window must be at least 1")
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
    target = smooth_median(luminance, window)
    return np.clip(target / np.maximum(luminance, 1e-6), clip[0], clip[1])


def apply_gain(rgb: np.ndarray, gain: float) -> np.ndarray:
    return np.clip(np.asarray(rgb, dtype=np.float32) * float(gain), 0, 255)


def grade(rgb: np.ndarray, sat: float, con: float, pivot: float) -> np.ndarray:
    gray = rgb.mean(axis=2, keepdims=True)
    output = gray + (rgb - gray) * sat
    output = (output - pivot) * con + pivot
    return np.clip(output, 0, 255)


def grade_by_style(
    rgb: np.ndarray, style: str, overrides: dict | None = None
) -> np.ndarray:
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
    low, high = core
    if low <= number <= high:
        return float(full)
    if ramp <= 0:
        return 0.0
    if low - ramp <= number < low:
        return float(full) * (number - (low - ramp)) / ramp
    if high < number <= high + ramp:
        return float(full) * ((high + ramp) - number) / ramp
    return 0.0
