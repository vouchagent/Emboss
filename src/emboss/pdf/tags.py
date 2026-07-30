"""PDF/UA structure tree construction.

The structure tree is what turns a page of positioned glyphs into a
document: it declares that this text is a level-2 heading, that group of
cells is a table with column headers, and this run of ink is decoration
to be ignored. Screen readers, text extraction, and reflow all read it.

Two pieces are easy to get wrong and are handled explicitly here:

  ParentTree  maps each page's marked-content ids back to the structure
              elements that own them. Readers use it to answer "what is
              this text part of". A missing or misnumbered ParentTree is
              the most common cause of a technically-tagged PDF failing
              a real audit.

  Scope       header cells must declare /Scope so a reader can announce
              the right header when the user moves between data cells.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .objects import PdfArray, PdfDict, PdfName, PdfRef, PdfString

__all__ = ["StructureElement", "StructureTreeBuilder"]

#: Tags used directly by this library, mapped to their standard roles.
_ROLE_MAP = {
    "H1": "H1",
    "H2": "H2",
    "H3": "H3",
    "H4": "H4",
    "H5": "H5",
    "H6": "H6",
    "P": "P",
    "L": "L",
    "LI": "LI",
    "LBody": "LBody",
    "Lbl": "Lbl",
    "Table": "Table",
    "THead": "THead",
    "TBody": "TBody",
    "TR": "TR",
    "TH": "TH",
    "TD": "TD",
    "BlockQuote": "BlockQuote",
    "Caption": "Caption",
    "Figure": "Figure",
    "Code": "Code",
    "Document": "Document",
    "Link": "Link",
    "Note": "Note",
    "Form": "Form",
}


@dataclass
class StructureElement:
    """A node in the structure tree."""

    tag: str
    page_index: int | None = None
    mcids: list = field(default_factory=list)
    children: list = field(default_factory=list)
    alt_text: str | None = None
    actual_text: str | None = None
    title: str | None = None
    scope: str | None = None
    colspan: int | None = None
    obj_id: int | None = None
    annot_ref: PdfRef | None = None
    struct_parent: int | None = None
    node_id: str | None = None
    af_refs: list | None = None

    def add(self, child: "StructureElement") -> "StructureElement":
        self.children.append(child)
        return child

    def add_mcid(self, page_index: int, mcid: int) -> None:
        self.page_index = page_index
        self.mcids.append(mcid)


class StructureTreeBuilder:
    """Serializes a structure tree into PDF objects."""

    def __init__(self, assembler, page_refs: list):
        self.assembler = assembler
        self.page_refs = page_refs
        # page index -> list of (mcid, element_ref)
        self._parent_entries: dict = {}
        # (struct_parent_key, element_ref) pairs for annotations
        self._annot_entries: list = []
        # (element_id, element_ref) pairs for the /IDTree name tree
        self._id_entries: list = []
        # base node id -> count, for disambiguating split-block duplicates
        self._id_seen: dict = {}

    def build(self, root: StructureElement) -> tuple:
        """Write the tree. Returns (struct_tree_root_ref, parent_tree_counts).

        The second value is the next available /StructParents key per page,
        which the page dictionaries need.
        """
        tree_root_id = self.assembler.allocate()
        tree_root_ref = PdfRef(tree_root_id)

        root_ref = self._write_element(root, tree_root_ref)

        parent_tree_ref = self._write_parent_tree()

        struct_root = PdfDict()
        struct_root["Type"] = PdfName("StructTreeRoot")
        struct_root["K"] = PdfArray([root_ref])
        struct_root["ParentTree"] = parent_tree_ref
        struct_root["ParentTreeNextKey"] = len(self.page_refs) + len(
            self._annot_entries
        )

        role_map = PdfDict()
        for tag, role in _ROLE_MAP.items():
            role_map[tag] = PdfName(role)
        struct_root["RoleMap"] = role_map

        id_tree_ref = self._write_id_tree()
        if id_tree_ref is not None:
            struct_root["IDTree"] = id_tree_ref

        self.assembler.add(struct_root, obj_id=tree_root_id)
        return tree_root_ref

    def _unique_id(self, node_id: str) -> str:
        """Return node_id, suffixing repeats so every /ID is tree-unique."""
        count = self._id_seen.get(node_id, 0)
        self._id_seen[node_id] = count + 1
        return node_id if count == 0 else f"{node_id}~{count}"

    def _write_id_tree(self) -> PdfRef | None:
        """Write the /IDTree name tree mapping element ids to StructElems."""
        if not self._id_entries:
            return None
        ordered = sorted(self._id_entries, key=lambda pair: pair[0])
        names = PdfArray()
        for uid, ref in ordered:
            names.append(PdfString(uid))
            names.append(ref)
        id_tree = PdfDict()
        id_tree["Names"] = names
        id_tree["Limits"] = PdfArray(
            [PdfString(ordered[0][0]), PdfString(ordered[-1][0])]
        )
        return self.assembler.add(id_tree)

    def _write_element(self, element: StructureElement, parent_ref: PdfRef) -> PdfRef:
        obj_id = self.assembler.allocate()
        element.obj_id = obj_id
        self_ref = PdfRef(obj_id)

        node = PdfDict()
        node["Type"] = PdfName("StructElem")
        node["S"] = PdfName(element.tag)
        node["P"] = parent_ref

        kids = PdfArray()

        # Marked content on the page this element occupies.
        if element.mcids and element.page_index is not None:
            node["Pg"] = self.page_refs[element.page_index]
            for mcid in element.mcids:
                kids.append(mcid)
                self._parent_entries.setdefault(element.page_index, []).append(
                    (mcid, self_ref)
                )

        if element.annot_ref is not None:
            if "Pg" not in node and element.page_index is not None:
                node["Pg"] = self.page_refs[element.page_index]
            objr = PdfDict()
            objr["Type"] = PdfName("OBJR")
            objr["Obj"] = element.annot_ref
            kids.append(objr)
            if element.struct_parent is not None:
                self._annot_entries.append((element.struct_parent, self_ref))

        for child in element.children:
            kids.append(self._write_element(child, self_ref))

        if len(kids):
            node["K"] = kids if len(kids) > 1 else kids.items[0]

        if element.node_id:
            uid = self._unique_id(element.node_id)
            node["ID"] = PdfString(uid)
            self._id_entries.append((uid, self_ref))
        if element.alt_text:
            node["Alt"] = element.alt_text
        if element.actual_text:
            node["ActualText"] = element.actual_text
        if element.title:
            node["T"] = element.title
        if element.scope:
            node["Scope"] = PdfName(element.scope)
        if element.colspan and element.colspan > 1:
            attrs = PdfDict()
            attrs["O"] = PdfName("Table")
            attrs["ColSpan"] = element.colspan
            node["A"] = attrs
        if element.af_refs:
            node["AF"] = PdfArray(list(element.af_refs))

        self.assembler.add(node, obj_id=obj_id)
        return self_ref

    def _write_parent_tree(self) -> PdfRef:
        """Write the number tree mapping /StructParents keys to elements."""
        numbers = PdfArray()
        for page_index in range(len(self.page_refs)):
            entries = self._parent_entries.get(page_index, [])
            # Order by MCID: readers index into this array positionally.
            entries.sort(key=lambda pair: pair[0])
            refs = PdfArray([ref for _mcid, ref in entries])
            numbers.append(page_index)
            numbers.append(refs)

        for key, ref in sorted(self._annot_entries, key=lambda pair: pair[0]):
            numbers.append(key)
            numbers.append(ref)

        parent_tree = PdfDict()
        parent_tree["Nums"] = numbers
        return self.assembler.add(parent_tree)
