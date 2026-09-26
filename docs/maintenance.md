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

## Upgrading OpenTAKServer

Make a backup first, then use OpenTAKServer's updater:

```bash
./setup/backup.sh
curl -L https://i.opentakserver.io/ubuntu_updater | bash - | tee ~/ots_upgrade.log
```

On a Raspberry Pi use `https://i.opentakserver.io/raspberry_pi_installer`
instead. After upgrading run `takcx doctor`, and re-run `takcx share NAME` for
any active links if the web folder was replaced.

## Updating ATAK-CX

```bash
cd ~/ATAK-CX && git pull
```

`takcx` is a link into this folder, so that's all it takes.

## Keep the OS patched

```bash
sudo apt update && sudo apt upgrade -y
```

Or turn on automatic security updates: `sudo apt install unattended-upgrades`.
