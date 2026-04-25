"""Tests for checksum utilities module."""


# from catalog_client.utils.checksums import ChecksumWarning, _ChecksumBackend, _HashUtils


class TestHashUtils:
    """Test hash algorithm implementations."""


#     def test_blake3_algorithm(self):
#         """Test blake3 produces expected output."""
#         data = b"hello world"
#         result = _HashUtils.blake3(data)
#         # blake3 of "hello world" is consistent
#         assert isinstance(result, str)
#         assert len(result) == 64  # blake3 default 256-bit = 64 hex chars
#
#         # Same input produces same output
#         assert _HashUtils.blake3(data) == result
#
#     def test_blake2b_algorithm(self):
#         """Test blake2b produces expected output."""
#         data = b"hello world"
#         result = _HashUtils.blake2b(data)
#         assert isinstance(result, str)
#         assert len(result) == 128  # blake2b default 512-bit = 128 hex chars
#         assert _HashUtils.blake2b(data) == result
#
#     def test_blake2s_algorithm(self):
#         """Test blake2s produces expected output."""
#         data = b"hello world"
#         result = _HashUtils.blake2s(data)
#         assert isinstance(result, str)
#         assert len(result) == 64  # blake2s default 256-bit = 64 hex chars
#         assert _HashUtils.blake2s(data) == result
#
#     def test_crc32_algorithm(self):
#         """Test crc32 produces expected output."""
#         data = b"hello world"
#         result = _HashUtils.crc32(data)
#         assert isinstance(result, str)
#         assert len(result) == 8  # crc32 is 32-bit = 8 hex chars
#         assert _HashUtils.crc32(data) == result
#
#     def test_algorithm_deterministic(self):
#         """Test all algorithms are deterministic."""
#         data = b"test data for consistency"
#
#         assert _HashUtils.blake3(data) == _HashUtils.blake3(data)
#         assert _HashUtils.blake2b(data) == _HashUtils.blake2b(data)
#         assert _HashUtils.blake2s(data) == _HashUtils.blake2s(data)
#         assert _HashUtils.crc32(data) == _HashUtils.crc32(data)
#
#
# class TestCheckSumBackend:
#     """Test _ChecksumBackend platform detection."""
#
#     def test_explicit_storage_platform_takes_precedence(self):
#         """Test explicit storage_platform overrides URI detection."""
#         from catalog_client.utils.checksums import _ChecksumBackend
#
#         backend = _ChecksumBackend()
#         asset = DataAssetRequest(
#             location_uri="file:///local/path",
#             asset_type=AssetType.file,
#             storage_platform=StoragePlatform.s3,
#         )
#         platform = backend._determine_platform(asset)
#         assert platform == StoragePlatform.s3
#
#     def test_uri_pattern_detection_s3(self):
#         """Test S3 URI pattern detection."""
#         from catalog_client.utils.checksums import _ChecksumBackend
#
#         backend = _ChecksumBackend()
#         asset = DataAssetRequest(
#             location_uri="s3://bucket/key", asset_type=AssetType.file
#         )
#         platform = backend._determine_platform(asset)
#         assert platform == StoragePlatform.s3
#
#     def test_uri_pattern_detection_s3a(self):
#         """Test S3A URI pattern detection."""
#         from catalog_client.utils.checksums import _ChecksumBackend
#
#         backend = _ChecksumBackend()
#         asset = DataAssetRequest(
#             location_uri="s3a://bucket/key", asset_type=AssetType.file
#         )
#         platform = backend._determine_platform(asset)
#         assert platform == StoragePlatform.s3
#
#     def test_uri_pattern_detection_hpc(self):
#         """Test HPC URI pattern detection."""
#         from catalog_client.utils.checksums import _ChecksumBackend
#
#         backend = _ChecksumBackend()
#         asset = DataAssetRequest(
#             location_uri="/hpc/data/file.txt", asset_type=AssetType.file
#         )
#         platform = backend._determine_platform(asset)
#         assert platform == StoragePlatform.hpc
#
#     def test_uri_pattern_detection_bruno_hpc(self):
#         """Test Bruno HPC URI pattern detection."""
#         from catalog_client.utils.checksums import _ChecksumBackend
#
#         backend = _ChecksumBackend()
#         asset = DataAssetRequest(
#             location_uri="/bruno_hpc/data/file.txt", asset_type=AssetType.file
#         )
#         platform = backend._determine_platform(asset)
#         assert platform == StoragePlatform.bruno_hpc
#
#     def test_uri_pattern_detection_coreweave(self):
#         """Test CoreWeave URI pattern detection."""
#         from catalog_client.utils.checksums import _ChecksumBackend
#
#         backend = _ChecksumBackend()
#         asset = DataAssetRequest(
#             location_uri="/coreweave/data/file.txt", asset_type=AssetType.file
#         )
#         platform = backend._determine_platform(asset)
#         assert platform == StoragePlatform.coreweave
#
#     def test_unsupported_platform_returns_none(self):
#         """Test unsupported platform returns None."""
#         from catalog_client.utils.checksums import _ChecksumBackend
#
#         backend = _ChecksumBackend()
#         asset = DataAssetRequest(
#             location_uri="http://example.com/file.txt", asset_type=AssetType.file
#         )
#         platform = backend._determine_platform(asset)
#         assert platform is None
#
#     def test_compute_filesystem_checksum_blake3(self):
#         """Test filesystem checksum computation with blake3."""
#         backend = _ChecksumBackend()
#
#         # Create temporary test file
#         with tempfile.NamedTemporaryFile(mode="w", delete=False) as f:
#             f.write("hello world")
#             temp_path = f.name
#
#         try:
#             checksum_value, checksum_alg = backend._compute_filesystem_checksum(
#                 temp_path, "blake3"
#             )
#
#             # Verify result format
#             assert isinstance(checksum_value, str)
#             assert checksum_alg == "blake3"
#             assert len(checksum_value) == 64  # blake3 256-bit = 64 hex chars
#
#             # Verify it matches direct hash computation
#             expected = _HashUtils.blake3(b"hello world")
#             assert checksum_value == expected
#
#         finally:
#             os.unlink(temp_path)
#
#     def test_compute_filesystem_checksum_crc32(self):
#         """Test filesystem checksum computation with crc32."""
#         backend = _ChecksumBackend()
#
#         with tempfile.NamedTemporaryFile(mode="w", delete=False) as f:
#             f.write("test data")
#             temp_path = f.name
#
#         try:
#             checksum_value, checksum_alg = backend._compute_filesystem_checksum(
#                 temp_path, "crc32"
#             )
#
#             assert isinstance(checksum_value, str)
#             assert checksum_alg == "crc32"
#             assert len(checksum_value) == 8  # crc32 32-bit = 8 hex chars
#
#             expected = _HashUtils.crc32(b"test data")
#             assert checksum_value == expected
#
#         finally:
#             os.unlink(temp_path)
#
#     def test_compute_filesystem_checksum_file_not_found(self):
#         """Test filesystem checksum with non-existent file."""
#         backend = _ChecksumBackend()
#
#         with pytest.raises(FileNotFoundError):
#             backend._compute_filesystem_checksum("/nonexistent/file", "blake3")
#
#     def test_compute_filesystem_checksum_unsupported_algorithm(self):
#         """Test filesystem checksum with unsupported algorithm."""
#         backend = _ChecksumBackend()
#
#         with tempfile.NamedTemporaryFile() as f:
#             with pytest.raises(ValueError, match="Unsupported algorithm: md5"):
#                 backend._compute_filesystem_checksum(f.name, "md5")
#
#
# @mock_aws
# class TestS3ChecksumOptimization:
#     """Test S3 checksum optimization using existing CRC32.
#
#     Note: moto 5.x automatically computes CRC32 for all uploaded objects.
#     The optimization retrieves this auto-computed CRC32 from S3 metadata
#     rather than downloading the object to compute a hash locally.
#     """
#
#     def test_s3_crc32_optimization_success(self):
#         """Test S3 uses existing CRC32 when algorithm is None.
#
#         moto 5.x auto-computes CRC32 for uploaded objects and returns it
#         via head_object with ChecksumMode=ENABLED. The optimization picks
#         this up to avoid downloading the object.
#         """
#         # Setup mock S3
#         s3_client = boto3.client("s3", region_name="us-east-1")
#         s3_client.create_bucket(Bucket="test-bucket")
#
#         # Upload object without explicit checksum — moto 5.x auto-computes CRC32
#         test_content = b"hello world"
#         s3_client.put_object(
#             Bucket="test-bucket",
#             Key="test-file.txt",
#             Body=test_content,
#         )
#
#         backend = _ChecksumBackend()
#         checksum_value, checksum_alg = backend._compute_s3_checksum(
#             "s3://test-bucket/test-file.txt", None
#         )
#
#         # Should return CRC32 from S3 metadata (moto auto-computes this)
#         assert checksum_alg == "crc32"
#         # Verify it's a valid 8-char hex CRC32 value
#         assert len(checksum_value) == 8
#         # Verify it matches the CRC32 of the content
#         expected_crc32 = _HashUtils.crc32(test_content)
#         assert checksum_value == expected_crc32
#
#     def test_s3_explicit_algorithm_bypasses_optimization(self):
#         """Test explicit algorithm bypasses S3 CRC32 optimization."""
#         # Setup mock S3
#         s3_client = boto3.client("s3", region_name="us-east-1")
#         s3_client.create_bucket(Bucket="test-bucket")
#
#         test_content = b"hello world"
#         s3_client.put_object(
#             Bucket="test-bucket",
#             Key="test-file.txt",
#             Body=test_content,
#         )
#
#         backend = _ChecksumBackend()
#         checksum_value, checksum_alg = backend._compute_s3_checksum(
#             "s3://test-bucket/test-file.txt", "blake3"
#         )
#
#         # Should compute blake3, not use S3 CRC32
#         assert checksum_alg == "blake3"
#         assert len(checksum_value) == 64
#         expected_blake3 = _HashUtils.blake3(test_content)
#         assert checksum_value == expected_blake3
#
#     def test_s3_fallback_when_no_crc32_metadata(self):
#         """Test fallback to download when no CRC32 in S3 metadata.
#
#         Simulates an S3 response without ChecksumCRC32 (e.g., older objects
#         or S3 implementations that don't provide checksum metadata).
#         Uses unittest.mock to patch head_object to return a response without
#         checksum data, since moto 5.x always provides CRC32 for all objects.
#         """
#         from unittest.mock import MagicMock, patch
#
#         # Setup mock S3 for get_object
#         s3_client = boto3.client("s3", region_name="us-east-1")
#         s3_client.create_bucket(Bucket="test-bucket")
#
#         test_content = b"test data"
#         s3_client.put_object(
#             Bucket="test-bucket", Key="test-file.txt", Body=test_content
#         )
#
#         backend = _ChecksumBackend()
#
#         # Patch head_object to simulate a response without CRC32 metadata
#         # (real S3 objects uploaded before checksum support was added won't have CRC32)
#         head_response_without_checksum = {
#             "ContentLength": len(test_content),
#             "ContentType": "binary/octet-stream",
#             "ETag": '"abc123"',
#         }
#
#         with patch("boto3.client") as mock_boto3_client:
#             mock_s3 = MagicMock()
#             mock_boto3_client.return_value = mock_s3
#             mock_s3.head_object.return_value = head_response_without_checksum
#             # Return actual content for get_object
#             mock_body = MagicMock()
#             mock_body.read.return_value = test_content
#             mock_s3.get_object.return_value = {"Body": mock_body}
#
#             checksum_value, checksum_alg = backend._compute_s3_checksum(
#                 "s3://test-bucket/test-file.txt", None
#             )
#
#         # Should fallback to blake3 computation
#         assert checksum_alg == "blake3"
#         expected_blake3 = _HashUtils.blake3(test_content)
#         assert checksum_value == expected_blake3
#
#     def test_s3_checksum_access_error_raises(self):
#         """Test S3 access errors propagate correctly."""
#         backend = _ChecksumBackend()
#
#         with pytest.raises(Exception):  # boto3 will raise various exceptions
#             backend._compute_s3_checksum(
#                 "s3://nonexistent-bucket/nonexistent-file.txt", "blake3"
#             )
#
#
# class TestGenerateForAssets:
#     """Test main generate_for_assets function."""
#
#     def test_generate_for_assets_filesystem_success(self):
#         """Test successful checksum generation for filesystem assets."""
#         # Create temporary test file
#         with tempfile.NamedTemporaryFile(mode="w", delete=False) as f:
#             f.write("test content")
#             temp_path = f.name
#
#         try:
#             assets = [
#                 DataAssetRequest(
#                     location_uri=temp_path,
#                     asset_type=AssetType.file,
#                     storage_platform=StoragePlatform.hpc,
#                 )
#             ]
#
#             result = checksums.generate_for_assets(assets, algorithm="blake3")
#
#             # Should return new list with checksums populated
#             assert len(result) == 1
#             assert result[0].checksum is not None
#             assert result[0].checksum_alg == "blake3"
#             assert len(result[0].checksum) == 64
#
#             # Original asset should be unchanged
#             assert assets[0].checksum is None
#             assert assets[0].checksum_alg is None
#
#         finally:
#             os.unlink(temp_path)
#
#     def test_generate_for_assets_skip_existing_checksums(self):
#         """Test skips assets that already have checksums."""
#         assets = [
#             DataAssetRequest(
#                 location_uri="/hpc/existing.txt",
#                 asset_type=AssetType.file,
#                 storage_platform=StoragePlatform.hpc,
#                 checksum="existing123",
#                 checksum_alg="blake3",
#             )
#         ]
#
#         result = checksums.generate_for_assets(assets, algorithm="crc32")
#
#         # Should preserve existing checksum
#         assert result[0].checksum == "existing123"
#         assert result[0].checksum_alg == "blake3"
#
#     def test_generate_for_assets_unsupported_platform_warning(self):
#         """Test warning for unsupported platform."""
#         assets = [
#             DataAssetRequest(
#                 location_uri="http://example.com/file.txt", asset_type=AssetType.file
#             )
#         ]
#
#         with warnings.catch_warnings(record=True) as w:
#             warnings.simplefilter("always")
#             result = checksums.generate_for_assets(assets, algorithm="blake3")
#
#             # Should issue warning
#             assert len(w) == 1
#             assert issubclass(w[0].category, ChecksumWarning)
#             assert "not supported" in str(w[0].message)
#
#             # Should return original asset unchanged
#             assert result[0].checksum is None
#             assert result[0].checksum_alg is None
#
#     def test_generate_for_assets_file_error_warning(self):
#         """Test warning for file access errors."""
#         assets = [
#             DataAssetRequest(
#                 location_uri="/nonexistent/file.txt",
#                 asset_type=AssetType.file,
#                 storage_platform=StoragePlatform.hpc,
#             )
#         ]
#
#         with warnings.catch_warnings(record=True) as w:
#             warnings.simplefilter("always")
#             result = checksums.generate_for_assets(assets, algorithm="blake3")
#
#             # Should issue warning about access failure
#             assert len(w) == 1
#             assert issubclass(w[0].category, ChecksumWarning)
#
#             # Should return original asset unchanged
#             assert result[0].checksum is None
#
#     @mock_aws
#     def test_generate_for_assets_s3_success(self):
#         """Test successful S3 checksum generation."""
#         # Setup mock S3
#         s3_client = boto3.client("s3", region_name="us-east-1")
#         s3_client.create_bucket(Bucket="test-bucket")
#         s3_client.put_object(
#             Bucket="test-bucket", Key="test.txt", Body=b"s3 test content"
#         )
#
#         assets = [
#             DataAssetRequest(
#                 location_uri="s3://test-bucket/test.txt", asset_type=AssetType.file
#             )
#         ]
#
#         result = checksums.generate_for_assets(assets, algorithm="blake3")
#
#         assert len(result) == 1
#         assert result[0].checksum is not None
#         assert result[0].checksum_alg == "blake3"
#         assert len(result[0].checksum) == 64
#
#     def test_generate_for_assets_default_algorithm(self):
#         """Test default algorithm selection."""
#         with tempfile.NamedTemporaryFile(mode="w", delete=False) as f:
#             f.write("test")
#             temp_path = f.name
#
#         try:
#             assets = [
#                 DataAssetRequest(
#                     location_uri=temp_path,
#                     asset_type=AssetType.file,
#                     storage_platform=StoragePlatform.hpc,
#                 )
#             ]
#
#             # No algorithm specified - should default to blake3
#             result = checksums.generate_for_assets(assets)
#
#             assert result[0].checksum_alg == "blake3"
#
#         finally:
#             os.unlink(temp_path)
