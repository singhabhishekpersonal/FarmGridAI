"""Versioned static URLs, so a browser can never run a stale JS file.

Why this exists
---------------
While developing, `runserver` serves /static/ itself and its responses carry a
Last-Modified header but no Cache-Control. Browsers are then entitled to apply
*heuristic* freshness - commonly 10% of the file's age - so an edited app.js
can keep running in an already-open tab for minutes after the file changed on
disk. The result is "I fixed it and nothing happened", which is very hard to
debug and very easy to misread as the fix not working.

Adding a middleware for Cache-Control does not help, because the staticfiles
handler answers /static/ without passing through the middleware chain.

Appending the file's mtime to the URL sidesteps caching entirely: change the
file, the URL changes, the browser has no choice but to fetch the new bytes.
Only used in development - production uses collectstatic with real hashed names.
"""
import os

from django.contrib.staticfiles.finders import find
from django.contrib.staticfiles.storage import StaticFilesStorage


class VersionedStaticStorage(StaticFilesStorage):
    """Append ?v=<mtime> to every static URL."""

    def url(self, name):
        url = super().url(name)
        if url.startswith(("http://", "https://", "//")):
            return url
        if "?" in url:
            return url  # someone already versioned it
        # Locate the file through the finders rather than self.path(): that
        # resolves against STATIC_ROOT, which is empty until collectstatic has
        # run, and a missing file must not silently skip the cache-bust.
        located = find(name)
        if not located or not os.path.exists(located):
            return url
        return "%s?v=%d" % (url, int(os.path.getmtime(located)))