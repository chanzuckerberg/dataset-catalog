# Changelog

## [0.5.1](https://github.com/chanzuckerberg/dataset-catalog/compare/catalog-client-v0.5.0...catalog-client-v0.5.1) (2026-07-23)


### Miscellaneous

* **deps:** bump cryptography in /dataset-catalog-client ([#43](https://github.com/chanzuckerberg/dataset-catalog/issues/43)) ([fdb3766](https://github.com/chanzuckerberg/dataset-catalog/commit/fdb37662a7ccbae27ab89efce404667898a97e2b))

## [0.5.0](https://github.com/chanzuckerberg/dataset-catalog/compare/catalog-client-v0.4.0...catalog-client-v0.5.0) (2026-07-15)


### Features

* no-install REST read path, OLS expansion, and catalog-reader subagent ([#56](https://github.com/chanzuckerberg/dataset-catalog/issues/56)) ([4348b19](https://github.com/chanzuckerberg/dataset-catalog/commit/4348b19945931bd889dff91421954d11c0af17e3))

## [0.4.0](https://github.com/chanzuckerberg/dataset-catalog/compare/catalog-client-v0.3.0...catalog-client-v0.4.0) (2026-07-14)


### Features

* **client:** add read-only catalog-client CLI ([#55](https://github.com/chanzuckerberg/dataset-catalog/issues/55)) ([e6db799](https://github.com/chanzuckerberg/dataset-catalog/commit/e6db799f897470629a050450093f935165bde967))


### Miscellaneous

* **deps:** bump jupyter-server in /dataset-catalog-client ([#44](https://github.com/chanzuckerberg/dataset-catalog/issues/44)) ([6b64085](https://github.com/chanzuckerberg/dataset-catalog/commit/6b64085b1f57a53535b520c98822b5bb2851ebf1))
* **deps:** bump mistune from 3.2.1 to 3.3.0 in /dataset-catalog-client ([#54](https://github.com/chanzuckerberg/dataset-catalog/issues/54)) ([116b163](https://github.com/chanzuckerberg/dataset-catalog/commit/116b1635ae21cfeb6c0863c0e8649b062d2dbac4))
* **deps:** bump urllib3 from 2.6.3 to 2.7.0 in /dataset-catalog-client ([#34](https://github.com/chanzuckerberg/dataset-catalog/issues/34)) ([81524d7](https://github.com/chanzuckerberg/dataset-catalog/commit/81524d723945795ec78dda59de13b071fffbb36c))

## [0.3.0](https://github.com/chanzuckerberg/dataset-catalog/compare/catalog-client-v0.2.0...catalog-client-v0.3.0) (2026-06-16)


### Features

* Adding collection entries endpoint ([#36](https://github.com/chanzuckerberg/dataset-catalog/issues/36)) ([ae2e604](https://github.com/chanzuckerberg/dataset-catalog/commit/ae2e604fa18eee6cd9b01f183d3cd47a2ed4c5e6))
* Generate manifest from collections ([#38](https://github.com/chanzuckerberg/dataset-catalog/issues/38)) ([bd3854a](https://github.com/chanzuckerberg/dataset-catalog/commit/bd3854a60243db09271f6a56a19c55cbb9100955))
* sync client with catalog-api ([#26](https://github.com/chanzuckerberg/dataset-catalog/issues/26)) ([e980c91](https://github.com/chanzuckerberg/dataset-catalog/commit/e980c91fdf4e6e096816fbdc57da302c9cfb958d))


### Bug Fixes

* Updating the collection client to be in sync with API ([#32](https://github.com/chanzuckerberg/dataset-catalog/issues/32)) ([2958d84](https://github.com/chanzuckerberg/dataset-catalog/commit/2958d84acef5a11d082d4e899d50786110f30a3e))


### Miscellaneous

* Align catalog client with API ([#40](https://github.com/chanzuckerberg/dataset-catalog/issues/40)) ([2d74fab](https://github.com/chanzuckerberg/dataset-catalog/commit/2d74fab79f50cc515b31285e2ee212cb71e8ce19))
* **deps:** bump jupyter-server in /dataset-catalog-client ([#29](https://github.com/chanzuckerberg/dataset-catalog/issues/29)) ([1dca485](https://github.com/chanzuckerberg/dataset-catalog/commit/1dca48528d0b755b380f6ab14ed33dae333dcf73))
* **deps:** bump mistune from 3.2.0 to 3.2.1 in /dataset-catalog-client ([#30](https://github.com/chanzuckerberg/dataset-catalog/issues/30)) ([93a6f7b](https://github.com/chanzuckerberg/dataset-catalog/commit/93a6f7b724611983211e190143b1c761341d148d))
* Making registration methods consistent ([#35](https://github.com/chanzuckerberg/dataset-catalog/issues/35)) ([7a99285](https://github.com/chanzuckerberg/dataset-catalog/commit/7a99285317f0157d7c7fc2085316354c7d741868))

## [0.2.0](https://github.com/chanzuckerberg/dataset-catalog/compare/catalog-client-v0.1.0...catalog-client-v0.2.0) (2026-05-01)


### Features

* add _SyncBase/_AsyncBase; remove old base.py ([9c80f84](https://github.com/chanzuckerberg/dataset-catalog/commit/9c80f844d2f59dcaccb12f7361e642cc4e07c778))
* add CatalogClient, AsyncCatalogClient, and register() workflow ([96927d4](https://github.com/chanzuckerberg/dataset-catalog/commit/96927d4ed066414382d278c325b9b0c400635b06))
* add CollectionClient and AsyncCollectionClient ([22f6945](https://github.com/chanzuckerberg/dataset-catalog/commit/22f6945e14f437c09ff2b98e120a7e5422452730))
* add dataset models and DatasetRef ([2833ccc](https://github.com/chanzuckerberg/dataset-catalog/commit/2833ccc427c7c4760c28a90b0a2254a04f45bf18))
* add DatasetClient and AsyncDatasetClient ([8b0ea32](https://github.com/chanzuckerberg/dataset-catalog/commit/8b0ea3272b2f6df4e55e055ad075dd1794255245))
* add governance, quality, and metadata models ([a183544](https://github.com/chanzuckerberg/dataset-catalog/commit/a183544446e8548b4bf5370822db1b136c4a4552))
* add lineage and collection models; complete models package ([ddf24c6](https://github.com/chanzuckerberg/dataset-catalog/commit/ddf24c6755ce0dad18525a33f565cb23dc2ec3ee))
* add LineageClient and AsyncLineageClient ([42c4cde](https://github.com/chanzuckerberg/dataset-catalog/commit/42c4cdefd6966ca5f3060ba17c18eaf4b02d67df))
* add pagination and asset models ([5d6c562](https://github.com/chanzuckerberg/dataset-catalog/commit/5d6c562a38c56264811212b40dc77b9cef0e773f))
* add RegistrationBuilder with fluent interface ([3bfbe32](https://github.com/chanzuckerberg/dataset-catalog/commit/3bfbe3223d1be7bcd2bf07b70501e58cd6229e41))
* add RegistrationRequest and LineageSpec ([47c317a](https://github.com/chanzuckerberg/dataset-catalog/commit/47c317a04fee721172c58ff51af8aeddea7665d2))
* Add support for create_or_update ([#13](https://github.com/chanzuckerberg/dataset-catalog/issues/13)) ([7d5943b](https://github.com/chanzuckerberg/dataset-catalog/commit/7d5943b545f9a30ba07002f0a5645f1faba433e8))
* Adding checksum generation support to client ([#12](https://github.com/chanzuckerberg/dataset-catalog/issues/12)) ([8313ab0](https://github.com/chanzuckerberg/dataset-catalog/commit/8313ab0da419fb51ef9d10ba1bf5af0fb4112e88))
* Base client features ([1da7cf6](https://github.com/chanzuckerberg/dataset-catalog/commit/1da7cf6ba6dacd8c7b2dcafa2196a351534c48d5))
* Base client features ([1da7cf6](https://github.com/chanzuckerberg/dataset-catalog/commit/1da7cf6ba6dacd8c7b2dcafa2196a351534c48d5))
* complete catalog_client rewrite with register() workflow ([47ecd46](https://github.com/chanzuckerberg/dataset-catalog/commit/47ecd468122104af94f578c4c66512ea18d319b4))
* init commit ([3377f12](https://github.com/chanzuckerberg/dataset-catalog/commit/3377f12a228234210c44b190cb47a3bb0c38b91f))
* rewrite exceptions with full hierarchy ([ed7c0f3](https://github.com/chanzuckerberg/dataset-catalog/commit/ed7c0f334fe44b59326fd8750368e3c9845f398b))
