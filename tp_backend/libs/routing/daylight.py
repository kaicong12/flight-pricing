"""Sunrise and sunset, computed locally. NOAA's approximation, no API call."""

import math
from datetime import date


def sun_times(d: date, lat: float, lon: float, tz_min: int) -> tuple[float | None, float | None]:
    """Sunrise and sunset in local minutes past midnight, or (None, None) in polar day or night.

    The 90.833° zenith folds in refraction and the sun's radius. |cos H| > 1 means the sun never
    crosses the horizon that day, which Tromsø really does for weeks either side of the solstice.
    """
    n = (date(d.year, d.month, d.day) - date(d.year, 1, 1)).days + 1
    g = (2 * math.pi / 365) * (n - 1 + 0.5)
    eq = 229.18 * (0.000075 + 0.001868 * math.cos(g) - 0.032077 * math.sin(g)
                   - 0.014615 * math.cos(2 * g) - 0.040849 * math.sin(2 * g))
    dec = (0.006918 - 0.399912 * math.cos(g) + 0.070257 * math.sin(g)
           - 0.006758 * math.cos(2 * g) + 0.000907 * math.sin(2 * g)
           - 0.002697 * math.cos(3 * g) + 0.00148 * math.sin(3 * g))
    phi = math.radians(lat)
    cos_h = (math.cos(math.radians(90.833)) / (math.cos(phi) * math.cos(dec))
             - math.tan(phi) * math.tan(dec))
    if abs(cos_h) > 1:
        return (None, None)
    h = math.degrees(math.acos(cos_h))
    return (720 - 4 * (lon + h) - eq + tz_min, 720 - 4 * (lon - h) - eq + tz_min)
