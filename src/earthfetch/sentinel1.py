"""Sentinel-1 SAR backscatter (radiometrically terrain corrected) via the
Microsoft Planetary Computer — no API key required.

Radar sees through cloud and works at night, so it is the source to reach for
when optical imagery can't: floods under storm cover, sea ice, winter
landscapes, crop structure. Uses the ``sentinel-1-rtc`` collection: gamma
naught backscatter, already terrain-flattened and on a 10 m UTM grid, with
anonymous SAS signing like NAIP and Landsat.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import xarray

import warnings
from collections import defaultdict
from collections.abc import Sequence

from .exceptions import BandNotFoundError, NoScenesError
from .utils import get_session, logger, validate_bbox

PC_STAC_URL = "https://planetarycomputer.microsoft.com/api/stac/v1/search"
COLLECTION = "sentinel-1-rtc"

#: polarizations served by the RTC collection (asset keys are lowercase)
POLARIZATIONS = ("VV", "VH", "HH", "HV")

#: VV backscatter (dB) below which a pixel reads as open water — smooth
#: water reflects the radar pulse away from the sensor. A common starting
#: point; tune per scene (wind-roughened water reads brighter).
WATER_DB = -18.0


def _pol(p: str) -> str:
    up = str(p).upper()
    if up not in POLARIZATIONS:
        raise BandNotFoundError(
            f"unknown Sentinel-1 polarization {p!r}; use one of {POLARIZATIONS}"
        )
    return up


def search_sentinel1(
    bbox: Sequence[float],
    start: str,
    end: str,
    orbit_state: str | None = None,
    limit: int = 100,
) -> list[dict]:
    """Search Sentinel-1 RTC scenes, newest first.

    ``orbit_state`` ("ascending"/"descending") keeps only one look direction,
    which matters when comparing dates — backscatter depends on geometry.
    """
    bbox = validate_bbox(bbox)
    body = {
        "collections": [COLLECTION],
        "bbox": list(bbox),
        "datetime": f"{start}T00:00:00Z/{end}T23:59:59Z",
        "limit": min(limit, 100),
        "sortby": [{"field": "properties.datetime", "direction": "desc"}],
    }
    if orbit_state:
        body["query"] = {"sat:orbit_state": {"eq": orbit_state.lower()}}
    resp = get_session().post(PC_STAC_URL, json=body, timeout=60)
    resp.raise_for_status()
    items = resp.json().get("features", [])
    items.sort(key=lambda i: i["properties"].get("datetime", ""), reverse=True)
    logger.info("Planetary Computer: %d Sentinel-1 scene(s) %s..%s", len(items),
                start, end)
    return items[:limit]


def acquisition_passes(items: Sequence[dict]) -> list[list[dict]]:
    """Group scenes into satellite passes (same day and relative orbit),
    newest pass first. The frames of one pass tile an AOI seamlessly."""
    groups: dict = defaultdict(list)
    for it in items:
        p = it["properties"]
        key = (p.get("datetime", "")[:10], p.get("sat:relative_orbit"),
               p.get("platform"))
        groups[key].append(it)
    return [groups[k] for k in sorted(groups, key=lambda k: k[0], reverse=True)]


def band_url(item: dict, pol: str) -> str:
    """Signed COG URL for one polarization of a Sentinel-1 RTC item."""
    from .landsat import sign_mpc

    key = _pol(pol).lower()
    if key not in item["assets"]:
        raise BandNotFoundError(
            f"{pol} not in scene {item.get('id')}; available: "
            f"{item['properties'].get('sar:polarizations')}"
        )
    return sign_mpc(item["assets"][key]["href"])


def load_sentinel1(
    aoi,
    polarizations: Sequence[str] = ("VV", "VH"),
    crs: str = "utm",
    res: float | None = None,
    start: str | None = None,
    end: str | None = None,
    item: dict | None = None,
    items: Sequence[dict] | None = None,
    orbit_state: str | None = None,
    method: str = "latest",
    max_passes: int = 6,
    db: bool = True,
    clip: bool | None = None,
) -> xarray.DataArray:
    """Sentinel-1 radar backscatter for any AOI as an ``xarray.DataArray``.

    Parameters
    ----------
    aoi : bbox, GeoJSON, vector file path, shapely geometry, or place name.
    polarizations : any of "VV", "VH" (and "HH"/"HV" over polar regions).
    crs : output CRS; "utm" picks the AOI's zone.
    res : pixel size in CRS units; defaults to 10 m (native).
    start, end : ISO dates to search between (ignored if ``item(s)`` given).
    item, items : explicit STAC item(s) to mosaic, skipping the search.
    orbit_state : "ascending" or "descending" to fix the look direction.
    method : "latest" mosaics the newest pass; "median" takes the per-pixel
        median over the newest ``max_passes`` passes, which suppresses
        speckle (the grainy noise every SAR image carries).
    db : return decibels (10·log10 of gamma naught). False keeps linear
        power, which is what you should average or difference.
    clip : NaN-out pixels outside a polygon AOI (default: True for explicit
        polygons, False for geocoded place names).

    Returns
    -------
    xarray.DataArray
        float32 (band, y, x) with band labels "VV"/"VH", NaN nodata, and
        scene ids, dates, and orbit direction in attrs.
    """
    from .aoi import resolve_aoi, resolve_crs

    try:
        import numpy as np

        from .load import _resolve_res, _to_dataarray, _xr
        from .raster import make_grid, mask_to_geometry, warp_into_grid

        _xr()
    except ImportError as exc:
        from .exceptions import MissingDependencyError

        raise MissingDependencyError(
            "'load_sentinel1' needs the optional 'xarray' dependencies; "
            "install with: pip install 'earthfetch[xarray]'"
        ) from exc

    if method not in ("latest", "median"):
        raise ValueError(f"method must be 'latest' or 'median', got {method!r}")
    pols = [_pol(p) for p in polarizations]
    a = resolve_aoi(aoi)
    bbox = a.bbox
    crs = resolve_crs(crs, bbox)

    if items is None and item is not None:
        items = [item]
    if items is not None:
        passes = acquisition_passes(list(items))
    else:
        if start is None or end is None:
            raise ValueError("pass start=/end= dates, or item=/items=")
        found = search_sentinel1(bbox, start, end, orbit_state=orbit_state)
        if not found:
            raise NoScenesError(
                f"no Sentinel-1 scenes for {tuple(bbox)} in {start}..{end}"
                + (f" ({orbit_state})" if orbit_state else "")
                + " — widen the dates (Sentinel-1 revisits every ~6-12 days)"
            )
        passes = acquisition_passes(found)
    if not passes:
        raise ValueError("items is empty")
    passes = passes[: (max_passes if method == "median" else 1)]

    res = _resolve_res(res, 10.0, crs)
    transform, width, height = make_grid(bbox, crs, res)
    logger.info("load_sentinel1: %d pass(es) %s -> %dx%d @ %s (%s)",
                len(passes), pols, width, height, crs, method)

    layers = []
    for p in pols:
        stack = []
        for group in passes:
            layer = warp_into_grid([band_url(it, p) for it in group],
                                   transform, width, height, crs)
            layer[layer <= 0] = np.nan  # -32768 fill and zero-power edges
            stack.append(layer)
        if len(stack) == 1:
            lin = stack[0]
        else:
            with warnings.catch_warnings():  # all-NaN pixels warn
                warnings.simplefilter("ignore", RuntimeWarning)
                lin = np.nanmedian(np.stack(stack), axis=0)
        if db:
            with np.errstate(divide="ignore", invalid="ignore"):
                lin = 10.0 * np.log10(lin)
        layers.append(lin.astype("float32"))
    data = np.stack(layers)

    if clip is None:
        clip = a.clip_default
    if clip and a.geometry is not None:
        mask_to_geometry(data, a.geometry, transform, crs)

    all_items = [it for g in passes for it in g]
    props = passes[0][0]["properties"]
    da = _to_dataarray(
        data, transform, width, height, crs, "sentinel1",
        {"source": "sentinel1", "units": "dB" if db else "linear",
         "method": method,
         "scene_ids": [it["id"] for it in all_items],
         "dates": sorted({it["properties"]["datetime"][:10] for it in all_items}),
         "datetime": props.get("datetime"),
         "orbit_state": props.get("sat:orbit_state")},
    )
    return da.assign_coords(band=("band", pols))


def water_mask(s1, threshold: float = WATER_DB, band: str = "VV"):
    """Open-water mask from Sentinel-1 backscatter: 1 water, 0 land, NaN nodata.

    Smooth water mirrors the radar pulse away, so it is the darkest surface in
    a scene. ``threshold`` is in dB (converted automatically if ``s1`` holds
    linear power). Works through cloud, which makes it the fast first look at
    a flood.
    """
    import numpy as np

    da = s1.sel(band=band.upper()) if "band" in s1.dims else s1
    vals = np.asarray(da.values, dtype="float32")
    if s1.attrs.get("units") == "linear":
        with np.errstate(divide="ignore", invalid="ignore"):
            vals = 10.0 * np.log10(vals)
    out = np.where(np.isfinite(vals), (vals < threshold).astype("float32"), np.nan)
    res = da.copy(data=out.astype("float32")).rename("water")
    if "band" in res.coords:
        res = res.drop_vars("band")
    res.attrs = {**s1.attrs, "threshold_db": threshold, "units": "water=1"}
    return res
