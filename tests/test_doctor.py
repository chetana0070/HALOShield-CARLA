from pathlib import Path

from haloshield.system import doctor


def test_doctor_returns_structured_checks(tmp_path: Path):
    checks = doctor(tmp_path)
    assert checks
    assert {check.status for check in checks}.issubset({"PASS", "WARN", "FAIL"})
    assert any(check.name == "Disk" for check in checks)
