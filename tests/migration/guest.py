"""Run `sudo unshare -m python3 guest.py` in a fresh disposable systemd VM only.

Pass QEMU `-smbios type=1,serial=sailry-migration-fixture`, restrict guest egress,
and copy prepare.sh's output into the VM. Destroy the VM after the run.
"""

import hashlib
import http.server
import json
import os
from pathlib import Path
import platform
import pwd
import ssl
import stat
import subprocess
import tempfile
import threading
import unittest

FIXTURE = Path(__file__).resolve().parent
BIN = Path('/usr/local/bin/sailry-relay')
CONF = Path('/etc/sailry-relay/relay.toml')
UNIT = Path('/etc/systemd/system/sailry-relay.service')
BOOT = UNIT.parent / 'multi-user.target.wants' / UNIT.name
DATA = Path('/var/lib/sailry-migration-fixture')
KEY = DATA / 'link.key'
PREVIOUS = BIN.with_suffix('.previous')
ARCH = {'aarch64': 'arm64', 'x86_64': 'amd64'}.get(platform.machine())
HARNESS, RELAY = 'sailry-harness', 'sailry-relay'
LATE_TAG, RELAY_TAG = 'v0.2.30', 'v0.2.9'


def run(*args, **kwargs):
    result = subprocess.run(args, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            timeout=90, **kwargs)
    if result.returncode:
        raise RuntimeError(f'{args!r} exited {result.returncode}: {result.stdout.strip()}')
    return result.stdout.strip()


def digest(path):
    with path.open('rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()


def metadata(path):
    s = path.lstat()
    return s.st_uid, s.st_gid, stat.S_IMODE(s.st_mode)


class Release(http.server.BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_GET(self):
        key = self.headers['Host'], self.path
        self.server.requests.append(key)
        body = self.server.assets.get(key)
        if body is None:
            self.send_error(404)
            return
        self.send_response(200)
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)


class Migration(unittest.TestCase):
    def publish(self, repo, tag, package, target=ARCH, corrupt=False):
        name = f'sailry-relay-linux-{ARCH}.tar.gz'
        sums = f'SHA256SUMS-relay-linux-{ARCH}'
        directory = FIXTURE / package / f'linux-{target}'
        archive = (directory / f'sailry-relay-linux-{target}.tar.gz').read_bytes()
        if corrupt:
            checksum = ('0' * 64 + '  ' + name + '\n').encode()
        elif target != ARCH:
            # A valid digest for a real binary of the wrong architecture.
            checksum = (hashlib.sha256(archive).hexdigest() + '  ' + name + '\n').encode()
        else:
            checksum = (directory / sums).read_bytes()
        latest = ('api.github.com', f'/repos/sailry/{repo}/releases/latest')
        download = f'/sailry/{repo}/releases/download/{tag}/'
        checks = ('github.com', download + sums)
        asset = ('github.com', download + name)
        self.server.assets = {
            latest: json.dumps({'tag_name': tag, 'assets': [{'name': n} for n in (name, sums)]}).encode(),
            checks: checksum, asset: archive,
        }
        self.server.requests.clear()
        return [latest, checks, asset]

    def pid(self):
        pid = int(run('systemctl', 'show', '--value', '-p', 'MainPID', UNIT.name))
        self.assertGreater(pid, 1)
        return pid

    def state(self):
        return (digest(CONF), digest(UNIT), digest(KEY), os.readlink(BOOT),
                [metadata(p) for p in (DATA, KEY, CONF, UNIT, BOOT, BIN)],
                run('runuser', '-u', 'sailry-relay', '--', BIN, 'id', '--data-dir', DATA),
                run('systemctl', 'is-active', UNIT.name), run('systemctl', 'is-enabled', UNIT.name))

    def unchanged_update(self, expectation, requests, fails=True):
        before = (self.state(), digest(BIN), self.pid(), digest(PREVIOUS) if PREVIOUS.exists() else None)
        result = subprocess.run([BIN, 'daemon', 'update'], capture_output=True, text=True, timeout=90)
        self.assertEqual(result.returncode != 0, fails, result.stdout + result.stderr)
        self.assertIn(expectation, result.stdout + result.stderr)
        self.assertEqual(self.server.requests, requests)
        after = (self.state(), digest(BIN), self.pid(), digest(PREVIOUS) if PREVIOUS.exists() else None)
        self.assertEqual(before, after)
        print(f'Preserved binary, backup, live PID and state: {expectation}', flush=True)

    def upgrade(self, requests, version):
        previous, pid = digest(BIN), self.pid()
        message = run(BIN, 'daemon', 'update')
        self.assertIn(f'service is online with PeerID {self.peer}', message)
        self.assertEqual(self.server.requests, requests)
        self.assertEqual(run(BIN, '--version'), f'Sailry Relay {version}')
        self.assertNotEqual(digest(BIN), previous)
        self.assertEqual(digest(PREVIOUS), previous)
        self.assertNotEqual(self.pid(), pid)
        self.assertEqual(digest(Path(f'/proc/{self.pid()}/exe')), digest(BIN))
        self.assertEqual(self.state(), self.initial)
        print(f'{requests[0][1]} -> installed {version}; same live PeerID, config, unit and owners', flush=True)

    def test_migration(self):
        self.assertEqual(os.geteuid(), 0, 'requires root in a disposable VM')
        self.assertIsNotNone(ARCH)
        self.assertEqual(Path('/sys/class/dmi/id/product_serial').read_text().strip(), 'sailry-migration-fixture')
        self.assertEqual(Path('/proc/1/comm').read_text().strip(), 'systemd')
        self.assertNotEqual(os.readlink('/proc/self/ns/mnt'), os.readlink('/proc/1/ns/mnt'), 'run via unshare -m')
        for p in (BIN, PREVIOUS, CONF.parent, UNIT, BOOT, DATA):
            self.assertFalse(os.path.lexists(p), f'not a clean guest: {p}')
        for name in ('HTTPS_PROXY', 'HTTP_PROXY', 'ALL_PROXY'):
            os.environ.pop(name, None)
            os.environ.pop(name.lower(), None)
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        work = Path(tmp.name)
        hosts = work / 'hosts'
        hosts.write_text('127.0.0.1 localhost api.github.com github.com\n::1 localhost\n')
        run('mount', '--make-rprivate', '/')
        run('mount', '--bind', hosts, '/etc/hosts')
        self.addCleanup(run, 'umount', '/etc/hosts')
        cert, key = work / 'cert.pem', work / 'key.pem'
        run('openssl', 'req', '-x509', '-newkey', 'rsa:2048', '-nodes', '-days', '1',
            '-subj', '/CN=api.github.com', '-addext', 'subjectAltName=DNS:api.github.com,DNS:github.com',
            '-keyout', key, '-out', cert)
        os.environ['SSL_CERT_FILE'] = str(cert)
        self.server = http.server.HTTPServer(('127.0.0.1', 443), Release)
        self.server.requests = []
        self.server.assets = {}
        tls = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        tls.load_cert_chain(cert, key)
        self.server.socket = tls.wrap_socket(self.server.socket, server_side=True)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)

        old = FIXTURE / 'v0.2.7'
        self.assertEqual(run(old, '--version'), 'Sailry Relay 0.2.7')
        config = work / 'source.toml'
        config.write_text(f'# operator configuration\nmode="public"\ndata_dir="{DATA}"\nlisten_ip="127.0.0.1"\nport=18401\n')
        run(old, 'daemon', 'install', '--config', config)
        self.peer = run('runuser', '-u', 'sailry-relay', '--', BIN, 'id', '--data-dir', DATA)
        self.assertEqual(run(BIN, '--version'), 'Sailry Relay 0.2.7')
        self.assertEqual(digest(BIN), digest(old))
        self.assertEqual(CONF.read_bytes(), config.read_bytes())
        self.initial = self.state()
        acct = pwd.getpwnam('sailry-relay')
        for p, mode in ((DATA, 0o700), (KEY, 0o600)):
            self.assertEqual(metadata(p), (acct.pw_uid, acct.pw_gid, mode))
        for p, mode in ((BIN, 0o755), (CONF, 0o644), (UNIT, 0o644)):
            self.assertEqual(metadata(p), (0, 0, mode))
        self.assertEqual(metadata(BOOT)[0], 0)
        self.assertEqual(BOOT.resolve(strict=True), UNIT)
        self.assertEqual(self.initial[-2:], ('active', 'enabled'))
        self.assertEqual(Path(f'/proc/{self.pid()}').stat().st_uid, acct.pw_uid)

        # Only a much later Harness tag exists. The first bridge tag is never served.
        requests = self.publish(HARNESS, LATE_TAG, 'relay-bridge', corrupt=True)
        self.unchanged_update('checksum does not match', requests)
        other = 'amd64' if ARCH == 'arm64' else 'arm64'
        requests = self.publish(HARNESS, LATE_TAG, 'relay-bridge', target=other)
        self.unchanged_update(f'expected linux/{ARCH}', requests)
        requests = self.publish(HARNESS, LATE_TAG, 'relay')
        self.unchanged_update('not a Sailry relay Go executable', requests)
        self.upgrade(self.publish(HARNESS, LATE_TAG, 'relay-bridge'), '0.2.8')

        # An operator's modified service must not be adopted by the bridge.
        owned = UNIT.read_bytes()
        try:
            UNIT.write_bytes(owned + b'\n# operator extension\n')
            self.server.requests.clear()
            self.unchanged_update('not a managed relay unit', [])
        finally:
            UNIT.write_bytes(owned)
        self.assertEqual(run('systemctl', 'show', '--value', '-p', 'NeedDaemonReload', UNIT.name), 'yes')
        self.unchanged_update('systemd has not loaded', [])
        run('systemctl', 'daemon-reload')
        requests = self.publish(RELAY, RELAY_TAG, 'relay', corrupt=True)
        self.unchanged_update('checksum does not match', requests)
        requests = self.publish(RELAY, RELAY_TAG, 'relay-bridge')
        self.unchanged_update('not a Sailry relay Go executable', requests)
        self.upgrade(self.publish(RELAY, RELAY_TAG, 'relay'), '0.2.9')
        for tag in (RELAY_TAG, 'v0.2.8'):
            requests = self.publish(RELAY, tag, 'relay')
            self.unchanged_update('No newer relay release', requests[:1], fails=False)


if __name__ == '__main__':
    unittest.main(verbosity=2)
