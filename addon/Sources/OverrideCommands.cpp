#include "OverrideCommands.hpp"

static void AddGuids (GS::ObjectState& os, const char* key, const GS::Array<API_Guid>& guids)
{
    const auto& list = os.AddList<GS::UniString> (key);
    for (const API_Guid& guid : guids) {
        list (APIGuidToString (guid));
    }
}

// ---------------------------------------------------------------------------------------
// GetGraphicOverrides
// ---------------------------------------------------------------------------------------

GS::String GetGraphicOverridesCommand::GetName () const
{
    return "GetGraphicOverrides";
}

GS::Optional<GS::UniString> GetGraphicOverridesCommand::GetInputParametersSchema () const
{
    return R"({
        "type": "object",
        "properties": {},
        "additionalProperties": false
    })";
}

GS::ObjectState GetGraphicOverridesCommand::Execute (const GS::ObjectState& /*parameters*/, GS::ProcessControl& /*processControl*/) const
{
    GS::Array<API_Guid> combinationIds;
    GS::Array<API_Guid> groupIds;
    GS::Array<API_Guid> ruleIds;
    GSErrCode err = ACAPI_GraphicalOverride_GetOverrideCombinationList (combinationIds);
    if (err == NoError) {
        err = ACAPI_GraphicalOverride_GetOverrideRuleGroupList (groupIds);
    }
    if (err == NoError) {
        err = ACAPI_GraphicalOverride_GetOverrideRuleList (ruleIds);
    }
    if (err != NoError) {
        return CreateErrorResponse (err, "Failed to list the graphic overrides.");
    }

    GS::ObjectState response;
    GS::HashTable<API_Guid, API_Guid> groupOfRule;

    const auto& groups = response.AddList<GS::ObjectState> ("ruleGroups");
    for (const API_Guid& guid : groupIds) {
        API_OverrideRuleGroup group {};
        group.guid = guid;
        GS::Array<API_Guid> rules;
        err = ACAPI_GraphicalOverride_GetOverrideRuleGroup (group, &rules);
        if (err != NoError) {
            return CreateErrorResponse (err, "Failed to read an override rule group.");
        }
        GS::ObjectState row ("guid", APIGuidToString (guid), "name", group.name);
        AddGuids (row, "ruleGuids", rules);
        groups (row);
        for (const API_Guid& rule : rules) {
            groupOfRule.Put (rule, guid);
        }
    }

    const auto& rules = response.AddList<GS::ObjectState> ("rules");
    for (const API_Guid& guid : ruleIds) {
        API_OverrideRule rule {};
        rule.guid = guid;
        err = ACAPI_GraphicalOverride_GetOverrideRuleById (rule);
        if (err != NoError) {
            return CreateErrorResponse (err, "Failed to read an override rule.");
        }
        GS::ObjectState row ("guid", APIGuidToString (guid), "name", rule.name);
        API_Guid group = APINULLGuid;
        if (groupOfRule.Get (guid, &group)) {
            row.Add ("ruleGroupGuid", APIGuidToString (group));
        }
        rules (row);
    }

    const auto& combinations = response.AddList<GS::ObjectState> ("combinations");
    for (const API_Guid& guid : combinationIds) {
        API_OverrideCombination combination {};
        combination.guid = guid;
        GS::Array<API_Guid> combinationRules;
        err = ACAPI_GraphicalOverride_GetOverrideCombination (combination, &combinationRules);
        if (err != NoError) {
            return CreateErrorResponse (err, "Failed to read an override combination.");
        }
        GS::ObjectState row ("guid", APIGuidToString (guid), "name", combination.name);
        AddGuids (row, "ruleGuids", combinationRules);
        combinations (row);
    }

#ifdef ServerMainVers_3000  // not in the AC29 API
    API_Guid current = APINULLGuid;
    if (ACAPI_GraphicalOverride_GetActualOverrideCombination (current) == NoError && current != APINULLGuid) {
        response.Add ("currentCombinationGuid", APIGuidToString (current));
    }
#endif
    return response;
}

// ---------------------------------------------------------------------------------------
// RenameGraphicOverrides
// ---------------------------------------------------------------------------------------

GS::String RenameGraphicOverridesCommand::GetName () const
{
    return "RenameGraphicOverrides";
}

GS::Optional<GS::UniString> RenameGraphicOverridesCommand::GetInputParametersSchema () const
{
    return R"({
        "type": "object",
        "properties": {
            "renames": {
                "type": "array",
                "minItems": 1,
                "maxItems": 500,
                "items": {
                    "type": "object",
                    "properties": {
                        "type": {"type": "string", "enum": ["rule", "ruleGroup", "combination"]},
                        "guid": {"type": "string", "minLength": 36, "maxLength": 38},
                        "newName": {"type": "string", "minLength": 1, "maxLength": 255}
                    },
                    "additionalProperties": false,
                    "required": ["type", "guid", "newName"]
                }
            }
        },
        "additionalProperties": false,
        "required": ["renames"]
    })";
}

static GSErrCode RenameOne (const GS::UniString& type, const API_Guid& guid, const GS::UniString& newName, GS::UniString& message)
{
    GSErrCode err = NoError;
    if (type == "rule") {
        API_OverrideRule rule {};
        rule.guid = guid;
        err = ACAPI_GraphicalOverride_GetOverrideRuleById (rule);
        if (err != NoError) {
            message = "No override rule with this GUID.";
            return err;
        }
        rule.name = newName;
        err = ACAPI_GraphicalOverride_ChangeOverrideRule (rule);
    } else if (type == "ruleGroup") {
        API_OverrideRuleGroup group {};
        group.guid = guid;
        err = ACAPI_GraphicalOverride_GetOverrideRuleGroup (group);
        if (err != NoError) {
            message = "No override rule group with this GUID.";
            return err;
        }
        group.name = newName;
        err = ACAPI_GraphicalOverride_ChangeOverrideRuleGroup (group);
    } else {
        API_OverrideCombination combination {};
        combination.guid = guid;
        err = ACAPI_GraphicalOverride_GetOverrideCombination (combination);
        if (err != NoError) {
            message = "No override combination with this GUID.";
            return err;
        }
        combination.name = newName;
        err = ACAPI_GraphicalOverride_ChangeOverrideCombination (combination);  // keeps its rules
    }
    switch (err) {
        case NoError:                   break;
        case APIERR_BADNAME:            message = "Archicad refused the name (blank or too long)."; break;
        case APIERR_NAMEALREADYUSED:    message = "The name is already used."; break;
        case APIERR_NOACCESSRIGHT:      message = "Built-in item or no Teamwork right; Archicad refused the change."; break;
        default:                        message = "Archicad refused the rename."; break;
    }
    return err;
}

GS::ObjectState RenameGraphicOverridesCommand::Execute (const GS::ObjectState& parameters, GS::ProcessControl& /*processControl*/) const
{
    GS::Array<GS::ObjectState> renames;
    parameters.Get ("renames", renames);

    GS::ObjectState response;
    const auto& results = response.AddList<GS::ObjectState> ("executionResults");
    GS::Array<GS::ObjectState> rows;

    const GSErrCode err = ACAPI_CallUndoableCommand ("Rename graphic overrides", [&] () -> GSErrCode {
        for (const GS::ObjectState& item : renames) {
            GS::UniString type;
            GS::UniString guidText;
            GS::UniString newName;
            item.Get ("type", type);
            item.Get ("guid", guidText);
            item.Get ("newName", newName);
            const API_Guid guid = APIGuidFromString (guidText.ToCStr ().Get ());
            GS::UniString message;
            const GSErrCode itemErr = guid == APINULLGuid ? APIERR_BADPARS : RenameOne (type, guid, newName, message);
            if (guid == APINULLGuid) {
                message = "Invalid GUID.";
            }
            if (itemErr == NoError) {
                rows.Push (GS::ObjectState ("success", true));
            } else {
                GS::ObjectState error ("code", itemErr, "message", message.ToCStr ().Get ());
                rows.Push (GS::ObjectState ("success", false, "error", error));
            }
        }
        return NoError;
    });
    if (err != NoError) {
        return CreateErrorResponse (err, "Archicad refused the undoable rename step; nothing was renamed.");
    }
    for (const GS::ObjectState& row : rows) {
        results (row);
    }
    return response;
}

// ---------------------------------------------------------------------------------------
// GetRenovationFilters
// ---------------------------------------------------------------------------------------

GS::String GetRenovationFiltersCommand::GetName () const
{
    return "GetRenovationFilters";
}

GS::Optional<GS::UniString> GetRenovationFiltersCommand::GetInputParametersSchema () const
{
    return R"({
        "type": "object",
        "properties": {},
        "additionalProperties": false
    })";
}

GS::ObjectState GetRenovationFiltersCommand::Execute (const GS::ObjectState& /*parameters*/, GS::ProcessControl& /*processControl*/) const
{
    GS::Array<API_Guid> filterIds;
    GSErrCode err = ACAPI_Renovation_GetRenovationFilters (&filterIds);
    if (err != NoError) {
        return CreateErrorResponse (err, "Failed to list the renovation filters.");
    }
    GS::ObjectState response;
    const auto& filters = response.AddList<GS::ObjectState> ("renovationFilters");
    for (const API_Guid& guid : filterIds) {
        GS::UniString name;
        err = ACAPI_Renovation_GetRenovationFilterName (&guid, &name);
        if (err != NoError) {
            return CreateErrorResponse (err, "Failed to read a renovation filter name.");
        }
        filters (GS::ObjectState ("guid", APIGuidToString (guid), "name", name));
    }
    API_Guid current = APINULLGuid;
    if (ACAPI_Renovation_GetActualRenovationFilter (&current) == NoError && current != APINULLGuid) {
        response.Add ("currentFilterGuid", APIGuidToString (current));
    }
    return response;
}
