"""Block template presets: every one loads, renders and has its own slug."""

from alpha_harness.labs import template_blocks as t


def test_every_preset_loads_and_renders() -> None:
    assert len({p.slug for p in t.PRESETS}) == len(t.PRESETS)
    for preset in t.PRESETS:
        doc = t.load(preset.doc)
        skeleton = t.skeleton(doc)
        assert skeleton and "FIELD A" in skeleton, preset.slug
