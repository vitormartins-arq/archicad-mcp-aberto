#include "AttributeRenameCommand.hpp"
#include "OnExit.hpp"

namespace {
API_AttrTypeID AttributeType (const GS::UniString& type)
{
    if (type == "Surface") return API_MaterialID;
    if (type == "BuildingMaterial") return API_BuildingMaterialID;
    if (type == "Fill") return API_FilltypeID;
    if (type == "Line") return API_LinetypeID;
    if (type == "Composite") return API_CompWallID;
    if (type == "Profile") return API_ProfileID;
    if (type == "ZoneCategory") return API_ZoneCatID;
    if (type == "Layer") return API_LayerID;
    return API_ZombieAttrID;
}

GSErrCode Rename (API_AttrTypeID type, const GS::UniString& guid, const GS::UniString& name,
                  GS::UniString& oldName, const char*& message)
{
    API_Attribute attribute = {};
    attribute.header.typeID = type;
    attribute.header.guid = APIGuidFromString (guid.ToCStr ().Get ());
    attribute.header.uniStringNamePtr = &oldName;
    if (attribute.header.guid == APINULLGuid) {
        message = "Invalid attribute GUID.";
        return APIERR_BADGUID;
    }
    const GS::OnExit texture ([&] () {
        if (type == API_MaterialID) delete attribute.material.texture.fileLoc;
    });
    GSErrCode error = ACAPI_Attribute_Get (&attribute);
    if (error != NoError) {
        message = "Attribute lookup failed.";
        return error;
    }
    GS::UniString trimmed = name;
    trimmed.Trim ();
    if (trimmed.IsEmpty () || name.GetLength () >= API_AttrNameLen ||
        name.FindFirst (GS::UniChar (char16_t {0})) != MaxUIndex) {
        message = "Blank, invalid or overlong attribute name.";
        return APIERR_BADNAME;
    }
    if (name == oldName) return NoError;
    GS::UniString newName = name;
    API_Attr_Head existing = {};
    existing.typeID = type;
    existing.uniStringNamePtr = &newName;
    error = ACAPI_Attribute_Search (&existing);
    if (error == NoError && existing.guid != attribute.header.guid) {
        message = "This name already exists in the same attribute type.";
        return APIERR_BADNAME;
    }
    if (error != NoError && error != APIERR_BADNAME) {
        message = "Could not check for duplicate names.";
        return error;
    }
    newName = name;
    attribute.header.uniStringNamePtr = &newName;
    message = "Attribute modification failed.";
    if (type == API_BuildingMaterialID || type == API_LayerID)
        return ACAPI_Attribute_Modify (&attribute, nullptr);

    API_AttributeDefExt definition = {};
    const GS::OnExit dispose ([&] () { ACAPI_DisposeAttrDefsHdlsExt (&definition); });
    error = ACAPI_Attribute_GetDefExt (type, attribute.header.index, &definition);
    // Some SDK/host versions expose the surface texture only in API_MaterialType.
    // In that case send the complete original material (including texture.fileLoc).
    if (error == APIERR_BADID && type == API_MaterialID)
        return ACAPI_Attribute_Modify (&attribute, nullptr);
    if (error != NoError) {
        message = "Could not read the extended attribute definition.";
        return error;
    }
    return ACAPI_Attribute_ModifyExt (&attribute, &definition);
}
}

GS::String RenameAttributesCommand::GetName () const { return "RenameAttributes"; }

GS::Optional<GS::UniString> RenameAttributesCommand::GetInputParametersSchema () const
{
    return R"({"type":"object","properties":{"attributeType":{"enum":["Surface","BuildingMaterial","Fill","Line","Composite","Profile","ZoneCategory","Layer"]},"renames":{"type":"array","minItems":1,"maxItems":500,"items":{"type":"object","properties":{"guid":{"type":"string","pattern":"^[0-9A-Fa-f]{8}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{12}$"},"newName":{"type":"string"}},"required":["guid","newName"],"additionalProperties":false}}},"required":["attributeType","renames"],"additionalProperties":false})";
}

GS::ObjectState RenameAttributesCommand::Execute (const GS::ObjectState& input, GS::ProcessControl&) const
{
    GS::UniString typeName;
    GS::Array<GS::ObjectState> items;
    input.Get ("attributeType", typeName);
    input.Get ("renames", items);
    const API_AttrTypeID type = AttributeType (typeName);
    if (type == API_ZombieAttrID || items.IsEmpty () || items.GetSize () > 500)
        return CreateErrorResponse (APIERR_BADPARS, "Invalid attribute type or batch size.");
    GS::Array<GS::ObjectState> answers;
    const GSErrCode batchError = ACAPI_CallUndoableCommand ("Rename attributes", [&] () -> GSErrCode {
        for (const auto& item : items) {
            GS::UniString guid, oldName, newName;
            item.Get ("guid", guid);
            item.Get ("newName", newName);
            const char* message = "";
            const GSErrCode error = Rename (type, guid, newName, oldName, message);
            GS::ObjectState row;
            row.Add ("guid", guid);
            row.Add ("oldName", oldName);
            row.Add ("newName", newName);
            row.Add ("success", error == NoError);
            if (error != NoError) {
                GS::ObjectState detail;
                detail.Add ("code", static_cast<Int32> (error));
                detail.Add ("message", GS::UniString (message));
                row.Add ("error", detail);
            }
            answers.Push (row);
        }
        return NoError;
    });
    if (batchError != NoError) return CreateErrorResponse (batchError, "Rename transaction failed.");
    GS::ObjectState result;
    auto add = result.AddList<GS::ObjectState> ("results");
    for (const auto& row : answers) add (row);
    return result;
}
