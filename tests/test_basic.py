import smol


def test_smol_importable():
    """Verify the smol package can be imported."""
    assert smol is not None


def test_cli_version():
    """Verify `smol --version` runs without error."""
    import subprocess  # nosec
    result = subprocess.run(
        ["smol", "--version"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0
    assert "0.1.0" in result.stdout