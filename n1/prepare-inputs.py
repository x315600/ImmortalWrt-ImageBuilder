#!/usr/bin/env python3
"""Stage verified ARM64 inputs; never execute target binaries or call host opkg."""
import argparse
import base64
import gzip
import hashlib
import io
import json
from pathlib import Path
import shutil
import subprocess
import tarfile
import tempfile


def sha256(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def checked(path, expected):
    if sha256(path) != expected:
        raise ValueError(f'SHA256 mismatch: {path}')
    return path


def acquire(item, cache, offline):
    path = cache / item['filename']
    if path.exists():
        return checked(path, item['sha256'])
    if offline:
        raise FileNotFoundError(f'Offline input missing: {path}')
    partial = path.with_suffix(path.suffix + '.part')
    try:
        subprocess.run(['curl', '--fail', '--location', '--retry', '1',
                        '--connect-timeout', '15', '--max-time', '300',
                        '--output', str(partial), item['url']], check=True)
        checked(partial, item['sha256'])
        partial.replace(path)
    finally:
        partial.unlink(missing_ok=True)
    return path


def unpack(archive, destination):
    # Reject traversal, links, devices, and duplicate paths before extracting.
    with tarfile.open(archive, 'r:*') as tar:
        names = set()
        for member in tar.getmembers():
            path = Path(member.name)
            if path.is_absolute() or '..' in path.parts or not (member.isfile() or member.isdir()):
                raise ValueError(f'Unsafe archive member: {member.name}')
            if str(path) in names:
                raise ValueError(f'Duplicate archive member: {member.name}')
            names.add(str(path))
        tar.extractall(destination)


def records(data):
    result = []
    for block in data.decode().strip().split('\n\n'):
        row = {}
        for line in block.splitlines():
            if line and not line[0].isspace() and ': ' in line:
                key, value = line.split(': ', 1)
                row[key] = value
        if row:
            result.append(row)
    return result


def ipk_control(path):
    # OpenWrt IPKs use tar; reject a changed archive format rather than guessing.
    with tarfile.open(path, 'r:*') as outer:
        member = next(m for m in outer.getmembers() if Path(m.name).name == 'control.tar.gz')
        with tarfile.open(fileobj=io.BytesIO(outer.extractfile(member).read()), mode='r:gz') as control:
            member = next(m for m in control.getmembers() if Path(m.name).name == 'control')
            return records(control.extractfile(member).read())[0]


def ipk_file_hash(path, filename):
    with tarfile.open(path, 'r:*') as outer:
        member = next(m for m in outer.getmembers() if Path(m.name).name == 'data.tar.gz')
        with tarfile.open(fileobj=io.BytesIO(outer.extractfile(member).read()), mode='r:gz') as data:
            member = next(m for m in data.getmembers() if m.name.removeprefix('./') == filename)
            if not member.isfile():
                raise ValueError(f'Expected regular package file: {filename}')
            return hashlib.sha256(data.extractfile(member).read()).hexdigest()


def install(source, target, mode):
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.is_symlink():
        raise ValueError(f'Refusing symlink destination: {target}')
    shutil.copyfile(source, target)
    target.chmod(mode)


def verify_bundle(bundle, key, lock):
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
    public = base64.b64decode(key.read_text().splitlines()[1], validate=True)
    signature = base64.b64decode((bundle / 'Packages.sig').read_text().splitlines()[1], validate=True)
    if len(public) != 42 or len(signature) != 74 or public[:10] != signature[:10] or public[:2] != b'Ed':
        raise ValueError('Invalid usign Ed25519 key/signature envelope')
    index = (bundle / 'Packages').read_bytes()
    Ed25519PublicKey.from_public_bytes(public[10:]).verify(signature[10:], index)
    if gzip.decompress((bundle / 'Packages.gz').read_bytes()) != index:
        raise ValueError('Signed Packages differs from Packages.gz')
    selected = {}
    for row in records(index):
        filename = row['Filename']
        if Path(filename).name != filename:
            raise ValueError('Unsafe package filename')
        path = checked(bundle / filename, row['SHA256sum'])
        if path.stat().st_size != int(row['Size']):
            raise ValueError(f'Package size mismatch: {filename}')
        name = row['Package']
        if name in lock['nikki_packages']:
            if name in selected or row['Version'] != lock['nikki_packages'][name]:
                raise ValueError(f'Unexpected package version: {name}')
            actual = ipk_control(path)
            for field in ('Package', 'Version', 'Architecture'):
                if actual[field] != row[field]:
                    raise ValueError(f'IPK metadata mismatch: {filename}: {field}')
            selected[name] = row
    if set(selected) != set(lock['nikki_packages']):
        raise ValueError('Incomplete Nikki bundle')
    return selected


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cache', type=Path, default=Path('.build/downloads'))
    parser.add_argument('--output', type=Path, default=Path('.build/n1-inputs'))
    parser.add_argument('--files', type=Path, default=Path('files'))
    parser.add_argument('--include-openclash', choices=('yes', 'no'), default='yes')
    parser.add_argument('--offline', action='store_true')
    args = parser.parse_args()
    lock_path = Path(__file__).with_name('inputs.lock.json')
    lock = json.loads(lock_path.read_text())
    args.cache.mkdir(parents=True, exist_ok=True)
    inputs = ['nikki_bundle', 'nikki_key', 'subs_check']
    if args.include_openclash == 'yes':
        inputs += ['openclash', 'openclash_core']
    fetched = {name: acquire(lock[name], args.cache, args.offline) for name in inputs}
    # Validate everything in an isolated directory before publishing any files.
    with tempfile.TemporaryDirectory(prefix='n1-inputs-') as tmp:
        root = Path(tmp)
        bundle = root / 'bundle'
        bundle.mkdir()
        unpack(fetched['nikki_bundle'], bundle)
        selected = verify_bundle(bundle, fetched['nikki_key'], lock)
        subs = root / 'subs'
        subs.mkdir()
        unpack(fetched['subs_check'], subs)
        if not (subs / 'subs-check').is_file():
            raise ValueError('subs-check archive lacks binary')
        if args.include_openclash == 'yes':
            control = ipk_control(fetched['openclash'])
            if control['Package'] != 'luci-app-openclash' or control['Version'] != lock['openclash']['version']:
                raise ValueError('Unexpected OpenClash package metadata')
        packages = args.output / 'packages'
        packages.mkdir(parents=True, exist_ok=True)
        for old in packages.glob('*.ipk'):
            old.unlink()
        for row in selected.values():
            install(bundle / row['Filename'], packages / row['Filename'], 0o644)
        # Export only regular files needed by offline first-boot CI tests.
        official = args.output / 'official-root'
        with tarfile.open(bundle / selected['nikki']['Filename'], 'r:*') as outer:
            member = next(m for m in outer.getmembers() if Path(m.name).name == 'data.tar.gz')
            with tarfile.open(fileobj=io.BytesIO(outer.extractfile(member).read()), mode='r:gz') as data:
                for member in data.getmembers():
                    name = member.name.removeprefix('./')
                    if member.isfile() and name.startswith(('etc/config/', 'etc/uci-defaults/')):
                        if '..' in Path(name).parts:
                            raise ValueError('Unsafe official fixture path')
                        target = official / name
                        target.parent.mkdir(parents=True, exist_ok=True)
                        target.write_bytes(data.extractfile(member).read())
        evidence = args.output / 'upstream-nikki'
        for name in ('Packages', 'Packages.gz', 'Packages.sig'):
            install(bundle / name, evidence / name, 0o644)
        install(fetched['nikki_key'], evidence / 'key-build.pub', 0o644)
        install(subs / 'subs-check', args.files / 'opt/subs-check/subs-check', 0o755)
        (args.files / 'opt/subs-check/data').mkdir(parents=True, exist_ok=True)
        core = args.files / 'etc/openclash/core/clash_meta'
        if args.include_openclash == 'yes':
            install(fetched['openclash'], packages / lock['openclash']['filename'], 0o644)
            with gzip.open(fetched['openclash_core'], 'rb') as stream:
                (root / 'clash_meta').write_bytes(stream.read())
            install(root / 'clash_meta', core, 0o755)
        elif core.exists() or core.is_symlink():
            core.unlink()
        manifest = {'schema': 1, 'lock_sha256': sha256(lock_path),
                    'include_openclash': args.include_openclash,
                    'inputs': {name: lock[name] for name in inputs},
                    'nikki_signature_verified': True, 'nikki_packages': selected,
                    'package_owned_files': {'usr/libexec/mihomo': ipk_file_hash(
                        bundle / selected['mihomo-meta']['Filename'], 'usr/libexec/mihomo')},
                    'reproducibility_gaps': lock['reproducibility_gaps'],
                    'packages': {p.name: sha256(p) for p in sorted(packages.glob('*.ipk'))},
                    'overlay': {'opt/subs-check/subs-check': sha256(args.files / 'opt/subs-check/subs-check')}}
        if args.include_openclash == 'yes':
            manifest['overlay']['etc/openclash/core/clash_meta'] = sha256(core)
        (args.output / 'inputs-manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
        print(f'Verified Nikki signature and {len(selected)} selected IPKs; OpenClash={args.include_openclash}')


if __name__ == '__main__':
    main()
