"""Portable trust-boundary checks; these do not establish MATLAB execution."""

import re
from pathlib import Path

from matlab_companion.contracts import PARAMETER_MODELS

NATIVE = Path(__file__).resolve().parents[1] / "matlab" / "+companion"


def _without_comments(source: str) -> str:
    return "\n".join(line for line in source.splitlines() if not line.lstrip().startswith("%"))


def test_recipe_has_no_arbitrary_execution_or_global_session_cleanup():
    """The fixed recipe boundary must never become an arbitrary-code escape hatch."""
    source = _without_comments((NATIVE / "run_recipe.m").read_text(encoding="utf-8"))
    forbidden = r"\b(?:eval|evalin|assignin|system|unix|dos|addpath|rmpath|restoredefaultpath)\s*\("
    assert not re.search(forbidden, source, flags=re.IGNORECASE)
    assert not re.search(r"\b(?:clear|close)\s+all\b", source, flags=re.IGNORECASE)
    assert not re.search(r"\b(?:delete|rmdir)\s*\(", source, flags=re.IGNORECASE)


def test_every_registered_operation_has_a_native_recipe():
    source = (NATIVE / "run_recipe.m").read_text(encoding="utf-8")
    dispatch = source.split("switch request.operation", 1)[1].split("\n    otherwise", 1)[0]
    cases = re.findall(r"^    case (.+)$", dispatch, flags=re.MULTILINE)
    native_operations = {name for case in cases for name in re.findall(r"'([a-z_]+)'", case)}
    assert native_operations == set(PARAMETER_MODELS)


def test_standalone_recipe_does_not_call_the_private_plugin_package():
    recipe = (NATIVE / "run_recipe.m").read_text(encoding="utf-8")
    assert not re.search(r"\bcompanion\.", _without_comments(recipe))
    assert recipe.startswith("function result = run_recipe(request, outputDir)")
    execute = (NATIVE / "execute.m").read_text(encoding="utf-8")
    assert "'run_recipe.m'" in execute
    assert "'reproduce.m'" in execute
    assert "run(scriptPath);" in execute
    assert "function result = isolatedRerun(" in execute


def test_recipe_uses_only_declared_operation_parameters():
    source = (NATIVE / "run_recipe.m").read_text(encoding="utf-8")
    used = set(re.findall(r"\bp\.([a-z_]+)\b", source))
    declared = {field for model in PARAMETER_MODELS.values() for field in model.model_fields}
    assert used <= declared
