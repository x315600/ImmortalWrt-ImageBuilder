#!/usr/bin/env python3
"""Regression: frozen package_reload retains rootfs/tmp after make image cleanup."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

FREEZE = Path(__file__).resolve().parents[1] / 'freeze-feeds.py'
FIXTURE = '''TOPDIR := .
TARGET_DIR := rootfs
TMP_DIR := build-tmp
.PHONY: image package_install
image:
\trm -rf "$(TARGET_DIR)" "$(TMP_DIR)"
\tmkdir -p "$(TARGET_DIR)"
\t$(MAKE) package_reload
\t$(MAKE) package_install
package_reload:
\t@mkdir -p "$(TARGET_DIR)/tmp"
package_install:
\t@test -d "$(TARGET_DIR)/tmp"
\t@touch "$(TARGET_DIR)/tmp/opkg.lock"
'''


class FrozenReloadTests(unittest.TestCase):
    def test_clean_rootfs_keeps_lock_directory_without_refresh(self):
        with tempfile.TemporaryDirectory(prefix='n1-freeze-regression-') as tmp:
            root = Path(tmp)
            (root / 'dl').mkdir()
            index = root / 'dl/fixture'
            original = b'Package: fixture\nSHA256sum: ' + b'0' * 64 + b'\n'
            index.write_bytes(original)
            (root / 'repositories.conf').write_text('src/gz fixture https://example.invalid/packages\n')
            audit = root / 'bin/n1-audit'
            audit.mkdir(parents=True)
            (audit / 'before-manifest.json').write_text(json.dumps({'fixture': True}))
            makefile = root / 'Makefile'
            makefile.write_text(FIXTURE)
            subprocess.run([sys.executable, '-B', str(FREEZE)], cwd=root,
                           check=True, capture_output=True, timeout=20)
            frozen = makefile.read_text()
            self.assertEqual(frozen.count('\npackage_reload:\n'), 1)
            # Reproduce d7b6c6e's override as a negative control.
            broken = frozen.replace('\t@mkdir -p "$(TARGET_DIR)/tmp" "$(TMP_DIR)"\n', '')
            self.assertNotEqual(broken, frozen)
            makefile.write_text(broken)
            result = subprocess.run(['make', 'image'], cwd=root, capture_output=True, timeout=20)
            self.assertNotEqual(result.returncode, 0)
            makefile.write_text(frozen)
            for _ in range(2):
                subprocess.run(['make', 'image'], cwd=root, check=True,
                               capture_output=True, timeout=20)
                self.assertTrue((root / 'rootfs/tmp/opkg.lock').is_file())
                self.assertTrue((root / 'build-tmp').is_dir())
                self.assertEqual(index.read_bytes(), original)


if __name__ == '__main__':
    unittest.main()
