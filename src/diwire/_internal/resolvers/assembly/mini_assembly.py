from __future__ import annotations

import re
from dataclasses import dataclass

_IDENTIFIER_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_EQUALITY_PATTERN = re.compile(
    r'^(?P<identifier>[A-Za-z_][A-Za-z0-9_]*)\s*==\s*"(?P<literal>[^"]*)"$',
)


@dataclass(frozen=True, slots=True)
class _TextToken:
    value: str


@dataclass(frozen=True, slots=True)
class _VariableToken:
    expression: str


@dataclass(frozen=True, slots=True)
class _BlockToken:
    expression: str


_Token = _TextToken | _VariableToken | _BlockToken


@dataclass(frozen=True, slots=True)
class _Condition:
    identifier: str
    expected_literal: str | None


@dataclass(frozen=True, slots=True)
class _TextNode:
    value: str


@dataclass(frozen=True, slots=True)
class _VariableNode:
    identifier: str


@dataclass(frozen=True, slots=True)
class _IfNode:
    condition: _Condition
    truthy_nodes: tuple[_Node, ...]
    falsy_nodes: tuple[_Node, ...]


_Node = _TextNode | _VariableNode | _IfNode


class Environment:
    """Minimal environment with a lightweight block-based interface used by resolver generation."""

    def __init__(self, *, autoescape: bool = False) -> None:
        if autoescape:
            msg = "autoescape=True is not supported by diwire mini_assembly."
            raise ValueError(msg)

    def from_string(self, text: str) -> AssemblySnippet:
        """Compile an assembly string into a renderable assembly snippet object.

        Args:
            text: Assembly source text to compile.

        """
        parser = _Parser(tokens=_tokenize(text))
        return AssemblySnippet(nodes=parser.parse())


class AssemblySnippet:
    """Compiled mini assembly snippet."""

    def __init__(self, *, nodes: tuple[_Node, ...]) -> None:
        self._nodes = nodes

    def render(self, **context: object) -> str:
        """Render an assembly snippet with keyword-only context variables.

        Args:
            context: Optional mapping of context values to bind in the entered scope.

        """
        return _render_nodes(nodes=self._nodes, context=context)


class _Parser:
    def __init__(self, *, tokens: tuple[_Token, ...]) -> None:
        self._tokens = tokens
        self._position = 0

    def parse(self) -> tuple[_Node, ...]:
        nodes, stop_tag = self._parse_nodes(stop_tags=frozenset())
        if stop_tag is not None:
            msg = f"Unexpected block tag '{stop_tag}'."
            raise ValueError(msg)
        return tuple(nodes)

    def _parse_nodes(self, *, stop_tags: frozenset[str]) -> tuple[list[_Node], str | None]:
        nodes: list[_Node] = []

        while self._position < len(self._tokens):
            token = self._tokens[self._position]

            if isinstance(token, _TextToken):
                nodes.append(_TextNode(value=token.value))
                self._position += 1
                continue

            if isinstance(token, _VariableToken):
                nodes.append(
                    _VariableNode(
                        identifier=_parse_identifier(
                            expression=token.expression,
                            expression_kind="variable",
                        ),
                    ),
                )
                self._position += 1
                continue

            tag = token.expression
            if tag in stop_tags:
                self._position += 1
                return nodes, tag

            if tag in {"else", "endif"}:
                msg = f"Unexpected block tag '{tag}'."
                raise ValueError(msg)

            if tag.startswith("if "):
                self._position += 1
                condition = _parse_condition(expression=tag[3:].strip())
                truthy_nodes, stop_tag = self._parse_nodes(
                    stop_tags=frozenset({"else", "endif"}),
                )
                if stop_tag is None:
                    msg = "Unclosed if block: missing endif."
                    raise ValueError(msg)

                falsy_nodes: tuple[_Node, ...] = ()
                if stop_tag == "else":
                    branch_nodes, else_stop = self._parse_nodes(stop_tags=frozenset({"endif"}))
                    if else_stop != "endif":
                        msg = "Unclosed if block: missing endif."
                        raise ValueError(msg)
                    falsy_nodes = tuple(branch_nodes)

                nodes.append(
                    _IfNode(
                        condition=condition,
                        truthy_nodes=tuple(truthy_nodes),
                        falsy_nodes=falsy_nodes,
                    ),
                )
                continue

            msg = f"Unsupported assembly tag '{tag}'."
            raise ValueError(msg)

        return nodes, None


def _tokenize(text: str) -> tuple[_Token, ...]:
    tokens: list[_Token] = []
    cursor = 0
    text_length = len(text)

    while cursor < text_length:
        next_tag = _find_next_tag(text=text, cursor=cursor)
        if next_tag is None:
            tokens.append(_TextToken(value=text[cursor:]))
            break

        tag_start, tag_kind = next_tag
        if tag_start > cursor:
            tokens.append(_TextToken(value=text[cursor:tag_start]))

        if tag_kind == "variable":
            end = text.find("}}", tag_start + 2)
            if end == -1:
                msg = "Unclosed variable tag."
                raise ValueError(msg)
            expression = text[tag_start + 2 : end].strip()
            if not expression:
                msg = "Variable tag cannot be empty."
                raise ValueError(msg)
            tokens.append(_VariableToken(expression=expression))
            cursor = end + 2
            continue

        end = text.find("%}", tag_start + 2)
        if end == -1:
            msg = "Unclosed block tag."
            raise ValueError(msg)
        expression = text[tag_start + 2 : end].strip()
        if not expression:
            msg = "Block tag cannot be empty."
            raise ValueError(msg)
        tokens.append(_BlockToken(expression=expression))
        cursor = end + 2

    return tuple(tokens)


def _find_next_tag(*, text: str, cursor: int) -> tuple[int, str] | None:
    variable_start = text.find("{{", cursor)
    block_start = text.find("{%", cursor)

    if variable_start == -1 and block_start == -1:
        return None
    if variable_start == -1:
        return block_start, "block"
    if block_start == -1:
        return variable_start, "variable"
    if variable_start < block_start:
        return variable_start, "variable"
    return block_start, "block"


def _parse_identifier(*, expression: str, expression_kind: str) -> str:
    if _IDENTIFIER_PATTERN.fullmatch(expression):
        return expression
    msg = f"Unsupported {expression_kind} expression '{expression}'."
    raise ValueError(msg)


def _parse_condition(*, expression: str) -> _Condition:
    equality_match = _EQUALITY_PATTERN.fullmatch(expression)
    if equality_match is not None:
        return _Condition(
            identifier=equality_match.group("identifier"),
            expected_literal=equality_match.group("literal"),
        )

    if _IDENTIFIER_PATTERN.fullmatch(expression):
        return _Condition(identifier=expression, expected_literal=None)

    msg = f"Unsupported if condition '{expression}'."
    raise ValueError(msg)


def _render_nodes(*, nodes: tuple[_Node, ...], context: dict[str, object]) -> str:
    rendered_parts: list[str] = []

    for node in nodes:
        if isinstance(node, _TextNode):
            rendered_parts.append(node.value)
            continue

        if isinstance(node, _VariableNode):
            rendered_parts.append(
                str(_resolve_context_value(context=context, identifier=node.identifier)),
            )
            continue

        condition_matched = _evaluate_condition(condition=node.condition, context=context)
        branch = node.truthy_nodes if condition_matched else node.falsy_nodes
        rendered_parts.append(_render_nodes(nodes=branch, context=context))

    return "".join(rendered_parts)


def _resolve_context_value(*, context: dict[str, object], identifier: str) -> object:
    if identifier not in context:
        msg = f"Missing assembly variable '{identifier}'."
        raise ValueError(msg)
    return context[identifier]


def _evaluate_condition(*, condition: _Condition, context: dict[str, object]) -> bool:
    value = _resolve_context_value(context=context, identifier=condition.identifier)
    if condition.expected_literal is None:
        return bool(value)
    return value == condition.expected_literal
