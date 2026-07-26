"""Regression tests for the detailed hardware job taxonomy."""

from src import config
from src.filters import classify_category


def category(title: str) -> str | None:
    return classify_category(title, config.filters()["categories"])


def test_taxonomy_overlay_is_loaded() -> None:
    filters = config.filters()
    categories = filters["categories"]

    assert len(categories) >= 17
    assert "pcb_board_design" in categories
    assert "embedded_firmware" in categories
    assert "rf_wireless" in categories
    assert "medtech_hardware" in categories
    assert "power_electronics" in categories
    assert filters["location"]["require_us"] is True


def test_pcb_beats_general_hardware() -> None:
    assert category("Electrical Hardware PCB Design Intern") == "pcb_board_design"


def test_analog_mixed_signal_category() -> None:
    assert category("Analog Mixed Signal Design Intern") == "analog_mixed_signal"


def test_fpga_is_distinct_from_asic() -> None:
    assert category("FPGA RTL Design Intern") == "digital_hardware_fpga"


def test_asic_category() -> None:
    assert category("ASIC Physical Design New Grad Engineer") == "semiconductor_asic"


def test_embedded_firmware_beats_generic_hardware() -> None:
    assert category("Embedded Firmware Engineer I") == "embedded_firmware"


def test_rf_wireless_category() -> None:
    assert category("RF and Wireless Hardware Intern") == "rf_wireless"


def test_signal_integrity_category() -> None:
    assert category("High Speed Signal Integrity Intern") == "signal_power_integrity"


def test_power_electronics_category() -> None:
    assert category("Power Electronics and Motor Drives Intern") == "power_electronics"


def test_controls_category() -> None:
    assert category("Motion Control Systems Intern") == "controls_motion"


def test_robotics_category() -> None:
    assert category("Robotics Mechatronics Hardware Intern") == "robotics_mechatronics"


def test_avionics_category() -> None:
    assert category("Avionics Electrical Engineering Intern") == "avionics_space"


def test_medtech_category() -> None:
    assert category("Medical Device Electronics Intern") == "medtech_hardware"


def test_validation_category() -> None:
    assert category("Hardware Validation Engineer I") == "test_validation"


def test_npi_category() -> None:
    assert category("Electronics New Product Introduction Intern") == "manufacturing_npi"


def test_systems_integration_category() -> None:
    assert category("Electrical Systems Integration Engineer I") == "systems_integration"


def test_field_applications_category() -> None:
    assert category("Field Applications Engineer Semiconductor New Grad") == "applications_field"


def test_general_electrical_fallback() -> None:
    assert category("Electrical Engineering Intern") == "general_electrical"
