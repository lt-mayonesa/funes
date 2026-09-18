test_store = executable(
  'test-store',
  core_sources + files('test-store.vala'),
  dependencies: [glib_dep, gobject_dep, gio_dep, gtk_dep],
)

test('store', test_store)
