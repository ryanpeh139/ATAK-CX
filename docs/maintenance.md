# Backups, restore and upgrades

## Backups

The installer schedules `setup/backup.sh` nightly at 03:17 into `~/takcx-backups/`
(the last 14 are kept). Run one any time:

```bash
./setup/backup.sh
```

Each backup has the **certificate authority**, OpenTAKServer's config, uploaded
files, the database and `~/takcx` (team settings and everyone's packages).
The certificate authority is the part that matters: without it, every
device has to be set up again.

**Copy backups off the server** now and then, and keep them private (they hold
everyone's keys):

```bash
scp 'tak@your-server:takcx-backups/*.tar.gz' ~/tak-backups/
```

## Restore onto a new server

1. Set up the new server with the **same Linux username** and the same address
   (update DNS if the IP changed), run `./setup/install-server.sh` as usual and
   let it finish.
2. Copy the backup over and restore it:
   ```bash
   mkdir ~/restore && tar -xzf takcx-backup-XXXX.tar.gz -C ~/restore
   sudo systemctl stop opentakserver cot_parser eud_handler eud_handler_ssl

   # Config: take the old one (it holds the password salt and secret keys that
   # the restored accounts depend on), but keep this server's database login.
   NEW_DB="$(grep '^SQLALCHEMY_DATABASE_URI:' ~/ots/config.yml)"
   cp ~/restore/ots/config.yml ~/ots/config.yml
   sed -i "s|^SQLALCHEMY_DATABASE_URI:.*|$NEW_DB|" ~/ots/config.yml

   # Certificates and uploaded files
   rm -rf ~/ots/ca && cp -a ~/restore/ots/ca ~/ots/
   cp -a ~/restore/ots/uploads ~/ots/ 2>/dev/null || true

   # Database (restored as the "ots" user)
   sudo -u postgres psql -c "DROP DATABASE ots;" -c "CREATE DATABASE ots OWNER ots;"
   sudo -u postgres psql -d ots -c "CREATE EXTENSION postgis;"
   export PGPASSWORD="$(sed -n 's|^SQLALCHEMY_DATABASE_URI: *[^:]*://ots:\(.*\)@.*|\1|p' ~/ots/config.yml)"
   psql -q -h 127.0.0.1 -U ots -d ots < ~/restore/ots.sql
   unset PGPASSWORD
   # Two errors about "extension postgis" / "spatial_ref_sys" are normal; ignore them.

   # Team settings, admin login and packages
   rm -rf ~/takcx && cp -a ~/restore/takcx ~/takcx

   sudo systemctl start opentakserver cot_parser eud_handler eud_handler_ssl
   takcx doctor
   ```

Everyone's existing packages keep working because the certificate authority is the same.
Share links aren't part of the backup; run `takcx share NAME` again for any you still need.
If you use the team radio, run `./setup/enable-radio.sh` once more afterwards to relink it.

## Updating (ATAK-CX, OpenTAKServer and the web map)

One step updates everything: **Manager → Settings → Update everything**, or over SSH:

```bash
cd ~/ATAK-CX && ./setup/update.sh          # --check just says what's out of date
```

In order, it:

1. gets the newest ATAK-CX (`git pull`)
2. if OpenTAKServer or its web map is out of date: **backs up** (`setup/backup.sh`),
   updates OpenTAKServer from PyPI, upgrades its database, restarts it and waits
   until it's healthy, then swaps in the newest web map
3. rebuilds everyone's welcome pages and packages (links stay the same)
4. runs `takcx doctor`, then restarts the Manager

The output is saved to `~/takcx/last-update.log` and shown under Settings → Updates.

**Why not OpenTAKServer's own updater?** It empties the web map's folder
(`/var/www/html/opentakserver`), which is also where everyone's private links (`join/`)
and downloads like elevation data (`files/`) live, and it stops to ask questions.
`takcx/ots_update.py` does the same steps but keeps those folders. It doesn't touch nginx,
Mumble, MediaMTX or your settings, and the systemd tweaks ATAK-CX adds live in drop-in
files that survive updates.

**If OpenTAKServer doesn't come back** after an update, the output says how to go back
to the version you had:

```bash
~/.opentakserver_venv/bin/pip install opentakserver==OLD_VERSION
# restore the database from the backup it made (see "Restore" above)
sudo systemctl restart opentakserver
```

**If an update changes what the Manager may do** (new services it may restart, a new
page in nginx), its notes will say to re-run `./setup/enable-manager.sh` once over SSH.

## Keep the OS patched

```bash
sudo apt update && sudo apt upgrade -y
```

Or turn on automatic security updates: `sudo apt install unattended-upgrades`.
