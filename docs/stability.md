# API stability

earthfetch is pre-1.0 and its development status is **Alpha**. This page
sets expectations so you can depend on it deliberately.

## Versioning

Releases follow [semantic versioning](https://semver.org/). While the
project is `0.x`:

- **Minor** versions (`0.6 → 0.7`) may contain breaking changes. Each is
  called out in the [changelog](https://github.com/Ethan-M2024/earthfetch/blob/main/CHANGELOG.md)
  under a **Changed** heading.
- **Patch** versions (`0.7.0 → 0.7.1`) are bug fixes and additive only.

**Pin what you ship.** For anything that matters, pin an exact version
(`earthfetch==0.7.0`) and read the changelog before upgrading. The API is
still settling and will keep moving until 1.0.

## What is public

The public API is exactly the names exported from the top-level package —
everything in `earthfetch.__all__` and documented in the
[API reference](api.md). That includes the functions, the `AOI` type, the
metadata dicts (`BAND_PRESETS`, `DEM_DATASETS`, ...), and the exception
hierarchy.

Anything else is internal and may change without notice:

- modules whose name starts with an underscore (`earthfetch._composite`,
  `earthfetch._terrain`);
- names starting with an underscore (`_to_dataarray`, `_resolve_res`, ...);
- the exact wording of log messages and error strings.

Importing from a submodule directly (`from earthfetch.load import ...`) is
not covered by the stability policy — import from the top level (`import
earthfetch as ef; ef.load_dem(...)`).

## Deprecation

Once the surface stabilizes, changes to public API will go through one
minor release of `DeprecationWarning` before removal, with the replacement
named in the warning. Until then, breaking changes are documented in the
changelog per release.

## Toward 1.0

1.0 will mark a commitment to backward compatibility within the major
version. The path there is: settle the array/return-type conventions, lock
the source/loader defaults (the `0.6.0` reflectance change was one such
settling step), and let the API sit through real-world use.
