#!/bin/sh
set -eu
umask 077

test -n "${EPISODE2_AUTHORIZED_KEY_FINGERPRINT:-}"
case "${EPISODE2_EXECUTION_SHA256:-}" in *[!0-9a-f]*|'') exit 1 ;; esac
test "${#EPISODE2_EXECUTION_SHA256}" = 64
if test ! -f /root/.ssh/authorized_keys && test -n "${PUBLIC_KEY:-}"; then
  mkdir -p /root/.ssh
  test ! -L /root/.ssh
  printf '%s\n' "$PUBLIC_KEY" > /root/.ssh/authorized_keys
fi
test -d /root/.ssh && test ! -L /root/.ssh
test "$(stat -c %u /root/.ssh)" = 0
test -f /root/.ssh/authorized_keys && test ! -L /root/.ssh/authorized_keys
test "$(stat -c %u /root/.ssh/authorized_keys)" = 0
awk 'NF == 0 {exit 1} {lines += 1} END {exit !(lines == 1)}' /root/.ssh/authorized_keys
chmod 0700 /root/.ssh
chmod 0600 /root/.ssh/authorized_keys
actual_fingerprint="$(ssh-keygen -lf /root/.ssh/authorized_keys -E sha256 | awk '{print $2}')"
test "$actual_fingerprint" = "$EPISODE2_AUTHORIZED_KEY_FINGERPRINT"
mkdir -p /run/sshd /run/episode2
chmod 0700 /run/episode2
printf '%s\n' "$EPISODE2_EXECUTION_SHA256" > /run/episode2/execution-sha256
rm -f /etc/ssh/ssh_host_*
ssh-keygen -A >/dev/null
/usr/bin/python3.12 - <<'PY'
import glob,json,subprocess
fingerprints=[]
for path in sorted(glob.glob('/etc/ssh/ssh_host_*_key.pub')):
    raw=subprocess.check_output(['ssh-keygen','-lf',path,'-E','sha256'],text=True,timeout=5)
    fingerprints.append(raw.split()[1])
assert fingerprints
print(json.dumps({'schema_version':'episode2.ssh-host-keys.v1','fingerprints':fingerprints},separators=(',',':')),flush=True)
PY
/usr/sbin/sshd -t -o PasswordAuthentication=no -o KbdInteractiveAuthentication=no \
  -o PubkeyAuthentication=yes -o AuthenticationMethods=publickey -o PermitRootLogin=prohibit-password \
  -o PermitTTY=no -o X11Forwarding=no -o AllowAgentForwarding=no \
  -o AllowTcpForwarding=local -o GatewayPorts=no -o PermitOpen=127.0.0.1:8000
sshd_pid=''
cleanup() {
  trap - EXIT INT TERM HUP
  /usr/bin/python3.12 - <<'PY'
import json,subprocess
from pathlib import Path
p=Path('/run/episode2/process.json')
if p.exists():
    obj=json.loads(p.read_bytes())
    request={'operation':'stop','execution_sha256':obj['execution_sha256'],'epoch_id':obj['epoch_id'],'timeout_seconds':60}
    result=subprocess.run(['/usr/local/bin/episode2-control'],input=json.dumps(request).encode(),capture_output=True,timeout=65)
    print(result.stdout.decode(),flush=True)
PY
  if test -n "$sshd_pid"; then kill -TERM "$sshd_pid" 2>/dev/null || true; wait "$sshd_pid" 2>/dev/null || true; fi
}
trap cleanup EXIT INT TERM HUP
/usr/sbin/sshd -D -e -o PasswordAuthentication=no -o KbdInteractiveAuthentication=no \
  -o PubkeyAuthentication=yes -o AuthenticationMethods=publickey -o PermitRootLogin=prohibit-password \
  -o PermitTTY=no -o X11Forwarding=no -o AllowAgentForwarding=no \
  -o AllowTcpForwarding=local -o GatewayPorts=no -o PermitOpen=127.0.0.1:8000 &
sshd_pid=$!
wait "$sshd_pid"
