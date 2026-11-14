#!/usr/bin/env python3
"""Keep ImageBuilder's first package_reload indexes unchanged during make image."""
from pathlib import Path
import shutil

# ImageBuilder's package_reload historically masks update failures with || true.
# Require each configured remote feed to have a captured, non-empty index.
for line in Path('repositories.conf').read_text().splitlines():
    fields = line.split()
    if len(fields) >= 3 and fields[0] in ('src', 'src/gz') and fields[2].startswith(('https://', 'http://')):
        index = Path('dl') / fields[1]
        if not index.is_file() or index.stat().st_size == 0:
            raise ValueError(f'Missing downloaded index for feed: {fields[1]}')
        data = index.read_bytes()
        if data[:2] == b'\x1f\x8b':
            import gzip
            data = gzip.decompress(data)
        if b'Package: ' not in data or b'SHA256sum: ' not in data:
            raise ValueError(f'Feed lacks SHA256 package records: {fields[1]}')

makefile = Path('Makefile')
text = makefile.read_text()
marker = 'package_reload:\n'
if text.count(marker) != 1:
    raise ValueError('Unknown ImageBuilder package_reload layout; refusing unsafe override')
audit = Path('bin/n1-audit')
if not (audit / 'before-manifest.json').is_file():
    raise ValueError('Capture indexes before freezing feeds')
shutil.copyfile(makefile, audit / 'ImageBuilder.Makefile.original')
# make image explicitly clears MAKEFLAGS, so make -o would NOT propagate.
# Rename only this target; all native package_index/package_install code stays intact.
text = text.replace(marker, 'n1_package_reload_unfrozen:\n', 1)
text += '\n# N1: indexes were loaded and recorded before installation.\npackage_reload:\n\t@test -s $(TOPDIR)/bin/n1-audit/before-manifest.json\n'
makefile.write_text(text)
print('Frozen native ImageBuilder feed indexes for this build')
