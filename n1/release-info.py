#!/usr/bin/env python3
"""Generate release documentation from actual audit artifacts, not guessed versions."""
import argparse
import hashlib
import json
from pathlib import Path


def read(path):
    return path.read_text().strip() if path.is_file() else 'not recorded'


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--audit', type=Path, default=Path('bin/n1-audit'))
    p.add_argument('--info', type=Path, default=Path(__file__).with_name('info.md'))
    p.add_argument('--skip-imagebuilder', choices=('true', 'false'), default='false')
    a = p.parse_args()
    a.audit.mkdir(parents=True, exist_ok=True)
    custom = a.skip_imagebuilder == 'false'
    after = a.audit / 'after-manifest.json'
    if custom and not after.is_file():
        raise ValueError('Customized build is missing installed-package audit')
    installed = json.loads(after.read_text())['installed'] if custom else []
    lines = ['# N1 build information', '', f'Custom ImageBuilder changes applied: {custom}',
             f'Source commit: `{read(a.audit / "source-commit.txt")}`',
             f'Docker image ID: `{read(a.audit / "docker-image-id.txt")}`', '',
             '## Selected build options', '```text', read(a.audit / 'build-options.txt'), '```', '']
    if custom:
        lines += ['## Actual installed versions', '| Package | Version |', '|---|---|']
        packages = installed[-1]['packages']
        for name in ('base-files', 'luci-base', 'nikki', 'luci-app-nikki', 'mihomo-meta',
                     'luci-app-openclash', 'lucky', 'luci-app-lucky', 'dnsmasq-full', 'odhcp6c'):
            lines.append(f'| {name} | {packages.get(name, "not installed")} |')
        lines += ['', '## Audited rootfs', '| File | SHA-256 |', '|---|---|']
        for item in installed:
            lines.append(f'| {item["rootfs"]} | `{item["sha256"]}` |')
    else:
        lines += ['## Prebuilt rootfs path',
                  'Nikki/OpenClash selection, profile and first-boot customizations were skipped.',
                  'Installed plugin versions have not been audited on this path.']
    lines += ['', '## Final image checksums', '```text', read(a.audit / 'SHA256SUMS'), '```',
              '', '## Verification scope',
              'This manifest records a build. It is not a real-device boot or network test.',
              'See inputs.lock.json reproducibility_gaps for inputs not locked before the build.', '']
    (a.audit / 'BUILD-INFO.md').write_text('\n'.join(lines))
    notes = '\n'.join(lines)
    if custom:
        notes += '\n---\n\n' + a.info.read_text()
    (a.audit / 'release-notes.md').write_text(notes)
    summaries = []
    for name in ('BUILD-INFO.md', 'release-notes.md', 'installed-packages.txt', 'inputs.lock.json'):
        path = a.audit / name
        if path.is_file():
            summaries.append(f'{hashlib.sha256(path.read_bytes()).hexdigest()}  {name}\n')
    (a.audit / 'audit-documents.sha256').write_text(''.join(summaries))


if __name__ == '__main__':
    main()
