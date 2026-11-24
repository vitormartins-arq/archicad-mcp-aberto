# Demolition and construction section dimensions

Approved by Vitor on 18 November 2026 after reviewing his manual dimensions in
WG Formosa_R06 sections 01, 02 and 03. These conventions guide the MCP agent using
`get_section_cut_elements` and `create_section_dimensions`.

## Scope and references

- By default, dimension floors, walls and ceilings marked as new construction.
- Existing elements may provide lower and upper references.
- Inspect the complete section and cover every distinct construction height and level.
- Choose the corresponding demolition and construction Dimension favorite.

## Placement and reading

- Work across the drawing from right to left, following the user's approved chains.
- Place vertical dimension lines to the left of the relevant local reference and keep
  the text on the left of the line. Verify the visible result after creation.
- Organize chains by room or construction detail. A locally lowered ceiling gets a
  dimension inside that room, using its own lower and upper references.
- Tie general chains to the relevant base and top, usually a floor/slab and a roof
  or upper slab. The reference extent follows the construction being dimensioned.
- Offset the first line 0.50 m from its local drawing reference. Space subsequent
  parallel lines by 0.20 m.

## Civil datum

For WG Formosa_R06, measure construction heights from the structural slab surface.
The floor finish has yet to be installed during civil execution. Check the datum
specified for each subsequent project.

Section 02 illustrates a slab at -0.20 m and a lowered ceiling at +2.50 m, giving
a civil height of 2.70 m. Other rooms have separate local chains. Section 03 has
a chain of 3.30 m + 0.20 m + 4.30 m up to +7.80 m.

## Verification

Rebuild the section and read every dimension again. Check every witness point,
value, association, text position and offset against the intended local detail.
Explicitly report any missing point or dimension converted to fixed.

Live observations on Archicad 30 build 3001 BRA, Tapir 1.7.0 showed section 01
losing associations or dropping dimensions after rebuild. Sections 02 and 03
retained chains, with some fixed wall points. The user subsequently adjusted the
three sections manually. His current examples establish the conventions above.
These documentation changes do not resolve the native association problem.
