"""Create design option sets, options and combinations (Tapir 1.7.0, Archicad 29+).

create_design_options adds, in one call and in this order, new option sets
(CreateDesignOptionSets), new options in existing or new sets (CreateDesignOptions) and
new combinations of existing or new options (CreateDesignOptionCombinations). A
combination names its active options by their string id ("F-01"). Nothing existing is
changed: set names, option ids and combination names already in the project are refused
in the preview. Tapir ignores the result of setting a combination's active options, so
the read-back (GetDesignOptionSets, GetDesignOptions, GetDesignOptionCombinations)
compares them too. Elements are not moved into options. Never saves.
"""

from __future__ import annotations

from typing import Annotated, Any

from pydantic import Field, field_validator, model_validator

from archicad_mcp_aberto.connection import ArchicadClient, ArchicadError, TapirError
from archicad_mcp_aberto.tools import write

MAX_EACH = 20
KINDS = ("set", "option", "combination")
Name = Annotated[str, Field(min_length=1, max_length=255)]


def _trimmed(value: str) -> str:
    if value != value.strip():
        raise ValueError("must not start or end with spaces.")
    return value


class OptionCreate(write.InputModel):
    name: Name
    id: Name
    set: Name

    @field_validator("name", "id", "set")
    @classmethod
    def trimmed(cls, value: str) -> str:
        return _trimmed(value)


class CombinationCreate(write.InputModel):
    name: Name
    options: Annotated[list[Name], Field(max_length=100)]

    @field_validator("name")
    @classmethod
    def trimmed(cls, value: str) -> str:
        return _trimmed(value)


class DesignOptionsCreate(write.InputModel):
    sets: Annotated[list[Name], Field(max_length=MAX_EACH)] = []
    options: Annotated[list[OptionCreate], Field(max_length=MAX_EACH)] = []
    combinations: Annotated[list[CombinationCreate], Field(max_length=MAX_EACH)] = []

    @model_validator(mode="after")
    def not_empty(self) -> DesignOptionsCreate:
        if not (self.sets or self.options or self.combinations):
            raise ValueError("Pass at least one set, option or combination.")
        for name in self.sets:
            _trimmed(name)
        return self


async def _inventory(client, port, timeout=None) -> tuple[list, list, list]:
    extra = {} if timeout is None else {"timeout": timeout}
    sets = (await client.tapir(port, "GetDesignOptionSets", **extra)).get("designOptionSets")
    options = (await client.tapir(port, "GetDesignOptions", **extra)).get("designOptions")
    combinations = (await client.tapir(port, "GetDesignOptionCombinations", **extra)).get(
        "designOptionCombinations"
    )
    if not all(isinstance(x, list) for x in (sets, options, combinations)):
        raise ValueError("Unexpected Design Options inventory response.")
    return sets, options, combinations


def _guid(row: Any, key: str) -> str | None:
    value = row.get(key) if isinstance(row, dict) else None
    guid = value.get("guid") if isinstance(value, dict) else None
    return guid.upper() if isinstance(guid, str) else None


def _unique(values: list[str], noun: str) -> None:
    seen = set()
    for value in values:
        if value.casefold() in seen:
            raise ValueError(f"The {noun} {value!r} appears twice in this call.")
        seen.add(value.casefold())


async def _plan(client, requests, port, operation):
    (request,) = requests
    port, target, _ = await write._context(client, port)
    sets, options, combinations = await _inventory(client, port)
    set_names = {str(s.get("name")) for s in sets}
    option_ids = {str(o.get("id")): _guid(o, "designOptionId") for o in options}
    combination_names = {str(c.get("name")).casefold() for c in combinations}
    _unique(request.sets, "set")
    _unique([o.id for o in request.options], "option id")
    _unique([c.name for c in request.combinations], "combination")
    items = []
    for name in request.sets:
        if name in set_names:
            raise ValueError(f"Design option set {name!r} already exists.")
        items.append({"kind": "set", "name": name})
    new_sets = set(request.sets)
    for option in request.options:
        if option.id in option_ids:
            raise ValueError(f"A design option with id {option.id!r} already exists.")
        if option.set not in set_names | new_sets:
            raise ValueError(
                f"Option {option.id!r}: set {option.set!r} does not exist and is not created "
                "here (names are case-sensitive)."
            )
        items.append(
            {
                "kind": "option",
                "name": option.name,
                "parameters": {"name": option.name, "id": option.id, "ownerSetName": option.set},
            }
        )
    new_ids = {o.id for o in request.options}
    for combination in request.combinations:
        if combination.name.casefold() in combination_names:
            raise ValueError(f"Design option combination {combination.name!r} already exists.")
        missing = [i for i in combination.options if i not in option_ids and i not in new_ids]
        if missing:
            raise ValueError(
                f"Combination {combination.name!r}: no design option with id {missing[0]!r}."
            )
        _unique(combination.options, f"option of {combination.name!r}")
        items.append(
            {
                "kind": "combination",
                "name": combination.name,
                "option_ids": list(combination.options),
                "existing_option_guids": {
                    i: option_ids[i] for i in combination.options if i in option_ids
                },
            }
        )
    for index, item in enumerate(items):
        item.update(index=index, status="ready")
    return {"operation": operation, "target": target, "items": items}


def _unknown(items: list[dict], error: str) -> None:
    for item in items:
        item.update(status="unknown", error=error)


async def _call(client, port, command, parameters, timeout) -> dict | str:
    try:
        return await client.tapir(port, command, parameters, timeout=timeout)
    except TapirError as exc:
        return f"{command}: {exc.detail or exc}"
    except ArchicadError as exc:
        return f"{command}: {exc}"


def _error(row: Any) -> Any:
    return row.get("error", row) if isinstance(row, dict) else row


async def _created(client, port, command, key, payload, items, field_name, timeout):
    """Run one create command; mark each item unverified with its GUID, or failed."""
    raw = await _call(client, port, command, payload, timeout)
    rows = raw.get(key) if isinstance(raw, dict) else None
    if not isinstance(rows, list) or len(rows) != len(items):
        return raw if isinstance(raw, str) else f"Unexpected {command} response."
    for item, row in zip(items, rows, strict=True):
        item["write_response"] = row
        if field_name is None:
            if isinstance(row, dict) and row.get("success") is True:
                item["status"] = "unverified"
            else:
                item.update(status="failed", error=_error(row))
            continue
        guid = _guid(row, field_name)
        if guid:
            item.update(status="unverified", created_guid=guid)
        else:
            item.update(status="failed", error=_error(row))
    return None


def _problems(item: dict, sets: list, options: list, combinations: list) -> list[str]:
    if item["kind"] == "set":
        return (
            []
            if item["name"] in {s.get("name") for s in sets if isinstance(s, dict)}
            else ["missing"]
        )
    if item["kind"] == "option":
        row = next((o for o in options if _guid(o, "designOptionId") == item["created_guid"]), None)
        item["after"] = row
        if row is None:
            return ["missing"]
        return [k for k in ("name", "id", "ownerSetName") if row.get(k) != item["parameters"][k]]
    row = next(
        (c for c in combinations if _guid(c, "designOptionCombinationId") == item["created_guid"]),
        None,
    )
    item["after"] = row
    if row is None:
        return ["missing"]
    problems = [] if row.get("name") == item["name"] else ["name"]
    active = sorted(_guid(a, "designOptionId") or "" for a in row.get("activeDesignOptions") or [])
    if active != sorted(item["active_option_guids"]):
        problems.append("active options")
    return problems


async def _dispatch(client, receipt):
    items, port = receipt["items"], receipt["target"]["port"]
    timeout = receipt["write_timeout_seconds"]
    sets, options, combos = ([i for i in items if i["kind"] == k] for k in KINDS)
    steps = [
        ("CreateDesignOptionSets", "executionResults", sets, None,
         lambda: {"designOptionSets": [i["name"] for i in sets]}),
        ("CreateDesignOptions", "designOptionIdsOrErrors", options, "designOptionId",
         lambda: {"designOptions": [i["parameters"] for i in options]}),
        ("CreateDesignOptionCombinations", "designOptionCombinationIdsOrErrors", None,
         "designOptionCombinationId", None),
    ]  # fmt: skip
    for command, key, group, field_name, payload in steps:
        if group is None:  # combinations need the GUIDs of the options made above
            created = {i["parameters"]["id"]: i.get("created_guid") for i in options}
            group = []
            for item in combos:
                guids = [item["existing_option_guids"].get(i) or created.get(i)
                         for i in item["option_ids"]]  # fmt: skip
                if None in guids:
                    item.update(status="failed", error="One of its options was not created.")
                else:
                    item["active_option_guids"] = guids
                    group.append(item)
            payload = lambda group=group: {  # noqa: E731
                "designOptionCombinations": [
                    {
                        "name": i["name"],
                        "activeDesignOptions": [
                            {"designOptionId": {"guid": g}} for g in i["active_option_guids"]
                        ],
                    }
                    for i in group
                ]
            }
        if not group:
            continue
        error = await _created(client, port, command, key, payload(), group, field_name, timeout)
        if error is not None:
            _unknown([i for i in items if i["status"] in ("ready", "unverified")], error)
            receipt["warning"] = "Outcome is unknown. Inspect Archicad; do not retry this plan."
            return
    created = [i for i in items if i["status"] == "unverified"]
    if not created:
        return
    try:
        inventory = await _inventory(client, port, timeout)
    except (ArchicadError, ValueError) as exc:
        receipt["verification_error"] = str(exc)
        return
    for item in created:
        problems = _problems(item, *inventory)
        item["status"] = "verification_failed" if problems else "verified"
        if problems:
            item["mismatches"] = problems


async def create_design_options(
    client: ArchicadClient,
    sets: list[str] | None = None,
    options: list[dict | OptionCreate] | None = None,
    combinations: list[dict | CombinationCreate] | None = None,
    port: int | None = None,
    dry_run: bool = True,
    confirmation_token: str | None = None,
) -> dict:
    """Preview/apply new design option sets, options (name, id, set) and combinations
    (name, active option ids), up to 20 of each. Only adds. Archicad 29+."""
    request = DesignOptionsCreate.model_validate(
        {"sets": sets or [], "options": options or [], "combinations": combinations or []}
    )
    return await write._write(
        client,
        [request],
        port,
        dry_run,
        confirmation_token,
        "create_design_options",
        planner_override=_plan,
        dispatcher_override=_dispatch,
    )
