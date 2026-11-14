#!/usr/bin/env python3
"""Offline build-input checks. Run with N1_TEST_CACHE containing inputs.lock files.
These are staging/synthetic-rootfs tests, not a complete ImageBuilder build.
Requires cryptography, PyYAML, ripgrep and the five locked public downloads.
"""
import importlib.util
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import tempfile

N1 = Path(__file__).resolve().parents[1]
CACHE = Path(os.environ.get('N1_TEST_CACHE', '/tmp'))
spec = importlib.util.spec_from_file_location('inputs', N1 / 'prepare-inputs.py')
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)
lock = json.loads((N1 / 'inputs.lock.json').read_text())
checks = []


def reject(label, call):
    try:
        call()
    except Exception:
        checks.append(label)
    else:
        raise AssertionError(label + ': accepted invalid input')


def run(script, *args, cwd=None, env=None, ok=True):
    p = subprocess.run([sys.executable, '-B', str(N1 / script), *map(str, args)],
                       cwd=cwd, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if (p.returncode == 0) != ok:
        raise AssertionError(script + ': unexpected result (output suppressed)')


def main():
    with tempfile.TemporaryDirectory(prefix='n1-build-test-') as tmp:
        root = Path(tmp)
        bundle = root / 'bundle'
        bundle.mkdir()
        m.unpack(CACHE / lock['nikki_bundle']['filename'], bundle)
        key = CACHE / lock['nikki_key']['filename']
        reject('wrong archive checksum rejected', lambda: m.checked(key, '0' * 64))
        m.verify_bundle(bundle, key, lock)
        checks.append('official signature and IPK hashes')
        index = bundle / 'Packages'
        original = index.read_bytes()
        index.write_bytes(original + b'\n')
        reject('tampered signature rejected', lambda: m.verify_bundle(bundle, key, lock))
        index.write_bytes(original)
        ipk = bundle / 'mihomo-meta_1.19.32_aarch64_generic.ipk'
        with ipk.open('r+b') as stream:
            stream.write(b'bad')
        reject('tampered IPK rejected', lambda: m.verify_bundle(bundle, key, lock))
        m.unpack(CACHE / lock['nikki_bundle']['filename'], bundle)
        attack = root / 'attack.tar.gz'
        with tarfile.open(attack, 'w:gz') as tar:
            member = tarfile.TarInfo('../escaped'); member.size = 1
            tar.addfile(member, io.BytesIO(b'x'))
        reject('archive traversal rejected', lambda: m.unpack(attack, root / 'extract'))
        for mode in ('yes', 'no'):
            builder = root / mode
            builder.mkdir()
            run('prepare-inputs.py', '--offline', '--cache', CACHE, '--output', builder / 'n1-inputs',
                '--files', builder / 'files', '--include-openclash', mode)
            (builder / 'repositories.conf').write_text('src/gz fixture https://example.invalid/packages\nsrc imagebuilder file:packages\n')
            (builder / 'dl').mkdir()
            shutil.copyfile(bundle / 'Packages', builder / 'dl/fixture')
            (builder / 'packages').mkdir()
            (builder / 'packages/nikki_old_all.ipk').write_bytes(b'old')
            env = dict(os.environ, INCLUDE_OPENCLASH=mode, PYTHONDONTWRITEBYTECODE='1')
            run('configure-builder.py', cwd=builder, env=env)
            assert len(list((builder / 'packages').glob('*.ipk'))) == (5 if mode == 'yes' else 4)
            assert not (builder / 'files/usr/bin/mihomo').exists()
            run('build-audit.py', 'before', cwd=builder, env=env)
            # Match ImageBuilder's _call_image: clean rootfs, reload indexes,
            # then install packages. The frozen target must recreate rootfs/tmp.
            (builder / 'Makefile').write_text(
                'TOPDIR := .\nTARGET_DIR := rootfs\nTMP_DIR := build-tmp\n'
                '.PHONY: image package_install\nimage:\n'
                '\trm -rf "$(TARGET_DIR)" "$(TMP_DIR)"\n'
                '\tmkdir -p "$(TARGET_DIR)"\n'
                '\t$(MAKE) package_reload\n\t$(MAKE) package_install\n'
                'package_reload:\n\t@mkdir -p "$(TARGET_DIR)/tmp"\n'
                'package_install:\n\t@test -d "$(TARGET_DIR)/tmp"\n'
                '\t@touch "$(TARGET_DIR)/tmp/opkg.lock"\n')
            run('freeze-feeds.py', cwd=builder, env=env)
            assert (builder / 'Makefile').read_text().count('\npackage_reload:\n') == 1
            make = subprocess.run(['make', 'image'], cwd=builder, env=env,
                                  stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            assert make.returncode == 0, 'Frozen reload lost rootfs tmp initialization'
            assert (builder / 'rootfs/tmp/opkg.lock').is_file()
            assert (builder / 'build-tmp').is_dir()
            checks.append('clean-rootfs/reload/opkg-lock: OpenClash=' + mode)
            checks.append('prepare/configure/freeze: OpenClash=' + mode)
            if mode == 'yes':
                staged = builder / 'files/etc/openclash/core/clash_meta'
                assert staged.is_file() and not staged.is_symlink()
                core = m.ipk_file_hash(bundle / 'mihomo-meta_1.19.32_aarch64_generic.ipk', 'usr/libexec/mihomo')
                assert core
                # True package payloads placed inside a synthetic rootfs archive.
                with tarfile.open(bundle / 'mihomo-meta_1.19.32_aarch64_generic.ipk') as tar:
                    inner = tar.extractfile(next(x for x in tar if x.name.endswith('data.tar.gz'))).read()
                with tarfile.open(fileobj=io.BytesIO(inner)) as tar:
                    payload = tar.extractfile(next(x for x in tar if x.name == './usr/libexec/mihomo')).read()
                versions = dict(lock['nikki_packages'], **{'luci-app-openclash': lock['openclash']['version']})
                data = {'usr/libexec/mihomo': payload, 'etc/openclash/core/clash_meta': staged.read_bytes(),
                        'usr/lib/opkg/status': ''.join(f'Package: {n}\nVersion: {v}\nStatus: install user installed\n\n'
                                                       for n,v in versions.items()).encode()}
                target = builder / 'bin/targets/armsr/armv8/test-rootfs.tar.gz'
                target.parent.mkdir(parents=True)
                def archive():
                    with tarfile.open(target, 'w:gz') as tar:
                        for name, content in data.items():
                            member = tarfile.TarInfo('./' + name); member.size = len(content)
                            tar.addfile(member, io.BytesIO(content))
                archive()
                run('build-audit.py', 'after', cwd=builder, env=env)
                checks.append('synthetic rootfs versions and independent real core payloads')
                saved = (builder / 'dl/fixture').read_bytes()
                (builder / 'dl/fixture').write_bytes(saved + b'\n')
                run('build-audit.py', 'after', cwd=builder, env=env, ok=False)
                (builder / 'dl/fixture').write_bytes(saved)
                checks.append('changed frozen index rejected')
                data['usr/libexec/mihomo'] = b'wrong-core'
                archive()
                run('build-audit.py', 'after', cwd=builder, env=env, ok=False)
                checks.append('overwritten Nikki core rejected')
        images = root / 'images'; images.mkdir()
        (images / 'fixture.img.gz').write_bytes(b'synthetic-image')
        run('build-audit.py', 'final', '--root', images, '--output', root / 'yes/bin/n1-audit')
        run('release-info.py', '--audit', root / 'yes/bin/n1-audit', '--skip-imagebuilder', 'false')
        assert '1.19.32' in (root / 'yes/bin/n1-audit/BUILD-INFO.md').read_text()
        checks.append('image checksums and actual-version release report')
    print(f'Build input checks: {len(checks)} passed')
    for check in checks: print('PASS ' + check)


if __name__ == '__main__':
    main()
