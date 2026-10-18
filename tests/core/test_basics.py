from pathlib import Path

import pytest

from smol.core import Result, format_size, output_path, parse_size


class TestParseSize:
    def test_parse_size_bytes_integer(self):
        assert parse_size(250000) == 250000
        assert parse_size("250000") == 250000
        assert parse_size("250000 B") == 250000
        assert parse_size("250000b") == 250000

    def test_parse_size_kb_and_mb(self):
        # 1 KB = 1000 bytes
        assert parse_size("100KB") == 100000
        assert parse_size("100 kb") == 100000
        assert parse_size("100k") == 100000
        assert parse_size("1.5MB") == 1500000
        assert parse_size("1.5 mb") == 1500000
        assert parse_size("1.5M") == 1500000
        assert parse_size("2 MB") == 2000000

    def test_parse_size_gb(self):
        assert parse_size("1GB") == 1000000000
        assert parse_size("0.5 GB") == 500000000

    def test_parse_size_invalid_inputs(self):
        with pytest.raises(ValueError, match="positive size"):
            parse_size("")
        with pytest.raises(ValueError, match="positive size"):
            parse_size("0")
        with pytest.raises(ValueError, match="positive size"):
            parse_size("-100KB")
        with pytest.raises(ValueError, match="positive size"):
            parse_size(0)
        with pytest.raises(ValueError, match="positive size"):
            parse_size(-50)
        with pytest.raises(ValueError, match="Cannot parse size"):
            parse_size("invalid")
        with pytest.raises(ValueError, match="Unknown size unit"):
            parse_size("100TB")
        with pytest.raises(TypeError):
            parse_size(None)  # type: ignore


class TestFormatSize:
    def test_format_size_clean(self):
        assert format_size(100000) == "100KB"
        assert format_size(1500000) == "1.5MB"
        assert format_size(2000000) == "2MB"
        assert format_size(500) == "500B"


class TestResultDataclass:
    def test_result_fields_and_defaults(self):
        res = Result(
            ok=True,
            output_path=Path("out.jpg"),
            original_bytes=1000000,
            final_bytes=95000,
            width=800,
            height=600,
            quality=82,
            steps=3,
            warning=None,
            error=None,
        )
        assert res.ok is True
        assert res.output_path == Path("out.jpg")
        assert res.original_bytes == 1000000
        assert res.final_bytes == 95000
        assert res.width == 800
        assert res.height == 600
        assert res.quality == 82
        assert res.steps == 3
        assert res.warning is None
        assert res.error is None

    def test_result_failure_defaults(self):
        res = Result(
            ok=False,
            original_bytes=1000000,
            error="Incompressible file: smallest possible size is 120KB",
        )
        assert res.ok is False
        assert res.output_path is None
        assert res.final_bytes == 0
        assert res.width is None
        assert res.height is None
        assert res.quality is None
        assert res.steps == 0
        assert res.warning is None
        assert "smallest possible size" in res.error


class TestOutputPath:
    def test_standard_output_path(self, tmp_path: Path):
        src = tmp_path / "photo.jpg"
        src.touch()

        out = output_path(src, 100000)
        assert out == tmp_path / "photo_100KB.jpg"
        assert not out.exists()

    def test_output_path_string_target(self, tmp_path: Path):
        src = tmp_path / "photo.jpg"
        src.touch()

        out = output_path(src, "100KB")
        assert out == tmp_path / "photo_100KB.jpg"

    def test_output_path_collision_resolution(self, tmp_path: Path):
        src = tmp_path / "photo.jpg"
        src.touch()

        # First output path
        out1 = output_path(src, 100000)
        assert out1 == tmp_path / "photo_100KB.jpg"
        out1.touch()

        # Second output path should increment with -1
        out2 = output_path(src, 100000)
        assert out2 == tmp_path / "photo_100KB-1.jpg"
        out2.touch()

        # Third output path should increment with -2
        out3 = output_path(src, 100000)
        assert out3 == tmp_path / "photo_100KB-2.jpg"

    def test_output_path_weird_filenames(self, tmp_path: Path):
        # 1. Spaces in filename
        src_spaces = tmp_path / "summer vacation photo.png"
        src_spaces.touch()
        out_spaces = output_path(src_spaces, 1500000)
        assert out_spaces == tmp_path / "summer vacation photo_1.5MB.png"

        # 2. Unicode filename
        src_unicode = tmp_path / "📸_東京.webp"
        src_unicode.touch()
        out_unicode = output_path(src_unicode, 50000)
        assert out_unicode == tmp_path / "📸_東京_50KB.webp"

        # 3. Leading dash
        src_dash = tmp_path / "-leading_dash.jpg"
        src_dash.touch()
        out_dash = output_path(src_dash, 20000)
        assert out_dash == tmp_path / "-leading_dash_20KB.jpg"

        # 4. No extension
        src_no_ext = tmp_path / "data_blob"
        src_no_ext.touch()
        out_no_ext = output_path(src_no_ext, 100000)
        assert out_no_ext == tmp_path / "data_blob_100KB"

        # Collision with no extension
        out_no_ext.touch()
        out_no_ext_coll = output_path(src_no_ext, 100000)
        assert out_no_ext_coll == tmp_path / "data_blob_100KB-1"

        # 5. Uppercase extension preserved
        src_upper = tmp_path / "SCAN.JPEG"
        src_upper.touch()
        out_upper = output_path(src_upper, 500000)
        assert out_upper == tmp_path / "SCAN_500KB.JPEG"
