"""Isolated UCI/init emulator. Never invokes a host UCI or init service."""
import copy
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import sys
import tempfile


def parse_uci(text):
    sections = []
    for line in text.splitlines():
        words = shlex.split(line, comments=True)
        if not words:
            continue
        if words[0] == 'config':
            sections.append({'type': words[1], 'name': words[2] if len(words) > 2 else None, 'options': {}})
        elif words[0] in ('option', 'list'):
            opts = sections[-1]['options']
            if words[0] == 'list':
                opts.setdefault(words[1], []).append(words[2])
            else:
                opts[words[1]] = words[2]
        else:
            raise ValueError('Unsupported UCI directive')
    return sections


def resolve(state, key):
    package, section, *option = key.split('.')
    sections = state[package]
    match = re.fullmatch(r'@([^\[]+)\[(-?\d+)\]', section)
    if match:
        found = [s for s in sections if s['type'] == match[1]][int(match[2])]
    else:
        found = next(s for s in sections if s['name'] == section)
    return found, option[0] if option else None


def get(state, key, default=None):
    try:
        section, option = resolve(state, key)
        return section['options'][option] if option else section['type']
    except (KeyError, IndexError, StopIteration):
        return default


def cli():
    root = Path(os.environ['FAKE_ROOT'])
    name = os.environ.get('FAKE_COMMAND', Path(sys.argv[0]).name)
    args = sys.argv[1:]
    if name == 'od':
        print(' '.join('%02x' % n for n in os.urandom(24)))
        return
    if name != 'uci':
        # Do not record logger messages or any UCI values (may contain secrets).
        if name != 'logger':
            with (root / 'services.jsonl').open('a') as stream:
                stream.write(json.dumps([name] + args) + '\n')
        return
    args = [a for a in args if a != '-q']
    command, *args = args
    state_path = root / 'state.json'
    state = json.loads(state_path.read_text())
    if command == 'commit':
        return
    if command == 'show':
        package = args[0]
        counts = {}
        for section in state.get(package, []):
            kind = section['type']
            idx = counts.get(kind, 0)
            counts[kind] = idx + 1
            key = package + '.' + (section['name'] or '@%s[%d]' % (kind, idx))
            print(key + '=' + kind)
            for option, value in section['options'].items():
                values = value if isinstance(value, list) else [value]
                print(key + '.' + option + '=' + ' '.join(shlex.quote(v) for v in values))
        return
    key, equals, value = args[0].partition('=')
    try:
        section, option = resolve(state, key)
    except (KeyError, IndexError, StopIteration):
        if command != 'set' or key.count('.') != 1 or not equals:
            raise ValueError('Missing UCI section')
        package, name = key.split('.')
        section = {'type': value, 'name': name, 'options': {}}
        state.setdefault(package, []).append(section)
        option = None
    opts = section['options']
    if command == 'get':
        result = opts[option] if option else section['type']
        print(' '.join(result) if isinstance(result, list) else result)
        return
    if command == 'set':
        if option:
            opts[option] = value
        else:
            section['type'] = value
    elif command in ('delete', 'del'):
        if option:
            del opts[option]
        else:
            state[key.split('.')[0]].remove(section)
    elif command == 'add_list':
        old = opts.get(option, [])
        opts[option] = (old if isinstance(old, list) else [old]) + [value]
    elif command == 'del_list':
        old = opts[option]
        opts[option] = [v for v in (old if isinstance(old, list) else [old]) if v != value]
    else:
        raise ValueError('Unsupported UCI operation')
    state_path.write_text(json.dumps(state))


class Sandbox:
    def __init__(self, official):
        self.tmp = tempfile.TemporaryDirectory(prefix='n1-firstboot-')
        self.root = Path(self.tmp.name)
        self.bin = self.root / 'bin'
        self.bin.mkdir()
        for directory in ('etc/config', 'etc/init.d', 'etc/uci-defaults', 'etc/nikki/scripts', 'dev'):
            (self.root / directory).mkdir(parents=True, exist_ok=True)
        self.original = parse_uci(official.read_text())
        state = {'nikki': copy.deepcopy(self.original)}
        fixtures = {
            'network': "config interface lan\n option ip6addr '2001:db8:1234::254/64'\n option ip6gw '2001:db8:1234::1'\n",
            'dhcp': "config dhcp lan\nconfig dnsmasq\n list server '2001:db8::53'\n",
            'firewall': "config zone\n option name 'lan'\nconfig zone docker\n option name 'docker'\nconfig forwarding\n option src 'docker'\n option dest 'lan'\nconfig forwarding\n option src 'lan'\n option dest 'wan'\n",
            'frpc': "config conf common\n option enabled '1'\n option token 'SYNTHETIC_TEST_ONLY'\nconfig proxy n1_web\n",
            'mosdns': 'config mosdns config\n', 'bandix': 'config bandix general\n',
            'ttyd': "config ttyd\n option interface 'lan'\n", 'dropbear': 'config dropbear\n',
        }
        state.update({name: parse_uci(text) for name, text in fixtures.items()})
        self.save(state)
        (self.root / 'state.json').chmod(0o600)
        shutil.copyfile(official, self.root / 'etc/config/nikki')
        (self.root / 'etc/nikki/scripts/include.sh').write_text(':\n')
        (self.root / 'dev/null').touch()
        (self.root / 'dev/urandom').touch()  # fake od provides fresh bytes
        helper = Path(__file__).resolve()
        launcher = '#!%s\nimport os,sys,runpy\nos.environ["FAKE_COMMAND"]=os.path.basename(sys.argv[0])\nrunpy.run_path(%r, run_name="__main__")\n' % (sys.executable, str(helper))
        for name in ('uci', 'logger', 'od'):
            path = self.bin / name
            path.write_text(launcher)
            path.chmod(0o755)
        # Strict PATH allowlist: no actual uci/init/network/download commands.
        for name in ('tr', 'chmod', 'date', 'grep', 'cut', 'sort', 'awk'):
            target = shutil.which(name)
            if not target:
                raise RuntimeError('Required harmless utility missing')
            (self.bin / name).symlink_to(target)
        for name in ('nikki', 'openclash', 'mosdns', 'passwall', 'passwall2', 'lucky', 'frpc'):
            path = self.root / 'etc/init.d' / name
            path.write_text(launcher)
            path.chmod(0o755)

    def state(self):
        return json.loads((self.root / 'state.json').read_text())

    def save(self, state):
        (self.root / 'state.json').write_text(json.dumps(state))

    def events(self):
        path = self.root / 'services.jsonl'
        return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []

    def run(self, source, staged=False, boot=False):
        text = source.read_text()
        # Only a COPY is rewritten; originals and host /etc are never changed.
        text = text.replace('/etc/', str(self.root / 'etc') + '/')
        text = text.replace('/dev/urandom', str(self.root / 'dev/urandom'))
        text = text.replace('/dev/null', str(self.root / 'dev/null'))
        inspected = text.split('\n', 1)[-1].replace(str(self.root), 'SANDBOX')
        if re.search(r'(?<![\w.])/(?:etc|usr|bin|sbin|var|root|home|proc|sys|run|dev)(?:/|\b)', inspected):
            raise RuntimeError('Unsafe unmapped absolute path; script was NOT executed')
        path = self.root / 'etc/uci-defaults' / source.name
        path.write_text(text)
        path.chmod(0o755)
        env = {'PATH': str(self.bin), 'HOME': str(self.root), 'LC_ALL': 'C',
               'FAKE_ROOT': str(self.root), 'IPKG_INSTROOT': str(self.root / 'staging') if staged else ''}
        result = subprocess.run(['/bin/sh', str(path)], env=env, cwd=self.root,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=30)
        if boot and result.returncode == 0:
            path.unlink()  # OpenWrt removes only successful uci-defaults scripts.
        return result, path

    def close(self):
        self.tmp.cleanup()


if __name__ == '__main__':
    try:
        cli()
    except Exception:
        # Deliberately omit exception text, arguments and state (secret-safe).
        sys.exit(1)
