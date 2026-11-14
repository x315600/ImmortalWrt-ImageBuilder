#!/usr/bin/env python3
"""Copy checked local IPKs after optional Store staging; preserve vendor feeds."""
import importlib.util
import json
import os
from pathlib import Path
import shutil

spec = importlib.util.spec_from_file_location('inputs', Path(__file__).with_name('prepare-inputs.py'))
inputs = importlib.util.module_from_spec(spec)
spec.loader.exec_module(inputs)
root = Path.cwd()
stage = root / 'n1-inputs'
manifest = json.loads((stage / 'inputs-manifest.json').read_text())
lock = Path(__file__).with_name('inputs.lock.json')
inputs.checked(lock, manifest['lock_sha256'])
if os.environ.get('INCLUDE_OPENCLASH', 'yes') != manifest['include_openclash']:
    raise ValueError('Staged OpenClash option differs from requested build')
packages = root / 'packages'
packages.mkdir(exist_ok=True)
managed = set(manifest['nikki_packages']) | {'mihomo-alpha', 'luci-app-openclash'}
# Remove all competing locally staged versions, including those from Store.
for path in packages.glob('*.ipk'):
    if path.name.split('_', 1)[0] in managed:
        path.unlink()
for name, digest in manifest['packages'].items():
    source = inputs.checked(stage / 'packages' / name, digest)
    shutil.copyfile(source, packages / name)
for name, digest in manifest['overlay'].items():
    path = root / 'files' / name
    if path.is_symlink():
        raise ValueError(f'Core overlay cannot be a symlink: {name}')
    inputs.checked(path, digest)
# Nikki's /usr/bin/mihomo alternative belongs to the official IPK only.
for name in ('usr/bin/mihomo', 'usr/libexec/mihomo'):
    path = root / 'files' / name
    if path.exists() or path.is_symlink():
        raise ValueError(f'Refusing to overwrite Nikki package-owned core: {name}')
conf = root / 'repositories.conf'
lines = [line for line in conf.read_text().splitlines()
         if not line.startswith(('arch aarch64_generic ', 'arch aarch64_cortex-a53 ', 'src/gz nikki-local '))]
lines = ['arch aarch64_generic 10', 'arch aarch64_cortex-a53 15'] + lines
if not any(line.startswith('src ') and 'packages' in line for line in lines):
    lines.append('src imagebuilder file:packages')
conf.write_text('\n'.join(lines) + '\n')
for filename in ('Packages', 'Packages.gz', 'Packages.sig'):
    (packages / filename).unlink(missing_ok=True)
# ImageBuilder regenerates and signs its own index as part of make image.
out = root / 'bin/n1-audit'
out.mkdir(parents=True, exist_ok=True)
shutil.copyfile(stage / 'inputs-manifest.json', out / 'inputs-manifest.json')
shutil.copyfile(lock, out / 'inputs.lock.json')
shutil.copytree(stage / 'upstream-nikki', out / 'upstream-nikki', dirs_exist_ok=True)
(out / 'pinned-package-paths.txt').write_text(' '.join(str(packages / name) for name in manifest['packages']) + '\n')
print('Verified official IPKs staged into ImageBuilder packages/')
