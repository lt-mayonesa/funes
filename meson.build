project(
  'funes',
  ['c', 'vala'],
  version: '0.1.0',
  license: 'GPL-3.0-or-later',
  meson_version: '>= 1.0.0',
  default_options: ['warning_level=1', 'c_std=gnu11'],
)

gnome = import('gnome')
i18n_domain = meson.project_name()

app_id = 'org.funes.Funes'

prefix = get_option('prefix')
bindir = get_option('bindir')
datadir = get_option('datadir')

conf = configuration_data()
conf.set('APP_ID', app_id)
conf.set('VERSION', meson.project_version())
config_vala = configure_file(
  input: 'src/config.vala.in',
  output: 'config.vala',
  configuration: conf,
)

glib_dep = dependency('glib-2.0', version: '>= 2.70')
gobject_dep = dependency('gobject-2.0')
gio_dep = dependency('gio-2.0')
gtk_dep = dependency('gtk+-3.0', version: '>= 3.22')
xapp_dep = dependency('xapp', version: '>= 2.0')

funes_deps = [glib_dep, gobject_dep, gio_dep, gtk_dep, xapp_dep]

add_project_arguments(['-w'], language: 'c')

core_sources = [config_vala] + files(
  'src/json-mini.vala',
  'src/history-item.vala',
  'src/history-store.vala',
  'src/json-file-store.vala',
  'src/settings.vala',
)

app_sources = files(
  'src/main.vala',
  'src/clipboard-monitor.vala',
  'src/paster.vala',
  'src/hotkey.vala',
  'src/autostart.vala',
  'src/tray.vala',
  'src/popup-window.vala',
  'src/settings-dialog.vala',
)

executable(
  'funes',
  core_sources + app_sources,
  dependencies: funes_deps,
  install: true,
  install_dir: bindir,
)

subdir('data')
subdir('tests')

gnome.post_install(
  glib_compile_schemas: true,
  gtk_update_icon_cache: true,
  update_desktop_database: true,
)
