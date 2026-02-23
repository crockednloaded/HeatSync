# HeatSync Test Suite

Comprehensive unit and integration tests for the HeatSync system monitor application.

## Test Structure

### Unit Tests

- **`test_sensors.py`** — Tests for all sensor functions (CPU, GPU, memory, disk)
  - CPU usage, temperature, and frequency
  - GPU usage, temperature, and VRAM (NVIDIA, AMD, Intel)
  - RAM and disk usage metrics

- **`test_gpu_detection.py`** — Tests for GPU detection logic
  - NVIDIA GPU initialization
  - AMD GPU sysfs reading
  - Intel GPU sysfs reading
  - Temperature and VRAM extraction from sysfs

- **`test_cpu_detection.py`** — Tests for CPU detection
  - CPU model name detection (Windows/Linux)
  - Core and logical core count
  - CPU frequency detection

### Integration Tests

- **`test_integration.py`** — End-to-end application tests
  - Application initialization and QApplication creation
  - UI component creation (ArcGauge, Sparkline, MonitorCard, StatusBar)
  - Data flow through widgets
  - Value range validation
  - Sensor return type validation

## Running Tests

### Run all tests
```bash
pytest
```

### Run with coverage report
```bash
pytest --cov=. --cov-report=html
```

### Run only unit tests
```bash
pytest tests/test_sensors.py tests/test_gpu_detection.py tests/test_cpu_detection.py
```

### Run only integration tests
```bash
pytest tests/test_integration.py
```

### Run with verbose output
```bash
pytest -v
```

### Run a specific test
```bash
pytest tests/test_sensors.py::TestCPUSensors::test_cpu_usage_returns_percentage -v
```

## Test Setup

### Fixtures (conftest.py)

- **`mock_psutil`** — Mocks psutil module for sensor testing
- **`mock_pynvml`** — Mocks pynvml module for NVIDIA GPU testing
- **`temp_sysfs_structure`** — Creates temporary sysfs structure for AMD/Intel GPU testing
- **`qapp`** — PyQt6 QApplication instance

## Mocking Strategy

Tests use `unittest.mock` to:
- Mock system calls and hardware APIs
- Isolate sensor functions for deterministic testing
- Simulate different hardware configurations (NVIDIA, AMD, Intel GPUs)
- Create temporary sysfs structures for Linux GPU device testing

## Coverage Goals

- **Sensor Functions**: 95%+ coverage
  - All sensor reading paths tested
  - Error handling verified
  - Edge cases covered

- **UI Components**: 90%+ coverage
  - Widget creation and initialization
  - Value setting and updates
  - Data validation

- **GPU Detection**: 85%+ coverage
  - All GPU vendor detection paths
  - sysfs reading and parsing
  - Fallback mechanisms

## CI/CD Integration

Tests can be integrated into GitHub Actions:

```yaml
- name: Run tests
  run: |
    pip install -r requirements.txt
    pytest --cov=. --cov-report=xml

- name: Upload coverage
  uses: codecov/codecov-action@v3
  with:
    files: ./coverage.xml
```

## Platform-Specific Testing

- **Linux**: Full sysfs GPU detection testing
- **Windows**: WMI CPU temperature detection (when available)
- **All Platforms**: Sensor function mocking and type validation

## Known Limitations

- PyQt6 UI rendering tests require display (X11/Wayland/Windows)
- Some sensor values require hardware-specific drivers
- CI/CD runners may have limited hardware support
- NVIDIA/AMD GPU tests rely on driver availability on test system
