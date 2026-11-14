#!/usr/bin/env python3
"""Record resolved inputs and enforce selected package/core provenance."""
import argparse
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import tarfile

spec = importlib.util.spec_from_file_location('inputs', Path(__file__).with_name('prepare-inputs.py'))
inputs = importlib.util.module_from_spec(spec)
spec.loader.exec_module(inputs)


def scan(root):
    result = subprocess.run(['rg', '--files', '-uuu', str(root)], check=True,
                            text=True, stdout=subprocess.PIPE)
    return [Path(p) for p in result.stdout.splitlines()]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('phase', choices=['before', 'after', 'final'])
    parser.add_argument('--root', type=Path, default=Path('.'))
    parser.add_argument('--output', type=Path, default=Path('bin/n1-audit'))
    args = parser.parse_args()
    args.root = args.root.resolve()
    args.output = args.output.resolve()
    args.output.mkdir(parents=True, exist_ok=True)
    lock = json.loads(Path(__file__).with_name('inputs.lock.json').read_text())
    if args.phase == 'final':
        images = sorted(args.root.glob('*.img.gz'))
        if not images:
            raise ValueError('No final N1 image found')
        (args.output / 'SHA256SUMS').write_text(''.join(f'{inputs.sha256(p)}  {p.name}\n' for p in images))
        return
    manifest = {'phase': args.phase, 'files': {}, 'installed': [],
                'reproducibility_gaps': lock['reproducibility_gaps']}
    known_hashes = set()
    ipks = []
    manifest['overlay_files'] = {}
    manifest['index_hashes'] = {}
    snapshots = args.output / (args.phase + '-indexes')
    for path in scan(args.root):
        if args.output in path.parents or path.is_symlink() or not path.is_file():
            continue
        relative = str(path.relative_to(args.root))
        if relative.startswith('files/'):
            manifest['overlay_files'][relative] = inputs.sha256(path)
        is_index = path.name.startswith('Packages') or path.parent.name == 'dl'
        if path.suffix == '.ipk':
            ipks.append(path)
        if path.suffix in ('.ipk', '.run') or is_index or path.name in ('repositories.conf', '.config', 'Makefile'):
            digest = inputs.sha256(path)
            manifest['files'][relative] = digest
            if is_index and path.suffix != '.ipk':
                manifest['index_hashes'][relative] = digest
                target = snapshots / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(path, target)
                try:
                    data = path.read_bytes()
                    if data[:2] == b'\x1f\x8b':
                        data = inputs.gzip.decompress(data)
                    known_hashes.update(row['SHA256sum'] for row in inputs.records(data) if 'SHA256sum' in row)
                except (UnicodeError, ValueError, OSError):
                    pass
    manifest['ipk_index_validation'] = []
    for path in ipks:
        digest = inputs.sha256(path)
        matched = digest in known_hashes
        manifest['ipk_index_validation'].append({'file': str(path.relative_to(args.root)),
                                                  'sha256': digest, 'index_hash_match': matched})
        # Local vendor IPKs have separately verified archive provenance; cached downloads must match indexes.
        if args.phase == 'after' and 'dl' in path.relative_to(args.root).parts and not matched:
            raise ValueError(f'Downloaded IPK has no matching SHA256 in captured indexes: {path.name}')
    if args.phase == 'after':
        before = json.loads((args.output / 'before-manifest.json').read_text())
        for name, digest in before['index_hashes'].items():
            if manifest['index_hashes'].get(name) != digest:
                raise ValueError(f'Frozen package index changed during installation: {name}')
        roots = sorted(args.root.glob('bin/targets/armsr/armv8/*rootfs.tar.gz'))
        if not roots:
            raise ValueError('No rootfs available for installed-version audit')
        expected = dict(lock['nikki_packages'])
        enabled = os.environ.get('INCLUDE_OPENCLASH', 'yes') == 'yes'
        if enabled:
            expected['luci-app-openclash'] = lock['openclash']['version']
        for rootfs in roots:
            with tarfile.open(rootfs, 'r:gz') as tar:
                members = {m.name.removeprefix('./').lstrip('/'): m for m in tar.getmembers()}
                status = tar.extractfile(members['usr/lib/opkg/status']).read()
                installed = {r['Package']: r['Version'] for r in inputs.records(status)
                             if r.get('Status', '').split()[-1:] in (['installed'], ['unpacked'])}
                for name, version in expected.items():
                    if installed.get(name) != version:
                        raise ValueError(f'Installed version drift: {name} expected {version}, got {installed.get(name)}')
                if not enabled and 'luci-app-openclash' in installed:
                    raise ValueError('OpenClash installed despite include_openclash=no')
                staged_manifest = json.loads((args.root / 'n1-inputs/inputs-manifest.json').read_text())
                for name, digest in staged_manifest['package_owned_files'].items():
                    member = members[name]
                    if not member.isfile() or inputs.hashlib.sha256(tar.extractfile(member).read()).hexdigest() != digest:
                        raise ValueError(f'Package-owned core was replaced: {name}')
                link = members.get('usr/bin/mihomo')
                if link is not None:
                    if not link.issym() or link.linkname not in ('/usr/libexec/mihomo', '../libexec/mihomo'):
                        raise ValueError('Nikki alternative points away from the official core')
                # The image may defer alternatives creation to first boot.
                manifest['mihomo_alternative'] = 'official' if link else 'pending first-boot alternatives'
                if enabled:
                    core = members['etc/openclash/core/clash_meta']
                    if not core.isfile():
                        raise ValueError('OpenClash core must be independent regular file')
                    staged = args.root / 'files/etc/openclash/core/clash_meta'
                    actual = inputs.hashlib.sha256(tar.extractfile(core).read()).hexdigest()
                    if actual != inputs.sha256(staged):
                        raise ValueError('OpenClash core changed during image build')
                manifest['installed'].append({'rootfs': rootfs.name, 'sha256': inputs.sha256(rootfs), 'packages': installed})
        (args.output / 'installed-packages.txt').write_text(''.join(f'{n} - {v}\n' for n, v in sorted(installed.items())))
    (args.output / f'{args.phase}-manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')


if __name__ == '__main__':
    main()
