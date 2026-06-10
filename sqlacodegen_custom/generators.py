from __future__ import annotations

import re
from typing import ClassVar

from sqlacodegen.generators import DeclarativeGenerator
from sqlacodegen.models import ColumnAttribute, Model, ModelClass, RelationshipAttribute, RelationshipType
from sqlalchemy.sql.sqltypes import DateTime

_CAMEL_1 = re.compile(r"(.)([A-Z][a-z]+)")
_CAMEL_2 = re.compile(r"([a-z0-9])([A-Z])")
_MULTI_UNDERSCORE = re.compile(r"__+")


def to_snake(name: str) -> str:
    """
    Convert camelCase / PascalCase / mixedCase identifiers to snake_case.
    Examples:
      memberId -> member_id
      OrganizationMember -> organization_member
      revokeReason -> revoke_reason
      IPAddress -> ip_address
    """
    name = name.strip()
    if not name:
        return name

    name = name.replace("-", "_")
    name = _CAMEL_1.sub(r"\1_\2", name)
    name = _CAMEL_2.sub(r"\1_\2", name)
    name = _MULTI_UNDERSCORE.sub("_", name)
    return name.lower()


def strip_fk_id_suffix(raw: str) -> str | None:
    """
    If the column looks like an FK identifier, return the prefix (without the suffix).
    Supports:
      - *_id
      - *Id
      - *ID
    """
    if raw.endswith("_id"):
        return raw[:-3]
    if raw.endswith("Id") or raw.endswith("ID"):
        return raw[:-2]
    return None


class DeclarativeSnakeCaseGenerator(DeclarativeGenerator):
    """
    Declarative generator that emits snake_case mapped attribute names.

    - Column attributes:
        memberId -> member_id
    - Relationship attributes (when possible, infer from FK column name):
        memberId -> member
        relationId -> relation
        organizationId -> organization
        targetId -> target
    - Adds SoftDeleteMixin to model classes that have both `id` and `deleted_at` columns.
    """

    # same option surface as DeclarativeGenerator
    valid_options: ClassVar[set[str]] = DeclarativeGenerator.valid_options

    MIXIN_IMPORT: ClassVar[str] = "worker.models"
    SOFT_DELETE_MIXIN_NAME: ClassVar[str] = "SoftDeleteMixin"

    def _normalized_column_names(self, model: ModelClass) -> set[str]:
        # Normalize DB column names (e.g., deletedAt -> deleted_at)
        return {to_snake(col.name) for col in model.table.columns}

    def _get_column_by_normalized_name(self, model: ModelClass, name: str):
        for col in model.table.columns:
            if to_snake(col.name) == name:
                return col
        return None

    def _is_soft_delete_model(self, model: ModelClass) -> bool:
        deleted_at_col = self._get_column_by_normalized_name(model, "deleted_at")
        if deleted_at_col is None:
            return False
        # Validate the column type is Optional[datetime.datetime]
        if not isinstance(deleted_at_col.type, DateTime):
            return False
        if not deleted_at_col.nullable:
            return False
        return True

    def _should_add_soft_delete_mixin(self, model: ModelClass) -> bool:
        """
        Avoid `TypeError: duplicate base class SoftDeleteMixin` for joined inheritance:
        if the parent class already has the mixin, don't add it again.
        """
        if model.parent_class and self._is_soft_delete_model(model.parent_class):
            return False
        return self._is_soft_delete_model(model)

    def generate_column_attr_name(
        self,
        column_attr: ColumnAttribute,
        global_names: set[str],
        local_names: set[str],
    ) -> None:
        preferred = to_snake(column_attr.column.name)
        column_attr.name = self.find_free_name(preferred, global_names, local_names)

    def generate_relationship_name(
        self,
        relationship: RelationshipAttribute,
        global_names: set[str],
        local_names: set[str],
    ) -> None:
        # Keep upstream self-referential reverse naming logic, but snake_case it later
        preferred_name: str
        if (
            relationship.type in (RelationshipType.ONE_TO_MANY, RelationshipType.ONE_TO_ONE)
            and relationship.source is relationship.target
            and relationship.backref
            and relationship.backref.name
        ):
            preferred_name = f"{relationship.backref.name}_reverse"
        else:
            preferred_name = relationship.target.table.name

            # Prefer FK column-derived name for the "owning" side (and for M2O / O2O),
            # extending upstream *_id logic to also handle *Id / *ID.
            if relationship.constraint and "noidsuffix" not in self.options:
                is_source = relationship.source.table is relationship.constraint.table
                if is_source or relationship.type not in (
                    RelationshipType.ONE_TO_ONE,
                    RelationshipType.ONE_TO_MANY,
                ):
                    column_names = [c.name for c in relationship.constraint.columns]
                    if len(column_names) == 1:
                        base = strip_fk_id_suffix(column_names[0])
                        if base:
                            preferred_name = base

        # Convert to snake_case before uniqueness checks
        preferred_name = to_snake(preferred_name).strip("_")

        # Preserve upstream "use_inflect" behavior, but make it snake-friendly by
        # pluralizing/singularizing only the last segment.
        if "use_inflect" in self.options and preferred_name:
            parts = preferred_name.split("_")
            last = parts[-1]

            if relationship.type in (RelationshipType.ONE_TO_MANY, RelationshipType.MANY_TO_MANY):
                # plural
                if not self.inflect_engine.singular_noun(last):  # type: ignore # inflect stubs are incomplete
                    plural = self.inflect_engine.plural_noun(last)  # type: ignore # inflect stubs are incomplete
                    if plural:
                        last = plural
            else:
                # singular
                singular = self.inflect_engine.singular_noun(last)  # type: ignore # inflect stubs are incomplete
                if singular:
                    last = singular

            preferred_name = "_".join(parts[:-1] + [last])

        relationship.name = self.find_free_name(preferred_name, global_names, local_names)

    def collect_imports_for_model(self, model: Model) -> None:
        super().collect_imports_for_model(model)
        if isinstance(model, ModelClass) and self._should_add_soft_delete_mixin(model):
            self.add_literal_import(self.MIXIN_IMPORT, self.SOFT_DELETE_MIXIN_NAME)

    def render_class_declaration(self, model: ModelClass) -> str:
        parent_class_name = model.parent_class.name if model.parent_class else self.base_class_name

        bases = [parent_class_name]
        if self._should_add_soft_delete_mixin(model):
            bases.insert(0, self.SOFT_DELETE_MIXIN_NAME)

        return f"class {model.name}({', '.join(bases)}):"
