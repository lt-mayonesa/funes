project(
  'funes',
  version: '0.6.1',
  # 0.60 is what Ubuntu 22.04 / Mint 21 ship; do not raise without dropping them.
  meson_version: '>= 0.60.0',
  license: 'GPL-3.0-or-later',
)

prefix = get_option('prefix')
bindir = get_option('bindir')
datadir = get_option('datadir')

funes_dir = join_paths(prefix, datadir, 'funes')
app_dir = join_paths(funes_dir, 'app')
pylib_dir = join_paths(prefix, 'lib', 'python3', 'dist-packages', 'funes')

# Shared, GTK-free modules: importable by tests and by any future daemon.
install_data(
  'funes/autostart.py',
  'funes/blobs.py',
  'funes/config.py',
  'funes/filters.py',
  'funes/hotkey.py',
  'funes/item.py',
  'funes/log.py',
  'funes/monitors.py',
  'funes/paster.py',
  'funes/presentation.py',
  'funes/search.py',
  'funes/store.py',
  install_dir: pylib_dir,
)

custom_target(
  'funes_init_versioned',
  input: 'funes/__init__.py',
  output: '__init__.py',
  command: ['sed', 's/__PROJECT_VERSION__/@0@/g'.format(meson.project_version()), '@INPUT@'],
  capture: true,
  install: true,
  install_dir: pylib_dir,
)

# The GTK application itself.
install_data(
  'app/clipboard.py',
  'app/funes_app.py',
  'app/popup.py',
  'app/preferences.py',
  'app/theming.py',
  'app/tray.py',
  install_dir: app_dir,
)

launcher_conf = configuration_data()
launcher_conf.set('app_dir', app_dir)
configure_file(
  input: 'data/funes.in',
  output: 'funes',
  configuration: launcher_conf,
  install: true,
  install_dir: bindir,
  install_mode: 'rwxr-xr-x',
)

subdir('data')
subdir('po')

python3 = find_program('/usr/bin/python3')
test(
  'unit-tests',
  python3,
  args: ['-m', 'unittest', 'discover', '-s', 'tests', '-v'],
  env: ['PYTHONDONTWRITEBYTECODE=1'],
  workdir: meson.project_source_root(),
)
