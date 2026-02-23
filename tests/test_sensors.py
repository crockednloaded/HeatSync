"""Unit tests for sensor functions."""

import sys
import os
import pytest
from unittest.mock import Mock, patch, MagicMock

# Import sensor functions (we'll use importlib to reload with mocks)


class TestCPUSensors:
    """Tests for CPU sensor functions."""

    def test_cpu_usage_returns_percentage(self, mock_psutil):
        """Test that CPU usage returns a valid percentage."""
        with patch('psutil.cpu_percent', return_value=45.0):
            from HeatSync import s_cpu_usage
            result = s_cpu_usage()
            assert 0 <= result <= 100
            assert result == 45.0

    def test_cpu_usage_zero(self):
        """Test CPU usage at zero percent."""
        with patch('psutil.cpu_percent', return_value=0.0):
            from HeatSync import s_cpu_usage
            result = s_cpu_usage()
            assert result == 0.0

    def test_cpu_usage_max(self):
        """Test CPU usage at 100 percent."""
        with patch('psutil.cpu_percent', return_value=100.0):
            from HeatSync import s_cpu_usage
            result = s_cpu_usage()
            assert result == 100.0

    def test_cpu_temp_coretemp_linux(self, mock_psutil):
        """Test CPU temperature detection on Linux with coretemp."""
        mock_temps = {
            "coretemp": [Mock(label="Package id 0", current=65.5)]
        }
        with patch('psutil.sensors_temperatures', return_value=mock_temps):
            with patch('sys.platform', 'linux'):
                from HeatSync import s_cpu_temp
                result = s_cpu_temp()
                assert result == 65.5

    def test_cpu_temp_windows_returns_zero_without_wmi(self):
        """Test that CPU temp returns 0 on Windows without WMI."""
        with patch('sys.platform', 'win32'):
            # Mock WMI not being available
            with patch.dict(sys.modules, {'wmi': None}):
                from HeatSync import s_cpu_temp
                result = s_cpu_temp()
                assert result == 0.0

    def test_cpu_freq_returns_ghz(self):
        """Test CPU frequency returns in GHz."""
        with patch('psutil.cpu_freq', return_value=Mock(current=3600.0)):
            from HeatSync import s_cpu_freq
            result = s_cpu_freq()
            assert result == 3.6
            assert result > 0

    def test_cpu_freq_none_returns_zero(self):
        """Test CPU frequency returns 0 when unavailable."""
        with patch('psutil.cpu_freq', return_value=None):
            from HeatSync import s_cpu_freq
            result = s_cpu_freq()
            assert result == 0.0


class TestMemorySensors:
    """Tests for memory sensor functions."""

    def test_ram_usage_valid_values(self, mock_psutil):
        """Test RAM usage returns valid (used, total, percent)."""
        mock_psutil.virtual_memory.return_value = Mock(
            used=8589934592,      # 8 GB
            total=17179869184,    # 16 GB
            percent=50.0
        )
        with patch('psutil.virtual_memory', return_value=mock_psutil.virtual_memory()):
            from HeatSync import s_ram
            used, total, pct = s_ram()
            assert used == pytest.approx(8.0, abs=0.1)
            assert total == pytest.approx(16.0, abs=0.1)
            assert pct == 50.0

    def test_disk_usage_valid_values(self):
        """Test disk usage returns valid (used, total, percent)."""
        with patch('psutil.disk_usage') as mock_disk:
            mock_disk.return_value = Mock(
                used=536870912000,    # 500 GB
                total=1099511627776,  # 1 TB
                percent=48.8
            )
            from HeatSync import s_disk
            used, total, pct = s_disk()
            assert used == pytest.approx(500.0, abs=1.0)
            assert total == pytest.approx(1000.0, abs=1.0)
            assert pct == pytest.approx(48.8, abs=0.1)


class TestGPUSensors:
    """Tests for GPU sensor functions."""

    def test_gpu_usage_nvidia(self):
        """Test NVIDIA GPU usage detection."""
        with patch('HeatSync.GPU_HANDLE', Mock()):
            with patch('pynvml.nvmlDeviceGetUtilizationRates') as mock_util:
                mock_util.return_value = Mock(gpu=72.0)
                from HeatSync import s_gpu_usage
                result = s_gpu_usage()
                assert result == 72.0

    def test_gpu_usage_no_gpu(self):
        """Test GPU usage returns 0 when no GPU found."""
        with patch('HeatSync.GPU_HANDLE', None):
            with patch('HeatSync._AMD_DEV', None):
                with patch('HeatSync._INTEL_DEV', None):
                    from HeatSync import s_gpu_usage
                    result = s_gpu_usage()
                    assert result == 0.0

    def test_gpu_temp_nvidia(self):
        """Test NVIDIA GPU temperature detection."""
        with patch('HeatSync.GPU_HANDLE', Mock()):
            with patch('pynvml.nvmlDeviceGetTemperature') as mock_temp:
                mock_temp.return_value = 68.0
                from HeatSync import s_gpu_temp
                result = s_gpu_temp()
                assert result == 68.0

    def test_gpu_temp_no_gpu(self):
        """Test GPU temp returns 0 when no GPU found."""
        with patch('HeatSync.GPU_HANDLE', None):
            with patch('HeatSync._AMD_DEV', None):
                with patch('HeatSync._INTEL_DEV', None):
                    from HeatSync import s_gpu_temp
                    result = s_gpu_temp()
                    assert result == 0.0

    def test_gpu_vram_nvidia(self):
        """Test NVIDIA GPU VRAM detection."""
        with patch('HeatSync.GPU_HANDLE', Mock()):
            gpu_mem = Mock()
            gpu_mem.used = 8589934592      # 8 GB
            gpu_mem.total = 10737418240    # 10 GB
            with patch('pynvml.nvmlDeviceGetMemoryInfo', return_value=gpu_mem):
                from HeatSync import s_gpu_vram
                used, total, pct = s_gpu_vram()
                assert used == 8192
                assert total == 10240
                assert pct == pytest.approx(80.0, abs=0.1)

    def test_gpu_vram_no_gpu(self):
        """Test GPU VRAM returns (0, 0, 0) when no GPU found."""
        with patch('HeatSync.GPU_HANDLE', None):
            with patch('HeatSync._AMD_DEV', None):
                with patch('HeatSync._INTEL_DEV', None):
                    from HeatSync import s_gpu_vram
                    used, total, pct = s_gpu_vram()
                    assert used == 0
                    assert total == 0
                    assert pct == 0
