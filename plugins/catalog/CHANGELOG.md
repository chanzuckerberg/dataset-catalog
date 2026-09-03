# Changelog

## [1.0.0](https://github.com/chanzuckerberg/dataset-catalog/compare/catalog-plugin-v0.6.0...catalog-plugin-v1.0.0) (2026-09-03)


### ⚠ BREAKING CHANGES

* **client:** `datasets.search()` no longer accepts `offset` — page with `cursor` or use `iter_search()`. `datasets.list()` returns `CursorPaginatedResponse` rather than `PaginatedResponse`, whose `total` and `offset` are now optional. `DatasetSearchResponse.offset` is gone. The `catalog search --offset` flag is replaced by `--cursor`.

### Features

* **client:** cursor pagination for dataset list and search ([#75](https://github.com/chanzuckerberg/dataset-catalog/issues/75)) ([7abef97](https://github.com/chanzuckerberg/dataset-catalog/commit/7abef9791546b40d03e0a317f865618a0de73225))

## [0.6.0](https://github.com/chanzuckerberg/dataset-catalog/compare/catalog-plugin-v0.5.0...catalog-plugin-v0.6.0) (2026-08-17)


### Features

* **checksum:** parallel folder hashing and a checksum CLI subcommand ([#69](https://github.com/chanzuckerberg/dataset-catalog/issues/69)) ([f29bc78](https://github.com/chanzuckerberg/dataset-catalog/commit/f29bc7811bb8366a84cdd7198206493a8d80ae84))

## [0.5.0](https://github.com/chanzuckerberg/dataset-catalog/compare/catalog-plugin-v0.4.0...catalog-plugin-v0.5.0) (2026-08-14)


### Features

* support Python 3.11 ([#65](https://github.com/chanzuckerberg/dataset-catalog/issues/65)) ([faebc4f](https://github.com/chanzuckerberg/dataset-catalog/commit/faebc4fac198dc026efaeb331e9e3560be8d369a))

## [0.4.0](https://github.com/chanzuckerberg/dataset-catalog/compare/catalog-plugin-v0.3.0...catalog-plugin-v0.4.0) (2026-07-23)


### Features

* **plugin:** Make the skills more specific and simple to use ([#61](https://github.com/chanzuckerberg/dataset-catalog/issues/61)) ([c9a16ac](https://github.com/chanzuckerberg/dataset-catalog/commit/c9a16ac41d4fd32370d31820904065a8051f2629))

## [0.3.0](https://github.com/chanzuckerberg/dataset-catalog/compare/catalog-plugin-v0.2.0...catalog-plugin-v0.3.0) (2026-07-15)


### Features

* no-install REST read path, OLS expansion, and catalog-reader subagent ([#56](https://github.com/chanzuckerberg/dataset-catalog/issues/56)) ([4348b19](https://github.com/chanzuckerberg/dataset-catalog/commit/4348b19945931bd889dff91421954d11c0af17e3))

## [0.2.0](https://github.com/chanzuckerberg/dataset-catalog/compare/catalog-plugin-v0.1.0...catalog-plugin-v0.2.0) (2026-07-14)


### Features

* Add claude plugin for registeration ([#48](https://github.com/chanzuckerberg/dataset-catalog/issues/48)) ([e43ef13](https://github.com/chanzuckerberg/dataset-catalog/commit/e43ef133e3ca507e6970d7981629cf1ed551a840))
* improving the registration skill ([#50](https://github.com/chanzuckerberg/dataset-catalog/issues/50)) ([6ce63f9](https://github.com/chanzuckerberg/dataset-catalog/commit/6ce63f99b775d923b0aa9a59c52c37b1238daa29))


### Miscellaneous

* Plugin optimization ([#49](https://github.com/chanzuckerberg/dataset-catalog/issues/49)) ([a8f8b14](https://github.com/chanzuckerberg/dataset-catalog/commit/a8f8b14ef8fa05c433e3555e5cf1735c1b6e07c9))
* Updating claude plugin ([#52](https://github.com/chanzuckerberg/dataset-catalog/issues/52)) ([077ad19](https://github.com/chanzuckerberg/dataset-catalog/commit/077ad190b4c47e5604adb1fdbd5a56207340c31d))
