"""Pytest configuration and shared fixtures."""

import os
import sys
import pytest
from unittest.mock import Mock, patch, MagicMock

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Set offscreen Qt platform before any import so PyQt6 works headless in CI
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

# Pre-import HeatSync so it is cached in sys.modules before any test patches
# sys.platform. Without this, a test that patches sys.platform='win32' and then
# does "from HeatSync import X" triggers a fresh import of HeatSync+psutil under
# the patched platform, causing psutil to raise NotImplementedError.
try:
    import HeatSync  # noqa: E402, F401
except Exception as _hs_err:
    print(f"WARNING: could not pre-import HeatSync: {_hs_err}")  # shown in CI logs


@pytest.fixture
def mock_psutil():
    """Mock psutil module for sensor tests."""
    mock = MagicMock()
    
    # Mock CPU metrics
    mock.cpu_percent.return_value = 45.0
    mock.cpu_freq.return_value = Mock(current=3600.0)
    mock.cpu_count.return_value = 8
    mock.cpu_count.side_effect = lambda logical=False: 4 if not logical else 8
    
    # Mock memory metrics
    mock.virtual_memory.return_value = Mock(
        used=8589934592,      # 8 GB
        total=17179869184,    # 16 GB
        percent=50.0
    )
    
    # Mock disk metrics
    mock.disk_usage.return_value = Mock(
        used=536870912000,    # 500 GB
        total=1099511627776,  # 1 TB
        percent=48.8
    )
    
    # Mock temperature sensors
    mock.sensors_temperatures.return_value = {
        "coretemp": [Mock(label="Package id 0", current=65.5)],
        "amdgpu": [Mock(label="amdgpu junction", current=62.0)],
    }
    
    return mock


@pytest.fixture
def mock_pynvml():
    """Mock pynvml module for NVIDIA GPU tests."""
    mock = MagicMock()
    mock.nvmlInit.return_value = None
    mock.nvmlDeviceGetHandleByIndex.return_value = Mock()
    mock.nvmlDeviceGetName.return_value = "NVIDIA GeForce RTX 3080"
    mock.nvmlDeviceGetUtilizationRates.return_value = Mock(gpu=72.0)
    mock.nvmlDeviceGetTemperature.return_value = 68.0
    
    gpu_mem = Mock()
    gpu_mem.used = 8589934592      # 8 GB
    gpu_mem.total = 10737418240    # 10 GB
    mock.nvmlDeviceGetMemoryInfo.return_value = gpu_mem
    
    mock.NVML_TEMPERATURE_GPU = 0
    
    return mock


@pytest.fixture
def temp_sysfs_structure(tmp_path):
    """Create a temporary sysfs structure for GPU testing."""
    # AMD GPU structure
    amd_dev = tmp_path / "sys" / "class" / "drm" / "card0" / "device"
    amd_hwmon = amd_dev / "hwmon" / "hwmon0"
    amd_hwmon.mkdir(parents=True)
    
    (amd_dev / "vendor").write_text("0x1002")
    (amd_dev / "product_name").write_text("AMD Radeon RX 6800 XT")
    (amd_dev / "gpu_busy_percent").write_text("55")
    (amd_hwmon / "temp1_input").write_text("62000")
    (amd_dev / "mem_info_vram_used").write_text("4294967296")
    (amd_dev / "mem_info_vram_total").write_text("17179869184")
    
    # Intel GPU structure
    intel_dev = tmp_path / "sys" / "class" / "drm" / "card1" / "device"
    intel_hwmon = intel_dev / "hwmon" / "hwmon1"
    intel_hwmon.mkdir(parents=True)
    
    (intel_dev / "vendor").write_text("0x8086")
    (intel_dev / "product_name").write_text("Intel Arc A770")
    (intel_hwmon / "temp1_input").write_text("58000")
    (intel_dev / "mem_info_gtt_used").write_text("2147483648")
    (intel_dev / "mem_info_gtt_total").write_text("8589934592")
    
    return {
        "amd_dev": str(amd_dev),
        "amd_hwmon": str(amd_hwmon),
        "intel_dev": str(intel_dev),
        "intel_hwmon": str(intel_hwmon),
    }

