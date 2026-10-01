"""Editable starting vocabulary. Each chapter extends its own copy at runtime.

Definitions ALWAYS read SOURCE -> TARGET. Similarity is not equivalence.
Inverse keys express equivalent facts ONLY after exchanging the endpoints.
"""
DEFAULT_RELATIONS = {
    "is_a": ("SOURCE is a subtype or kind of TARGET, not a component or instance.", "has_subtype", False),
    "has_subtype": ("TARGET is a subtype or kind of SOURCE, not a component or instance.", "is_a", False),
    "part_of": ("SOURCE is a structural component of TARGET, not merely located there or participating in it.", "has_part", False),
    "has_part": ("TARGET is a structural component of SOURCE, not merely located there or participating in it.", "part_of", False),
    "contains": ("SOURCE spatially contains TARGET; structural parthood and ownership are not implied.", "contained_in", False),
    "contained_in": ("SOURCE is spatially contained in TARGET; structural parthood and ownership are not implied.", "contains", False),
    "causes": ("SOURCE causally produces the explicit event TARGET, not merely permitting it. TARGET names the action or change, not its affected object.", "caused_by", False),
    "caused_by": ("The explicit event SOURCE is causally produced by TARGET. SOURCE names the action or change, not its affected object.", "causes", False),
    "acts_on": ("The event SOURCE acts on or changes the state, position, or availability of the object TARGET; TARGET is not another event or process.", None, False),
    "enables": ("SOURCE provides conditions or capacity permitting TARGET, without claiming it produces TARGET.", None, False),
    "inhibits": ("SOURCE reduces or suppresses the occurrence or activity of TARGET.", None, False),
    "associated_with": ("SOURCE and TARGET are associated; no causality, parthood or direction is asserted.", None, True),
    "occurs_in": ("The event or process SOURCE takes place in the physical location TARGET.", None, False),
    "participates_in": ("The entity SOURCE participates in the event or process TARGET, without being its structural part.", "has_participant", False),
    "has_participant": ("The entity TARGET participates in the event or process SOURCE, without being its structural part.", "participates_in", False),
    "precedes": ("SOURCE happens temporally before TARGET, without implying causation.", "follows", False),
    "follows": ("SOURCE happens temporally after TARGET, without implying causation.", "precedes", False),
    "sibling_of": ("SOURCE and TARGET are distinct peers under an explicitly justified common parent and the same parent relation.", None, True),
    "requires_understanding_of": ("Understanding SOURCE requires prior understanding of TARGET; this is a learning prerequisite, not causality.", None, False),
    "defines": ("TARGET is the defining description of SOURCE, not a function, participant or mere associated concept.", None, False),
}
