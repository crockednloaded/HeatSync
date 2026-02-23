"""Integration tests for HeatSync application."""

import sys
import pytest
from unittest.mock import patch, Mock, MagicMock
from PyQt6.QtWidgets import QApplication


class TestApplicationInitialization:
    """Tests for application startup and initialization."""

    @pytest.fixture
    def qapp(self):
        """Create QApplication instance for tests."""
        app = QApplication.instance()
        if app is None:
            app = QApplication(sys.argv)
        yield app

    def test_app_can_be_created(self, qapp):
        """Test that QApplication can be instantiated."""
        assert qapp is not None
        assert isinstance(qapp, QApplication)

    def test_main_window_imports(self):
        """Test that MainWindow can be imported."""
        from HeatSync import MainWindow
        assert MainWindow is not None

    @patch('sys.platform', 'linux')
    def test_sensor_functions_callable(self):
        """Test that all sensor functions are callable."""
        from HeatSync import (
            s_cpu_usage, s_cpu_temp, s_cpu_freq,
            s_gpu_usage, s_gpu_temp, s_gpu_vram,
            s_ram, s_disk
        )
        
        # All should be callable
        assert callable(s_cpu_usage)
        assert callable(s_cpu_temp)
        assert callable(s_cpu_freq)
        assert callable(s_gpu_usage)
        assert callable(s_gpu_temp)
        assert callable(s_gpu_vram)
        assert callable(s_ram)
        assert callable(s_disk)

    def test_sensor_function_returns_valid_types(self):
        """Test that sensor functions return expected types."""
        from HeatSync import s_cpu_usage, s_ram, s_disk
        
        with patch('psutil.cpu_percent', return_value=45.0):
            assert isinstance(s_cpu_usage(), float)
        
        with patch('psutil.virtual_memory') as mock_mem:
            mock_mem.return_value = Mock(used=1e9, total=1e10, percent=10.0)
            used, total, pct = s_ram()
            assert isinstance(used, float)
            assert isinstance(total, float)
            assert isinstance(pct, float)
        
        with patch('psutil.disk_usage') as mock_disk:
            mock_disk.return_value = Mock(used=1e11, total=1e12, percent=10.0)
            used, total, pct = s_disk()
            assert isinstance(used, float)
            assert isinstance(total, float)
            assert isinstance(pct, float)


class TestUIComponents:
    """Tests for UI component creation and functionality."""

    @pytest.fixture
    def qapp(self):
        """Create QApplication instance for tests."""
        app = QApplication.instance()
        if app is None:
            app = QApplication(sys.argv)
        yield app

    def test_arc_gauge_creation(self, qapp):
        """Test that ArcGauge widget can be created."""
        from HeatSync import ArcGauge
        gauge = ArcGauge("Test", "%", lo=0, hi=100, color="#00ccdd")
        assert gauge is not None
        assert gauge.width() > 0
        assert gauge.height() > 0

    def test_arc_gauge_value_setting(self, qapp):
        """Test that ArcGauge values can be set."""
        from HeatSync import ArcGauge
        gauge = ArcGauge("CPU", "%", lo=0, hi=100)
        gauge.set_value(50)
        assert gauge._target == 50.0

    def test_sparkline_creation(self, qapp):
        """Test that Sparkline widget can be created."""
        from HeatSync import Sparkline
        sparkline = Sparkline(color="#00ccdd", max_pts=90)
        assert sparkline is not None
        assert len(sparkline._hist) == 0

    def test_sparkline_data_push(self, qapp):
        """Test that Sparkline can accept data points."""
        from HeatSync import Sparkline
        sparkline = Sparkline()
        sparkline.push(50.0)
        sparkline.push(55.0)
        sparkline.push(60.0)
        assert len(sparkline._hist) == 3
        assert list(sparkline._hist) == [50.0, 55.0, 60.0]

    def test_sparkline_max_points(self, qapp):
        """Test that Sparkline respects max_pts limit."""
        from HeatSync import Sparkline
        sparkline = Sparkline(max_pts=5)
        for i in range(10):
            sparkline.push(float(i))
        assert len(sparkline._hist) == 5
        assert list(sparkline._hist) == [5.0, 6.0, 7.0, 8.0, 9.0]

    def test_monitor_card_creation(self, qapp):
        """Test that MonitorCard widget can be created."""
        from HeatSync import MonitorCard
        card = MonitorCard("CPU USAGE", "%", lo=0, hi=100, color="#00ccdd")
        assert card is not None
        assert card.gauge is not None
        assert card.spark is not None

    def test_monitor_card_push_value(self, qapp):
        """Test that MonitorCard can receive values."""
        from HeatSync import MonitorCard
        card = MonitorCard("CPU USAGE", "%")
        card.push(45.5)
        assert card.gauge._target == 45.5
        assert len(card.spark._hist) == 1

    def test_status_bar_creation(self, qapp):
        """Test that StatusBar widget can be created."""
        from HeatSync import StatusBar
        with patch('psutil.virtual_memory') as mock_mem:
            with patch('psutil.disk_usage') as mock_disk:
                with patch('HeatSync.s_ram') as mock_s_ram:
                    with patch('HeatSync.s_gpu_vram') as mock_s_gpu_vram:
                        with patch('HeatSync.s_cpu_freq') as mock_s_cpu_freq:
                            mock_mem.return_value = Mock(used=1e9, total=1e10, percent=10.0)
                            mock_disk.return_value = Mock(used=1e11, total=1e12, percent=10.0)
                            mock_s_ram.return_value = (8.0, 16.0, 50.0)
                            mock_s_gpu_vram.return_value = (0, 0, 0)
                            mock_s_cpu_freq.return_value = 3.6
                            
                            sb = StatusBar()
                            assert sb is not None
                            sb.refresh()


class TestSensorRanges:
    """Tests to ensure sensor values stay within expected ranges."""

    def test_cpu_usage_range(self):
        """Test CPU usage is always 0-100%."""
        from HeatSync import s_cpu_usage
        for test_val in [0, 25, 50, 75, 100]:
            with patch('psutil.cpu_percent', return_value=float(test_val)):
                result = s_cpu_usage()
                assert 0 <= result <= 100

    def test_cpu_temp_reasonable_range(self):
        """Test CPU temperature is in reasonable range."""
        from HeatSync import s_cpu_temp
        with patch('psutil.sensors_temperatures') as mock_temp:
            mock_temp.return_value = {
                "coretemp": [Mock(label="Package id 0", current=75.0)]
            }
            result = s_cpu_temp()
            assert 0 <= result <= 150  # Reasonable CPU temp range

    def test_ram_percent_valid(self):
        """Test RAM percentage is 0-100%."""
        from HeatSync import s_ram
        with patch('psutil.virtual_memory') as mock_mem:
            for pct in [0, 25, 50, 75, 100]:
                mock_mem.return_value = Mock(
                    used=pct * 1e9,
                    total=100 * 1e9,
                    percent=float(pct)
                )
                used, total, result_pct = s_ram()
                assert 0 <= result_pct <= 100

    def test_disk_percent_valid(self):
        """Test disk percentage is 0-100%."""
        from HeatSync import s_disk
        with patch('psutil.disk_usage') as mock_disk:
            for pct in [0, 25, 50, 75, 100]:
                mock_disk.return_value = Mock(
                    used=pct * 1e11,
                    total=100 * 1e11,
                    percent=float(pct)
                )
                used, total, result_pct = s_disk()
                assert 0 <= result_pct <= 100
