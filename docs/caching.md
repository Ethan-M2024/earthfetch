# Caching & configuration

## Download cache

`download_dem`, `download_copernicus_dem`, and `download_sentinel2` write to
a local cache and skip files that already exist, so repeated calls and
interrupted runs are cheap and resumable. (Windowed array reads — `load_*`,
`composite`, `terrain` — stream over HTTP and are not cached.)

Inspect and manage the cache from Python:

```python
import earthfetch as ef

ef.cache_dir()     # -> PosixPath('~/Library/Caches/earthfetch')  (platform dir)
ef.cache_info()    # -> {'path': '...', 'files': 12, 'bytes': 486539213}
ef.clear_cache()   # deletes everything; returns bytes freed
```

The location is the platform cache dir by default (`~/Library/Caches` on
macOS, `%LOCALAPPDATA%` on Windows, `$XDG_CACHE_HOME` or `~/.cache` on
Linux). Override it with an environment variable:

```bash
export EARTHFETCH_CACHE=/data/earthfetch-cache
```

## Retries

Two independent layers retry transient failures:

- **HTTP requests** (search, geocode, downloads) use a session with
  exponential backoff on connection errors and on HTTP 429/500/502/503/504.
- **Windowed COG reads** go through GDAL, which does its own HTTP and so has
  its own retry — earthfetch configures GDAL to match.

Both are tunable with environment variables:

| Variable | Default | Effect |
|---|---|---|
| `EARTHFETCH_HTTP_RETRIES` | `4` | max retry attempts (HTTP session and GDAL) |
| `EARTHFETCH_HTTP_BACKOFF` | `1.0` | backoff factor / GDAL retry delay (seconds) |
| `EARTHFETCH_CACHE` | platform dir | download cache location |

```bash
# be more patient on a flaky connection
export EARTHFETCH_HTTP_RETRIES=8
export EARTHFETCH_HTTP_BACKOFF=2
```

## Logging

earthfetch never prints; it logs to the `earthfetch` logger. Turn on
progress and diagnostics with the standard library:

```python
import logging
logging.basicConfig(level=logging.INFO)
```

URLs are redacted in logs (query strings are stripped) so signed-URL
credentials never reach your log files.
