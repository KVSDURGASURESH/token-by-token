#!/bin/sh
set -eu
umask 077

test -n "${EPISODE1_AUTHORIZED_KEY_FINGERPRINT:-}"
case "${EPISODE1_PLAN_SHA256:-}" in
  *[!0-9a-f]*|'') exit 1 ;;
esac
test "${#EPISODE1_PLAN_SHA256}" = 64
test -d /root/.ssh
test ! -L /root/.ssh
test "$(stat -c %u /root/.ssh)" = 0
test -f /root/.ssh/authorized_keys
test ! -L /root/.ssh/authorized_keys
test "$(stat -c %u /root/.ssh/authorized_keys)" = 0
test -s /root/.ssh/authorized_keys
awk 'NF == 0 { exit 1 } { lines += 1 } END { exit !(lines == 1) }' /root/.ssh/authorized_keys
chmod 0700 /root/.ssh
chmod 0600 /root/.ssh/authorized_keys
actual_fingerprint="$(ssh-keygen -lf /root/.ssh/authorized_keys -E sha256 | awk '{print $2}')"
test "$actual_fingerprint" = "$EPISODE1_AUTHORIZED_KEY_FINGERPRINT"
mkdir -p /run/sshd
rm -f /etc/ssh/ssh_host_*
ssh-keygen -A
/usr/sbin/sshd -t \
  -o PasswordAuthentication=no -o KbdInteractiveAuthentication=no \
  -o PubkeyAuthentication=yes -o AuthenticationMethods=publickey \
  -o PermitRootLogin=prohibit-password -o PermitTTY=no \
  -o X11Forwarding=no -o AllowAgentForwarding=no \
  -o AllowTcpForwarding=local -o GatewayPorts=no -o PermitOpen=127.0.0.1:8000

control_pid=''
sshd_pid=''
cleanup() {
  trap - EXIT INT TERM HUP
  if test -n "$sshd_pid"; then kill -TERM "$sshd_pid" 2>/dev/null || true; fi
  if test -n "$control_pid"; then kill -TERM "$control_pid" 2>/dev/null || true; fi
  if test -n "$sshd_pid"; then wait "$sshd_pid" 2>/dev/null || true; fi
  if test -n "$control_pid"; then wait "$control_pid" 2>/dev/null || true; fi
}
trap cleanup EXIT INT TERM HUP

/usr/local/bin/episode1-control daemon &
control_pid=$!

/usr/sbin/sshd -D -e \
  -o PasswordAuthentication=no -o KbdInteractiveAuthentication=no \
  -o PubkeyAuthentication=yes -o AuthenticationMethods=publickey \
  -o PermitRootLogin=prohibit-password -o PermitTTY=no \
  -o X11Forwarding=no -o AllowAgentForwarding=no \
  -o AllowTcpForwarding=local -o GatewayPorts=no -o PermitOpen=127.0.0.1:8000 &
sshd_pid=$!

while kill -0 "$control_pid" 2>/dev/null && kill -0 "$sshd_pid" 2>/dev/null; do
  sleep 1
done
exit 1
