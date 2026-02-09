from __future__ import annotations

import pytest

from diwire.resolvers.templates.mini_jinja import Environment


def test_variable_interpolation_renders_context_value() -> None:
    template = Environment().from_string("hello {{ name }}")

    rendered = template.render(name="world")

    assert rendered == "hello world"


def test_if_condition_uses_truthy_branch() -> None:
    template = Environment().from_string("{% if is_enabled %}yes{% endif %}")

    rendered = template.render(is_enabled=True)

    assert rendered == "yes"


def test_if_condition_uses_falsy_branch() -> None:
    template = Environment().from_string("{% if is_enabled %}yes{% else %}no{% endif %}")

    rendered = template.render(is_enabled=False)

    assert rendered == "no"


def test_if_equality_condition_matches_literal() -> None:
    template = Environment().from_string('{% if mode == "async" %}ok{% else %}skip{% endif %}')

    rendered = template.render(mode="async")

    assert rendered == "ok"


def test_if_equality_condition_does_not_match_literal() -> None:
    template = Environment().from_string('{% if mode == "async" %}ok{% else %}skip{% endif %}')

    rendered = template.render(mode="thread")

    assert rendered == "skip"


def test_nested_if_blocks_render_expected_branch() -> None:
    template = Environment().from_string(
        "{% if outer %}A{% if inner %}B{% else %}C{% endif %}{% else %}D{% endif %}",
    )

    rendered = template.render(outer=True, inner=False)

    assert rendered == "AC"


def test_environment_rejects_autoescape_true() -> None:
    with pytest.raises(ValueError, match="autoescape=True"):
        Environment(autoescape=True)


def test_parser_rejects_unknown_block_tag() -> None:
    with pytest.raises(ValueError, match="Unsupported template tag"):
        Environment().from_string("{% for item in items %}{{ item }}{% endfor %}")


def test_parser_rejects_unclosed_if_block() -> None:
    with pytest.raises(ValueError, match="missing endif"):
        Environment().from_string("{% if condition %}x")


def test_parser_rejects_unclosed_if_block_with_else_branch() -> None:
    with pytest.raises(ValueError, match="missing endif"):
        Environment().from_string("{% if condition %}x{% else %}y")


def test_parser_rejects_unexpected_else_block() -> None:
    with pytest.raises(ValueError, match="Unexpected block tag 'else'"):
        Environment().from_string("{% else %}")


def test_parser_rejects_unclosed_variable_tag() -> None:
    with pytest.raises(ValueError, match="Unclosed variable tag"):
        Environment().from_string("{{ value")


def test_render_raises_for_missing_variable() -> None:
    template = Environment().from_string("{{ value }}")

    with pytest.raises(ValueError, match="Missing template variable 'value'"):
        template.render()


def test_render_raises_for_missing_if_condition_variable() -> None:
    template = Environment().from_string("{% if is_enabled %}yes{% endif %}")

    with pytest.raises(ValueError, match="Missing template variable 'is_enabled'"):
        template.render()


def test_parser_rejects_unsupported_variable_expression() -> None:
    with pytest.raises(ValueError, match="Unsupported variable expression"):
        Environment().from_string("{{ value.name }}")


def test_parser_rejects_unsupported_if_condition_expression() -> None:
    with pytest.raises(ValueError, match="Unsupported if condition"):
        Environment().from_string('{% if mode != "async" %}x{% endif %}')
