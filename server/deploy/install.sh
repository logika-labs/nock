#!/bin/sh
# Installs one release of api.nock.dev on this box (Logika's box 1, Debian 13). `deploy.py HOST` unpacks
# the release to /opt/nock-api/releases/ID and runs this as root:
#   sh /opt/nock-api/releases/ID/deploy/install.sh /opt/nock-api/releases/ID
#
# The box must be provisioned first (server/README.md, "Provisioning"): the system user nock-api, the
# nock role and database in Postgres, /etc/nock-api/nock-api.env, uv, Caddy importing
# /etc/caddy/sites/*.caddy.
set -eu

release=${1:?usage: install.sh /opt/nock-api/releases/ID}
case "$release" in
/opt/nock-api/releases/?*) ;;
*)
	echo "install.sh: $release is not a release under /opt/nock-api/releases" >&2
	exit 2
	;;
esac
env_file=/etc/nock-api/nock-api.env
if [ ! -f "$env_file" ]; then
	echo "install.sh: $env_file is missing; provision the box first (server/README.md)" >&2
	exit 1
fi

echo "== interpreter and packages"
export UV_PYTHON_INSTALL_DIR=/opt/nock-api/python
uv venv --quiet --python 3.14 "$release/venv"
uv pip install --quiet --compile-bytecode --python "$release/venv/bin/python" --require-hashes --no-deps \
	-r "$release/requirements.txt"
uv pip install --quiet --compile-bytecode --python "$release/venv/bin/python" --no-deps "$release"/wheels/*.whl
# The service runs as nock-api, which must read the interpreter and the release, never write them.
chmod -R a+rX,go-w "$release" "$UV_PYTHON_INSTALL_DIR"

echo "== migrations"
# Before the restart, with the new release: migrations are forward-only, so the running release keeps working.
systemd-run --quiet --wait --pipe --collect --uid=nock-api --gid=nock-api \
	-p EnvironmentFile="$env_file" -p WorkingDirectory="$release" \
	"$release/venv/bin/nock-api" migrate --directory "$release/migrations"

echo "== system files"
install -m 0644 "$release/deploy/nock-api.service" /etc/systemd/system/nock-api.service
systemctl daemon-reload
site=/etc/caddy/sites/nock-api.caddy
if ! cmp -s "$release/deploy/nock-api.caddy" "$site"; then
	install -d /etc/caddy/sites
	[ ! -f "$site" ] || cp "$site" "$site.previous"
	install -m 0644 "$release/deploy/nock-api.caddy" "$site"
	# Logika's Caddyfile, which imports the site, reads its placeholders from caddy.env.
	if ! (
		set -a
		[ ! -f /etc/caddy/caddy.env ] || . /etc/caddy/caddy.env
		caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile
	); then
		if [ -f "$site.previous" ]; then mv "$site.previous" "$site"; else rm -f "$site"; fi
		echo "install.sh: Caddy refuses the new site; the previous one is back" >&2
		exit 1
	fi
	rm -f "$site.previous"
	systemctl reload caddy.service
fi

echo "== switch"
ln -sfn "$release" /opt/nock-api/current.new
mv -T /opt/nock-api/current.new /opt/nock-api/current

echo "== restart"
systemctl enable --quiet nock-api.service
systemctl restart nock-api.service

echo "== prune"
# Keep the five newest releases; names start with their UTC time, so they sort by age.
find /opt/nock-api/releases -mindepth 1 -maxdepth 1 -type d | sort | head -n -5 | while read -r old; do
	[ "$old" = "$release" ] || rm -rf "$old"
done
echo "installed $release"
