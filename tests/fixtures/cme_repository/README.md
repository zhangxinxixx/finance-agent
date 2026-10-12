# CME repository/parser fixture

`Section64_Metals_Option_Products_2026-05-06.pdf` is a version-managed copy of
the real PDF preserved in the non-running E2E acceptance archive
`storage/raw/cme/daily_bulletin/2026-05-06/Section64_Metals_Option_Products_2026-05-06.pdf`.

- trade date: `2026-05-06`
- size: `888765` bytes
- SHA-256: `1185cbdd78a8378af454b11222da354051eaed3daf1635f6f240d7f69017fb7d`
- archive provenance: the E2E acceptance report records that its `app/storage`
  is an isolated copy of the original storage and that the formal runtime was
  not started or modified.

The tests use this fixture directly. It is not restored under `storage/`, and
the test suite does not read the live runtime directory.
