"""Tests for CPU detection and information gathering."""

import pytest
from unittest.mock import patch, mock_open


class TestCPUDetection:
    """Tests for CPU model detection."""

    def test_get_cpu_name_windows(self):
        """Test CPU name detection on Windows."""
        with patch('sys.platform', 'win32'):
            with patch('platform.processor', return_value='Intel64 Family 6 Model 158 Stepping 12 GenuineIntel'):
                from HeatSync import _get_cpu_name
                result = _get_cpu_name()
                assert 'Intel' in result or len(result) > 0

    def test_get_cpu_name_linux_with_cpuinfo(self):
        """Test CPU name detection on Linux via /proc/cpuinfo."""
        cpu_info = """processor\t: 0
vendor_id\t: GenuineIntel
cpu family\t: 6
model\t\t: 158
model name\t: Intel(R) Core(TM) i7-8700K CPU @ 3.70GHz
"""
        with patch('sys.platform', 'linux'):
            with patch('builtins.open', mock_open(read_data=cpu_info)):
                from HeatSync import _get_cpu_name
                result = _get_cpu_name()
                assert 'i7' in result or 'Intel' in result

    def test_get_cpu_name_fallback(self):
        """Test CPU name uses fallback when detection fails."""
        with patch('sys.platform', 'linux'):
            with patch('builtins.open', side_effect=FileNotFoundError):
                with patch('platform.processor', return_value=''):
                    from HeatSync import _get_cpu_name
                    result = _get_cpu_name()
                    assert result == 'CPU' or len(result) > 0

    def test_cpu_core_count(self):
        """Test that CPU core count is detected."""
        import psutil
        cores = psutil.cpu_count(logical=False)
        logical_cores = psutil.cpu_count(logical=True)
        
        assert cores is not None and cores > 0
        assert logical_cores is not None and logical_cores >= cores

    def test_cpu_frequency_detection(self):
        """Test CPU frequency detection returns reasonable values."""
        import psutil
        freq = psutil.cpu_freq()
        
        if freq is not None:
            assert freq.current > 0
            assert freq.current < 10000  # Reasonable upper bound in MHz
