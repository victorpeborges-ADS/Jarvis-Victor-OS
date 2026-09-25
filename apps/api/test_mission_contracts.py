import copy

import pytest

from mission_contracts import Mission, contract_examples, validate_contract


def test_shared_schema_examples_validate_for_python() -> None:
    examples = contract_examples()
    for name, value in examples.items():
        validate_contract(name, value)


def test_mission_pydantic_model_accepts_versioned_contract() -> None:
    assert Mission.model_validate(contract_examples()["Mission"]).status == "planned"


@pytest.mark.parametrize("mutation", [
    lambda value: value.update(status="executed"),
    lambda value: value.update(budget={"cap": 50, "spent": 0}),
    lambda value: value.update(created_at="2026-09-25T01:30:00"),
])
def test_mission_rejects_invalid_status_budget_or_naive_timestamp(mutation) -> None:
    value = copy.deepcopy(contract_examples()["Mission"])
    mutation(value)
    with pytest.raises(ValueError):
        validate_contract("Mission", value)


def test_schema_rejects_unknown_contract_or_fields() -> None:
    with pytest.raises(ValueError, match="contrato desconhecido"):
        validate_contract("NotAContract", {})
    value = copy.deepcopy(contract_examples()["Mission"])
    value["unreviewed"] = True
    with pytest.raises(ValueError):
        validate_contract("Mission", value)
