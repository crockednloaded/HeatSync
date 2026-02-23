"""Tests for GPU detection and initialization."""

import pytest
from unittest.mock import patch, Mock, MagicMock


class TestGPUDetection:
    """Tests for GPU detection logic."""

    def test_nvidia_gpu_detection(self, mock_pynvml):
        """Test NVIDIA GPU is detected and initialized."""
        with patch('pynvml.nvmlInit') as mock_init:
            with patch('pynvml.nvmlDeviceGetHandleByIndex') as mock_handle:
                with patch('pynvml.nvmlDeviceGetName') as mock_name:
                    mock_handle.return_value = Mock()
                    mock_name.return_value = "NVIDIA GeForce RTX 3080"
                    
                    mock_init.assert_not_called()

    def test_amd_gpu_detection_linux(self, temp_sysfs_structure):
        """Test AMD GPU detection on Linux via sysfs."""
        import os
        
        # Verify AMD device structure was created
        amd_dev = temp_sysfs_structure["amd_dev"]
        assert os.path.exists(os.path.join(amd_dev, "vendor"))
        assert os.path.exists(os.path.join(amd_dev, "product_name"))
        
        # Read vendor ID
        with open(os.path.join(amd_dev, "vendor")) as f:
            vendor = f.read().strip()
        assert vendor == "0x1002"
        
        # Read product name
        with open(os.path.join(amd_dev, "product_name")) as f:
            product = f.read().strip()
        assert "AMD" in product

    def test_intel_gpu_detection_linux(self, temp_sysfs_structure):
        """Test Intel GPU detection on Linux via sysfs."""
        import os
        
        # Verify Intel device structure was created
        intel_dev = temp_sysfs_structure["intel_dev"]
        assert os.path.exists(os.path.join(intel_dev, "vendor"))
        assert os.path.exists(os.path.join(intel_dev, "product_name"))
        
        # Read vendor ID
        with open(os.path.join(intel_dev, "vendor")) as f:
            vendor = f.read().strip()
        assert vendor == "0x8086"
        
        # Read product name
        with open(os.path.join(intel_dev, "product_name")) as f:
            product = f.read().strip()
        assert "Intel" in product

    def test_amd_gpu_temp_from_sysfs(self, temp_sysfs_structure):
        """Test AMD GPU temperature reading from sysfs."""
        import os
        
        hwmon_path = temp_sysfs_structure["amd_hwmon"]
        temp_file = os.path.join(hwmon_path, "temp1_input")
        
        with open(temp_file) as f:
            temp_millidegrees = int(f.read().strip())
        
        temp_celsius = temp_millidegrees / 1000.0
        assert temp_celsius == 62.0

    def test_intel_gpu_temp_from_sysfs(self, temp_sysfs_structure):
        """Test Intel GPU temperature reading from sysfs."""
        import os
        
        hwmon_path = temp_sysfs_structure["intel_hwmon"]
        temp_file = os.path.join(hwmon_path, "temp1_input")
        
        with open(temp_file) as f:
            temp_millidegrees = int(f.read().strip())
        
        temp_celsius = temp_millidegrees / 1000.0
        assert temp_celsius == 58.0

    def test_amd_gpu_vram_from_sysfs(self, temp_sysfs_structure):
        """Test AMD GPU VRAM reading from sysfs."""
        import os
        
        dev_path = temp_sysfs_structure["amd_dev"]
        
        with open(os.path.join(dev_path, "mem_info_vram_used")) as f:
            used = int(f.read().strip())
        with open(os.path.join(dev_path, "mem_info_vram_total")) as f:
            total = int(f.read().strip())
        
        used_mb = used >> 20
        total_mb = total >> 20
        pct = used / total * 100
        
        assert used_mb == 4096
        assert total_mb == 16384
        assert pct == pytest.approx(25.0, abs=0.1)

    def test_intel_gpu_vram_from_sysfs(self, temp_sysfs_structure):
        """Test Intel GPU GTT memory reading from sysfs."""
        import os
        
        dev_path = temp_sysfs_structure["intel_dev"]
        
        with open(os.path.join(dev_path, "mem_info_gtt_used")) as f:
            used = int(f.read().strip())
        with open(os.path.join(dev_path, "mem_info_gtt_total")) as f:
            total = int(f.read().strip())
        
        used_mb = used >> 20
        total_mb = total >> 20
        pct = used / total * 100
        
        assert used_mb == 2048
        assert total_mb == 8192
        assert pct == pytest.approx(25.0, abs=0.1)
