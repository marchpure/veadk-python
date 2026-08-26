from pathlib import Path

from frontend.server.knowledge_assets.html_acceptance import (
    acceptance_models,
    write_acceptance_site,
)
from frontend.server.knowledge_assets.trusted_renderers import (
    RENDERER_VERSION,
    compile_with_visual_feedback,
    render_trusted_html,
)
from frontend.server.knowledge_assets.design_system import (
    evaluate_html,
    tokens_for,
)


def test_all_formal_bundles_have_required_assets() -> None:
    root = (
        Path(__file__).parents[3] / "frontend/server/knowledge_assets/template_bundles"
    )
    for template in (
        "dashboard",
        "semantic",
        "sop",
        "knowledge",
        "graph-ontology",
        "monitoring",
    ):
        bundle = root / template
        assert all(
            (bundle / name).is_file()
            for name in (
                "SKILL.md",
                "DESIGN.md",
                "template.html",
                "example.html",
                "checklist.md",
                "manifest.json",
                "visual-profile.json",
            )
        )


def test_compiler_emits_professional_typed_views_without_executable_surface() -> None:
    for template, model in acceptance_models().items():
        output = render_trusted_html(
            template, model, data_revision_refs=["fixture-revision-7"]
        ).decode()
        assert f'data-template="{template}"' in output
        assert 'data-view-model-digest="' in output
        assert 'data-data-revisions="fixture-revision-7"' in output
        assert f'data-renderer-version="{RENDERER_VERSION}"' in output
        assert "<pre" not in output.lower()
        assert "<script" not in output.lower()
        assert "<iframe" not in output.lower()
        assert "data-artifact-event=" in output
        assert 'data-direction="' in output
        assert 'class="state-coverage"' in output
        if template == "dashboard":
            assert "<svg" in output
        if template == "monitoring":
            assert "monitor-log-panel" in output
        if template == "graph-ontology":
            assert "<svg" in output and "data-node-id=" in output
        if template == "sop":
            assert "step-card" in output and "evidence-list" in output


def test_acceptance_site_is_self_contained(tmp_path: Path) -> None:
    site = write_acceptance_site(tmp_path / "site")
    assert (site / "index.html").is_file()
    assert len(list(site.glob("*.html"))) == 13
    assert (site / "visual-evaluation.json").is_file()


def test_directions_change_presentation_but_preserve_typed_facts() -> None:
    model = acceptance_models()["dashboard"]
    executive = render_trusted_html("dashboard", model, direction="executive").decode()
    editorial = render_trusted_html("dashboard", model, direction="editorial").decode()
    assert executive != editorial
    assert "184" in executive and "184" in editorial
    assert "font-display" in editorial
    assert "direction-executive" in executive
    assert "direction-editorial" in editorial


def test_visual_evaluator_scores_real_fixture_and_reports_weak_structure() -> None:
    model = acceptance_models()["dashboard"]
    output = render_trusted_html("dashboard", model, direction="executive").decode()
    score = evaluate_html("dashboard", model, output, "executive")
    assert score.core_pass
    assert score.overall >= 4
    assert (
        tokens_for("editorial").font_display != tokens_for("operational").font_display
    )
    weak = evaluate_html("dashboard", model, "<main>tiny</main>", "executive")
    assert not weak.core_pass
    assert weak.reasons


def test_compile_feedback_is_bounded_and_records_choice() -> None:
    result = compile_with_visual_feedback(
        "dashboard", acceptance_models()["dashboard"], direction="executive"
    )
    assert result.html
    assert len(result.attempts) <= 3
    assert result.attempts[0].direction == "executive"
    assert result.attempts[0].score >= 4
    assert result.direction == "executive"
