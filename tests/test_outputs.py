import json
from pathlib import Path

from haloshield.utils import write_json


def test_json_output_is_readable(tmp_path: Path):
    target = tmp_path / "nested" / "result.json"
    write_json(target, {"seed": 123, "ok": True})
    assert json.loads(target.read_text()) == {"ok": True, "seed": 123}
