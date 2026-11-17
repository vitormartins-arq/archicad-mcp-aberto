#include "ProfileModifierCommands.hpp"
#include "ProjectSaveCommands.hpp"
#include "ProfileVectorImage.hpp"
#include "MD5Channel.hpp"
#include "OnExit.hpp"

namespace {
using Names = GS::HashTable<PVI::ProfileParameterId, GS::UniString>;

GSErrCode ReadProfile (const GS::UniString& guid, API_Attribute& attribute,
                      API_AttributeDefExt& definition)
{
    attribute.header.typeID = API_ProfileID;
    attribute.header.guid = APIGuidFromString (guid.ToCStr ().Get ());
    if (attribute.header.guid == APINULLGuid) return APIERR_BADGUID;
    const GSErrCode error = ACAPI_Attribute_Get (&attribute);
    if (error != NoError) return error;
    if (attribute.header.typeID != API_ProfileID ||
        attribute.header.guid != APIGuidFromString (guid.ToCStr ().Get ()))
        return APIERR_BADGUID;
    return ACAPI_Attribute_GetDefExt (API_ProfileID, attribute.header.index, &definition);
}

bool Fingerprint (const ProfileVectorImage& image, GS::UniString& value)
{
    IO::MD5Channel channel;
    if (image.Write (channel) != NoError) return false;
    value = GS::UniString (channel.Finish ().GetAsGsString ());
    return true;
}

GS::ObjectState Anchor (const ProfileVectorImage& image, const PVI::ProfileAnchorId& id)
{
    GS::ObjectState row ("id", id.Get ().ToUniString ());
    const auto anchor = image.GetAnchor (id);
    if (!anchor.HasValue ()) return row;

    using Type = PVI::Anchor::AnchorType;
    const auto type = anchor->GetAnchorType ();
    row.Add ("type", static_cast<int> (type));
    if (type == Type::VertexAssociative) {
        const auto& vertex = anchor->GetAssociatedVertexId ();
        row.Add ("hatchId", vertex.GetHatchId ().ToUniString ());
        row.Add ("vertexIndex", vertex.GetVertexIndex ());
    } else if (type == Type::EdgeAssociative) {
        const auto& edge = anchor->GetAssociatedEdgeId ();
        row.Add ("hatchId", edge.GetHatchId ().ToUniString ());
        row.Add ("edgeIndex", edge.GetEdgeIndex ());
        row.Add ("rightSide", anchor->GetEdgePosSideOnRightOfEdge ());
    } else if (type == Type::FixedToStretchCanvas) {
        const auto& position = anchor->GetFixAnchorPosition ();
        row.Add ("x", position.x);
        row.Add ("y", position.y);
    }
    return row;
}

GS::ObjectState Setup (const ProfileVectorImage& image, const PVI::ProfileParameterSetupId& id)
{
    GS::ObjectState row ("id", id.Get ().ToUniString ());
    const auto& parameter = image.GetParameterDef (id);
    const bool offset = parameter.GetType () == PVI::ProfileVectorImageParameter::ParameterType::EdgeOffset;
    row.Add ("edgeOffset", offset);
    if (!offset) return row;

    const auto& offsetParameter = parameter.GetEdgeOffsetParameter ();
    auto addEdge = row.AddList<GS::ObjectState> ("edges");
    for (const auto& edge : offsetParameter.GetAssociatedEdges ()) {
        addEdge (GS::ObjectState ("hatchId", edge.GetHatchId ().ToUniString (),
            "edgeIndex", edge.GetEdgeIndex (), "direction",
            GS::UniString (edge.GetDirectionFlag () == PVI::AssociatedEdge::DirectionFlag::Left
                ? "left" : "right")));
    }
    const auto& dimensionId = offsetParameter.GetDimControlToolID ();
    row.Add ("dimensionId", dimensionId.Get ().ToUniString ());
    const auto dimension = image.GetDimensionControlTool (dimensionId);
    if (dimension.HasValue ()) {
        GS::ObjectState measurement ("begin", Anchor (image, dimension->GetBegAnchorID ()),
                                     "end", Anchor (image, dimension->GetEndAnchorID ()));
        measurement.Add ("controlParameterId", dimension->GetControlParamID ().ToUniString ());
        measurement.Add ("outputParameterId", dimension->GetOutputParamID ().ToUniString ());
        measurement.Add ("projectedToNominalDirection", dimension->IsProjectedToNominalDirType ());
        measurement.Add ("euclidean", dimension->IsEuclideanType ());
        if (dimension->IsProjectedToAngleDirType ())
            measurement.Add ("projectionAngle", dimension->GetProjAngleRad ());
        row.Add ("measurement", measurement);
    }
    return row;
}

bool IsOffset (const ProfileVectorImage& image, const PVI::ProfileParameterId& id)
{
    if (!image.HasParameter (id) || image.GetSetupIDs (id).IsEmpty ()) return false;
    for (const auto& setup : image.GetSetupIDs (id)) {
        if (!image.GetParameterDefs ().ContainsKey (setup) ||
            image.GetParameterDef (setup).GetType () !=
                PVI::ProfileVectorImageParameter::ParameterType::EdgeOffset)
            return false;
    }
    return true;
}

bool SameContext (const GS::ObjectState& expected, const GS::ObjectState& current)
{
    for (const char* field : {"sessionId", "projectEpoch", "modificationStamp"}) {
        GS::UniString before, now;
        if (!expected.Get (field, before) || !current.Get (field, now) || before != now) return false;
    }
    bool teamwork = true;
    return current.Get ("teamwork", teamwork) && !teamwork;
}

enum class Verification { Unavailable, Different, Matches };

Verification Verify (const GS::UniString& guid, const GS::UniString& fingerprint, const Names& expected)
{
    API_Attribute attribute {};
    API_AttributeDefExt definition {};
    const GS::OnExit dispose ([&] { ACAPI_DisposeAttrDefsHdlsExt (&definition); });
    GS::UniString actual;
    if (ReadProfile (guid, attribute, definition) != NoError ||
        definition.profile_vectorImageItems == nullptr ||
        definition.profile_vectorImageParameterNames == nullptr ||
        !Fingerprint (*definition.profile_vectorImageItems, actual))
        return Verification::Unavailable;
    return actual == fingerprint && *definition.profile_vectorImageParameterNames == expected
        ? Verification::Matches : Verification::Different;
}
}

GS::String GetProfileModifiersCommand::GetName () const { return "GetProfileModifiers"; }
GS::Optional<GS::UniString> GetProfileModifiersCommand::GetInputParametersSchema () const
{
    return GS::UniString (R"({"type":"object","properties":{"profileGuid":{"type":"string"}},"required":["profileGuid"],"additionalProperties":false})");
}
GS::ObjectState GetProfileModifiersCommand::Execute (const GS::ObjectState& input, GS::ProcessControl&) const
{
    GS::UniString guid;
    input.Get ("profileGuid", guid);
    API_Attribute attribute {};
    API_AttributeDefExt definition {};
    const GS::OnExit dispose ([&] { ACAPI_DisposeAttrDefsHdlsExt (&definition); });
    const GSErrCode error = ReadProfile (guid, attribute, definition);
    if (error != NoError) return CreateErrorResponse (error, "Could not load the complex profile.");
    const auto* image = definition.profile_vectorImageItems;
    const auto* names = definition.profile_vectorImageParameterNames;
    GS::UniString fingerprint;
    if (image == nullptr || !Fingerprint (*image, fingerprint))
        return CreateErrorResponse (APIERR_GENERAL, "Could not fingerprint the profile definition.");

    GS::ObjectState result ("profileGuid", guid, "geometryFingerprint", fingerprint);
    auto add = result.AddList<GS::ObjectState> ("modifiers");
    if (names == nullptr) return result;
    for (auto it = names->EnumeratePairs (); it != nullptr; ++it) {
        const auto& id = it->key;
        GS::ObjectState row ("id", id.ToUniString (), "name", it->value,
                             "renamable", IsOffset (*image, id));
        auto addSetup = row.AddList<GS::ObjectState> ("setups");
        if (image->HasParameter (id)) {
            for (const auto& setup : image->GetSetupIDs (id)) {
                if (image->GetParameterDefs ().ContainsKey (setup))
                    addSetup (Setup (*image, setup));
            }
        }
        add (row);
    }
    return result;
}

GS::String RenameProfileModifiersCommand::GetName () const { return "RenameProfileModifiers"; }
GS::Optional<GS::UniString> RenameProfileModifiersCommand::GetInputParametersSchema () const
{
    return GS::UniString (R"({"type":"object","properties":{"profileGuid":{"type":"string"},"geometryFingerprint":{"type":"string"},"context":{"type":"object"},"renames":{"type":"array","minItems":1,"maxItems":100,"items":{"type":"object","properties":{"id":{"type":"string"},"oldName":{"type":"string"},"newName":{"type":"string"}},"required":["id","oldName","newName"],"additionalProperties":false}}},"required":["profileGuid","geometryFingerprint","context","renames"],"additionalProperties":false})");
}
GS::ObjectState RenameProfileModifiersCommand::Execute (const GS::ObjectState& input, GS::ProcessControl& process) const
{
    GS::UniString guid, expectedFingerprint, fingerprint;
    GS::ObjectState context;
    GS::Array<GS::ObjectState> renames;
    input.Get ("profileGuid", guid);
    input.Get ("geometryFingerprint", expectedFingerprint);
    input.Get ("context", context);
    input.Get ("renames", renames);
    if (renames.IsEmpty () || renames.GetSize () > 100 ||
        !SameContext (context, GetProjectSaveContextCommand ().Execute ({}, process)))
        return CreateErrorResponse (APIERR_BADPARS, "Invalid batch or stale project context.");

    GS::UniString profileName;
    API_Attribute attribute {};
    attribute.header.uniStringNamePtr = &profileName;
    API_AttributeDefExt definition {};
    const GS::OnExit dispose ([&] { ACAPI_DisposeAttrDefsHdlsExt (&definition); });
    GSErrCode error = ReadProfile (guid, attribute, definition);
    if (error != NoError) return CreateErrorResponse (error, "Could not load the complex profile.");
    const auto* image = definition.profile_vectorImageItems;
    auto* names = definition.profile_vectorImageParameterNames;
    if (image == nullptr || names == nullptr || !Fingerprint (*image, fingerprint) ||
        fingerprint != expectedFingerprint)
        return CreateErrorResponse (APIERR_BADPARS, "The profile definition changed since preview.");

    const Names original = *names;
    Names desired = original;
    GS::HashSet<PVI::ProfileParameterId> edited;
    for (const auto& row : renames) {
        GS::UniString rawId, oldName, newName;
        row.Get ("id", rawId);
        row.Get ("oldName", oldName);
        row.Get ("newName", newName);
        const GS::Guid id = APIGuid2GSGuid (APIGuidFromString (rawId.ToCStr ().Get ()));
        GS::UniString trimmed = newName;
        trimmed.Trim ();
        if (id == GS::NULLGuid || edited.Contains (id) || !original.ContainsKey (id) ||
            original[id] != oldName || !IsOffset (*image, id) || trimmed != newName ||
            newName.IsEmpty () || newName.GetLength () >= API_AttrNameLen ||
            newName.FindFirst (GS::UniChar (char16_t {0})) != MaxUIndex)
            return CreateErrorResponse (APIERR_BADPARS, "Invalid, unsupported or stale modifier rename.");
        edited.Add (id);
        desired[id] = newName;
    }

    // Existing duplicates stay readable; a changed name must not collide with another ID.
    for (const auto& id : edited) {
        if (original[id] == desired[id]) continue;
        GS::UniString candidate = desired[id];
        candidate.SetToLowerCase ();
        for (auto other = desired.AsConst ().EnumeratePairs (); other != nullptr; ++other) {
            if (other->key == id) continue;
            GS::UniString otherName = other->value;
            otherName.Trim ();
            otherName.SetToLowerCase ();
            if (candidate == otherName)
                return CreateErrorResponse (APIERR_BADNAME, "The target name belongs to another modifier ID.");
        }
    }

    if (desired != original) {
        *names = desired;
        error = ACAPI_Attribute_ModifyExt (&attribute, &definition);
        if (error != NoError)
            return GS::ObjectState ("status", GS::UniString ("unknown"), "code", static_cast<Int32> (error));
        const auto verification = Verify (guid, fingerprint, desired);
        if (verification == Verification::Unavailable)
            return GS::ObjectState ("status", GS::UniString ("unknown"));
        if (verification == Verification::Different) {
            *names = original;
            const bool restored = ACAPI_Attribute_ModifyExt (&attribute, &definition) == NoError &&
                Verify (guid, fingerprint, original) == Verification::Matches;
            return GS::ObjectState ("status", GS::UniString (restored ? "restored" : "unknown"));
        }
    }
    return GS::ObjectState ("status", GS::UniString ("verified"));
}
