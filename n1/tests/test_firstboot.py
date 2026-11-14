#!/usr/bin/env python3
"""Run: python3 -B -m unittest discover -s n1/tests -p 'test_firstboot.py'
Or: python3 -B n1/tests/test_firstboot.py (secret-safe summary runner).
Needs PyYAML and extracted official Nikki v1.26.2 defaults. Override the latter
with NIKKI_OFFICIAL_ROOT; no network, router, or real init service is contacted.
"""
import copy
import ipaddress
import os
from pathlib import Path
import re
import stat
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from firstboot_helper import Sandbox, get, parse_uci, resolve
import yaml

ROOT = Path(__file__).resolve().parents[1]
OFFICIAL = Path(os.environ.get('NIKKI_OFFICIAL_ROOT', '/tmp/nikki-official-root'))
NIKKI = ROOT / 'zzz-n1-nikki.sh'
NETWORK = ROOT / '99-n1-bypass-router.sh'


class UniqueLoader(yaml.SafeLoader):
    def construct_mapping(self, node, deep=False):
        # Reject explicit duplicate keys before merge flattening. YAML merge
        # defaults may legally be overridden by an explicit key.
        seen = set()
        for key_node, _ in node.value:
            if key_node.tag == 'tag:yaml.org,2002:merge':
                key = '<<'
            else:
                key = self.construct_object(key_node, deep=deep)
            if key in seen:
                raise ValueError('Duplicate YAML mapping key')
            seen.add(key)
        self.flatten_mapping(node)
        return super().construct_mapping(node, deep=deep)


def template():
    try:
        return yaml.load((ROOT / 'nikki-dual.yaml').read_text(), Loader=UniqueLoader)
    except Exception:
        raise AssertionError('YAML invalid or contains duplicate keys; contents suppressed') from None


def validate_graph(document):
    groups = document['proxy-groups']
    names = [g['name'] for g in groups]
    if len(set(names)) != len(names):
        raise ValueError('Duplicate proxy-group name')
    graph = {g['name']: g.get('proxies', []) for g in groups}
    known = set(graph) | {'DIRECT', 'REJECT', 'REJECT-DROP', 'PASS', 'COMPATIBLE'}
    known.update(p['name'] for p in document.get('proxies', []))
    providers = document.get('proxy-providers', {})
    visiting, visited = set(), set()

    def visit(name):
        if name in visiting:
            raise ValueError('Proxy-group cycle')
        if name in visited:
            return
        visiting.add(name)
        for target in graph[name]:
            if target not in known:
                raise ValueError('Unknown group proxy target')
            if target in graph:
                visit(target)
        visiting.remove(name)
        visited.add(name)

    for group in groups:
        if any(p not in providers for p in group.get('use', [])):
            raise ValueError('Unknown proxy provider')
        visit(group['name'])
    for rule in document['rules']:
        fields = [x.strip() for x in rule.split(',')]
        while fields and fields[-1] in ('no-resolve', 'src'):
            fields.pop()
        if len(fields) < 2 or fields[-1] not in known:
            raise ValueError('Unknown rule target')
        if fields[0] == 'RULE-SET' and fields[1] not in document.get('rule-providers', {}):
            raise ValueError('Unknown rule provider')


class FirstBootTests(unittest.TestCase):
    def setUp(self):
        config = OFFICIAL / 'etc/config/nikki'
        self.assertTrue(config.is_file(), 'Official v1.26.2 defaults missing; set NIKKI_OFFICIAL_ROOT')
        self.box = Sandbox(config)
        self.addCleanup(self.box.close)

    def run_ok(self, path=NIKKI):
        result, _ = self.box.run(path)
        self.assertTrue(result.returncode == 0, 'Isolated firstboot returned nonzero; output suppressed')
        state = self.box.state()
        for key in ('nikki.mixin.api_secret', 'nikki.@authentication[0].password'):
            secret = get(state, key)
            if secret:
                self.assertTrue(secret.encode() not in result.stdout + result.stderr, 'Generated secret leaked to script output')
        return state

    def test_vendor_order_and_executable_permissions(self):
        vendor = OFFICIAL / 'etc/uci-defaults/99_init_nikki'
        self.assertTrue(vendor.is_file(), 'Official vendor init missing')
        self.assertTrue(NIKKI.name > vendor.name, 'Nikki override must sort after vendor init')
        for path in (NIKKI, NETWORK):
            self.assertTrue(stat.S_IMODE(path.stat().st_mode) == 0o755, 'Firstboot script mode must be 0755')
        self.run_ok(vendor)
        self.assertTrue(get(self.box.state(), 'nikki.config.init') is None, 'Vendor init did not run in sandbox')
        state = self.run_ok()
        self.assertTrue(get(state, 'nikki.config.profile') == 'file:nikki-dual.yaml', 'Vendor profile override missing')

    def test_nikki_profile_and_dual_stack_tun_defaults(self):
        state = self.run_ok()
        expected = {'config.profile': 'file:nikki-dual.yaml', 'config.enabled': '0',
                    'config.scheduled_restart': '0', 'proxy.enabled': '1',
                    'proxy.ipv4_dns_hijack': '1', 'proxy.ipv6_dns_hijack': '1',
                    'proxy.ipv4_proxy': '1', 'proxy.ipv6_proxy': '1',
                    'proxy.router_proxy': '1', 'proxy.lan_proxy': '1',
                    'proxy.tcp_mode': 'redirect', 'proxy.udp_mode': 'tun',
                    'mixin.tun_enabled': '1', 'mixin.ipv6': '1', 'mixin.dns_ipv6': '1',
                    'mixin.authentication': '1', 'config.n1_initialized': '1'}
        for key, value in expected.items():
            self.assertTrue(get(state, 'nikki.' + key) == value, 'Incorrect Nikki default: ' + key)

    def test_independent_random_credentials_and_lan_api(self):
        state = self.run_ok()
        api = get(state, 'nikki.mixin.api_secret', '')
        auth = get(state, 'nikki.@authentication[0].password', '')
        self.assertTrue(bool(re.fullmatch('[0-9a-f]{48}', api)), 'API secret must be 48 lowercase hex characters')
        self.assertTrue(bool(re.fullmatch('[0-9a-f]{48}', auth)), 'Proxy auth must be 48 lowercase hex characters')
        self.assertTrue(api != auth, 'API and proxy auth must be independent')
        self.assertTrue(get(state, 'nikki.mixin.api_listen') == '192.168.2.254:9090', 'API must bind only LAN address')
        self.assertTrue(stat.S_IMODE((self.box.root / 'etc/config/nikki').stat().st_mode) == 0o600, 'Credential config mode must be 0600')
        other = Sandbox(OFFICIAL / 'etc/config/nikki')
        self.addCleanup(other.close)
        result, _ = other.run(NIKKI)
        self.assertTrue(result.returncode == 0, 'Second isolated installation failed')
        self.assertTrue(api != get(other.state(), 'nikki.mixin.api_secret'), 'Different installations reused API credentials')
        self.assertTrue(auth != get(other.state(), 'nikki.@authentication[0].password'), 'Different installations reused proxy credentials')

    def test_preserve_official_acl_and_lucky_once(self):
        state = self.run_ok()
        before = [s for s in self.box.original if s['type'] == 'router_access_control']
        after = [s for s in state['nikki'] if s['type'] == 'router_access_control']
        self.assertTrue(len(before) == len(after), 'Do not add a standalone cgroup-only ACL')
        for key in ('user', 'group', 'enabled', 'dns', 'proxy'):
            self.assertTrue(after[0]['options'].get(key) == before[0]['options'].get(key), 'Official ACL field changed: ' + key)
        old_groups = before[0]['options']['cgroup']
        new_groups = after[0]['options'].get('cgroup', [])
        self.assertTrue(new_groups.count('services/lucky') == 1, 'Lucky cgroup must occur exactly once')
        self.assertTrue(all(c in new_groups for c in old_groups), 'Official cgroup exemptions lost')
        for section in after:
            opts = section['options']
            self.assertTrue(not opts.get('cgroup') or bool(opts.get('user') and opts.get('group')), 'Unsafe cgroup-only ACL')

    def test_second_run_preserves_user_enable_and_secrets(self):
        state = self.run_ok()
        section, option = resolve(state, 'nikki.config.enabled')
        section['options'][option] = '1'
        self.box.save(state)
        before_events = self.box.events()
        self.run_ok()
        self.assertTrue(self.box.state() == state, 'Second run changed user enable state, credentials, or configuration')
        self.assertTrue(self.box.events() == before_events, 'Second run unexpectedly touched services')

    def test_conflicting_services_disabled_lucky_untouched(self):
        self.run_ok()
        events = self.box.events()
        for name in ('openclash', 'mosdns', 'passwall', 'passwall2'):
            self.assertTrue([name, 'stop'] in events and [name, 'disable'] in events, 'Conflicting service not stopped and disabled: ' + name)
        self.assertTrue(not any(e[0] == 'lucky' for e in events), 'Lucky must not be stopped or disabled')
        self.assertTrue(['nikki', 'enable'] in events, 'Nikki init must remain enabled for later user activation')
        self.assertTrue(['nikki', 'start'] not in events and ['nikki', 'restart'] not in events, 'Unconfigured Nikki must not start')

    def test_staging_nonzero_retains_nikki_firstboot(self):
        before = self.box.state()
        result, path = self.box.run(NIKKI, staged=True, boot=True)
        self.assertTrue(result.returncode != 0, 'IPKG_INSTROOT staging must return nonzero')
        self.assertTrue(path.exists(), 'Staging must retain pending firstboot script')
        self.assertTrue(self.box.state() == before and not self.box.events(), 'Staging must have no UCI or init side effects')

    def test_network_dynamic_ipv6_and_explicit_bootstrap_dns(self):
        state = self.run_ok(NETWORK)
        expected = {'network.lan.ipaddr': '192.168.2.254', 'network.lan.gateway': '192.168.2.1',
                    'network.lan.dns': '192.168.2.1', 'network.lan6.proto': 'dhcpv6',
                    'network.lan6.device': '@lan', 'network.lan6.peerdns': '0',
                    'network.lan6.reqaddress': 'try', 'network.lan6.reqprefix': 'auto',
                    'network.lan6.disabled': '0', 'dhcp.lan.ignore': '1',
                    'dhcp.lan.dynamicdhcp': '0', 'dhcp.lan.ra': 'disabled',
                    'dhcp.lan.dhcpv6': 'disabled', 'dhcp.lan.ndp': 'disabled',
                    'dhcp.@dnsmasq[0].noresolv': '1'}
        for key, value in expected.items():
            self.assertTrue(get(state, key) == value, 'Incorrect network default: ' + key)
        self.assertTrue(get(state, 'dhcp.@dnsmasq[0].server') == ['192.168.2.1'], 'dnsmasq must explicitly use only main-router IPv4 DNS')
        for section in ('lan', 'lan6'):
            for option in ('ip6addr', 'ip6gw', 'ip6prefix'):
                self.assertTrue(get(state, 'network.' + section + '.' + option) in (None, '', []), 'Static IPv6 address or prefix remains')
        # Check active source too, not comments or unrelated template fake-IP ranges.
        for line in NETWORK.read_text().splitlines():
            if line.lstrip().startswith('#'):
                continue
            for token in re.findall(r'[0-9a-fA-F:]{4,}(?:/\d+)?', line):
                try:
                    address = ipaddress.ip_interface(token).ip
                except ValueError:
                    continue
                self.assertTrue(not isinstance(address, ipaddress.IPv6Address) or address.is_link_local or address.is_loopback or address.is_unspecified, 'Network script embeds a static IPv6 address')

    def test_frpc_no_credentials_endpoint_and_disabled(self):
        sections = parse_uci((ROOT / 'frpc.config').read_text())
        forbidden = ('token', 'password', 'secret', 'server_addr', 'server_port', 'serveraddr', 'serverport')
        for section in sections:
            for key, value in section['options'].items():
                self.assertTrue(not any(word in key.lower() for word in forbidden), 'Public FRPC template has endpoint/credential field')
                if key == 'enabled':
                    self.assertTrue(value == '0', 'Public FRPC template must remain disabled')
        state = self.run_ok(NETWORK)
        self.assertTrue(get(state, 'frpc.common') is None and get(state, 'frpc.n1_web') is None, 'Legacy FRPC credentials/endpoints not removed')
        events = self.box.events()
        self.assertTrue(['frpc', 'disable'] in events and ['frpc', 'stop'] in events, 'FRPC must stay stopped and disabled')
        self.assertTrue(not any(e[0] == 'lucky' for e in events), 'Network firstboot touched Lucky')

    def test_network_staging_retained_without_side_effects(self):
        before = self.box.state()
        result, path = self.box.run(NETWORK, staged=True, boot=True)
        self.assertTrue(result.returncode != 0, 'Network IPKG_INSTROOT staging must return nonzero and remain pending')
        self.assertTrue(path.exists(), 'Network firstboot was removed during staging')
        self.assertTrue(self.box.state() == before and not self.box.events(), 'Network staging changed UCI or services')

    def test_sandbox_refuses_unmapped_absolute_commands(self):
        source = self.box.root / 'unsafe.sh'
        source.write_text('#!/bin/sh\n/usr/bin/true\n')
        with self.assertRaises(RuntimeError):
            self.box.run(source)


class TemplateTests(unittest.TestCase):
    def test_yaml_unique_keys_and_validator_negative_controls(self):
        template()
        for text in ('a: 1\na: 2\n', 'x:\n  a: 1\n  a: 2\n'):
            with self.assertRaises(ValueError):
                yaml.load(text, Loader=UniqueLoader)
        # A merge override is valid YAML, not a duplicate explicit key.
        value = yaml.load('base: &b {a: 1}\nx: {<<: *b, a: 2}\n', Loader=UniqueLoader)
        self.assertTrue(value['x']['a'] == 2, 'YAML merge override handling broken')

    def test_exact_group_and_rule_counts_and_fallbacks(self):
        document = template()
        groups, rules = document['proxy-groups'], document['rules']
        expected = {'手动节点', '默认代理', 'GLOBAL', 'AI', 'YouTube', 'Emby', 'Linux Do', '自动选择', '直连',
                    '香港', '台湾', '日本', '美国', '新加坡', '其他地区', '漏网之鱼'}
        self.assertTrue(len(groups) == 16 and {g['name'] for g in groups} == expected, 'Expected exactly the 16 approved groups')
        self.assertTrue(len(rules) == 40, 'Expected exactly 40 routing rules')
        self.assertTrue(rules[-1] == 'MATCH,漏网之鱼', 'Final catch-all must target 漏网之鱼')
        by_name = {g['name']: g for g in groups}
        self.assertTrue('其他地区' in by_name['漏网之鱼'].get('proxies', []), 'Catch-all lost other-regions option')
        self.assertTrue(set(by_name['其他地区'].get('use', [])) == {'p1', 'p2'}, 'Other-regions must use both subscriptions')
        self.assertTrue(bool(by_name['其他地区'].get('filter') or by_name['其他地区'].get('exclude-filter')), 'Other-regions selector lost region filter')

    def test_groups_acyclic_targets_and_provider_references(self):
        try:
            validate_graph(template())
        except ValueError:
            self.fail('Invalid group graph, rule target, or provider reference; values suppressed')
        base = {'proxy-groups': [{'name': 'A', 'proxies': ['DIRECT']}], 'rules': ['MATCH,A']}
        validate_graph(base)
        for invalid in (
            {'proxy-groups': [{'name': 'A', 'proxies': ['A']}], 'rules': ['MATCH,A']},
            {'proxy-groups': [{'name': 'A', 'proxies': ['B']}, {'name': 'B', 'proxies': ['A']}], 'rules': ['MATCH,A']},
            {'proxy-groups': [{'name': 'A', 'proxies': ['DIRECT']}], 'rules': ['MATCH,missing']},
            {'proxy-groups': [{'name': 'A', 'proxies': ['DIRECT']}], 'rules': ['RULE-SET,missing,A']},
        ):
            with self.assertRaises(ValueError):
                validate_graph(invalid)

    def test_two_placeholders_no_embedded_subscription_credentials(self):
        document = template()
        providers = document['proxy-providers']
        self.assertTrue(set(providers) == {'p1', 'p2'}, 'Expected two subscription providers')
        for name, provider in providers.items():
            expected = 'https://[NIKKI_SUBSCRIPTION_' + name.upper() + ']'
            self.assertTrue(provider.get('url') == expected, 'Subscription must use a credential-free placeholder')
            self.assertTrue(provider.get('type') == 'http', 'Provider type must remain http')
            self.assertTrue(not provider.get('header'), 'Public subscription provider must not embed authorization headers')
        self.assertTrue(providers['p1'].get('path') != providers['p2'].get('path'), 'Provider caches must remain independent')
        self.assertTrue(not document.get('secret') and not document.get('authentication'), 'Public template must not embed API/proxy credentials')
        self.assertTrue(not document.get('proxies'), 'Public template must not embed credential-bearing nodes')
        def inspect(value):
            if isinstance(value, dict):
                for key, child in value.items():
                    if str(key).lower() in ('password', 'token', 'api-key', 'authorization', 'uuid', 'private-key'):
                        self.assertTrue(child in (None, '', []), 'Public YAML contains a credential field')
                    inspect(child)
            elif isinstance(value, list):
                for child in value:
                    inspect(child)
        inspect(document)


class SummaryResult(unittest.TestResult):
    """Never render exception messages, frames, fixture values or captured output."""
    def print_summary(self):
        for test, _ in self.failures:
            print('FAIL ' + test.id())
        for test, _ in self.errors:
            print('ERROR ' + test.id() + ' (details suppressed)')
        for test, _ in self.skipped:
            print('SKIP ' + test.id())
        print('Tests: %d; failures: %d; errors: %d; skipped: %d' %
              (self.testsRun, len(self.failures), len(self.errors), len(self.skipped)))


if __name__ == '__main__':
    suite = unittest.defaultTestLoader.loadTestsFromModule(sys.modules[__name__])
    result = SummaryResult()
    suite.run(result)
    result.print_summary()
    sys.exit(not result.wasSuccessful())
