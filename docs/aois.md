# Areas of interest

Every public function takes its area of interest in any of these forms:

```python
ef.composite((-111.9, 40.7, -111.8, 40.8), ...)   # bbox tuple (WGS84)
ef.composite("Yosemite National Park", ...)        # place name (geocoded)
ef.composite("watershed.geojson", ...)             # GeoJSON file
ef.composite("/data/fields.shp", ...)              # shapefile (or .gpkg, .kml)
ef.composite(geojson_dict, ...)                    # GeoJSON dict
ef.composite(shapely_polygon, ...)                 # __geo_interface__
```

- **bbox** — `(min_lon, min_lat, max_lon, max_lat)` in WGS84 degrees.
- **place name** — resolved with OpenStreetMap Nominatim (free, no key).
- **GeoJSON / shapely** — Polygon, MultiPolygon, Point, LineString, and
  collections. Degenerate geometries (a Point, or an axis-aligned line)
  resolve to a small valid bbox around the feature.

## Vector files (shapefile, GeoPackage, KML)

Point any function at a local vector file. GeoJSON works out of the box;
shapefiles, GeoPackages, and KML need the `vector` extra
(`pip install "earthfetch[vector]"`):

```python
ef.load_dem("/data/basin.shp", ...)        # shapefile
ef.composite("/data/parcels.gpkg", ...)    # GeoPackage
```

All features in the file are unioned into one AOI, and — importantly — the
file's CRS is read and **reprojected to WGS84 automatically**, so a shapefile
stored in a UTM or State-Plane projection lands in the right place without any
manual step.

## Clipping

`crs="utm"` (the default for `composite`, `terrain`, `load_naip`) picks the
right UTM zone for metric pixels. Explicit polygons clip results to their
boundary; geocoded place names return the full rectangle (pass `clip=True`
to cut to the boundary).

::: earthfetch.aoi.resolve_aoi

::: earthfetch.aoi.geocode

::: earthfetch.aoi.utm_crs
