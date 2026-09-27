# Incident: `fns install-local` clobbered the system GSettings schema cache

**Date:** 2026-09-26
**Host:** `frmwrk` (Linux Mint, XFCE, LightDM + slick-greeter, Framework laptop, Intel Iris Xe / `i915`)
**Symptom:** Boot hangs forever on the Linux Mint splash logo. TTY (Ctrl+Alt+F3) still works.
**Severity:** High — machine unusable in graphical mode.
**Cause:** Local dev tooling in this repo (`.cli/install_local`), not an OS update.
**Status:** Root-caused, recovery procedure known, code fix applied (Option B: `.cli/install_local/__init__.py`, `.cli/_lib.py`).

---

## 1. Summary

`fns install-local` runs `glib-compile-schemas --targetdir /usr/share/glib-2.0/schemas data/`.

`--targetdir` does **not** merge into an existing cache — it **overwrites** `gschemas.compiled`
in the target directory with a compile of the source directory only. Since `data/` contains a
single schema (`org.x.funes.gschema.xml`), the system-wide cache was reduced from 341 schemas
to 1.

`slick-greeter` needs the `x.dm.slick-greeter` schema at startup. Missing schema in a
`g_settings_new()` call is a **fatal** GLib error (`g_log` → `abort`), so the greeter crashes
instantly, LightDM restart-loops, hits its start limit, and the boot never leaves the splash.

---

## 2. Evidence

### 2.1 Failed units

```
$ systemctl --failed
● casper-md5check.service  loaded failed failed  casper-md5check Verify Live ISO checksums
● gpu-manager.service      loaded failed failed  Detect the available GPUs ...
● lightdm.service          loaded failed failed  Light Display Manager

$ systemctl is-system-running
degraded
```

### 2.2 LightDM restart loop

```
$ systemctl status display-manager
× lightdm.service - Light Display Manager
     Active: failed (Result: exit-code) since Sat 2026-09-26 20:19:36 CEST
   Duration: 1.054s
    Process: ExecStart=/usr/sbin/lightdm (code=exited, status=1/FAILURE)

Sep 26 20:19:36 frmwrk systemd[1]: lightdm.service: Scheduled restart job, restart counter is at 5.
Sep 26 20:19:36 frmwrk systemd[1]: lightdm.service: Start request repeated too quickly.
Sep 26 20:19:36 frmwrk systemd[1]: Failed to start lightdm.service - Light Display Manager.
```

Five start attempts in ~6 seconds, each lasting ~1s.

### 2.3 The actual crash

```
Sep 26 20:19:36 frmwrk kernel: traps: slick-greeter[10454] trap int3 ip:722a5e1cc721 sp:7fff54cd20d0 \
    error:0 in libglib-2.0.so.0.8000.0[62721,722a5e188000+a0000]
Sep 26 20:19:36 frmwrk systemd-coredump[10456]: Process 10454 (slick-greeter) of user 113 dumped core.

    Stack trace of thread 10454:
    #0  g_logv                      (libglib-2.0.so.0   + 0x62721)
    #1  g_log                       (libglib-2.0.so.0   + 0x629d3)
    #2  n/a                         (libgio-2.0.so.0    + 0xf6445)
    #3  n/a                         (libgobject-2.0.so.0 + 0x261fa)
    #4  n/a                         (libgobject-2.0.so.0 + 0x26b98)
    #5  g_object_new_valist         (libgobject-2.0.so.0 + 0x28bc3)
    #6  g_object_new                (libgobject-2.0.so.0 + 0x28f4f)
    #7  n/a                         (slick-greeter      + 0x1442d)
    #8  __libc_start_call_main      (libc.so.6          + 0x2a1ca)
```

`trap int3` from `g_logv` inside `libgio` during `g_object_new` is the textbook signature of
**"Settings schema 'x' is not installed"** — GLib treats it as fatal and aborts.

### 2.4 Smoking gun

```
$ ls -la /usr/share/glib-2.0/schemas/gschemas.compiled
-rw-r--r-- 1 root root 1596 Sep 26 19:33 gschemas.compiled     # 1.5 KB — should be ~2 MB

$ ls /usr/share/glib-2.0/schemas/ | wc -l
341                                                            # XML sources all still present

$ ls /usr/share/glib-2.0/schemas/ | grep slick
x.dm.slick-greeter.gschema.xml                                 # greeter's schema IS on disk

$ gsettings list-schemas
org.x.funes                                                    # ...but only funes is compiled

$ strings /usr/share/glib-2.0/schemas/gschemas.compiled | grep org
org.x.funes
/org/x/funes/
```

Cache mtime `Sep 26 19:33` lines up with the last `fns install-local` run; first failed boot
was `20:11`.

`dpkg -V slick-greeter` is clean — no package file was modified or deleted. Only the
*compiled cache* was destroyed.

### 2.5 Files this repo has installed into `/usr`

```
/usr/share/glib-2.0/schemas/org.x.funes.gschema.xml
/usr/share/applications/org.x.funes.desktop
/usr/share/icons/hicolor/256x256/apps/org.x.funes.png
/usr/share/icons/hicolor/scalable/apps/org.x.funes.svg
/usr/share/icons/hicolor/symbolic/apps/org.x.funes-symbolic.svg
/usr/share/funes/app
/usr/lib/python3/dist-packages/funes
```

### 2.6 Ruled out

| Suspect | Verdict | Evidence |
|---|---|---|
| Disk full | No | `/` 30% used (128G/457G), inodes 13% |
| GPU / driver | No | Intel Iris Xe `8086:46a6`, `i915` bound, `card1-eDP-1` connected; `gpu-manager.log` says `Single card detected / Nothing to do` |
| Kernel / initramfs | No | Kernel boots, TTYs work, no module errors |
| `gpu-manager.service` failure | Collateral | `start-limit-hit` only, dragged down by the LightDM loop |
| `casper-md5check.service` failure | Benign | Live-ISO leftover unit; always fails on an installed system |
| apt dist-upgrade | No | No package files modified (`dpkg -V` clean) |

---

## 3. Failure chain

1. `fns install-local` → `glib-compile-schemas --targetdir /usr/share/glib-2.0/schemas data/`
2. `/usr/share/glib-2.0/schemas/gschemas.compiled` overwritten; 340 schemas vanish from the cache
3. Reboot
4. LightDM spawns `slick-greeter`
5. `g_settings_new("x.dm.slick-greeter")` → schema not in cache → fatal `g_log` → `SIGTRAP`/abort
6. `lightdm` exits `1`; systemd restarts it — 5× in 6s
7. `Start request repeated too quickly` → unit dead, `system-running = degraded`
8. Plymouth never gets handed off to a display manager → **stuck on the Mint splash**

---

## 4. Offending code

`.cli/install_local/__init__.py:41-47`

```python
run(
    "glib-compile-schemas",
    "--targetdir",
    "/usr/share/glib-2.0/schemas",
    str(ROOT / "data"),
    sudo=True,
)
```

Reading `glib-compile-schemas --help`: the positional argument is the *directory to scan*, and
`--targetdir` is where the resulting `gschemas.compiled` is *written*. Writing a
single-schema compile into a shared system directory destroys every other schema's entry.
The XML files are untouched, which is why the damage is invisible to `ls` and to `dpkg -V`.

### Secondary problem: install/uninstall disagree on prefix

`.cli/uninstall/__init__.py:16,30-31` operates on `/usr/local`:

```python
"/usr/local/share/glib-2.0/schemas/org.x.funes.gschema.xml",
...
"glib-compile-schemas",
"/usr/local/share/glib-2.0/schemas",
```

while `install_local` writes to `/usr`. So `fns uninstall` cannot remove what `fns
install-local` installed. Note the uninstall call is already the **correct** form —
directory positional, no `--targetdir`.

For reference, `.cli/run/__init__.py:29` also uses `--targetdir`, but into a private build
dir, which is the legitimate use of that flag. Leave it alone.

---

## 5. Code fix — pick one

Not applied yet. Both are correct; **Option B** is recommended because it matches what
`uninstall` already expects and never writes to `/usr`, which is dpkg's territory.

### Option A — keep `/usr`, recompile the whole directory

```python
run("cp", str(ROOT / "data" / "org.x.funes.gschema.xml"),
    "/usr/share/glib-2.0/schemas/", sudo=True)
run("glib-compile-schemas", "/usr/share/glib-2.0/schemas", sudo=True)
```

- Schema stays where it is today, so no migration needed.
- Still writes into a dpkg-managed directory; a package update can overwrite it.

### Option B — move to `/usr/local` (recommended)

```python
run("mkdir", "-p", "/usr/local/share/glib-2.0/schemas", sudo=True)
run("cp", str(ROOT / "data" / "org.x.funes.gschema.xml"),
    "/usr/local/share/glib-2.0/schemas/", sudo=True)
run("glib-compile-schemas", "/usr/local/share/glib-2.0/schemas", sudo=True)
```

- GLib searches `XDG_DATA_DIRS`, which includes `/usr/local/share`, so lookup still works.
- Makes `fns uninstall` correct with no changes.
- Blast radius of a future mistake is limited to a directory only this project writes to.
- Requires a one-time cleanup of the stale `/usr/share/glib-2.0/schemas/org.x.funes.gschema.xml`
  (and a recompile of that directory afterwards).

### Guard rail worth adding either way

Never pass `--targetdir` pointing at a directory you do not own. If a future command needs it,
assert the target is under the build dir or `/usr/local`.

---

## 6. System recovery

Automated: run `/home/joaco/src/fix-gschemas.sh` as root.

Manual equivalent:

```bash
sudo cp -a /usr/share/glib-2.0/schemas/gschemas.compiled \
           /var/backups/gschemas.compiled.broken            # optional
sudo glib-compile-schemas /usr/share/glib-2.0/schemas       # rebuild from all 341 XMLs
gsettings list-schemas | wc -l                              # expect ~341, not 1
gsettings list-schemas | grep x.dm.slick-greeter            # must print
sudo systemctl reset-failed lightdm gpu-manager
sudo systemctl start lightdm                                # kills the TTY session
```

Funes keeps working: `org.x.funes.gschema.xml` is already present in that directory, so the
rebuild includes it.

If `lightdm` still fails after the rebuild, read the greeter log directly (needs root):

```bash
sudo tail -60 /var/log/lightdm/seat0-greeter.log
sudo tail -60 /var/log/lightdm/x-0.log
```

---

## 7. Blast radius — it was never only LightDM

Audited 2026-09-26 20:40, pre-fix, with `/home/joaco/src/audit-gsettings.sh`.

**LightDM was just the loudest victim.** Every GSettings consumer on the machine was broken
from 19:33:56 onward. LightDM was the only one that made the machine unbootable, so it got
the attention.

### 7.1 Scale

| Metric | Value |
|---|---|
| `.gschema.xml` sources on disk | 322 (+ 4 `.gschema.override`) |
| Schemas actually in the cache | **1** (`org.x.funes`) |
| Cache size | 1596 B (expected ~2 MB) |
| Cache mtime | 2026-09-26 19:33:56 |

Every one of the other 321 schemas was unreadable. `gsettings get` on any of them failed;
any app calling `g_settings_new()` on one aborted.

### 7.2 Exact command, from the sudo log

```
Sep 26 19:33:56 frmwrk sudo[229600]: joaco : TTY=pts/1 ; PWD=/home/joaco/src/linux/funes ; USER=root ;
    COMMAND=/usr/bin/glib-compile-schemas --targetdir /usr/share/glib-2.0/schemas /home/joaco/src/linux/funes/data
```

Cache mtime matches the sudo timestamp to the second.

### 7.3 Who actually crashed (26 coredumps since 19:30)

```
15  /usr/sbin/slick-greeter                        # 3 boot attempts x 5 restarts
 7  /usr/bin/python3.12                            # funes itself, during the dev loop
 1  /usr/lib/x86_64-linux-gnu/cinnamon-session-binary
 1  /usr/libexec/xdg-desktop-portal
 1  /usr/libexec/ibus-ui-gtk3
 1  /usr/bin/file-roller
```

Same `SIGTRAP` signature on all of them. One runtime error made it to the journal in plain
text before the log filled with greeter crashes:

```
Sep 26 20:14:50 frmwrk xdg-desktop-por[6148]: Settings schema 'org.gnome.system.proxy' is not installed
```

Note `file-roller` at 19:54 — an ordinary archive double-click was already dying ~20 minutes
before the first failed boot. The desktop was broken before the reboot; the reboot only made
it unrecoverable. `cinnamon-session-binary` and `ibus-ui-gtk3` dying at 20:14 means a Cinnamon
session would not have come up either — this was never specific to slick-greeter or to XFCE.

### 7.4 Critical schemas confirmed missing from the cache

XML present on disk, absent from the compiled cache:

| Schema | Consumer |
|---|---|
| `x.dm.slick-greeter` | LightDM greeter — **the boot hang** |
| `org.gnome.system.proxy` | xdg-desktop-portal, GLib networking — **observed in the journal** |
| `org.cinnamon` | Cinnamon shell |
| `org.cinnamon.desktop.interface` | GTK theme/font |
| `org.cinnamon.desktop.background` | Wallpaper |
| `org.cinnamon.settings-daemon.plugins.power` | Power management |
| `org.nemo.preferences` | Nemo |
| `org.gnome.desktop.interface` | GTK apps, portals |
| `org.gtk.Settings.FileChooser` | File dialogs in every GTK app |
| `org.x.apps.portal` | XApp portal |
| `org.x.editor.preferences.editor` | xed |

11 of 12 probed. Only `org.x.funes` survived — it was the one being compiled.

### 7.5 Vendor overrides also lost

`.gschema.override` files are merged into the cache **at compile time**. Clobbering the cache
discards them even where the schema itself would otherwise exist. All 4 were gone:

```
10_cinnamon.gschema.override
10_compiz-gnome.gschema.override
10_gsettings-desktop-schemas.gschema.override
mint-artwork.gschema.override          <- also carries x.dm.slick-greeter defaults
```

Practical effect: Mint's branding, default theme and default-application choices silently
revert to upstream GNOME defaults. This is the failure mode that would have been hardest to
diagnose had the greeter not crashed outright.

### 7.6 What was NOT damaged

This is the good news, and it is the reason recovery is a one-liner.

**User settings are intact.** dconf stores values keyed by *path*, with no dependency on the
schema cache:

```
~/.config/dconf/user : 45203 bytes, 716 lines across 118 paths
```

`dconf read` on a raw path still returned correct values while `gsettings get` failed:

| Path | Value recovered via dconf |
|---|---|
| `/org/cinnamon/desktop/interface/gtk-theme` | `'Mint-Y-Dark'` |
| `/org/cinnamon/desktop/interface/icon-theme` | `'Papirus-Dark'` |
| `/org/cinnamon/desktop/background/picture-uri` | `'file:///usr/share/backgrounds/linuxmint-vanessa/sferrara_new_zealand.jpg'` |
| `/org/gnome/desktop/interface/gtk-theme` | `'Mint-Y-Dark'` |

So: nothing to re-configure after the fix. Theme, wallpaper and preferences come straight
back once the schemas can be resolved again.

**Exactly one file was damaged.** `find /usr -xdev -newermt "2026-09-26 00:00"` outside this
project's own files returns only:

```
19:33  /usr/share/glib-2.0/schemas/gschemas.compiled
```

(plus `/usr/share/keyrings/google-chrome.gpg` at 20:16 from an unrelated apt run)

**Adjacent caches are fine.** `install-local` also drops `.desktop` and icon files into
`/usr/share`, but the tools that refresh those caches rescan the whole directory and have no
`--targetdir` equivalent:

```
/usr/share/applications/mimeinfo.cache          35651 B   2026-09-26 15:18
/usr/share/icons/hicolor/icon-theme.cache       95768 B   2026-09-26 15:18
/usr/share/mime/mime.cache                     171388 B   2026-09-08
/etc/ld.so.cache                               115051 B   2026-09-25
```

Both Sep-26 timestamps are normal `update-desktop-database` / `gtk-update-icon-cache` runs
from installing the funes `.desktop` and icons. Sizes are healthy, desktop database parses
clean.

**No `/usr/local` shadow copy.** `/usr/local/share/glib-2.0/schemas` exists but is empty, so
there is no duplicate schema competing via `XDG_DATA_DIRS`
(`/var/lib/flatpak/exports/share:/usr/local/share/:/usr/share/`). Corollary: `fns uninstall`,
which targets that path, has always been a silent no-op.

**dpkg integrity is clean.** A full `dpkg -V` sweep flagged nothing related to this incident.
The only project-relevant entries are the expected ones — `install-local` overwriting its own
packaged files:

```
??5??????  /usr/lib/python3/dist-packages/funes/config.py
??5??????  /usr/lib/python3/dist-packages/funes/paster.py
??5??????  /usr/share/funes/app/funes_app.py
??5??????  /usr/share/funes/app/popup.py
??5??????  /usr/share/funes/app/preferences.py
```

Remaining `dpkg -V` output is pre-existing noise: kernel images, missing kdeconnect/KDE
`.desktop` files, legacy Mint-Y icon themes, `/etc` conffiles. Unrelated.

Crucially, `gschemas.compiled` is a **generated** file, so it appears in no package's
`md5sums`. `dpkg -V` is structurally blind to this class of damage — which is why the
system looked healthy by every package-level check while being unbootable.

### 7.7 Re-running the audit

```bash
bash /home/joaco/src/audit-gsettings.sh | tee /tmp/audit-before.txt
sudo bash /home/joaco/src/fix-gschemas.sh
bash /home/joaco/src/audit-gsettings.sh | tee /tmp/audit-after.txt
diff -u /tmp/audit-before.txt /tmp/audit-after.txt
```

Read-only, writes nothing outside `/tmp`, never restarts a service. Run as your normal user
so the dconf checks read your database. Expected post-fix: section 1 shows ~322 schemas,
sections 2/3 all `OK`, section 6 flips from `schema lookup FAILS` to real values, section 10
reports healthy.

---

## 8. Lessons

- `glib-compile-schemas --targetdir DIR SRC` is a **replace**, not a merge. Only aim it at
  directories the project owns.
- Dev-loop scripts with `sudo` into `/usr` can brick the graphical session while leaving every
  package verification check green — `dpkg -V` does not see cache corruption.
- A missing GSettings schema is fatal, not a warning. Any display-manager greeter is one bad
  cache away from an unbootable desktop.
- Keep install and uninstall on the same prefix, or uninstall silently no-ops — confirmed
  here: `/usr/local/share/glib-2.0/schemas` is empty, so `fns uninstall` has never removed
  anything.
- Generated caches are invisible to `dpkg -V`. Package verification passing does not mean the
  system is intact.
- The blast radius of a shared-cache clobber is every consumer of that cache, not just the one
  that fails loudly. `file-roller` was already crashing 20 minutes before the first bad boot.
